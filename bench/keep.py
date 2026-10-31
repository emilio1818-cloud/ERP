"""Grow one firm of the bench, delivery by delivery on its day, and keep the result to look at.

    python bench/keep.py FIRM FOLDER [S0|S1|S2|S3]     then: python -m physarum FOLDER --port 8800

The pages then show the firm as of its last delivery (the dates of the bench are fixed; Heute counts from
the real today, so a few days may lie between)."""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE))
import shim  # noqa: E402  (before anything that asks for today)

sys.path.insert(0, str(HERE.parent))
from firms import FIRMS  # noqa: E402
from variants import apply  # noqa: E402

from physarum.grow import ingest, regrow  # noqa: E402
from physarum.store import Store  # noqa: E402


def main(argv: list[str]) -> int:
    if len(argv) < 2 or argv[0] not in FIRMS:
        print(__doc__.strip(), "\n\nFirmen:", ", ".join(FIRMS))
        return 2
    firm, out = argv[0], Path(argv[1])
    variant = argv[2] if len(argv) > 2 else "S0"
    store = Store(out)
    with tempfile.TemporaryDirectory(prefix="bench-keep-") as tmp:
        for d in FIRMS[firm](Path(tmp)):
            shim.set_today(d["today"])
            ingest(store, apply(variant, d["files"]), "Prüfstand")
            regrow(store)
            print("Lieferung vom", d["today"], "eingewachsen")
    print(f"fertig: python -m physarum {out} --port 8800")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
