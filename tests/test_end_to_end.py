"""The whole organism on the demo company: dump everything in, check what grew."""
import shutil
import tempfile
import time
import unittest
from collections import defaultdict
from datetime import date
from pathlib import Path

from starlette.testclient import TestClient

from physarum import ops
from physarum.demo.generate import generate
from physarum.grow import ingest, regrow
from physarum.process import compute_work
from physarum.runtime import Runtime
from physarum.store import Store
from physarum.web.app import create_app

TODAY = date.today()


class DemoCompany(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = Path(tempfile.mkdtemp(prefix="physarum-test-"))
        res = generate(cls.tmp / "dump", today=TODAY)
        cls.growth = res["growth"]
        cls.store = Store(cls.tmp / "firma")
        ingest(cls.store, [(p.name, p.read_bytes()) for p in res["initial"]], "Test")
        cls.summary = regrow(cls.store)
        cls.model = cls.store.model()
        cls.rt = Runtime(cls.store)
        cls.rt.ensure()

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def t(self, name):
        return next(t for t in self.model["types"] if t["name"] == name)

    def a(self, tname, aname):
        return next(a for a in self.t(tname)["attrs"] if a["name"] == aname)

    def test_types_that_grew(self):
        names = {t["name"] for t in self.model["types"]}
        for n in ["Kunde", "Artikel", "Auftrag", "Auftragsposition", "Rechnung", "Kontobewegung", "Einkauf",
                  "Lieferant", "Mitarbeiter", "Shop-Bestellung", "Shop-Bestellposition", "Dokument",
                  "Eingangsrechnung", "Eingangsrechnungsposition"]:
            self.assertIn(n, names)
        self.assertEqual(len(names), 14)  # nothing spurious

    def test_einvoices_are_anchored(self):
        """XRechnung (UBL) and ZUGFeRD (CII, also inside a PDF) become supplier invoices with lines."""
        er = self.t("Eingangsrechnung")
        self.assertEqual(len(self.rt.records[er["id"]]), 4)
        refs = {a["name"]: next(t["name"] for t in self.model["types"] if t["id"] == a["ref"])
                for a in er["attrs"] if a["kind"] == "ref"}
        self.assertEqual(refs.get("Lieferant"), "Lieferant")
        self.assertEqual(refs.get("Einkauf"), "Einkauf")
        lines = self.t("Eingangsrechnungsposition")
        parent = next(a for a in lines["attrs"] if a["kind"] == "ref")
        self.assertEqual(parent["ref"], er["id"])
        sup = self.a("Eingangsrechnung", "Lieferant")["id"]
        self.assertTrue(all(isinstance(r["data"].get(sup), int) for r in self.rt.records[er["id"]]))
        # not mixed up with order lines
        self.assertFalse(any("E-Rechnung" in (m["label"] or "") + (m["source"] or "") for m in self.t("Auftragsposition")["members"]))

    def test_customers_merged_from_all_sources(self):
        k = self.t("Kunde")
        sources = {m["source"] for m in k["members"]}
        self.assertTrue({"Kundenliste_alt.xlsx", "CRM_Export.csv", "Shop_Bestellungen_Export.csv"} <= sources)

    def test_every_invoice_has_its_customer_and_order(self):
        recs = self.rt.records[self.t("Rechnung")["id"]]
        kunde, auftrag = self.a("Rechnung", "Kunde")["id"], self.a("Rechnung", "Auftrag")["id"]
        self.assertTrue(all(isinstance(r["data"].get(kunde), int) for r in recs))
        self.assertTrue(all(isinstance(r["data"].get(auftrag), int) for r in recs))

    def test_formulas_learned(self):
        texts = [f["text"] for t in self.model["types"] for f in t.get("formulas") or []]
        for expected in ["Brutto = Netto + MwSt", "MwSt = Netto × 0,07", "kg = Säcke × 60", "Gesamt = Menge × Einzelpreis",
                         "Summe € = kg × Preis/kg €"]:
            self.assertIn(expected, texts)
        self.assertTrue(any(t.startswith("Fällig am = Rechnungsdatum + Zahlungsziel") for t in texts))

    def test_processes_and_bank_reconciliation(self):
        p = next(p for p in self.model["processes"] if p["type"] == self.t("Rechnung")["id"])
        step = p["steps"][0]
        self.assertEqual(step["label"], "bezahlt")
        self.assertEqual([x["name"] for x in step.get("also", [])], ["Kontobewegung"])
        self.assertEqual(p["status"]["initial"], "offen")
        self.assertTrue(p["status"]["stale"])  # paid per bank statement, still "offen" in the book
        order = next(p for p in self.model["processes"] if p["type"] == self.t("Auftrag")["id"])
        self.assertEqual([s["label"] for s in order["steps"]], ["geliefert", "berechnet"])

    def test_work_items(self):
        work = self.rt.work(TODAY)
        kinds = {(g["title"].split(" ")[0], g["kind"]) for g in work}
        self.assertIn(("Aufträge", "late"), kinds)          # delivered, not invoiced for too long
        self.assertIn(("Artikel", "threshold"), kinds)      # below minimum stock
        self.assertTrue(any(g["kind"] == "rhythm" for g in work))
        self.assertTrue(all(g["count"] > 0 for g in work))

    def test_questions_are_few_and_meaningful(self):
        qs = self.store.q("SELECT kind, payload FROM questions WHERE status='open'")
        self.assertLessEqual(len(qs), 5)
        self.assertTrue(any("Feinkost Tidenhub" in q["payload"] for q in qs))

    def test_payments_without_reference_are_proposed_by_amount(self):
        qs = [self.store.q1("SELECT payload FROM questions WHERE id=?", (r["id"],)) for r in
              self.store.q("SELECT id FROM questions WHERE kind='payment_match' AND status='open'")]
        self.assertTrue(qs)
        self.assertTrue(all("keine Rechnungsnummer" in q["payload"] for q in qs))

    def test_fraud_warning_for_changed_bank_account(self):
        risks = [g for g in self.rt.work(TODAY) if g["kind"] == "risk"]
        self.assertEqual(len(risks), 1)
        self.assertEqual(len(risks[0]["items"]), 1)  # the phishing mail, not the genuine invoice
        self.assertIn("nie gezahlt", risks[0]["items"][0]["reason"])

    def test_data_freshness(self):
        k = self.t("Kunde")
        old = next(m for m in k["members"] if m["source"] == "Kundenliste_alt.xlsx")
        self.assertIsNotNone(old["asof"])

    def test_regrow_is_stable(self):
        before = {r["id"] for rs in self.store.all_records().values() for r in rs}
        s2 = regrow(self.store)
        after = {r["id"] for rs in self.store.all_records().values() for r in rs}
        self.assertEqual(before, after)
        self.assertEqual(s2["stats"]["new"], 0)
        self.assertEqual(s2["stats"]["changed"], 0)


class EditingRules(unittest.TestCase):
    """Creating, editing, locking – on a fresh copy so the other tests stay independent."""

    @classmethod
    def setUpClass(cls):
        cls.tmp = Path(tempfile.mkdtemp(prefix="physarum-ops-"))
        res = generate(cls.tmp / "dump", today=TODAY)
        cls.growth = res["growth"]
        cls.store = Store(cls.tmp / "firma")
        ingest(cls.store, [(p.name, p.read_bytes()) for p in res["initial"]], "Test")
        regrow(cls.store)
        cls.rt = Runtime(cls.store)
        cls.rt.ensure()

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def spec(self, name):
        return next(t for t in self.rt.model["types"] if t["name"] == name)

    def attr(self, spec, name):
        return next(a for a in spec["attrs"] if a["name"] == name)

    def test_invoice_is_locked_but_payable(self):
        inv = self.spec("Rechnung")
        rec = next(r for r in self.rt.records[inv["id"]] if not r["data"].get(self.attr(inv, "Bezahlt am")["id"]))
        with self.assertRaises(ops.OpError):
            ops.update(self.rt, rec["id"], {self.attr(inv, "Netto")["id"]: "1,00"}, "Test")
        changed = ops.set_step(self.rt, rec["id"], self.attr(inv, "Bezahlt am")["id"], None, "Test")
        self.assertIn(self.attr(inv, "Bezahlt am")["id"], changed)
        with self.assertRaises(ops.OpError):
            ops.delete(self.rt, rec["id"], "Test")
        ops.storno(self.rt, rec["id"], "falscher Kunde", "Test")
        self.rt.ensure()
        self.assertEqual(self.rt.by_id[rec["id"]]["data"][self.attr(inv, "Status")["id"]], "storniert")

    def test_create_order_with_lines_uses_numbering_and_formulas(self):
        order = self.spec("Auftrag")
        line = self.spec("Auftragsposition")
        kunde = self.rt.records[self.spec("Kunde")["id"]][0]["id"]
        art = self.rt.records[self.spec("Artikel")["id"]][0]["id"]
        rid = ops.create(self.rt, order["id"], {self.attr(order, "Kunde")["id"]: str(kunde)}, "Test",
                         [{self.attr(line, "Artikel")["id"]: str(art), self.attr(line, "Menge")["id"]: "3",
                           self.attr(line, "Einzelpreis")["id"]: "24,90"}], line["id"])
        self.rt.ensure()
        rec = self.rt.by_id[rid]
        self.assertTrue(str(rec["data"][order["key"]]).startswith(f"A-{TODAY.year}-"))
        lines = [r for r in self.rt.records[line["id"]] if r["data"].get(self.attr(line, "Auftrag")["id"]) == rid]
        self.assertEqual(len(lines), 1)
        self.assertEqual(lines[0]["data"][self.attr(line, "Gesamt")["id"]], 74.7)
        # computed total of the order from its lines
        self.assertEqual(rec["data"].get(self.attr(order, "Summe")["id"]), 74.7)

    def test_customer_with_documents_cannot_be_deleted(self):
        k = self.spec("Kunde")
        used = next(r for r in self.rt.records[k["id"]] if self.rt.backrefs.get(r["id"]))
        with self.assertRaises(ops.OpError):
            ops.delete(self.rt, used["id"], "Test")

    def test_user_edit_survives_regrowth(self):
        k = self.spec("Kunde")
        rec = next(r for r in self.rt.records[k["id"]] if r["data"].get(self.attr(k, "Ort")["id"]))
        ops.update(self.rt, rec["id"], {self.attr(k, "Ort")["id"]: "Neustadt"}, "Test")
        regrow(self.store)
        self.rt.ensure()
        self.assertEqual(self.rt.by_id[rec["id"]]["data"][self.attr(k, "Ort")["id"]], "Neustadt")

    def test_growth_with_new_file(self):
        ingest(self.store, [(p.name, p.read_bytes()) for p in self.growth], "Test")
        s = regrow(self.store)
        self.assertIn("Wartungsverträge", s["new_types"])
        self.rt.ensure()
        wv = next(t for t in self.rt.model["types"] if t["plural"] == "Wartungsverträge")
        ref = next(a for a in wv["attrs"] if a["kind"] == "ref")
        self.assertEqual(self.rt.spec(ref["ref"])["name"], "Kunde")


class WebPages(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = Path(tempfile.mkdtemp(prefix="physarum-web-"))
        cls.app = create_app(cls.tmp / "firma")
        cls.c = TestClient(cls.app)
        r = cls.c.post("/beispiel")
        jid = r.json()["job"]
        for _ in range(240):
            j = cls.c.get(f"/api/job/{jid}").json()
            if j["status"] != "running":
                break
            time.sleep(0.25)
        assert j["status"] == "done", j

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def test_all_pages_render(self):
        m = self.app.state.store.model()
        for path in ["/", "/organismus", "/ablaeufe", "/quellen", "/fragen", "/suche?q=hafen", "/verfahrensdoku"]:
            self.assertEqual(self.c.get(path).status_code, 200, path)
        for t in m["types"]:
            self.assertEqual(self.c.get(f"/t/{t['id']}").status_code, 200, t["name"])
            recs = self.app.state.store.records_of(t["id"])
            self.assertEqual(self.c.get(f"/r/{recs[0]['id']}").status_code, 200, t["name"])
            if t["kind"] != "document":
                self.assertEqual(self.c.get(f"/t/{t['id']}/neu").status_code, 200, t["name"])

    def test_exports(self):
        m = self.app.state.store.model()
        tid = m["types"][0]["id"]
        self.assertTrue(self.c.get(f"/export/{tid}.csv").content.startswith("﻿".encode()))
        self.assertEqual(self.c.get(f"/export/{tid}.xlsx").status_code, 200)
        self.assertEqual(self.c.get("/sicherung.zip").status_code, 200)

    def test_search_finds_mails(self):
        r = self.c.get("/suche?q=Versandavis")
        self.assertIn("Dokumente", r.text)


if __name__ == "__main__":
    unittest.main()
