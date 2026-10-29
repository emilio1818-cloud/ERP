"""Write the files a small online shop really has lying around, from the simulated world."""
from __future__ import annotations

import csv
import io
import random
import zipfile
from collections import defaultdict
from datetime import date, datetime, timedelta
from email.message import EmailMessage
from email.utils import format_datetime, make_msgid
from pathlib import Path
from zoneinfo import ZoneInfo

import openpyxl
from openpyxl.styles import Font

from sim import CUT, D1, D2, FIRM, OWN_BIC, OWN_IBAN, SEED, add_bdays, bday_on_or_after, is_bday, next_bday
from world import PAYMETHOD, PICKUP, TAXNAME

BERLIN = ZoneInfo("Europe/Berlin")
START = {1: date(2026, 1, 1), 2: date(2026, 8, 1)}           # shop export period
MONEY_START = {1: date(2026, 1, 1), 2: date(2026, 10, 1)}    # bank / PayPal / Shopify Payments / Klarna


def m(c):  # 12.34
    return f"{c / 100:.2f}"


def mde(c):  # 12,34
    return f"{c / 100:.2f}".replace(".", ",")


def mde_t(c):  # 1.234,56
    s = f"{abs(c) / 100:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    return ("-" if c < 0 else "") + s


def tzoff(dt: datetime) -> str:
    return "+0200" if date(2026, 3, 29) <= dt.date() < date(2026, 10, 25) else "+0100"


def sts(dt):
    return dt.strftime("%Y-%m-%d %H:%M:%S ") + tzoff(dt) if dt else ""


def month_end_recon(d: date) -> date:
    """Last business day of d's month: Jana reconciles lexoffice and Shopify."""
    x = (d.replace(day=28) + timedelta(days=4)).replace(day=1) - timedelta(days=1)
    while not is_bday(x):
        x -= timedelta(days=1)
    return x


# ================================================================================================ state at a cut
def order_state(o, cut: date, world):
    """What Shopify shows for the order at the end of `cut`."""
    end = datetime(cut.year, cut.month, cut.day, 23, 59, 59)
    paid = o.paid_at if o.paid_at and o.paid_at <= end else None
    ful = o.fulfilled_at if o.fulfilled_at and o.fulfilled_at <= end else None
    canc = o.cancelled_at if o.cancelled_at and o.cancelled_at <= end else None
    refunded = sum(r.amount for r in o.refunds if r.when <= end)
    if o.b2b:
        paid_marked = shopify_b2b_paid(o, cut, world)
        fin = "paid" if paid_marked else "pending"
        paid = datetime.combine(paid_marked, datetime.min.time()).replace(hour=18) if paid_marked else None
    elif o.gateway == "klarna":
        fin = "voided" if canc else ("paid" if paid else "authorized")
    elif o.gateway in ("vorkasse", "cash"):
        if canc and not paid:
            fin = "voided"
        elif paid:
            fin = "partially_paid" if "partially_paid" in o.flags else "paid"
        else:
            fin = "pending"
    else:
        fin = "paid" if paid else "pending"
    if refunded and fin in ("paid", "partially_paid"):
        fin = "refunded" if refunded >= o.total - o.gc_amount else "partially_refunded"
    if canc and o.gateway in ("paypal", "shopify") and refunded:
        fin = "refunded"
    outstanding = 0
    if fin in ("pending", "authorized"):
        outstanding = o.total
    elif fin == "partially_paid":
        outstanding = o.total - sum(x["amount"] for x in o.money)
    return dict(fin=fin, paid=paid, ful=ful, canc=canc, refunded=refunded, outstanding=outstanding)


def money_in_bank(o, cut):
    return sum(x["amount"] for x in o.money if x["d"] <= cut)


# ---------------------------------------------------------------- lexoffice: what the invoice book knows
def netted_credits(world) -> dict:
    """invoice no -> credit note that the customer deducted in the payment of that invoice"""
    out = {}
    sc = world.scenario
    for key, target in (("gu2", "offset"), ("gu3", "inv")):
        x = sc.get(key)
        if isinstance(x, dict) and x.get(target):
            out[x[target]] = next(i for i in world.inv if i.no == x["no"])
    return out


def lex_events(inv, world):
    """[(when, amount)] – when lexoffice learns of a payment, independent of the cut.
    Bank sync matches transfers that carry the exact number the next banking day; Skonto, credit-note
    netting, combined transfers and references without the exact number wait for the month-end reconciliation."""
    netted = netted_credits(world)
    ev = []
    if inv.kind == "Gutschrift":
        if inv.no == world.scenario.get("gu1") and inv.payments:
            ev.append((next_bday(inv.payments[0]["d"]), inv.gross))
        else:
            for no, gu in netted.items():
                if gu is inv:
                    target = next(i for i in world.inv if i.no == no)
                    pays = [p for p in target.payments if p["amount"] > 0]
                    if pays:
                        ev.append((month_end_recon(pays[0]["d"]), inv.gross))
        return ev
    gu = netted.get(inv.no)
    remaining = inv.gross
    for p in sorted(inv.payments, key=lambda p: p["d"]):
        if p["amount"] <= 0:
            continue
        if remaining <= 0:
            break                      # a second payment for a paid invoice stays unassigned
        if gu is not None:
            ev.append((month_end_recon(p["d"]), remaining))
            remaining = 0
            continue
        if p["channel"] == "paypal":
            ev.append((p["d"], min(p["amount"], remaining)))
            remaining -= min(p["amount"], remaining)
        elif p.get("exact") and not p.get("combined"):
            amt = min(p["amount"], remaining)
            ev.append((next_bday(p["d"]), amt))
            remaining -= amt
            if remaining > 0 and inv.cust.skonto:
                ev.append((month_end_recon(p["d"]), remaining))   # booked as Skonto
                remaining = 0
        else:
            amt = min(p["amount"], remaining)
            ev.append((month_end_recon(p["d"]), amt))
            remaining -= amt
    return ev


