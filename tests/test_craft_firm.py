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


def _pdf_page(lines: list[str]) -> bytes:
    """A one-page PDF with these lines, one under the other (a scanned-and-recognised letter)."""
    esc = [x.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)") for x in lines]
    body = ("BT /F1 10 Tf 50 800 Td " + " ".join(f"({x}) Tj 0 -14 Td" for x in esc) + " ET").encode("cp1252")
    objs = [b"<< /Type /Catalog /Pages 2 0 R >>", b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
            b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] /Contents 4 0 R "
            b"/Resources << /Font << /F1 5 0 R >> >> >>",
            b"<< /Length %d >>\nstream\n" % len(body) + body + b"\nendstream",
            b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding >>"]
    out, offs = b"%PDF-1.4\n", []
    for i, o in enumerate(objs, start=1):
        offs.append(len(out))
        out += b"%d 0 obj\n" % i + o + b"\nendobj\n"
    xref = len(out)
    out += b"xref\n0 %d\n0000000000 65535 f \n" % (len(objs) + 1)
    out += b"".join(b"%010d 00000 n \n" % o for o in offs)
    out += b"trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (len(objs) + 1, xref)
    return out


def _supplier_invoice(no, day: date, net: float, iban: str, mail="rechnung@gh-nord.example", note=""):
    tax, gross = round(net * 0.19, 2), round(net * 1.19, 2)
    return _pdf_page([
        "Grosshandel Nord GmbH", f"Hafenstr. 5 · 20457 Hamburg · {mail}",
        "Muster Haustechnik GmbH", "Hauptstr. 1", "33602 Bielefeld", "RECHNUNG",
        f"Rechnung Nr.: {no}", f"Rechnungsdatum: {day.strftime('%d.%m.%Y')}", "Ihre Kunden-Nr.: 55120",
        "Kommission: Lager", "Pos Bezeichnung Menge EP GP", f"1 Kupferrohr 15 mm 10 Stk {_eur(net / 10)} {_eur(net)}",
        f"Warenwert netto {_eur(net)} EUR", f"zzgl. 19 % MwSt. {_eur(tax)} EUR", f"Rechnungsbetrag {_eur(gross)} EUR",
        f"Zahlbar bis {(day + timedelta(days=10)).strftime('%d.%m.%Y')} abzgl. 2 % Skonto ({_eur(gross * 0.98)} EUR) "
        f"oder bis {(day + timedelta(days=30)).strftime('%d.%m.%Y')} netto.",
        "Grosshandel Nord GmbH · Hafenstr. 5 · 20457 Hamburg · USt-IdNr. DE123456789",
        f"Bankverbindung: IBAN {iban} · BIC COBADEFFXXX {note}"])


