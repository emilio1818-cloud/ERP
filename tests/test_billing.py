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


COMPANY = dict(name="Röstwerk Hafenbohne GmbH", street="Am Sandtorkai 12", zip="20457", city="Hamburg",
               vat_id="DE 123 456 789", iban="DE95 2005 0550 2461 5874 01", email="buero@hafenbohne.de",
               phone="040 123456")


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
        cls.store.kv_set("company_profile", COMPANY)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def spec(self, name):
        return next(t for t in self.rt.model["types"] if t["name"] == name)

    def attr(self, spec, name):
        return next(a for a in spec["attrs"] if a["name"] == name)

    def new_order(self, articles, delivered=True):
        order, line = self.spec("Auftrag"), self.spec("Auftragsposition")
        kunde = self.rt.records[self.spec("Kunde")["id"]][3]["id"]
        lines = [{self.attr(line, "Artikel")["id"]: str(a), self.attr(line, "Menge")["id"]: str(q)} for a, q in articles]
        rid = ops.create(self.rt, order["id"], {self.attr(order, "Kunde")["id"]: str(kunde)}, "Test", lines, line["id"])
        if delivered:
            ops.set_step(self.rt, rid, self.attr(order, "Geliefert am")["id"], None, "Test")
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
        number = billing.issue(self.rt, rid, "Test", here_ok=True)
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
        n1 = billing.issue(self.rt, a, "Test", here_ok=True)
        nid = ops.storno(self.rt, a, "Test-Storno", "Test")
        self.rt.ensure()
        n_storno = self.rt.by_id[nid]["data"][inv["key"]]
        b = ops.create(self.rt, inv["id"], {self.attr(inv, "Auftrag")["id"]: str(order_rid)}, "Test")
        n2 = billing.issue(self.rt, b, "Test", here_ok=True)
        self.assertEqual(len({n1, n_storno, n2}), 3)

    def test_issue_needs_customer_and_amount(self):
        inv = self.spec("Rechnung")
        rid = ops.create(self.rt, inv["id"], {}, "Test")
        with self.assertRaises(billing.BillingError):
            billing.issue(self.rt, rid, "Test", here_ok=True)

    def issued(self, articles=None):
        inv = self.spec("Rechnung")
        art = self.rt.records[self.spec("Artikel")["id"]]
        order_rid, _ = self.new_order(articles or [(art[4]["id"], 2)])
        rid = ops.create(self.rt, inv["id"], {self.attr(inv, "Auftrag")["id"]: str(order_rid)}, "Test")
        number = billing.issue(self.rt, rid, "Test", here_ok=True)
        self.rt.ensure()
        return inv, rid, number

    def test_an_issued_invoice_cannot_be_changed_by_any_door(self):
        inv, rid, number = self.issued()
        for aid in (self.attr(inv, "Netto")["id"], self.attr(inv, "Rechnungsdatum")["id"], inv["key"],
                    self.attr(inv, "Kunde")["id"]):
            with self.assertRaises(ops.OpError):
                ops.set_step(self.rt, rid, aid, "2026-01-02", "Test")      # a quick action is no back door
        with self.assertRaises(ops.OpError):
            ops.revert(self.rt, rid, [inv["key"]], "Test")                 # nor is "undo"
        with self.assertRaises(ops.OpError):
            ops.delete(self.rt, rid, "Test", reason="weg")
        self.assertEqual(self.store.record(rid)["data"][inv["key"]], number)
        self.assertTrue(ops.lock_state(self.rt, inv, self.store.record(rid)))

    def test_discount_line_keeps_print_and_einvoice_consistent(self):
        from physarum.einvoice import to_xrechnung
        inv = self.spec("Rechnung")
        art = self.rt.records[self.spec("Artikel")["id"]]
        order_rid, _ = self.new_order([(art[5]["id"], 3)])
        rid = ops.create(self.rt, inv["id"], {self.attr(inv, "Auftrag")["id"]: str(order_rid)}, "Test")
        self.rt.ensure()
        pos = billing.draft_positions(self.rt, self.store.record(rid))
        rate = pos[0]["rate"]
        off = round(sum(p["total"] for p in pos) * 0.1, 2)
        rows = [dict(p) for p in pos] + [dict(text="Rabatt 10 %", qty="1", price=f"-{off}", rate=str(rate * 100))]
        billing.set_positions(self.rt, rid, rows, "Test")
        number = billing.issue(self.rt, rid, "Test", here_ok=True)
        self.rt.ensure()
        rec = self.store.record(rid)
        doc = billing.document(self.rt, rec)
        gross = self.attr(inv, "Brutto")["id"]
        self.assertAlmostEqual(rec["data"][gross], doc["gross"], places=2)          # head = sum of lines
        self.assertAlmostEqual(doc["net"], round(sum(p["total"] for p in doc["positions"]), 2), places=2)
        xml = to_xrechnung(doc)
        self.assertIn(f'<cbc:PayableAmount currencyID="EUR">{doc["gross"]:.2f}</cbc:PayableAmount>', xml)
        self.assertNotIn("<cbc:PriceAmount currencyID=\"EUR\">-", xml)              # BR-27: discount by quantity
        self.assertEqual(rec["data"][inv["key"]], number)

    def test_lines_and_amounts_of_a_draft_follow_each_other(self):
        inv = self.spec("Rechnung")
        rid = ops.create(self.rt, inv["id"], {self.attr(inv, "Kunde")["id"]:
                                              str(self.rt.records[self.spec("Kunde")["id"]][2]["id"])}, "Test")
        with self.assertRaises(billing.BillingError):
            billing.issue(self.rt, rid, "Test", delivery="2026-10-01", here_ok=True)             # no lines yet
        billing.set_positions(self.rt, rid, [dict(text="Barista-Schulung", qty="2", unit="Std", price="85,00", rate="19")], "Test")
        self.rt.ensure()
        rec = self.store.record(rid)
        self.assertAlmostEqual(rec["data"][self.attr(inv, "Brutto")["id"]], 202.30, places=2)
        with self.assertRaises(ops.OpError):
            ops.update(self.rt, rid, {self.attr(inv, "Netto")["id"]: "100"}, "Test")  # amounts come from the lines
        number = billing.issue(self.rt, rid, "Test", delivery="2026-10-01", here_ok=True)
        with self.assertRaises(billing.BillingError):
            billing.issue(self.rt, rid, "Test", delivery="2026-10-01", here_ok=True)             # never twice
        self.assertTrue(number)

    def test_issued_invoice_is_dated_today_and_archived(self):
        from datetime import date
        inv, rid, number = self.issued()
        rec = self.store.record(rid)
        self.assertEqual(rec["data"][self.attr(inv, "Rechnungsdatum")["id"]], date.today().isoformat())
        self.assertTrue(rec["meta"]["delivery"])                                     # from the order's delivery
        arch = billing.archive_get(self.store, rid, "xml")
        if arch:  # complete data: the e-invoice is archived with its checksum and can never change
            import sqlite3
            with self.assertRaises(sqlite3.Error):
                with self.store.tx() as c:
                    c.execute("UPDATE archive SET content=? WHERE id=?", (b"x", arch["id"]))

    def test_paid_can_be_taken_back_later_and_status_follows(self):
        inv, rid, number = self.issued()
        proc = next(p for p in self.rt.model["processes"] if p["type"] == inv["id"])
        paid = next(x["attr"] for x in [proc["steps"][0]] + proc["steps"][0].get("also", []) if x["source"] == "own")
        status = proc["status"]["attr"]
        ops.set_step(self.rt, rid, paid, None, "Test")
        self.rt.ensure()
        self.assertEqual(self.rt.by_id[rid]["data"][status], "bezahlt")
        cid = self.store.q1("SELECT id FROM changes WHERE record_id=? AND attr=? ORDER BY id DESC", (rid, paid))["id"]
        ops.revert_change(self.rt, rid, cid, "Test")                     # days later, from the history
        self.rt.ensure()
        d = self.rt.by_id[rid]["data"]
        self.assertIsNone(d.get(paid))
        self.assertNotEqual(d.get(status), "bezahlt")
        ops.set_step(self.rt, rid, paid, None, "Test")
        ops.update(self.rt, rid, {paid: ""}, "Test")                       # emptied by hand: status goes back too
        self.rt.ensure()
        self.assertNotEqual(self.rt.by_id[rid]["data"].get(status), "bezahlt")
        self.assertEqual(self.store.record(rid)["data"][inv["key"]], number)

    def test_supplier_invoices_are_not_ours_to_cancel(self):
        ein = next((t for t in self.rt.model["types"] if t["name"] == "Eingangsrechnung"), None)
        if not ein:
            self.skipTest("keine Eingangsrechnungen in den Daten")
        self.assertTrue(ein.get("incoming"))
        self.assertFalse(billing.is_invoice(ein))
        rid = self.rt.records[ein["id"]][0]["id"]
        with self.assertRaises(billing.BillingError):
            billing.cancel(self.rt, rid, "Test", "Test")

    def test_cancelled_invoice_does_not_bill_the_order(self):
        from datetime import date, timedelta
        from physarum.process import compute_work
        inv, order = self.spec("Rechnung"), self.spec("Auftrag")
        order_rid, _ = self.new_order([(self.rt.records[self.spec("Artikel")["id"]][1]["id"], 1)])
        rid = ops.create(self.rt, inv["id"], {self.attr(inv, "Auftrag")["id"]: str(order_rid)}, "Test")
        billing.issue(self.rt, rid, "Test", here_ok=True)
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

    def test_the_tax_advisor_gets_one_booking_per_invoice_and_rate(self):
        import hashlib
        import io
        import zipfile
        from datetime import date
        from physarum import taxexport
        inv = self.spec("Rechnung")
        art = self.rt.records[self.spec("Artikel")["id"]]
        rate = self.attr(self.spec("Artikel"), "MwSt")["id"]
        coffee = next(r for r in art if r["data"].get(rate) in (0.07, 7))
        rid = ops.create(self.rt, inv["id"], {self.attr(inv, "Kunde")["id"]:
                                              str(self.rt.records[self.spec("Kunde")["id"]][5]["id"])}, "Test")
        billing.set_positions(self.rt, rid, [dict(text="Hafenmischung 1 kg", qty="4", price="18,50", rate="7"),
                                             dict(text="Barista-Schulung", qty="2", unit="Std", price="85,00", rate="19")], "Test")
        number = billing.issue(self.rt, rid, "Test", delivery=date.today().isoformat(), here_ok=True)
        _, rid2, number2 = self.issued([(coffee["id"], 3)])
        billing.cancel(self.rt, rid2, "Falscher Kunde", "Test")
        self.rt.ensure()
        von, bis, label = taxexport.period("monat", date.today().year, date.today().month)
        content, data = taxexport.build(self.rt, von, bis, label, "Test")
        z = zipfile.ZipFile(io.BytesIO(content))
        stapel = z.read(next(n for n in z.namelist() if n.startswith("EXTF"))).decode("cp1252").split("\r\n")
        head = stapel[0].split(";")
        self.assertEqual(head[:5], ['"EXTF"', "700", "21", '"Buchungsstapel"', "9"])
        self.assertEqual(head[14:16], [von.strftime("%Y%m%d"), bis.strftime("%Y%m%d")])
        self.assertEqual(len(stapel[1].split(";")), 116)
        mine = [r.split(";") for r in stapel[2:] if f'"{number}"' in r]
        self.assertEqual(sorted(r[7] for r in mine), ["8300", "8400"])          # 7 % and 19 % on their own accounts
        self.assertEqual({r[1] for r in mine}, {'"S"'})
        self.assertEqual(sorted(r[0] for r in mine), ["202,30", "79,18"])        # 2 × 85 € + 19 %, 4 × 18,50 € + 7 %
        storno = [r.split(";") for r in stapel[2:] if r and r.split(";")[1] == '"H"']
        self.assertTrue(storno)                                                   # the cancellation, the other way round
        self.assertTrue(all(len(r.split(";")) == 116 for r in stapel[2:] if r))
        ust = z.read(next(n for n in z.namelist() if n.startswith("Umsatzsteuer"))).decode("utf-8-sig")
        self.assertIn("Umsätze 19 %", ust)
        self.assertIn("Umsätze 7 %", ust)
        proto = z.read("Pruefprotokoll.txt").decode()
        for name in z.namelist():
            if name != "Pruefprotokoll.txt":
                self.assertIn(f"{hashlib.sha256(z.read(name)).hexdigest()}  {name}", proto)
        self.assertIn("unverändert", proto)
        # the same customer keeps its debtor number from one export to the next
        again = taxexport.collect(self.rt, von, bis)
        self.assertEqual({r["number"]: r["account"] for r in data["out"]}, {r["number"]: r["account"] for r in again["out"]})

    def test_cells_that_would_run_as_formulas_in_excel_are_defused(self):
        from physarum.taxexport import _csv
        text = _csv([["=HYPERLINK(\"http://x\")", "-12,50", "+49 40 123", "@SUM(A1)", "Kunde"]]).decode("utf-8-sig")
        self.assertIn("'=HYPERLINK", text)
        self.assertFalse(any(cell.lstrip('"').startswith(("=", "@")) for cell in text.strip().split(";")))
        self.assertIn(";-12,50;", text)                                           # a negative amount stays a number
        self.assertIn(";'+49 40 123;", text)
        self.assertIn(";'@SUM(A1);", text)


