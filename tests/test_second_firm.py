"""A second, independent firm: a plumbing and heating business in Dresden.

The data was built by an independent reviewer who never saw the demo company, with the
mess of a real craft business: a bank export with a preamble, multi-line purposes and a
separate Soll/Haben column; one timesheet per fitter; a pivot sheet; old customer numbers
from a previous system; a scheduling tool's nested JSON; a second delivery of the same
files with changed values; and broken files. The expected counts come from its ground truth.
"""
import shutil
import tempfile
import time
import unittest
from pathlib import Path

from physarum.grow import ingest, regrow
from physarum.questions import open_questions
from physarum.runtime import Runtime
from physarum.store import Store

HERE = Path(__file__).parent / "fixtures" / "brenner"


def files(folder: Path):
    return [(str(p.relative_to(folder)), p.read_bytes()) for p in sorted(folder.rglob("*")) if p.is_file()]


class SecondFirm(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = Path(tempfile.mkdtemp(prefix="physarum-brenner-"))
        cls.store = Store(cls.tmp / "firma")
        ingest(cls.store, files(HERE / "daten"), "Test")
        cls.summary = regrow(cls.store)
        cls.model = cls.store.model()
        cls.rt = Runtime(cls.store)
        cls.rt.ensure()

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def t(self, name):
        return next(t for t in self.model["types"] if t["name"] == name)

    def n(self, name):
        return len(self.rt.records[self.t(name)["id"]])

    def test_no_learning_step_failed(self):
        self.assertEqual(self.model.get("errors"), [])

    def test_counts_match_the_ground_truth(self):
        self.assertEqual(self.n("Kunde"), 151)          # 135 current + 13 only in the old system + 3 prospects
        self.assertEqual(self.n("Lieferant"), 6)        # from the sheet "Lieferanten" of "Kundenstamm"
        self.assertEqual(self.n("Mitarbeiter"), 8)      # HR export and scheduling resources are one list
        self.assertEqual(self.n("Auftrag"), 514)
        self.assertEqual(self.n("Rechnung"), 498)
        self.assertEqual(self.n("Kontobewegung"), 488)  # preamble and balance rows are not bookings
        self.assertEqual(self.n("Stundenzettel"), 455)  # one sheet per fitter, nothing merged by building site
        self.assertEqual(self.n("Termin"), 108)
        self.assertEqual(self.n("Wartungsvertrag"), 42)
        self.assertFalse(any("Auswertung" in m["label"] for t in self.model["types"] for m in t["members"]))

    def test_few_and_sensible_questions(self):
        qs = open_questions(self.store)
        self.assertLessEqual(len(qs), 8)
        self.assertTrue(any("Hofmann" in q["text"] and "Hoffmann" in q["text"] for q in qs))

    def test_bank_signs_and_sheet_owner(self):
        kb = self.t("Kontobewegung")
        amount = next(a for a in kb["attrs"] if a["kind"] == "money")
        recs = self.rt.records[kb["id"]]
        self.assertTrue(any(r["data"].get(amount["id"], 0) < 0 for r in recs))   # Soll = money out
        self.assertTrue(any(r["data"].get(amount["id"], 0) > 0 for r in recs))
        sz = self.t("Stundenzettel")
        who = next(a for a in sz["attrs"] if a["kind"] == "ref" and a["ref"] == self.t("Mitarbeiter")["id"])
        linked = sum(1 for r in self.rt.records[sz["id"]] if isinstance(r["data"].get(who["id"]), int))
        self.assertGreaterEqual(linked, 440)

    def test_links(self):
        inv, cust, order = self.t("Rechnung"), self.t("Kunde"), self.t("Auftrag")
        ik = next(a for a in inv["attrs"] if a["kind"] == "ref" and a["ref"] == cust["id"])
        self.assertTrue(all(isinstance(r["data"].get(ik["id"]), int) for r in self.rt.records[inv["id"]]))
        ok = 0
        for r in self.rt.records[order["id"]]:
            if any(isinstance(r["data"].get(a["id"]), int) for a in order["attrs"] if a.get("ref") == cust["id"]):
                ok += 1
        self.assertGreaterEqual(ok, 490)
        phones = [r["data"].get(a["id"]) for a in cust["attrs"] if a["kind"] == "phone" for r in self.rt.records[cust["id"]]]
        phones = [p for p in phones if p]
        self.assertTrue(all(str(p).startswith(("0", "+")) for p in phones))  # no eaten leading zeros

    def test_second_delivery_updates_in_place(self):
        tmp = Path(tempfile.mkdtemp(prefix="physarum-brenner2-"))
        try:
            shutil.copytree(self.tmp / "firma", tmp / "firma")
            store = Store(tmp / "firma")
            before = {t["id"]: t["name"] for t in store.model()["types"]}
            time.sleep(1)
            ingest(store, files(HERE / "lieferung2"), "Test")
            summary = regrow(store)
            model = store.model()
            self.assertEqual({t["id"]: t["name"] for t in model["types"]}, before)
            self.assertFalse(summary["stats"].get("conflicts"))
            rt = Runtime(store)
            rt.ensure()
            order = next(t for t in model["types"] if t["name"] == "Auftrag")
            self.assertEqual(len(rt.records[order["id"]]), 522)
            status = next(a for a in order["attrs"] if a["name"] == "Status")
            a010 = next(r for r in rt.records[order["id"]] if r["data"].get(order["key"]) == "A-25-010")
            self.assertEqual(a010["data"][status["id"]], "abgerechnet")
            cust = next(t for t in model["types"] if t["name"] == "Kunde")
            tel = next(a for a in cust["attrs"] if a["name"] == "Telefon")
            k = next(r for r in rt.records[cust["id"]] if str(r["data"].get(cust["key"])) == "10052")
            self.assertEqual(k["data"][tel["id"]], "+49 351 3109000")
            member = next(m for m in cust["members"] if m["label"].startswith("Kundenstamm"))
            self.assertIn("10119", member["versions"]["vanished"])  # reported, not silently dropped
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_broken_files_never_stop_the_growth(self):
        tmp = Path(tempfile.mkdtemp(prefix="physarum-broken-"))
        try:
            store = Store(tmp / "firma")
            res = ingest(store, files(HERE / "kaputt"), "Test")
            self.assertEqual(len(res), len(list((HERE / "kaputt").iterdir())))
            regrow(store)
            self.assertIsNotNone(store.model())
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
