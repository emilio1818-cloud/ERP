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


if __name__ == "__main__":
    unittest.main()
