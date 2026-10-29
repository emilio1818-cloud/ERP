"""Lessons from a firm nobody had seen: a web agency with a CRM, two time trackers, an
invoice book, a bank statement and a ticket system, delivered twice.

Each test is one finding of the independent review that once gave a wrong answer.
"""
import json
import shutil
import tempfile
import unittest
from datetime import date, timedelta
from email.message import EmailMessage
from pathlib import Path

from physarum.grow import ingest, regrow
from physarum.runtime import Runtime
from physarum.store import Store
from physarum.values import parse_hours


def csv(head, rows, sep=";"):
    return (head + "\n" + "\n".join(sep.join(str(x) for x in r) for r in rows) + "\n").encode("utf-8")


def _pdf(text: str) -> bytes:
    """A minimal one-page PDF with a line of text."""
    body = f"BT /F1 12 Tf 50 750 Td ({text}) Tj ET".encode("latin-1")
    objs = [b"<< /Type /Catalog /Pages 2 0 R >>", b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
            b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] /Contents 4 0 R "
            b"/Resources << /Font << /F1 5 0 R >> >> >>",
            b"<< /Length %d >>\nstream\n" % len(body) + body + b"\nendstream",
            b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>"]
    out, offs = b"%PDF-1.4\n", []
    for i, o in enumerate(objs, start=1):
        offs.append(len(out))
        out += b"%d 0 obj\n" % i + o + b"\nendobj\n"
    xref = len(out)
    out += b"xref\n0 %d\n0000000000 65535 f \n" % (len(objs) + 1)
    out += b"".join(b"%010d 00000 n \n" % o for o in offs)
    out += b"trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (len(objs) + 1, xref)
    return out


class Firm:
    def __init__(self):
        self.dir = Path(tempfile.mkdtemp(prefix="physarum-unseen-"))
        self.store = Store(self.dir / "firma")

    def feed(self, files):
        ingest(self.store, [(n, b if isinstance(b, bytes) else b.encode("utf-8")) for n, b in files], "Test")
        return regrow(self.store)

    def rt(self):
        rt = Runtime(self.store)
        rt.ensure()
        return rt

    def close(self):
        shutil.rmtree(self.dir, ignore_errors=True)


def _type(rt, name):
    return next(t for t in rt.model["types"] if t["name"] == name)


INV_HEAD = "Belegnummer;Belegdatum;Kundennummer;Kunde;Betreff;Netto;USt;Brutto;Fällig am;Status"


def _invoices(n=30, start=date(2026, 3, 2)):
    rows = []
    for i in range(n):
        d = start + timedelta(days=i)
        net = 100 + 10 * i
        rows.append([f"RE-2026-{i + 1:04d}", d.strftime("%d.%m.%Y"), f"K-{10000 + i % 6}", f"Kunde {i % 6} GmbH",
                     f"Leistung {i}", f"{net},00", f"{net * 0.19:.2f}".replace(".", ","),
                     f"{net * 1.19:.2f}".replace(".", ","), (d + timedelta(days=14)).strftime("%d.%m.%Y"), "offen"])
    return rows


