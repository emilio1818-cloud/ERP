"""Review 10 – an adversarial reading of round 9: what its new code did wrong, each case as a test (the
reviewer's reproductions, kept here with the behaviour they ask for)."""
import unittest
from datetime import date, timedelta
from email.message import EmailMessage
from pathlib import Path
from unittest import mock

from physarum import billing, dunning, ops, process
from tests.test_contracts import _camt
from tests.test_unseen_firm import Firm, _type, csv

TODAY = date.today()


def de(d: date) -> str:
    return d.strftime("%d.%m.%Y")


def eur(x: float) -> str:
    return f"{x:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def book_firm(f: Firm, n=24, paid=lambda i: True, special=None, extra_bank=(), step=7, start_days=200):
    """An invoice book and its statement: RE-0001 … weekly, paid nine days later by number."""
    start = TODAY - timedelta(days=start_days)
    rows, bank = [], ["Buchungstag;Verwendungszweck;Zahlungspartner;Betrag"]
    for i in range(n):
        d, g, no = start + timedelta(days=step * i), round(300 + 17.5 * i, 2), f"RE-{i + 1:04d}"
        g = (special or {}).get(i, g)
        rows.append([no, de(d), f"Kunde {i % 4}", eur(g), de(d + timedelta(days=14))])
        if paid(i):
            bank.append(f"{de(d + timedelta(days=9))};{no};Kunde {i % 4};{eur(g)}")
    bank += list(extra_bank)
    book = "\n".join(["Rechnungsnr;Rechnungsdatum;Kunde;Brutto;Fällig am"] + [";".join(r) for r in rows]) + "\n"
    f.feed([("Rechnungen.csv", book), ("Konto.csv", "\n".join(bank) + "\n")])
    return bank


def invoice(rt, no):
    spec = next(t for t in rt.model["types"] if t["name"] == "Rechnung")
    return spec, next(r["id"] for r in rt.records[spec["id"]] if r["data"][spec["key"]] == no)


