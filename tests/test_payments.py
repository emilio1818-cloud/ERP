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


class PlainNumbers(unittest.TestCase):
    """A workshop numbers its invoices 31001, 31002, …: "Rg 31076" in a purpose is that invoice, though the
    number is short. Cash at the counter goes by the book; a sale without an order is overdue all the
    same; the customer list keeps the surname as "Name" next to "Vorname"."""

    @classmethod
    def setUpClass(cls):
        cls.tmp = Path(tempfile.mkdtemp(prefix="physarum-plain-"))
        people = [("Hoffmann", "Sabine"), ("Ahlke", "Jan"), ("Kaya", "Peter"), ("Wolf", "Jan"), ("Meyer", "Ayse")]
        kunden = ["KdNr;Name;Vorname;PLZ;Ort"] + [f"{10100 + 37 * i};{n};{v};5955{i};Lippstadt"
                                                  for i, (n, v) in enumerate(people)]
        orders = ["Auftrag;Annahme;Kd.-Nr.;Arbeiten"]
        inv = ["Rg-Nr.;Datum;Kd-Nr.;Kennz.;Auftr.;Brutto;Zahlart;fällig;bez. am;Betrag erh."]
        bank = ["Buchungstag;Auftraggeber;Verwendungszweck;Betrag"]
        start = TODAY - timedelta(days=90)
        cls.no = {}
        for i in range(30):
            d = start + timedelta(days=2 * i)
            no, g, (n, v) = 31001 + i, round(80.0 + 13.5 * i, 2), people[i % 5]
            kd = 10100 + 37 * (i % 5)
            order = f"26-{500 + i:04d}" if i % 3 else ""     # every third a sale at the counter, no order
            if order:
                orders.append(f"{order};{de(d - timedelta(days=i % 2))};{kd};Inspektion")
            cash = i % 2 == 0 and i < 26
            # the book: cash the day of the sale, transfers ticked off until a few weeks ago
            paid = de(d) if cash else de(d + timedelta(days=6)) if i < 12 else ""
            got = eur(g) if paid else ""
            plate = f"LP-{v[0]}{n[0]} {100 + 7 * (i % 5) + (i // 5) % 2}"  # two cars each, in for this and that
            if not cash and i < 26 and i != 21:
                bank.append(f"{de(d + timedelta(days=6))};{v} {n};Rg {no};{eur(g)}")
            if i == 21:  # the insurer pays, the deductible was paid by card at the counter: the book has both
                bank.append(f"{de(d + timedelta(days=9))};Kreis-Versicherung;Schaden Rg {no};{eur(g - 150.0)}")
                got = eur(g)
            if i == 27:  # by transfer, the number not given: who paid and how much tell
                bank.append(f"{de(d + timedelta(days=5))};{v.upper()} {n.upper()};Inspektion Werkstatt;{eur(g)}")
            if i == 28:  # 40 € down at the counter, the rest still to come
                got = eur(40.0)
            inv.append(f"{no};{de(d)};{kd};{plate};{order};{eur(g)};{'bar' if cash else 'Überw.'};"
                       f"{'' if cash else de(d + timedelta(days=14))};{paid};{got}")
            cls.no[i] = str(no)
        files = {"Kunden.csv": kunden, "Auftragsbuch.csv": orders, "Rechnungsbuch.csv": inv, "Konto.csv": bank}
        for n, rows in files.items():
            (cls.tmp / n).write_text("\n".join(rows) + "\n", encoding="utf-8")
        cls.store = Store(cls.tmp / "firma")
        ingest(cls.store, [(n, (cls.tmp / n).read_bytes()) for n in files], "T")
        regrow(cls.store)
        cls.rt = Runtime(cls.store)
        cls.rt.ensure()
        spec = next(t for t in cls.rt.model["types"] if t.get("concept") == "rechnung")
        cls.by_no = {str(r["data"][spec["key"]]): cls.rt.ledger.get(r["id"]) for r in cls.rt.records[spec["id"]]}
        cls.overdue = {cls.rt.title(x["rid"]) for g in cls.rt.work(TODAY) if g["kind"] == "overdue" for x in g["items"]}

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def test_a_short_number_in_the_purpose_pays_its_invoice(self):
        e = self.by_no[self.no[1]]
        self.assertEqual(e["state"], "bezahlt")
        self.assertTrue(any(x.get("rid") for x in e["payments"]))            # by the bank line, not by the book

    def test_cash_at_the_counter_is_paid_by_the_book(self):
        self.assertEqual(self.by_no[self.no[0]]["state"], "bezahlt")

    def test_surname_and_first_name_make_the_payer(self):
        self.assertEqual(self.by_no[self.no[27]]["state"], "bezahlt")        # "SABINE HOFFMANN" paid, no number
        kunde = next(t for t in self.rt.model["types"] if t.get("concept") == "kunde")
        self.assertIn("Sabine Hoffmann", {self.rt.title(r["id"]) for r in self.rt.records[kunde["id"]]})

    def test_the_book_says_what_came_in_at_the_counter(self):
        self.assertEqual(self.by_no[self.no[21]]["state"], "bezahlt")        # insurer by bank, deductible by card
        e = self.by_no[self.no[28]]
        self.assertEqual(e["state"], "teilbezahlt")
        self.assertAlmostEqual(e["open"], e["gross"] - 40.0, places=2)

    def test_unpaid_is_overdue_with_or_without_an_order(self):
        self.assertIn(self.no[26], self.overdue)                              # an order's invoice (26 % 3 != 0)
        self.assertIn(self.no[29], self.overdue)                              # a sale at the counter, no order
        self.assertNotIn(self.no[1], self.overdue)


