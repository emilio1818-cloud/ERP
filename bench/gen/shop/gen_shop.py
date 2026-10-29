#!/usr/bin/env python3
"""Ritzelwerk (fictional online bike-parts shop, Osnabrück): messy two-delivery data dump + exact ground truth.

    python3 gen_shop.py OUT

writes OUT/lieferung1/…, OUT/lieferung2/…, OUT/truth_d1.json, OUT/truth_d2.json.  Seeded: the same every run.
"""
from __future__ import annotations

import json
import shutil
import sys
import zipfile
from datetime import date, datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from export import (eml, pdf_invoice, write_bank, write_contacts, write_inventur, write_invoice_book, write_klarna,  # noqa: E402
                    write_orders, write_paypal, write_pricelist, write_products, write_receipts, write_returns,
                    write_shopify_payments, xrechnung, mde_t)
from sim import CUT, OWN_IBAN, Mail  # noqa: E402
from truth import compute_truth  # noqa: E402
from world import SIELMANN_MAIL, World  # noqa: E402

SHOP = "Ritzelwerk Kundenservice <info@ritzelwerk.example>"
INFO = "info@ritzelwerk.example"


def mails_for(w: World) -> list[Mail]:
    sc, S = w.scenario, w.special
    find = w.find
    out: list[Mail] = []

    def mail(k, fname, when, sender, subject, body, needs, kind, to=INFO, refs=(), att=None, reply=""):
        out.append(Mail(fname=fname, when=when, sender=sender, to=to, subject=subject, body=body, needs_action=needs,
                        kind=kind, refs=list(refs), attachment=att, delivery=k, reply_to_msgid=reply))

    fo = find(sc["forgotten"])
    mail(1, "2026-10-27_Wo_bleibt_mein_Paket.eml", datetime(2026, 10, 27, 9, 14), f"Sabine Krüger <{S['forgotten'].email}>",
         f"Wo bleibt mein Paket? Bestellung {fo.name}",
         f"Hallo,\n\nich habe am 21.10. bei Ihnen bestellt (Bestellung {fo.name}, Lichtset und Minipumpe) und gleich mit "
         "PayPal bezahlt. Bisher habe ich keine Versandbestätigung bekommen und auch keine Sendungsnummer.\n\n"
         "Können Sie mir sagen, wann das Paket kommt? Ich brauche das Licht dringend, es wird ja jetzt früh dunkel.\n\n"
         "Viele Grüße\nSabine Krüger\nHannover", True, "Lieferstatus", refs=[fo.name])
    go = find(sc["gloves_order"])
    mail(1, "Ruecksendung_Handschuhe.eml", datetime(2026, 10, 26, 20, 2), f"Hauke Janßen <{S['gloves'].email}>",
         "Rücksendung Handschuhe",
         f"Moin,\n\ndie Handschuhe Griffig Sommer in L aus meiner Bestellung {go.name} sind leider zu klein. "
         "Ich möchte sie zurückgeben. Bekomme ich ein Retourenetikett von Ihnen oder soll ich sie selbst frankieren?\n\n"
         "Bezahlt habe ich mit Klarna.\n\nGruß Hauke Janßen", True, "Retoure", refs=[go.name])
    sielmann_sep = [i for i in w.inv if i.cust.kno == "K-10001" and i.kind == "Rechnung" and i.d.month == 9]
    copy_inv = sielmann_sep[0] if sielmann_sep else [i for i in w.inv if i.cust.kno == "K-10001"][-1]
    sc["invoice_copy_requested"] = copy_inv.no
    mail(1, "Rechnungskopie_Radhaus_Sielmann.eml", datetime(2026, 10, 27, 10, 31),
         "Petra Sielmann <buchhaltung@radhaus-sielmann.example>", f"Rechnungskopie {copy_inv.no}",
         f"Sehr geehrte Frau Brenner,\n\nbei uns fehlt die Rechnung {copy_inv.no} vom {copy_inv.d:%d.%m.%Y} "
         f"(Ihre Lieferung an unsere Werkstatt). Bitte senden Sie uns eine Kopie als PDF.\n\n"
         "Mit freundlichen Grüßen\nPetra Sielmann\nBuchhaltung · Radhaus Sielmann GmbH · Osterdeich 112 · 28205 Bremen",
         True, "Bitte", refs=[copy_inv.no])
    items = "\n".join(f"{q} x {sku}" for sku, q in SIELMANN_MAIL)
    mail(1, "Bestellung_KW44_Radhaus_Sielmann.eml", datetime(2026, 10, 28, 7, 48),
         "Henning Sielmann <werkstatt@radhaus-sielmann.example>", "Bestellung KW 44",
         f"Moin Jana,\n\nbitte schick uns diese Woche noch:\n\n{items}\n\nLieferung wie immer an die Werkstatt, "
         "Rechnung an die Buchhaltung.\n\nDanke und Gruß\nHenning\n\nRadhaus Sielmann GmbH – Kd-Nr. K-10001",
         True, "Bestellung", refs=["K-10001"])
    bo = find(sc["brakes_order"])
    mail(1, "Reklamation_Bremsbelaege.eml", datetime(2026, 10, 23, 18, 20), f"Mehmet Öztürk <{S['brakes'].email}>",
         f"Reklamation Bestellung {bo.name}",
         f"Guten Tag,\n\ndie Bremsbeläge (Stopp Organic, Shimano J04C) aus Bestellung {bo.name} passen nicht an meine "
         "Deore-Bremse, die Halteklammer ist anders. Laut Ihrer Seite sollten sie passen. Können Sie mir die richtigen "
         "schicken oder das Geld erstatten?\n\nMfG M. Öztürk", True, "Reklamation", refs=[bo.name])
    lo = find(sc["paid_after_cancel"])
    mail(1, "Stornierung_trotz_Zahlung.eml", datetime(2026, 10, 21, 13, 5), f"Dennis Rothert <{S['latepay'].email}>",
         f"Bestellung {lo.name} storniert?!",
         f"Hallo,\n\nich habe gestern {mde_t(lo.total)} € für die Bestellung {lo.name} überwiesen und heute sehe ich, dass "
         "die Bestellung storniert wurde. Ich habe bereits bezahlt! Bitte schicken Sie mir die Kette trotzdem oder "
         "überweisen Sie mir das Geld zurück.\n\nDennis Rothert", True, "schon bezahlt", refs=[lo.name])
    vo = find(sc["vatinv_order"])
    mail(1, "Rechnung_mit_MwSt.eml", datetime(2026, 10, 25, 11, 47), f"Christina Haase <{S['vatinv'].email}>",
         f"Rechnung für Bestellung {vo.name}",
         f"Hallo Ritzelwerk-Team,\n\nfür mein Dienstrad brauche ich für den Arbeitgeber eine ordentliche Rechnung mit "
         f"ausgewiesener Mehrwertsteuer zu meiner Bestellung {vo.name} vom 13.10. Können Sie mir die bitte per Mail "
         "schicken?\n\nDanke!\nChristina Haase", True, "Bitte", refs=[vo.name])
    mail(1, "Anfrage_Haendlerkonditionen_Radsport_Ems.eml", datetime(2026, 10, 26, 15, 33),
         "Gerrit Wulf <einkauf@radsport-ems.example>", "Anfrage Händlerkonditionen",
         "Sehr geehrte Damen und Herren,\n\nwir sind ein Fahrradgeschäft in Lingen und suchen einen Lieferanten für "
         "Verschleißteile (Schläuche, Ketten, Bremsbeläge). Können Sie uns Ihre Händlerpreisliste und Konditionen "
         "schicken? Ein Kollege aus Bremen hat Sie empfohlen.\n\nMit freundlichen Grüßen\nGerrit Wulf\nRadsport Ems GmbH",
         True, "Anfrage")
    last_pp = [p for p in w.pp if p.kind == "sale" and p.dt.date() <= CUT[1]][-1]
    out.append(Mail(fname="PayPal_Zahlung_erhalten.eml", when=last_pp.dt + timedelta(minutes=1), sender="PayPal <service@paypal.de>",
                    to="paypal@ritzelwerk.example", subject="Sie haben eine Zahlung erhalten",
                    body=f"Hallo Ritzelwerk,\n\nSie haben eine Zahlung über {mde_t(last_pp.gross)} € EUR von {last_pp.name} erhalten.\n"
                         f"Transaktionscode: {last_pp.code}\nRechnungsnummer: {last_pp.invoice_no}\n\n"
                         "Dies ist eine automatisch erstellte Nachricht. Bitte antworten Sie nicht auf diese E-Mail.",
                    needs_action=False, kind="automatisch", refs=[last_pp.invoice_no], delivery=1, html=True))
    mail(1, "Newsletter_VeloTrade_Herbstaktion.eml", datetime(2026, 10, 20, 6, 0), "VeloTrade Newsletter <newsletter@velotrade.example>",
         "Herbstaktion: 10 % auf Beleuchtung bis 31.10.",
         "Liebe Fachhändler,\n\nbis 31.10. gibt es 10 % auf alle Beleuchtungsartikel von Leuchtturm. Einfach im B2B-Shop "
         "bestellen.\n\nIhr VeloTrade-Team\n\nAbmelden: https://velotrade.example/newsletter", False, "Newsletter")
    kl_ret = [o for o in w.orders if o.gateway == "klarna" and o.fulfilled_at and any(r.arrived > CUT[1] for r in w.returns if r.order is o)]
    if kl_ret:
        ko = kl_ret[0]
        mail(1, "Klarna_Retoure_angemeldet.eml", datetime(2026, 10, 27, 8, 2), "Klarna <noreply@klarna.de>",
             f"Retoure angemeldet für Bestellung {ko.name}",
             f"Hallo Ritzelwerk,\n\n{ko.cust.name} hat für die Bestellung {ko.name} eine Retoure angemeldet. Die Zahlung "
             "wird pausiert, bis die Retoure bearbeitet ist.\n\nIhr Klarna-Team (automatische Nachricht)", False, "automatisch",
             refs=[ko.name])
    vt_last = [si for si in w.sinv if si.supplier == "VeloTrade" and si.d <= CUT[1]][-1]
    mail(1, f"VeloTrade_Rechnung_{vt_last.no}.eml", datetime.combine(vt_last.d, datetime.min.time()).replace(hour=17, minute=5),
         "VeloTrade Buchhaltung <rechnung@velotrade.example>", f"Ihre Rechnung {vt_last.no}",
         f"Sehr geehrte Kundin, sehr geehrter Kunde,\n\nanbei erhalten Sie Ihre Rechnung {vt_last.no} zur Lieferung "
         f"{vt_last.delivery_note}.\n\nMit freundlichen Grüßen\nVeloTrade Großhandel GmbH", False, "Eingangsrechnung",
         refs=[vt_last.no], att=("pdf", vt_last.no))
    q_id = "<frage-trikot-20261020@gmail.com>"
    mail(1, "Re_Lieferzeit_Trikot.eml", datetime(2026, 10, 21, 9, 12), SHOP, "Re: Lieferzeit Trikot M Petrol",
         "Hallo Frau Siebert,\n\ndas Trikot Ritzelwerk Classic in M/Petrol kommt voraussichtlich Anfang November wieder "
         "rein. Sie können es schon bestellen, wir schicken es dann sofort los.\n\nViele Grüße\nMia Schulte\nRitzelwerk\n\n"
         "> Am 20.10.2026 schrieb Paula Siebert:\n> Hallo, wann gibt es das Trikot in M Petrol wieder?\n> Gruß Paula",
         False, "beantwortet", to=f"Paula Siebert <{S['jersey'].email}>", reply=q_id)
    mail(1, "DHL_Sendungsstatus.eml", datetime(2026, 10, 24, 11, 40), "DHL Paket <noreply@dhl.de>",
         "Ihre Sendung wurde zugestellt",
         "Guten Tag,\n\nIhre Sendung 00340434161094015902 wurde am 24.10.2026 zugestellt.\n\nIhr DHL Team\n"
         "(Diese E-Mail wurde automatisch erstellt.)", False, "automatisch")
    to_ = find(sc["thanks_order"])
    mail(1, "Danke_Sattel.eml", datetime(2026, 10, 14, 19, 3), f"Bernd Thiele <{S['thanks'].email}>", "Sattel angekommen",
         f"Hallo,\n\nder Sattel (Bestellung {to_.name}) ist angekommen und passt super. Danke für den schnellen Versand!\n\n"
         "Bernd Thiele", False, "Dank", refs=[to_.name])
    dp = sc["dispute"]
    mail(1, "PayPal_Konflikt_eroeffnet.eml", datetime(2026, 10, 24, 10, 15), "PayPal <service@paypal.de>",
         "Ein Käufer hat einen Konflikt eröffnet",
         f"Hallo Ritzelwerk,\n\n{dp['customer']} hat einen Konflikt zur Bestellung {dp['order']} eröffnet "
         f"(Grund: Artikel nicht erhalten). Betrag: {mde_t(dp['amount'])} € EUR. Der Betrag wird einbehalten, bis der "
         "Konflikt gelöst ist.\n\nBitte antworten Sie bis zum 03.11.2026 im Konfliktlösungszentrum, z. B. mit einem "
         "Sendungsnachweis.\n\nIhr PayPal-Team", True, "Konflikt", refs=[dp["order"]])

    # ---------------------------------------------------------------- second delivery (November)
    kf = next(si for si in w.sinv if si.no == sc["kartonfix_overdue"])
    mail(2, "Zahlungserinnerung_Kartonfix.eml", datetime(2026, 11, 2, 9, 0), "Kartonfix Buchhaltung <rechnungen@kartonfix.example>",
         f"Zahlungserinnerung Rechnung {kf.no}",
         f"Sehr geehrte Damen und Herren,\n\nsicher haben Sie übersehen, dass unsere Rechnung {kf.no} vom {kf.d:%d.%m.%Y} "
         f"über {mde_t(kf.gross)} € seit dem {kf.due:%d.%m.%Y} fällig ist. Bitte überweisen Sie den Betrag in den nächsten "
         "Tagen.\n\nMit freundlichen Grüßen\nKartonfix Verpackungen GmbH", False, "Mahnung (erledigt: am 03.11. bezahlt)",
         refs=[kf.no])
    da = find(sc["damaged_order"])
    mail(2, "Paket_beschaedigt.eml", datetime(2026, 11, 20, 19, 44), f"Natalia Nowak <{S['damaged'].email}>",
         f"Standpumpe kaputt angekommen – {da.name}",
         f"Hallo,\n\ndie Standpumpe aus Bestellung {da.name} ist heute angekommen, aber der Karton war eingedrückt und das "
         "Manometer ist gesprungen. Fotos hänge ich an, wenn Sie möchten. Wie geht es jetzt weiter?\n\nNatalia Nowak",
         True, "Reklamation", refs=[da.name])
    mail(2, "Erstbestellung_Radsport_Ems.eml", datetime(2026, 11, 12, 8, 10), "Gerrit Wulf <einkauf@radsport-ems.example>",
         "Erstbestellung Radsport Ems",
         "Hallo Frau Brenner,\n\ndanke für die Preisliste. Wir bestellen erstmal: 20 x SCH-28-SV, 10 x SCH-29-SV, 6 x KET-11, "
         "4 x KET-12, 10 x BBS-B01S, 12 x OEL-DRY. Zahlungsziel 14 Tage wie besprochen.\n\nGruß Gerrit Wulf",
         False, "Bestellung (erledigt: am 13.11. angelegt)", refs=[sc["new_b2b_order"]])
    le = sc["le_open"]
    mail(2, "Lastesel_Zahlungszusage.eml", datetime(2026, 11, 18, 12, 0), "Wiebke Göken <kasse@lastesel-os.example>",
         f"Re: Offene Rechnung {le}",
         f"Hallo Jana,\n\nsorry, die Rechnung {le} ist bei unserem Kassenwechsel untergegangen. Wir überweisen bis zum "
         "25.11.\n\nViele Grüße\nWiebke\nLastesel Lastenradverleih e.V.", False, "Zahlungszusage (erledigt: am 24.11. bezahlt)",
         refs=[le])
    rw = find(sc["refundwait_order"])
    mail(2, "Wo_bleibt_meine_Erstattung.eml", datetime(2026, 11, 24, 21, 15), f"Florian Dittmann <{S['refundwait'].email}>",
         f"Erstattung Rücksendung {rw.name}",
         f"Hallo,\n\nich habe das Trikot aus Bestellung {rw.name} zurückgeschickt, laut DHL ist es am 12.11. bei Ihnen "
         "angekommen. Bisher habe ich mein Geld (PayPal) nicht zurück. Wann wird erstattet?\n\nFlorian Dittmann",
         True, "Erstattung", refs=[rw.name])
    for si in [s for s in w.sinv if s.supplier == "VeloTrade" and CUT[1] < s.d <= CUT[2]][:2]:
        mail(2, f"VeloTrade_Rechnung_{si.no}.eml", datetime.combine(si.d, datetime.min.time()).replace(hour=17, minute=2),
             "VeloTrade Buchhaltung <rechnung@velotrade.example>", f"Ihre Rechnung {si.no}",
             f"Sehr geehrte Kundin, sehr geehrter Kunde,\n\nanbei erhalten Sie Ihre Rechnung {si.no} zur Lieferung "
             f"{si.delivery_note}.\n\nMit freundlichen Grüßen\nVeloTrade Großhandel GmbH", False, "Eingangsrechnung",
             refs=[si.no], att=("pdf", si.no))
    mail(2, "Umfirmierung_Bike_and_Bean.eml", datetime(2026, 11, 3, 10, 20), "Luca Brandt <hallo@bikeandbean.example>",
         "Wir heißen jetzt Bike & Bean GmbH",
         "Hallo Jana,\n\nkurze Info: Seit 1.11. sind wir die Bike & Bean GmbH (vorher Bike & Bean Café-Werkstatt UG). Neue "
         "Adresse: Hasestraße 63, 49074 Osnabrück. Bitte Rechnungen ab sofort auf den neuen Namen. Kundennummer bleibt "
         "K-10010, oder?\n\nLuca", False, "Stammdaten (erledigt: in lexoffice geändert)", refs=["K-10010"])
    mail(2, "Newsletter_VeloTrade_Winter.eml", datetime(2026, 11, 10, 6, 0), "VeloTrade Newsletter <newsletter@velotrade.example>",
         "Winterpause: Bestellschluss 18.12.", "Liebe Fachhändler,\n\nletzte Bestellung vor der Winterpause bis 18.12.\n\n"
         "Ihr VeloTrade-Team", False, "Newsletter")
    mail(2, "PayPal_Konflikt_geschlossen.eml", datetime(2026, 11, 6, 14, 5), "PayPal <service@paypal.de>",
         "Konflikt zu Ihren Gunsten entschieden",
         f"Hallo Ritzelwerk,\n\nder Konflikt zur Bestellung {dp['order']} wurde zu Ihren Gunsten entschieden. Der "
         "einbehaltene Betrag wurde freigegeben.\n\nIhr PayPal-Team", False, "automatisch", refs=[dp["order"]])
    return [m_ for m_ in out if m_ is not None]