class PaidByHand(unittest.TestCase):
    def setUp(self):
        self.f = Firm()
        self.addCleanup(self.f.close)

    def test_the_second_installment_entered_by_hand_is_not_the_first_one_on_the_statement(self):
        first = TODAY - timedelta(days=200) + timedelta(days=7 * 5 + 20)
        book_firm(self.f, paid=lambda i: i != 5, special={5: 1000.0}, extra_bank=[f"{de(first)};RE-0006 1. Rate;Kunde 1;{eur(500)}"])
        rt = self.f.rt()
        _, rid = invoice(rt, "RE-0006")
        self.assertEqual((rt.ledger[rid]["state"], rt.ledger[rid]["paid"]), ("teilbezahlt", 500.0))
        ops.record_payment(rt, rid, 500.0, TODAY.isoformat(), "ueberweisung", "T")   # the 2nd rate, by hand
        e = self.f.rt().ledger[rid]
        self.assertEqual((e["state"], e["paid"]), ("bezahlt", 1000.0))   # the old line does not swallow it

    def test_a_transfer_entered_by_hand_counts_once_when_the_statement_shows_it_without_a_number(self):
        bank = book_firm(self.f, paid=lambda i: i < 22)
        rt = self.f.rt()
        _, rid = invoice(rt, "RE-0023")
        g = rt.ledger[rid]["gross"]
        ops.record_payment(rt, rid, g, (TODAY - timedelta(days=3)).isoformat(), "ueberweisung", "T")
        self.f.feed([("Konto Neu.csv", "\n".join([bank[0], f"{de(TODAY - timedelta(days=2))};Zahlung;Kunde 2;{eur(g)}"]) + "\n")])
        rt = self.f.rt()
        e = rt.ledger[rid]
        receipts = [x for gg in rt.work(TODAY) if gg["kind"] == "receipt" for x in gg["items"]]
        self.assertEqual((e["state"], e["paid"]), ("bezahlt", g))
        self.assertIn("bestätigt Ihre Eintragung", " ".join(x["how"] for x in e["payments"]))
        self.assertFalse(any(abs((x.get("money") or 0) - g) < 0.01 for x in receipts))   # not money for nothing

    def test_a_refund_needs_money_paid_twice(self):
        book_firm(self.f, step=5, start_days=150, paid=lambda i: i < 20)
        rt = self.f.rt()
        _, rid = invoice(rt, "RE-0024")
        with self.assertRaises(ops.OpError):
            ops.record_payment(rt, rid, rt.ledger[rid]["gross"], TODAY.isoformat(), "erstattung", "T")
        self.assertEqual(self.f.rt().ledger[rid]["state"], "offen")

    def test_a_computed_due_date_follows_its_invoice_date(self):
        book_firm(self.f, step=5, start_days=150)
        rt = self.f.rt()
        spec = next(t for t in rt.model["types"] if t["name"] == "Rechnung")
        attr = {a["name"]: a["id"] for a in spec["attrs"]}
        rid = ops.create(rt, spec["id"], {attr["Rechnungsnr"]: "RE-9001", attr["Rechnungsdatum"]: de(TODAY),
                                          attr["Brutto"]: "100,00"}, "T")
        ops.update(self.f.rt(), rid, {attr["Rechnungsdatum"]: de(TODAY + timedelta(days=10))}, "T")
        self.assertEqual(self.f.rt().by_id[rid]["data"].get(attr["Fällig am"]), (TODAY + timedelta(days=24)).isoformat())

    def test_undo_gives_the_field_to_the_newest_file(self):
        kunden = [[f"K-{i:03d}", f"Kunde {i} GmbH", f"Weg {i}", "Hamburg"] for i in range(12)]
        self.f.feed([("Kunden.csv", "\n".join(["Kd-Nr;Name;Straße;Ort"] + [";".join(r) for r in kunden]) + "\n")])
        rt = self.f.rt()
        spec = next(t for t in rt.model["types"] if t["kind"] == "master")
        ort = next(a["id"] for a in spec["attrs"] if a["name"] == "Ort")
        rid = next(r["id"] for r in rt.records[spec["id"]] if r["data"][spec["key"]] == "K-003")
        ops.update(rt, rid, {ort: "Bremen"}, "T")
        kunden[3][3] = "Kiel"
        self.f.feed([("Kunden Stand neu.csv", "\n".join(["Kd-Nr;Name;Straße;Ort"] + [";".join(r) for r in kunden]) + "\n")])
        ops.revert(self.f.rt(), rid, [ort], "T")
        rec = self.f.rt().by_id[rid]
        self.assertEqual(rec["data"][ort], "Kiel")                          # not "Hamburg" of the replaced list
        self.assertEqual((rec["meta"].get("w") or {}).get(ort, [""])[0], "import")


COMPANY = dict(name="Glanz Gebäudedienste GmbH", street="Hauptstr. 1", zip="31134", city="Hildesheim",
               vat_id="DE123456789", iban="DE02120300000000202051", email="info@glanz.example", phone="05121 1234")
CONTRACTS = [["V-01", "Kunde 1", "01.03.2024", ""], ["V-02", "Kunde 2", "01.05.2023", ""],
             ["V-03", "Kunde 3", "01.01.2025", ""], ["V-04", "Kunde 4", "01.09.2022", ""],
             ["V-05", "Kunde 5", "01.07.2026", ""], ["V-06", "Kunde 6", "01.02.2021", "31.08.2026"],
             ["V-07", "Kunde 7", "01.10.2025", ""], ["V-08", "Kunde 8", "01.11.2024", ""]]


