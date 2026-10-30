"""Lessons from a tax advisor's audit and a first-time user: what an invoice, the books and the
seal must get right whatever the firm's files look like.

Each test is one finding of the independent review that once gave a wrong answer.
"""
import sqlite3
import unittest
from datetime import date, timedelta

from starlette.testclient import TestClient

from physarum import billing, ops, taxexport
from physarum.web.app import create_app
from tests.test_craft_firm import _eur, _supplier_invoice
from tests.test_unseen_firm import Firm, _type, csv

TODAY = date.today()
CUSTOMERS = csv("Kd-Nr;Firma;Straße;PLZ;Ort;E-Mail;USt-IdNr;Leitweg-ID",
                [["K-01", "Elektro Funke GmbH", "Hauptstraße 1", "01067", "Dresden", "rechnung@funke.example", "", ""],
                 ["K-02", "Bäckerei Krume OHG", "Marktplatz 2", "01069", "Dresden", "info@krume.example", "", ""],
                 ["K-03", "Holzbau Gruber GmbH", "Ring 4", "1020", "Wien", "office@gruber.example", "ATU12345678", ""],
                 ["K-04", "Stadt Pirna", "Am Markt 1", "01796", "Pirna", "e-rechnung@pirna.example", "",
                  "14628000-0001-38"]])


def _book(n=8, start=date(2026, 3, 5), head="RE"):
    """An old program's invoice book; 80 % of its numbers follow one scheme – too few to learn it."""
    rows = []
    for i in range(n):
        d = start + timedelta(days=3 * i)
        net = 100 * (i + 1)
        rows.append([f"{head}-2026-{i + 1:04d}", d.strftime("%d.%m.%Y"), f"K-0{i % 2 + 1}", f"Arbeiten {i}",
                     _eur(net), _eur(net * 0.19), _eur(net * 1.19), "offen"])
    rows.append(["GS-2026-0001", "20.03.2026", "K-01", "Gutschrift", "-50,00", "-9,50", "-59,50", "offen"])
    rows.append(["AR-2026-0001", "25.03.2026", "K-02", "Abschlag", "1000,00", "190,00", "1190,00", "offen"])
    return csv("Rechnungsnr;Datum;Kd-Nr;Betreff;Netto;USt;Brutto;Status", rows)