def lex_view(inv, cut: date, world):
    """(status, open_amount, paid_on) as the lexoffice export shows it at the end of `cut`."""
    got = [(w, a) for w, a in lex_events(inv, world) if w <= cut]
    paid = sum(a for _, a in got)
    open_ = inv.gross - paid
    if inv.kind == "Gutschrift":
        return ("bezahlt", 0, max(w for w, _ in got)) if got else ("offen", inv.gross, None)
    if open_ <= 0:
        return "bezahlt", 0, max(w for w, _ in got)
    if paid > 0:
        return "teilbezahlt", open_, None
    return ("überfällig" if inv.due <= cut else "offen"), open_, None


def shopify_b2b_paid(o, cut, world):
    """Jana marks B2B orders paid in Shopify at the month-end reconciliation."""
    inv = o.invoice
    if not inv or not o.fulfilled_at or o.fulfilled_at.date() > cut:
        return None
    d = month_end_recon(inv.d)
    while d <= cut:
        if lex_view(inv, d, world)[0] == "bezahlt":
            return d
        d = month_end_recon(d + timedelta(days=5))
    return None


# ================================================================================================ Shopify orders
ORDER_COLS = ["Name", "Email", "Financial Status", "Paid at", "Fulfillment Status", "Fulfilled at", "Accepts Marketing",
              "Currency", "Subtotal", "Shipping", "Taxes", "Total", "Discount Code", "Discount Amount", "Shipping Method",
              "Created at", "Lineitem quantity", "Lineitem name", "Lineitem price", "Lineitem compare at price",
              "Lineitem sku", "Lineitem requires shipping", "Lineitem taxable", "Lineitem fulfillment status",
              "Billing Name", "Billing Street", "Billing Address1", "Billing Address2", "Billing Company", "Billing City",
              "Billing Zip", "Billing Province", "Billing Country", "Billing Phone", "Shipping Name", "Shipping Street",
              "Shipping Address1", "Shipping Address2", "Shipping Company", "Shipping City", "Shipping Zip",
              "Shipping Province", "Shipping Country", "Shipping Phone", "Notes", "Note Attributes", "Cancelled at",
              "Payment Method", "Payment Reference", "Refunded Amount", "Vendor", "Outstanding Balance", "Employee",
              "Location", "Device ID", "Id", "Tags", "Risk Level", "Source", "Lineitem discount", "Tax 1 Name",
              "Tax 1 Value", "Tax 2 Name", "Tax 2 Value", "Tax 3 Name", "Tax 3 Value", "Tax 4 Name", "Tax 4 Value",
              "Tax 5 Name", "Tax 5 Value", "Phone", "Receipt Number", "Duties", "Billing Province Name",
              "Shipping Province Name", "Payment ID", "Payment Terms Name", "Next Payment Due At", "Payment References"]


def write_orders(world, k: int, path: Path):
    cut = CUT[k]
    rng = random.Random(SEED + 100)      # the same order looks the same in both exports
    cols = list(ORDER_COLS)
    if k == 2:
        cols[cols.index("Financial Status")] = "Payment Status"
    rows = []
    orders = [o for o in world.orders if START[k] <= o.created.date() <= cut]
    styles = {}
    for o in world.orders:
        styles[o.no] = (rng.random(), rng.random(), rng.random())
    for o in sorted(orders, key=lambda o: o.created, reverse=True):
        st = order_state(o, cut, world)
        c = o.cust
        s1, s2, s3 = styles[o.no]
        bname = c.name
        if not o.b2b and s1 < 0.03:
            bname = bname.lower()
        elif not o.b2b and s1 < 0.05:
            bname = f"{c.first[0]}. {c.last}"
        company = o.b2b.name if o.b2b else ""
        if o.b2b and o.b2b.kno == "K-10010" and o.created.date() >= date(2026, 11, 3):
            company = "Bike & Bean GmbH"
        if not o.b2b and s2 < 0.02 and o.country == "DE":
            company = rng.choice(["Stadtwerke Köln GmbH", "Kanzlei Weber & Partner", "Praxis Dr. Lehmann", "Ingenieurbüro Nord"])
        street, zip_, city = c.street, c.zip, c.city
        if o.b2b and o.b2b.kno == "K-10010" and o.created.date() >= date(2026, 11, 3):
            street, zip_, city = "Hasestraße 63", "49074", "Osnabrück"
        sname, sstreet, szip, scity = bname if not o.b2b else f"{c.first} {c.last}", street, zip_, city
        if not o.b2b and s3 < 0.05:
            sname = f"{rng.choice(['Petra', 'Hannes', 'Oma Gisela', 'Lea', 'Martin'])} {c.last}"
        if k == 2 and o.name == world.scenario.get("unmatched_vorkasse"):
            sstreet = "Hammer Straße 12"        # the customer corrected the delivery address
        addr2 = "" if s2 > 0.08 else rng.choice(["Hinterhaus", "c/o Werkstatt", "2. OG links", "Packstation 112"])
        method = PAYMETHOD.get(o.gateway, o.gateway)
        fin = st["fin"]
        first = True
        tax_name = TAXNAME.get(o.country, "") if o.taxes else ""
        for ln in o.lines:
            row = dict.fromkeys(cols, "")
            row["Name"] = o.name
            row["Email"] = world.order_email(o)
            row["Created at"] = sts(o.created)
            row["Lineitem quantity"] = ln.qty
            row["Lineitem name"] = ln.v.name
            row["Lineitem price"] = m(ln.price)
            row["Lineitem compare at price"] = ""
            row["Lineitem sku"] = ln.v.sku or ""
            row["Lineitem requires shipping"] = "true" if ln.v.ship else "false"
            row["Lineitem taxable"] = "true" if ln.v.taxable else "false"
            row["Lineitem fulfillment status"] = ("fulfilled" if st["ful"] else "restocked" if st["canc"] else "pending")
            row["Vendor"] = ln.v.vendor
            row["Lineitem discount"] = m(ln.disc)
            if first:
                row.update({
                    cols[2]: fin, "Paid at": sts(st["paid"]), "Fulfillment Status": "fulfilled" if st["ful"] else "unfulfilled",
                    "Fulfilled at": sts(st["ful"]), "Accepts Marketing": "yes" if c.marketing else "no",
                    "Currency": o.currency, "Subtotal": m(o.subtotal), "Shipping": m(o.ship), "Taxes": m(o.taxes),
                    "Total": m(o.total), "Discount Code": o.disc_code, "Discount Amount": m(o.disc),
                    "Shipping Method": o.ship_method,
                    "Billing Name": bname, "Billing Street": street, "Billing Address1": street, "Billing Address2": addr2,
                    "Billing Company": company, "Billing City": city, "Billing Zip": "'" + zip_, "Billing Province": "",
                    "Billing Country": c.country, "Billing Phone": ("'" + c.phone) if c.phone else "",
                    "Shipping Name": sname if o.ship_method != PICKUP else bname, "Shipping Street": sstreet,
                    "Shipping Address1": sstreet, "Shipping Address2": addr2, "Shipping Company": company,
                    "Shipping City": scity, "Shipping Zip": "'" + szip, "Shipping Province": "", "Shipping Country": c.country,
                    "Shipping Phone": "", "Notes": o.notes, "Note Attributes": "", "Cancelled at": sts(st["canc"]),
                    "Payment Method": method, "Payment Reference": o.checkout if o.gateway not in ("b2b", "vorkasse", "cash") else "",
                    "Refunded Amount": m(st["refunded"]), "Outstanding Balance": m(st["outstanding"]),
                    "Employee": "Jana Brenner" if o.b2b else "", "Location": "Hasestraße 41" if o.ship_method == PICKUP else "",
                    "Device ID": "", "Id": o.shopify_id, "Tags": ", ".join(o.tags), "Risk Level": "Low",
                    "Source": "shopify_draft_order" if o.b2b else "web",
                    "Tax 1 Name": tax_name, "Tax 1 Value": m(o.taxes) if tax_name else "",
                    "Payment ID": "", "Payment References": o.checkout if o.gateway not in ("b2b", "vorkasse", "cash") else "",
                })
                if o.b2b:
                    row["Payment Terms Name"] = o.b2b.terms_text
                    if fin == "pending":
                        row["Next Payment Due At"] = sts(o.created + timedelta(days=o.b2b.terms))
                first = False
            rows.append(row)
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=cols)
        w.writeheader()
        w.writerows(rows)
    return len(orders), len(rows)