class Workshop(unittest.TestCase):
    """An order book of a workshop: the invoice the day the car is done, its number in "Rg." – or a word
    ("Kulanz") where nothing is invoiced; the cars of two customers called Thomas Becker stay two."""

    @classmethod
    def setUpClass(cls):
        cls.tmp = Path(tempfile.mkdtemp(prefix="physarum-shop-"))
        orders = ["Auftrag;Annahme;Kd.-Nr.;Kunde;Kennzeichen;Fahrzeug;fertig am;Status;Rg."]
        inv = ["Rg-Nr.;Datum;Kd-Nr.;Auftr.;Brutto;fällig"]
        start = TODAY - timedelta(days=80)
        cls.unbilled = set()
        cars = [(10133, "Becker, Th.", "LP-TB 412", "Opel Astra"), (10541, "Becker, Th.", "SO-TB 77", "VW Touran")] + \
            [(10200 + 17 * k, f"{n}, {v}.", f"LP-{v}{n[0]} {100 + 7 * k}", "Ford Fiesta")
             for k, (n, v) in enumerate([("Kaya", "P"), ("Wolf", "J"), ("Meyer", "A"), ("Brune", "R"), ("Lange", "M"),
                                         ("Pohl", "D"), ("Vogt", "K"), ("Albers", "F")])]
        for i in range(40):
            d = start + timedelta(days=2 * i)
            no, order = 41001 + i, f"26-{700 + i:04d}"
            kd, who, plate, car = cars[i % len(cars)]
            rg = str(no)
            if i in (11, 17):
                rg = ""                               # done, nobody wrote the invoice
                cls.unbilled.add(order)
            elif i == 13:
                rg = "Kulanz"                         # done for free: decided, nothing to invoice
            done = d + timedelta(days=i % 3)
            orders.append(f"{order};{de(d)};{kd};{who};{plate};{car};{de(done)};fertig;{rg}")
            if rg.isdigit():
                inv.append(f"{no};{de(done)};{kd};{order};{eur(100.0 + 7 * i)};{de(done + timedelta(days=14))}")
        files = {"Auftragsbuch.csv": orders, "Rechnungsbuch.csv": inv}
        for n, rows in files.items():
            (cls.tmp / n).write_text("\n".join(rows) + "\n", encoding="utf-8")
        cls.store = Store(cls.tmp / "firma")
        ingest(cls.store, [(n, (cls.tmp / n).read_bytes()) for n in files], "T")
        regrow(cls.store)
        cls.rt = Runtime(cls.store)
        cls.rt.ensure()

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def test_done_without_an_invoice_is_money_waiting(self):
        ready = {x["title"] for g in self.rt.work(TODAY) if g["kind"] == "ready" for x in g["items"]}
        self.assertEqual(ready, self.unbilled)                                # not the one done "Kulanz"

    def test_two_customers_of_one_name_stay_two(self):
        beckers = {r["id"] for t in self.rt.model["types"] if t["kind"] == "master"
                   for r in self.rt.records[t["id"]] if "Becker" in self.rt.title(r["id"])}
        self.assertEqual(len(beckers), 2)                                     # 10133 and 10541, two cars