class Invoicing(unittest.TestCase):
    def setUp(self):
        self.f = Firm()

    def tearDown(self):
        self.f.close()

    def grow(self, files, **company):
        self.f.feed(files)
        self.f.store.kv_set("company_profile", dict(dict(name="Muster Bau GmbH", street="Hauptstr. 1", zip="01067",
                                                         city="Dresden", vat_id="DE123456789", iban="DE02120300000000202051",
                                                         email="info@muster.example", phone="0351 123456"), **company))
        return self.f.rt()

    def issue(self, rt, customer: str, lines, **kw) -> int:
        inv = _type(rt, "Rechnung")
        cust = next(a for a in inv["attrs"] if a["kind"] == "ref" and rt.spec(a["ref"])["name"] == "Kunde")
        kunde = next(r["id"] for r in rt.records[cust["ref"]] if rt.title(r["id"]).startswith(customer))
        rid = ops.create(rt, inv["id"], {cust["id"]: str(kunde)}, "Test")
        billing.set_positions(rt, rid, [dict(text=t, qty="1", price=str(p), rate=str(r)) for t, p, r in lines], "Test")
        billing.issue(rt, rid, "Test", delivery=TODAY.isoformat(), **kw, here_ok=True)
        rt.ensure()
        return rid

    def test_a_number_is_never_given_twice_and_the_printed_date_is_stored(self):
        rt = self.grow([("Kunden.csv", CUSTOMERS), ("Rechnungsbuch_alt.csv", _book())])
        inv = _type(rt, "Rechnung")
        old = {str(r["data"][inv["key"]]) for r in rt.records[inv["id"]]}
        a, b = self.issue(rt, "Elektro", [("Prüfung", 150, 19)]), self.issue(rt, "Bäckerei", [("Reparatur", 80, 19)])
        na, nb = rt.by_id[a]["data"][inv["key"]], rt.by_id[b]["data"][inv["key"]]
        self.assertNotIn(na, old)                                    # RE-2026-0001 exists in the old book
        self.assertNotIn(nb, old | {na})
        da = billing.date_attr(rt, inv)
        self.assertEqual(rt.by_id[a]["data"][da], TODAY.isoformat())  # stored as printed, also without a learned course
        von, bis, _ = taxexport.period("monat", TODAY.year, TODAY.month)
        data = taxexport.collect(rt, von, bis)
        self.assertEqual({r["number"] for r in data["out"]}, {na, nb})  # in the batch of its month

    def test_only_invoices_written_here_are_booked(self):
        rt = self.grow([("Kunden.csv", CUSTOMERS), ("Rechnungsbuch_alt.csv", _book())])
        data = taxexport.collect(rt, date(2026, 3, 1), date(2026, 3, 31))
        self.assertEqual(data["out"], [])                            # booked by the program that wrote them
        self.assertEqual(len(data["copies"]), 10)
        book = taxexport.books(data)["Rechnungsausgangsbuch.csv"].decode("utf-8-sig")
        self.assertIn("Datei (anderes Programm, nicht im Stapel)", book)
        extf = taxexport.extf(data, "03/2026").decode("cp1252").splitlines()
        self.assertEqual(len(extf), 2)                               # header and column names, no booking
        with self.assertRaises(ops.OpError):                         # nor cancelled here
            ops.storno(rt, rt.records[_type(rt, "Rechnung")["id"]][0]["id"], "falsch", "Test")

    def test_a_kleinunternehmer_states_no_vat(self):
        rt = self.grow([("Kunden.csv", CUSTOMERS), ("Rechnungsbuch_alt.csv", _book())], kleinunternehmer=True)
        rid = self.issue(rt, "Elektro", [("Grafik", 500, 19)])
        doc = billing.document(rt, rt.store.record(rid))
        self.assertEqual(doc["gross"], 500.0)
        self.assertEqual([g["tax"] for g in doc["groups"]], [0.0])
        from physarum.einvoice import to_xrechnung
        xml = to_xrechnung(doc)
        self.assertIn("<cbc:ID>E</cbc:ID>", xml)
        self.assertNotIn("<cbc:ID>S</cbc:ID>", xml)

    def test_an_xrechnung_says_country_leitweg_id_and_when_to_pay(self):
        from physarum.einvoice import to_xrechnung
        rt = self.grow([("Kunden.csv", CUSTOMERS), ("Rechnungsbuch_alt.csv", _book())])
        eu = billing.document(rt, rt.store.record(self.issue(rt, "Holzbau", [("Treppe", 1780, 0)], tax_note="eu")))
        xml = to_xrechnung(eu)
        self.assertIn("<cac:DeliveryLocation><cac:Address><cac:Country><cbc:IdentificationCode>AT", xml)  # BR-IC-12
        self.assertIn("<cbc:IdentificationCode>AT</cbc:IdentificationCode></cac:Country></cac:PostalAddress>", xml)
        city = billing.document(rt, rt.store.record(self.issue(rt, "Stadt Pirna", [("Wartung", 300, 19)])))
        xml = to_xrechnung(city)
        self.assertIn("<cbc:BuyerReference>14628000-0001-38</cbc:BuyerReference>", xml)  # BT-10
        self.assertTrue("<cbc:DueDate>" in xml or "<cac:PaymentTerms>" in xml)          # BR-CO-25

    def test_a_final_invoice_books_what_is_left_after_its_down_payments(self):
        rows = []
        for i in range(1, 13):
            net = 400 + 35 * i
            less = 0.0 if i % 4 else round(net * 1.19 * 0.6, 2)  # every fourth one is a final invoice
            rows.append([f"RE-2026-{i:04d}", f"{i + 2:02d}.03.2026", f"K-0{i % 2 + 1}", "Arbeiten", _eur(net), _eur(net * 0.19),
                         _eur(net * 1.19), _eur(less) if less else "", _eur(net * 1.19 - less)])
        book = csv("Rechnungsnr;Datum;Kd-Nr;Betreff;Netto;USt;Brutto;abzgl. Abschläge;Zahlbetrag", rows)
        rt = self.grow([("Kunden.csv", CUSTOMERS), ("Rechnungsbuch.csv", book)])
        inv = _type(rt, "Rechnung")
        deduct = next(a for a in inv["attrs"] if a["name"] == "abzgl. Abschläge")
        cust = next(a for a in inv["attrs"] if a["kind"] == "ref" and rt.spec(a["ref"])["name"] == "Kunde")
        kunde = next(r["id"] for r in rt.records[cust["ref"]] if rt.title(r["id"]).startswith("Elektro"))
        rid = ops.create(rt, inv["id"], {cust["id"]: str(kunde), deduct["id"]: "9520,00"}, "Test")
        billing.set_positions(rt, rid, [dict(text="Dachstuhl", qty="1", price="10000", rate="19")], "Test")
        billing.issue(rt, rid, "Test", delivery=TODAY.isoformat(), here_ok=True)
        rt.ensure()
        von, bis, label = taxexport.period("monat", TODAY.year, TODAY.month)
        data = taxexport.collect(rt, von, bis)
        row = next(r for r in data["out"] if r["rid"] == rid)
        self.assertEqual([(g["net"], g["tax"]) for g in row["groups"]], [(2000.0, 380.0)])  # not 10.000 / 1.900 again
        self.assertIn("2380,00", taxexport.extf(data, label).decode("cp1252"))

    def test_the_export_survives_partners_known_only_by_name(self):
        good = "DE89370400440532013000"
        rt = self.grow([("Kunden.csv", CUSTOMERS), ("Rechnungsbuch_alt.csv", _book()),
                        ("Eingangsrechnungen/RE_4471001.pdf", _supplier_invoice("4471001", TODAY - timedelta(days=3), 900.0, good))])
        self.issue(rt, "Elektro", [("Prüfung", 150, 19)])
        c = TestClient(create_app(self.f.dir / "firma"))
        h = {"origin": "http://testserver", "x-requested-with": "fetch"}
        for _ in range(2):  # the first export stores the partners' numbers, the second reads them back
            self.assertEqual(c.get("/steuerberatung").status_code, 200)
            r = c.post("/steuerberatung/export", data={"art": "monat", "nr": str(TODAY.month), "jahr": str(TODAY.year)},
                       headers=h)
            self.assertEqual(r.status_code, 200)
        self.assertNotIn("None", str(self.f.store.kv_get("datev_kreditors")))