# ================================================================================================ Shopify products
PROD_COLS = ["Handle", "Title", "Body (HTML)", "Vendor", "Product Category", "Type", "Tags", "Published", "Option1 Name",
             "Option1 Value", "Option2 Name", "Option2 Value", "Option3 Name", "Option3 Value", "Variant SKU",
             "Variant Grams", "Variant Inventory Tracker", "Variant Inventory Qty", "Variant Inventory Policy",
             "Variant Fulfillment Service", "Variant Price", "Variant Compare At Price", "Variant Requires Shipping",
             "Variant Taxable", "Variant Barcode", "Image Src", "Image Position", "Image Alt Text", "Gift Card",
             "SEO Title", "SEO Description", "Variant Image", "Variant Weight Unit", "Variant Tax Code", "Cost per item",
             "Status"]


def shopify_available(world, sku, cut):
    on_hand = stock_on_hand(world, sku, cut)
    end = datetime(cut.year, cut.month, cut.day, 23, 59, 59)
    committed = 0
    for o in world.orders:
        if o.created > end:
            continue
        if (o.fulfilled_at and o.fulfilled_at <= end) or (o.cancelled_at and o.cancelled_at <= end):
            continue
        committed += sum(ln.qty for ln in o.lines if ln.v.sku == sku)
    forgotten = sum(r.qty for r in world.receipts if r.sku == sku and not r.booked_in_shopify and r.d <= cut)
    # Tom restocks physically when the parcel arrives, Shopify only when Mia refunds with "restock"
    pending_restock = sum(q for d, s, q, ret in world.restocked if s == sku and d <= cut and not (ret.refund_on and ret.refund_on <= cut))
    return on_hand - committed - forgotten - pending_restock


def stock_on_hand(world, sku, cut):
    q = world.inventur.get(sku, 0)
    q += sum(r.qty for r in world.receipts if r.sku == sku and r.d <= cut)
    q -= sum(qq for d, s, qq, o in world.shipped if s == sku and d <= cut)
    q += sum(qq for d, s, qq, ret in world.restocked if s == sku and d <= cut)
    return q


def write_products(world, k, path: Path):
    cut = CUT[k]
    rows = []
    by_handle = defaultdict(list)
    for v in world.catalog:
        if v.discontinued:
            continue
        by_handle[v.handle].append(v)
    for handle, vs in by_handle.items():
        v0 = vs[0]
        names = [n for n, _ in v0.opts] or ["Title"]
        for i, v in enumerate(vs):
            row = dict.fromkeys(PROD_COLS, "")
            row["Handle"] = handle
            if i == 0:
                row.update({"Title": v.title, "Body (HTML)": f"<p>{v.title} – bei Ritzelwerk in Osnabrück geprüft.</p>",
                            "Vendor": v.vendor, "Product Category": "Sporting Goods > Outdoor Recreation > Cycling",
                            "Type": v.ptype, "Tags": v.ptype.lower(), "Published": "true",
                            "Image Src": f"https://cdn.ritzelwerk.example/files/{handle}.jpg", "Image Position": 1,
                            "Image Alt Text": v.title, "Gift Card": "true" if v.gift else "false",
                            "SEO Title": "", "SEO Description": "", "Status": "active"})
                for j, n in enumerate(names[:3], 1):
                    row[f"Option{j} Name"] = n
            vals = [val for _, val in v.opts] or ["Default Title"]
            for j, val in enumerate(vals[:3], 1):
                row[f"Option{j} Value"] = val
            row.update({"Variant SKU": v.sku or "", "Variant Grams": v.grams,
                        "Variant Inventory Tracker": "shopify" if v.sku else "",
                        "Variant Inventory Qty": shopify_available(world, v.sku, cut) if v.sku else "",
                        "Variant Inventory Policy": v.policy, "Variant Fulfillment Service": "manual",
                        "Variant Price": m(v.price), "Variant Compare At Price": "",
                        "Variant Requires Shipping": "true" if v.ship else "false",
                        "Variant Taxable": "true" if v.taxable else "false", "Variant Barcode": v.ean,
                        "Variant Weight Unit": "g", "Cost per item": m(v.cost) if v.cost else ""})
            rows.append(row)
        if len(vs) > 3:
            for pos in (2, 3):
                row = dict.fromkeys(PROD_COLS, "")
                row.update({"Handle": handle, "Image Src": f"https://cdn.ritzelwerk.example/files/{handle}-{pos}.jpg",
                            "Image Position": pos})
                rows.append(row)
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=PROD_COLS)
        w.writeheader()
        w.writerows(rows)