def contract_firm(f: Firm, contracts=None, months=None, status=None, extra_invoices=(), extra_contracts=()):
    """The cleaning contracts of tests/test_contracts.py, billed month by month."""
    contracts = (contracts or CONTRACTS) + list(extra_contracts)
    months = months if months is not None else {"V-02": set(range(1, 10)) - {6}, "V-04": set(range(1, 8)),
                                                "V-05": {8, 9}, "V-06": set(range(1, 9))}
    today = date(2026, 10, 20)
    rows, bank, n = [], [], 0
    for v, cust, *_ in contracts:
        for m in sorted(months.get(v, set(range(1, 10)))):
            n += 1
            day = date.fromordinal(date(2026, m + 1, 1).toordinal() - 1)
            rows.append([f"RE-2026-{n:04d}", day.strftime("%d.%m.%Y"), cust, v, f"{m:02d}/2026", f"{595 + 7 * int(v[-1])},00"])
    for i in range(8):
        n += 1
        rows.append([f"RE-2026-{n:04d}", f"{10 + i:02d}.0{i + 1}.2026", f"Kunde {i % 8 + 1}", "", "", f"{180 + 15 * i},00"])
    rows += list(extra_invoices)
    for r in rows:
        paid = date(int(r[1][6:]), int(r[1][3:5]), int(r[1][:2])).toordinal() + 10
        if paid < today.toordinal():
            bank.append([date.fromordinal(paid).strftime("%d.%m.%Y"), f"Rechnung {r[0]}", r[2], r[5]])
    head = "Vertrag;Kunde;Beginn;Vertragsende" + (";Status" if status else "")
    crow = [c + ([status.get(c[0], "aktiv")] if status else []) for c in contracts]
    f.feed([("Kunden.csv", csv("Kd.-Nr.;Name;Straße;PLZ;Ort", [[f"K{i}", f"Kunde {i}", f"Marktplatz {i}", "31134", "Hildesheim"]
                                                             for i in range(1, 9)])),
            ("Vertraege.csv", csv(head, crow)),
            ("Rechnungen.csv", csv("Rechnungsnr;Datum;Kunde;Vertrag;Zeitraum;Brutto", rows)),
            ("Konto.csv", csv("Buchungstag;Verwendungszweck;Zahlungspartner;Betrag", bank))])
    return today


def periods(rt, today):
    g = next((g for g in rt.work(today) if g["id"].endswith(":periods")), None)
    return {x["title"]: x["reason"] for x in g["items"]} if g else {}


class ContractPeriods(unittest.TestCase):
    def setUp(self):
        self.f = Firm()
        self.addCleanup(self.f.close)

    def test_the_month_billed_here_is_billed(self):
        today = contract_firm(self.f)
        self.f.store.kv_set("company_profile", COMPANY)
        rt = self.f.rt()
        self.assertEqual(periods(rt, today)["V-02"], "06/2026 ohne Rechnung")
        g = next(g for g in rt.work(today) if g["id"].endswith(":periods"))
        inv = rt.spec(g["action"]["type"])
        v02 = next(x["rid"] for x in g["items"] if x["title"] == "V-02")
        attrs = {a["name"]: a["id"] for a in inv["attrs"]}
        rid = ops.create(rt, inv["id"], {g["action"]["attr"]: str(v02), attrs["Brutto"]: "609,00"}, "T")
        billing.set_positions(self.f.rt(), rid, [dict(text="Unterhaltsreinigung Juni 2026", qty=1, price=511.76, rate=0.19)], "T")
        with mock.patch.object(billing, "issue_problems", lambda *a, **k: []):  # the customer sits behind the contract
            billing.issue(self.f.rt(), rid, "T", today=today, delivery="2026-06-01", delivery_end="2026-06-30",
                          here_ok=True, extra_ok=True)
        self.assertNotIn("V-02", periods(self.f.rt(), today))          # the period of the issue dialog counts

    def test_a_contract_whose_own_end_is_ahead_has_not_ended(self):
        contracts = [c if c[0] != "V-03" else ["V-03", "Kunde 3", "01.01.2025", "31.12.2027"] for c in CONTRACTS]
        months = {"V-02": set(range(1, 10)) - {6}, "V-03": set(range(1, 8)), "V-06": set(range(1, 9))}
        today = contract_firm(self.f, contracts, months)
        self.assertIn("V-03", periods(self.f.rt(), today))             # August and September: forgotten, not over

    def test_a_cancelled_contract_is_not_asked_for(self):
        contract_firm(self.f, status={"V-04": "gekündigt", "V-06": "gekündigt"})
        self.assertNotIn("V-04", periods(self.f.rt(), date(2026, 9, 20)))

    def test_a_period_in_the_year_9999_does_not_take_heute_down(self):
        today = contract_firm(self.f, extra_invoices=[["RE-2026-9999", "28.03.2026", "Kunde 8", "V-09", "01.12.9999–31.12.9999",
                                                       "500,00"]], extra_contracts=[["V-09", "Kunde 8", "", ""]])
        self.f.rt().work(today)

    def test_leading_zeros_survive_a_form_error(self):
        import re
        from starlette.testclient import TestClient
        from physarum.web.app import create_app
        contract_firm(self.f)
        spec = next(t for t in self.f.rt().model["types"] if t["name"] == "Rechnung")
        a = {x["name"]: x["id"] for x in spec["attrs"]}
        r = TestClient(create_app(self.f.dir / "firma")).post(
            f"/t/{spec['id']}/neu", data={f"a_{a['Rechnungsnr']}": "0042", f"a_{a['Zeitraum']}": "0007",
                                          f"a_{a['Datum']}": "kein Datum"}, headers={"origin": "http://testserver"})
        self.assertEqual(re.search(r'name="a_%s"[^>]*value="([^"]*)"' % a["Zeitraum"], r.text).group(1), "0007")


