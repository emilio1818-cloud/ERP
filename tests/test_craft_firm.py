"""Lessons from a craft business: a carpenter's invoice book with down payments, a bank that writes
numbers with spaces, customers who pay with the wrong number or none, and a book that leaves out
due dates.

Each test is one finding of the independent review that once gave a wrong answer.
"""
import unittest
from datetime import date, timedelta

from tests.test_unseen_firm import Firm, _type, csv

BOOK_HEAD = "Rechnungsnr;Datum;Kunde;Betreff;Netto;USt;Brutto;abzgl. Abschläge;Zahlbetrag;fällig am"
BANK_HEAD = "Buchungstag;Auftraggeber/Empfänger;Verwendungszweck;Betrag"


def _eur(x: float) -> str:
    return f"{x:.2f}".replace(".", ",")


def _book(n=24, start=date(2026, 3, 2)):
    rows = []
    for i in range(n):
        d = start + timedelta(days=3 * i)
        net = 800 + 25 * i
        rows.append([f"RE-2026-{i + 1:04d}", d.strftime("%d.%m.%Y"), f"Kunde {i % 5}", f"Arbeiten {i}",
                     _eur(net), _eur(net * 0.19), _eur(net * 1.19), "", _eur(net * 1.19),
                     (d + timedelta(days=14)).strftime("%d.%m.%Y")])
    return rows


def _states(rt, inv):
    return {rt.by_id[rid]["data"][inv["key"]]: e for rid, e in rt.ledger.items()}


