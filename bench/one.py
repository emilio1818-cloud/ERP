"""One firm, one variant: grow every delivery on its own day and measure it against the truth.
python bench/one.py FIRM [S0|S1|S2|S3]  ->  one JSON line on stdout."""
from __future__ import annotations

import json
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import shim  # noqa: E402  (before anything that asks for today)

sys.path.insert(0, str(Path(__file__).parent.parent))
from firms import FIRMS  # noqa: E402
from variants import apply  # noqa: E402

from physarum.coverage import coverage  # noqa: E402
from physarum.grow import ingest, regrow  # noqa: E402
from physarum.runtime import Runtime  # noqa: E402
from physarum.store import Store  # noqa: E402

SCHEMA = {"same_type", "relation", "confirm_merge"}  # questions about the data model, not about the firm


def _score(got: set, want: set) -> dict:
    return dict(tp=len(got & want), fp=len(got - want), fn=len(want - got))


def measure(rt: Runtime, truth: dict, today) -> dict:
    keyed = {}
    for rid, e in rt.ledger.items():
        rec = rt.by_id.get(rid)
        spec = rt.spec(rec["type"]) if rec else None
        if not spec or e.get("outgoing"):
            continue  # money the firm pays is not what it is owed
        keyed[rid] = str(rec["data"].get(spec.get("key")) or rt.title(rid))
    open_ = {keyed[rid]: round(e["open"], 2) for rid, e in rt.ledger.items()
             if rid in keyed and e["state"] in ("offen", "teilbezahlt") and e["open"] > 0.005}
    work = rt.work(today)
    overdue = {keyed[x["rid"]] for g in work if g["kind"] == "overdue" for x in g["items"] if x.get("rid") in keyed}
    unbilled = {str(x["title"]) for g in work if g["kind"] == "ready" for x in g["items"]}
    over_budget = {str(x["title"]) for g in work if g["kind"] == "budget" for x in g["items"]}
    receipts = sorted(round(x["money"], 2) for g in work if g["kind"] == "receipt" for x in g["items"] if x.get("money"))
    qs = rt.store.q("SELECT kind FROM questions WHERE status='open'")
    out = dict(types=len(rt.model["types"]), lists=sorted(t["plural"] for t in rt.model["types"]), questions=len(qs), schema_questions=sum(1 for q in qs if q["kind"] in SCHEMA),
               heute_groups=len(work), heute_items=sum(g["count"] for g in work if g.get("severity", 2) >= 2),
               coverage=round(coverage(rt).get("score", 0), 3), open=open_, overdue=sorted(overdue),
               unbilled=sorted(unbilled), over_budget=sorted(over_budget), receipts=receipts,
               eur_open=round(sum(open_.values()), 2))
    score = {}
    if truth.get("open") is not None:
        want = truth["open"]
        score["open"] = _score(set(open_), set(want))
        score["open"]["amount_ok"] = sum(1 for k, v in want.items() if v is not None and k in open_ and abs(open_[k] - v) <= 0.01)
        score["open"]["eur_truth"] = round(truth.get("open_total") or sum(v or 0 for v in want.values()), 2)
    for k in ("overdue", "unbilled", "over_budget"):
        if truth.get(k) is not None:
            score[k] = _score(set(out[k]), set(truth[k]))
    if truth.get("receipts") is not None:
        score["receipts"] = _score(set(receipts), set(round(x, 2) for x in truth["receipts"]))
    out["score"] = score
    return out


def main(firm: str, variant: str = "S0") -> dict:
    with tempfile.TemporaryDirectory(prefix=f"bench-{firm}-") as tmp:
        tmp = Path(tmp)
        deliveries = FIRMS[firm](tmp)
        store = Store(tmp / "firma")
        res = dict(firm=firm, variant=variant, deliveries=[])
        for i, d in enumerate(deliveries, start=1):
            shim.set_today(d["today"])
            t0 = time.time()
            ingest(store, apply(variant, d["files"]), "Bench")
            regrow(store)
            rt = Runtime(store)
            rt.ensure()
            m = measure(rt, d["truth"], shim.FakeDate.today())
            m["seconds"] = round(time.time() - t0, 1)
            m["delivery"], m["today"] = i, d["today"]
            res["deliveries"].append(m)
        return res


if __name__ == "__main__":
    print(json.dumps(main(sys.argv[1], sys.argv[2] if len(sys.argv) > 2 else "S0"), ensure_ascii=False, default=str))