class NewBookAfterIssuing(unittest.TestCase):
    """The accountant exports the invoice book again – with a changed amount, a missing row and a
    number that was meanwhile issued here. What was issued here stays as issued; what the other
    program issued follows its newest list, logged; Heute says what differs."""

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
            store.kv_set("company_profile", COMPANY)
            mine = ops.create(rt, inv["id"], {oref["id"]: str(rt.records[order["id"]][0]["id"])}, "Test")
            number = billing.issue(rt, mine, "Test", delivery="2026-10-01", extra_ok=True, here_ok=True)
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
            # issued by the other program: its newest list corrects it – taken over, logged, shown
            self.assertAlmostEqual(ch["data"][net["id"]], 999.99, places=2)
            was, now, _src, _when = ch["meta"]["corrected"][net["id"]]
            self.assertAlmostEqual(was, float(old.replace(".", "").replace(",", ".")), places=2)
            self.assertAlmostEqual(now, 999.99, places=2)
            self.assertTrue(store.q1("SELECT 1 FROM changes WHERE record_id=? AND attr=? AND note LIKE "
                                     "'nach der Ausstellung geändert%'", (ch["id"], net["id"])))
            self.assertIn(gone_no, by_no)                                        # an issued invoice is never removed
            self.assertEqual(rt.by_id[mine]["data"][net["id"]], my_net)          # the one issued here is untouched
            # the file's twin does not become a second invoice with the issued number (it would be dunned) …
            self.assertEqual(len(by_no[number]), 1)
            self.assertEqual(by_no[number][0]["id"], mine)
            self.assertIn(net["id"], rt.by_id[mine]["meta"].get("collision") or {})
            group = next(g for g in rt.work() if g["kind"] == "integrity")       # … and all of it is on Heute
            reasons = {(x["rid"], x["reason"].split(" ")[0]) for x in group["items"]}
            self.assertIn(ch["id"], {rid for rid, _ in reasons})
            seen = next(x for x in group["items"] if x["rid"] == ch["id"])
            self.assertIn("nach der Ausstellung geändert", seen["reason"])
            from starlette.testclient import TestClient
            from physarum.web.app import create_app
            r = TestClient(create_app(tmp / "firma")).post(seen["seen"], headers={"origin": "http://testserver"})
            self.assertEqual(r.status_code, 200, r.text)
            rt = Runtime(store)
            rt.ensure()
            group = next(g for g in rt.work() if g["kind"] == "integrity")
            self.assertNotIn(ch["id"], {x["rid"] for x in group["items"]})   # seen: off Heute
            self.assertIn(by_no[gone_no][0]["id"], {rid for rid, _ in reasons})
            self.assertTrue(any(rid == mine and "andere Rechnung" in x["reason"] for x in group["items"]
                                for rid in [x["rid"]]))
            self.assertNotEqual(billing.next_free_number(rt, inv), number)
            # the file corrected: the mark goes away
            time.sleep(1)
            ingest(store, [("Rechnungsausgangsbuch.csv", ("\n".join([head] + body[:-1]) + "\n").encode("cp1252"))], "Test")
            regrow(store)
            rt = Runtime(store)
            rt.ensure()
            self.assertFalse(rt.by_id[mine]["meta"].get("collision"))
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


