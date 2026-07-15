"""CLI del escáner de red defensivo.

Uso legítimo: SOLO tu red o redes con autorización explícita por escrito.

Ejemplos (PowerShell, desde C:\\Users\\Usuario\\jarvis):
    .venv\\Scripts\\python.exe scripts\\netscan_check.py
    .venv\\Scripts\\python.exe scripts\\netscan_check.py --subnet 192.168.1.0/24
    .venv\\Scripts\\python.exe scripts\\netscan_check.py --fast --no-cve --no-notify
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

os.environ["PYTHONUTF8"] = "1"
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from netscan import report  # noqa: E402

BANNER = (
    "AVISO: escanea únicamente redes de tu propiedad o con permiso escrito.\n"
    "El escaneo de redes ajenas puede constituir delito.\n"
)


def main():
    parser = argparse.ArgumentParser(description="Jarvis NetScan — auditoría defensiva de red")
    parser.add_argument("--subnet", help="Subred CIDR, ej. 192.168.1.0/24 (auto si se omite)")
    parser.add_argument("--fast", action="store_true", help="Escaneo ligero (menos puertos)")
    parser.add_argument("--no-cve", action="store_true", help="No consultar NVD (solo inventario)")
    parser.add_argument("--no-notify", action="store_true", help="No enviar a Telegram")
    args = parser.parse_args()

    print(BANNER)
    result = report.run_scan(
        subnet=args.subnet, fast=args.fast,
        with_cve=not args.no_cve, notify=not args.no_notify,
    )
    print(report.format_text(result))
    s = result["summary"]["cve_by_severity"]
    print(f"\nInforme en netscan\\reports\\ · dispositivos={result['host_count']} · "
          f"CRIT={s['CRITICAL']} HIGH={s['HIGH']}")
    sys.exit(1 if (s["CRITICAL"] or s["HIGH"]) else 0)


if __name__ == "__main__":
    main()