# ================================================================================================ PayPal
PP_COLS = ["Datum", "Uhrzeit", "Zeitzone", "Name", "Typ", "Status", "Währung", "Brutto", "Gebühr", "Netto",
           "Absender E-Mail-Adresse", "Empfänger E-Mail-Adresse", "Transaktionscode", "Lieferadresse", "Adress-Status",
           "Artikelbezeichnung", "Artikelnummer", "Versand- und Bearbeitungsgebühr", "Versicherungsbetrag", "Umsatzsteuer",
           "Option 1 Name", "Option 1 Wert", "Option 2 Name", "Option 2 Wert", "Zugehöriger Transaktionscode",
           "Rechnungsnummer", "Zollnummer", "Anzahl", "Empfangsnummer", "Guthaben", "Adresszeile 1", "Adresszusatz", "Ort",
           "Bundesland", "PLZ", "Land", "Telefon", "Betreff", "Hinweis", "Ländervorwahl", "Auswirkung auf Guthaben"]


def write_paypal(world, k, path: Path):
    lo, cut = MONEY_START[k], CUT[k]
    out = io.StringIO()
    w = csv.writer(out, quoting=csv.QUOTE_ALL, lineterminator="\r\n")
    w.writerow(PP_COLS)
    n = 0
    for p in world.pp:
        if not (lo <= p.dt.date() <= cut):
            continue
        a = p.address or {}
        o = p.order
        ship = m(o.ship).replace(".", ",") if (o and p.kind == "sale") else ""
        row = [p.dt.strftime("%d.%m.%Y"), p.dt.strftime("%H:%M:%S"), "Europe/Berlin", p.name, p.typ, p.status, p.cur,
               mde_t(p.gross), mde_t(p.fee), mde_t(p.net), p.sender if p.gross > 0 or p.kind == "sale" else "paypal@ritzelwerk.example",
               p.receiver if p.gross > 0 else (p.receiver or ""), p.code,
               f"{p.name}, {a.get('street', '')}, {a.get('zip', '')} {a.get('city', '')}, {a.get('country', '')}" if a else "",
               "Bestätigt" if a else "", p.item_title, "", ship, "", "", "", "", "", "", p.related, p.invoice_no, "",
               "1" if p.kind == "sale" else "", "", mde_t(p.balance), a.get("street", ""), "", a.get("city", ""), "",
               a.get("zip", ""), {"DE": "Deutschland", "AT": "Österreich", "NL": "Niederlande", "CH": "Schweiz"}.get(a.get("country"), "") if a else "",
               "", p.subject, p.note, a.get("country", "") if a else "", p.impact]
        w.writerow(row)
        n += 1
    path.write_bytes(out.getvalue().encode("utf-8-sig"))
    return n


# ================================================================================================ Shopify Payments
SP_COLS = ["Transaction Date", "Type", "Order", "Card Brand", "Card Source", "Payout Status", "Payout Date", "Payout ID",
           "Available On", "Amount", "Fee", "Net", "Checkout", "Payment Method Name", "Presentment Amount",
           "Presentment Currency", "Currency"]


def write_shopify_payments(world, k, path: Path):
    lo, cut = MONEY_START[k], CUT[k]
    rows = []
    for s in sorted(world.sp, key=lambda s: s.dt, reverse=True):
        if not (lo <= s.dt.date() <= cut):
            continue
        paid_out = s.payout_date and s.payout_date <= cut
        avail = s.dt.date() + timedelta(days=3)
        rows.append([sts(s.dt), s.typ, s.order.name, s.brand, "online" if s.typ == "charge" else "",
                     "paid" if paid_out else "pending", s.payout_date.isoformat() if paid_out else "",
                     s.payout_id if paid_out else "", avail.isoformat(), m(s.amount), m(s.fee), m(s.net),
                     s.checkout.split(".")[0][1:], s.method, m(s.amount), "EUR", "EUR"])
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(SP_COLS)
        w.writerows(rows)
    return len(rows)


# ================================================================================================ Klarna
KL_COLS = ["type", "capture_id", "merchant_reference1", "merchant_reference2", "order_id", "capture_date", "sale_date",
           "amount", "vat_amount", "currency_code", "payment_reference", "payout_date", "purchase_country", "merchant_id",
           "short_order_id", "initial_payment_method_type"]


def write_klarna(world, k, path: Path):
    lo, cut = MONEY_START[k], CUT[k]
    rows = []
    rng = random.Random(SEED + 300)
    method = {}
    for kr in sorted(world.kl, key=lambda x: (x.payout_date or date.max, x.capture_date, x.order.no, x.typ != "SALE")):
        if not kr.payout_date or not (lo <= kr.payout_date <= cut):
            continue
        if kr.order.no not in method:
            method[kr.order.no] = rng.choices(["PAY_LATER", "PAY_NOW", "SLICE_IT"], weights=[70, 20, 10])[0]
        rows.append([kr.typ, kr.capture_id, kr.order.name, "", kr.klarna_id, kr.capture_date.isoformat(),
                     kr.sale_date.isoformat(), m(kr.amount), m(kr.vat), "EUR", kr.payout_ref, kr.payout_date.isoformat(),
                     kr.order.country, "K503210", kr.klarna_id[:8], method[kr.order.no]])
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(KL_COLS)
        w.writerows(rows)
    return len(rows)


