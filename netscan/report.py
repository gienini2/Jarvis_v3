"""Network scan orchestration, Telegram notification, and document reports."""
from __future__ import annotations

import json
import logging
import os
from datetime import datetime
from pathlib import Path

import requests

from netscan import assessment, cve_lookup, discover, identify

log = logging.getLogger("jarvis.netscan")

RELAY_URL = os.environ.get("RELAY_URL", "http://100.78.43.76:10004")
REPORTS_DIR = (
    Path(os.environ.get("JARVIS_ROOT", r"C:\Users\Usuario\jarvis"))
    / "netscan"
    / "reports"
)

SEV_ICON = {
    "CRITICAL": "🔴 CRÍTICA",
    "HIGH": "🟠 ALTA",
    "MEDIUM": "🟡 MEDIA",
    "LOW": "🔵 BAJA",
    "UNKNOWN": "⚪ ?",
}
SEV_ORDER = {"CRITICAL": 0, "HIGH": 1, "MEDIUM": 2, "LOW": 3, "UNKNOWN": 4}


def _device_emoji(device_type: str) -> str:
    """Emoji segun el tipo de dispositivo, para el informe de Telegram."""
    t = (device_type or "").lower()
    if "router" in t or "gateway" in t:
        return "📶"
    if any(k in t for k in ("pc", "windows", "linux", "mac", "server", "servidor")):
        return "💻"
    if any(k in t for k in ("camera", "cámara", "camara", "dvr", "nvr")):
        return "📷"
    if "print" in t or "impresora" in t:
        return "🖨️"
    if any(k in t for k in ("phone", "móvil", "movil", "android", "iphone")):
        return "📱"
    if "tv" in t or "media" in t or "cast" in t:
        return "📺"
    return "🔷"


def run_scan(
    site_name: str | None = None,
    subnet: str | None = None,
    fast: bool = False,
    with_cve: bool = True,
    notify: bool = True,
    authorize_vuln_scan: bool = False,
    authorization_note: str | None = None,
    with_synthesis: bool | None = None,
    nse_scripts: str | None = None,
    with_udp: bool = False,
    host_discovery: str = "default",
    timing: int = 4,
    with_traceroute: bool = False,
    with_os: bool = False,
) -> dict:
    os.environ["PYTHONUTF8"] = "1"
    active_allowed = authorize_vuln_scan and bool((authorization_note or "").strip())
    # None = auto: sintetiza salvo en escaneos rapidos (para no ralentizarlos).
    do_synthesis = (not fast) if with_synthesis is None else with_synthesis

    disc = discover.discover(
        subnet,
        fast=fast,
        nse_scripts=nse_scripts,
        with_udp=with_udp,
        host_discovery=host_discovery,
        timing=timing,
        with_traceroute=with_traceroute,
        with_os=with_os,
    )
    hosts = identify.enrich(disc["hosts"])

    if with_cve:
        for host in hosts:
            host["cve_findings"] = cve_lookup.lookup_for_host(host)
    else:
        for host in hosts:
            host["cve_findings"] = []

    if active_allowed:
        assessment.assess_hosts(hosts)
    else:
        reason = "authorization_required"
        if authorize_vuln_scan and not active_allowed:
            reason = "authorization_note_required"
        for host in hosts:
            host["active_assessment"] = assessment.skipped_assessment(reason)

    scan_report = {
        "timestamp": datetime.now().isoformat(timespec="seconds"),
        "site_name": _clean_site_name(site_name),
        "subnet": disc["subnet"],
        "backend": disc["backend"],
        "warning": disc.get("warning", ""),
        "host_count": len(hosts),
        "vulnerability_assessment": {
            "authorized": active_allowed,
            "authorization_note": authorization_note,
            "mode": "non_intrusive_reachability" if active_allowed else "not_run",
        },
        "hosts": hosts,
        "summary": _summary(hosts),
        "scan_params": {
            "fast": fast,
            "nse_scripts": nse_scripts,
            "with_udp": with_udp,
            "host_discovery": host_discovery,
            "timing": timing,
            "with_traceroute": with_traceroute,
            "with_os": with_os,
        },
    }
    scan_report["analysis"] = _synthesize(scan_report) if do_synthesis else ""
    _save(scan_report)
    if notify:
        _notify_telegram(format_text(scan_report))
    return scan_report