def mail(sender, subject, body, when):
    m = EmailMessage()
    m["From"], m["To"], m["Subject"] = sender, "buero@muster.example", subject
    m["Date"] = when.strftime("%a, %d %b %Y 10:00:00 +0200")
    m.set_content(body)
    return bytes(m)


class AnnouncedAccount(unittest.TestCase):
    def firm(self, body):
        f = Firm()
        self.addCleanup(f.close)
        sup = [["L-1", "Brotzeit Großhandel GmbH", "buchhaltung@brotzeit-gh.de", "DE89370400440532013000"],
               ["L-2", "Getränke Huber KG", "info@getraenke-huber.de", "DE02120300000000202051"],
               ["L-3", "Wäscherei Blank", "info@waescherei-blank.de", "DE12500105170648489890"]]
        rows, bank, start = [], [], TODAY - timedelta(days=120)
        for i in range(30):
            s, d = sup[i % 3], start + timedelta(days=4 * i)
            no, amount = f"{s[0]}-2026-{i + 1:03d}", 200 + 13 * i
            rows.append([no, de(d), s[1], f"{amount},00", de(d + timedelta(days=14))])
            if d + timedelta(days=14) < TODAY - timedelta(days=3):
                bank.append([de(d + timedelta(days=12)), f"Rechnung {no}", s[1], f"-{amount},00", s[3]])
        f.feed([("Lieferanten.csv", csv("Lieferant-Nr;Name;E-Mail;IBAN", sup)),
                ("Eingangsrechnungen.csv", csv("Rechnungsnr;Datum;Lieferant;Betrag;Fällig am", rows)),
                ("Konto.csv", csv("Buchungstag;Verwendungszweck;Zahlungspartner;Betrag;IBAN", bank)),
                ("neue_bank.eml", mail("Brotzeit Großhandel GmbH <buchhaltung@brotzeit-gh.de>", "Wichtig: neue Bankverbindung",
                                       body, TODAY - timedelta(days=2)))])
        rt = f.rt()
        inv = next(t for t in rt.model["types"] if t.get("incoming"))
        no = {r["id"]: r["data"].get(inv["key"]) for r in rt.records[inv["id"]]}
        risk = {no.get(x["rid"], x["title"]) for g in rt.work(TODAY) if g["kind"] == "risk" for x in g["items"]}
        open_l1 = {no[r] for r, e in rt.ledger.items() if r in no and str(no[r]).startswith("L-1")
                   and e["state"] in ("offen", "teilbezahlt")}
        return risk, open_l1

    def test_a_mail_without_number_holds_the_suppliers_open_invoices(self):
        risk, open_l1 = self.firm("Sehr geehrte Damen und Herren,\nbitte beachten Sie unsere neue Bankverbindung: "
                                  "LT12 1000 0111 0100 1000. Bitte überweisen Sie ab sofort nur noch dorthin.\nMfG")
        self.assertTrue(open_l1 and open_l1 <= risk)

    def test_a_mail_naming_a_paid_invoice_still_holds_the_open_ones(self):
        risk, open_l1 = self.firm("Sehr geehrte Damen und Herren,\nanbei die korrigierte Rechnung L-1-2026-001. Unsere neue "
                                  "Bankverbindung: LT12 1000 0111 0100 1000. Bitte nur noch dorthin überweisen.\nMfG")
        self.assertTrue(open_l1 and open_l1 <= risk)


