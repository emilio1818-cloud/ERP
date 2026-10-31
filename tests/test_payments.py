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

    def test_the_record_page_follows_the_money(self):
        """Review 9: a part-paid invoice showed "bezahlt" as done and offered no reminder; a paid one offered it."""
        from starlette.testclient import TestClient
        from physarum.web.app import create_app
        c = TestClient(create_app(self.tmp / "firma"))
        part, paid = c.get(f"/r/{self.e(30)['rid']}").text, c.get(f"/r/{self.e(3)['rid']}").text
        self.assertEqual(self.e(30)["state"], "teilbezahlt")
        self.assertIn("Zahlungserinnerung", part)
        self.assertNotIn("Zahlungserinnerung", paid)

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


class Contracts(unittest.TestCase):
    """A cleaning firm: objects under contract, a customer with several of them, the account the customer list
    gives, a statement whose first money column is only filled on returns, money that names no invoice (the
    oldest first, § 366 BGB), an advice that holds one invoice back, a purpose cut off after 140 characters."""

    @classmethod
    def setUpClass(cls):
        cls.tmp = Path(tempfile.mkdtemp(prefix="physarum-contract-"))
        custs = [("10001", "Kanzlei Lotse PartG", "DE89251933316843135158"), ("10002", "Hausverwaltung Kai GmbH", "DE53259400333432537529"),
                 ("10003", "Kirchengemeinde St. Anna", "DE94520604101809531276"), ("10004", "Praxis am Markt GbR", "DE22300606013064489528"),
                 ("10005", "Bistro Anker", "DE12259700740256736020")]
        kunden = ["Kundennr;Firma;IBAN;Zahlungsart"] + [f"{k};{n};{i};Überweisung" for k, n, i in custs]
        objekte = ["Obj.-Nr.;Kd.-Nr.;Objekt;Pauschale"]
        objs = {"10001": ["OB-101"], "10002": ["OB-102", "OB-103", "OB-104"], "10003": ["OB-105"], "10004": ["OB-106"],
                "10005": ["OB-107"]}
        price = {"OB-101": 357.0, "OB-102": 809.2, "OB-103": 618.8, "OB-104": 285.6, "OB-105": 487.9, "OB-106": 547.4,
                 "OB-107": 214.2}
        for k, os in objs.items():
            objekte += [f"{o};{k};Objekt {o};{eur(price[o] / 1.19)}" for o in os]
        book = ["Re.-Nr.;Datum;Kd.-Nr.;Obj.-Nr.;Kunde;Zahlart;Brutto;fällig am"]
        bank = ["Buchungstag;Verwendungszweck;Lastschrift Ursprungsbetrag;Beguenstigter/Zahlungspflichtiger;Kontonummer/IBAN;Betrag"]
        name, iban = {k: n for k, n, _ in custs}, {k: i for k, _, i in custs}
        cls.no, n = {}, 0
        months = [TODAY.replace(day=1) - timedelta(days=31 * m) for m in (5, 4, 3, 2, 1)]
        for m in months:
            day = (m.replace(day=28) + timedelta(days=4)).replace(day=1) - timedelta(days=1)  # the last of the month
            for k, os in objs.items():
                for o in os:
                    n += 1
                    no = f"2026-{n:04d}"
                    cls.no[(o, m.month)] = no
                    book.append(f"{no};{de(day)};{k};{o};{name[k]};Überweisung;{eur(price[o])};{de(day + timedelta(days=14))}")
        cls.months = [m.month for m in months]
        first, second, third, fourth, last = cls.months
        pay = lambda d, text, k, amount: bank.append(f"{de(d)};{text};;{name[k].upper()};{iban[k]};{eur(amount)}")  # noqa: E731
        later = lambda mon, days: [m for m in months if m.month == mon][0] + timedelta(days=31 + days)  # noqa: E731
        for mon in cls.months[:-1]:  # the manager pays its three objects with numbers – but in August the purpose is cut off
            nos = [cls.no[(o, mon)] for o in objs["10002"]]
            text = "Sammelzahlung " + " ".join(f"Wohnanlage Objekt Nummer {o} RE {x}," for o, x in zip(objs["10002"], nos))
            pay(later(mon, 9), text[:140] if mon == third else text, "10002", sum(price[o] for o in objs["10002"]))
        # the last month: an advice names all three, holds one back, the transfer is for two
        nos = [cls.no[(o, last)] for o in objs["10002"]]
        cls.advice = (nos[0], nos[1], nos[2])
        pay(later(last, 9), "Zahlungsavis 3 Belege", "10002", price["OB-102"] + price["OB-103"])
        # the parish pays a quarter at once, naming nothing
        pay(later(third, 12), "Reinigung Gemeindehaus", "10003", 3 * price["OB-105"])
        # the law firm's two oldest invoices are alike; one transfer of that amount, no number
        pay(later(first, 20), "Danke", "10001", price["OB-101"])
        for mon in cls.months:  # the practice and the bistro pay with numbers
            pay(later(mon, 5), f"RE {cls.no[('OB-106', mon)]}", "10004", price["OB-106"])
            pay(later(mon, 6), f"Rechnung {cls.no[('OB-107', mon)]}", "10005", price["OB-107"])
        # the bistro's debit came back once: only that line fills the first money column
        bank.append(f"{de(later(second, 8))};RUECKLASTSCHRIFT RE {cls.no[('OB-107', second)]};{eur(price['OB-107'])};"
                    f"BISTRO ANKER;{iban['10005']};-{eur(price['OB-107'])}")
        mail = (f"From: Buchhaltung <buchhaltung@hv-kai.example>\nTo: info@reinigung.example\nSubject: Zahlungsavis\n"
                f"Date: {later(last, 9).strftime('%a, %d %b %Y')} 09:00:00 +0200\nContent-Type: text/plain; charset=utf-8\n\n"
                f"mit Valuta heute haben wir beglichen:\n  {nos[0]}   {eur(price['OB-102'])} €\n  {nos[1]}   {eur(price['OB-103'])} €\n"
                f"Die Rechnung {nos[2]} behalten wir wegen der Reklamation ein.\n")
        files = {"Kunden_Export.csv": kunden, "Objektliste.csv": objekte, "Rechnungsausgangsbuch.csv": book,
                 "Sparkasse_Umsaetze.csv": bank}
        for f, rows in files.items():
            (cls.tmp / f).write_text("\n".join(rows) + "\n", encoding="utf-8")
        (cls.tmp / "Zahlungsavis.eml").write_text(mail, encoding="utf-8")
        cls.store = Store(cls.tmp / "firma")
        ingest(cls.store, [(f, (cls.tmp / f).read_bytes()) for f in list(files) + ["Zahlungsavis.eml"]], "T")
        regrow(cls.store)
        cls.rt = Runtime(cls.store)
        cls.rt.ensure()
        cls.spec = next(t for t in cls.rt.model["types"] if t["name"] == "Rechnung")
        cls.state = {r["data"][cls.spec["key"]]: cls.rt.ledger[r["id"]] for r in cls.rt.records[cls.spec["id"]]}

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def states(self, obj, months=None):
        return [self.state[self.no[(obj, m)]]["state"] for m in (months or self.months)]

    def test_the_invoice_names_its_customer_by_number(self):
        party = next(a for a in self.spec["attrs"] if a["kind"] == "ref" and
                     next(t for t in self.rt.model["types"] if t["id"] == a["ref"])["name"] == "Kunde")
        kunde = next(t for t in self.rt.model["types"] if t["name"] == "Kunde")
        self.assertEqual(party["orig_name"] if party.get("orig_name") else party["name"], "Kd.-Nr.")
        self.assertFalse([a for a in kunde["attrs"] if a.get("orig_name") == "Obj.-Nr."])  # an object is no customer field
        names = {self.rt.title(r["data"][party["id"]]) for r in self.rt.records[self.spec["id"]]}
        self.assertIn("Hausverwaltung Kai GmbH", names)

    def test_the_amount_of_a_statement_line_is_the_column_filled_on_every_line(self):
        self.assertEqual(self.states("OB-106"), ["bezahlt"] * 5)
        second = self.months[1]
        self.assertEqual(self.state[self.no[("OB-107", second)]]["state"], "offen")  # the returned debit

    def test_money_that_names_nothing_pays_the_oldest_first(self):
        first, second = self.months[:2]
        self.assertEqual(self.states("OB-101", [first, second]), ["bezahlt", "offen"])
        self.assertEqual(self.states("OB-105", self.months[:3]), ["bezahlt"] * 3)  # a quarter at once
        self.assertEqual(self.states("OB-105", self.months[3:]), ["offen"] * 2)

    def test_a_cut_off_purpose_still_pays_all_three(self):
        third = self.months[2]
        self.assertEqual([self.state[self.no[(o, third)]]["state"] for o in ("OB-102", "OB-103", "OB-104")],
                         ["bezahlt"] * 3)

    def test_the_advice_says_which_and_holds_one_back(self):
        a, b, held = self.advice
        self.assertEqual([self.state[x]["state"] for x in (a, b, held)], ["bezahlt", "bezahlt", "offen"])
        self.assertFalse(self.state[a]["notes"])  # paid in full, no skonto guessed