class MoneyBack(unittest.TestCase):
    """Money that goes back: a refund leaves the invoice settled, a returned debit opens it again – also
    when the debit it returns was one of a collective one; a deduction is skonto where the terms grant it,
    not because the book has the invoice as paid."""

    @classmethod
    def setUpClass(cls):
        cls.tmp = Path(tempfile.mkdtemp(prefix="physarum-back-"))
        start = TODAY - timedelta(days=150)
        inv = ["Rechnungsnr;Rechnungsdatum;Kunde;Brutto;Fällig am;Bezahlt am;Storniert am;Zahlungsbedingung"]
        bank = ["Buchungstag;Verwendungszweck;Zahlungspartner;Betrag"]
        cls.no = {}
        for i in range(12):
            d = start + timedelta(days=11 * i)
            g = 200.0 + 10 * i
            no, cust = f"RE-{d.year}-{i + 1:04d}", ["Café Linde", "Hotel Möwe", "Bistro Anker"][i % 3]
            paid, booked, void = d + timedelta(days=8), "", ""
            terms = "8 Tage 2 % Skonto, 14 Tage netto" if i == 9 else "14 Tage netto"
            if i < 7 or i == 8:
                bank.append(f"{de(paid)};{no} danke;{cust};{eur(g)}")
                booked = de(paid)
            if i == 7:   # 3 % less although nothing was agreed – and the book has it as paid all the same
                bank.append(f"{de(paid)};{no} abzgl. 3% Skonto;{cust};{eur(round(g * 0.97, 2))}")
                booked = de(paid)
            if i == 8:   # half a return sent back
                bank.append(f"{de(paid + timedelta(days=12))};Erstattung {no} Ruecksendung;{cust};-{eur(50.0)}")
            if i == 9:   # 2 % less, as the terms allow
                bank.append(f"{de(paid)};{no} abzgl. 2% Skonto;{cust};{eur(round(g * 0.98, 2))}")
                booked = de(paid)
            if i == 10:  # debited with others in one go, returned with the bank's fee
                bank.append(f"{de(paid + timedelta(days=5))};RUECKLASTSCHRIFT {no} zzgl. Entgelt 3,00 EUR;{cust};-{eur(g + 3.0)}")
                booked = de(paid)
            if i == 11:
                void = de(d + timedelta(days=2))
            bank.append(f"{de(d + timedelta(days=1))};Miete Laden;Immobilien Kuhn GbR;-{eur(950.0)}")
            inv.append(f"{no};{de(d)};{cust};{eur(g)};{de(d + timedelta(days=14))};{booked};{void};{terms}")
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

    def test_a_deduction_the_terms_grant_is_skonto(self):
        e = self.by_no[self.no[9]]
        self.assertEqual(e["state"], "bezahlt")
        self.assertTrue(e["skonto"])

    def test_a_deduction_nobody_agreed_stays_open(self):
        e = self.by_no[self.no[7]]
        self.assertEqual(e["state"], "teilbezahlt")                       # the book's date does not grant it
        self.assertTrue(any("ohne dass" in n for n in e["notes"]))

    def test_a_cancellation_date_ends_the_claim(self):
        self.assertEqual(self.by_no[self.no[11]]["state"], "storniert")


