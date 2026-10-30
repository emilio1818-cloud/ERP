"""Small firms a code reviewer built to break one rule each (review 8, tests/fixtures/scenarios): each stays as
it was once its rule was fixed."""
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from physarum.grow import ingest, regrow
from physarum.runtime import Runtime
from physarum.store import Store

HERE = Path(__file__).parent / "fixtures" / "scenarios"


class Scenarios(unittest.TestCase):
    def grow(self, script: str, *args) -> Runtime:
        self.tmp = Path(tempfile.mkdtemp(prefix="physarum-scenario-"))
        out = self.tmp / "files"
        subprocess.run([sys.executable, str(HERE / script), str(out), *args], capture_output=True, check=True)
        store = Store(self.tmp / "firma")
        ingest(store, [(str(f.relative_to(out)), f.read_bytes()) for f in sorted(out.rglob("*")) if f.is_file()], "T")
        regrow(store)
        rt = Runtime(store)
        rt.ensure()
        self.state = {rt.title(rid): e for rid, e in rt.ledger.items()}
        return rt

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def having(self, state: str) -> list[str]:
        return sorted(k for k, e in self.state.items() if e["state"] == state)

    def test_a_postcode_is_no_invoice_number(self):
        self.grow("a_plz.py")
        self.assertEqual(self.having("offen"), ["31035", "31037", "31039", "31040"])
        self.assertEqual(self.having("teilbezahlt"), ["31020", "31022"])
        self.assertEqual(len(self.having("bezahlt")), 34)  # also by a third party and by the wife, with the number

    def test_cash_at_the_counter_is_paid_by_the_book(self):
        self.grow("b_cash.py", "erh")
        self.assertEqual(self.having("offen"), ["31034", "31036", "31037", "31039", "31040"])
        self.assertEqual(len(self.having("bezahlt")), 35)

    def test_a_debit_ticked_off_before_the_bank_books_it(self):
        self.grow("c_debit.py")
        nos = sorted(self.state)
        self.assertEqual(self.having("offen"), nos[-3:])
        self.assertEqual(len(self.having("bezahlt")), 37)

    def test_the_customer_number_next_to_the_invoice_number(self):
        self.grow("e_overlap.py")
        self.assertEqual(self.having("offen"), ["10012"] + [str(n) for n in range(10073, 10081)])
        self.assertEqual(self.having("teilbezahlt"), ["10060"])
        self.assertAlmostEqual(self.state["10060"]["open"], 300.0)

    def test_a_reminder_is_no_payment_and_a_strangers_deposit_stays_a_question(self):
        rt = self.grow("g_advice.py")
        self.assertEqual(self.having("offen"), ["31006", "31014", "31037", "31038", "31039", "31040"])
        receipts = [x["money"] for g in rt.work() if g["kind"] == "receipt" for x in g["items"]]
        self.assertEqual(receipts, [1470.0])

    def test_a_double_payment_and_a_refund_to_a_new_account(self):
        rt = self.grow("j_refund.py")
        self.assertEqual(self.having("überzahlt"), ["RE-2026-0026"])
        risk = next(g for g in rt.work() if g["id"] == "risk:iban")
        self.assertTrue(any("DE75 5121 0800 1245 1261 99" in x["reason"] for x in risk["items"]), risk["items"])

    def test_a_down_payment_invoice_is_owed_as_written_not_the_order_sum(self):
        self.grow("k_gross.py")
        self.assertEqual({k: self.state[k]["open"] for k in self.having("offen")},
                         {"RE-2026-0027": 17700.0, "RE-2026-0028": 1999.0, "RE-2026-0029": 18600.0,
                          "RE-2026-0030": 19050.0})

    def test_skonto_as_it_is_usually_written(self):
        self.grow("n_skonto.py")
        self.assertEqual(self.having("offen"), ["RE-2026-0028", "RE-2026-0029", "RE-2026-0030"])
        paid = [e for k, e in self.state.items() if e["state"] == "bezahlt"]
        self.assertEqual(len(paid), 27)
        self.assertFalse([e["notes"] for e in paid if any("nachfordern" in n for n in e["notes"])])


if __name__ == "__main__":
    unittest.main()
