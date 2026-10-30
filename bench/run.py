"""The bench: every firm grown on the day of each delivery, the quick ones also under other names; one
table, compared with the baseline. This, not a review's single finding, is what a change must improve.

    python bench/run.py              all firms, also as S1 and S2, the quick ones also as S3
    python bench/run.py demo maler   only these
    python bench/run.py --s0         only under their own names (the quick look while working)
    python bench/run.py --save       the result becomes the baseline (bench/baseline.json)
"""
from __future__ import annotations

import json
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE))
from codesize import measure as code_size  # noqa: E402
from firms import FIRMS, VARIED  # noqa: E402


def _run(firm: str, variant: str) -> dict:
    p = subprocess.run([sys.executable, str(HERE / "one.py"), firm, variant], capture_output=True, text=True,
                       cwd=HERE.parent, timeout=1800)
    if p.returncode:
        return dict(firm=firm, variant=variant, error=(p.stderr or p.stdout)[-600:])
    return json.loads(p.stdout.strip().splitlines()[-1])


def _jaccard(a, b) -> float:
    a, b = set(a), set(b)
    return 1.0 if not a and not b else round(len(a & b) / len(a | b), 2)


def summary(results: list[dict]) -> dict:
    base = {r["firm"]: r for r in results if r.get("variant") == "S0" and not r.get("error")}
    money = [0, 0]
    tasks = [0, 0]
    for r in base.values():
        for d in r["deliveries"]:
            for k, sc in d["score"].items():
                bucket = money if k == "open" else tasks
                bucket[0] += sc["tp"]
                bucket[1] += sc["tp"] + sc["fp"] + sc["fn"]
    inv, lists = [], []
    for r in results:  # every delivery: a first growth under other names can go wrong where the second does not
        if r.get("variant", "S0") != "S0" and not r.get("error") and r["firm"] in base:
            for b, v in zip(base[r["firm"]]["deliveries"], r["deliveries"]):
                inv.append((_jaccard(b["open"], v["open"]) + _jaccard(b["overdue"], v["overdue"])) / 2)
                lists.append(_jaccard(b.get("lists", []), v.get("lists", [])))
    return dict(money=round(money[0] / money[1], 3) if money[1] else None,
                heute=round(tasks[0] / tasks[1], 3) if tasks[1] else None,
                names=round(sum(inv) / len(inv), 3) if inv else None,
                lists=round(sum(lists) / len(lists), 3) if lists else None,
                schema_questions=sum(r["deliveries"][-1]["schema_questions"] for r in base.values()),
                errors=sum(1 for r in results if r.get("error")), **code_size(HERE.parent))


def _cell(sc: dict | None) -> str:
    return "–" if not sc else f"{sc['tp']}/{sc['fp']}/{sc['fn']}"


def table(results: list[dict]) -> str:
    rows = ["| Firma | Variante | Lfg. | offen tp/fp/fn | € offen (Wahrheit) | überfällig | nicht berechnet | über Budget"
            " | Geld ohne Rechnung | Heute | Fragen (Schema) | s |", "|" + "---|" * 12]
    for r in sorted(results, key=lambda r: (r["firm"], r.get("variant", ""))):
        if r.get("error"):
            rows.append(f"| {r['firm']} | {r['variant']} | FEHLER: {r['error'][-120:]!r} |" + " |" * 9)
            continue
        for d in r["deliveries"]:
            s = d["score"]
            eur = f"{d['eur_open']:,.2f}".replace(",", " ") + (f" ({s['open']['eur_truth']:,.2f})".replace(",", " ") if "open" in s else "")
            rows.append(f"| {r['firm']} | {r['variant']} | {d['delivery']} | {_cell(s.get('open'))} | {eur} | "
                        f"{_cell(s.get('overdue'))} | {_cell(s.get('unbilled'))} | {_cell(s.get('over_budget'))} | "
                        f"{_cell(s.get('receipts'))} | "
                        f"{d['heute_items']} | {d['questions']} ({d['schema_questions']}) | {d['seconds']} |")
    return "\n".join(rows)


def main(argv: list[str]) -> int:
    save = "--save" in argv
    only = [a for a in argv if not a.startswith("--")] or list(FIRMS)
    jobs = [(f, "S0") for f in only]
    if "--s0" not in argv:
        jobs += [(f, v) for f in only for v in ("S1", "S2", "S3") if v != "S3" or f in VARIED]
    jobs.sort(key=lambda j: j[0] not in ("agentur", "shop"))  # the slow ones first
    with ThreadPoolExecutor(max_workers=4) as ex:
        results = list(ex.map(lambda j: _run(*j), jobs))
    s = summary(results)
    print(table(results))
    print()
    baseline = json.loads((HERE / "baseline.json").read_text()) if (HERE / "baseline.json").exists() else None
    names = dict(money="Geld richtig", heute="Heute-Aufgaben richtig", names="gleich bei anderen Namen",
                 lists="Listen gleich benannt",
                 schema_questions="Fragen zum Datenmodell", errors="Abstürze", lines="Zeilen Code",
                 word_rules="Wort-Regeln", regexes="reguläre Ausdrücke")
    for k, label in names.items():
        was = (baseline or {}).get("summary", {}).get(k)
        delta = "" if was is None or s[k] is None else f"  (Basis {was})"
        print(f"{label:28} {s[k]}{delta}")
    out = dict(summary=s, results=results)
    (HERE / "last.json").write_text(json.dumps(out, ensure_ascii=False, indent=1, default=str))
    if save:
        (HERE / "baseline.json").write_text(json.dumps(out, ensure_ascii=False, indent=1, default=str))
        print("\nals Basis gespeichert: bench/baseline.json")
    return 1 if s["errors"] else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
