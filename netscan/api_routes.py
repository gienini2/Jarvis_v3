"""FastAPI routes for defensive network scanning."""
from __future__ import annotations

import threading

from fastapi import APIRouter, Body
from pydantic import BaseModel, Field

from netscan import report

router = APIRouter(prefix="/netscan", tags=["netscan"])

_state = {"running": False, "last_error": None}


class ScanRequest(BaseModel):
    site_name: str | None = Field(
        default=None,
        description="Free label for this network, for example red_1 or oficina_vlan.",
    )
    subnet: str | None = Field(default=None, description="Example: 192.168.1.0/24")
    fast: bool = False
    with_cve: bool = True
    notify: bool = True
    authorize_vuln_scan: bool = False
    authorization_note: str | None = Field(
        default=None,
        description="Human note confirming ownership or written authorization.",
    )
    with_synthesis: bool | None = Field(
        default=None,
        description="LLM analysis of the result via Jarvis router. None = auto (on unless fast).",
    )
    nse_scripts: str | None = Field(
        default=None,
        description="NSE scripts defensivos: safe,default,vuln,discovery,version",
    )
    with_udp: bool = Field(
        default=False,
        description="Escaneo UDP de puertos comunes (DNS, SNMP, NTP, mDNS...).",
    )
    host_discovery: str = Field(
        default="default",
        description="Estrategia de descubrimiento: default, arp, tcp_syn, tcp_ack, icmp, aggressive, none.",
    )
    timing: int = Field(
        default=4, ge=0, le=5, description="Plantilla de timing nmap (0=paranoico, 5=insane)."
    )
    with_traceroute: bool = Field(default=False, description="Incluir traceroute.")
    with_os: bool = Field(
        default=False,
        description="Deteccion de sistema operativo (nmap -O; requiere admin en Windows).",
    )


def _worker(payload: ScanRequest) -> None:
    try:
        _state["last_error"] = None
        report.run_scan(
            site_name=payload.site_name,
            subnet=payload.subnet,
            fast=payload.fast,
            with_cve=payload.with_cve,
            notify=payload.notify,
            authorize_vuln_scan=payload.authorize_vuln_scan,
            authorization_note=payload.authorization_note,
            with_synthesis=payload.with_synthesis,
            nse_scripts=payload.nse_scripts,
            with_udp=payload.with_udp,
            host_discovery=payload.host_discovery,
            timing=payload.timing,
            with_traceroute=payload.with_traceroute,
            with_os=payload.with_os,
        )
    except Exception as exc:
        _state["last_error"] = str(exc)
    finally:
        _state["running"] = False


@router.post("/scan")
def start_scan(
    payload: ScanRequest | None = Body(default=None),
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
):
    """Start a scan in the background."""
    payload = payload or ScanRequest(
        site_name=site_name,
        subnet=subnet,
        fast=fast,
        with_cve=with_cve,
        notify=notify,
        authorize_vuln_scan=authorize_vuln_scan,
        authorization_note=authorization_note,
        with_synthesis=with_synthesis,
        nse_scripts=nse_scripts,
        with_udp=with_udp,
        host_discovery=host_discovery,
        timing=timing,
        with_traceroute=with_traceroute,
        with_os=with_os,
    )
    if payload.authorize_vuln_scan and not (payload.authorization_note or "").strip():
        return {
            "status": "authorization_required",
            "detail": "Set authorization_note to confirm ownership or written authorization before active assessment.",
        }
    if _state["running"]:
        return {"status": "already_running"}
    _state["running"] = True
    threading.Thread(target=_worker, args=(payload,), daemon=True).start()
    return {
        "status": "started",
        "site_name": payload.site_name or "unnamed",
        "subnet": payload.subnet or "auto",
        "vulnerability_assessment": (
            "authorized" if payload.authorize_vuln_scan else "skipped"
        ),
    }


@router.get("/last")
def last_report():
    return report.load_last() or {"status": "no_reports_yet"}


@router.get("/status")
def status():
    return {"running": _state["running"], "last_error": _state["last_error"]}
