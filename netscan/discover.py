"""Descubrimiento de hosts activos en la red local.

Estrategia por capas (usa la primera disponible):
  1. nmap  -> mejor: descubrimiento + puertos + servicios + versión + OS guess
  2. scapy -> barrido ARP (rápido, requiere Npcap en Windows)
  3. socket puro -> ping + escaneo TCP de puertos comunes (sin dependencias)

Diseñado para el HP Victus (Windows). En Windows, nmap con -sV funciona
sin admin usando 'TCP connect scan'; -O (OS detection) sí requiere admin.
"""
from __future__ import annotations

import ipaddress
import os
import shutil
import socket
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from xml.etree import ElementTree as ET

# Puertos habituales para fingerprinting rápido en el fallback sin nmap.
COMMON_PORTS = [21, 22, 23, 25, 53, 80, 139, 443, 445, 515, 554, 631,
                1883, 3389, 5000, 5357, 6668, 7547, 8000, 8080, 8443,
                8554, 8888, 9000, 9100, 37777, 49152]

# --------------------------------------------------------------------------- #
# Utilidades de red
# --------------------------------------------------------------------------- #
def local_subnet() -> str:
    """Deduce la subred /24 local a partir de la IP de salida."""
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
    except OSError:
        ip = "192.168.1.1"
    finally:
        s.close()
    net = ipaddress.ip_network(f"{ip}/24", strict=False)
    return str(net)


def _tcp_open(ip: str, port: int, timeout: float = 0.6) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(timeout)
        return s.connect_ex((ip, port)) == 0


# --------------------------------------------------------------------------- #
# Backend 1: nmap
# --------------------------------------------------------------------------- #
def _nmap_available() -> bool:
    return shutil.which("nmap") is not None


def _scan_nmap(
    subnet: str,
    fast: bool = False,
    nse_scripts: str | None = None,
    with_udp: bool = False,
    host_discovery: str = "default",
    timing: int = 4,
    with_traceroute: bool = False,
    with_os: bool = False,
) -> list[dict]:
    """Escaneo TCP con nmap. Devuelve lista de hosts o [{'_error': ...}]."""

    # Base args
    args = ["nmap", "-sV", f"-T{timing}", "-oX", "-"]

    # Estrategia de descubrimiento
    discovery_map = {
        "default": [],
        "arp": ["-PR", "-sn"],
        "tcp_syn": ["-PS22,80,443,445"],
        "tcp_ack": ["-PA80,443"],
        "icmp": ["-PE", "-PP"],
        "aggressive": ["-PE", "-PP", "-PS22,80,443", "-PA80,443"],
        "none": ["-Pn"],
    }
    hd_args = discovery_map.get(host_discovery, [])
    if hd_args:
        args.extend(hd_args)

    # Timing / fast
    if fast:
        args.extend(["--version-light", "--top-ports", "50"])
    else:
        args.extend(["--top-ports", "100"])

    # NSE scripts (solo categorías seguras)
    if nse_scripts:
        allowed = {"safe", "default", "vuln", "discovery", "version", "broadcast"}
        requested = set(s.strip() for s in nse_scripts.split(","))
        if requested.issubset(allowed):
            args.append(f"--script={nse_scripts}")
        else:
            bad = requested - allowed
            return [{"_error": f"Scripts no permitidos: {bad}. Solo: {allowed}"}]

    # Traceroute
    if with_traceroute:
        args.append("--traceroute")

    # OS detection
    if with_os:
        args.append("-O")

    # Target
    args.append(subnet)

    # Los scripts NSE (vuln) y -O son mucho mas lentos: damos mas margen.
    timeout_s = 1800 if (nse_scripts or with_os) else 900
    try:
        proc = subprocess.run(args, capture_output=True, text=True, timeout=timeout_s)
        if proc.returncode not in (0, 1):  # 0=ok, 1=ningún host up
            return [{"_error": f"nmap exit code {proc.returncode}: {proc.stderr[:400]}"}]
        root = ET.fromstring(proc.stdout)
    except subprocess.TimeoutExpired:
        return [{"_error": f"nmap timeout ({timeout_s}s)"}]
    except ET.ParseError as exc:
        return [{"_error": f"nmap XML parse error: {exc}"}]
    except OSError as exc:
        return [{"_error": f"nmap falló: {exc}"}]

    hosts = []
    for host in root.findall("host"):
        state = host.find("status")
        if state is not None and state.get("state") != "up":
            continue
        ip = mac = vendor = None
        for addr in host.findall("address"):
            if addr.get("addrtype") == "ipv4":
                ip = addr.get("addr")
            elif addr.get("addrtype") == "mac":
                mac = addr.get("addr")
                vendor = addr.get("vendor")
        ports = []
        for p in host.findall("./ports/port"):
            st = p.find("state")
            if st is None or st.get("state") != "open":
                continue
            svc = p.find("service")
            ports.append({
                "port": int(p.get("portid")),
                "proto": p.get("protocol"),
                "service": (svc.get("name") if svc is not None else "") or "",
                "product": (svc.get("product") if svc is not None else "") or "",
                "version": (svc.get("version") if svc is not None else "") or "",
            })
        os_guess = ""
        osmatch = host.find("./os/osmatch")
        if osmatch is not None:
            os_guess = osmatch.get("name", "")
        if ip:
            hosts.append({
                "ip": ip, "mac": mac, "vendor": vendor,
                "os_guess": os_guess, "ports": ports,
            })
    return hosts