def _synthesize(scan_report: dict) -> str:
    """Analisis en lenguaje natural del escaneo, redactado por el mejor modelo
    disponible via el router de Jarvis (intent='reasoning' -> Groq/DeepSeek/
    Nemotron, con qwen local solo como ultimo recurso). El escaneo en si es
    determinista; esto solo interpreta el resultado. Nunca debe romper el
    informe: si el LLM falla, se devuelve cadena vacia."""
    try:
        from core.llm import generate  # import perezoso: evita coste/ciclos al importar el modulo
    except Exception as exc:  # pragma: no cover - entorno sin core.llm
        log.warning("netscan: core.llm no disponible, sin sintesis (%s)", exc)
        return ""

    payload = _synthesis_payload(scan_report)
    prompt = (
        "Eres un analista de seguridad de redes. Tienes el resultado de un escaneo "
        "DEFENSIVO de la red local de Juan Pablo (solo su propia red).\n\n"
        "FORMATO DE SALIDA (MUY IMPORTANTE): el texto se envía por Telegram, que NO "
        "renderiza markdown. Está PROHIBIDO usar tablas, el caracter '|', almohadillas "
        "'#', asteriscos '**' o bloques de código. Escribe SOLO texto plano en "
        "castellano, líneas cortas, usando emojis como viñetas. Estructura así:\n"
        "🔎 Panorama: 1-2 líneas (cuántos dispositivos y de qué tipo).\n"
        "⚠️ Lo que preocupa: una línea por hallazgo real, cada una empezando por su "
        "emoji de gravedad (🔴 crítico, 🟠 alto, 🟡 medio). Incluye dispositivos "
        "expuestos, CVEs críticas/altas relevantes y cámaras/DVR con vídeo accesible.\n"
        "✅ Acciones: lista numerada priorizada, una acción por línea (1) ... 2) ...).\n\n"
        "REGLAS: no inventes datos fuera del JSON. Si no hay hallazgos, dilo claro con "
        "'✅ Sin hallazgos relevantes'. Sé directo, sin relleno. Si una CVE es antigua "
        "(anterior a ~2015) y se ha cruzado solo por nombre de producto sin número de "
        "versión, adviértelo como posible falso positivo, no como crítico confirmado.\n\n"
        f"DATOS DEL ESCANEO (JSON):\n{json.dumps(payload, ensure_ascii=False)}"
    )
    try:
        text = generate(prompt, intent="reasoning")
        return (text or "").strip()
    except Exception as exc:
        log.warning("netscan: sintesis LLM fallo (%s)", exc)
        return ""


def _synthesis_payload(scan_report: dict) -> dict:
    """Estructura compacta para el prompt: solo lo relevante, sin inflar tokens."""
    hosts = []
    for host in sorted(scan_report["hosts"], key=_host_priority):
        hosts.append({
            "ip": host.get("ip"),
            "device_type": host.get("device_type"),
            "vendor": host.get("vendor"),
            "os_guess": host.get("os_guess") or "",
            "ports": [p.get("port") for p in host.get("ports", [])],
            "risk_flags": host.get("risk_flags", []),
            "active_checks": [
                {"name": c.get("name"), "status": c.get("status"), "detail": c.get("detail")}
                for c in host.get("active_assessment", {}).get("checks", [])
            ],
            "top_cves": [
                {"id": c["id"], "severity": c.get("severity"), "cvss": c.get("cvss"),
                 "product": c.get("product")}
                for c in _top_cves(host, limit=5)
            ],
        })
    return {
        "site_name": scan_report.get("site_name"),
        "subnet": scan_report.get("subnet"),
        "host_count": scan_report.get("host_count"),
        "active_assessment_authorized": scan_report.get(
            "vulnerability_assessment", {}).get("authorized", False),
        "summary": scan_report.get("summary"),
        "hosts": hosts,
    }


def _summary(hosts: list[dict]) -> dict:
    sev_counts = {key: 0 for key in SEV_ICON}
    risky_devices = 0
    active_warnings = 0
    for host in hosts:
        if host.get("risk_flags"):
            risky_devices += 1
        for check in host.get("active_assessment", {}).get("checks", []):
            if check.get("status") in {"warning", "review"}:
                active_warnings += 1
        for finding in host.get("cve_findings", []):
            for cve in finding["cves"]:
                sev_counts[cve.get("severity", "UNKNOWN")] += 1
    return {
        "cve_by_severity": sev_counts,
        "devices_with_config_risk": risky_devices,
        "active_assessment_warnings": active_warnings,
    }