# ================================================================================================ bank (Volksbank)
BANK_COLS = ["Bezeichnung Auftragskonto", "IBAN Auftragskonto", "BIC Auftragskonto", "Bankname Auftragskonto",
             "Buchungstag", "Valutadatum", "Name Zahlungsbeteiligter", "IBAN Zahlungsbeteiligter",
             "BIC (SWIFT-Code) Zahlungsbeteiligter", "Buchungstext", "Verwendungszweck", "Betrag", "Waehrung",
             "Saldo nach Buchung", "Bemerkung", "Kategorie", "Steuerrelevant", "Glaeubiger ID", "Mandatsreferenz"]
CATEGORY = {"rent": "Miete", "salary": "Gehalt & Lohn", "social": "Versicherungen & Abgaben", "tax": "Steuern",
            "insurance": "Versicherungen & Abgaben", "phone": "Telefon & Internet", "software": "Software", "private": "Privat",
            "bankfee": "Bankgebühren", "creditcard": "Kreditkarte"}


def write_bank(world, k, path: Path):
    lo, cut = MONEY_START[k], CUT[k]
    out = io.StringIO()
    w = csv.writer(out, delimiter=";", quoting=csv.QUOTE_MINIMAL, lineterminator="\r\n")
    w.writerow(BANK_COLS)
    n = 0
    for t in sorted((t for t in world.bank if lo <= t.d <= cut), key=lambda t: (t.d, t.seq), reverse=True):
        w.writerow(["Geschäftskonto Ritzelwerk", OWN_IBAN, OWN_BIC, "Volksbank Hasetal eG", t.d.strftime("%d.%m.%Y"),
                    (t.valuta or t.d).strftime("%d.%m.%Y"), t.name, t.iban, t.bic, t.btext, t.purpose, mde(t.amount), "EUR",
                    mde(t.balance), "", CATEGORY.get(t.kind, "Sonstiges" if t.amount < 0 else "Einnahmen"), "", t.cred_id,
                    t.mandate])
        n += 1
    path.write_bytes(out.getvalue().encode("cp1252", errors="replace"))
    return n


# ================================================================================================ lexoffice
def write_invoice_book(world, k, path: Path):
    cut = CUT[k]
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Belege"
    hdr = ["Belegnummer", "Belegdatum", "Belegtyp", "Kontakt", "Kundennummer", "Referenz", "Netto", "Steuer", "Brutto",
           "Währung", "Fälligkeit", "Status", "Offener Betrag", "Bezahlt am"]
    ws.append(hdr)
    for c in ws[1]:
        c.font = Font(bold=True)
    n = 0
    for inv in sorted((i for i in world.inv if i.d <= cut), key=lambda i: (i.d, i.no), reverse=True):
        st, open_, paid_on = lex_view(inv, cut, world)
        name = inv.cust.name
        if inv.cust.kno == "K-10010" and k == 2:
            name = "Bike & Bean GmbH"
        ref = inv.order.name if inv.order else (inv.ref.no if inv.ref else "")
        ws.append([inv.no, inv.d, inv.kind, name, inv.cust.kno, ref, inv.net / 100, inv.vat / 100, inv.gross / 100, "EUR",
                   inv.due, st, open_ / 100, paid_on])
        n += 1
    for row in ws.iter_rows(min_row=2):
        for c in (row[1], row[10], row[13]):
            c.number_format = "DD.MM.YYYY"
        for c in (row[6], row[7], row[8], row[12]):
            c.number_format = "#,##0.00"
    wb.save(path)
    return n


def write_contacts(world, k, path: Path):
    cut = CUT[k]
    out = io.StringIO()
    w = csv.writer(out, delimiter=";", lineterminator="\r\n")
    w.writerow(["Kundennummer", "Lieferantennummer", "Firmenname", "Anrede", "Vorname", "Nachname", "Straße", "PLZ", "Ort",
                "Land", "E-Mail", "Telefon", "USt-IdNr.", "IBAN", "BIC", "Zahlungsziel (Tage)", "Notiz"])
    for b in world.b2b:
        if b.kno == "K-10011" and k == 1:
            continue
        name, street, zip_ = b.name, b.street, b.zip
        if b.kno == "K-10010" and k == 2:
            name, street, zip_ = "Bike & Bean GmbH", "Hasestraße 63", "49074"
        w.writerow([b.kno, "", name, "Frau" if b.first in ("Birgit", "Katrin", "Wiebke") else "Herr", b.first, b.last, street,
                    zip_, b.city, b.country, b.email, b.phone, b.vat_id, b.iban, b.bic, b.terms,
                    "Skonto 2 % bei Zahlung in 7 Tagen" if b.skonto else ("Reverse Charge" if b.reverse_charge else "")])
    sup = [("L-70001", "VeloTrade Großhandel GmbH", "Industriestraße 120", "33689", "Bielefeld", "rechnung@velotrade.example",
            "+49 5205 99880", "DE811223344", "DE" + "48050161" + "0071188830", "SPBIDE3BXXX", 30, "Kd-Nr. bei VT: 40877"),
           ("L-70002", "Wollweber Textildruck GmbH", "Weender Landstraße 3", "37073", "Göttingen", "buchhaltung@wollweber-textil.example",
            "+49 551 3077120", "DE277665544", "DE" + "26050001" + "0058812271", "NOLADE21GOE", 30, ""),
           ("L-70003", "Kartonfix Verpackungen GmbH", "Gewerbering 7", "84030", "Ergolding", "rechnungen@kartonfix.example",
            "+49 871 9744100", "DE129988776", "DE" + "70020270" + "0659912210", "HYVEDEMMXXX", 14, ""),
           ("L-70004", "DHL Paket GmbH", "Sträßchensweg 10", "53113", "Bonn", "", "", "DE169838187", "", "", 10, "Lastschrift"),
           ("L-70005", "Google Ireland Limited", "Gordon House, Barrow Street", "D04 E5W5", "Dublin", "", "", "IE6388047V", "", "",
            0, "Lastschrift, Reverse Charge")]
    from sim import iban as mkiban
    for s in sup:
        ib = mkiban("DE", s[8][2:]) if s[8] else ""
        w.writerow(["", s[0], s[1], "", "", "", s[2], s[3], s[4], "DE" if s[0] != "L-70005" else "IE", s[5], s[6], s[7], ib,
                    s[9], s[10], s[11]])
    path.write_bytes(out.getvalue().encode("cp1252", errors="replace"))


