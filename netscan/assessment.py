"""Optional defensive assessment for discovered devices.

This module only performs non-intrusive reachability checks after explicit
authorization. It does not try credentials, exploit CVEs, or retrieve camera
images.
"""
from __future__ import annotations

import socket
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

HTTP_PORTS = {80, 443, 5000, 5357, 8000, 8080, 8443, 8888, 9000}
CAMERA_PORTS = {80, 443, 554, 8000, 8080, 8554, 37777, 34567}
TV_HINT_PORTS = {8008, 8009, 8060, 9080}


def assess_hosts(hosts: list[dict], timeout: float = 1.5) -> list[dict]:
    """Add active_assessment to each host."""
    for host in hosts:
        host["active_assessment"] = assess_host(host, timeout=timeout)
    return hosts


def assess_host(host: dict, timeout: float = 1.5) -> dict:
    ip = host["ip"]
    ports = host.get("ports", [])
    open_ports = {p["port"] for p in ports}
    device_type = _normalize(host.get("device_type") or "")
    checks: list[dict] = []

    for port in sorted(open_ports & HTTP_PORTS):
        checks.append(_check_http(ip, port, timeout))

    if "camara" in device_type or "camera" in device_type or open_ports & CAMERA_PORTS:
        checks.extend(_camera_checks(open_ports))

    if "tele" in device_type or "tv" in device_type or open_ports & TV_HINT_PORTS:
        checks.append({
            "name": "tv_media_surface",
            "status": "review",
            "detail": "TV/cast/media ports were detected. Confirm whether this device should be reachable from this network segment.",
        })

    checks.extend(_baseline_risk_checks(open_ports))
    return {
        "authorized": True,
        "scope": "non_intrusive_reachability",
        "checks": checks,
    }


def skipped_assessment(reason: str = "authorization_required") -> dict:
    return {
        "authorized": False,
        "scope": "not_run",
        "reason": reason,
        "checks": [],
    }


def _camera_checks(open_ports: set[int]) -> list[dict]:
    checks = []
    if open_ports & {554, 8554}:
        checks.append({
            "name": "camera_rtsp_reachable",
            "status": "warning",
            "detail": "RTSP is open. Video may be exposed if streams allow anonymous access or weak credentials are used.",
        })
    if open_ports & {80, 443, 8000, 8080}:
        checks.append({
            "name": "camera_web_reachable",
            "status": "review",
            "detail": "Camera/DVR web interface is reachable. Review firmware, unique password, and network segmentation.",
        })
    if 37777 in open_ports:
        checks.append({
            "name": "dahua_service_exposed",
            "status": "warning",
            "detail": "Port 37777 is open, commonly seen on Dahua/DVR devices. Avoid exposure outside trusted LANs.",
        })
    return checks


def _baseline_risk_checks(open_ports: set[int]) -> list[dict]:
    risky = {
        21: ("ftp_plaintext", "FTP is open; credentials and data may travel in clear text."),
        23: ("telnet_plaintext", "Telnet is open; disable it where possible."),
        445: ("smb_reachable", "SMB is reachable; restrict to trusted hosts and keep patched."),
        3389: ("rdp_reachable", "RDP is reachable; require VPN/MFA and source restrictions."),
        7547: ("tr069_reachable", "TR-069/CWMP is reachable; verify it is not exposed to untrusted segments."),
    }
    checks = []
    for port, (name, detail) in risky.items():
        if port in open_ports:
            checks.append({"name": name, "status": "warning", "detail": detail})
    return checks


def _check_http(ip: str, port: int, timeout: float) -> dict:
    scheme = "https" if port in {443, 8443} else "http"
    url = f"{scheme}://{ip}:{port}/"
    try:
        req = Request(url, headers={"User-Agent": "Jarvis-NetScan/1.0"})
        with urlopen(req, timeout=timeout) as resp:
            status = getattr(resp, "status", None)
            server = resp.headers.get("Server", "")
            auth = resp.headers.get("WWW-Authenticate", "")
    except HTTPError as exc:
        status = exc.code
        server = exc.headers.get("Server", "")
        auth = exc.headers.get("WWW-Authenticate", "")
    except (URLError, TimeoutError, socket.timeout, OSError) as exc:
        return {
            "name": f"http_{port}",
            "status": "info",
            "detail": f"HTTP/HTTPS service detected but root GET did not complete: {type(exc).__name__}.",
        }

    if status in {401, 403} or auth:
        state = "ok"
        detail = f"HTTP {status}: authentication challenge or access block detected."
    elif status and 200 <= status < 400:
        state = "review"
        detail = f"HTTP {status}: root path responds without an authentication challenge."
    else:
        state = "info"
        detail = f"HTTP {status}: inconclusive response."
    if server:
        detail += f" Server: {server[:80]}."
    return {"name": f"http_{port}", "status": state, "detail": detail}


def _normalize(text: str) -> str:
    replacements = {
        "\u00e1": "a", "\u00e9": "e", "\u00ed": "i", "\u00f3": "o", "\u00fa": "u",
        "\u00c3\u00a1": "a", "\u00c3\u00a9": "e", "\u00c3\u00ad": "i",
        "\u00c3\u00b3": "o", "\u00c3\u00ba": "u",
    }
    out = text.lower()
    for src, dst in replacements.items():
        out = out.replace(src, dst)
    return out