class SealedLog(unittest.TestCase):
    def test_the_change_log_cannot_be_rewritten_and_tampering_shows(self):
        import sqlite3
        tmp = Path(tempfile.mkdtemp(prefix="physarum-seal-"))
        try:
            st = Store(tmp)
            with st.tx() as c:
                for i in range(4):
                    c.execute("INSERT INTO changes(record_id, ts, actor, kind, note) VALUES(?,?,?,?,?)",
                              (i, "2026-10-29T10:00:00", "Anna", "edit", f"Eintrag {i}"))
            ok = st.verify_chain()
            self.assertTrue(ok["ok"])
            self.assertEqual(ok["n"], 4)
            for sql in ("UPDATE changes SET note='anders' WHERE id=2", "DELETE FROM changes WHERE id=2"):
                with self.assertRaises(sqlite3.Error):
                    with st.tx() as c:
                        c.execute(sql)
            c = st.conn()
            c.execute("DROP TRIGGER changes_keep")                                 # at the database, past the app
            c.execute("UPDATE changes SET note='anders' WHERE id=3")
            bad = st.verify_chain()
            self.assertFalse(bad["ok"])
            self.assertEqual(bad["broken_at"], 3)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()


class OwnEInvoice(unittest.TestCase):
    """The firm sent one invoice as XRechnung, and the file is in its folder: it is no invoice from a supplier,
    and what it says about the seller is what the firm's own data page needs."""

    CII = """<?xml version="1.0" encoding="UTF-8"?>
<rsm:CrossIndustryInvoice xmlns:rsm="urn:un:unece:uncefact:data:standard:CrossIndustryInvoice:100"
  xmlns:ram="urn:un:unece:uncefact:data:standard:ReusableAggregateBusinessInformationEntity:100"
  xmlns:udt="urn:un:unece:uncefact:data:standard:UnqualifiedDataType:100">
 <rsm:ExchangedDocument><ram:ID>2026-0394</ram:ID><ram:TypeCode>380</ram:TypeCode>
  <ram:IssueDateTime><udt:DateTimeString format="102">20260831</udt:DateTimeString></ram:IssueDateTime></rsm:ExchangedDocument>
 <rsm:SupplyChainTradeTransaction>
  <ram:ApplicableHeaderTradeAgreement>
   <ram:SellerTradeParty><ram:Name>Ostermeier Gebäudedienste GmbH</ram:Name>
    <ram:DefinedTradeContact><ram:TelephoneUniversalCommunication><ram:CompleteNumber>05121 99876-0</ram:CompleteNumber>
    </ram:TelephoneUniversalCommunication></ram:DefinedTradeContact>
    <ram:PostalTradeAddress><ram:PostcodeCode>31135</ram:PostcodeCode><ram:LineOne>Bavenstedter Straße 48</ram:LineOne>
     <ram:CityName>Hildesheim</ram:CityName><ram:CountryID>DE</ram:CountryID></ram:PostalTradeAddress>
    <ram:URIUniversalCommunication><ram:URIID schemeID="EM">buchhaltung@ostermeier-gd.example</ram:URIID></ram:URIUniversalCommunication>
    <ram:SpecifiedTaxRegistration><ram:ID schemeID="VA">DE312456789</ram:ID></ram:SpecifiedTaxRegistration>
   </ram:SellerTradeParty>
   <ram:BuyerTradeParty><ram:Name>Stadt Hildesheim</ram:Name></ram:BuyerTradeParty>
  </ram:ApplicableHeaderTradeAgreement>
  <ram:ApplicableHeaderTradeSettlement><ram:InvoiceCurrencyCode>EUR</ram:InvoiceCurrencyCode>
   <ram:SpecifiedTradeSettlementPaymentMeans><ram:TypeCode>58</ram:TypeCode>
    <ram:PayeePartyCreditorFinancialAccount><ram:IBANID>DE57259501300912345678</ram:IBANID></ram:PayeePartyCreditorFinancialAccount>
   </ram:SpecifiedTradeSettlementPaymentMeans>
   <ram:ApplicableTradeTax><ram:CalculatedAmount>921.50</ram:CalculatedAmount><ram:TypeCode>VAT</ram:TypeCode>
    <ram:BasisAmount>4850.00</ram:BasisAmount><ram:CategoryCode>S</ram:CategoryCode><ram:RateApplicablePercent>19</ram:RateApplicablePercent>
   </ram:ApplicableTradeTax>
   <ram:SpecifiedTradeSettlementHeaderMonetarySummation><ram:LineTotalAmount>4850.00</ram:LineTotalAmount>
    <ram:TaxBasisTotalAmount>4850.00</ram:TaxBasisTotalAmount><ram:TaxTotalAmount currencyID="EUR">921.50</ram:TaxTotalAmount>
    <ram:GrandTotalAmount>5771.50</ram:GrandTotalAmount><ram:DuePayableAmount>5771.50</ram:DuePayableAmount>
   </ram:SpecifiedTradeSettlementHeaderMonetarySummation>
  </ram:ApplicableHeaderTradeSettlement>
 </rsm:SupplyChainTradeTransaction>
</rsm:CrossIndustryInvoice>
"""

    def test_it_is_ours_and_says_who_we_are(self):
        tmp = Path(tempfile.mkdtemp(prefix="physarum-own-xr-"))
        self.addCleanup(shutil.rmtree, tmp, True)
        book = ["Rechnungsausgangsbuch 2026 · Ostermeier Gebäudedienste GmbH", "",
                "Re.-Nr.;Datum;Kunde;Brutto;fällig am"]
        book += [f"2026-{390 + i:04d};{i + 1:02d}.08.2026;Kunde {i % 3};{100 + i},00;{i + 15:02d}.08.2026" for i in range(4)]
        book.append("2026-0394;31.08.2026;Stadt Hildesheim;5.771,50;30.09.2026")
        store = Store(tmp / "firma")
        ingest(store, [("Rechnungsausgangsbuch.csv", "\n".join(book).encode("utf-8")),
                       ("Stadt_XRechnung/XRechnung_2026-0394.xml", self.CII.encode("utf-8"))], "T")
        regrow(store)
        rt = Runtime(store)
        rt.ensure()
        self.assertFalse([t for t in rt.model["types"] if t.get("incoming")])  # no supplier: the firm itself
        firm = billing.guess_company(rt)
        self.assertEqual({k: firm.get(k) for k in ("name", "street", "zip", "city", "vat_id", "email", "phone", "iban")},
                         dict(name="Ostermeier Gebäudedienste GmbH", street="Bavenstedter Straße 48", zip="31135",
                              city="Hildesheim", vat_id="DE312456789", email="buchhaltung@ostermeier-gd.example",
                              phone="05121 99876-0", iban="DE57259501300912345678"))