def _iban(blz: str, konto: int) -> str:
    bban = f"{blz}{konto:010d}"
    return f"DE{98 - int(bban + '131400') % 97:02d}{bban}"


class DownPayments(unittest.TestCase):
    """Special jobs: an offer, the order that takes it up and names its invoice, the invoice written after the job.
    The customer pays a deposit naming the offer before there is an invoice, and the rest naming the invoice.
    One deposit has no invoice yet; one invoice was paid twice and the surplus refunded; a direct-debit customer
    changes banks in a newer customer list."""

    @classmethod
    def setUpClass(cls):
        import time
        cls.tmp = Path(tempfile.mkdtemp(prefix="physarum-down-"))
        custs = [(f"100{20 + i}", n, _iban("25050180", 4711 + i)) for i, n in enumerate(
            ["Kinderarztpraxis Dr. Behrens", "Möbelhaus Sievers KG", "Autohaus Wendt GmbH", "Pension Domblick"])]
        kunden = ["Kd.-Nr.;Firma;IBAN;Zahlungsart"] + [f"{k};{n};{i};{'Lastschrift' if k == '10023' else 'Überweisung'}"
                                                         for k, n, i in custs]
        offers = ["Angebot;Datum;Interessent / Kunde;Leistung;Preis netto;Status"]
        orders = ["Auftrag;Eingang;Kd.-Nr.;Leistung;Angebot;Re.-Nr.;Preis netto;erledigt am"]
        book = ["Re.-Nr.;Datum;Kd.-Nr.;Leistung;Netto;USt;Brutto;fällig am"]
        bank = ["Buchungstag;Verwendungszweck;Beguenstigter/Zahlungspflichtiger;Kontonummer/IBAN;Betrag"]
        start = TODAY - timedelta(days=150)
        cls.inv = {}
        for i in range(12):
            k, name, iban = custs[i % 4]
            d = start + timedelta(days=11 * i)
            offer, order = f"A-26-{i + 1:03d}", f"SA-26-{i + 1:03d}"
            net = 2900.0 if i == 10 else 400.0 + 35 * i
            gross = round(net * 1.19, 2)
            done = d + timedelta(days=12)
            no = f"2026-{i + 1:04d}" if i < 11 else ""
            offers.append(f"{offer};{de(d - timedelta(days=5))};{name};Sonderreinigung {i + 1};{eur(net)};angenommen")
            orders.append(f"{order};{de(d)};{k};Sonderreinigung {i + 1};{offer};{no};{eur(net)};{de(done)}")
            if no:
                inv_day = done + timedelta(days=2)
                book.append(f"{no};{de(inv_day)};{k};Sonderreinigung {i + 1} lt. Auftrag {order};{eur(net)};"
                            f"{eur(gross - net)};{eur(gross)};{de(inv_day + timedelta(days=14))}")
                cls.inv[i] = (no, gross)
                if i == 10:  # the deposit before the job, naming the offer; the rest naming the invoice
                    bank.append(f"{de(d + timedelta(days=3))};Anzahlung Bauendreinigung Angebot {offer} Dr. Behrens;"
                                f"{name.upper()};{iban};{eur(1500.0)}")
                    bank.append(f"{de(inv_day + timedelta(days=9))};RE {no} Restbetrag;{name.upper()};{iban};"
                                f"{eur(gross - 1500.0)}")
                elif inv_day + timedelta(days=8) < TODAY:  # the guesthouse by direct debit, the others by transfer
                    debit = f"SEPA-BASISLASTSCHRIFT CRED DE98ZZZ09999999999 MREF M-{k} " if k == "10023" else ""
                    bank.append(f"{de(inv_day + timedelta(days=8))};{debit}RE {no};{name.upper()};{iban};{eur(gross)}")
                    if i == 4:  # paid twice, the second given back
                        bank.append(f"{de(inv_day + timedelta(days=9))};RE {no};{name.upper()};{iban};{eur(gross)}")
                        bank.append(f"{de(inv_day + timedelta(days=20))};Rueckerstattung Doppelzahlung RE {no};"
                                    f"{name.upper()};{iban};-{eur(gross)}")
            else:  # a deposit for a job nobody has invoiced yet
                cls.waiting = offer
                bank.append(f"{de(TODAY - timedelta(days=4))};Anzahlung {offer};{name.upper()};{iban};{eur(800.0)}")
        files = {"Kunden_Export.csv": kunden, "Angebote_2026.csv": offers, "Sonderauftraege_2026.csv": orders,
                 "Rechnungsausgangsbuch_2026.csv": book, "Sparkasse_Umsaetze_2026.csv": bank}
        for f, rows in files.items():
            (cls.tmp / f).write_text("\n".join(rows) + "\n", encoding="utf-8")
        cls.store = Store(cls.tmp / "firma")
        ingest(cls.store, [(f, (cls.tmp / f).read_bytes()) for f in files], "T")
        regrow(cls.store)
        time.sleep(1)  # the newer customer list: the direct-debit customer's new account
        newer = [r.replace(custs[3][2], _iban("25190088", 993311)) for r in kunden]
        ingest(cls.store, [("Kunden_Export_neu.csv", ("\n".join(newer) + "\n").encode("utf-8"))], "T")
        regrow(cls.store)
        cls.rt = Runtime(cls.store)
        cls.rt.ensure()
        cls.spec = next(t for t in cls.rt.model["types"] if t["name"] == "Rechnung")
        cls.state = {r["data"][cls.spec["key"]]: cls.rt.ledger[r["id"]] for r in cls.rt.records[cls.spec["id"]]}

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def test_a_deposit_naming_the_offer_pays_the_invoice_written_later(self):
        no, gross = self.inv[10]
        e = self.state[no]
        self.assertEqual(e["state"], "bezahlt", e)
        self.assertTrue(any(x["how"].startswith("Anzahlung zu Angebot A-26-011") for x in e["payments"]), e["payments"])
        receipts = [x for g in self.rt.work() if g["kind"] == "receipt" for x in g["items"]]
        self.assertEqual([x["money"] for x in receipts], [800.0])                     # only the one without an invoice
        self.assertIn(f"Anzahlung zu {self.waiting}", receipts[0]["reason"])

    def test_a_double_payment_given_back_is_paid(self):
        no, _ = self.inv[4]
        self.assertEqual(self.state[no]["state"], "bezahlt", self.state[no])

    def test_a_customer_changing_banks_is_no_fraud(self):
        risk = next((g for g in self.rt.work() if g["id"] == "risk:iban"), None)
        self.assertIsNone(risk, risk and risk["items"])