def _scan_nmap_udp(subnet: str, timing: int = 4) -> list[dict]:
    """Escaneo UDP ligero para puertos comunes."""
    args = ["nmap", "-sU", f"-T{timing}", "--top-ports", "20", "-oX", "-", subnet]
    try:
        proc = subprocess.run(args, capture_output=True, text=True, timeout=300)
        if proc.returncode not in (0, 1):
            return [{"_error": f"nmap UDP exit {proc.returncode}: {proc.stderr[:400]}"}]
        root = ET.fromstring(proc.stdout)
    except Exception as exc:
        return [{"_error": f"nmap UDP falló: {exc}"}]

    hosts = []
    for host in root.findall("host"):
        state = host.find("status")
        if state is not None and state.get("state") != "up":
            continue
        ip = None
        for addr in host.findall("address"):
            if addr.get("addrtype") == "ipv4":
                ip = addr.get("addr")
                break
        if not ip:
            continue
        ports = []
        for p in host.findall("./ports/port"):
            st = p.find("state")
            if st is None:
                continue
            st_state = st.get("state", "")
            if st_state not in ("open", "open|filtered"):
                continue
            svc = p.find("service")
            ports.append({
                "port": int(p.get("portid")),
                "proto": "udp",
                "service": (svc.get("name") if svc is not None else "") or "",
                "product": "",
                "version": "",
                "state": st_state,
            })
        # Merge con host existente o crear nuevo
        hosts.append({
            "ip": ip, "mac": None, "vendor": None,
            "os_guess": "", "ports": ports,
        })
    return hosts


# --------------------------------------------------------------------------- #
# Backend 2/3: fallback sin nmap (socket puro, multihilo)
# --------------------------------------------------------------------------- #
def _probe_host(ip: str) -> dict | None:
    open_ports = [p for p in COMMON_PORTS if _tcp_open(ip, p)]
    if not open_ports:
        # host puede estar vivo sin puertos comunes; intento resolución inversa
        try:
            socket.gethostbyaddr(ip)
        except OSError:
            return None
    ports = []
    for p in open_ports:
        ports.append({"port": p, "proto": "tcp",
                      "service": _guess_service(p), "product": "", "version": ""})
    return {"ip": ip, "mac": None, "vendor": None, "os_guess": "", "ports": ports}


def _guess_service(port: int) -> str:
    return {21: "ftp", 22: "ssh", 23: "telnet", 25: "smtp", 53: "domain",
            80: "http", 139: "netbios-ssn", 443: "https", 445: "microsoft-ds",
            515: "printer", 554: "rtsp", 631: "ipp", 1883: "mqtt",
            3389: "ms-wbt-server", 8000: "http-alt", 8080: "http-proxy",
            8443: "https-alt", 8554: "rtsp-alt", 9100: "jetdirect",
            37777: "dahua-dvr"}.get(port, "")