def format_text(scan_report: dict) -> str:
    sev = scan_report["summary"]["cve_by_severity"]
    site_name = scan_report.get("site_name") or "unnamed"
    params = scan_report.get("scan_params", {})
    ts = scan_report["timestamp"]
    subnet = scan_report["subnet"]
    host_count = scan_report["host_count"]
    backend = scan_report["backend"]
    warning = (scan_report.get("warning") or "").strip()
    vuln_auth = scan_report["vulnerability_assessment"]["authorized"]

    opts = []
    if params.get("nse_scripts"):
        opts.append("🛡️ vuln/NSE")
    if params.get("with_udp"):
        opts.append("📡 UDP")
    if params.get("with_os"):
        opts.append("💻 SO")
    if params.get("with_traceroute"):
        opts.append("🧭 traceroute")
    if params.get("fast"):
        opts.append("⚡ rápido")
    opts_txt = " · ".join(opts) if opts else "estándar"

    lines = [
        "🛰️ Jarvis NetScan — auditoría de red",
        f"🕒 {ts}",
        f"🌐 {subnet}  ·  🏷️ {site_name}  ·  📶 {host_count} dispositivos  ·  ⚙️ {backend}",
        f"🎚️ Opciones: {opts_txt}",
        (
            f"🔴 {sev['CRITICAL']} críticas  ·  🟠 {sev['HIGH']} altas  ·  "
            f"🟡 {sev['MEDIUM']} medias  ·  🔵 {sev['LOW']} bajas"
        ),
        f"🧪 Evaluación activa: {'✅ autorizada' if vuln_auth else '⏭️ no ejecutada'}",
    ]
    if warning:
        lines.append(f"⚠️ {warning}")
    lines.append("")

    analysis = (scan_report.get("analysis") or "").strip()
    if analysis:
        lines.extend(["🧠 Análisis de Jarvis", analysis, ""])

    lines.append("📋 Dispositivos")
    for host in sorted(scan_report["hosts"], key=_host_priority):
        emoji = _device_emoji(host.get("device_type", ""))
        head = f"{emoji} {host['ip']}  ·  {host.get('device_type', '?')}"
        if host.get("vendor"):
            head += f"  ·  {host['vendor']}"
        lines.append(head)
        if host.get("ports"):
            lines.append(f"   🔌 {_ports_text(host['ports'][:12])}")
        for flag in host.get("risk_flags", []):
            lines.append(f"   ⚠️ {flag}")
        for check in _top_checks(host):
            lines.append(f"   ⚠️ {check['name']}: {check['detail']}")
        for cve in _top_cves(host):
            icon = SEV_ICON.get(cve["severity"], "⚪ ?")
            lines.append(
                f"   {icon}  {cve['id']} (CVSS {cve.get('cvss', '?')})  {cve['product']}"
            )
        if not host.get("risk_flags") and not _top_checks(host) and not _top_cves(host):
            lines.append("   ✅ sin hallazgos")
    if scan_report.get("document_path"):
        lines.extend(["", f"📄 {scan_report['document_path']}"])
    return "\n".join(lines).strip()


def format_markdown(scan_report: dict) -> str:
    sev = scan_report["summary"]["cve_by_severity"]
    auth = scan_report.get("vulnerability_assessment", {})
    site_name = scan_report.get("site_name") or "unnamed"
    config_risk = scan_report["summary"].get("devices_with_config_risk", 0)
    active_warnings = scan_report["summary"].get("active_assessment_warnings", 0)
    nse_count = scan_report["summary"].get("nse_findings_count", 0)
    params = scan_report.get("scan_params", {})
    ts = scan_report["timestamp"]
    subnet = scan_report["subnet"]
    backend = scan_report["backend"]
    host_count = scan_report["host_count"]
    auth_str = "authorized" if auth.get("authorized") else "not run"
    
    lines = [
        "# Jarvis NetScan - network report",
        "",
        f"- Date: {ts}",
        f"- Site name: {site_name}",
        f"- Subnet: {subnet}",
        f"- Backend: {backend}",
        f"- Devices: {host_count}",
        f"- CVEs: critical={sev['CRITICAL']}, high={sev['HIGH']}, medium={sev['MEDIUM']}, low={sev['LOW']}, unknown={sev['UNKNOWN']}",
        f"- Active assessment: {auth_str}",
        f"- NSE scripts: {params.get('nse_scripts') or 'none'}",
        f"- UDP scan: {params.get('with_udp', False)}",
        f"- Host discovery: {params.get('host_discovery', 'default')}",
        f"- Timing: T{params.get('timing', 4)}",
        f"- Traceroute: {params.get('with_traceroute', False)}",
        f"- OS detection: {params.get('with_os', False)}",
        "",
        "## Executive summary",
        "",
        f"- Devices with configuration risk: {config_risk}",
        f"- Active assessment warnings/review items: {active_warnings}",
        f"- NSE script findings: {nse_count}",
        "",
    ]
    # ... resto igual
    analysis = (scan_report.get("analysis") or "").strip()
    if analysis:
        lines.extend(["## Analisis Jarvis", "", analysis, ""])
    lines.extend([
        "## Devices",
        "",
    ])
    for host in sorted(scan_report["hosts"], key=_host_priority):
        lines.extend(_host_markdown(host))
    lines.extend([
        "",
        "## Scope and safety",
        "",
        "This report is defensive and intended for owned or explicitly authorized networks.",
        (
            "The active assessment does not try credentials, exploit CVEs, "
            "or retrieve camera images."
        ),
    ])
    return "\n".join(lines).strip() + "\n"