class DepositOnOrder(unittest.TestCase):
    """A craft business: every other customer pays 30 % right after ordering, naming the order; the invoice names
    the order and the rest names the invoice. A billed order is no claim of its own – its invoice is."""

    @classmethod
    def setUpClass(cls):
        cls.tmp = Path(tempfile.mkdtemp(prefix="physarum-deposit-"))
        names = ["Müller, Hans", "Schulz, Petra", "Becker, Tom", "Wagner, Eva", "Koch, Lisa", "Wolf, Ben"]
        orders = ["Auftrag;Datum;Kunde;Leistung;Auftragssumme;fertig am"]
        inv = ["Rechnungsnr;Rechnungsdatum;Auftrag;Kunde;Brutto;Fällig am"]
        bank = ["Buchungstag;Auftraggeber;Verwendungszweck;Betrag"]
        start = TODAY - timedelta(days=170)
        cls.inv = {}
        for i in range(24):
            d = start + timedelta(days=6 * i)
            order, cust, total = f"A26-{100 + i:03d}", names[i % 6], round(2000 + 150 * i, 2)
            done = d + timedelta(days=14)
            payer = " ".join(reversed(cust.split(", ")))
            orders.append(f"{order};{de(d)};{cust};Bad;{eur(total)};{de(done)}")
            if i % 2 == 0:
                bank.append(f"{de(d + timedelta(days=2))};{payer};Anzahlung {order};{eur(round(total * 0.3, 2))}")
            no = f"RE-2026-{i + 1:04d}"
            inv.append(f"{no};{de(done)};{order};{cust};{eur(total)};{de(done + timedelta(days=14))}")
            cls.inv[i] = no
            if done + timedelta(days=10) < TODAY:
                rest = total * 0.7 if i % 2 == 0 else total
                bank.append(f"{de(done + timedelta(days=10))};{payer};{no};{eur(round(rest, 2))}")
            bank.append(f"{de(d + timedelta(days=1))};Großhandel Nord;Material;-{eur(800.0)}")
        files = {"Auftragsbuch.csv": orders, "Rechnungsbuch.csv": inv, "Konto.csv": bank}
        for f, rows in files.items():
            (cls.tmp / f).write_text("\n".join(rows) + "\n", encoding="utf-8")
        cls.store = Store(cls.tmp / "firma")
        ingest(cls.store, [(f, (cls.tmp / f).read_bytes()) for f in files], "T")
        regrow(cls.store)
        cls.rt = Runtime(cls.store)
        cls.rt.ensure()
        cls.spec = next(t for t in cls.rt.model["types"] if t["name"] == "Rechnung")
        cls.state = {r["data"][cls.spec["key"]]: cls.rt.ledger[r["id"]] for r in cls.rt.records[cls.spec["id"]]}

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def test_deposit_and_rest_pay_the_invoice(self):
        paid = [i for i in range(0, 20, 2) if self.state[self.inv[i]]["state"] == "bezahlt"]
        self.assertEqual(paid, list(range(0, 20, 2)), {self.inv[i]: self.state[self.inv[i]]["notes"] for i in range(0, 20, 2)})
        overdue = [x["title"] for g in self.rt.work() if g["kind"] == "overdue" for x in g["items"]]
        self.assertEqual(overdue, [])

    def test_a_billed_order_is_no_claim_of_its_own(self):
        types = {self.rt.by_id[rid]["type"] for rid in self.rt.ledger}
        self.assertEqual(types, {self.spec["id"]})


