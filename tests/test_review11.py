"""Review 11 – a sports club nobody had seen: its bank in MT940, a member list whose first date is a birthday, and
money owed without an invoice – rent and fees, period after period (with the property manager of review 10)."""
import unittest
from datetime import date

from physarum.ingest import read_file
from tests.test_unseen_firm import Firm, csv

STA = """:20:STARTUMS
:25:12345678/0123456789
:28C:00001/001
:60F:C260102EUR1234,56
:61:2601050105CR42,00NMSCNONREF
:86:166?00GUTSCHRIFT?20EREF+RE-2026-0001?21SVWZ+Beitrag Q1 2026 Mitgl 1042?30GENODEF1XXX?31DE021203000000002
02051?32MUELLER HANS
:61:2601070107DR3,00NCHGNONREF
:86:805?00ENTGELT?20Ruecklastschrift Gebuehr
:62F:C260107EUR1273,56
-
:20:STARTUMS
:25:12345678/0999999999
:28C:00001/001
:60F:C260102EUR10,00
:61:2601060106CR5,00NTRFNONREF
:86:166?00GUTSCHRIFT?20Spende?32ANNA SCHMIDT
:62F:C260106EUR15,00
-
"""


class Mt940(unittest.TestCase):
    def test_a_statement_in_mt940_is_read_like_camt(self):
        t = read_file("auszug.sta", STA.encode("latin-1")).tables[0]
        self.assertEqual(t.columns[:2], ["Auftragskonto", "Buchungstag"])          # two accounts in one file
        first = dict(zip(t.columns, t.rows[0]))
        self.assertEqual((first["Betrag"], first["Zahlungspartner"], first["IBAN"], first["BIC"]),
                         (42.0, "MUELLER HANS", "DE02120300000000202051", "GENODEF1XXX"))
        self.assertEqual(first["Verwendungszweck"], "Beitrag Q1 2026 Mitgl 1042")   # SVWZ, not the references
        self.assertEqual(first["Kundenreferenz (End-to-End)"], "RE-2026-0001")
        self.assertEqual([r[t.columns.index("Betrag")] for r in t.rows], [42.0, -3.0, 5.0])

    def test_a_day_without_bookings_is_no_document(self):
        d = read_file("leer.sta", ":20:STARTUMS\n:25:12345678/0123456789\n:28C:00001/001\n:60F:C260102EUR10,00\n"
                                  ":62F:C260102EUR10,00\n-\n".encode())
        self.assertEqual((d.tables, d.docs), ([], []))


class Birthday(unittest.TestCase):
    def test_a_birthday_is_no_start(self):
        from physarum.process import _first_date
        spec = dict(attrs=[dict(id="a1", name="Geburtsdatum", kind="date", fill=1.0),
                           dict(id="a2", name="Eintritt", kind="date", fill=1.0)])
        recs = [dict(data=dict(a1=date(1950 + i, 3, 1).isoformat(), a2=date(2015 + i % 10, 1, 1).isoformat())) for i in range(40)]
        self.assertEqual(_first_date(spec, recs), "a2")


def iban(n: int) -> str:
    return f"DE{n:02d}1203000000{n:08d}"[:22]


class ClaimsWithoutInvoice(unittest.TestCase):
    def setUp(self):
        self.f = Firm()
        self.addCleanup(self.f.close)

    def open_claims(self):
        rt = self.f.rt()
        return rt, {c["label"]: c["open"] for c in rt.claims.values() if c["open"] > 0.005}

    def test_rent_month_after_month(self):
        """Tenants pay their rent every month by transfer; one stops in July, one pays 600 instead of 812 from June."""
        rents = {f"{1000 + i}": 600 + 35 * i for i in range(8)}
        rents["1007"] = 812
        tenants = [[k, f"Mieter {k} Nachname{k}", iban(int(k) - 990), f"{v},00", "01.01.2020"] for k, v in rents.items()]
        bank = []
        for mo in range(1, 10):
            for k, v in rents.items():
                if k == "1006" and mo >= 7:
                    continue                                    # stops paying
                paid = 600 if k == "1007" and mo >= 6 else v
                bank.append([f"0{2 if mo != 2 else 3}.{mo:02d}.2026", f"Miete {mo:02d}/2026 {k}", f"Mieter {k} Nachname{k}",
                             iban(int(k) - 990), f"{paid},00"])
        bank.append(["28.09.2026", "Abschlag Strom", "Stadtwerke", iban(77), "-120,00"])   # the statement reaches September
        self.f.feed([("Mieter.csv", csv("Mieter-Nr;Name;IBAN;Gesamtmiete;Mietbeginn", tenants)),
                     ("Konto.csv", csv("Buchungstag;Verwendungszweck;Zahlungspartner;IBAN;Betrag", bank))])
        rt, got = self.open_claims()
        self.assertEqual(got, {"1006 Gesamtmiete 07/2026": 810.0, "1006 Gesamtmiete 08/2026": 810.0,
                               "1006 Gesamtmiete 09/2026": 810.0, **{f"1007 Gesamtmiete {m:02d}/2026": 212.0 for m in range(6, 10)}})
        group = next(g for g in rt.work(date(2026, 10, 1)) if g["id"].startswith("claims:"))
        self.assertEqual({x["title"] for x in group["items"]}, {rt.title(m) for m in {c["member"] for c in rt.claims.values()
                                                                                      if c["open"] > 0.005}})
        receipts = [x for g in rt.work(date(2026, 10, 1)) if g["kind"] == "receipt" for x in g["items"]]
        self.assertFalse(receipts)                                # the rent is no money for nothing

    def test_a_fee_raised_for_all_in_july(self):
        """Members pay each quarter; from July the fee is 42 instead of 36 – one standing order still says 36. A member
        who pays 9 € a month is not taken for one who pays the old fee."""
        members = [[f"{2001 + i}", f"Mitglied Vorname{i} Nachname{i}", "vierteljährlich", "42,00"] for i in range(9)]
        members.append(["2010", "Mitglied Vorname9 Nachname9", "vierteljährlich", "42,00"])
        bank = []
        for i in range(9):
            for mo, amount in ((1, 36), (4, 36), (7, 42 if i < 8 else 36)):
                bank.append([f"1{i}.{mo:02d}.2026", f"Beitrag Q{(mo - 1) // 3 + 1} 2026 Mitgl {2001 + i}",
                             f"Mitglied Vorname{i} Nachname{i}", f"{amount},00"])
        for mo in range(1, 10):
            bank.append([f"05.{mo:02d}.2026", "Beitrag Mitgl 2010", "Mitglied Vorname9 Nachname9", "9,00"])
        self.f.feed([("Mitglieder.csv", csv("Mitgliedsnr.;Name;Zahlungsrhythmus;Beitrag je Fälligkeit", members)),
                     ("Konto.csv", csv("Buchungstag;Verwendungszweck;Zahlungspartner;Betrag", bank))])
        rt, got = self.open_claims()
        self.assertEqual(got, {"2009 Beitrag je Fälligkeit Q3/2026": 6.0})
        group = next(g for g in rt.work(date(2026, 10, 1)) if g["id"].startswith("claims:"))
        self.assertEqual([x["reason"] for x in group["items"]], ["Q3/2026 (6,00 € von 42,00 €) offen"])  # the quarter, not "07/2026"


if __name__ == "__main__":
    unittest.main()
