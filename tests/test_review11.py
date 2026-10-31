"""Review 11 – a sports club nobody had seen: its bank in MT940, a member list whose first date is a birthday."""
import unittest
from datetime import date

from physarum.ingest import read_file

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


if __name__ == "__main__":
    unittest.main()