class CraftFirm(unittest.TestCase):
    def setUp(self):
        self.f = Firm()

    def tearDown(self):
        self.f.close()

    def test_a_final_invoice_is_paid_with_the_down_payments_deducted(self):
        rows = _book()
        # the final invoice of a job: 10.000 € net, two down payments of 4.000 € already paid
        rows.append(["SR-2026-001", "20.05.2026", "Kunde 1", "Schlussrechnung Dachstuhl", "10000,00", "1900,00",
                     "11900,00", "8000,00", "3900,00", "03.06.2026"])
        bank = [[r[1], r[2], r[0], r[8]] for r in rows]
        self.f.feed([("Rechnungsausgangsbuch.csv", csv(BOOK_HEAD, rows)),
                     ("Umsaetze_Girokonto.csv", csv(BANK_HEAD, bank))])
        rt = self.f.rt()
        inv = _type(rt, "Rechnung")
        e = _states(rt, inv)["SR-2026-001"]
        self.assertEqual(e["state"], "bezahlt")
        self.assertAlmostEqual(e["open"], 0.0, places=2)
        # revenue: the down payments were revenue of their own invoices – the final one adds the rest
        from physarum.process import kpis
        k = next(k for k in kpis(rt.model, rt.active_records(), date(2026, 5, 31)) if k["type"] == inv["id"])
        may = next(x["value"] for x in k["series"] if x["month"] == "2026-05")
        others = sum(float(r[4].replace(",", ".")) for r in rows[:-1] if r[1][3:5] == "05")
        self.assertAlmostEqual(may, others + 10000.0 * 3900 / 11900, places=1)

    def test_an_older_export_dropped_in_later_does_not_overwrite_the_newer(self):
        import time
        rows = _book(20)
        new = [list(r) for r in rows]
        new[4][3] = "Arbeiten 4 (berichtigt)"
        new.append(["RE-2026-0021", "20.10.2026", "Kunde 1", "Wartung", "300,00", "57,00", "357,00", "", "357,00",
                    "03.11.2026"])
        self.f.feed([("Rechnungsausgangsbuch.csv", csv(BOOK_HEAD, new))])
        time.sleep(1)
        self.f.feed([("Rechnungsausgangsbuch_alt.csv", csv(BOOK_HEAD, rows))])  # last month's export, found today
        rt = self.f.rt()
        inv = _type(rt, "Rechnung")
        subj = next(a["id"] for a in inv["attrs"] if a["name"] == "Betreff")
        by_no = {r["data"][inv["key"]]: r for r in rt.records[inv["id"]]}
        self.assertEqual(by_no["RE-2026-0005"]["data"][subj], "Arbeiten 4 (berichtigt)")
        self.assertIn("RE-2026-0021", by_no)
        self.assertFalse((by_no["RE-2026-0021"].get("meta") or {}).get("vanished"))

    def test_vat_is_a_legal_rate_of_the_net_amount(self):
        rows = _book()
        rows.append(["SR-2026-001", "20.05.2026", "Kunde 1", "Schlussrechnung", "10000,00", "1900,00", "11900,00",
                     "8000,00", "3900,00", "03.06.2026"])
        self.f.feed([("Rechnungsausgangsbuch.csv", csv(BOOK_HEAD, rows))])
        rt = self.f.rt()
        texts = {f["text"] for f in _type(rt, "Rechnung").get("formulas") or []}
        self.assertIn("Brutto = Netto + USt", texts)
        self.assertIn("USt = Netto × 0,19", texts)
        self.assertFalse([t for t in texts if "Zahlbetrag" in t or "0,1597" in t or "5,26" in t], texts)

    def test_an_invoice_without_due_date_is_due_by_the_customers_term(self):
        cust_head = "Kunde;Straße;Ort;Zahlungsziel"
        custs = [[f"Kunde {i}", f"Weg {i}", "Bielefeld", "14 Tage" if i % 2 else "30 Tage"] for i in range(5)]
        today = date.today()
        rows = _book(start=today - timedelta(days=150))
        for i, r in enumerate(rows):  # the book: invoice date plus the customer's payment term
            d = date(int(r[1][6:]), int(r[1][3:5]), int(r[1][:2]))
            r[9] = (d + timedelta(days=14 if i % 5 % 2 else 30)).strftime("%d.%m.%Y")
        rows[3][9] = ""   # left out: Kunde 3 pays within 14 days – long past
        rows[-1][9] = ""  # left out, but the invoice is young: not yet due
        rows[-1][1] = (today - timedelta(days=5)).strftime("%d.%m.%Y")
        bank = [[r[1], r[2], r[0], r[8]] for k, r in enumerate(rows) if k not in (3, len(rows) - 1)]
        self.f.feed([("Kunden.csv", csv(cust_head, custs)), ("Rechnungsausgangsbuch.csv", csv(BOOK_HEAD, rows)),
                     ("Umsaetze_Girokonto.csv", csv(BANK_HEAD, bank))])
        rt = self.f.rt()
        inv = _type(rt, "Rechnung")
        e = _states(rt, inv)
        old, young = e[rows[3][0]], e[rows[-1][0]]
        d3 = date(int(rows[3][1][6:]), int(rows[3][1][3:5]), int(rows[3][1][:2]))
        self.assertEqual(old["due"], d3 + timedelta(days=14))
        self.assertIn("Zahlungsziel des Kunden", old["due_how"])
        rec = rt.by_id[old["rid"]]
        self.assertEqual(rec["data"]["pay_state"], "überfällig")
        self.assertEqual(rt.by_id[young["rid"]]["data"]["pay_state"], "offen")
        # on Heute: the book has no "bezahlt am", so the due date itself is the work – long passed
        it = next(x for g in rt.work() if g["kind"] == "due" for x in g["items"] if x["rid"] == old["rid"])
        self.assertEqual(it["days"], (old["due"] - today).days)
        self.assertLess(it["days"], 0)
        self.assertIn("Zahlungsziel", it["due_how"])
        from physarum import dunning
        letter = dunning.overdue_of(rt, rec["data"][next(a["id"] for a in inv["attrs"] if a["kind"] == "ref")], inv["id"])
        self.assertEqual([x["number"] for x in letter], [rows[3][0]])

    def test_an_old_customer_list_names_people_as_people(self):
        head = "KDNR;ANREDE;NAME1;NAME2;STRASSE;PLZ;ORT;ZAHLUNGSZIEL;KUNDE_SEIT"
        custs = [["1001", "Herr", "Brockmann", "Wolfgang", "Am Brodhagen 12", "33613", "Bielefeld", "14", "03.05.2011"],
                 ["1003", "Eheleute", "Rasche", "Detlef u. Sabine", "Talbrückenstr. 44", "33611", "Bielefeld", "14", "28.08.2017"],
                 ["1004", "Herr", "Meyer", "Klaus-Dieter", "Herforder Str. 301", "33609", "Bielefeld", "14", "17.01.2015"],
                 ["1006", "Familie", "Tepe", "Markus", "Osningstr. 5", "33605", "Bielefeld", "14", "22.02.2020"],
                 ["1012", "Herr", "Schulze", "Gerd", "Stieghorster Str. 23", "33605", "Bielefeld", "14", "19.05.2014"],
                 ["1031", "Frau", "Schulze", "Heike", "Treppenstr. 3", "33647", "Bielefeld", "14", "21.05.2024"],
                 ["1005", "Frau", "Vogt", "Dr. Annette", "Lindenweg 2", "33602", "Bielefeld", "14", "01.02.2019"],
                 ["1020", "Firma", "Immobilienverwaltung Teutoburg GmbH", "z. Hd. Frau Kortenbruck", "Niederwall 26",
                  "33602", "Bielefeld", "30", "01.01.2008"],
                 ["1028", "Firma", "Gaststätte Zum Kesselbrink", "Inh. Uwe Kröger", "Kesselbrink 9", "33602",
                  "Bielefeld", "14", "05.06.2016"]]
        orders = [["A26-001", "02.03.2026", "Fam. Tepe", "Heizkörper getauscht", "929,58"],
                  ["A26-002", "03.03.2026", "KD Meyer", "Thermostatventile erneuert", "301,02"],
                  ["A26-003", "05.03.2026", "Schulze, Gerd", "WC-Spülkasten erneuert", "563,52"],
                  ["A26-004", "06.03.2026", "H. Schulze (Brackwede)", "Enthärtungsanlage gewartet", "270,30"],
                  ["A26-005", "09.03.2026", "Fam. Schulze", "Badsanierung", "14850,00"],
                  ["A26-006", "10.03.2026", "HV Teutoburg", "Wartung Heizung", "480,00"],
                  ["A26-007", "11.03.2026", "Dr. Vogt", "Heizungsreparatur", "345,10"],
                  ["A26-008", "12.03.2026", "WEG Bahnhofstr. 12 c/o Immobilienverwaltung Teutoburg GmbH",
                   "Strangsanierung", "8400,00"],
                  ["A26-009", "13.03.2026", "Kesselbrink Gaststätte Kröger", "Fettabscheider", "1200,00"],
                  ["A26-010", "16.03.2026", "Rasche", "Wartung Heizung", "249,90"],
                  ["A26-011", "17.03.2026", "Brockmann", "Heizungsreparatur", "297,50"],
                  ["A26-012", "18.03.2026", "Tepe", "Thermostatventile erneuert", "520,91"]]
        self.f.feed([("Kundenstamm_alt.csv", csv(head, custs)),
                     ("Auftragsbuch_2026.csv", csv("Auftrag;Datum;Kunde;Leistung;Wert €", orders))])
        rt = self.f.rt()
        kunde = _type(rt, "Kunde")
        names = {rt.title(r["id"]) for r in rt.records[kunde["id"]]}
        self.assertTrue({"Wolfgang Brockmann", "Detlef u. Sabine Rasche", "Klaus-Dieter Meyer", "Markus Tepe",
                         "Dr. Annette Vogt", "Immobilienverwaltung Teutoburg GmbH", "Gaststätte Zum Kesselbrink"} <= names)
        self.assertIn("Kunde seit", {a["name"] for a in kunde["attrs"]})   # "KUNDE_SEIT" was shouted, not meant
        auftrag = _type(rt, "Auftrag")
        ref = next(a["id"] for a in auftrag["attrs"] if a["kind"] == "ref" and a.get("ref") == kunde["id"])
        got = {r["data"][auftrag["key"]]: rt.title(r["data"][ref]) if isinstance(r["data"].get(ref), int) else None
               for r in rt.records[auftrag["id"]]}
        self.assertEqual(got, {"A26-001": "Markus Tepe", "A26-002": "Klaus-Dieter Meyer", "A26-003": "Gerd Schulze",
                               "A26-004": "Heike Schulze", "A26-005": None,  # two Schulzes: nobody can tell
                               "A26-006": "Immobilienverwaltung Teutoburg GmbH", "A26-007": "Dr. Annette Vogt",
                               "A26-008": "Immobilienverwaltung Teutoburg GmbH",
                               "A26-009": "Gaststätte Zum Kesselbrink", "A26-010": "Detlef u. Sabine Rasche",
                               "A26-011": "Wolfgang Brockmann", "A26-012": "Markus Tepe"})

    def test_a_transfer_without_number_pays_the_one_invoice_it_fits(self):
        from starlette.testclient import TestClient
        from physarum import dunning
        from physarum.grow import regrow
        from physarum.web.app import create_app
        head = "KDNR;ANREDE;NAME1;NAME2;ORT"
        custs = [[str(1000 + i), "Herr", f"Name{chr(65 + i)}mann", f"Vor{chr(65 + i)}", "Bielefeld"] for i in range(5)]
        custs.append(["1005", "Eheleute", "Rasche", "Detlef u. Sabine", "Bielefeld"])
        today = date.today()
        rows = []
        for i in range(24):
            d = today - timedelta(days=100 - 3 * i)
            k = custs[i % 6]
            net = 300 + 17 * i
            rows.append([f"RE-2026-{i + 1:04d}", d.strftime("%d.%m.%Y"), k[0], f"Arbeiten {i}", _eur(net), _eur(net * 0.19),
                         _eur(net * 1.19), "", _eur(net * 1.19), (d + timedelta(days=14)).strftime("%d.%m.%Y")])
        rasche = [r for r in rows if r[2] == "1005"]
        rows[5][4:9] = ["210,00", "39,90", "249,90", "", "249,90"]              # Rasche's maintenance
        twin = [r for r in rows if r[2] == "1001"][:2]
        for r in twin:                                                          # two invoices of one amount
            r[4:9] = ["300,00", "57,00", "357,00", "", "357,00"]
        bank = [[r[1], f"{k} Kunde", r[0], r[8]] for r, k in zip(rows, range(len(rows)))
                if r is not rows[5] and r not in twin]
        bank.append([(today - timedelta(days=60)).strftime("%d.%m.%Y"), "DETLEF RASCHE", "Wartung Heizung", "249,90"])
        bank.append([(today - timedelta(days=40)).strftime("%d.%m.%Y"), "VORB NAMEBMANN", "Danke", "357,00"])
        self.f.feed([("Kundenstamm_alt.csv", csv(head, custs)),
                     ("Rechnungsausgangsbuch.csv", csv("Rechnungsnr;Datum;Kd-Nr;Betreff;Netto;USt;Brutto;"
                                                       "abzgl. Abschläge;Zahlbetrag;fällig am", rows)),
                     ("Umsaetze_Girokonto.csv", csv(BANK_HEAD, bank))])
        rt = self.f.rt()
        inv = _type(rt, "Rechnung")
        e = _states(rt, inv)
        paid = e[rows[5][0]]
        self.assertEqual(paid["state"], "bezahlt")                              # booked by payer and amount
        self.assertIn("Betrag und Zahler", paid["payments"][0]["how"])
        self.assertTrue(paid["payments"][0]["by_amount"])
        self.assertEqual({e[r[0]]["state"] for r in twin}, {"offen"})          # which of the two? a question
        q = rt.payment_proposals()
        self.assertTrue(set(q) & {e[r[0]]["rid"] for r in twin})
        held = dunning.overdue_of(rt, rt.by_id[e[twin[0][0]]["rid"]]["data"][next(
            a["id"] for a in inv["attrs"] if a["kind"] == "ref")], inv["id"])
        self.assertTrue([x for x in held if x["rid"] in q])
        self.assertTrue(all(x["maybe_paid"] for x in held if x["rid"] in q))  # no letter before the answer
        self.assertEqual(dunning.record_sent(rt, held[0] and rt.by_id[held[0]["rid"]]["data"][next(
            a["id"] for a in inv["attrs"] if a["kind"] == "ref")], inv["id"], "Test"),
            len([x for x in held if not x["maybe_paid"] and not x["complaint"]]))
        # the owner knows better: the transfer was something else
        c = TestClient(create_app(self.f.dir / "firma"))
        r = c.post(f"/r/{paid['rid']}/zahlung-loesen", data={"bank": str(paid["payments"][0]["rid"])},
                   headers={"origin": "http://testserver"})
        self.assertEqual(r.status_code, 200, r.text)
        rt = self.f.rt()
        self.assertEqual(rt.by_id[paid["rid"]]["data"]["pay_state"], "überfällig")
        regrow(self.f.store)
        rt = self.f.rt()
        self.assertEqual(rt.by_id[paid["rid"]]["data"]["pay_state"], "überfällig")  # and stays so
        self.assertNotIn(paid["rid"], rt.payment_proposals())                  # without asking again

    def test_the_bank_says_more_than_the_numbers(self):
        from tests.test_unseen_firm import _pdf
        from physarum import dunning
        today = date.today()
        head = "KDNR;ANREDE;NAME1;NAME2;BEMERKUNG"
        custs = [["1001", "Herr", "Brockmann", "Wolfgang", ""], ["1002", "Frau", "Kemper", "Ingrid", "Wartung per Lastschrift"],
                 ["1007", "Herr", "Hoffmann", "Ralf", "Wartung per Lastschrift"], ["1012", "Herr", "Schulze", "Gerd", ""],
                 ["1022", "Firma", "Bäckerei Heitbrink GmbH", "", ""], ["1024", "Firma", "Kita Sonnenschein e.V.", "", ""],
                 ["1026", "Firma", "Lindemann Wohnbau GmbH", "", ""], ["1032", "Firma", "Metzgerei Brüggemann", "", ""]]
        d = lambda n: (today - timedelta(days=n)).strftime("%d.%m.%Y")
        book = [  # number, date, customer, subject, net, gross, down payments, payable, due (VAT goes in below)
            ["RE-2026-0068", d(100), "1001", "Heizungsreparatur", "250,00", "297,50", "", "297,50", d(86)],
            ["RE-2026-0077", d(90), "1022", "Backofen-Abluft", "540,00", "642,60", "", "642,60", d(76)],
            ["RE-2026-0087", d(80), "1032", "Kühlraum Kondensatleitung", "1250,00", "1487,50", "", "1487,50", d(66)],
            ["RE-2026-0094", d(60), "1024", "Sanitär Krippe", "900,00", "1071,00", "", "1071,00", d(46)],
            ["RE-2026-0096", d(55), "1001", "Thermostatventile", "450,00", "535,50", "", "535,50", d(41)],
            ["RE-2026-0113", d(28), "1012", "Wartung lt. Vertrag WV-0102", "250,00", "297,50", "", "297,50", d(14)],
            ["RE-2026-0116", d(22), "1002", "Wartung lt. Vertrag WV-0101", "200,00", "238,00", "", "238,00", d(8)],
            ["RE-2026-0117", d(20), "1007", "Wartung lt. Vertrag WV-0110", "240,00", "285,60", "", "285,60", d(6)],
            ["RE-2026-0120", d(18), "1012", "Austausch Küchenarmatur", "300,00", "357,00", "", "357,00", d(4)],
            ["SR-2026-002", d(17), "1026", "Schlussrechnung BV Lindenstraße 14", "88240,00", "105005,60", "83300,00",
             "21705,60", d(1)]]
        for i in range(14):  # an ordinary rest of the year, paid with their numbers
            book.append([f"RE-2026-{i + 1:04d}", d(200 - 5 * i), custs[i % 8][0], f"Arbeiten {i}", f"{100 + i},00",
                         _eur((100 + i) * 1.19), "", _eur((100 + i) * 1.19), d(186 - 5 * i)])
        for r in book:
            net, gross = (float(x.replace(",", ".")) for x in (r[4], r[5]))
            r.insert(5, _eur(gross - net))
        bank = [[r[1], "Kunde", r[0], r[8]] for r in book[10:]]
        bank += [[d(85), "WOLFGANG BROCKMANN", "RE-2026-0068", "297,50"],
                 [d(78), "Brockmann, Wolfgang", "RE-2026-0068 Heizungsreparatur", "297,50"],          # twice
                 [d(40), "Brockmann, Wolfgang", "RE-2026-0096 abzgl. Doppelzahlung (RE-2026-0068)", "238,00"],
                 [d(50), "BAECKEREI HEITBRINK GMBH", "Rechnung RE-2026-0094 Heitbrink", "642,60"],    # wrong number
                 [d(45), "KITA SONNENSCHEIN E.V.", "RE-2026-0094 Kita", "1071,00"],
                 [d(66), "METZGEREI BRUEGGEMANN", "RE-2026-0087", "1433,95"],                          # as the PDF says
                 [d(10), "LINDEMANN WOHNBAU GMBH", "SR-2026-002 abzgl. 5% Sicherheitseinbehalt", "16455,32"],
                 [d(5), "WIESNER HAUSTECHNIK GMBH", f"SEPA-LASTSCHRIFT-SAMMLER 3 POSTEN EINREICHUNG {d(8)} WARTUNG",
                  "821,10"]]
        self.f.feed([("Kundenstamm_alt.csv", csv(head, custs)),
                     ("Rechnungsausgangsbuch.csv", csv(BOOK_HEAD.replace(";Kunde;", ";Kd.-Nr.;"), book)),
                     ("Umsaetze_Girokonto.csv", csv(BANK_HEAD, bank)),
                     ("Ausgangsrechnungen_PDF/RE-2026-0087.pdf",
                      _pdf("RECHNUNG RE-2026-0087) Tj 0 -16 Td (Summe netto 1.205,00 EUR) Tj 0 -16 Td "
                           "(Gesamtbetrag brutto 1.433,95 EUR"))])
        rt = self.f.rt()
        inv = _type(rt, "Rechnung")
        e = _states(rt, inv)
        self.assertEqual(e["RE-2026-0077"]["state"], "bezahlt")     # Heitbrink's money, the Kita's number
        self.assertEqual(e["RE-2026-0094"]["state"], "bezahlt")     # … so the Kita is not paid twice
        self.assertEqual((e["RE-2026-0068"]["state"], e["RE-2026-0096"]["state"]), ("bezahlt", "bezahlt"))  # netted
        self.assertEqual({e[n]["state"] for n in ("RE-2026-0113", "RE-2026-0116", "RE-2026-0117")}, {"bezahlt"})
        self.assertEqual(e["RE-2026-0120"]["state"], "offen")       # not in the collection
        sr = e["SR-2026-002"]
        self.assertAlmostEqual(sr["retention"], 5250.28, places=2)
        overdue = {x["rid"] for g in rt.work() if g["kind"] in ("overdue", "due") for x in g["items"]}
        self.assertNotIn(sr["rid"], overdue)                        # a retention is not chased …
        self.assertNotIn(sr["rid"], {x["rid"] for g in rt.work() if g["kind"] == "payment" for x in g["items"]})  # … nor a problem
        party = next(a["id"] for a in inv["attrs"] if a["kind"] == "ref")
        self.assertEqual(dunning.overdue_of(rt, rt.by_id[sr["rid"]]["data"][party], inv["id"]), [])
        self.assertAlmostEqual(e["RE-2026-0087"]["gross"], 1433.95, places=2)   # the PDF the customer got
        self.assertEqual(e["RE-2026-0087"]["state"], "bezahlt")
        g = next(g for g in rt.work() if g["kind"] == "integrity")
        self.assertTrue(any(x["rid"] == e["RE-2026-0087"]["rid"] and "PDF" in x["reason"] for x in g["items"]))

    def test_a_second_bank_with_its_own_layout_counts_the_same(self):
        today = date.today()
        d = lambda n: (today - timedelta(days=n)).strftime("%d.%m.%Y")
        head = "KDNR;ANREDE;NAME1;NAME2"
        custs = [["1020", "Firma", "Immobilienverwaltung Teutoburg GmbH", "z. Hd. Frau Kortenbruck"],
                 ["1021", "Firma", "Hausverwaltung Kramer & Söhne", ""], ["1028", "Firma", "Gaststätte Zum Kesselbrink", ""],
                 ["1003", "Eheleute", "Rasche", "Detlef u. Sabine"], ["1004", "Herr", "Meyer", "Klaus-Dieter"],
                 ["1006", "Familie", "Tepe", "Markus"]]
        book = []
        for i in range(20):
            net = 200 + 11 * i
            book.append([f"RE-2026-{i + 1:04d}", d(150 - 6 * i), ["1020", "1021", "1028", "1003", "1004", "1006", "1021",
                                                                    "1020", "1003", "1004"][i % 10], f"Arbeiten {i}",
                         _eur(net), _eur(net * 0.19), _eur(net * 1.19), "", _eur(net * 1.19), d(136 - 6 * i)])
        spk = [[r[1], "Kunde", r[0], r[8]] for r in book[:12]]
        # the Volksbank's "Umsatzanzeige": Umsatz with S/H, two name columns, the kind of booking on line one
        vb = ['"Volksbank Bielefeld-Gütersloh eG"', '', '"Umsatzanzeige";;;;;;;;;;;;', '',
              '"Buchungstag";"Valuta";"Auftraggeber/Zahlungsempfänger";"Empfänger/Zahlungspflichtiger";"Konto-Nr.";"IBAN";'
              '"BLZ";"BIC";"Vorgang/Verwendungszweck";"Kundenreferenz";"Währung";"Umsatz";" "']
        teutoburg, kramer = "DE91100000000123456789", "DE25500105177119332108"
        lines = []
        for r in book[12:16]:  # with the number, but written as payers write it
            who, iban = ("IMMOBILIENVERWALTUNG TEUTOBURG", teutoburg) if r[2] == "1020" else \
                ("HAUSVERWALTUNG KRAMER + SOEHNE", kramer) if r[2] == "1021" else ("KESSELBRINK", "DE02120300000000202051")
            number = r[0].replace("-", " ") if r[2] == "1020" else r[0].replace("RE-", "Rg. ").replace("-", "/")
            lines.append((r[1], who, iban, f"Überweisungsgutschr.\n{number}", r[8], "H"))
        r16, r17 = book[16], book[17]   # the owners' association pays the manager's invoice: by date, from a known account
        lines.append((d(20), "WEG BAHNHOFSTR. 12", teutoburg if r16[2] == "1020" else kramer,
                      f"Überweisungsgutschr.\nIhre Rechnung vom {r16[1]}", r16[8], "H"))
        lines.append((d(18), "WIESNER HAUSTECHNIK GMBH", "", "Lastschrift\nLeasingrate 10/2026", "545,00", "S"))
        for when, who, iban, purpose, amount, sh in lines:
            payer, payee = (who, "Wiesner Haustechnik GmbH") if sh == "H" else ("Wiesner Haustechnik GmbH", who)
            vb.append(f'"{when}";"{when}";"{payer}";"{payee}";"";"{iban}";"";"";"{purpose}";"";"EUR";"{amount}";"{sh}"')
        vb += ['', f'"{d(160)}";;;;;;;;;"Anfangssaldo";"EUR";"8.412,77";"H"', f'"{d(1)}";;;;;;;;;"Endsaldo";"EUR";"9.000,00";"H"']
        # the accounts are known from the Sparkasse: Teutoburg and Kramer paid with numbers there
        for r in book[:12]:
            if r[2] in ("1020", "1021"):
                spk[book.index(r)][1] = "IMMOBILIENVERWALTUNG TEUTOBURG" if r[2] == "1020" else "HAUSVERWALTUNG KRAMER"
        spk_head = "Buchungstag;Beguenstigter/Zahlungspflichtiger;Verwendungszweck;Betrag;Kontonummer/IBAN"
        spk = [row + [teutoburg if "TEUTOBURG" in row[1] else kramer if "KRAMER" in row[1] else ""] for row in spk]
        self.f.feed([("Kundenstamm_alt.csv", csv(head, custs)),
                     ("Rechnungsausgangsbuch.csv", csv(BOOK_HEAD.replace(";Kunde;", ";Kd.-Nr.;"), book)),
                     ("Sparkasse_Umsaetze.csv", csv(spk_head, spk)),
                     ("Volksbank_Umsaetze_2026.csv", ("\r\n".join(vb) + "\r\n").encode("cp1252"))])
        rt = self.f.rt()
        bank = _type(rt, "Kontobewegung")
        names = {a["name"] for a in bank["attrs"] if not a.get("hidden")}
        self.assertFalse(names & {"Umsatz", "Vorgang/Verwendungszweck", "Spalte 13", "Empfänger/Zahlungspflichtiger"})
        self.assertFalse(any("saldo" in str(v).lower() for r in rt.records[bank["id"]] for v in r["data"].values()))
        inv = _type(rt, "Rechnung")
        e = _states(rt, inv)
        self.assertEqual({e[r[0]]["state"] for r in book[:17]}, {"bezahlt"}, {r[0]: e[r[0]]["state"] for r in book[:17]})
        self.assertEqual({e[r[0]]["state"] for r in book[17:]}, {"offen"})
        lease = next(r for r in rt.records[bank["id"]] if "Leasing" in str(r["data"]))
        self.assertIn(-545.0, lease["data"].values())                              # S is money going out

    def _timesheets(self) -> bytes:
        import io
        import openpyxl
        wb = openpyxl.Workbook()
        wb.remove(wb.active)
        layouts = {  # every fitter keeps his sheet his own way
            "Kortmann": (["Datum", "Auftrag", "Baustelle", "Tätigkeit", "Std."], lambda d, job: [d, job, "BV Lindenstr.", "Heizung", 8]),
            "Nowak": (["Datum", "Kommission", "Objekt", "Arbeiten", "Stunden"],
                      lambda d, job: [d, job, "Schulze Bad", "Bad", timedelta(hours=7, minutes=30)]),
            "Schäfer": (["Tag", "Auftrag/Kunde", "Was gemacht", "Fahrtzeit", "Arbeitszeit"],
                        lambda d, job: [d, f"{job} Pension", "Duschthermostat", "0:30", "1,5 h"]),
        }
        for n, (who, (head, row)) in enumerate(layouts.items()):
            ws = wb.create_sheet(who)
            ws.append(["Stundenzettel August 2026"])
            ws.append([f"Mitarbeiter: {['Jens Kortmann', 'Dariusz Nowak', 'Timo Schäfer'][n]}", None, None, None,
                       f"Pers.-Nr. {103 + n}"])
            ws.append([])
            ws.append(head)
            for day in range(3, 24):
                ws.append(row(date(2026, 8, day), ["A26-003", "A26-028", "A26-074"][n] if day % 7 else "WV-0102"))
            ws.append([])
            ws.append([None, None, None, "Summe", "=SUM(E5:E25)"])
            ws.append([None, None, None, "Unterschrift:"])
        buf = io.BytesIO()
        wb.save(buf)
        return buf.getvalue()

    def test_three_fitters_three_layouts_one_time_sheet(self):
        orders = [[f"A26-{i:03d}", "02.03.2026", "Kunde", f"Leistung {i}", "1000,00"] for i in range(1, 80)]
        contracts = [[f"WV-{100 + i:04d}", "Kunde", "Gastherme", "jährlich"] for i in range(1, 12)]
        self.f.feed([("Auftragsbuch_2026.csv", csv("Auftr.-Nr.;Datum;Kunde;Leistung;Wert €", orders)),
                     ("Wartungsvertraege.csv", csv("Vertr.-Nr.;Kunde;Anlage;Intervall", contracts)),
                     ("Stundenzettel_August_2026.xlsx", self._timesheets())])
        rt = self.f.rt()
        sheets = [t for t in rt.model["types"] if t.get("concept") == "zeiteintrag"]
        self.assertEqual(len(sheets), 1)                                    # one list, whatever the layout
        sz = sheets[0]
        self.assertEqual(len(rt.records[sz["id"]]), 3 * 21)                 # "Unterschrift:" is no entry
        ma = _type(rt, "Mitarbeiter")
        self.assertEqual({rt.title(r["id"]) for r in rt.records[ma["id"]]}, {"Jens Kortmann", "Dariusz Nowak", "Timo Schäfer"})
        who = next(a["id"] for a in sz["attrs"] if a["kind"] == "ref" and a.get("ref") == ma["id"])
        job = next(a["id"] for a in sz["attrs"] if a["kind"] == "ref" and a.get("ref") == _type(rt, "Auftrag")["id"])
        hours = next(a["id"] for a in sz["attrs"] if a["name"] == "Stunden")
        per = {}
        for r in rt.records[sz["id"]]:
            key = (rt.title(r["data"].get(who)), rt.title(r["data"][job]) if isinstance(r["data"].get(job), int) else None)
            per[key] = per.get(key, 0) + (r["data"].get(hours) or 0)
        self.assertEqual(per[("Jens Kortmann", "A26-003")], 18 * 8)
        self.assertEqual(per[("Dariusz Nowak", "A26-028")], 18 * 7.5)
        self.assertEqual(per[("Timo Schäfer", "A26-074")], 18 * 1.5)        # "A26-074 Pension" names the order
        wv = [r for r in rt.records[sz["id"]] if "WV-0102" in str((r.get("meta") or {}).get("raw") or {})
              or rt.title(r["data"].get(job)) == "WV-0102"]
        self.assertEqual(len(wv), 3 * 3)
        self.assertTrue(all(isinstance(r["data"].get(job), int) for r in wv))  # the visit names the contract
        auftrag = _type(rt, "Auftrag")
        self.assertFalse({a["name"] for a in auftrag["attrs"]} & {"Tätigkeit", "Baustelle", "Arbeiten"})
        self.assertFalse([t for t in rt.model["types"] if t["name"] == "Projekt"])  # no projects made of sites

    def test_measurement_lines_and_the_advisors_lists_ask_nothing(self):
        aufmass = [["Pos.", "Bezeichnung", "Menge", "Einheit", "EP", "GP"]]
        rows = []
        for flat in range(1, 7):
            rows.append([f"Wohnung {flat}", None, None, None, None, None])
            for pos, what in enumerate(["Heizung / FBH", "Sanitär / Bad", "Lüftung / Sonstiges"], start=1):
                rows.append([pos, what, 1, "psch", f"{5000 + 37 * flat},00", f"{5000 + 37 * flat},00"])
            rows.append([None, f"Zwischensumme Wohnung {flat}", None, None, None, "15000,00"])
        opos = ("Offene Posten Debitoren;Stichtag 30.09.2026;;;;;;\n;;;;;;;\n"
                "Konto;Name;Belegdatum;Belegfeld1;Fällig;Betrag EUR;Offen EUR;Tage überf.\n"
                + "".join(f"1100{i};Kunde {i};0{i}.09.2026;RE-2026-00{i}0;1{i}.09.2026;100,00;100,00;\n" for i in range(1, 9)))
        extf = ('"EXTF";700;21;"Buchungsstapel";13;20261005101530123;;"RE";"";"";24680;10117;20260101;4;20260901;20260930;;"PL";1;0;0;"EUR"\n'
                '"Umsatz (ohne Soll/Haben-Kz)";"Soll/Haben-Kennzeichen";"WKZ Umsatz";"Konto";"Gegenkonto (ohne BU-Schlüssel)";"Belegdatum";"Belegfeld 1";"Buchungstext"\n'
                + "".join(f'"119,00";"S";"EUR";"1100{i}";"8400";"0{i}09";"RE-2026-00{i}0";"Kunde {i}"\n' for i in range(1, 9)))
        rows = [["" if v is None else v for v in r] for r in rows]
        self.f.feed([("Aufmass_A26-003_Schlussaufmass.csv", csv(";".join(aufmass[0]), rows)),
                     ("OPOS_Debitoren_30.09.2026.csv", opos.encode("cp1252")),
                     ("EXTF_Buchungsstapel_09_2026.csv", extf.encode("cp1252"))])
        rt = self.f.rt()
        qs = self.f.store.q("SELECT payload FROM questions WHERE status='open' AND kind='same_record'")
        self.assertEqual(qs, [])                                            # a position repeats per flat
        lines = next(t for t in rt.model["types"] if "Aufmass" in t["name"] or "Aufmaß" in t["name"])
        self.assertEqual(len(rt.records[lines["id"]]), 18)                  # subtotals are no lines
        self.assertFalse([t for t in rt.model["types"] if any("OPOS" in m["label"] or "EXTF" in m["label"]
                                                              for m in t["members"])])
        from physarum import taxexport
        cfg = taxexport.settings(self.f.store)
        self.assertEqual((cfg["berater"], cfg["mandant"]), (24680, 10117))   # as the advisor's own export says
        self.assertEqual(taxexport.advisor_accounts(self.f.store)["re-2026-0010"], 11001)


if __name__ == "__main__":
    unittest.main()