class Seal(unittest.TestCase):
    def setUp(self):
        self.f = Firm()
        self.f.feed([("Kunden.csv", CUSTOMERS), ("Rechnungsbuch_alt.csv", _book())])
        rt = self.f.rt()
        k = _type(rt, "Kunde")
        for r in rt.records[k["id"]][:3]:
            ops.add_note(rt, r["id"], "angerufen", "Test")
        self.db = self.f.dir / "firma" / "physarum.db"

    def tearDown(self):
        self.f.close()

    def raw(self, sql, args=()):
        con = sqlite3.connect(self.db)
        for t in ("changes_keep", "changes_stay", "archive_keep", "archive_stay"):
            con.execute(f"DROP TRIGGER IF EXISTS {t}")
        con.execute(sql, args)
        con.commit()
        con.close()

    def test_an_unsealed_entry_in_the_middle_breaks_the_chain(self):
        self.assertTrue(self.f.store.verify_chain()["ok"])
        mid = self.f.store.q1("SELECT id FROM changes ORDER BY id LIMIT 1 OFFSET 2")["id"]
        self.raw("UPDATE changes SET actor='Jemand anderes', chain=NULL WHERE id=?", (mid,))
        v = self.f.store.verify_chain()
        self.assertFalse(v["ok"])
        self.assertEqual(v["broken_at"], mid)

    def test_entries_deleted_after_an_export_are_missed(self):
        v = self.f.store.anchor_chain()  # an export hands the seal out
        self.assertTrue(v["ok"])
        last = self.f.store.q1("SELECT MAX(id) AS m FROM changes")["m"]
        self.raw("DELETE FROM changes WHERE id >= ?", (last - 1,))
        v = self.f.store.verify_chain()
        self.assertFalse(v["ok"])
        self.assertEqual(v["lost"], 2)


    def test_a_changed_original_or_archived_document_is_noticed(self):
        import hashlib
        store = self.f.store
        self.assertEqual(store.verify_files()["changed"], [])
        src = store.q1("SELECT id, name FROM sources ORDER BY id LIMIT 1")
        path = store.source_path(src["id"], src["name"])
        path.write_bytes(path.read_bytes() + b"x")
        self.assertEqual(store.verify_files()["changed"], [src["name"]])
        with store.tx() as c:
            billing.archive_put(c, 1, "html", "Rechnung_X.html", b"<p>100,00</p>")
        forged = b"<p>10,00</p>"  # swapped with a fresh checksum of its own: the sealed one still differs
        self.raw("UPDATE archive SET content=?, sha256=? WHERE name='Rechnung_X.html'", (forged, hashlib.sha256(forged).hexdigest()))
        self.assertEqual(store.verify_files()["docs_changed"], ["Rechnung_X.html"])


