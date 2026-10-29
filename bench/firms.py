"""The firms of the bench: each a data dump the way an independent reviewer built it, delivered once or
twice, with what a bookkeeper knows to be true on the day of each delivery.

A truth names, per delivery: the open invoices (number → amount still owed), the overdue ones, the
finished jobs nobody invoiced yet, and money that came in for no invoice. A firm may know only some.
"""
from __future__ import annotations

import json
import subprocess
import sys
import zipfile
from datetime import date
from pathlib import Path

HERE = Path(__file__).parent
ROOT = HERE.parent


def _files(folder: Path) -> list[tuple[str, bytes]]:
    return [(str(p.relative_to(folder)), p.read_bytes()) for p in sorted(folder.rglob("*")) if p.is_file()]


def _unzip(name: str, tmp: Path) -> Path:
    out = tmp / name
    with zipfile.ZipFile(HERE / "data" / f"{name}.zip") as z:
        z.extractall(out)
    return out


def demo(tmp: Path) -> list[dict]:
    """The coffee roaster shipped with Physarum."""
    from physarum.demo.generate import generate
    res = generate(tmp / "dump", today=date(2026, 10, 29), growth=False)
    files = [(str(p.relative_to(tmp / "dump")), p.read_bytes()) for p in res["initial"]]
    return [dict(files=files, today="2026-10-29", truth=res["truth"])]


# the plumbing firm of tests/test_second_firm.py: done, but never invoiced
_BRENNER_UNBILLED = [
    "A-25-010", "A-25-038", "A-25-106", "A-25-121", "A-25-136", "A-25-141", "A-25-186", "A-25-190", "A-25-201",
    "A-25-223", "A-26-031", "A-26-065", "A-26-069", "A-26-094", "A-26-125", "A-26-135", "A-26-136", "A-26-157",
    "A-26-160", "A-26-173", "A-26-179", "A-26-195", "A-26-196", "A-26-197", "A-26-202", "A-26-204", "A-26-208",
    "A-26-214", "A-26-218", "A-26-226", "A-26-231", "A-26-232", "A-26-234", "A-26-237", "A-26-241", "A-26-242",
    "A-26-243", "A-26-248", "A-26-250", "A-26-253", "A-26-254"]


def brenner(tmp: Path) -> list[dict]:
    """Plumbing and heating in Dresden (review 2): preamble bank export, one sheet per fitter, a pivot sheet."""
    return [dict(files=_files(ROOT / "tests" / "fixtures" / "brenner" / "daten"), today="2026-10-29",
                 truth=dict(unbilled=_BRENNER_UNBILLED))]


def _delivered(name: str, tmp: Path) -> list[dict]:
    data = _unzip(name, tmp)
    truth = json.loads((HERE / "data" / f"{name}_truth.json").read_text(encoding="utf-8"))
    return [dict(files=_files(data / d["folder"]), today=d["today"], truth=d) for d in truth["deliveries"]]


def agentur(tmp: Path) -> list[dict]:
    """A web agency nobody had seen (review 3): CRM, two time trackers, tickets, invoice book, bank; twice."""
    return _delivered("agentur", tmp)


def handwerk(tmp: Path) -> list[dict]:
    """A heating and plumbing business (review 4): order book per year, time sheets per fitter, two banks."""
    return _delivered("handwerk", tmp)


def musikschule(tmp: Path) -> list[dict]:
    """A music school nobody had seen (strategic review): SEPA batches, VAT-free fees, teachers by initials."""
    out = tmp / "musik"
    subprocess.run([sys.executable, str(HERE / "gen" / "musikschule.py"), str(out)], check=True, capture_output=True)
    t = json.loads((tmp / "musik_truth.json").read_text(encoding="utf-8"))
    return [dict(files=_files(out), today=t["today"],
                 truth=dict(open={no: None for no in t["open_invoices"]}, open_total=t["open_amount"],
                            overdue=t["overdue"]))]


def maler(tmp: Path) -> list[dict]:
    """A painting business in Kassel (usability test): two Hans Müller, a family that is no customer."""
    out = tmp / "maler"
    subprocess.run([sys.executable, str(HERE / "gen" / "maler.py"), str(out)], check=True, capture_output=True)
    return [dict(files=_files(out), today="2026-10-29",
                 truth=dict(open={"RE-2026-100": 1570.0, "RE-2026-106": 4284.0, "RE-2026-107": 1071.0,
                                  "RE-2026-109": 2856.0, "RE-2026-110": 3689.0, "RE-2026-111": 690.2,
                                  "RE-2026-112": 2558.5},
                            overdue=["RE-2026-100", "RE-2026-106", "RE-2026-107"],
                            unbilled=["A-2026-030", "A-2026-034"]))]


def shop(tmp: Path) -> list[dict]:
    """A bike-parts web shop (review 6): Shopify, PayPal, Klarna, payouts, refunds, sizes, B2B invoices; twice."""
    out = tmp / "shop"
    subprocess.run([sys.executable, str(HERE / "gen" / "shop" / "gen_shop.py"), str(out)], check=True, capture_output=True)
    res = []
    for i in (1, 2):
        t = json.loads((out / f"truth_d{i}.json").read_text(encoding="utf-8"))
        owed = {x[0]: x[2] for x in t["b2b"]["open_items"]["items"]}  # the invoices to business customers
        for no, o in t["orders"].items():  # web orders that wait for money (after the shop review's own count)
            if not o["b2b"] and o["state_true"] in ("pending", "partially_paid"):
                owed[no] = round(o["total"] - (o["money_received"] or 0), 2) if o["state_true"] == "partially_paid" else o["total"]
        res.append(dict(files=_files(out / f"lieferung{i}"), today=t["as_of"],
                        truth=dict(open=owed, overdue=[x[0] for x in t["b2b"]["overdue"]["items"]])))
    return res


FIRMS = dict(demo=demo, brenner=brenner, agentur=agentur, handwerk=handwerk, musikschule=musikschule, maler=maler,
             shop=shop)
# the quick firms are also run with other names for the same things
VARIED = ("demo", "maler", "musikschule")
