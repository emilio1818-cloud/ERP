"""Paid is what the money says: partial, skonto, double, chargeback, collective, cancelled."""
import shutil
import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path

from physarum.grow import ingest, regrow
from physarum.runtime import Runtime
from physarum.store import Store

TODAY = date.today()


def de(d: date) -> str:
    return d.strftime("%d.%m.%Y")


def eur(x: float) -> str:
    return f"{x:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


class Payments(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = Path(tempfile.mkdtemp(prefix="physarum-pay-"))
        names = ["Café Linde", "Hotel Möwe", "Bistro Anker", "Kanzlei Lotse", "Bäckerei Krume", "Büro Kompass"]
        inv = ["Rechnungsnr;Rechnungsdatum;Kunde;Netto;MwSt;Brutto;Fällig am;Bezahlt am;Status"]
        bank = ["Buchungstag;Verwendungszweck;Zahlungspartner;Betrag"]
        cls.no = {}
        start = TODAY - timedelta(days=200)
        for i in range(40):
            d = start + timedelta(days=4 * i)
            net = 100.0 + 7 * i
            tax = round(net * 0.07, 2)
            gross = round(net + tax, 2)
            no = f"RE-{d.year}-{i + 1:04d}"
            cust = names[i % 6]
            status, paid_at = "offen", ""
            if i < 30:  # normal: paid after ~10 days, by the book and by the bank
                paid = d + timedelta(days=10)
                status, paid_at = "bezahlt", de(paid)
                bank.append(f"{de(paid)};{no};{cust};{eur(gross)}")
            inv.append(f"{no};{de(d)};{cust};{eur(net)};{eur(tax)};{eur(gross)};{de(d + timedelta(days=14))};{paid_at};{status}")
            cls.no[i] = (no, gross, d)
        # the special cases, all still "offen" in the book
        n, g, d = cls.no[30]; bank.append(f"{de(d + timedelta(days=5))};{n} Teilzahlung;X;{eur(100.0)}")       # partial
        n, g, d = cls.no[31]; bank.append(f"{de(d + timedelta(days=5))};{n} abzgl. 2% Skonto;X;{eur(round(g * 0.98, 2))}")
        n, g, d = cls.no[32]; bank += [f"{de(d + timedelta(days=5))};{n};X;{eur(g)}", f"{de(d + timedelta(days=6))};{n};X;{eur(g)}"]
        n, g, d = cls.no[33]; bank += [f"{de(d + timedelta(days=5))};{n};X;{eur(g)}",
                                       f"{de(d + timedelta(days=9))};RUECKLASTSCHRIFT {n};X;-{eur(g)}"]
        n1, g1, d1 = cls.no[34]; n2, g2, _ = cls.no[35]
        bank.append(f"{de(d1 + timedelta(days=20))};{n1} und {n2};X;{eur(round(g1 + g2, 2))}")             # collective
        n, g, d = cls.no[38]; bank.append(f"{de(d + timedelta(days=5))};{n} abzgl. 3% Reklamation;X;{eur(round(g * 0.97, 2))}")
        n1, g1, d1 = cls.no[37]; n2, g2, _ = cls.no[39]
        bank.append(f"{de(d1 + timedelta(days=9))};{n1}, {n2};X;{eur(g2)}")   # names two, pays exactly the second
        n, g, d = cls.no[36]
        inv = [l.replace(f"{n};", f"{n};", 1) if not l.startswith(n) else l.rsplit(";", 1)[0] + ";storniert" for l in inv]
        bank.append(f"{de(d + timedelta(days=3))};{n};X;{eur(g)}")                                          # on cancelled
        (cls.tmp / "Rechnungen.csv").write_text("\n".join(inv) + "\n", encoding="utf-8")
        (cls.tmp / "Konto.csv").write_text("\n".join(bank) + "\n", encoding="utf-8")
        # only Hotel Möwe is granted skonto
        kunden = ["Kunde;Ort;Skonto"] + [f"{n};Hamburg;{'2 %' if n == 'Hotel Möwe' else ''}" for n in names]
        (cls.tmp / "Kunden.csv").write_text("\n".join(kunden) + "\n", encoding="utf-8")
        cls.store = Store(cls.tmp / "firma")
        ingest(cls.store, [(p.name, p.read_bytes()) for p in [cls.tmp / "Rechnungen.csv", cls.tmp / "Konto.csv",
                                                              cls.tmp / "Kunden.csv"]], "T")
        regrow(cls.store)
        cls.rt = Runtime(cls.store)
        cls.rt.ensure()
        spec = next(t for t in cls.rt.model["types"] if t["name"] == "Rechnung")
        cls.by_no = {r["data"][spec["key"]]: cls.rt.ledger.get(r["id"]) for r in cls.rt.records[spec["id"]]}

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def e(self, i):
        return self.by_no[self.no[i][0]]

    def test_normal_invoices_are_paid(self):
        self.assertTrue(all(self.e(i)["state"] == "bezahlt" for i in range(30)))

    def test_partial_payment_leaves_the_rest_open(self):
        e = self.e(30)
        self.assertEqual(e["state"], "teilbezahlt")
        self.assertAlmostEqual(e["open"], round(self.no[30][1] - 100, 2), places=2)

    def test_skonto_counts_as_paid_where_it_is_granted(self):
        e = self.e(31)                          # Hotel Möwe: 2 % skonto agreed
        self.assertEqual(e["state"], "bezahlt")
        self.assertIsNotNone(e["skonto"])

    def test_a_deduction_without_skonto_stays_open(self):
        e = self.e(38)                          # Bistro Anker deducted 3 % for a complaint
        self.assertEqual(e["state"], "teilbezahlt")
        self.assertTrue(any("ohne dass Skonto vereinbart" in n for n in e["notes"]))

    def test_a_transfer_pays_what_its_amount_fits(self):
        self.assertEqual(self.e(39)["state"], "bezahlt")
        self.assertEqual(self.e(37)["state"], "offen")

    def test_double_payment(self):
        e = self.e(32)
        self.assertEqual(e["state"], "überzahlt")
        self.assertTrue(any("doppelt" in n for n in e["notes"]))

    def test_chargeback_reopens(self):
        self.assertEqual(self.e(33)["state"], "offen")

    def test_collective_transfer_is_split(self):
        self.assertEqual(self.e(34)["state"], "bezahlt")
        self.assertEqual(self.e(35)["state"], "bezahlt")

    def test_payment_on_cancelled_invoice_is_flagged(self):
        e = self.e(36)
        self.assertEqual(e["state"], "storniert")
        self.assertTrue(e["notes"])

    def test_one_truth_on_every_page(self):
        spec = next(t for t in self.rt.model["types"] if t["name"] == "Rechnung")
        r = next(r for r in self.rt.records[spec["id"]] if r["data"][spec["key"]] == self.no[30][0])
        self.assertEqual(r["data"]["pay_state"], "teilbezahlt")        # list column and facet
        work = self.rt.work()
        overdue = [x for g in work if g["kind"] == "overdue" and g["type"] == spec["id"] for x in g["items"]]
        partial = next(x for x in overdue if x["rid"] == r["id"])
        self.assertAlmostEqual(partial["money"], self.e(30)["open"], places=2)  # only what is missing
        self.assertTrue(any(g["id"] == "pay:problems" for g in work))
        paid_rids = {rid for rid, e in self.rt.ledger.items() if e["state"] == "bezahlt"}
        self.assertFalse(paid_rids & {x["rid"] for x in overdue})      # nobody gets dunned for paid money


class OtherHeadings(unittest.TestCase):
    """Paid is what the money says, whatever the columns and files are called: the book's own date that
    agrees with the bank's transfers is the date of payment."""

    def grow(self, head: str, names: tuple[str, str]) -> dict:
        tmp = Path(tempfile.mkdtemp(prefix="physarum-names-"))
        self.addCleanup(shutil.rmtree, tmp, True)
        start = TODAY - timedelta(days=160)
        inv, bank = [head], ["Buchungstag;Verwendungszweck;Zahlungspartner;Betrag"]
        for i in range(12):
            d = start + timedelta(days=12 * i)
            gross = 119.0 + 11 * i
            no, cust = f"B-{d.year}-{i + 1:03d}", ["Café Linde", "Hotel Möwe", "Bistro Anker"][i % 3]
            paid = d + timedelta(days=9)
            book = de(paid) if i < 8 else ""        # 0–3 before the statement, 4–7 in both, 8–9 bank only
            if 4 <= i < 10:
                bank.append(f"{de(paid + timedelta(days=i % 2))};Rechnung {no} vielen Dank;{cust};{eur(gross)}")
            if i >= 4:  # a statement also holds what the firm pays
                bank.append(f"{de(d + timedelta(days=1))};Miete Laden Monat {d.month};Immobilien Kuhn GbR;-{eur(950.0)}")
            inv.append(f"{no};{de(d)};{cust};{eur(gross)};{de(d + timedelta(days=14))};{book}")
        (tmp / names[0]).write_text("\n".join(inv) + "\n", encoding="utf-8")
        (tmp / names[1]).write_text("\n".join(bank) + "\n", encoding="utf-8")
        store = Store(tmp / "firma")
        ingest(store, [(n, (tmp / n).read_bytes()) for n in names], "T")
        regrow(store)
        rt = Runtime(store)
        rt.ensure()
        spec = next(t for t in rt.model["types"] if any(str(r["data"].get(t.get("key"))).startswith("B-")
                                                        for r in rt.records.get(t["id"], [])))
        proc = next(p for p in rt.model["processes"] if p["type"] == spec["id"])
        self.assertIn("bezahlt", [s["label"] for s in proc["steps"]])
        # whatever the files are called: an invoice list and a bank statement, with everything that goes with them
        self.assertEqual((spec["plural"], spec.get("concept")), ("Rechnungen", "rechnung"))
        self.assertIn("Kontobewegungen", [t["plural"] for t in rt.model["types"]])
        return {r["data"][spec["key"]][-3:]: rt.ledger[r["id"]]["state"] for r in rt.records[spec["id"]]}

    def test_same_money_under_other_names(self):
        usual = self.grow("Rechnungsnr;Rechnungsdatum;Kunde;Brutto;Fällig am;Bezahlt am", ("Rechnungen.csv", "Konto.csv"))
        other = self.grow("Beleg;Belegdatum;Empfänger;Bruttobetrag;Zahlbar bis;Ausgeglichen am",
                          ("export (1).csv", "export (2).csv"))
        self.assertEqual(usual, other)
        self.assertEqual({k for k, v in other.items() if v == "bezahlt"}, {f"{i + 1:03d}" for i in range(10)})


class MoneyBack(unittest.TestCase):
    """Money that goes back: a refund leaves the invoice settled, a returned debit opens it again – also
    when the debit it returns was one of a collective one; a deduction the book accepted is skonto."""

    @classmethod
    def setUpClass(cls):
        cls.tmp = Path(tempfile.mkdtemp(prefix="physarum-back-"))
        start = TODAY - timedelta(days=150)
        inv = ["Rechnungsnr;Rechnungsdatum;Kunde;Brutto;Fällig am;Bezahlt am;Storniert am"]
        bank = ["Buchungstag;Verwendungszweck;Zahlungspartner;Betrag"]
        cls.no = {}
        for i in range(12):
            d = start + timedelta(days=11 * i)
            g = 200.0 + 10 * i
            no, cust = f"RE-{d.year}-{i + 1:04d}", ["Café Linde", "Hotel Möwe", "Bistro Anker"][i % 3]
            paid, booked, void = d + timedelta(days=8), "", ""
            if i < 9:
                bank.append(f"{de(paid)};{no} danke;{cust};{eur(g)}")
                booked = de(paid)
            if i == 8:   # half a return sent back
                bank.append(f"{de(paid + timedelta(days=12))};Erstattung {no} Ruecksendung;{cust};-{eur(50.0)}")
            if i == 9:   # 2 % less, and the book has it as paid
                bank.append(f"{de(paid)};{no} abzgl. 2% Skonto;{cust};{eur(round(g * 0.98, 2))}")
                booked = de(paid)
            if i == 10:  # debited with others in one go, returned with the bank's fee
                bank.append(f"{de(paid + timedelta(days=5))};RUECKLASTSCHRIFT {no} zzgl. Entgelt 3,00 EUR;{cust};-{eur(g + 3.0)}")
                booked = de(paid)
            if i == 11:
                void = de(d + timedelta(days=2))
            bank.append(f"{de(d + timedelta(days=1))};Miete Laden;Immobilien Kuhn GbR;-{eur(950.0)}")
            inv.append(f"{no};{de(d)};{cust};{eur(g)};{de(d + timedelta(days=14))};{booked};{void}")
            cls.no[i] = no
        (cls.tmp / "Rechnungen.csv").write_text("\n".join(inv) + "\n", encoding="utf-8")
        (cls.tmp / "Konto.csv").write_text("\n".join(bank) + "\n", encoding="utf-8")
        cls.store = Store(cls.tmp / "firma")
        ingest(cls.store, [(n, (cls.tmp / n).read_bytes()) for n in ("Rechnungen.csv", "Konto.csv")], "T")
        regrow(cls.store)
        cls.rt = Runtime(cls.store)
        cls.rt.ensure()
        spec = next(t for t in cls.rt.model["types"] if t["name"] == "Rechnung")
        cls.by_no = {r["data"][spec["key"]]: cls.rt.ledger.get(r["id"]) for r in cls.rt.records[spec["id"]]}

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def test_a_refund_leaves_it_settled(self):
        e = self.by_no[self.no[8]]
        self.assertEqual(e["state"], "bezahlt")
        self.assertTrue(any("50,00 € erstattet" in n for n in e["notes"]))

    def test_a_returned_debit_opens_it_again(self):
        e = self.by_no[self.no[10]]
        self.assertEqual(e["state"], "offen")
        self.assertAlmostEqual(e["open"], 300.0, places=2)                 # the invoice, not the bank's fee

    def test_a_deduction_the_book_accepted_is_skonto(self):
        e = self.by_no[self.no[9]]
        self.assertEqual(e["state"], "bezahlt")
        self.assertTrue(e["skonto"])

    def test_a_cancellation_date_ends_the_claim(self):
        self.assertEqual(self.by_no[self.no[11]]["state"], "storniert")


if __name__ == "__main__":
    unittest.main()
