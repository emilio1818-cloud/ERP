"""Review 9, a caterer nobody had seen: a bank that speaks only camt.053, and contracts billed period by
period whose forgotten month nobody reported (the cleaning firm of review 8 had the same gap)."""
import unittest
from datetime import date

from tests.test_unseen_firm import Firm, _type, csv


def _camt(entries) -> bytes:
    """A camt.053 statement: (day, amount, other party, purpose, status) per booking; a list of
    (amount, party, purpose) as amount makes one booking of several transactions (a batch)."""
    def tx(amount, party, purpose):
        side = "Dbtr" if amount > 0 else "Cdtr"
        return (f"<TxDtls><Amt Ccy=\"EUR\">{abs(amount):.2f}</Amt><RltdPties><{side}><Pty><Nm>{party}</Nm></Pty></{side}>"
                f"</RltdPties><RmtInf><Ustrd>{purpose}</Ustrd></RmtInf></TxDtls>")
    out = []
    for day, amount, party, purpose, status in entries:
        txs = amount if isinstance(amount, list) else [(amount, party, purpose)]
        total = sum(a for a, _p, _u in txs)
        out.append(f"<Ntry><Amt Ccy=\"EUR\">{abs(total):.2f}</Amt><CdtDbtInd>{'CRDT' if total > 0 else 'DBIT'}</CdtDbtInd>"
                   f"<Sts><Cd>{status}</Cd></Sts><BookgDt><Dt>{day}</Dt></BookgDt><ValDt><Dt>{day}</Dt></ValDt>"
                   f"<NtryDtls>{''.join(tx(*t) for t in txs)}</NtryDtls></Ntry>")
    return ("<?xml version=\"1.0\" encoding=\"UTF-8\"?><Document xmlns=\"urn:iso:std:iso:20022:tech:xsd:camt.053.001.08\">"
            "<BkToCstmrStmt><GrpHdr><MsgId>1</MsgId></GrpHdr><Stmt><Id>1</Id><Acct><Id><IBAN>DE02120300000000202051</IBAN>"
            "</Id><Ownr><Nm>Muster GmbH</Nm></Ownr></Acct>" + "".join(out) + "</Stmt></BkToCstmrStmt></Document>").encode()


class Contracts(unittest.TestCase):
    def setUp(self):
        self.f = Firm()

    def tearDown(self):
        self.f.close()

    def test_a_bank_statement_as_camt053(self):
        rows, entries = [], []
        for i in range(12):
            no, gross = f"RE-2026-{i + 1:04d}", 300 + 25 * i
            rows.append([no, f"{i + 1:02d}.03.2026", f"Kunde {i % 4}", f"{gross},00"])
            if i < 9:
                entries.append((f"2026-04-{i + 1:02d}", gross, f"Kunde {i % 4}", f"Rechnung {no}", "BOOK"))
        entries.append(("2026-04-15", [(-1800.0, "Anna Lohn", "Lohn 03/2026"), (-2100.0, "Ben Lohn", "Lohn 03/2026")],
                        None, None, "BOOK"))                                    # one booking, two transfers
        entries.append(("2026-04-16", 425.0, "Kunde 2", "Rechnung RE-2026-0010", "PDNG"))  # not booked yet
        self.f.feed([("Rechnungen.csv", csv("Rechnungsnr;Datum;Kunde;Brutto", rows)),
                     ("camt053_2026-04.xml", _camt(entries))])
        rt = self.f.rt()
        bank = next(t for t in rt.model["types"] if t.get("concept") == "kontobewegung")
        self.assertEqual(len(rt.records[bank["id"]]), 11)                       # 9 payments, 2 wages
        inv = _type(rt, "Rechnung")
        state = {rt.by_id[r]["data"][inv["key"]]: e["state"] for r, e in rt.ledger.items()}
        self.assertEqual(sorted(k for k, v in state.items() if v != "bezahlt"), ["RE-2026-0010", "RE-2026-0011", "RE-2026-0012"])

    def test_a_contract_month_nobody_billed(self):
        today = date(2026, 10, 20)
        contracts = [["V-01", "Kunde 1", "01.03.2024", ""], ["V-02", "Kunde 2", "01.05.2023", ""],
                     ["V-03", "Kunde 3", "01.01.2025", ""], ["V-04", "Kunde 4", "01.09.2022", ""],
                     ["V-05", "Kunde 5", "01.07.2026", ""], ["V-06", "Kunde 6", "01.02.2021", "31.08.2026"],
                     ["V-07", "Kunde 7", "01.10.2025", ""], ["V-08", "Kunde 8", "01.11.2024", ""]]
        months = {"V-02": set(range(1, 10)) - {6},          # June forgotten
                  "V-04": set(range(1, 8)),                    # nothing since August: ended, not forgotten
                  "V-05": {8, 9},                              # began in July: July forgotten
                  "V-06": set(range(1, 9))}                    # ended with August
        rows, bank, n = [], [], 0
        for v, cust, *_ in contracts:
            for m in sorted(months.get(v, set(range(1, 10)))):
                n += 1
                day = date.fromordinal(date(2026, m + 1, 1).toordinal() - 1)  # billed on the month's last day
                rows.append([f"RE-2026-{n:04d}", day.strftime("%d.%m.%Y"), cust, v, f"{m:02d}/2026", f"{595 + 7 * int(v[-1])},00"])
        for i in range(8):  # jobs of their own, without a contract
            n += 1
            rows.append([f"RE-2026-{n:04d}", f"{10 + i:02d}.0{i + 1}.2026", f"Kunde {i % 8 + 1}", "", "", f"{180 + 15 * i},00"])
        for r in rows:  # paid ten days later
            paid = date(int(r[1][6:]), int(r[1][3:5]), int(r[1][:2])).toordinal() + 10
            if paid < today.toordinal():
                bank.append([date.fromordinal(paid).strftime("%d.%m.%Y"), f"Rechnung {r[0]}", r[2], r[5]])
        self.f.feed([("Kunden.csv", csv("Kd.-Nr.;Name;Ort", [[f"K{i}", f"Kunde {i}", "Hildesheim"] for i in range(1, 9)])),
                     ("Vertraege.csv", csv("Vertrag;Kunde;Beginn;Vertragsende", contracts)),
                     ("Rechnungen.csv", csv("Rechnungsnr;Datum;Kunde;Vertrag;Zeitraum;Brutto", rows)),
                     ("Konto.csv", csv("Buchungstag;Verwendungszweck;Zahlungspartner;Betrag", bank))])
        rt = self.f.rt()
        g = next(g for g in rt.work(today) if g["id"].endswith(":periods"))
        self.assertEqual({x["title"]: x["reason"] for x in g["items"]},
                         {"V-02": "06/2026 ohne Rechnung", "V-05": "07/2026 ohne Rechnung"})
        self.assertEqual(g["kind"], "ready")                                   # money waiting to be asked for
        from starlette.testclient import TestClient
        from physarum.web.app import create_app
        v02 = next(x["rid"] for x in g["items"] if x["title"] == "V-02")
        page = TestClient(create_app(self.f.dir / "firma")).get(f"/r/{v02}").text
        self.assertIn("zuletzt berechnet", page)                               # how far it is billed, not a chain
        self.assertIn("06/2026 ohne Rechnung", page)


if __name__ == "__main__":
    unittest.main()