class Reminders(unittest.TestCase):
    def complaint(self, who):
        f = Firm()
        self.addCleanup(f.close)
        cust = [[f"K{i:03d}", f"Kunde {i:03d} GmbH", f"buero@kunde{i:03d}.de"] for i in range(60)]
        rows, bank = [], []
        for i in range(120):  # the first 60 paid, the last 60 overdue
            c = i % 60
            d = TODAY - timedelta(days=400 - 3 * i) if i < 60 else TODAY - timedelta(days=200 - 2 * (i - 60))
            rows.append([f"RE-{i + 1:04d}", de(d), f"Kunde {c:03d} GmbH", f"{300 + i},00", de(d + timedelta(days=14))])
            if i < 60:
                bank.append([de(d + timedelta(days=10)), f"Rechnung RE-{i + 1:04d}", f"Kunde {c:03d} GmbH", f"{300 + i},00"])
        f.feed([("Kunden.csv", csv("Kd-Nr;Name;E-Mail", cust)),
                ("Rechnungen.csv", csv("Rechnungsnr;Rechnungsdatum;Kunde;Brutto;Fällig am", rows)),
                ("Konto.csv", csv("Buchungstag;Verwendungszweck;Zahlungspartner;Betrag", bank)),
                ("reklamation.eml", mail(f"Kunde {who} GmbH <buero@kunde{who}.de>", "Reklamation",
                                         f"Guten Tag,\nleider ist die Lieferung defekt angekommen. Bitte melden Sie sich.\n"
                                         f"Kunde {who} GmbH", TODAY - timedelta(days=3)))])
        rt = f.rt()
        inv = next(t for t in rt.model["types"] if t["name"] == "Rechnung")
        k = next(r["id"] for t in rt.model["types"] if t["kind"] == "master" for r in rt.records[t["id"]] if who in rt.title(r["id"]))
        letter = dunning.overdue_of(rt, k, inv["id"], TODAY)
        self.assertTrue(letter and all(x["complaint"] for x in letter))

    def test_a_complaint_holds_the_letter_of_the_most_overdue_customer(self):
        self.complaint("000")

    def test_a_complaint_holds_the_letter_beyond_the_fifty_shown(self):
        self.complaint("059")

    def test_after_the_first_reminder_comes_the_first_dunning(self):
        f = Firm()
        self.addCleanup(f.close)
        rows, bank = [], []
        for i in range(40):
            d = TODAY - timedelta(days=300 - 6 * i)
            status = "bezahlt" if i < 30 else ("Mahnung" if i in (30, 31) else "offen")
            rows.append([f"RE-{i + 1:04d}", de(d), f"Kunde {i % 5}", f"{400 + i},00", de(d + timedelta(days=14)), status])
            if i < 30:
                bank.append([de(d + timedelta(days=10)), f"Rechnung RE-{i + 1:04d}", f"Kunde {i % 5}", f"{400 + i},00"])
        f.feed([("Kunden.csv", csv("Kd-Nr;Name;Straße;PLZ;Ort", [[f"K{i}", f"Kunde {i}", f"Weg {i}", "20095", "Hamburg"]
                                                                 for i in range(5)])),
                ("Rechnungen.csv", csv("Rechnungsnr;Rechnungsdatum;Kunde;Brutto;Fällig am;Status", rows)),
                ("Konto.csv", csv("Buchungstag;Verwendungszweck;Zahlungspartner;Betrag", bank))])
        rt = f.rt()
        inv = next(t for t in rt.model["types"] if t["name"] == "Rechnung")
        party = next(p for p in rt.model["processes"] if p["type"] == inv["id"])["party"]
        rid = next(r["id"] for r in rt.records[inv["id"]] if r["data"][inv["key"]] == "RE-0039")
        who = rt.by_id[rid]["data"][party]
        self.assertEqual([x for x in dunning.overdue_of(rt, who, inv["id"], TODAY) if x["rid"] == rid][0]["level"], 1)
        dunning.record_sent(rt, who, inv["id"], "T", TODAY)   # writes the firm's word "Mahnung" into the status
        later = [x for x in dunning.overdue_of(f.rt(), who, inv["id"], TODAY + timedelta(days=11)) if x["rid"] == rid][0]
        self.assertEqual(later["level"], 2)                   # the 1. Mahnung, not the 2.


