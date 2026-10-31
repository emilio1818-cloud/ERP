"""Every page and every action an owner has, through the web doors, on the grown demo company.

The other tests check what the actions compute. This one checks that each door opens: no page and no
button answers with a crash, odd input included, and what an action promises is there afterwards."""
import io
import re
import shutil
import tempfile
import time
import unittest
from pathlib import Path

from starlette.testclient import TestClient

from physarum.demo.generate import generate
from physarum.grow import ingest, regrow
from physarum.runtime import Runtime
from physarum.store import Store
from physarum.web.app import create_app

SAME_ORIGIN = {"origin": "http://testserver", "x-requested-with": "fetch"}


class EveryAction(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = Path(tempfile.mkdtemp(prefix="physarum-doors-"))
        res = generate(cls.tmp / "dump")
        cls.store = Store(cls.tmp / "firma")
        ingest(cls.store, [(p.name, p.read_bytes()) for p in res["initial"]], "Test")
        regrow(cls.store)
        cls.c = TestClient(create_app(cls.tmp / "firma"))
        cls.rt = Runtime(cls.store)
        cls.rt.ensure()

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def tearDown(self):
        for _ in range(600):  # a growth an action started is over before the next test looks
            if not self.store.q1("SELECT id FROM jobs WHERE status='running'"):
                return
            time.sleep(0.1)

    # --- helpers -------------------------------------------------------------------------------------------
    def spec(self, name):
        self.rt.ensure()
        return next(t for t in self.rt.model["types"] if t["name"] == name)

    def attr(self, spec, name):
        return next(a for a in spec["attrs"] if a["name"] == name)

    def get(self, url, ok=(200,)):
        r = self.c.get(url, follow_redirects=False)
        self.assertLess(r.status_code, 500, f"{url}: {r.text[:300]}")
        if ok:
            self.assertIn(r.status_code, ok, url)
        return r

    def post(self, url, data=None, ok=(200, 303), **kw):
        r = self.c.post(url, data=data or {}, headers=SAME_ORIGIN, follow_redirects=False, **kw)
        self.assertLess(r.status_code, 500, f"{url}: {r.text[:300]}")
        if ok:
            self.assertIn(r.status_code, ok, f"{url}: {r.text[:300]}")
        return r

    def done(self, r):
        """An action that answers in JSON did what it said, or started a job that finished."""
        j = r.json()
        self.assertNotIn("error", j, j)
        if "job" in j:
            for _ in range(600):
                s = self.c.get(f"/api/job/{j['job']}").json()
                if s["status"] != "running":
                    break
                time.sleep(0.1)
            self.assertEqual(s["status"], "done", s)
        return j

    # --- reading -------------------------------------------------------------------------------------------
    def test_every_page_opens(self):
        self.rt.ensure()
        for url in ("/", "/gesund", "/fragen", "/organismus", "/ablaeufe", "/quellen", "/firma", "/suche?q=Hafen",
                    "/steuerberatung", "/steuerberatung?art=quartal&jahr=2026&nr=2", "/steuerberatung?art=jahr&jahr=2026",
                    "/verfahrensdoku", "/sicherung.zip"):
            self.get(url)
        for spec in self.rt.model["types"]:
            tid = spec["id"]
            for url in (f"/t/{tid}", f"/t/{tid}?teil=1", f"/t/{tid}/neu", f"/export/{tid}.csv", f"/export/{tid}.xlsx"):
                self.get(url)
            for rec in self.rt.records.get(tid, [])[:2]:
                self.get(f"/r/{rec['id']}")
                self.get(f"/api/datensatz/{rec['id']}")
        inv = self.spec("Rechnung")
        rid = self.rt.records[inv["id"]][0]["id"]
        self.get(f"/r/{rid}/druck")
        self.get(f"/r/{rid}/erinnerung", ok=None)
        self.get(f"/r/{rid}/xrechnung", ok=(200, 404, 409))  # an invoice of the old program has no e-invoice
        sid = self.store.q1("SELECT id FROM sources WHERE active=1 ORDER BY id")["id"]
        self.get(f"/quellen/{sid}/datei")
        kunde = self.spec("Kunde")
        self.assertTrue(self.get(f"/api/suche?q=a&typen={kunde['id']}").json())
        party = self.rt.records[kunde["id"]][0]["id"]
        self.get(f"/api/wie-letztes-mal?typ={self.spec('Auftrag')['id']}&partei={party}")

    def test_an_amount_and_what_a_booking_was_for(self):
        """An amount typed as it stands on the statement finds what carries it; the bank list says what each
        booking was for."""
        from urllib.parse import quote
        from physarum.billing import money_fields
        from physarum.web import views
        inv = self.spec("Rechnung")
        gross = money_fields(inv)["gross"]["id"]
        rec = next(r for r in self.rt.records[inv["id"]] if (r["data"].get(gross) or 0) > 1000)
        amount = f"{rec['data'][gross]:,.2f}".translate(str.maketrans(",.", ".,"))   # 1.059,10
        for q in (amount, amount.replace(".", "") + " €"):
            self.assertIn(str(rec["data"][inv["key"]]), self.get(f"/suche?q={quote(q)}").text, q)
        bank = next(t for t in self.rt.model["types"] if t.get("concept") == "kontobewegung")
        purpose = self.attr(bank, "Verwendungszweck")["id"]
        self.assertIn(purpose, [c["id"] for c in views.list_columns(bank, 8)])

    def test_who_owes_how_much(self):
        """The customer list says who owes how much: their open invoices, by the bank – and all of them."""
        from physarum.web import views
        kunde = self.spec("Kunde")
        self.assertIn("pay_open", [c["id"] for c in views.list_columns(kunde, 8)])
        owed = sum(r["data"].get("pay_open") or 0 for t in self.rt.model["types"] if t.get("kind") == "master"
                   for r in self.rt.records.get(t["id"], []))
        open_ = sum(e["open"] for e in self.rt.ledger.values()
                    if not e.get("outgoing") and e["state"] in ("offen", "teilbezahlt") and e["open"] > 0.005)
        self.assertGreater(owed, 0)
        self.assertAlmostEqual(owed, open_, places=2)
        self.assertIn("Offen", self.get(f"/t/{kunde['id']}").text)

    def test_odd_requests_never_crash(self):
        """What a stale tab, a typo in the address or a half-sent form sends: an answer, never a crash."""
        for url in ("/api/wie-letztes-mal?typ=gibtsnicht&partei=abc", "/api/wie-letztes-mal", "/api/suche?typen=,,",
                    "/api/datensatz/0", "/api/ableiten", "/api/ableiten?typ=x&attr=y", "/api/job/0", "/wachsen/0",
                    "/r/0", "/r/0/xrechnung", "/r/0/druck", "/r/0/erinnerung", "/mahnung/0", "/quellen/0/datei",
                    "/t/x", "/t/x/neu", "/export/x.csv", "/export/x.xlsx", "/suche?q=",
                    "/steuerberatung?art=woche&jahr=x&nr=y", "/steuerberatung?art=monat&jahr=99999&nr=13"):
            self.get(url, ok=None)
        for url, data in (("/r/0", {"a_x": "1"}), ("/r/0/einblenden", {}), ("/r/0/notiz", {"text": "x"}),
                          ("/r/0/positionen", {"pos_0_text": "x"}), ("/r/0/trennen", {"key": "x"}),
                          ("/r/0/korrektur-gesehen", {}), ("/r/0/schritt", {"attr": "x"}), ("/r/0/nachfassen", {}),
                          ("/r/0/zahlung", {"amount": "x"}), ("/r/0/zahlung-entfernen", {}), ("/r/0/zuordnen", {}),
                          ("/r/0/storno", {}), ("/r/0/loeschen", {}), ("/r/0/rueckgaengig", {}), ("/r/0/ausstellen", {}),
                          ("/r/0/zahlung-loesen", {}), ("/post/0/erledigt", {}), ("/zahlungsquelle/0", {}),
                          ("/mahnung/0", {}), ("/fragen/0", {"value": "yes"}), ("/fragen/0", {"value": "reopen"}),
                          ("/regel", {}), ("/organismus/verweis", {}), ("/organismus/umbenennen", {"type": "x", "name": "X"}),
                          ("/organismus/feld", {"type": "x", "attr": "y", "action": "hide"}), ("/t/x/neu", {"a_x": "1"}),
                          ("/t/x/spalte", {}), ("/quellen/0/entfernen", {}), ("/quellen/0/zurueck", {}),
                          ("/steuerberatung/einstellungen", {"berater": "abc", "fy_start": "99"}),
                          ("/steuerberatung/export", {"art": "x", "jahr": "y"}), ("/firma", {"iban": "x" * 500}),
                          ("/ich", {"name": "x" * 100}), ("/einwerfen", {})):
            self.post(url, data, ok=None)

    # --- writing -------------------------------------------------------------------------------------------
    def test_owner_corrects_a_customer_and_takes_it_back(self):
        kunde = self.spec("Kunde")
        rec = self.rt.records[kunde["id"]][1]
        text = next(a for a in kunde["attrs"] if a["kind"] in ("text", "phone", "city", "street")
                    and a["id"] != kunde.get("key") and not a.get("hidden") and not a.get("virtual"))
        r = self.post(f"/r/{rec['id']}", {f"a_{text['id']}": "Testwert 42"})
        self.assertIn("gespeichert=1", r.headers["location"])
        self.assertEqual(self.store.record(rec["id"])["data"][text["id"]], "Testwert 42")
        self.done(self.post(f"/r/{rec['id']}/rueckgaengig", {"attrs": text["id"]}))
        self.assertNotEqual(self.store.record(rec["id"])["data"].get(text["id"]), "Testwert 42")
        self.post(f"/r/{rec['id']}/notiz", {"text": "Ruft lieber vormittags an"})
        self.assertIn("Ruft lieber vormittags an", self.get(f"/r/{rec['id']}").text)

    def test_hide_and_show_again(self):
        bank = self.spec("Kontobewegung")
        rid = self.rt.records[bank["id"]][-1]["id"]
        self.done(self.post(f"/r/{rid}/loeschen", {"reason": "doppelt eingelesen"}))
        self.get(f"/r/{rid}", ok=(404,))
        self.post(f"/r/{rid}/einblenden")
        self.get(f"/r/{rid}")

    def test_owner_shapes_lists_and_names(self):
        art = self.spec("Artikel")
        col = next(a for a in art["attrs"] if not a.get("hidden") and a["id"] != art.get("key"))
        self.done(self.post(f"/t/{art['id']}/spalte", {"attr": col["id"], "action": "pin"}))
        self.assertIn(col["id"], self.store.decisions("list_cols")[art["id"]]["pin"])
        self.done(self.post(f"/t/{art['id']}/spalte", {"attr": col["id"], "action": "unpin"}))
        self.post("/organismus/feld", {"type": art["id"], "attr": col["id"], "action": "rename", "name": "Mein Feld"})
        self.assertEqual(self.attr(self.spec("Artikel"), "Mein Feld")["id"], col["id"])
        self.post("/organismus/feld", {"type": art["id"], "attr": col["id"], "action": "hide"})
        self.assertTrue(self.attr(self.spec("Artikel"), "Mein Feld").get("hidden"))
        self.post("/organismus/feld", {"type": art["id"], "attr": col["id"], "action": "show"})
        self.post("/organismus/umbenennen", {"type": art["id"], "name": "Produkt", "plural": "Produkte"})
        self.assertIn("Produkte", self.get(f"/t/{art['id']}").text)
        self.post("/organismus/umbenennen", {"type": art["id"], "name": "Artikel", "plural": "Artikel"})
        self.done(self.post("/regel", {"key": "test|regel", "value": "on"}))
        r = self.post("/ich", {"name": "Anna"})
        self.assertIn("physarum_name", r.headers.get("set-cookie", ""))

    def test_invoice_from_the_form_to_the_einvoice_and_storno(self):
        self.post("/firma", {"name": "Röstwerk Hafenbohne GmbH", "street": "Am Kai 3", "zip": "20457", "city": "Hamburg",
                             "vat_id": "DE123456789", "iban": "DE95 2005 0550 2461 5874 01", "email": "buero@hafenbohne.de",
                             "phone": "040 123456", "country": "DE", "back": "/firma"})
        self.assertIn("Am Kai 3", self.get("/firma").text)
        inv, kunde = self.spec("Rechnung"), self.spec("Kunde")
        party = next(r for r in self.rt.records[kunde["id"]] if r["data"].get(self.attr(kunde, "PLZ")["id"]))
        r = self.post(f"/t/{inv['id']}/neu", {f"a_{self.attr(inv, 'Kunde')['id']}": str(party["id"])})
        rid = int(re.search(r"/r/(\d+)", r.headers["location"]).group(1))
        self.done(self.post(f"/r/{rid}/positionen", {"pos_0_text": "Espresso Bohne 1 kg", "pos_0_qty": "3",
                                                     "pos_0_price": "18,90", "pos_0_rate": "7",
                                                     "pos_1_text": "Versand", "pos_1_qty": "1",
                                                     "pos_1_price": "5,90", "pos_1_rate": "19"}))
        self.assertAlmostEqual(self.store.record(rid)["data"][self.attr(inv, "Netto")["id"]], 62.6, places=2)
        j = self.done(self.post(f"/r/{rid}/ausstellen", {"leistung": "2026-06-01", "hier": "1"}))
        self.assertIn("Ausgestellt", j["toast"])
        self.assertIn("Espresso Bohne", self.get(f"/r/{rid}/druck").text)
        x = self.get(f"/r/{rid}/xrechnung")
        self.assertIn("<cbc:PayableAmount", x.text)
        j = self.done(self.post(f"/r/{rid}/storno", {"reason": "falscher Kunde"}))
        self.get(j["next"])

    def test_money_by_hand_and_sources_of_payments(self):
        er = self.spec("Eingangsrechnung")
        rid = self.rt.records[er["id"]][0]["id"]
        j = self.done(self.post(f"/r/{rid}/zahlung", {"amount": "10,00", "date": "2026-06-02", "how": "ueberweisung"}))
        self.done(self.post(j["undo"]["url"], j["undo"]["body"]))
        sid = self.store.q1("SELECT id FROM sources WHERE active=1 ORDER BY id")["id"]
        j = self.done(self.post(f"/zahlungsquelle/{sid}"))
        self.done(self.post(j["undo"]["url"], j["undo"]["body"]))
        self.done(self.post("/zahlungen/zuordnen"))
        doc = self.rt.records[self.spec("Dokument")["id"]][0]["id"]
        j = self.done(self.post(f"/post/{doc}/erledigt"))
        self.done(self.post(j["undo"]["url"], j["undo"]["body"]))

    def test_a_fraud_warning_until_the_supplier_is_asked(self):
        x = next(x for g in self.rt.work() if g["kind"] == "risk" for x in g["items"] if x.get("mail"))
        home = self.get("/").text
        self.assertIn(f'data-post="/post/{x["mail"]}/erledigt"', home)
        self.assertNotIn("Stand Ihrer Daten", home)                    # the statement reaches into this week
        page = self.get(f"/r/{x['rid']}").text
        self.assertIn("Vorsicht:", page)
        self.assertIn(f'href="/r/{x["mail"]}"', page)
        j = self.done(self.post(f"/post/{x['mail']}/erledigt"))
        self.assertNotIn("Vorsicht:", self.get(f"/r/{x['rid']}").text)
        self.done(self.post(j["undo"]["url"], j["undo"]["body"]))
        self.assertIn("Vorsicht:", self.get(f"/r/{x['rid']}").text)

    def test_heute_asks_once_who_works_here(self):
        c = TestClient(self.c.app)
        self.assertIn("Wer arbeitet hier?", c.get("/").text)
        c.post("/ich", data={"name": "Katrin"}, headers=SAME_ORIGIN, follow_redirects=False)
        self.assertNotIn("Wer arbeitet hier?", c.get("/").text)

    def test_questions_can_wait_and_come_back(self):
        q = self.store.q1("SELECT id FROM questions WHERE status='open' ORDER BY id")
        if not q:
            self.skipTest("keine offene Frage")
        self.done(self.post(f"/fragen/{q['id']}", {"value": "later"}))
        self.done(self.post(f"/fragen/{q['id']}", {"value": "reopen"}))
        self.assertEqual(self.store.q1("SELECT status FROM questions WHERE id=?", (q["id"],))["status"], "open")

    def test_tax_settings_stay(self):
        self.post("/steuerberatung/einstellungen", {"berater": "1234567", "mandant": "4711", "skr": "SKR04",
                                                    "method": "ist", "fy_start": "1"})
        cfg = self.store.kv_get("tax_advisor")
        self.assertEqual((cfg["berater"], cfg["mandant"], cfg["method"]), (1234567, 4711, "ist"))
        self.post("/steuerberatung/einstellungen", {"method": "soll"})

    def test_feeding_and_taking_out_a_file(self):
        csv = "Kennzeichen;Marke;Erstzulassung\nHH-HB 101;VW Caddy;2021-03-01\nHH-HB 102;Ford Transit;2019-07-15\n"
        r = self.post("/einwerfen", files=[("files", ("Fahrzeuge.csv", io.BytesIO(csv.encode()), "text/csv"))])
        self.done(r)
        sid = self.store.q1("SELECT id FROM sources WHERE name='Fahrzeuge.csv'")["id"]
        self.assertIn("Fahrzeuge.csv", self.get("/quellen").text)
        self.done(self.post(f"/quellen/{sid}/entfernen"))
        self.assertFalse(self.store.q1("SELECT active FROM sources WHERE id=?", (sid,))["active"])
        self.done(self.post(f"/quellen/{sid}/zurueck"))
        self.assertTrue(self.store.q1("SELECT active FROM sources WHERE id=?", (sid,))["active"])
        self.assertEqual(self.post("/r/1/trennen", {"key": "gibt es nicht"}, ok=(400,)).json().keys(), {"error"})


if __name__ == "__main__":
    unittest.main()
