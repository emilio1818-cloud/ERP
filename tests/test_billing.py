"""An invoice made here: from the order, as a draft, issued with a number, cancelled with a document."""
import shutil
import tempfile
import unittest
from pathlib import Path

from physarum import billing, ops
from physarum.demo.generate import generate
from physarum.grow import ingest, regrow
from physarum.runtime import Runtime
from physarum.store import Store


class InvoiceFromOrder(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = Path(tempfile.mkdtemp(prefix="physarum-bill-"))
        res = generate(cls.tmp / "dump")
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

    def new_order(self, articles):
        order, line = self.spec("Auftrag"), self.spec("Auftragsposition")
        kunde = self.rt.records[self.spec("Kunde")["id"]][3]["id"]
        lines = [{self.attr(line, "Artikel")["id"]: str(a), self.attr(line, "Menge")["id"]: str(q)} for a, q in articles]
        rid = ops.create(self.rt, order["id"], {self.attr(order, "Kunde")["id"]: str(kunde)}, "Test", lines, line["id"])
        self.rt.ensure()
        return rid, kunde

    def test_invoice_from_order_takes_customer_amount_and_vat_by_article(self):
        art = self.spec("Artikel")
        rate = self.attr(art, "MwSt")["id"]
        price = self.attr(art, "VK netto €")["id"]
        coffee = next(r for r in self.rt.records[art["id"]] if r["data"].get(rate) in (0.07, 7))
        tool = next((r for r in self.rt.records[art["id"]] if r["data"].get(rate) in (0.19, 19)), None)
        items = [(coffee["id"], 2)] + ([(tool["id"], 1)] if tool else [])
        order_rid, kunde = self.new_order(items)
        inv = self.spec("Rechnung")
        rid = ops.create(self.rt, inv["id"], {self.attr(inv, "Auftrag")["id"]: str(order_rid)}, "Test")
        self.rt.ensure()
        rec = self.rt.by_id[rid]
        d = rec["data"]
        self.assertEqual(d[self.attr(inv, "Kunde")["id"]], kunde)          # the order's customer
        net = round(sum(self.rt.by_id[a]["data"][price] * q for a, q in items), 2)
        self.assertAlmostEqual(d[self.attr(inv, "Netto")["id"]], net, places=2)
        def frac(x):
            return x if x <= 1 else x / 100
        tax = round(sum(self.rt.by_id[a]["data"][price] * q * frac(self.rt.by_id[a]["data"][rate]) for a, q in items), 2)
        self.assertAlmostEqual(d[self.attr(inv, "MwSt")["id"]], tax, places=2)  # by the articles' rates
        self.assertIsNone(d.get(inv["key"]))                                     # a draft has no number yet
        self.assertIsNone(ops.lock_state(self.rt, inv, self.store.record(rid)))  # and can be changed
        number = billing.issue(self.rt, rid, "Test")
        self.rt.ensure()
        full = self.store.record(rid)
        self.assertEqual(full["data"][inv["key"]], number)
        self.assertTrue(ops.lock_state(self.rt, inv, full))
        self.assertEqual(len(full["meta"]["positions"]), len(items))           # lines as issued
        self.assertTrue(full["meta"]["recipient"]["name"])
        due = self.attr(inv, "Fällig am")["id"]
        self.assertTrue(full["data"].get(due))

    def test_numbers_are_never_given_twice(self):
        inv = self.spec("Rechnung")
        order_rid, _ = self.new_order([(self.rt.records[self.spec("Artikel")["id"]][0]["id"], 1)])
        a = ops.create(self.rt, inv["id"], {self.attr(inv, "Auftrag")["id"]: str(order_rid)}, "Test")
        n1 = billing.issue(self.rt, a, "Test")
        nid = ops.storno(self.rt, a, "Test-Storno", "Test")
        self.rt.ensure()
        n_storno = self.rt.by_id[nid]["data"][inv["key"]]
        b = ops.create(self.rt, inv["id"], {self.attr(inv, "Auftrag")["id"]: str(order_rid)}, "Test")
        n2 = billing.issue(self.rt, b, "Test")
        self.assertEqual(len({n1, n_storno, n2}), 3)

    def test_issue_needs_customer_and_amount(self):
        inv = self.spec("Rechnung")
        rid = ops.create(self.rt, inv["id"], {}, "Test")
        with self.assertRaises(billing.BillingError):
            billing.issue(self.rt, rid, "Test")

    def test_cancelled_invoice_does_not_bill_the_order(self):
        from datetime import date, timedelta
        from physarum.process import compute_work
        inv, order = self.spec("Rechnung"), self.spec("Auftrag")
        order_rid, _ = self.new_order([(self.rt.records[self.spec("Artikel")["id"]][1]["id"], 1)])
        ops.set_step(self.rt, order_rid, self.attr(order, "Geliefert am")["id"], None, "Test")
        rid = ops.create(self.rt, inv["id"], {self.attr(inv, "Auftrag")["id"]: str(order_rid)}, "Test")
        billing.issue(self.rt, rid, "Test")
        ops.storno(self.rt, rid, "falsch", "Test")
        self.rt.ensure()
        later = date.today() + timedelta(days=60)
        work = compute_work(self.rt.model, self.rt.records, self.rt.mentions, later, ledger=self.rt.ledger)
        waiting = {x["rid"] for g in work if g.get("step") == "berechnet" for x in g["items"]}
        self.assertIn(order_rid, waiting)  # the cancelled invoice does not count as "berechnet"

    def test_a_draft_is_not_owed(self):
        from datetime import date, timedelta
        from physarum.process import compute_work, kpis
        inv, order = self.spec("Rechnung"), self.spec("Auftrag")
        before = {k["type"]: k["current"] for k in kpis(self.rt.model, self.rt.records)}
        order_rid, _ = self.new_order([(self.rt.records[self.spec("Artikel")["id"]][2]["id"], 3)])
        ops.set_step(self.rt, order_rid, self.attr(order, "Geliefert am")["id"], None, "Test")
        rid = ops.create(self.rt, inv["id"], {self.attr(inv, "Auftrag")["id"]: str(order_rid)}, "Test")
        self.rt.ensure()
        self.assertNotIn(rid, self.rt.ledger)                       # no receivable, no payment matching
        self.assertEqual(before.get(inv["id"]), {k["type"]: k["current"] for k in kpis(self.rt.model, self.rt.records)}
                         .get(inv["id"]))                           # no revenue
        later = date.today() + timedelta(days=60)
        work = compute_work(self.rt.model, self.rt.records, self.rt.mentions, later, ledger=self.rt.ledger)
        self.assertFalse(any(x["rid"] == rid for g in work if g["kind"] in ("overdue", "late", "soon") for x in g["items"]))
        drafts = next(g for g in work if g["kind"] == "draft")
        self.assertIn(rid, {x["rid"] for x in drafts["items"]})     # but it is not forgotten
        waiting = [x for g in work if g.get("step") == "berechnet" for x in g["items"] if x["rid"] == order_rid]
        self.assertTrue(waiting and all(x.get("draft") == rid for x in waiting))  # open the draft, not a second one
        self.assertTrue(self.rt.title(rid).startswith("Entwurf"))

class NewBookAfterIssuing(unittest.TestCase):
    """The accountant exports the invoice book again – with a changed amount, a missing row and a
    number that was meanwhile issued here. Issued invoices stay as issued, and Heute says what differs."""

    def test_issued_invoices_are_not_changed_and_differences_are_shown(self):
        import time
        tmp = Path(tempfile.mkdtemp(prefix="physarum-book-"))
        try:
            res = generate(tmp / "dump")
            store = Store(tmp / "firma")
            ingest(store, [(p.name, p.read_bytes()) for p in res["initial"]], "Test")
            regrow(store)
            rt = Runtime(store)
            rt.ensure()
            inv = next(t for t in rt.model["types"] if t["name"] == "Rechnung")
            net = next(a for a in inv["attrs"] if a["name"] == "Netto")
            order = next(t for t in rt.model["types"] if t["name"] == "Auftrag")
            oref = next(a for a in inv["attrs"] if a["name"] == "Auftrag")
            mine = ops.create(rt, inv["id"], {oref["id"]: str(rt.records[order["id"]][0]["id"])}, "Test")
            number = billing.issue(rt, mine, "Test")
            rt.ensure()
            my_net = rt.by_id[mine]["data"][net["id"]]
            src = next(p for p in res["initial"] if p.name == "Rechnungsausgangsbuch.csv")
            lines = src.read_bytes().decode("cp1252").splitlines()
            head, body = lines[0], [x for x in lines[1:] if not x.startswith("Summe")]
            cols = head.split(";")
            i_net = cols.index("Netto")
            row = body[100].split(";")
            changed_no, old = row[0], row[i_net]
            row[i_net] = "999,99"
            body[100] = ";".join(row)
            gone_no = body[50].split(";")[0]
            del body[50]
            twin = body[-1].split(";")
            twin[0], twin[i_net] = number, "55,00"
            body.append(";".join(twin))
            time.sleep(1)
            ingest(store, [("Rechnungsausgangsbuch.csv", ("\n".join([head] + body) + "\n").encode("cp1252"))], "Test")
            regrow(store)
            rt = Runtime(store)
            rt.ensure()
            by_no = {}
            for r in rt.records[inv["id"]]:
                by_no.setdefault(r["data"].get(inv["key"]), []).append(r)
            ch = by_no[changed_no][0]
            self.assertAlmostEqual(ch["data"][net["id"]], float(old.replace(".", "").replace(",", ".")), places=2)
            self.assertIn(net["id"], ch["meta"].get("conflicts") or {})          # recorded, not applied
            self.assertIn(gone_no, by_no)                                        # an issued invoice is never removed
            self.assertEqual(rt.by_id[mine]["data"][net["id"]], my_net)          # the one issued here is untouched
            self.assertEqual(len(by_no[number]), 2)                              # the file's twin stays separate ...
            group = next(g for g in rt.work() if g["kind"] == "integrity")       # ... and all of it is on Heute
            reasons = {(x["rid"], x["reason"].split(" ")[0]) for x in group["items"]}
            self.assertIn(ch["id"], {rid for rid, _ in reasons})
            self.assertIn(by_no[gone_no][0]["id"], {rid for rid, _ in reasons})
            self.assertIn(mine, {rid for rid, _ in reasons})
            self.assertNotEqual(billing.next_free_number(rt, inv), number)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
