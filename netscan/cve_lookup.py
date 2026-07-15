"""Cruce de servicios detectados con vulnerabilidades conocidas (NVD 2.0).

Módulo 4: "base de datos de CVEs que se actualiza". Consulta la API oficial
del NIST (National Vulnerability Database) por producto+versión y cachea los
resultados en SQLite local para no repetir llamadas ni depender de estar online.

- Sin API key funciona (5 req / 30 s). Con NVD_API_KEY sube a 50 req / 30 s.
- El cache tiene TTL: pasado el plazo, vuelve a consultar (así se "actualiza").

NVD NO ejecuta nada contra los dispositivos: solo informa de qué CVEs afectan
al producto/versión. Es diagnóstico, no explotación.
"""
from __future__ import annotations

import json
import os
import sqlite3
import time
from datetime import datetime, timedelta
from pathlib import Path

import requests

NVD_URL = "https://services.nvd.nist.gov/rest/json/cves/2.0"
API_KEY = os.environ.get("NVD_API_KEY")
CACHE_TTL_DAYS = 7
JARVIS_ROOT = Path(os.environ.get("JARVIS_ROOT", r"C:\Users\Usuario\jarvis"))
DB_PATH = JARVIS_ROOT / "netscan" / "cve_cache.db"


def _db() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS cve_cache (
            query TEXT PRIMARY KEY,
            fetched_at TEXT,
            payload TEXT
        )""")
    return conn


def _cache_get(query: str) -> list[dict] | None:
    conn = _db()
    try:
        row = conn.execute(
            "SELECT fetched_at, payload FROM cve_cache WHERE query=?", (query,)
        ).fetchone()
    finally:
        conn.close()
    if not row:
        return None
    fetched = datetime.fromisoformat(row[0])
    if datetime.now() - fetched > timedelta(days=CACHE_TTL_DAYS):
        return None
    return json.loads(row[1])


def _cache_put(query: str, data: list[dict]) -> None:
    conn = _db()
    try:
        conn.execute(
            "INSERT OR REPLACE INTO cve_cache VALUES (?,?,?)",
            (query, datetime.now().isoformat(), json.dumps(data, ensure_ascii=False)),
        )
        conn.commit()
    finally:
        conn.close()


def _parse_cvss(metrics: dict) -> tuple[float | None, str]:
    for key in ("cvssMetricV31", "cvssMetricV30", "cvssMetricV2"):
        if key in metrics and metrics[key]:
            data = metrics[key][0]["cvssData"]
            score = data.get("baseScore")
            sev = data.get("baseSeverity") or _sev_from_score(score)
            return score, sev
    return None, "UNKNOWN"


def _sev_from_score(score: float | None) -> str:
    if score is None:
        return "UNKNOWN"
    if score >= 9:
        return "CRITICAL"
    if score >= 7:
        return "HIGH"
    if score >= 4:
        return "MEDIUM"
    return "LOW"


def _query_nvd(keyword: str, limit: int = 20) -> list[dict]:
    headers = {"apiKey": API_KEY} if API_KEY else {}
    params = {"keywordSearch": keyword, "resultsPerPage": limit}
    try:
        resp = requests.get(NVD_URL, params=params, headers=headers, timeout=30)
        if resp.status_code == 403:
            time.sleep(6)  # rate limit sin key
            resp = requests.get(NVD_URL, params=params, headers=headers, timeout=30)
        resp.raise_for_status()
        raw = resp.json()
    except (requests.RequestException, ValueError) as exc:
        return [{"_error": str(exc)}]

    out = []
    for item in raw.get("vulnerabilities", []):
        cve = item.get("cve", {})
        score, sev = _parse_cvss(cve.get("metrics", {}))
        desc = ""
        for d in cve.get("descriptions", []):
            if d.get("lang") == "en":
                desc = d.get("value", "")
                break
        out.append({
            "id": cve.get("id"),
            "cvss": score,
            "severity": sev,
            "summary": desc[:240],
        })
    out.sort(key=lambda c: c.get("cvss") or 0, reverse=True)
    return out


def lookup(vendor: str, product: str, version: str = "") -> list[dict]:
    """Devuelve CVEs para vendor/product/version. Usa cache con TTL."""
    terms = " ".join(t for t in (vendor, product, version) if t).strip()
    if not terms:
        return []
    cached = _cache_get(terms)
    if cached is not None:
        return cached
    result = _query_nvd(terms)
    if result and "_error" not in result[0]:
        _cache_put(terms, result)
    return result


def lookup_for_host(host: dict, max_products: int = 4) -> list[dict]:
    """Consulta CVEs para los servicios con producto/versión identificados."""
    seen, findings = set(), []
    vendor = host.get("vendor") or ""
    for port in host.get("ports", []):
        product = port.get("product") or ""
        version = port.get("version") or ""
        if not product:
            continue
        key = (product, version)
        if key in seen:
            continue
        seen.add(key)
        cves = lookup(vendor if vendor else product, product, version)
        real = [c for c in cves if "_error" not in c]
        if real:
            findings.append({
                "port": port["port"], "product": product, "version": version,
                "cves": real[:8],
            })
        if len(seen) >= max_products:
            break
    return findings


if __name__ == "__main__":
    import sys
    v, p, ver = (sys.argv[1:4] + ["", "", ""])[:3]
    for c in lookup(v, p, ver)[:10]:
        print(c.get("id"), c.get("severity"), c.get("cvss"), "-", c.get("summary", "")[:80])
