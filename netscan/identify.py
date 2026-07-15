"""Identificación de dispositivos: fabricante (OUI/MAC) + tipo por huella.

El tipo se infiere con heurística sobre puertos y servicios abiertos.
No es infalible (una cámara puede exponer sólo HTTP), pero orienta bien
el informe y la posterior consulta de CVEs.
"""
from __future__ import annotations

# Firmas de tipo de dispositivo por puerto/servicio.
# Cada entrada: (conjunto de puertos indicativos, palabras clave de servicio, tipo)
TYPE_SIGNATURES = [
    ({554, 8554, 37777, 34567, 8000}, {"rtsp", "dahua", "hikvision", "onvif"}, "cámara IP / DVR"),
    ({9100, 515, 631}, {"jetdirect", "printer", "ipp"}, "impresora"),
    ({80, 443, 7547, 53}, {"router", "gateway", "mikrotik", "openwrt", "tr-069"}, "router / gateway"),
    ({445, 139, 3389}, {"microsoft-ds", "netbios", "ms-wbt"}, "PC Windows"),
    ({22}, {"ssh"}, "host Linux/Unix"),
    ({1883, 8883}, {"mqtt"}, "dispositivo IoT"),
    ({32400, 8096, 5000}, {"plex", "jellyfin", "synology"}, "NAS / media server"),
    ({23}, {"telnet"}, "dispositivo con Telnet (riesgo)"),
]

# Prefijos OUI frecuentes en cámaras/IoT como pista extra (fabricante conocido).
CAMERA_VENDORS = {"hangzhou hikvision", "dahua", "zhejiang dahua", "reolink",
                  "amcrest", "foscam", "ezviz", "tp-link", "wyze"}


def _match_type(ports: list[dict], vendor: str | None) -> str:
    open_ports = {p["port"] for p in ports}
    services = {(p.get("service") or "").lower() for p in ports}
    services |= {(p.get("product") or "").lower() for p in ports}
    blob = " ".join(services)

    vend = (vendor or "").lower()
    if any(cv in vend for cv in CAMERA_VENDORS):
        return "cámara IP / DVR"

    best = None
    for sig_ports, sig_kw, label in TYPE_SIGNATURES:
        score = len(open_ports & sig_ports)
        score += sum(1 for kw in sig_kw if kw in blob)
        if score and (best is None or score > best[0]):
            best = (score, label)
    return best[1] if best else "desconocido"


def _risk_flags(ports: list[dict]) -> list[str]:
    """Riesgos evidentes sin necesidad de CVE (config insegura)."""
    flags = []
    open_ports = {p["port"] for p in ports}
    services = {(p.get("service") or "").lower() for p in ports}
    if 23 in open_ports or "telnet" in services:
        flags.append("Telnet abierto (protocolo sin cifrar)")
    if 21 in open_ports or "ftp" in services:
        flags.append("FTP abierto (credenciales en claro)")
    if 445 in open_ports:
        flags.append("SMB expuesto (445)")
    if 3389 in open_ports:
        flags.append("RDP expuesto (3389)")
    if {554, 8554} & open_ports:
        flags.append("RTSP expuesto (posible acceso a vídeo)")
    return flags


def enrich(hosts: list[dict]) -> list[dict]:
    """Añade device_type y risk_flags a cada host descubierto."""
    for h in hosts:
        h["device_type"] = _match_type(h.get("ports", []), h.get("vendor"))
        h["risk_flags"] = _risk_flags(h.get("ports", []))
    return hosts