def _host_markdown(host: dict) -> list[str]:
    lines = [
        f"### {host['ip']} - {host.get('device_type', 'unknown')}",
        "",
        f"- Vendor: {host.get('vendor') or 'unknown'}",
        f"- MAC: {host.get('mac') or 'not available'}",
        f"- OS guess: {host.get('os_guess') or 'not available'}",
        f"- Ports: {_ports_text(host.get('ports', []))}",
    ]
    if host.get("risk_flags"):
        lines.append("- Configuration risks:")
        lines.extend(f"  - {flag}" for flag in host["risk_flags"])
    checks = host.get("active_assessment", {}).get("checks", [])
    if checks:
        lines.append("- Authorized active assessment:")
        lines.extend(
            f"  - [{check.get('status')}] {check.get('name')}: {check.get('detail')}"
            for check in checks
        )
    else:
        lines.append("- Active assessment: not run; explicit authorization required.")
    cves = _top_cves(host, limit=8)
    if cves:
        lines.append("- Relevant CVEs:")
        lines.extend(
            (
                f"  - {cve['id']} ({cve.get('severity', 'UNKNOWN')}, "
                f"CVSS {cve.get('cvss', '?')}): {cve.get('product', '')}"
            )
            for cve in cves
        )
    else:
        lines.append("- Relevant CVEs: no findings with available service data.")
    lines.append("")
    return lines


def _top_cves(host: dict, limit: int = 3) -> list[dict]:
    flat = []
    for finding in host.get("cve_findings", []):
        for cve in finding["cves"]:
            flat.append({**cve, "product": finding["product"]})
    flat.sort(key=lambda item: SEV_ORDER.get(item.get("severity", "UNKNOWN"), 4))
    return flat[:limit]


def _top_checks(host: dict, limit: int = 3) -> list[dict]:
    checks = host.get("active_assessment", {}).get("checks", [])
    priority = {"warning": 0, "review": 1, "info": 2, "ok": 3}
    checks = sorted(checks, key=lambda item: priority.get(item.get("status"), 9))
    return checks[:limit]


def _host_priority(host: dict) -> tuple:
    top = _top_cves(host, 1)
    sev = SEV_ORDER.get(top[0]["severity"], 4) if top else 5
    return (sev, 0 if host.get("risk_flags") else 1, host["ip"])


def _ports_text(ports: list[dict]) -> str:
    if not ports:
        return "no open ports detected"
    parts = []
    for port in ports:
        service = port.get("service") or "tcp"
        product = port.get("product") or ""
        version = port.get("version") or ""
        label = f"{port['port']}/{service}"
        product_text = " ".join(item for item in (product, version) if item)
        if product_text:
            label += f" ({product_text})"
        parts.append(label)
    return ", ".join(parts)


def _clean_site_name(site_name: str | None) -> str:
    if not site_name:
        return "unnamed"
    cleaned = " ".join(str(site_name).strip().split())
    return cleaned[:80] if cleaned else "unnamed"


def _save(scan_report: dict) -> None:
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    stamp = scan_report["timestamp"].replace(":", "-")
    json_path = REPORTS_DIR / f"netscan_{stamp}.json"
    doc_path = REPORTS_DIR / f"netscan_{stamp}.md"
    scan_report["document_path"] = str(doc_path)
    json_path.write_text(
        json.dumps(scan_report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (REPORTS_DIR / "last.json").write_text(
        json.dumps(scan_report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    doc = format_markdown(scan_report)
    doc_path.write_text(doc, encoding="utf-8")
    (REPORTS_DIR / "last.md").write_text(doc, encoding="utf-8")


def load_last() -> dict | None:
    path = REPORTS_DIR / "last.json"
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else None


def _notify_telegram(text: str) -> None:
    headers = {}
    relay_key = os.environ.get("RELAY_API_KEY")
    if relay_key:
        headers["X-Relay-Key"] = relay_key
    try:
        requests.post(
            f"{RELAY_URL}/notify",
            json={"message": text[:3900]},
            headers=headers,
            timeout=10,
        )
    except requests.RequestException:
        pass