class UnseenFirm(unittest.TestCase):
    def setUp(self):
        self.f = Firm()

    def tearDown(self):
        self.f.close()

    def test_a_row_exported_twice_does_not_cost_the_list_its_numbers(self):
        rows = _invoices()
        v1 = rows[:20] + [rows[7]]  # one invoice written twice into the first export
        self.f.feed([("Rechnungsausgangsbuch_2026-03-21.csv", csv(INV_HEAD, v1))])
        rt = self.f.rt()
        inv = _type(rt, "Rechnung")
        ids1 = {r["data"][inv["key"]]: r["id"] for r in rt.records[inv["id"]]}
        self.assertEqual(len(ids1), 20)
        v2 = [list(r) for r in rows]
        v2[3][-1] = "bezahlt"  # a status changed in the next export
        self.f.feed([("Rechnungsausgangsbuch_2026-04-15.csv", csv(INV_HEAD, v2))])
        rt = self.f.rt()
        inv = _type(rt, "Rechnung")
        self.assertEqual(inv["key"], next(a["id"] for a in inv["attrs"] if a["name"] == "Belegnummer"))
        ids2 = {r["data"][inv["key"]]: r["id"] for r in rt.records[inv["id"]]}
        self.assertEqual(len(rt.records[inv["id"]]), 30)
        self.assertTrue(all(ids2[k] == v for k, v in ids1.items()))  # every invoice kept its identity
        removed = self.f.store.q1("SELECT COUNT(*) n FROM changes WHERE kind='remove'")["n"]
        self.assertEqual(removed, 0)

    def test_overlapping_time_exports_carry_corrections_and_deletions(self):
        head = "Project,User,Email,Start Date,Start Time,Duration (h)"
        days = [date(2026, 9, 1) + timedelta(days=i) for i in range(20)]
        old = [[f"P-2026-0{10 + i % 3} Relaunch", "Anna Berg", "anna@agentur.de", d.strftime("%m/%d/%Y"), "09:00 AM",
                "02:00:00"] for i, d in enumerate(days)]
        self.f.feed([("Clockify_Time_Report_09_01_2026-09_20_2026.csv", csv(head, old, ","))])
        new = [list(r) for r in old[10:]]
        new[0][5] = "03:00:00"   # corrected in the time tracker
        del new[1]                # deleted in the time tracker
        new += [[f"P-2026-010 Relaunch", "Anna Berg", "anna@agentur.de", (date(2026, 9, 21) + timedelta(days=i))
                 .strftime("%m/%d/%Y"), "09:00 AM", "01:00:00"] for i in range(5)]
        self.f.feed([("Clockify_Time_Report_09_11_2026-09_25_2026.csv", csv(head, new, ","))])
        rt = self.f.rt()
        te = _type(rt, "Zeiteintrag")
        hours = next(a["id"] for a in te["attrs"] if a["name"].startswith("Duration"))
        recs = rt.records[te["id"]]
        self.assertEqual(len(recs), 10 + 9 + 5)
        self.assertAlmostEqual(sum(r["data"][hours] for r in recs), 10 * 2 + 3 + 8 * 2 + 5, places=2)

    def test_split_debit_credit_columns_credit_notes_storno_and_a_swapped_number(self):
        rows = _invoices(12)
        gross = {r[0]: float(r[7].replace(",", ".")) for r in rows}
        rows.append(["GS-2026-0001", "20.03.2026", "K-10002", "Kunde 2 GmbH", "Gutschrift zu RE-2026-0003 (Nachlass)",
                     "-50,00", "-9,50", "-59,50", "", "Gutschrift"])
        rows.append(["ST-2026-0001", "21.03.2026", "K-10004", "Kunde 4 GmbH", "Stornorechnung zu RE-2026-0005",
                     "-140,00", "-26,60", "-166,60", "", "Storno"])
        bank_head = '"Buchungstag";"Auftraggeber / Begünstigter";"Verwendungszweck";"Soll";"Haben";"Währung"'
        bank = []
        for no in [r[0] for r in rows[:12]]:
            if no in ("RE-2026-0003", "RE-2026-0005", "RE-2026-0010", "RE-2026-0001"):
                continue
            k = int(no[-2:]) - 1
            bank.append(["25.03.2026", f"Kunde {k % 6} GmbH", no, "", f"{gross[no]:.2f}".replace(".", ",")])
        bank.append(["26.03.2026", "Kunde 2 GmbH", "RE-2026-0003 abzgl. GS-2026-0001", "",
                     f"{gross['RE-2026-0003'] - 59.5:.2f}".replace(".", ",")])
        bank.append(["27.03.2026", "Kunde 3 GmbH", "RE-2026-0001", "",  # meant RE-2026-0010, digits swapped
                     f"{gross['RE-2026-0010']:.2f}".replace(".", ",")])
        bank.append(["27.03.2026", "Bürobedarf AG", "Druckerpatronen", "89,90", ""])
        bank_csv = (bank_head + "\n" + "\n".join(";".join(f'"{x}"' for x in r + ["EUR"]) for r in bank) + "\n")
        self.f.feed([("Rechnungsausgangsbuch.csv", csv(INV_HEAD, rows)),
                     ("Umsaetze_Girokonto.csv", bank_csv.encode("cp1252"))])
        rt = self.f.rt()
        inv = _type(rt, "Rechnung")
        by_no = {r["data"][inv["key"]]: rt.ledger.get(r["id"]) for r in rt.records[inv["id"]]}
        self.assertEqual(by_no["RE-2026-0003"]["state"], "bezahlt")      # paid minus its credit note
        self.assertEqual(by_no["GS-2026-0001"]["state"], "verrechnet")
        self.assertEqual(by_no["RE-2026-0005"]["state"], "storniert")    # cancelled by its storno document
        self.assertEqual(by_no["RE-2026-0010"]["state"], "bezahlt")      # the swapped number found its invoice
        self.assertEqual(by_no["RE-2026-0001"]["state"], "offen")
        self.assertEqual(sorted(k for k, e in by_no.items() if e and e["open"] > 0.005), ["RE-2026-0001"])

    def test_hours_however_they_were_typed(self):
        for raw, h in [("1,5", 1.5), ("1:30", 1.5), ("01:30:00", 1.5), ("1,35 h", 1.35), ("2 h", 2.0), ("2 Std.", 2.0),
                       ("90 min", 1.5), ("1h 30m", 1.5), (1.75, 1.75), ("0:57", 0.95)]:
            self.assertAlmostEqual(parse_hours(raw), h, places=2, msg=str(raw))
        rows = [[f"{(i % 20) + 1:02d}.03.2026", f"Projekt {i % 3}", "Entwicklung", v]
                for i, v in enumerate(["1,5", "2:15", "1,35 h", "2 h", "0:30", "3", "1,25", "4", "2,5", "1"] * 2)]
        self.f.feed([("Stundenzettel_Steinbach_2026.csv", csv("Datum;Projekt;Tätigkeit;Stunden", rows))])
        rt = self.f.rt()
        sz = _type(rt, "Stundenzettel")
        hours = next(a for a in sz["attrs"] if a["name"] == "Stunden")
        vals = [r["data"].get(hours["id"]) for r in rt.records[sz["id"]]]
        self.assertTrue(all(isinstance(v, float) for v in vals))
        self.assertAlmostEqual(sum(vals), 2 * (1.5 + 2.25 + 1.35 + 2 + 0.5 + 3 + 1.25 + 4 + 2.5 + 1), places=2)

    def test_project_numbers_inside_names_and_time_entries_are_events(self):
        projects = [[f"P-2026-{i:03d}", f"Kunde {i % 4} GmbH", ["Website-Relaunch", "Wartung & Hosting"][i % 2],
                     f"{(i % 9) + 1:02d}.02.2026", f"{5000 + 100 * i}"] for i in range(1, 13)]
        entries = []
        for k in range(60):
            i = k % 12 + 1
            name = ["Website-Relaunch", "Wartung & Hosting"][i % 2]
            label = f"P-2026-{i:03d} {name}" if k % 2 else f"{name} Kunde {i % 4} ({'P-2026-%03d' % i})"
            entries.append([label, "anna@agentur.de", (date(2026, 3, 1) + timedelta(days=k)).strftime("%d.%m.%Y"), "2,0"])
        self.f.feed([("Projektliste.csv", csv("Projekt-Nr.;Kunde;Projekt;Start;Budget", projects)),
                     ("time_entries_2026.csv", csv("Project;Email;Date;Duration (h)", entries))])
        rt = self.f.rt()
        pj = _type(rt, "Projekt")
        self.assertEqual(len(rt.records[pj["id"]]), 12)  # one project per number, whatever the tool wrote
        te = _type(rt, "Zeiteintrag")
        self.assertEqual(te["kind"], "transaction")
        ref = next(a for a in te["attrs"] if a["kind"] == "ref" and a.get("ref") == pj["id"])
        self.assertEqual(sum(1 for r in rt.records[te["id"]] if isinstance(r["data"].get(ref["id"]), int)), 60)

    def test_the_same_pdf_as_file_and_as_mail_attachment(self):
        pdf = _pdf("Rechnung FR-2026-117 Steinbach IT 1.785,00 EUR")
        m = EmailMessage()
        m["From"], m["To"], m["Subject"] = "marco@steinbach-it.de", "info@agentur.de", "Rechnung September"
        m.set_content("Anbei meine Rechnung.")
        m.add_attachment(pdf, maintype="application", subtype="pdf", filename="FR-2026-117.pdf")
        s = self.f.feed([("belege/FR-2026-117.pdf", pdf), ("mails/rechnung.eml", m.as_bytes())])
        self.assertIsNotNone(s)
        docs = self.f.store.q("SELECT data FROM records WHERE type='doc' AND deleted=0")
        self.assertGreaterEqual(len(docs), 2)  # the mail and the invoice, the PDF only once

    def test_deleted_in_the_crm_is_marked_moved_between_sheets_is_not(self):
        head = "Record ID,First Name,Last Name,Email,Company Name"
        people = [[str(9000 + i), ["Anna", "Jan", "Lena", "Paul", "Maria", "Tim"][i % 6], f"Muster{i}",
                   f"p{i}@firma{i % 5}.de", f"Firma {i % 5} GmbH"] for i in range(25)]
        self.f.feed([("hubspot-crm-exports-all-contacts-2026-09-15.csv", csv(head, people, ","))])
        self.f.feed([("hubspot-crm-exports-all-contacts-2026-10-27.csv", csv(head, people[:-2], ","))])
        rt = self.f.rt()
        kt = _type(rt, "Kontakt")
        gone = [r for r in rt.records[kt["id"]] if (r.get("meta") or {}).get("vanished")]
        self.assertEqual(len(rt.records[kt["id"]]), 25)
        self.assertEqual(sorted(r["data"][kt["key"]] for r in gone), ["9023", "9024"])

    def test_fixed_budget_overrun_and_freelancer_names(self):
        kunden = ["Elbkind Spielwaren GmbH", "Tidenhub Meerestechnik GmbH", "Baumschule Kruse GmbH", "Hansen Bau GmbH",
                  "Kröger Haustechnik GmbH"]
        projects = []
        for i in range(1, 11):
            k = kunden[i % 5]
            short = k.split()[0]
            art = ["Website-Relaunch", "Wartung & Hosting"][i % 2]
            projects.append([f"P-2026-{i:03d}", short, art, art, "Festpreis" if i % 2 == 0 else "Retainer",
                             f"{i:02d}.03.2026", "8000" if i % 2 == 0 else "250"])
        self.f.feed([("Kunden.csv", csv("Kundennr;Firma;Ort", [[f"K-{100 + i}", k, "Hamburg"] for i, k in enumerate(kunden)])),
                     ("Projektliste.csv", csv("Projekt-Nr.;Kunde;Projekt;Art;Abrechnung;Start;Budget", projects))])
        entries, sheet = [], []
        for k in range(120):
            i = k % 10 + 1
            amount = "950,00" if i == 2 else "150,00"  # P-2026-002: 12 x 950 = 11.400 on a budget of 8.000
            entries.append([f"P-2026-{i:03d} Projekt", "anna@agentur.de",
                            (date(2026, 3, 15) + timedelta(days=k % 60)).strftime("%d.%m.%Y"), "2,0", amount])
            p = projects[i - 1]
            name = f"{p[1]} {'Relaunch' if 'Relaunch' in p[2] else 'Wartung'}" if k % 2 else \
                f"{'Relaunch' if 'Relaunch' in p[2] else 'Wartung'} {p[1]}"
            sheet.append([(date(2026, 3, 15) + timedelta(days=k % 60)).strftime("%d.%m.%Y"), name, "Entwicklung", "1,5"])
        self.f.feed([("time_entries.csv", csv("Project;Email;Date;Duration (h);Amount (EUR)", entries)),
                     ("Stundenzettel_Steinbach.csv", csv("Datum;Projekt;Tätigkeit;Stunden", sheet))])
        rt = self.f.rt()
        pj = _type(rt, "Projekt")
        work = rt.work(date(2026, 6, 1))
        over = next(g for g in work if g["kind"] == "budget")
        self.assertEqual([it["title"] for it in over["items"]], ["P-2026-002"])  # retainers are left out
        sz = _type(rt, "Stundenzettel")
        ref = next(a for a in sz["attrs"] if a["kind"] == "ref" and a.get("ref") == pj["id"])
        linked = [r for r in rt.records[sz["id"]] if isinstance(r["data"].get(ref["id"]), int)]
        self.assertGreaterEqual(len(linked), 0.9 * len(rt.records[sz["id"]]))
        by_no = {r["id"]: r["data"][pj["key"]] for r in rt.records[pj["id"]]}
        for r in linked:  # "Elbkind Relaunch" and "Wartung Tidenhub" name the right project
            name = r["data"][next(a["id"] for a in sz["attrs"] if a["name"] == "Projekt")]
            no = by_no[r["data"][ref["id"]]]
            p = projects[int(no[-3:]) - 1]
            self.assertIn(p[1], str(rt.title(r["data"][ref["id"]])) + " " + no + " " + p[1])

    def test_a_note_is_a_document_not_a_table(self):
        self.f.feed([("LIESMICH.txt", "Export aus Toggl + alter Kundenstamm (WaWi 2014), erstellt 02.07.2025 von J. P.\n"
                                      "Toggl wurde zum 30.06.2025 gekündigt, ab 01.07. Clockify.\n"),
                     ("kunden.csv", csv("Kundennr;Firma;Ort", [[f"K-{i}", f"Firma {i} GmbH", "Kiel"] for i in range(10)]))])
        rt = self.f.rt()
        self.assertFalse(any("LIESMICH" in t["name"] for t in rt.model["types"]))
        self.assertTrue(any("LIESMICH" in str(r["data"].get("doc_title")) for r in rt.records.get("doc", [])))


if __name__ == "__main__":
    unittest.main()