def _scan_socket(subnet: str) -> list[dict]:
    net = ipaddress.ip_network(subnet, strict=False)
    hosts_iter = [str(h) for h in net.hosts()]
    results = []
    with ThreadPoolExecutor(max_workers=64) as pool:
        for res in pool.map(_probe_host, hosts_iter):
            if res:
                results.append(res)
    return results


# --------------------------------------------------------------------------- #
# Merge UDP results into TCP results
# --------------------------------------------------------------------------- #
def _merge_udp(tcp_hosts: list[dict], udp_hosts: list[dict]) -> list[dict]:
    """Fusiona puertos UDP en los hosts TCP existentes; hosts nuevos se añaden."""
    by_ip = {h["ip"]: h for h in tcp_hosts}
    for uh in udp_hosts:
        if "_error" in uh:
            continue
        ip = uh["ip"]
        if ip in by_ip:
            by_ip[ip]["ports"].extend(uh.get("ports", []))
        else:
            tcp_hosts.append(uh)
    return tcp_hosts


# --------------------------------------------------------------------------- #
# API pública
# --------------------------------------------------------------------------- #
def discover(
    subnet: str | None = None,
    fast: bool = False,
    nse_scripts: str | None = None,
    with_udp: bool = False,
    host_discovery: str = "default",
    timing: int = 4,
    with_traceroute: bool = False,
    with_os: bool = False,
) -> dict:
    """Descubre hosts activos. Devuelve {subnet, backend, hosts:[...]}."""
    subnet = subnet or local_subnet()
    _validate_subnet_scope(subnet)

    hosts = []
    backend = "socket-fallback"
    warning = ""
    nmap_error = ""

    if _nmap_available():
        hosts = _scan_nmap(
            subnet, fast=fast, nse_scripts=nse_scripts,
            host_discovery=host_discovery, timing=timing,
            with_traceroute=with_traceroute, with_os=with_os,
        )
        if hosts and "_error" not in hosts[0]:
            backend = "nmap"
        elif hosts and "_error" in hosts[0]:
            nmap_error = hosts[0]["_error"]
            hosts = []  # nmap falló, se intentará el fallback

    # Si se pidieron funciones que SOLO nmap puede hacer (NSE/CVE, OS) y nmap
    # falló, el fallback de socket NO las cumple. No degradamos en silencio:
    # avisamos claramente de que esa parte no se ejecutó.
    if nmap_error and (nse_scripts or with_os):
        backend = "socket-fallback (nmap fallo)"
        pedido = []
        if nse_scripts:
            pedido.append("vulnerabilidades/NSE")
        if with_os:
            pedido.append("deteccion de SO")
        warning = (
            f"nmap falló ({nmap_error}); el fallback basico NO ejecuta "
            f"{' ni '.join(pedido)}. Reintenta apuntando a un solo host "
            f"(ej. un host, no toda la /24) o revisa nmap/permisos."
        )

    if not hosts:
        hosts = _scan_socket(subnet)

    if with_udp and _nmap_available():
        udp_hosts = _scan_nmap_udp(subnet, timing=timing)
        if udp_hosts and "_error" in udp_hosts[0]:
            warning = (warning + " | " if warning else "") + f"UDP: {udp_hosts[0]['_error']}"
        else:
            hosts = _merge_udp(hosts, udp_hosts)

    return {"subnet": subnet, "backend": backend, "hosts": hosts, "warning": warning}


def _validate_subnet_scope(subnet: str) -> None:
    """Default to local/private network ranges to avoid accidental public scans."""
    net = ipaddress.ip_network(subnet, strict=False)
    if net.is_private or net.is_loopback or net.is_link_local:
        return
    if sys.argv and "--allow-public-scan" in sys.argv:
        return
    if str(os.environ.get("NETSCAN_ALLOW_PUBLIC", "")).lower() in {"1", "true", "yes"}:
        return
    raise ValueError(
        f"Refusing to scan non-private subnet {subnet}. "
        "Set NETSCAN_ALLOW_PUBLIC=1 only for explicitly authorized scopes."
    )


if __name__ == "__main__":
    sub = sys.argv[1] if len(sys.argv) > 1 else None
    data = discover(sub)
    print(f"Backend: {data['backend']} · subred {data['subnet']} · "
          f"{len(data['hosts'])} hosts")
    for h in data["hosts"]:
        print(h["ip"], h.get("vendor") or "", [p["port"] for p in h["ports"]])