class WhoPaid(unittest.TestCase):
    """Names as people write them: a family is no bakery of the same name, the place in brackets tells two
    "Müller, Hans" apart, and a family in no list still pays its invoice by amount and name."""

    @classmethod
    def setUpClass(cls):
        cls.tmp = Path(tempfile.mkdtemp(prefix="physarum-who-"))
        kunden = ["Kd-Nr;Anrede;Name;Straße;PLZ;Ort",
                  "K-1;Firma;Bäckerei Fischer;Bettenhäuser Straße 12;34123;Kassel",
                  "K-2;Herr;Müller, Hans;Wilhelmshöher Allee 210;34119;Kassel",
                  "K-3;Herr;Müller, Hans;Kasseler Straße 5;34246;Vellmar"]
        kunden += [f"K-{i};Firma;Firma {n};Straße {i};341{i:02d};Kassel" for i, n in
                   enumerate(["Lotse", "Anker", "Krume", "Kompass", "Möwe", "Linde"], start=4)]
        start = TODAY - timedelta(days=120)
        inv = ["Re-Nr.;Re-Datum;Kunde;Brutto;fällig am;bezahlt am"]
        bank = ["Buchungstag;Verwendungszweck;Zahlungspflichtiger;Betrag"]
        who = ["Firma Lotse", "Firma Anker", "Firma Krume", "Firma Kompass", "Firma Möwe", "Firma Linde",
               "Bäckerei Fischer", "Fam. Fischer", "Müller, Hans (Vellmar)"]
        cls.no = {}
        for i, name in enumerate(who):
            d = start + timedelta(days=9 * i)
            g = 300.0 + 17 * i
            no = f"RE-{d.year}-{i + 1:03d}"
            cls.no[name] = no
            if i < 7:
                bank.append(f"{de(d + timedelta(days=7))};{no};{name};{eur(g)}")
            elif name == "Fam. Fischer":
                bank.append(f"{de(d + timedelta(days=12))};Malerarbeiten Kinderzimmer Danke;Fischer, Jan und Petra;{eur(g)}")
            else:
                bank.append(f"{de(d + timedelta(days=12))};Malerarbeiten Wohnzimmer;Hans Mueller;{eur(g)}")
            bank.append(f"{de(d + timedelta(days=1))};Miete Werkstatt;Immobilien Kuhn GbR;-{eur(1450.0)}")
            inv.append(f"{no};{de(d)};{name};{eur(g)};{de(d + timedelta(days=14))};")
        for n, rows in (("Kundenliste.csv", kunden), ("Rechnungsbuch.csv", inv), ("Girokonto.csv", bank)):
            (cls.tmp / n).write_text("\n".join(rows) + "\n", encoding="utf-8")
        cls.store = Store(cls.tmp / "firma")
        ingest(cls.store, [(n, (cls.tmp / n).read_bytes()) for n in ("Kundenliste.csv", "Rechnungsbuch.csv", "Girokonto.csv")], "T")
        regrow(cls.store)
        cls.rt = Runtime(cls.store)
        cls.rt.ensure()
        spec = next(t for t in cls.rt.model["types"] if t["name"] == "Rechnung")
        party = next(a["id"] for a in spec["attrs"] if a["kind"] == "ref")
        cls.inv = {r["data"][spec["key"]]: r for r in cls.rt.records[spec["id"]]}
        cls.party = party

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def customer_of(self, name):
        v = self.inv[self.no[name]]["data"].get(self.party)
        return self.rt.by_id[v]["data"] if isinstance(v, int) else None

    def test_a_family_is_no_bakery(self):
        self.assertIsNone(self.customer_of("Fam. Fischer"))
        self.assertEqual(self.rt.ledger[self.inv[self.no["Fam. Fischer"]]["id"]]["state"], "bezahlt")  # by amount and name

    def test_the_place_tells_two_of_a_name_apart(self):
        c = self.customer_of("Müller, Hans (Vellmar)")
        self.assertIsNotNone(c)
        self.assertIn("Vellmar", [v for v in c.values() if isinstance(v, str)])
        self.assertEqual(self.rt.ledger[self.inv[self.no["Müller, Hans (Vellmar)"]]["id"]]["state"], "bezahlt")