def _states(rt, inv):
    return {rt.by_id[rid]["data"][inv["key"]]: e for rid, e in rt.ledger.items() if e["type"] == inv["id"]}


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

    def test_maintenance_inspections_and_mot_come_due_on_heute(self):
        import io
        import openpyxl
        today = date(2026, 10, 29)
        wb = openpyxl.Workbook()
        ws = wb.active
        ws.title = "Verträge"
        ws.append(["Wartungsverträge Heizung / Sanitär – Stand 10/2026"])
        ws.append([])
        ws.append(["Vertr.-Nr.", "Kunde", "Anlage", "Intervall", "letzte Wartung", "nächste Wartung", "Status"])
        contracts = [  # number, interval, last, next as written by hand
            ("WV-0106", "1x jährl.", "20.10.25", "10/2026"),        # overdue: the month hides the day
            ("WV-0120", "alle 2 Jahre", date(2024, 10, 10), "10/2026"),
            ("WV-0124", "12 Monate", date(2025, 5, 20), "KW 21"),    # a week without a year: last round's
            ("WV-0121", "jährlich", "Okt. 2025", "KW 42"),           # due this month
            ("WV-0105", "jährlich", date(2025, 11, 5), None),        # in a week
            ("WV-0101", "jährlich", date(2025, 10, 8), None),        # done on 06.10. – the time sheet says so
            ("WV-0104", "halbjährlich", date(2026, 10, 13), None),   # just done
            ("WV-0103", "12 Mon.", "31.08.26", "nach Absprache"),
            ("WV-0113", "jährlich", "—", "07/2027"),                 # first visit next year
        ]
        for no, iv, last, nxt in contracts:
            ws.append([no, "Kunde", "Gastherme", iv, last, nxt, "aktiv"])
        ws.append(["WV-0110", "Kunde", "Wärmepumpe", "jährlich", date(2025, 10, 8), None, "gekündigt zum 30.09.2026"])
        buf = io.BytesIO()
        wb.save(buf)
        contracts_xlsx = buf.getvalue()
        wb = openpyxl.Workbook()
        wb.active.title = "Werkzeug + Geräte"
        wb.active.append(["Inv.-Nr.", "Gerät", "letzte Prüfung", "nächste Prüfung"])
        for no, what, nxt in [("WZ-001", "Pressmaschine", "11/2026"), ("WZ-002", "Rohrreiniger", "06/2026"),
                              ("WZ-003", "Kernbohrgerät", "11/2027"), ("WZ-004", "Abgasmessgerät", "09/2026")]:
            wb.active.append([no, what, date(2025, 6, 1), nxt])
        fleet = wb.create_sheet("Fahrzeuge")
        fleet.append(["Kennzeichen", "Fahrzeug", "EZ", "Fahrer", "HU fällig"])
        for plate, car, ez, hu in [("BI-WH 101", "VW Crafter", "03/2021", "03/2027"), ("BI-WH 103", "Sprinter", "09/2018", "09/2026"),
                                   ("BI-WH 104", "Transit", "11/2023", "11/2026"), ("BI-WH 105", "Caddy", "04/2019", "04/2027"),
                                   ("BI-WH 106", "Anhänger", "07/2014", "07/2026")]:
            fleet.append([plate, car, ez, "—", hu])
        buf = io.BytesIO()
        wb.save(buf)
        visit = csv("Datum;Auftrag;Tätigkeit;Std.;Mitarbeiter", [["06.10.2026", "WV-0101", "Wartung Therme", "2", "Dreier"]] +
                    [[f"{d:02d}.10.2026", "WV-0104", "Wartung", "3", "Dreier"] for d in (12, 13)])
        self.f.feed([("Wartungsvertraege.xlsx", contracts_xlsx), ("Fuhrpark_Werkzeug.xlsx", buf.getvalue()),
                     ("Stundenzettel_Dreier_Oktober.csv", visit)])
        rt = self.f.rt()
        self.assertTrue({"Fahrzeuge", "Werkzeug + Geräte"} <= {t["plural"] for t in rt.model["types"]})  # by sheet
        work = rt.work(today)
        due = {x["title"]: x for g in work if g["kind"] == "due" for x in g["items"]}
        late = {k for k, x in due.items() if x["days"] < 0}
        self.assertEqual({k for k in late if k.startswith("WV")}, {"WV-0106", "WV-0120", "WV-0124"})
        self.assertEqual(due["WV-0121"]["due"], "2026-10-31")                      # this month
        self.assertIn("WV-0105", due)                                              # within the month ahead
        self.assertFalse({"WV-0101", "WV-0104", "WV-0103", "WV-0113", "WV-0110"} & set(due))
        self.assertEqual({k for k in late if not k.startswith("WV")}, {"Sprinter", "Anhänger", "Rohrreiniger",
                                                                       "Abgasmessgerät"})  # HU and inspection overdue
        self.assertIn("Transit", due)                                              # HU next month
        self.assertIn("Pressmaschine", due)

    def test_offers_to_follow_up_are_the_open_ones_whose_day_has_come(self):
        from starlette.testclient import TestClient
        from physarum import ops
        from physarum.web.app import create_app
        today = date(2026, 10, 29)
        head = "Angebots-Nr.;Datum;Kunde;Betreff;Netto;Status;Auftrag;nachfassen am"
        rows, orders = [], []
        for i in range(40):
            d = date(2026, 1, 8) + timedelta(days=7 * i)
            no, age = f"AN-26-{i + 1:03d}", (today - d).days
            st, job = ("beauftragt" if i % 4 == 0 and age > 40 else "abgelehnt" if i % 4 == 1 and age > 30 else "offen"), ""
            if st == "beauftragt" or i == 34:  # AN-26-035: ordered, but the list still says "offen"
                job = f"A26-{i + 1:03d}"
                orders.append([job, (d + timedelta(days=21)).strftime("%d.%m.%Y"), f"Kunde {i % 6}", no,
                               f"Arbeiten {i}", _eur(5000 + 100 * i)])
            follow = (d + timedelta(days=14)).strftime("%d.%m.%Y") if st == "offen" or i == 33 else ""
            rows.append([no, d.strftime("%d.%m.%Y"), f"Kunde {i % 6}", f"Arbeiten {i}", _eur(5000 + 100 * i), st, job,
                         follow])
        rows.append(["AN-26-041", "16.10.2026", "Kunde 1", "Bad", "7000,00", "offen", "", "30.10.2026"])  # tomorrow
        self.f.feed([("Angebote_2026.csv", csv(head, rows)),
                     ("Auftragsbuch.csv", csv("Auftrag;Datum;Kunde;Angebot;Leistung;Wert", orders))])
        rt = self.f.rt()
        self.assertEqual(next(a for a in _type(rt, "Angebot")["attrs"] if a["name"] == "nachfassen am")["role"], "due")
        work = rt.work(today)
        g = next(g for g in work if g["kind"] == "due" and g["type"] == _type(rt, "Angebot")["id"])
        self.assertEqual(g["title"], "Angebote nachfassen")
        # open, the day has come, younger than three months – not the taken, the turned down, the lapsed
        self.assertEqual({x["title"] for x in g["items"]}, {"AN-26-031", "AN-26-032", "AN-26-036", "AN-26-039",
                                                             "AN-26-040"})
        self.assertIn("verlaufen", g["explain"])
        self.assertFalse([w for w in work if w["kind"] == "late" and w["type"] == g["type"]])  # no "not ordered yet"
        self.assertEqual(g["action"]["days"], 14)                     # the firm sets the day two weeks ahead
        rid = {x["title"]: x["rid"] for x in g["items"]}
        # after the call: again in two weeks, or the customer said no
        ops.follow_up(rt, rid["AN-26-031"], "later", "Test", today)
        c = TestClient(create_app(self.f.dir / "firma"))
        r = c.post(f"/r/{rid['AN-26-032']}/nachfassen", data={"outcome": "lost"}, headers={"origin": "http://testserver"})
        self.assertEqual(r.status_code, 200, r.text)
        self.assertIn("abgelehnt", r.json()["toast"])
        rt = self.f.rt()
        left = {x["title"] for g in rt.work(today) if g["kind"] == "due" for x in g["items"]}
        self.assertFalse({"AN-26-031", "AN-26-032"} & left)
        self.assertIn("AN-26-031", {x["title"] for g in rt.work(today + timedelta(days=14)) if g["kind"] == "due"
                                    for x in g["items"]})              # back on the list in two weeks

    def test_a_pdf_invoice_reads_like_an_e_invoice(self):
        from physarum.pdfinvoice import read
        inv = read("Steinbach IT – Marco Steinbach\nMühlenkamp 31 · 22303 Hamburg · USt-IdNr. DE312345678\n"
                   "Nordlicht Digital GmbH\nGroßer Burstah 12\n20457 Hamburg\nRechnung Nr. SIT-2026-07 Datum: 04.08.2026\n"
                   "1. Entwicklung Juli (88,35 Std. à 95,00 EUR) 8.393,14 EUR\nNetto: 8.393,14 EUR\n"
                   "USt 19 %: 1.594,70 EUR\nGesamtbetrag: 9.987,84 EUR\nZahlbar innerhalb von 10 Tagen ohne Abzug.")
        self.assertEqual((inv["number"], inv["seller"], inv["buyer"], inv["net"], inv["tax"], inv["gross"], inv["due"],
                          inv["seller_vat"]),
                         ("SIT-2026-07", "Steinbach IT – Marco Steinbach", "Nordlicht Digital GmbH", 8393.14, 1594.70,
                          9987.84, date(2026, 8, 14), "DE312345678"))
        # a letter about an invoice is no invoice
        self.assertIsNone(read("Sehr geehrte Damen und Herren,\nzu Ihrer Rechnung Nr. 4471288 über 7.854,00 EUR:\n"
                               "Gesamtbetrag 7.854,00 EUR haben wir überwiesen."))

    def test_supplier_invoices_from_pdf_paid_twice_received_and_a_fraud(self):
        from email.message import EmailMessage
        today = date(2026, 10, 29)
        good, bad = "DE89370400440532013000", "DE12500105170648489890"
        rows = _book(24, start=date(2026, 6, 1))
        bank = [[r[1], r[2], "DE02120300000000202051", f"Rechnung {r[0]} vielen Dank", r[8]] for r in rows]
        files = []
        for no, day, net in (("4471001", date(2026, 8, 3), 1000.0), ("4471002", date(2026, 9, 1), 2000.0),
                             ("4471003", date(2026, 10, 1), 1500.0)):
            files.append((f"Eingangsrechnungen/RE_{no}.pdf", _supplier_invoice(no, day, net, good)))
            bank.append([(day + timedelta(days=9)).strftime("%d.%m.%Y"), "GROSSHANDEL NORD", good, f"RG {no} KD 55120",
                         "-" + _eur(net * 1.19 * 0.98)])
        late = _supplier_invoice("4471004", date(2026, 10, 5), 800.0, good)       # Skonto gone, due in a week
        files += [("Eingangsrechnungen/RE_4471004.pdf", late), ("Eingangsrechnungen/Scan_0001.pdf", late + b"\n")]
        msg = EmailMessage()
        msg["From"], msg["To"] = "Grosshandel Nord Buchhaltung <buchhaltung@gh-nord-hamburg.example>", "info@muster.example"
        msg["Subject"], msg["Date"] = "Rechnung 4471005 / neue Bankverbindung", "Tue, 20 Oct 2026 14:02:00 +0200"
        msg.set_content(f"anbei Rechnung 4471005. Bitte beachten Sie, dass sich unsere Bankverbindung geändert hat: {bad}.")
        msg.add_attachment(_supplier_invoice("4471005", date(2026, 10, 20), 6600.0, bad, note="NEUE BANKVERBINDUNG"),
                           maintype="application", subtype="pdf", filename="Rechnung_4471005.pdf")
        own = _pdf_page(["Muster Haustechnik GmbH", "Hauptstr. 1 · 33602 Bielefeld · info@muster.example", rows[2][2],
                         "Dorfstr. 3", "33602 Bielefeld", "RECHNUNG", f"Rechnungs-Nr.: {rows[2][0]}",
                         f"Datum: {rows[2][1]}", f"Gesamtbetrag brutto {rows[2][6]} EUR",
                         "USt-IdNr. DE987654321 · IBAN DE02120300000000202051"])
        self.f.feed([("Rechnungsausgangsbuch.csv", csv(BOOK_HEAD, rows)),
                     ("Umsaetze_Girokonto.csv", csv("Buchungstag;Auftraggeber/Empfänger;IBAN;Verwendungszweck;Betrag", bank)),
                     (f"Ausgangsrechnungen/{rows[2][0]}.pdf", own), ("Rechnung_4471005.eml", msg.as_bytes())] + files)
        rt = self.f.rt()
        inc = _type(rt, "Eingangsrechnung")
        self.assertTrue(inc["incoming"])
        key = inc["key"]
        st = {rt.by_id[r["id"]]["data"][key]: rt.ledger.get(r["id"], {}).get("state") for r in rt.records[inc["id"]]}
        self.assertEqual(set(st), {"4471001", "4471002", "4471003", "4471004", "4471005"})        # not the firm's own invoice
        self.assertEqual({k for k, v in st.items() if v == "bezahlt"}, {"4471001", "4471002", "4471003"})
        work = rt.work(today)
        risk = next(g for g in work if g["kind"] == "risk")
        self.assertEqual([x["title"] for x in risk["items"]], ["4471005"])
        why = risk["items"][0]["reason"]
        self.assertIn("DE12 5001", why)                                           # an account never paid to
        self.assertIn("gh-nord-hamburg.example", why)                             # from a look-alike address
        self.assertIn("geändert", why)                                            # and the mail says so
        pay = [x for g in work if g["kind"] == "payable" for x in g["items"]]
        self.assertEqual([x["title"] for x in pay], ["4471004"])                     # the fraud is not on the list to pay
        self.assertIn("Skonto-Frist 15.10. verpasst", pay[0]["reason"])
        self.assertIn("zweimal eingegangen (RE_4471004.pdf, Scan_0001.pdf)", pay[0]["reason"])
        self.assertEqual(pay[0]["party"], "Grosshandel Nord GmbH")

    def test_mails_that_wait_for_an_answer(self):
        from email.message import EmailMessage

        def mail(sender, subject, day, text):
            m = EmailMessage()
            m["From"], m["To"], m["Subject"] = sender, "info@muster.example", subject
            m["Date"] = f"{day.strftime('%a')}, {day.day:02d} {day.strftime('%b')} {day.year} 10:00:00 +0200"
            m.set_content(text)
            return m.as_bytes()
        today = date(2026, 10, 29)
        rows = _book(24, start=date(2026, 5, 4))
        bank = [[r[1], r[2], f"Rechnung {r[0]}", r[8]] for r in rows if r[0] not in ("RE-2026-0004", "RE-2026-0005")]
        customers = csv("Kd.-Nr.;Name;E-Mail", [[f"K{i}", f"Kunde {i}", f"post@kunde{i}.example"] for i in range(5)]
                        + [["K9", "Metzgerei Brüggemann", ""]])
        contracts = csv("Vertr.-Nr.;Kunde;Intervall;letzte Wartung;Status",
                        [[f"WV-{i:04d}", f"Kunde {i % 5}", "jährlich", "10.10.2025", "aktiv"] for i in range(101, 108)])
        self.f.feed([("Rechnungsausgangsbuch.csv", csv(BOOK_HEAD, rows)), ("Umsaetze.csv", csv(BANK_HEAD, bank)),
                     ("Kunden.csv", customers), ("Wartungsvertraege.csv", contracts),
                     ("claim.eml", mail("Kunde 3 <post@kunde3.example>", "AW: Zahlungserinnerung RE-2026-0004",
                                        date(2026, 9, 14), "die Rechnung RE-2026-0004 haben wir bereits am 12.08.2026 "
                                                           "überwiesen. Bitte prüfen Sie Ihren Zahlungseingang.")),
                     ("paid.eml", mail("Kunde 1 <post@kunde1.example>", "Rechnung RE-2026-0002", date(2026, 10, 20),
                                       "die Rechnung RE-2026-0002 haben wir bereits überwiesen.")),
                     ("cancel.eml", mail("Kunde 2 <post@kunde2.example>", "Kündigung", date(2026, 10, 5),
                                         "hiermit kündige ich den Wartungsvertrag WV-0102 zum 31.12.2026.")),
                     ("bitte.eml", mail("Frank Brüggemann <info@metzgerei-brueggemann.example>", "Rohrbruch – Danke!",
                                        date(2026, 10, 26), "Schicken Sie uns bitte die Rechnung. Und bitte Termin machen "
                                                            "für die Klimaanlage.")),
                     ("danke.eml", mail("Kunde 4 <post@kunde4.example>", "Danke für die Wartung", date(2026, 10, 7),
                                        "Herr Dreier war gestern da und hat die Therme gewartet. Alles bestens.")),
                     ("bank.eml", mail("Buchhaltung <buchhaltung@gh-nord-hamburg.example>", "WICHTIG: neue Bankverbindung",
                                       date(2026, 10, 20), "Bitte überweisen Sie ab sofort nur noch auf unsere neue "
                                                           "Bankverbindung DE12500105170648489890."))])
        rt = self.f.rt()
        work = rt.work(today)
        g = next(g for g in work if g["kind"] == "mail")
        got = {x["title"]: x for x in g["items"]}
        self.assertEqual(set(got), {"AW: Zahlungserinnerung RE-2026-0004", "Kündigung", "Rohrbruch – Danke!",
                                    "WICHTIG: neue Bankverbindung"})               # not the thanks, not the paid one
        self.assertEqual(g["items"][0]["title"], "WICHTIG: neue Bankverbindung")   # the risk first
        self.assertIn("RE-2026-0004 sei am 12.08. bezahlt", got["AW: Zahlungserinnerung RE-2026-0004"]["reason"])
        self.assertIn("WV-0102 zum 31.12.", got["Kündigung"]["reason"])
        self.assertIn("noch nicht in der Vertragsliste", got["Kündigung"]["reason"])
        self.assertEqual(got["Rohrbruch – Danke!"]["party"], "Metzgerei Brüggemann")  # the domain is the name
        self.assertIn("um die Rechnung und einen Termin", got["Rohrbruch – Danke!"]["reason"])
        self.assertEqual(got["Rohrbruch – Danke!"]["act"]["label"], "+ Rechnung")
        overdue = {x["title"]: x for w in work if w["kind"] == "overdue" for x in w["items"]}
        self.assertIn("Kunde sagt: bezahlt", overdue["RE-2026-0004"]["claim"])     # look before reminding
        self.assertNotIn("claim", overdue["RE-2026-0005"])

    def test_customers_the_books_name_differently(self):
        import time
        people = [["1001", "Wohnbau-Genossenschaft Ostwestfalen-Süd eG"], ["1002", "Emre Kaya"],
                  ["1003", "Gerd Schulze"], ["1004", "Heike Schulze"], ["1005", "Hausverwaltung Kramer & Söhne"],
                  ["1006", "Zahnarztpraxis Dr. Lehmann"]] + [[str(1010 + i), f"Kunde {i} GmbH"] for i in range(8)]
        head = "Kd.-Nr.;Name;Ort"
        jobs_head = "Auftr.-Nr.;Datum;Kunde;Leistung;Wert"
        written = ["Genossenschaft OWL-Süd", "Kaya PV", "Fam. Schulze", "Kramer & Söhne", "Fitnessstudio Kraftwerk",
                   "Praxis Dr. med. dent. Lehmann", "Kraftwerk Fitness UG", "Barverkauf"]
        jobs = [[f"A26-{i + 1:03d}", f"{(i % 27) + 1:02d}.0{(i % 8) + 2}.2026", f"Kunde {i % 8} GmbH", "Wartung", "300"]
                for i in range(30)]
        jobs += [[f"A26-{i + 101:03d}", f"{i + 3:02d}.09.2026", w, "Arbeiten", "900"] for i, w in enumerate(written)]
        jobs += [["A26-120", "20.09.2026", "Barverkauf", "Kleinteile", "40"]]
        book = [[r[0].replace("A26-", "RE-2026-"), r[1], r[2], r[0], "Arbeiten", "500,00"] for r in jobs[:30]]
        # the invoice for the Schulze job names Gerd: that decides "Fam. Schulze"
        book += [["RE-2026-0203", "30.09.2026", "Gerd Schulze", "A26-103", "Bad", "4800,00"],
                 ["RE-2026-0205", "30.09.2026", "Kraftwerk Fitness UG", "A26-105", "Duschen", "900,00"]]
        self.f.feed([("Kundenstamm.csv", csv(head, [p + ["Bielefeld"] for p in people])),
                     ("Auftragsbuch.csv", csv(jobs_head, jobs)),
                     ("Rechnungsbuch.csv", csv("Re.-Nr.;Datum;Kunde;Auftrag;Leistung;Netto", book))])
        time.sleep(1)
        # the next customer list renames Kramer – the orders keep the old short name
        people[4] = ["1005", "Kramer Immobilienmanagement GmbH"]
        self.f.feed([("Kundenstamm_neu.csv", csv(head, [p + ["Bielefeld"] for p in people]))])
        rt = self.f.rt()
        job, kunde = _type(rt, "Auftrag"), _type(rt, "Kunde")
        party = next(a for a in job["attrs"] if a["kind"] == "ref" and a.get("ref") == kunde["id"])
        to = {rt.by_id[r["id"]]["data"][job["key"]]: rt.by_id[r["id"]]["data"].get(party["id"])
              for r in rt.records[job["id"]]}
        name = {r["id"]: rt.title(r["id"]) for r in rt.records[kunde["id"]]}
        self.assertEqual(name.get(to["A26-101"]), "Wohnbau-Genossenschaft Ostwestfalen-Süd eG")  # OWL
        self.assertEqual(name.get(to["A26-102"]), "Emre Kaya")                    # PV is the job, not who
        self.assertEqual(name.get(to["A26-103"]), "Gerd Schulze")                 # the invoice says which Schulze
        self.assertEqual(name.get(to["A26-104"]), "Kramer Immobilienmanagement GmbH")  # its former name
        self.assertEqual(name.get(to["A26-106"]), "Zahnarztpraxis Dr. Lehmann")   # a title is no name
        # a customer only the books know: one record for both spellings, the bank's included
        self.assertEqual(to["A26-105"], to["A26-107"])
        self.assertEqual(name[to["A26-105"]], "Kraftwerk Fitness UG")
        self.assertIn(["Aufträgen", 2], rt.by_id[to["A26-105"]]["meta"]["implied"])
        self.assertFalse(isinstance(to["A26-108"], int) or isinstance(to["A26-120"], int))  # "Barverkauf" is nobody
        self.assertEqual(len(rt.records[kunde["id"]]), len(people) + 1)

    def test_one_sheet_per_year_is_one_order_book(self):
        import io
        import openpyxl
        wb = openpyxl.Workbook()
        old = wb.active
        old.title = "2025"
        old.append(["Auftragsbuch 2025"])
        old.append([])
        old.append(["Auftrag", "Datum", "Kunde", "Objekt", "Leistung", "Wert €", "Monteur", "Status", "erledigt"])
        for i in range(20):
            d = date(2025, 7, 1) + timedelta(days=7 * i)
            old.append([f"A25-{i + 1:03d}", d, f"Kunde {i % 5}", None, "Wartung", 300 + i, ["Dreier", "Pieper"][i % 2],
                        "abgerechnet", d + timedelta(days=5)])
        new = wb.create_sheet("Aufträge 2026")
        new.append(["Wiesner Haustechnik GmbH – Auftragsbuch"])
        new.append(["Auftr.-Nr.", "Datum", "Kunde", "Baustelle / Objekt", "Leistung", "Angebot", "Auftragswert netto",
                    "Monteur", "Status", "fertig am", "Rechnung", "Bemerkung"])
        for i in range(25):
            d = date(2026, 1, 5) + timedelta(days=7 * i)
            new.append([f"A26-{i + 1:03d}", d, f"Kunde {i % 5}", f"Hauptstr. {i}", "Reparatur", None, 500 + i,
                        ["Dreier", "Pieper"][i % 2], "in Arbeit" if i > 20 else "fertig",
                        None if i > 20 else d + timedelta(days=4), None, None])
        buf = io.BytesIO()
        wb.save(buf)
        self.f.feed([("Auftragsbuch_2025_2026.xlsx", buf.getvalue())])
        rt = self.f.rt()
        orders = [t for t in rt.model["types"] if t.get("concept") == "auftrag"]
        self.assertEqual(len(orders), 1)                                           # last year's sheet is no other kind
        t = orders[0]
        self.assertEqual(len(rt.records[t["id"]]), 45)
        self.assertEqual(len([a for a in t["attrs"] if a["kind"] == "money"]), 1)  # "Wert €" is the "Auftragswert"
        done = [a for a in t["attrs"] if a["kind"] in ("date", "datetime") and a["name"] != "Datum"]
        self.assertEqual(len(done), 1)                                             # "erledigt" is "fertig am"

    def test_only_questions_that_need_the_owner(self):
        import io
        import openpyxl
        from physarum.questions import open_questions
        jobs = [[f"A26-{i + 1:03d}", f"{(i % 27) + 1:02d}.0{(i % 8) + 2}.2026", f"Kunde {i % 6}", "Reparatur", "400"]
                for i in range(30)]
        wb = openpyxl.Workbook()
        wb.active.title = "Schäfer"
        for name in ("Schäfer", "Kortmann"):
            ws = wb[name] if name in wb.sheetnames else wb.create_sheet(name)
            ws.append([f"Stundenzettel August 2026 – {name}"])
            ws.append(["Datum", "Auftrag", "Baustelle", "Tätigkeit", "Stunden"])
            for d in range(3, 25):
                ws.append([date(2026, 8, d), f"A26-{(d * 3) % 30 + 1:03d}", f"Hauptstr. {d}", "Montage", 7.5])
        sheets = io.BytesIO()
        wb.save(sheets)
        wb = openpyxl.Workbook()
        wb.active.append(["Pos.", "Art.-Nr.", "Bezeichnung", "Menge", "Einheit", "EP netto", "GP netto"])
        for i in range(10):
            wb.active.append([i + 1, f"KM-{100 + i}", f"Fitting {i}", 2 + i, "Stk", 4.5, (2 + i) * 4.5])
        aufmass = io.BytesIO()
        wb.save(aufmass)
        prices = csv("Art.-Nr.;Bezeichnung;Einheit;EK netto;VK netto;Lieferant;Gruppe",
                     [[f"KM-{100 + i}", f"Fitting {i}", "Stk", "3,00", "4,50", "HTG", "Kleinmaterial"] for i in range(15)])
        people = csv("KDNR;ANREDE;NAME1;NAME2;STRASSE;PLZ;ORT;TELEFON",
                     [[str(1000 + i), "Herr", f"Name{i}", "Max", f"Weg {i}", "33602", "Bielefeld", f"0521 10{i:02d}"]
                      for i in range(6)] + [["1008", "Herr", "Müller", "Hans-Peter", "Jöllenbecker Str. 210", "33613",
                                             "Bielefeld", "0521 887766"],
                                            ["1044", "Herr", "Mueller", "Hans Peter", "Jöllenbecker Straße 210", "33613",
                                             "Bielefeld", "0521/887766"]])
        self.f.feed([("Auftragsbuch.csv", csv("Auftr.-Nr.;Datum;Kunde;Leistung;Wert", jobs)),
                     ("Stundenzettel_August_2026.xlsx", sheets.getvalue()), ("Aufmass_A26-028_Schulze_Bad.xlsx", aufmass.getvalue()),
                     ("Kleinmaterial_Preisliste_2026.csv", prices), ("Kundenstamm_alt.csv", people)])
        qs = open_questions(self.f.store)
        self.assertFalse([q["text"] for q in qs if q["kind"] in ("same_type", "confirm_merge")])
        twin = [q for q in qs if q["kind"] == "same_record"]
        self.assertEqual(len(twin), 1)                                             # the one the owner must decide
        self.assertIn("gleiche Straße", twin[0]["detail"])                         # "Str." is "Straße"

    def test_money_that_pays_no_invoice_is_asked_about(self):
        today = date(2026, 10, 29)
        rows = _book(24, start=date(2026, 6, 1))
        bank = [[r[1], r[2], "DE02120300000000202051", f"Rechnung {r[0]}", r[8]] for r in rows]
        offers = csv("Angebots-Nr.;Datum;Kunde;Betreff;Netto;Status;Auftrag",
                     [[f"AN-26-{i:03d}", f"0{(i % 8) + 1}.08.2026", f"Kunde {i % 5}", "Bad", "8000", "beauftragt",
                       f"A26-{i:03d}"] for i in range(40, 52)])
        jobs = csv("Auftr.-Nr.;Datum;Kunde;Leistung;Wert;Angebot",
                   [[f"A26-{i:03d}", f"1{(i % 8) + 1}.08.2026", f"Kunde {i % 5}", "Bad", "8000", f"AN-26-{i:03d}"]
                    for i in range(40, 52)])
        supplier = _supplier_invoice("4471120", date(2026, 9, 1), 1000.0, "DE89370400440532013000")
        bank += [["30.09.2026", "KITA SONNENSCHEIN E.V.", "DE42440100464793027145",
                  "Anzahlung lt. Auftragsbestaetigung Angebot AN-26-045", "3000,00"],
                 ["15.10.2026", "GROSSHANDEL NORD", "DE89370400440532013000", "Gutschrift 4471199 Retoure", "214,20"],
                 ["20.10.2026", "Muster Haustechnik GmbH", "DE75512108001245126199", "Umbuchung Tagesgeld", "5000,00"],
                 ["11.09.2026", "GROSSHANDEL NORD", "DE89370400440532013000", "RG 4471120 KD 55120", "-1190,00"]]
        customers = csv("Kd.-Nr.;Name;Ort", [[f"K{i}", f"Kunde {i}", "Bielefeld"] for i in range(5)])
        self.f.feed([("Kunden.csv", customers), ("Rechnungsausgangsbuch.csv", csv(BOOK_HEAD, rows)),
                     ("Angebote.csv", offers), ("Auftraege.csv", jobs),
                     ("Umsaetze.csv", csv("Buchungstag;Auftraggeber/Empfänger;IBAN;Verwendungszweck;Betrag", bank)),
                     ("Eingangsrechnungen/RE_4471120.pdf", supplier)])
        rt = self.f.rt()
        g = next(g for g in rt.work(today) if g["kind"] == "receipt")
        got = {x["money"]: x for x in g["items"]}
        self.assertEqual(set(got), {3000.0, 214.2})                     # not the paid invoices, not the own transfer
        self.assertIn("Anzahlung zu AN-26-045 (Auftrag A26-045)", got[3000.0]["reason"])
        self.assertEqual(got[3000.0]["act"]["label"], "+ Anzahlungsrechnung")
        self.assertIn("Grosshandel Nord GmbH (Lieferant)", got[214.2]["reason"])

    def test_a_measurement_belongs_to_its_job(self):
        import io
        import openpyxl
        jobs = [[f"A26-{i:03d}", f"{(i % 27) + 1:02d}.0{(i % 8) + 2}.2026", f"Kunde {i % 6}", "Bad", "9000"]
                for i in range(1, 31)]

        def sheet(title, head, rows, preamble):
            wb = openpyxl.Workbook()
            wb.active.title = title
            for p in preamble:
                wb.active.append(p)
            wb.active.append(head)
            for r in rows:
                wb.active.append(r)
            buf = io.BytesIO()
            wb.save(buf)
            return buf.getvalue()
        one = sheet("Aufmaß", ["Pos.", "Art.-Nr.", "Bezeichnung", "Menge", "Einheit", "EP netto", "GP netto"],
                    [[i + 1, None, f"Leistung {i}", 2, "Stk", 100.0 + i, 2 * (100.0 + i)] for i in range(8)],
                    [["Aufmaß / Materialliste"], ["Auftrag:", "A26-028"], ["Kunde:", "Kunde 3"], []])
        two = sheet("Schlussaufmaß", ["Pos.", "Bezeichnung", "Menge", "Einheit", "EP", "GP"],
                    [[i + 1, f"Wohnung {i}", 1, "psch", 5000.0 + i, 5000.0 + i] for i in range(6)],
                    [["Schlussaufmaß BV Lindenstraße 14"], ["Bauherr: Kunde 1"], []])
        self.f.feed([("Auftragsbuch.csv", csv("Auftr.-Nr.;Datum;Kunde;Leistung;Wert", jobs)),
                     ("Aufmass_A26-028_Schulze_Bad.xlsx", one), ("Aufmass_A26-003_BV_Lindenstrasse_Schlussaufmass.xlsx", two)])
        rt = self.f.rt()
        am = [t for t in rt.model["types"] if t.get("concept") == "aufmass"]
        self.assertEqual([(t["name"], len(rt.records[t["id"]])) for t in am], [("Aufmaßposition", 14)])  # one list
        job = _type(rt, "Auftrag")
        ref = next(a for a in am[0]["attrs"] if a["kind"] == "ref" and a.get("ref") == job["id"])
        self.assertEqual({rt.title(r["data"].get(ref["id"])) for r in rt.records[am[0]["id"]]}, {"A26-028", "A26-003"})

    def test_a_draft_written_here_is_no_copy_from_another_program(self):
        import re
        from starlette.testclient import TestClient
        from physarum.web.app import create_app
        rows = _book(24)
        self.f.feed([("Rechnungsausgangsbuch.csv", csv(BOOK_HEAD, rows))])
        rt = self.f.rt()
        inv = _type(rt, "Rechnung")
        c = TestClient(create_app(self.f.dir / "firma"))
        imported = next(r["id"] for r in rt.records[inv["id"]])
        self.assertIn("anderen Programm", c.get(f"/r/{imported}/druck").text)   # the book's invoice: a copy
        form = c.get(f"/t/{inv['id']}/neu").text
        vals = dict(re.findall(r'name="(a_[^"]+)"[^>]*value="([^"]*)"', form))
        r = c.post(f"/t/{inv['id']}/neu", data=vals, headers={"origin": "http://testserver"}, follow_redirects=False)
        draft = int(re.search(r"/r/(\d+)", r.headers["location"]).group(1))
        page = c.get(f"/r/{draft}/druck").text
        self.assertIn("Vorschau eines Entwurfs", page)
        self.assertNotIn("anderen Programm", page)                              # written here, not a copy

    def test_cash_part_payments_and_a_bank_line_the_owner_assigns(self):
        from starlette.testclient import TestClient
        from physarum.grow import regrow
        from physarum.web.app import create_app
        rows = _book(24, start=date(2026, 6, 1))
        bank = [[r[1], r[2], f"Rechnung {r[0]}", r[8]] for r in rows[:20]]
        bank.append(["20.10.2026", "Kunde 4", "Danke für die Arbeiten", rows[22][8]])   # no number: which one?
        self.f.feed([("Rechnungsausgangsbuch.csv", csv(BOOK_HEAD, rows)), ("Umsaetze.csv", csv(BANK_HEAD, bank))])
        rt = self.f.rt()
        inv = _type(rt, "Rechnung")
        rid = {rt.by_id[r["id"]]["data"][inv["key"]]: r["id"] for r in rt.records[inv["id"]]}
        c = TestClient(create_app(self.f.dir / "firma"))
        h = {"origin": "http://testserver"}
        # a customer pays part in cash at the counter
        target = rid[rows[21][0]]
        gross = rt.ledger[target]["gross"]
        r = c.post(f"/r/{target}/zahlung", data={"amount": "100,00", "date": "2026-10-28", "how": "bar"}, headers=h).json()
        self.assertIn(f"noch offen", r["toast"])
        rt = self.f.rt()
        self.assertEqual(rt.ledger[target]["state"], "teilbezahlt")
        self.assertAlmostEqual(rt.ledger[target]["open"], gross - 100, places=2)
        # the bank line without a number: the owner says which invoice it pays – and that holds after growing
        b = next(x["rid"] for g in rt.work(date(2026, 10, 29)) if g["kind"] == "receipt" for x in g["items"])
        self.assertIn("Wofür ist diese Zahlung?", c.get(f"/r/{b}").text)
        r = c.post(f"/r/{b}/zuordnen", data={"invoice": str(rid[rows[22][0]])}, headers=h).json()
        self.assertTrue(r.get("reload") or r.get("job"), r)
        regrow(self.f.store)
        rt = self.f.rt()
        self.assertEqual(rt.ledger[rid[rows[22][0]]]["state"], "bezahlt")
        self.assertEqual(rt.ledger[target]["state"], "teilbezahlt")                # the cash stays as well
        # and both can be taken back
        pid = rt.ledger[target]["payments"][0]["by_hand"]
        c.post(f"/r/{target}/zahlung-entfernen", data={"id": str(pid)}, headers=h)
        c.post(f"/r/{rid[rows[22][0]]}/zahlung-loesen", data={"bank": str(b)}, headers=h)
        rt = self.f.rt()
        self.assertEqual((rt.ledger[target]["state"], rt.ledger[rid[rows[22][0]]]["state"]), ("offen", "offen"))

    def test_the_final_invoice_marks_its_order_invoiced(self):
        from physarum import billing, ops
        jobs = [[f"A26-{i:03d}", f"0{(i % 8) + 1}.0{(i % 8) + 1}.2026", f"Kunde {i % 4}", "Bad", "4000",
                 "abgerechnet" if i < 20 else "fertig" if i < 26 else "in Arbeit",
                 f"RE-2026-{i:04d}" if i < 20 else ""] for i in range(1, 31)]
        book = [[f"RE-2026-{i:04d}", f"1{(i % 8) + 1}.0{(i % 8) + 1}.2026", f"Kunde {i % 4}", f"A26-{i:03d}",
                 "Abschlagsrechnung" if i % 5 == 0 else "Rechnung", _eur(1000 + 50 * i), _eur((1000 + 50 * i) * 0.19),
                 _eur((1000 + 50 * i) * 1.19)] for i in range(1, 20)]
        customers = csv("Kd.-Nr.;Name;Straße;PLZ;Ort", [[f"K{i}", f"Kunde {i}", "Hauptstr. 1", "33602", "Bielefeld"]
                                                         for i in range(4)])
        self.f.feed([("Kunden.csv", customers),
                     ("Auftragsbuch.csv", csv("Auftr.-Nr.;Datum;Kunde;Leistung;Wert;Status;Rechnung", jobs)),
                     ("Rechnungsausgangsbuch.csv", csv("Re.-Nr.;Datum;Kunde;Auftrag;Art;Netto;USt;Brutto", book))])
        self.f.store.kv_set("company_profile", dict(name="Muster Haustechnik GmbH", street="Hauptstr. 1", zip="33602",
                                                    city="Bielefeld", vat_id="DE123456789"))
        rt = self.f.rt()
        job, inv = _type(rt, "Auftrag"), _type(rt, "Rechnung")
        status = next(a for a in job["attrs"] if a["name"] == "Status")
        order = {rt.by_id[r["id"]]["data"][job["key"]]: r["id"] for r in rt.records[job["id"]]}
        ref = next(a for a in inv["attrs"] if a["kind"] == "ref" and a.get("ref") == job["id"])
        art = next(a for a in inv["attrs"] if a["name"] == "Art")

        def invoice(no, kind):
            rid = ops.create(rt, inv["id"], {ref["id"]: str(order[no]), art["id"]: kind}, "Test")
            billing.set_positions(rt, rid, [dict(text="Badsanierung", qty="1", price="4000", rate="19")], "Test")
            billing.issue(rt, rid, "Test", delivery="2026-10-20")
            rt.ensure()
        invoice("A26-027", "Abschlagsrechnung")                               # a down payment: still working
        self.assertEqual(rt.by_id[order["A26-027"]]["data"][status["id"]], "in Arbeit")
        invoice("A26-021", "Rechnung")                                        # the final one: invoiced
        self.assertEqual(rt.by_id[order["A26-021"]]["data"][status["id"]], "abgerechnet")

    def test_what_the_statement_cannot_see_and_what_comes_every_week(self):
        import random
        from physarum.demo.generate import make_iban
        rng = random.Random(7)
        today = date(2026, 10, 29)
        iban = {n: make_iban(rng) for n in range(5)}
        rows, bank = [], []
        for i in range(30):
            d = date(2026, 6, 1) + timedelta(days=4 * i)
            net, paid = 500 + 20 * i, d + timedelta(days=10)
            rows.append([f"RE-2026-{i + 1:04d}", d.strftime("%d.%m.%Y"), f"Kunde {i % 5}", _eur(net), _eur(net * 0.19),
                         _eur(net * 1.19), (d + timedelta(days=14)).strftime("%d.%m.%Y"), paid.strftime("%d.%m.%Y")])
            if i not in (20, 25):
                bank.append([paid.strftime("%d.%m.%Y"), f"KUNDE {i % 5}", iban[i % 5], f"Rechnung RE-2026-{i + 1:04d}",
                             _eur(net * 1.19)])
        # Kunde 0 pays two invoices with one transfer; the book gives each its own day
        rows[20][7], rows[25][7] = "16.09.2026", "19.09.2026"
        both = round(float(rows[20][5].replace(",", ".")) + float(rows[25][5].replace(",", ".")), 2)
        bank.append(["19.09.2026", "KUNDE 0", iban[0], "Sammelzahlung", _eur(both)])
        shop = make_iban(rng)
        for k in range(8):  # the shop's weekly payout pays no invoice and never will
            day = date(2026, 9, 7) + timedelta(days=7 * k)
            bank.append([day.strftime("%d.%m.%Y"), "SHOP PAYMENTS EUROPE", shop, f"Auszahlung Shop {37 + k}/2026",
                         _eur(400 + 97 * k)])
        bank.append(["02.10.2026", "HANS MEIER", make_iban(rng), "Danke für alles", "777,00"])
        good = "DE89370400440532013000"
        self.f.feed([("Kunden.csv", csv("Kd.-Nr.;Name;Ort", [[f"K{i}", f"Kunde {i}", "Bielefeld"] for i in range(5)])),
                     ("Rechnungsausgangsbuch.csv", csv("Rechnungsnr;Datum;Kunde;Netto;USt;Brutto;fällig am;bezahlt am", rows)),
                     ("Umsaetze.csv", csv("Buchungstag;Auftraggeber/Empfänger;IBAN;Verwendungszweck;Betrag", bank)),
                     # due in early June, before the statement begins: whether it was paid, the bank cannot say
                     ("Eingangsrechnungen/RE_4471300.pdf", _supplier_invoice("4471300", date(2026, 5, 4), 1000.0, good)),
                     ("Eingangsrechnungen/RE_4471301.pdf", _supplier_invoice("4471301", date(2026, 10, 20), 2000.0, good))])
        rt = self.f.rt()
        inv, inc = _type(rt, "Rechnung"), _type(rt, "Eingangsrechnung")
        st = _states(rt, inv)
        for no in ("RE-2026-0021", "RE-2026-0026"):
            self.assertEqual(st[no]["state"], "bezahlt")
            self.assertIn("Sammelzahlung", st[no]["payments"][0]["how"])
            self.assertIsNotNone(st[no]["payments"][0]["rid"])
        work = rt.work(today)
        receipts = [x["money"] for g in work if g["kind"] == "receipt" for x in g["items"]]
        self.assertEqual(receipts, [777.0])                     # not the shop, not the collective transfer
        old = _states(rt, inc)["4471300"]
        self.assertEqual(old["unseen"], date(2026, 6, 11))
        self.assertIn("ob bezahlt, zeigt ein älterer Auszug", " ".join(old["notes"]))
        pay = [x["title"] for g in work if g["kind"] in ("payable", "overdue") and g["type"] == inc["id"] for x in g["items"]]
        self.assertEqual(pay, ["4471301"])                      # what is due now – not what the statement cannot see

    def test_an_order_whose_invoice_was_cancelled_long_ago_is_no_work(self):
        today = date(2026, 10, 29)
        jobs, book = [], []
        for i in range(1, 31):
            start = date(2026, 3, 2) + timedelta(days=7 * i)
            done = start + timedelta(days=10)
            jobs.append([f"A26-{i:03d}", start.strftime("%d.%m.%Y"), f"Kunde {i % 4}", "Bad", _eur(3000 + 10 * i),
                         done.strftime("%d.%m.%Y")])
            if i < 30:
                status = "storniert" if i in (5, 29) else "bezahlt"
                book.append([f"RE-2026-{i:04d}", (done + timedelta(days=2)).strftime("%d.%m.%Y"), f"Kunde {i % 4}",
                             f"A26-{i:03d}", _eur(3000 + 10 * i), _eur((3000 + 10 * i) * 0.19),
                             _eur((3000 + 10 * i) * 1.19), status,
                             "" if status == "storniert" else (done + timedelta(days=20)).strftime("%d.%m.%Y")])
        self.f.feed([("Auftragsbuch.csv", csv("Auftr.-Nr.;Datum;Kunde;Leistung;Wert;fertig am", jobs)),
                     ("Rechnungsausgangsbuch.csv", csv("Re.-Nr.;Datum;Kunde;Auftrag;Netto;USt;Brutto;Status;bezahlt am",
                                                       book))])
        rt = self.f.rt()
        job = _type(rt, "Auftrag")
        ready = next(g for g in rt.work(today) if g["type"] == job["id"] and g["kind"] == "ready")
        got = {rt.by_id[x["rid"]]["data"][job["key"]]: x for x in ready["items"]}
        self.assertNotIn("A26-005", got)                        # cancelled in spring, nothing followed: decided
        self.assertEqual(got["A26-029"]["reason"], "RE-2026-0029 storniert, noch keine neue")
        self.assertIn("A26-030", got)                           # finished, never invoiced
        self.assertIsNone(got["A26-030"]["reason"])


if __name__ == "__main__":
    unittest.main()
