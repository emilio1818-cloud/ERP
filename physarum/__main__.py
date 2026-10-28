"""Start Physarum:  python -m physarum [ORDNER] [--port 8000] [--host 127.0.0.1] [--einwerfen DATEIEN …]

ORDNER is where the company lives (database + original files). Default: ./firma
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path


def main(argv: list[str] | None = None):
    ap = argparse.ArgumentParser(prog="physarum", description="Physarum – ein ERP, das aus Ihren Daten wächst.")
    ap.add_argument("ordner", nargs="?", default="firma", help="Datenordner der Firma (Standard: ./firma)")
    ap.add_argument("--port", type=int, default=8000)
    ap.add_argument("--host", default="127.0.0.1", help="127.0.0.1 = nur dieser Rechner (Standard)")
    ap.add_argument("--erlaubt", nargs="*", default=[], metavar="NAME",
                    help="weitere Rechnernamen, unter denen Physarum im Netz erreichbar sein darf")
    ap.add_argument("--einwerfen", nargs="*", metavar="PFAD", help="Dateien/Ordner einwerfen und wachsen, ohne Server")
    ap.add_argument("--beispiel", action="store_true", help="Beispielfirma (Kaffeerösterei) erzeugen und einwerfen")
    args = ap.parse_args(argv)
    folder = Path(args.ordner)
    if args.einwerfen is not None or args.beispiel:
        from .grow import Progress, ingest, regrow
        from .store import Store

        store = Store(folder)
        files = []
        if args.beispiel:
            from .demo.generate import generate

            res = generate(folder / "beispiel" / "dump")
            files += [(p.name, p.read_bytes()) for p in res["initial"]]
        for p in args.einwerfen or []:
            p = Path(p)
            items = sorted(x for x in p.rglob("*") if x.is_file()) if p.is_dir() else [p]
            files += [(x.name, x.read_bytes()) for x in items]
        say = Progress(lambda m, f: print("  " + m))
        ingest(store, files, "Kommandozeile", say)
        regrow(store, say)
        if args.einwerfen is not None and not args.beispiel:
            return
    import uvicorn

    from .web.app import create_app

    import socket

    local = args.host in ("127.0.0.1", "localhost", "::1")
    hosts = set(args.erlaubt) | ({args.host, socket.gethostname()} if not local else set())
    print(f"Physarum läuft: http://{args.host}:{args.port}  (Daten in {folder.resolve()})")
    if not local:
        print("  Hinweis: im Netz erreichbar, aber ohne Anmeldung – nur in einem vertrauenswürdigen Netz verwenden.")
    uvicorn.run(create_app(folder, hosts=hosts, any_ip=not local), host=args.host, port=args.port, log_level="warning")


if __name__ == "__main__":
    main(sys.argv[1:])