class UntilTheMoney(unittest.TestCase):
    """A project is billed where its invoice names it in the text ("Anzahlung P-2026-003"); the chain goes from
    the project to the money, invoiced with the last invoice (the down payment comes before the work is done),
    and a project billed month by month is a running case, not a way to one payment."""

    def test_the_chain_follows_an_invoice_that_names_the_project(self):
        tmp = Path(tempfile.mkdtemp(prefix="physarum-chain-"))
        self.addCleanup(shutil.rmtree, tmp, True)
        start = TODAY - timedelta(days=300)
        proj = ["Projekt-Nr;Kunde;Projekt;Start"]
        inv = ["Rechnungsnr;Rechnungsdatum;Kunde;Leistung;Brutto;Fällig am;Bezahlt am"]
        bank = ["Buchungstag;Verwendungszweck;Zahlungspartner;Betrag"]
        n = 0
        for i in range(14):
            d = start + timedelta(days=17 * i)
            pno, cust = f"P-{d.year}-{i + 1:03d}", ["Agentur Kai", "Hotel Möwe", "Café Linde", "Kanzlei Lotse"][i % 4]
            proj.append(f"{pno};{cust};Website {i + 1};{de(d)}")
            bills = [(d + timedelta(days=2), "Anzahlung"), (d + timedelta(days=50), "Schlussrechnung")]
            if i == 13:
                bills = [(d + timedelta(days=30 * k), f"Betreuung Monat {k + 1}") for k in range(4)]
            for when, what in bills:
                if when + timedelta(days=12) > TODAY:
                    continue
                n += 1
                no = f"RE-{when.year}-{n:04d}"
                paid = when + timedelta(days=12)
                inv.append(f"{no};{de(when)};{cust};{what} {pno};{eur(500.0 + n)};{de(when + timedelta(days=14))};{de(paid)}")
                bank.append(f"{de(paid)};{no};{cust};{eur(500.0 + n)}")
            bank.append(f"{de(d + timedelta(days=1))};Miete Büro;Immobilien Kuhn GbR;-{eur(1200.0)}")
        for name, rows in (("Projekte.csv", proj), ("Rechnungen.csv", inv), ("Konto.csv", bank)):
            (tmp / name).write_text("\n".join(rows) + "\n", encoding="utf-8")
        store = Store(tmp / "firma")
        ingest(store, [(n_, (tmp / n_).read_bytes()) for n_ in ("Projekte.csv", "Rechnungen.csv", "Konto.csv")], "T")
        regrow(store)
        rt = Runtime(store)
        rt.ensure()
        from physarum.process import value_chains
        chains = value_chains(rt.model, rt.records, rt.mentions, rt.ledger, TODAY)
        c = next((c for c in chains if rt.spec(c["type"])["name"] == "Projekt"), None)
        self.assertIsNotNone(c, [x["nodes"] for x in chains])
        self.assertEqual(c["nodes"][-2:], ["berechnet", "bezahlt"])
        seg = {(s["frm"], s["to"]): s for s in c["segments"]}
        self.assertAlmostEqual(seg[("berechnet", "bezahlt")]["median"], 12, delta=1)  # the money, not the work
        self.assertLess(seg[("berechnet", "bezahlt")]["n"], c["n"])               # the monthly one is left out


if __name__ == "__main__":
    unittest.main()