class Recount(unittest.TestCase):
    def test_a_large_group_loses_one_item_not_all_beyond_fifty(self):
        data = Path(__file__).parent / "fixtures" / "brenner" / "daten"
        f = Firm()
        self.addCleanup(f.close)
        f.feed([(str(p.relative_to(data)), p.read_bytes()) for p in sorted(data.rglob("*")) if p.is_file()])
        today = date(2026, 10, 29)
        big = next(g for g in f.rt().work(today) if g["kind"] in ("late", "ready") and g["count"] > 50)
        one = big["items"][0]
        fake = [dict(id="p_x:periods", type=big["type"], kind="ready", severity=2, title="Zeitraum ohne Rechnung", count=1,
                     amount=0.0, items=[dict(rid=one["rid"], title="x", days=1, money=0.0, period=True, reason="x")])]
        with mock.patch.object(process, "_period_work", lambda *a, **k: fake):
            g2 = next(g for g in f.rt().work(today) if g["id"] == big["id"])
        self.assertEqual(g2["count"], big["count"] - 1)
        self.assertAlmostEqual(g2["amount"] or 0, (big["amount"] or 0) - (one["money"] or 0), places=2)


class PropertyManager(unittest.TestCase):
    """The office of review 10's property manager: its fee comes from the object's account to its own, a service-charge
    statement can end in a credit, a month of fees is paid with one transfer naming a range."""

    def setUp(self):
        self.f = Firm()
        self.addCleanup(self.f.close)

    def test_a_transfer_between_two_accounts_of_the_dump_is_one_payment(self):
        own, obj = "DE89370400440532013000", "DE02120300000000202051"
        rows, mine, theirs = [], [], []
        for i in range(12):
            d, no, g = TODAY - timedelta(days=150 - 10 * i), f"RE-2026-{i + 1:04d}", f"{300 + 10 * i},00"
            rows.append([no, de(d), "WEG Rosenhof", g, de(d + timedelta(days=14))])
            purpose = f"Verwaltervergütung {no}"
            mine.append([de(d + timedelta(days=5)), purpose, "WEG Rosenhof", obj, g])          # arrives on the office's
            theirs.append([de(d + timedelta(days=6)), purpose, "Kerkhoff Hausverwaltung", own, "-" + g])  # leaves the WEG's
        head = "Buchungstag;Verwendungszweck;Zahlungspartner;IBAN;Betrag"
        self.f.feed([("Rechnungsausgang.csv", csv("Rechnungsnr;Datum;Kunde;Brutto;Fällig am", rows)),
                     ("Umsaetze_Geschaeftskonto.csv", csv(head, mine)), ("Umsaetze_WEG_Rosenhof.csv", csv(head, theirs))])
        rt = self.f.rt()
        inv = _type(rt, "Rechnung")
        states = {e["state"] for r, e in rt.ledger.items() if rt.by_id[r]["type"] == inv["id"]}
        self.assertEqual(states, {"bezahlt"})                       # not paid and charged back

    def test_a_credit_is_no_claim(self):
        rows, bank = [], []
        for i in range(10):
            d, no = TODAY - timedelta(days=200 - 10 * i), f"BK-2025-{i + 1:03d}"
            cost, pre = 1200 + 40 * i, (1300 if i % 3 == 0 else 1000)   # every third has paid more in advance
            rows.append([no, de(d), f"Mieter {i}", f"{cost},00", f"{pre},00", de(d + timedelta(days=30))])
            if cost > pre:
                bank.append([de(d + timedelta(days=20)), f"Nachzahlung {no}", f"Mieter {i}", f"{cost - pre},00"])
        self.f.feed([("BK-Abrechnung_2025.csv", csv("Abrechnung;Datum;Mieter;Kosten;Vorauszahlungen;Fällig am", rows)),
                     ("Konto.csv", csv("Buchungstag;Verwendungszweck;Zahlungspartner;Betrag", bank))])
        rt = self.f.rt()
        owed = {rt.by_id[r]["data"].get(rt.spec(rt.by_id[r]["type"])["key"]): e["open"] for r, e in rt.ledger.items()}
        self.assertEqual(owed["BK-2025-001"], 0.0)                 # 1300 paid in advance on costs of 1200
        self.assertFalse([k for k, v in owed.items() if v > 0.005])

    def test_one_transfer_for_a_range_of_invoices(self):
        rows, bank = [], []
        for i in range(12):
            d, no = TODAY - timedelta(days=120 - 7 * i), f"RE-2026-{i + 1:04d}"
            rows.append([no, de(d), "Eigentümer Albers", f"{200 + i},00", de(d + timedelta(days=14))])
        bank.append([de(TODAY - timedelta(days=5)), "Entnahme Verwaltervergütung RE-2026-0001 bis RE-2026-0012",
                     "Eigentümer Albers", f"{sum(200 + i for i in range(12))},00"])
        self.f.feed([("Rechnungsausgang.csv", csv("Rechnungsnr;Datum;Kunde;Brutto;Fällig am", rows)),
                     ("Konto.csv", csv("Buchungstag;Verwendungszweck;Zahlungspartner;Betrag", bank))])
        rt = self.f.rt()
        self.assertEqual({e["state"] for e in rt.ledger.values()}, {"bezahlt"})