class OrderNamesItsInvoice(unittest.TestCase):
    """A cleaning firm's special jobs: the order list has a column for the invoice's number, the invoice book
    knows nothing of orders. "+ Rechnung" on a finished job gives a filled draft, the job then names it; the
    first invoice written here asks whether the old program stops writing invoices."""

    @classmethod
    def setUpClass(cls):
        from datetime import date, timedelta
        from starlette.testclient import TestClient
        from physarum.web.app import create_app
        cls.tmp = Path(tempfile.mkdtemp(prefix="physarum-ownref-"))
        today = date.today()
        de = lambda d: d.strftime("%d.%m.%Y")  # noqa: E731
        kunden = ["Kd.-Nr.;Firma;Straße;PLZ;Ort"] + [f"{10001 + i};{n};Markt {i + 1};31134;Hildesheim" for i, n in enumerate(
            ["Kita Sonnenblume", "Autohaus Wendt GmbH", "Praxis am Markt", "Pension Domblick"])]
        orders = ["Auftrag;Eingang;Kd.-Nr.;Leistung;erledigt am;Preis netto;Re.-Nr."]
        book = ["Re.-Nr.;Datum;Kd.-Nr.;Leistung;Netto;USt;Brutto;fällig am"]
        eur = lambda x: f"{x:.2f}".replace(".", ",")  # noqa: E731
        for i in range(20):
            d = today - timedelta(days=200 - 9 * i)
            kd, net, sa = 10001 + i % 4, 300.0 + 40 * i, f"SA-26-{i + 1:03d}"
            no = f"2026-{i + 1:04d}" if i not in (17, 19) else ""
            orders.append(f"{sa};{de(d)};{kd};Grundreinigung Objekt {i + 1};{de(d + timedelta(days=5))};{eur(net)};{no}")
            if no:
                book.append(f"{no};{de(d + timedelta(days=6))};{kd};{('Glas', 'Teppich', 'Bau')[i % 3]}reinigung;{eur(net)};"
                            f"{eur(net * 0.19)};{eur(net * 1.19)};{de(d + timedelta(days=20))}")
        files = {"Kunden.csv": kunden, "Sonderauftraege.csv": orders, "Rechnungsausgangsbuch.csv": book}
        cls.store = Store(cls.tmp / "firma")
        ingest(cls.store, [(n, ("\n".join(rows) + "\n").encode("utf-8")) for n, rows in files.items()], "Test")
        regrow(cls.store)
        cls.store.kv_set("company_profile", COMPANY)
        cls.client = TestClient(create_app(cls.tmp / "firma"))
        cls.rt = Runtime(cls.store)
        cls.rt.ensure()

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def test_a_finished_job_is_invoiced_from_its_order(self):
        import re
        rt = self.rt
        heute = self.client.get("/").text
        links = re.findall(r'href="/t/(\w+)/neu\?aus=(\d+)"', heute)
        self.assertEqual(len(links), 2, "the two finished jobs without an invoice")
        tid, case = links[0][0], int(links[0][1])
        form = self.client.get(f"/t/{tid}/neu?aus={case}").text
        self.assertIn("Kunde, Leistung, Preis und Leistungsdatum übernommen", form)
        self.assertIn(f'name="aus" value="{case}"', form)
        spec = rt.spec(tid)
        values = dict(re.findall(r'name="(a_\w+)" (?:[^>]*?)value="([^"]*)"', form))
        r = self.client.post(f"/t/{tid}/neu", data=dict(values, aus=str(case)), headers={"origin": "http://testserver"},
                             follow_redirects=False)
        self.assertEqual(r.status_code, 303, r.text[:500])
        rid = int(re.search(r"/r/(\d+)", r.headers["location"]).group(1))
        rt = Runtime(self.store)
        rt.ensure()
        draft = rt.by_id[rid]
        self.assertTrue(billing.is_draft(draft))
        party = billing.party_attr(rt, spec)
        self.assertEqual(draft["data"][party["id"]], next(rt.by_id[case]["data"][a["id"]] for a in rt.spec(
            rt.by_id[case]["type"])["attrs"] if a.get("ref") == party["ref"]))           # the job's customer
        pos = billing.draft_positions(rt, draft)
        self.assertEqual([(p["text"], p["price"], p["rate"]) for p in pos], [("Grundreinigung Objekt 18", 980.0, 0.19)])
        self.assertIn(rid, rt.by_id[case]["data"].values())                      # the job names its invoice now
        self.assertIn(f"/r/{rid}", self.client.get("/").text)                    # Heute: "Entwurf öffnen", no 2nd draft
        with self.assertRaises(billing.BillingError) as e:
            billing.issue(rt, rid, "Test")                                       # the old program numbered so far
        self.assertIn("Ab jetzt schreiben Sie Rechnungen hier", str(e.exception))
        number = billing.issue(rt, rid, "Test", here_ok=True)
        self.assertEqual(number, "2026-0020")                                    # after the last one of the book
        self.assertEqual(self.store.decisions("invoicing").get(tid), "hier")
        rt = Runtime(self.store)
        rt.ensure()
        self.assertIsNone(billing.handover(rt, spec))                            # asked once
        self.assertNotIn(f"aus={case}", self.client.get("/").text)               # no longer "not invoiced"