# ================================================================================================ Excel lists of the team
def write_returns(world, k, path: Path):
    cut = CUT[k]
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Retouren 2026"
    ws.append([f"Retouren 2026 – Stand {cut + timedelta(days=1):%d.%m.%Y} (Tom)"])
    ws.append([])
    ws.append(["RMA", "Eingang", "Bestellnr.", "Kunde", "Artikel", "Menge", "Grund", "Zustand", "Erstattet am", "Betrag", "Notiz"])
    n = 0
    for ret in world.returns:
        if ret.arrived > cut:
            continue
        shown_refund = ret.sheet_refund_on if (ret.sheet_refund_on and ret.sheet_refund_on <= cut) else None
        if getattr(ret, "sheet_lag", False) and k == 1:
            shown_refund = None
        for i, (sku, q) in enumerate(ret.items):
            ws.append([ret.rma, ret.arrived, ret.sheet_order_text, ret.order.cust.name, sku, q, ret.reason if i == 0 else "",
                       ("OK – eingelagert" if ret.condition == "OK" else "beschädigt – nicht verkaufbar"),
                       shown_refund if i == 0 else None, ret.amount / 100 if i == 0 else None,
                       ("über Klarna" if ret.order.gateway == "klarna" else "") if i == 0 else ""])
            n += 1
    for row in ws.iter_rows(min_row=4):
        row[1].number_format = "DD.MM.YYYY"
        row[8].number_format = "DD.MM.YYYY"
    wb.save(path)
    return n


def write_inventur(world, path: Path):
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Inventur"
    ws.append(["Inventur zum 31.12.2025"])
    ws.append(["Lager Hasestraße 41, 49074 Osnabrück – gezählt T. Wieczorek / J. Brenner am 31.12.2025"])
    ws.append([])
    ws.append(["Lagerplatz", "Art.-Nr.", "Bezeichnung", "Menge", "Einheit", "EK netto", "Wert"])
    total = 0
    rng = random.Random(SEED + 400)
    n = 0
    for v in world.catalog:
        if not v.sku:
            continue
        q = world.inventur.get(v.sku, 0)
        val = q * v.cost
        total += val
        ws.append([f"R{rng.randint(1, 6)}-{rng.randint(1, 12):02d}", v.sku, v.name, q, "Stk", v.cost / 100, val / 100])
        n += 1
    ws.append([])
    ws.append(["", "", "Summe", None, "", None, total / 100])
    wb.save(path)
    return n


def write_receipts(world, k, path: Path):
    cut = CUT[k]
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Wareneingang"
    ws.append(["Datum", "Lieferant", "Lieferschein", "Art.-Nr.", "Bezeichnung", "Menge", "geprüft", "Bemerkung"])
    n = 0
    for r in world.receipts:
        if r.d > cut:
            continue
        ws.append([r.d, r.supplier, r.note, r.sku, world.sku[r.sku].name, r.qty, "TW", ""])
        n += 1
    for row in ws.iter_rows(min_row=2):
        row[0].number_format = "DD.MM.YYYY"
    wb.save(path)
    return n


def write_pricelist(world, path: Path):
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Händlerpreise 2026"
    ws.append(["Ritzelwerk – Händlerpreisliste 2026 (gültig ab 01.01.2026, Preise netto zzgl. USt.)"])
    ws.append([])
    ws.append(["Art.-Nr.", "Artikel", "Variante", "UVP brutto", "Händlerpreis netto", "VE"])
    by = defaultdict(list)
    for v in world.catalog:
        if v.sku and not v.discontinued:
            by[v.ptype].append(v)
    for ptype, vs in by.items():
        ws.append([ptype.upper()])
        for v in vs:
            ws.append([v.sku, v.title, v.vtitle or "", v.price / 100, v.dealer_net / 100, v.pack])
    wb.save(path)