def build(out: Path):
    w = World()
    w.run()
    mails = mails_for(w)
    if out.exists():
        shutil.rmtree(out)
    truths = {}
    for k in (1, 2):
        cut = CUT[k]
        base = out / f"lieferung{k}"
        for sub in ("Shop", "PayPal", "Klarna", "Bank", "lexoffice", "Lager", "Mails"):
            (base / sub).mkdir(parents=True, exist_ok=True)
        files = {}
        files["orders"] = write_orders(w, k, base / "Shop" / "orders_export_1.csv")
        write_products(w, k, base / "Shop" / "products_export_1.csv")
        files["sp"] = write_shopify_payments(w, k, base / "Shop" / "payment_transactions_export_1.csv")
        files["paypal"] = write_paypal(w, k, base / "PayPal" / "Download.CSV")
        lo = "2026-01-01" if k == 1 else "2026-10-01"
        files["klarna"] = write_klarna(w, k, base / "Klarna" / f"settlement_report_{lo}_{cut.isoformat()}.csv")
        files["bank"] = write_bank(w, k, base / "Bank" / f"Umsaetze_{OWN_IBAN}_{cut:%Y.%m.%d}.csv")
        files["invoices"] = write_invoice_book(w, k, base / "lexoffice" / "Rechnungen_2026.xlsx")
        write_contacts(w, k, base / "lexoffice" / "Kontakte_Export.csv")
        files["returns"] = write_returns(w, k, base / "Lager" / "Retouren_2026.xlsx")
        files["receipts"] = write_receipts(w, k, base / "Lager" / "Wareneingang_2026.xlsx")
        if k == 1:
            files["inventur"] = write_inventur(w, base / "Lager" / "Inventur_31.12.2025.xlsx")
            (base / "Vertrieb").mkdir(exist_ok=True)
            write_pricelist(w, base / "Vertrieb" / "Haendlerpreisliste_2026.xlsx")
        # supplier documents
        docs = {}
        tmp = out / f"_docs{k}"
        tmp.mkdir(parents=True, exist_ok=True)
        for si in w.sinv:
            dump = 1 if (date(2026, 8, 1) <= si.d <= CUT[1]) else (2 if CUT[1] < si.d <= CUT[2] else 0)
            if dump != k:
                continue
            if si.supplier == "Wollweber" and "Vereinsdruck" not in si.lines[0][1]:
                p = tmp / f"XRechnung_{si.no}.xml"
                p.write_bytes(xrechnung(si))
            else:
                prefix = {"VeloTrade": "VT_Rechnung", "Kartonfix": "Kartonfix_RG", "Wollweber": "Wollweber_Rechnung",
                          "DHL": "DHL_Rechnung", "Google": "Google_Ads_Rechnung"}[si.supplier]
                p = tmp / f"{prefix}_{si.no}.pdf"
                pdf_invoice(p, si, w)
            docs[si.no] = p
        if k == 1:
            (base / "Belege").mkdir(exist_ok=True)
            with zipfile.ZipFile(base / "Belege" / "Belege_Eingang_2026-08_bis_10.zip", "w", zipfile.ZIP_DEFLATED) as z:
                for no, p in sorted(docs.items()):
                    z.write(p, f"Eingangsrechnungen/{p.name}")
        else:
            d = base / "Eingangsrechnungen_November"
            d.mkdir(exist_ok=True)
            for no, p in docs.items():
                shutil.copy(p, d / p.name)
        for m_ in mails:
            if m_.delivery != k:
                continue
            att = []
            if m_.attachment:
                kind, no = m_.attachment
                p = docs[no]
                att.append((p.name, p.read_bytes(), "application/pdf"))
            (base / "Mails" / m_.fname).write_bytes(eml(m_, att))
        shutil.rmtree(tmp)
        truths[k] = compute_truth(w, k, mails, files)
        truths[k]["files"] = sorted(str(p.relative_to(base)) for p in base.rglob("*") if p.is_file())
        (out / f"truth_d{k}.json").write_text(json.dumps(truths[k], ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    return w, truths


if __name__ == "__main__":
    out = Path(sys.argv[1] if len(sys.argv) > 1 else "out")
    w, truths = build(out)
    for k, t in truths.items():
        c = t["counts"]
        print(f"delivery {k}: as of {t['as_of']}: {c['orders_in_this_export']} orders in export, {c['bank_lines_in_this_file']} bank lines, "
              f"open B2B {t['b2b']['open_items']['count']} / {t['b2b']['open_items']['total']} €, todo {len(t['todo'])}")