class PaidByTheBook(unittest.TestCase):
    def test_the_books_paid_date_counts_before_the_statement_begins(self):
        """The book says paid in June – also in cash; the bank export starts in August: paid, not overdue."""
        f = Firm()
        try:
            rows, bank = [], []
            for i in range(20):
                d = date(2026, 5, 4) + timedelta(days=7 * i)
                net = 500 + 25 * i
                paid = d + timedelta(days=12)
                rows.append([f"RE-2026-{i + 1:03d}", d.strftime("%d.%m.%Y"), f"K-0{i % 2 + 1}", _eur(net), _eur(net * 0.19),
                             _eur(net * 1.19), (d + timedelta(days=14)).strftime("%d.%m.%Y"), paid.strftime("%d.%m.%Y"),
                             "bar bei Abnahme" if i == 1 else ""])
                if paid >= date(2026, 8, 3):  # the export of the bank starts later
                    bank.append([paid.strftime("%d.%m.%Y"), "ELEKTRO FUNKE" if i % 2 == 0 else "BAECKEREI KRUME",
                                 f"RE-2026-{i + 1:03d}", _eur(net * 1.19)])
            f.feed([("Kunden.csv", CUSTOMERS),
                    ("Rechnungsbuch.csv", csv("Rechnungsnr;Re-Datum;Kd-Nr;Netto;USt;Brutto;fällig am;bezahlt am;Bemerkung", rows)),
                    ("Umsaetze_Girokonto.csv", csv("Buchungstag;Auftraggeber/Empfänger;Verwendungszweck;Betrag", bank))])
            rt = f.rt()
            inv = _type(rt, "Rechnung")
            p = next(p for p in rt.model["processes"] if p["type"] == inv["id"])
            self.assertEqual([s["label"] for s in p["steps"]], ["bezahlt"])  # one milestone, not "bezahlt → bezahlt"
            open_ = [rt.title(rid) for rid, e in rt.ledger.items() if e["type"] == inv["id"] and e["open"] > 0.005]
            self.assertEqual(open_, [])
            self.assertFalse([g for g in rt.work(date(2026, 10, 29)) if g["kind"] == "overdue"])
        finally:
            f.close()


if __name__ == "__main__":
    unittest.main()