# ================================================================================================ supplier documents
def pdf_invoice(path: Path, si, world):
    from reportlab.lib.pagesizes import A4
    from reportlab.pdfgen import canvas
    sup = {
        "VeloTrade": ("VeloTrade Großhandel GmbH", "Industriestraße 120 · 33689 Bielefeld", "Tel. +49 5205 99880 · rechnung@velotrade.example",
                      "DE811223344", "Sparkasse Bielefeld", "DE" + "48050161" + "0071188830", "SPBIDE3BXXX", "HRB 40112 AG Bielefeld"),
        "Kartonfix": ("Kartonfix Verpackungen GmbH", "Gewerbering 7 · 84030 Ergolding", "rechnungen@kartonfix.example",
                      "DE129988776", "VR-Bank Landshut", "DE" + "70020270" + "0659912210", "HYVEDEMMXXX", "HRB 8812 AG Landshut"),
        "Wollweber": ("Wollweber Textildruck GmbH", "Weender Landstraße 3 · 37073 Göttingen", "buchhaltung@wollweber-textil.example",
                      "DE277665544", "Sparkasse Göttingen", "DE" + "26050001" + "0058812271", "NOLADE21GOE", "HRB 2290 AG Göttingen"),
        "DHL": ("DHL Paket GmbH", "Sträßchensweg 10 · 53113 Bonn", "Geschäftskundenservice", "DE169838187", "", "", "", "HRB 20869 AG Bonn"),
        "Google": ("Google Ireland Limited", "Gordon House, Barrow Street · Dublin 4 · Irland", "ads-billing", "IE6388047V", "", "",
                   "", "Registered in Ireland No. 368047"),
    }[si.supplier]
    from sim import iban as mkiban
    ib = mkiban("DE", sup[5][2:]) if sup[5] else ""
    c = canvas.Canvas(str(path), pagesize=A4)
    W, H = A4
    y = H - 50
    c.setFont("Helvetica-Bold", 14)
    c.drawString(50, y, sup[0])
    c.setFont("Helvetica", 8)
    c.drawString(50, y - 12, sup[1])
    c.drawString(50, y - 22, sup[2])
    y -= 70
    c.setFont("Helvetica", 9)
    for ln in ["Ritzelwerk – Fahrradteile & Zubehör", "Inh. Jana Brenner e.K.", "Hasestraße 41", "49074 Osnabrück"]:
        c.drawString(50, y, ln)
        y -= 12
    y -= 20
    title = {"Google": "Rechnung (Google Ads)", "DHL": "Rechnung"}.get(si.supplier, "Rechnung")
    c.setFont("Helvetica-Bold", 13)
    c.drawString(50, y, title)
    c.setFont("Helvetica", 9)
    meta = [("Rechnungsnummer", si.no), ("Rechnungsdatum", si.d.strftime("%d.%m.%Y"))]
    if si.supplier == "VeloTrade":
        meta += [("Kundennummer", "40877"), ("Lieferschein", si.delivery_note), ("Lieferdatum", si.d.strftime("%d.%m.%Y"))]
    elif si.supplier == "Kartonfix":
        meta += [("Kunden-Nr.", "K-55120"), ("Lieferdatum", si.d.strftime("%d.%m.%Y"))]
    elif si.supplier == "Wollweber":
        meta += [("Ihre Bestellung", "Vereinsdruck RSG Osnabrück"), ("Lieferschein", si.delivery_note)]
    elif si.supplier == "DHL":
        meta += [("Kundennummer (EKP)", "6312345678"), ("Abrechnungszeitraum", si.period)]
    elif si.supplier == "Google":
        meta += [("Konto", "412-889-2071"), ("Abrechnungszeitraum", si.period)]
    yy = y - 18
    for k_, v_ in meta:
        c.drawString(50, yy, f"{k_}:")
        c.drawString(170, yy, str(v_))
        yy -= 12
    y = yy - 14
    c.setFont("Helvetica-Bold", 8.5)
    c.drawString(50, y, "Pos.")
    c.drawString(80, y, "Art.-Nr.")
    c.drawString(160, y, "Bezeichnung")
    c.drawRightString(410, y, "Menge")
    c.drawRightString(480, y, "EP netto")
    c.drawRightString(545, y, "Gesamt netto")
    c.setFont("Helvetica", 8.5)
    y -= 13
    for i, (sku, desc, q, u) in enumerate(si.lines, 1):
        if y < 120:
            c.showPage()
            y = H - 60
            c.setFont("Helvetica", 8.5)
        c.drawString(50, y, str(i))
        c.drawString(80, y, sku)
        c.drawString(160, y, desc[:48])
        c.drawRightString(410, y, str(q))
        c.drawRightString(480, y, mde_t(u))
        c.drawRightString(545, y, mde_t(q * u))
        y -= 12
    y -= 8
    c.line(380, y + 6, 545, y + 6)
    c.drawString(380, y - 4, "Nettobetrag")
    c.drawRightString(545, y - 4, mde_t(si.net) + " €")
    if si.supplier == "Google":
        c.drawString(380, y - 16, "USt 0 % (Reverse Charge)")
        c.drawRightString(545, y - 16, "0,00 €")
    else:
        c.drawString(380, y - 16, "zzgl. 19 % USt")
        c.drawRightString(545, y - 16, mde_t(si.vat) + " €")
    c.setFont("Helvetica-Bold", 9)
    c.drawString(380, y - 30, "Rechnungsbetrag")
    c.drawRightString(545, y - 30, mde_t(si.gross) + " €")
    c.setFont("Helvetica", 8.5)
    y -= 56
    if si.supplier == "VeloTrade":
        sk = si.gross - round(si.gross * 0.02)
        terms = [f"Zahlbar bis {si.due:%d.%m.%Y} ohne Abzug oder bis {si.skonto_until:%d.%m.%Y} mit 2 % Skonto "
                 f"(Zahlbetrag {mde_t(sk)} €)."]
    elif si.supplier in ("Kartonfix", "Wollweber"):
        terms = [f"Zahlbar innerhalb von {(si.due - si.d).days} Tagen ohne Abzug bis {si.due:%d.%m.%Y}."]
    elif si.supplier == "DHL":
        terms = [f"Der Rechnungsbetrag wird am {si.due:%d.%m.%Y} per SEPA-Lastschrift von Ihrem Konto",
                 f"{OWN_IBAN[:4]} **** **** **** {OWN_IBAN[-4:]} eingezogen (Mandat 6312345678-001)."]
    else:
        terms = ["Steuerschuldnerschaft des Leistungsempfängers (Reverse Charge).",
                 f"Der Betrag wird automatisch per SEPA-Lastschrift belastet (ca. {si.due:%d.%m.%Y})."]
    for t in terms:
        c.drawString(50, y, t)
        y -= 12
    if ib:
        c.drawString(50, y - 6, f"Bankverbindung: {sup[4]} · IBAN {' '.join(ib[i:i + 4] for i in range(0, len(ib), 4))} · BIC {sup[6]}")
    c.setFont("Helvetica", 7)
    c.drawString(50, 40, f"{sup[0]} · {sup[7]} · USt-IdNr. {sup[3]}")
    c.save()


