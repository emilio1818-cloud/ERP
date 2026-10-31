"""What a change did, cell by cell: the last run (bench/last.json) against the baseline (bench/baseline.json).

    python bench/diff.py                 every firm, variant and delivery that differs, then the summary
    python bench/diff.py --without hausverwaltung   the summary also without these firms

Only cells in both files are compared (a run of a few firms compares those). A change may go into the
baseline (`python bench/run.py --save`) when no firm got worse."""
from __future__ import annotations

import json
import sys
from pathlib import Path

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE))
from run import summary  # noqa: E402


def _cells(run: dict) -> dict:
    return {(r["firm"], r["variant"]): r for r in run["results"] if not r.get("error")}


def main(argv: list[str]) -> int:
    base = json.loads((HERE / "baseline.json").read_text())
    last = json.loads((HERE / "last.json").read_text())
    without = set(argv[argv.index("--without") + 1:]) if "--without" in argv else set()
    for r in last["results"]:
        if r.get("error"):
            print("ABSTURZ", r["firm"], r["variant"], r["error"][-300:])
    b, l = _cells(base), _cells(last)
    same = True
    for key in sorted(l):
        if key not in b:
            print("neu im Lauf:", *key)
            continue
        for db, dl in zip(b[key]["deliveries"], l[key]["deliveries"]):
            sb = {k: (v["tp"], v["fp"], v["fn"]) for k, v in db["score"].items()}
            sl = {k: (v["tp"], v["fp"], v["fn"]) for k, v in dl["score"].items()}
            moved = {k: (sb.get(k), sl.get(k)) for k in sb.keys() | sl.keys() if sb.get(k) != sl.get(k)}
            lists = (sorted(set(db.get("lists", [])) - set(dl.get("lists", []))),
                     sorted(set(dl.get("lists", [])) - set(db.get("lists", []))))
            if moved or db["heute_items"] != dl["heute_items"] or abs(db["eur_open"] - dl["eur_open"]) > 0.01 \
                    or lists != ([], []):
                same = False
                print(*key, "Lieferung", dl["delivery"], "| tp/fp/fn vorher→nachher:", moved or "gleich",
                      "| Heute", db["heute_items"], "→", dl["heute_items"], "| € offen", db["eur_open"], "→", dl["eur_open"],
                      *(["| Listen weg", lists[0], "neu", lists[1]] if lists != ([], []) else []))
    if same:
        print("Alle verglichenen Zellen gleich.")
    keys = [k for k in l if k in b]
    print("\nZusammenfassung (Basis → Lauf), nur verglichene Zellen:")
    for label, drop in (("alle", set()),) + ((("ohne " + ", ".join(sorted(without)), without),) if without else ()):
        sb = summary([b[k] for k in keys if k[0] not in drop])
        sl = summary([l[k] for k in keys if k[0] not in drop])
        print(f"  {label}: " + ", ".join(f"{k} {sb[k]} → {sl[k]}" for k in ("money", "heute", "names", "lists")))
    print("  Code: " + ", ".join(f"{k} {base['summary'][k]} → {last['summary'][k]}" for k in ("lines", "word_rules", "regexes")))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