class CamtStatements(unittest.TestCase):
    HEAD = ('<?xml version="1.0" encoding="UTF-8"?><Document xmlns="urn:iso:std:iso:20022:tech:xsd:camt.053.001.08">'
            '<BkToCstmrStmt><GrpHdr><MsgId>1</MsgId></GrpHdr>')
    TAIL = '</BkToCstmrStmt></Document>'

    @staticmethod
    def stmt(iban, entries):
        return (f'<Stmt><Id>{iban}</Id><Acct><Id><IBAN>{iban}</IBAN></Id><Ownr><Nm>Muster GmbH</Nm></Ownr></Acct>'
                f'<Bal><Tp><CdOrPrtry><Cd>CLBD</Cd></CdOrPrtry></Tp><Amt Ccy="EUR">1000.00</Amt><CdtDbtInd>CRDT</CdtDbtInd>'
                f'<Dt><Dt>2026-10-01</Dt></Dt></Bal>{"".join(entries)}</Stmt>')

    @staticmethod
    def entry(amount, ind, details="", extra=""):
        return (f'<Ntry><Amt Ccy="EUR">{amount}</Amt><CdtDbtInd>{ind}</CdtDbtInd>{extra}<Sts><Cd>BOOK</Cd></Sts>'
                f'<BookgDt><Dt>2026-10-01</Dt></BookgDt><ValDt><Dt>2026-10-01</Dt></ValDt>{details}</Ntry>')

    def read(self, *stmts):
        from physarum.ingest import Digest, _read_xml
        d = Digest()
        _read_xml("auszug", (self.HEAD + "".join(stmts) + self.TAIL).encode(), d)
        return d

    def test_a_batch_without_amounts_per_transaction_is_its_total_once(self):
        tx = "".join(f'<TxDtls><Refs><EndToEndId>RE-2026-00{i}</EndToEndId></Refs><RltdPties><Dbtr><Pty><Nm>Kunde {i}</Nm>'
                     f'</Pty></Dbtr></RltdPties><RmtInf><Ustrd>Beitrag 10/2026 RE-2026-00{i}</Ustrd></RmtInf></TxDtls>'
                     for i in range(1, 4))
        rows = self.read(self.stmt("DE02120300000000202051", [self.entry("360.00", "CRDT", f"<NtryDtls>{tx}</NtryDtls>")])).tables[0].rows
        self.assertEqual([r[7] for r in rows], [360.0])
        self.assertIsNone(rows[0][4])                          # not the first customer's money
        self.assertIn("RE-2026-003", rows[0][3])               # every purpose, for the batch to be split by number

    def test_the_booked_amount_is_what_moved(self):
        rv = self.entry("120.00", "DBIT", '<NtryDtls><TxDtls><Amt Ccy="EUR">120.00</Amt><RltdPties><Dbtr><Pty><Nm>Kunde 1</Nm>'
                        '</Pty></Dbtr></RltdPties><RmtInf><Ustrd>RE-1</Ustrd></RmtInf></TxDtls></NtryDtls>', "<RvslInd>true</RvslInd>")
        fx = self.entry("95.00", "CRDT", '<NtryDtls><TxDtls><AmtDtls><TxAmt><Amt Ccy="EUR">100.00</Amt></TxAmt></AmtDtls>'
                        '<RltdPties><Dbtr><Pty><Nm>US Client</Nm></Pty></Dbtr></RltdPties><RmtInf><Ustrd>RE-2</Ustrd></RmtInf>'
                        '</TxDtls></NtryDtls>')
        self.assertEqual([r[7] for r in self.read(self.stmt("DE02120300000000202051", [rv, fx])).tables[0].rows], [-120.0, 95.0])

    def test_two_accounts_in_one_file_say_which_account(self):
        one = '<NtryDtls><TxDtls><RmtInf><Ustrd>Umbuchung</Ustrd></RmtInf></TxDtls></NtryDtls>'
        t = self.read(self.stmt("DE02120300000000202051", [self.entry("5000.00", "DBIT", one)]),
                      self.stmt("DE89370400440532013000", [self.entry("5000.00", "CRDT", one)])).tables[0]
        self.assertEqual(t.columns[0], "Auftragskonto")
        self.assertEqual([(r[0], r[8]) for r in t.rows], [("DE02120300000000202051", -5000.0), ("DE89370400440532013000", 5000.0)])

    def test_a_day_without_bookings_is_no_document(self):
        d = self.read(self.stmt("DE02120300000000202051", []))
        self.assertEqual((d.tables, d.docs), ([], []))

    def test_an_entity_bomb_is_refused(self):
        from physarum.ingest import Digest, _read_xml
        bomb = ('<?xml version="1.0"?><!DOCTYPE d [<!ENTITY a "aaaaaaaaaa"><!ENTITY b "&a;&a;&a;&a;&a;&a;&a;&a;&a;&a;">'
                '<!ENTITY c "&b;&b;&b;&b;&b;&b;&b;&b;&b;&b;">]><Document><BkToCstmrStmt><Stmt><Ntry><Amt>&c;</Amt>'
                '</Ntry></Stmt></BkToCstmrStmt></Document>')
        with self.assertRaises(Exception):
            _read_xml("x", bomb.encode(), Digest())

    def test_the_same_bookings_as_statement_and_as_notification_count_once(self):
        f = Firm()
        self.addCleanup(f.close)
        rows, entries = [], []
        for i in range(12):
            no, gross = f"RE-2026-{i + 1:04d}", 300 + 25 * i
            rows.append([no, f"{i + 1:02d}.03.2026", f"Kunde {i % 4}", f"{gross},00"])
            if i < 9:
                entries.append((f"2026-04-{i + 1:02d}", gross, f"Kunde {i % 4}", f"Rechnung {no}", "BOOK"))
        stmt = _camt(entries)
        note = stmt.replace(b"camt.053.001.08", b"camt.054.001.08").replace(b"BkToCstmrStmt", b"BkToCstmrDbtCdtNtfctn") \
            .replace(b"<Stmt>", b"<Ntfctn>").replace(b"</Stmt>", b"</Ntfctn>")
        f.feed([("Rechnungen.csv", csv("Rechnungsnr;Datum;Kunde;Brutto", rows)),
                ("camt053_2026-04.xml", stmt), ("camt054_2026-04.xml", note)])
        rt = f.rt()
        bank = next(t for t in rt.model["types"] if t.get("concept") == "kontobewegung")
        self.assertEqual(len(rt.records[bank["id"]]), 9)
        self.assertFalse([e for e in rt.ledger.values() if e["state"] == "überzahlt"])
        self.assertEqual(len([e for r, e in rt.ledger.items() if rt.by_id[r]["type"] == _type(rt, "Rechnung")["id"]
                              and e["state"] == "bezahlt"]), 9)


if __name__ == "__main__":
    unittest.main()