class ByHandAndLater(unittest.TestCase):
    """Review 9: what the owner enters by hand and what a later delivery says agree – a transfer entered before
    the statement came counts once, a double payment paid back is settled, an undone click leaves the field
    to its file, and a learned date offset does not move a date that was set."""

    def test_by_hand_then_the_next_delivery(self):
        from physarum import ops
        from tests.test_unseen_firm import Firm
        f = Firm()
        self.addCleanup(f.close)
        start, rows, bank, later = TODAY - timedelta(days=150), [], ["Buchungstag;Verwendungszweck;Zahlungspartner;Betrag"], []
        for i in range(24):
            d, g, no = start + timedelta(days=5 * i), round(300 + 17.5 * i, 2), f"RE-{i + 1:04d}"
            paid = d + timedelta(days=9)
            rows.append([no, de(d), f"Kunde {i % 4}", eur(g), de(d + timedelta(days=14)), de(paid) if i < 21 else ""])
            if i != 21 and i != 23:
                bank.append(f"{de(paid)};{no};Kunde {i % 4};{eur(g)}")
            if i == 22:
                bank.append(f"{de(d + timedelta(days=11))};{no};Kunde {i % 4};{eur(g)}")      # paid twice
            if i == 21:
                later.append(f"{de(paid)};{no};Kunde {i % 4};{eur(g)}")                         # the transfer, late seen
            if i == 22:
                later.append(f"{de(TODAY - timedelta(days=2))};Erstattung {no};Kunde {i % 4};-{eur(g)}")

        def book(rs):
            return "\n".join(["Rechnungsnr;Rechnungsdatum;Kunde;Brutto;Fällig am;Bezahlt am"] + [";".join(r) for r in rs]) + "\n"
        f.feed([("Rechnungen.csv", book(rows)), ("Konto.csv", "\n".join(bank) + "\n")])
        rt = f.rt()
        spec = next(t for t in rt.model["types"] if t["name"] == "Rechnung")
        rid = {r["data"][spec["key"]]: r["id"] for r in rt.records[spec["id"]]}
        attr = {a["name"]: a["id"] for a in spec["attrs"]}
        due, day, paid_on = attr["Fällig am"], attr["Rechnungsdatum"], attr["Bezahlt am"]
        self.assertTrue(any(x["op"] == "date_add" and x["attr"] == due for x in spec.get("formulas") or []))
        data = dict(rt.by_id[rid["RE-0024"]]["data"], **{day: TODAY.isoformat()})
        ops.apply_formulas(rt, spec, data, {day})                                              # a set date stays,
        self.assertEqual(data[due], rt.by_id[rid["RE-0024"]]["data"][due])
        data = {day: TODAY.isoformat()}
        ops.apply_formulas(rt, spec, data, {day})                                              # an empty one is filled
        self.assertEqual(data[due], (TODAY + timedelta(days=14)).isoformat())
        self.assertEqual(rt.ledger[rid["RE-0023"]]["state"], "überzahlt")
        g22, g23 = rt.ledger[rid["RE-0022"]]["gross"], rt.ledger[rid["RE-0023"]]["gross"]
        ops.record_payment(rt, rid["RE-0022"], g22, TODAY.isoformat(), "ueberweisung", "T")   # the customer says so
        ops.record_payment(rt, rid["RE-0023"], g23, TODAY.isoformat(), "erstattung", "T")     # paid back
        rt = f.rt()
        self.assertEqual([rt.ledger[rid[k]]["state"] for k in ("RE-0022", "RE-0023")], ["bezahlt", "bezahlt"])
        changed = ops.set_step(rt, rid["RE-0024"], paid_on, None, "T")                         # clicked by mistake
        ops.revert(f.rt(), rid["RE-0024"], changed, "T")                                       # and taken back
        rows[23][5] = de(TODAY - timedelta(days=3))                                            # the book has it later
        f.feed([(f"Rechnungen Stand {de(TODAY - timedelta(days=1))}.csv", book(rows)),
                ("Konto November.csv", "\n".join([bank[0]] + later) + "\n")])
        rt = f.rt()
        e22, e23 = rt.ledger[rid["RE-0022"]], rt.ledger[rid["RE-0023"]]
        self.assertEqual((e22["state"], e22["paid"]), ("bezahlt", g22))                       # once, not twice
        self.assertIn("bestätigt Ihre Eintragung", " ".join(x["how"] for x in e22["payments"]))
        self.assertEqual((e23["state"], e23["open"]), ("bezahlt", 0.0))
        self.assertEqual(rt.by_id[rid["RE-0024"]]["data"][paid_on], (TODAY - timedelta(days=3)).isoformat())
