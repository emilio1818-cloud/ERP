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


if __name__ == "__main__":
    unittest.main()