def xrechnung(si) -> bytes:
    from sim import iban as mkiban
    ib = mkiban("DE", "26050001" + "0058812271")
    lines = []
    for i, (sku, desc, q, u) in enumerate(si.lines, 1):
        lines.append(f"""  <cac:InvoiceLine>
    <cbc:ID>{i}</cbc:ID>
    <cbc:InvoicedQuantity unitCode="H87">{q}</cbc:InvoicedQuantity>
    <cbc:LineExtensionAmount currencyID="EUR">{q * u / 100:.2f}</cbc:LineExtensionAmount>
    <cac:Item>
      <cbc:Name>{desc}</cbc:Name>
      <cac:BuyersItemIdentification><cbc:ID>{sku}</cbc:ID></cac:BuyersItemIdentification>
      <cac:ClassifiedTaxCategory><cbc:ID>S</cbc:ID><cbc:Percent>19</cbc:Percent><cac:TaxScheme><cbc:ID>VAT</cbc:ID></cac:TaxScheme></cac:ClassifiedTaxCategory>
    </cac:Item>
    <cac:Price><cbc:PriceAmount currencyID="EUR">{u / 100:.2f}</cbc:PriceAmount></cac:Price>
  </cac:InvoiceLine>""")
    xml = f"""<?xml version="1.0" encoding="UTF-8"?>
<ubl:Invoice xmlns:ubl="urn:oasis:names:specification:ubl:schema:xsd:Invoice-2"
  xmlns:cac="urn:oasis:names:specification:ubl:schema:xsd:CommonAggregateComponents-2"
  xmlns:cbc="urn:oasis:names:specification:ubl:schema:xsd:CommonBasicComponents-2">
  <cbc:CustomizationID>urn:cen.eu:en16931:2017#compliant#urn:xeinkauf.de:kosit:xrechnung_3.0</cbc:CustomizationID>
  <cbc:ProfileID>urn:fdc:peppol.eu:2017:poacc:billing:01:1.0</cbc:ProfileID>
  <cbc:ID>{si.no}</cbc:ID>
  <cbc:IssueDate>{si.d.isoformat()}</cbc:IssueDate>
  <cbc:DueDate>{si.due.isoformat()}</cbc:DueDate>
  <cbc:InvoiceTypeCode>380</cbc:InvoiceTypeCode>
  <cbc:DocumentCurrencyCode>EUR</cbc:DocumentCurrencyCode>
  <cbc:BuyerReference>RITZELWERK-01</cbc:BuyerReference>
  <cac:AccountingSupplierParty><cac:Party>
    <cbc:EndpointID schemeID="EM">buchhaltung@wollweber-textil.example</cbc:EndpointID>
    <cac:PostalAddress><cbc:StreetName>Weender Landstraße 3</cbc:StreetName><cbc:CityName>Göttingen</cbc:CityName><cbc:PostalZone>37073</cbc:PostalZone><cac:Country><cbc:IdentificationCode>DE</cbc:IdentificationCode></cac:Country></cac:PostalAddress>
    <cac:PartyTaxScheme><cbc:CompanyID>DE277665544</cbc:CompanyID><cac:TaxScheme><cbc:ID>VAT</cbc:ID></cac:TaxScheme></cac:PartyTaxScheme>
    <cac:PartyLegalEntity><cbc:RegistrationName>Wollweber Textildruck GmbH</cbc:RegistrationName></cac:PartyLegalEntity>
  </cac:Party></cac:AccountingSupplierParty>
  <cac:AccountingCustomerParty><cac:Party>
    <cbc:EndpointID schemeID="EM">info@ritzelwerk.example</cbc:EndpointID>
    <cac:PostalAddress><cbc:StreetName>Hasestraße 41</cbc:StreetName><cbc:CityName>Osnabrück</cbc:CityName><cbc:PostalZone>49074</cbc:PostalZone><cac:Country><cbc:IdentificationCode>DE</cbc:IdentificationCode></cac:Country></cac:PostalAddress>
    <cac:PartyTaxScheme><cbc:CompanyID>{FIRM['vat_id']}</cbc:CompanyID><cac:TaxScheme><cbc:ID>VAT</cbc:ID></cac:TaxScheme></cac:PartyTaxScheme>
    <cac:PartyLegalEntity><cbc:RegistrationName>Ritzelwerk – Fahrradteile &amp; Zubehör, Inh. Jana Brenner e.K.</cbc:RegistrationName></cac:PartyLegalEntity>
  </cac:Party></cac:AccountingCustomerParty>
  <cac:PaymentMeans><cbc:PaymentMeansCode>58</cbc:PaymentMeansCode><cac:PayeeFinancialAccount><cbc:ID>{ib}</cbc:ID></cac:PayeeFinancialAccount></cac:PaymentMeans>
  <cac:PaymentTerms><cbc:Note>Zahlbar innerhalb von 30 Tagen ohne Abzug.</cbc:Note></cac:PaymentTerms>
  <cac:TaxTotal>
    <cbc:TaxAmount currencyID="EUR">{si.vat / 100:.2f}</cbc:TaxAmount>
    <cac:TaxSubtotal><cbc:TaxableAmount currencyID="EUR">{si.net / 100:.2f}</cbc:TaxableAmount><cbc:TaxAmount currencyID="EUR">{si.vat / 100:.2f}</cbc:TaxAmount>
      <cac:TaxCategory><cbc:ID>S</cbc:ID><cbc:Percent>19</cbc:Percent><cac:TaxScheme><cbc:ID>VAT</cbc:ID></cac:TaxScheme></cac:TaxCategory></cac:TaxSubtotal>
  </cac:TaxTotal>
  <cac:LegalMonetaryTotal>
    <cbc:LineExtensionAmount currencyID="EUR">{si.net / 100:.2f}</cbc:LineExtensionAmount>
    <cbc:TaxExclusiveAmount currencyID="EUR">{si.net / 100:.2f}</cbc:TaxExclusiveAmount>
    <cbc:TaxInclusiveAmount currencyID="EUR">{si.gross / 100:.2f}</cbc:TaxInclusiveAmount>
    <cbc:PayableAmount currencyID="EUR">{si.gross / 100:.2f}</cbc:PayableAmount>
  </cac:LegalMonetaryTotal>
{chr(10).join(lines)}
</ubl:Invoice>
"""
    return xml.encode("utf-8")


# ================================================================================================ mails
def eml(mail, attachments=None) -> bytes:
    msg = EmailMessage()
    msg["From"] = mail.sender
    msg["To"] = mail.to
    msg["Subject"] = mail.subject
    msg["Date"] = format_datetime(mail.when.replace(tzinfo=BERLIN))
    msg["Message-ID"] = mail.msgid or make_msgid(domain=mail.sender.split("@")[-1].strip(">"))
    if mail.reply_to_msgid:
        msg["In-Reply-To"] = mail.reply_to_msgid
        msg["References"] = mail.reply_to_msgid
    msg.set_content(mail.body)
    if mail.html:
        msg.add_alternative("<html><body>" + "".join(f"<p>{p}</p>" for p in mail.body.split("\n\n")) + "</body></html>",
                            subtype="html")
    for fname, data, mime in attachments or []:
        maintype, subtype = mime.split("/")
        msg.add_attachment(data, maintype=maintype, subtype=subtype, filename=fname)
    return bytes(msg)
