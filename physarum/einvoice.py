"""E-invoices (XRechnung / ZUGFeRD / Factur-X): structured anchors.

Since 2025 every German business must be able to receive e-invoices. They are exact:
number, dates, supplier, VAT id, bank account, totals and lines. Both syntaxes are read:
UBL (urn:oasis:...:Invoice-2) and UN/CEFACT CII (CrossIndustryInvoice), also when the XML
is embedded in a PDF (ZUGFeRD/Factur-X). The result is one header table and one line table
whose structure is known, so nothing has to be guessed.
"""
from __future__ import annotations

from datetime import date

from .values import fmt_eur


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _find(el, path: list[str]):
    """Namespace-agnostic path lookup: ['AccountingSupplierParty', 'Party', 'PartyName', 'Name']."""
    cur = [el]
    for name in path:
        nxt = []
        for c in cur:
            nxt.extend(x for x in c if _local(x.tag) == name)
        if not nxt:
            return None
        cur = nxt
    return cur[0]


def _findall(el, name: str):
    return [x for x in el.iter() if _local(x.tag) == name]


def _text(el, path: list[str]) -> str | None:
    x = _find(el, path)
    return x.text.strip() if x is not None and x.text and x.text.strip() else None


def _num(s):
    try:
        return float(s) if s is not None else None
    except ValueError:
        return None


def _date(s):
    if not s:
        return None
    s = s.strip()
    try:
        if len(s) == 8 and s.isdigit():
            return date(int(s[:4]), int(s[4:6]), int(s[6:]))
        return date.fromisoformat(s[:10])
    except ValueError:
        return None


def parse(root) -> dict | None:
    kind = _local(root.tag)
    if kind == "Invoice" or kind == "CreditNote":
        return _ubl(root, credit=kind == "CreditNote")
    if kind == "CrossIndustryInvoice":
        return _cii(root)
    return None


def _ubl_subtotals(r) -> list[dict]:
    out = []
    for tt in [x for x in r if _local(x.tag) == "TaxTotal"]:
        for st in [x for x in tt if _local(x.tag) == "TaxSubtotal"]:
            out.append(dict(base=_num(_text(st, ["TaxableAmount"])), tax=_num(_text(st, ["TaxAmount"])),
                            rate=_num(_text(st, ["TaxCategory", "Percent"])), category=_text(st, ["TaxCategory", "ID"])))
    return out


def _ubl_tax_ids(r, party: list[str]) -> tuple[str | None, str | None]:
    """(USt-IdNr, Steuernummer) of a party: the tax scheme says which is which."""
    vat = tax_no = None
    p = _find(r, party)
    for ts in ([x for x in p if _local(x.tag) == "PartyTaxScheme"] if p is not None else []):
        cid, scheme = _text(ts, ["CompanyID"]), (_text(ts, ["TaxScheme", "ID"]) or "").upper()
        if scheme == "VAT" and not vat:
            vat = cid
        elif cid and not tax_no:
            tax_no = cid
    return vat, tax_no


def _ubl(r, credit=False) -> dict:
    sup = ["AccountingSupplierParty", "Party"]
    cus = ["AccountingCustomerParty", "Party"]
    vat, tax_no = _ubl_tax_ids(r, sup)
    tot = ["LegalMonetaryTotal"]
    lines = []
    for ln in [x for x in r if _local(x.tag) in ("InvoiceLine", "CreditNoteLine")]:
        q = _find(ln, ["InvoicedQuantity"])
        if q is None:
            q = _find(ln, ["CreditedQuantity"])
        lines.append(dict(pos=_text(ln, ["ID"]), name=_text(ln, ["Item", "Name"]) or _text(ln, ["Item", "Description"]),
                          qty=_num(q.text if q is not None else None), unit=q.get("unitCode") if q is not None else None,
                          price=_num(_text(ln, ["Price", "PriceAmount"])),
                          per=_num(_text(ln, ["Price", "BaseQuantity"])),
                          total=_num(_text(ln, ["LineExtensionAmount"])),
                          discounted=any(_local(x.tag) == "AllowanceCharge" for x in ln),
                          sku=_text(ln, ["Item", "SellersItemIdentification", "ID"])))
    return dict(
        number=_text(r, ["ID"]), date=_date(_text(r, ["IssueDate"])),
        due=_date(_text(r, ["DueDate"]) or _text(r, ["PaymentMeans", "PaymentDueDate"])),
        seller=_text(r, sup + ["PartyLegalEntity", "RegistrationName"]) or _text(r, sup + ["PartyName", "Name"]),
        seller_vat=vat or tax_no, seller_tax_no=tax_no,
        seller_mail=_text(r, sup + ["Contact", "ElectronicMail"]),
        buyer=_text(r, cus + ["PartyLegalEntity", "RegistrationName"]) or _text(r, cus + ["PartyName", "Name"]),
        iban=_text(r, ["PaymentMeans", "PayeeFinancialAccount", "ID"]),
        order=_text(r, ["OrderReference", "ID"]),
        net=_num(_text(r, tot + ["TaxExclusiveAmount"])),
        tax=_num(_text(r, ["TaxTotal", "TaxAmount"])),
        gross=_num(_text(r, tot + ["PayableAmount"]) or _text(r, tot + ["TaxInclusiveAmount"])),
        totals=dict(lines=_num(_text(r, tot + ["LineExtensionAmount"])), allowances=_num(_text(r, tot + ["AllowanceTotalAmount"])),
                    charges=_num(_text(r, tot + ["ChargeTotalAmount"])), inclusive=_num(_text(r, tot + ["TaxInclusiveAmount"])),
                    prepaid=_num(_text(r, tot + ["PrepaidAmount"])), rounding=_num(_text(r, tot + ["PayableRoundingAmount"])),
                    payable=_num(_text(r, tot + ["PayableAmount"]))),
        subtotals=_ubl_subtotals(r),
        currency=_text(r, ["DocumentCurrencyCode"]) or "EUR", credit=credit, syntax="UBL", lines=lines)


def _cii(r) -> dict:
    doc = _find(r, ["ExchangedDocument"])
    tr = _find(r, ["SupplyChainTradeTransaction"])
    agr = _find(tr, ["ApplicableHeaderTradeAgreement"]) if tr is not None else None
    stl = _find(tr, ["ApplicableHeaderTradeSettlement"]) if tr is not None else None
    lines = []
    for ln in _findall(r, "IncludedSupplyChainTradeLineItem"):
        q = _find(ln, ["SpecifiedLineTradeDelivery", "BilledQuantity"])
        lines.append(dict(pos=_text(ln, ["AssociatedDocumentLineDocument", "LineID"]),
                          name=_text(ln, ["SpecifiedTradeProduct", "Name"]),
                          qty=_num(q.text if q is not None else None), unit=q.get("unitCode") if q is not None else None,
                          price=_num(_text(ln, ["SpecifiedLineTradeAgreement", "NetPriceProductTradePrice", "ChargeAmount"])),
                          per=_num(_text(ln, ["SpecifiedLineTradeAgreement", "NetPriceProductTradePrice", "BasisQuantity"])),
                          total=_num(_text(ln, ["SpecifiedLineTradeSettlement",
                                                "SpecifiedTradeSettlementLineMonetarySummation", "LineTotalAmount"])),
                          discounted=_find(ln, ["SpecifiedLineTradeSettlement", "SpecifiedTradeAllowanceCharge"]) is not None,
                          sku=_text(ln, ["SpecifiedTradeProduct", "SellerAssignedID"])))
    summ = ["SpecifiedTradeSettlementHeaderMonetarySummation"]
    type_code = _text(doc, ["TypeCode"]) if doc is not None else None
    vat = tax_no = None
    seller = _find(agr, ["SellerTradeParty"]) if agr is not None else None
    for reg in ([x for x in seller if _local(x.tag) == "SpecifiedTaxRegistration"] if seller is not None else []):
        rid = _find(reg, ["ID"])
        scheme = (rid.get("schemeID") or "").upper() if rid is not None else ""
        val = rid.text.strip() if rid is not None and rid.text else None
        if scheme == "VA" and not vat:
            vat = val
        elif val and not tax_no:
            tax_no = val
    subtotals = []
    for tt in ([x for x in stl if _local(x.tag) == "ApplicableTradeTax"] if stl is not None else []):
        subtotals.append(dict(base=_num(_text(tt, ["BasisAmount"])), tax=_num(_text(tt, ["CalculatedAmount"])),
                              rate=_num(_text(tt, ["RateApplicablePercent"])), category=_text(tt, ["CategoryCode"])))

    def total(name):
        return _num(_text(stl, summ + [name])) if stl is not None else None
    return dict(
        number=_text(doc, ["ID"]) if doc is not None else None,
        date=_date(_text(doc, ["IssueDateTime", "DateTimeString"])) if doc is not None else None,
        due=_date(_text(stl, ["SpecifiedTradePaymentTerms", "DueDateDateTime", "DateTimeString"])) if stl is not None else None,
        seller=_text(agr, ["SellerTradeParty", "Name"]) if agr is not None else None,
        seller_vat=vat or tax_no, seller_tax_no=tax_no,
        seller_mail=_text(agr, ["SellerTradeParty", "URIUniversalCommunication", "URIID"]) if agr is not None else None,
        buyer=_text(agr, ["BuyerTradeParty", "Name"]) if agr is not None else None,
        iban=_text(stl, ["SpecifiedTradeSettlementPaymentMeans", "PayeePartyCreditorFinancialAccount", "IBANID"]) if stl is not None else None,
        order=_text(agr, ["BuyerOrderReferencedDocument", "IssuerAssignedID"]) if agr is not None else None,
        net=_num(_text(stl, summ + ["TaxBasisTotalAmount"])) if stl is not None else None,
        tax=_num(_text(stl, summ + ["TaxTotalAmount"])) if stl is not None else None,
        gross=_num(_text(stl, summ + ["DuePayableAmount"]) or _text(stl, summ + ["GrandTotalAmount"])) if stl is not None else None,
        totals=dict(lines=total("LineTotalAmount"), allowances=total("AllowanceTotalAmount"), charges=total("ChargeTotalAmount"),
                    inclusive=total("GrandTotalAmount"), prepaid=total("TotalPrepaidAmount"), rounding=total("RoundingAmount"),
                    payable=total("DuePayableAmount")),
        subtotals=subtotals,
        currency=_text(stl, ["InvoiceCurrencyCode"]) if stl is not None else "EUR", credit=type_code == "381",
        syntax="CII", lines=lines)


def check(inv: dict) -> list[str]:
    """What does not add up in a received e-invoice (the EN 16931 calculation rules a reader can check
    without a schema) and what § 14 UStG requires that is missing. Every finding is a sentence."""
    out = []
    tol = 0.011
    tot = inv.get("totals") or {}
    lines = [ln.get("total") for ln in inv.get("lines") or [] if ln.get("total") is not None]
    if lines and tot.get("lines") is not None and abs(sum(lines) - tot["lines"]) > tol:
        out.append(f"Die Positionen ergeben {fmt_eur(sum(lines))}, die Rechnung nennt {fmt_eur(tot['lines'])} als Summe")
    for ln in inv.get("lines") or []:
        if None in (ln.get("qty"), ln.get("price"), ln.get("total")) or ln.get("discounted"):
            continue
        per = ln.get("per") or 1.0  # a price per 100 pieces
        if abs(ln["qty"] * ln["price"] / per - ln["total"]) > max(tol, abs(ln["total"]) * 0.0005):
            out.append(f"Position {ln.get('pos') or '?'}: {ln['qty']:g} × {fmt_eur(ln['price'])}"
                       f"{'' if per == 1 else f' je {per:g}'} sind nicht {fmt_eur(ln['total'])}")
            break
    base = tot.get("lines")
    if base is not None and inv.get("net") is not None:
        want = base - (tot.get("allowances") or 0.0) + (tot.get("charges") or 0.0)
        if abs(want - inv["net"]) > tol:
            out.append(f"Netto {fmt_eur(inv['net'])} passt nicht zu den Positionen abzüglich Rabatten ({fmt_eur(want)})")
    incl = tot.get("inclusive")
    if incl is not None and inv.get("net") is not None and inv.get("tax") is not None and abs(inv["net"] + inv["tax"] - incl) > tol:
        out.append(f"Netto {fmt_eur(inv['net'])} plus Umsatzsteuer {fmt_eur(inv['tax'])} sind nicht {fmt_eur(incl)}")
    if incl is not None and tot.get("payable") is not None:
        want = incl - (tot.get("prepaid") or 0.0) + (tot.get("rounding") or 0.0)
        if abs(want - tot["payable"]) > tol:
            out.append(f"Zu zahlen sind {fmt_eur(tot['payable'])}, nach Brutto und Anzahlungen wären es {fmt_eur(want)}")
    subs = inv.get("subtotals") or []
    for st in subs:
        if None not in (st.get("base"), st.get("rate"), st.get("tax")) and abs(st["base"] * st["rate"] / 100 - st["tax"]) > 0.015:
            out.append(f"{st['rate']:g} % von {fmt_eur(st['base'])} sind nicht {fmt_eur(st['tax'])} Umsatzsteuer")
    if subs and inv.get("tax") is not None and all(st.get("tax") is not None for st in subs) and \
            abs(sum(st["tax"] for st in subs) - inv["tax"]) > tol:
        out.append(f"Die Steuer je Satz ergibt {fmt_eur(sum(st['tax'] for st in subs))}, die Rechnung nennt {fmt_eur(inv['tax'])}")
    for key, label in (("number", "Rechnungsnummer"), ("date", "Rechnungsdatum"), ("seller", "Name des Lieferanten"),
                       ("buyer", "Empfänger"), ("gross", "Betrag")):
        if inv.get(key) in (None, ""):
            out.append(f"{label} fehlt")
    if not inv.get("seller_vat") and not inv.get("seller_tax_no"):
        out.append("Weder USt-IdNr. noch Steuernummer des Lieferanten (§ 14 Abs. 4 UStG) – kein Vorsteuerabzug")
    return out


HEADER_COLS = ["Rechnungsnr", "Rechnungsdatum", "Fällig am", "Lieferant", "USt-IdNr", "IBAN", "Bestellung", "Netto",
               "MwSt", "Brutto", "Art"]
LINE_COLS = ["Rechnungsnr", "Pos", "Art.-Nr.", "Bezeichnung", "Menge", "Einheit", "Einzelpreis", "Gesamt"]


def to_tables(inv: dict, source_name: str):
    """(header RawTable, line RawTable, RawDoc) for one e-invoice."""
    from .ingest import RawDoc, RawTable

    sign = -1 if inv.get("credit") else 1
    art = "Gutschrift" if inv.get("credit") else "Rechnung"
    head = RawTable(name="Eingangsrechnungen (E-Rechnung)", columns=list(HEADER_COLS),
                    rows=[[inv["number"], inv["date"], inv["due"], inv["seller"], inv["seller_vat"], inv["iban"],
                           inv["order"], _s(inv["net"], sign), _s(inv["tax"], sign), _s(inv["gross"], sign), art]],
                    lines=[1], meta={"format": f"E-Rechnung ({inv['syntax']})", "structured": "einvoice-header",
                                     "number_formats": {}})
    rows = []
    for i, ln in enumerate(inv["lines"], start=1):
        rows.append([inv["number"], ln.get("pos") or str(i), ln.get("sku"), ln.get("name"), ln.get("qty"),
                     ln.get("unit"), ln.get("price"), _s(ln.get("total"), sign)])
    lines = RawTable(name="Eingangsrechnungspositionen (E-Rechnung)", columns=list(LINE_COLS), rows=rows,
                     lines=list(range(1, len(rows) + 1)),
                     meta={"format": f"E-Rechnung ({inv['syntax']})", "structured": "einvoice-lines",
                           "parent_table": "Eingangsrechnungen (E-Rechnung)", "parent_key": "Rechnungsnr",
                           "number_formats": {}})
    text = (f"E-Rechnung {inv['number']} von {inv['seller']} vom {inv['date']}\n"
            f"Betrag: {inv['gross']} {inv['currency']}\nIBAN: {inv['iban'] or '–'}\nBestellung: {inv['order'] or '–'}")
    doc = RawDoc("e-rechnung", f"E-Rechnung {inv['number']} · {inv['seller']}", text,
                 sender=inv.get("seller_mail") or inv.get("seller"),
                 meta={"syntax": inv["syntax"], "problems": check(inv), "buyer": inv.get("buyer")})
    return head, lines if rows else None, doc


def _s(x, sign):
    return None if x is None else round(sign * x, 2)


# --- writing: outgoing invoices as XRechnung (UBL) --------------------------------------------------

def _x(s) -> str:
    from xml.sax.saxutils import escape
    return escape(str(s if s is not None else ""))


def _dec(x):
    from decimal import Decimal
    return Decimal(str(x if x is not None else 0))


def _amt(x) -> str:
    from decimal import ROUND_HALF_UP, Decimal
    return str(_dec(x).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def _qty(x) -> str:
    q = _dec(x).normalize()
    return format(q, "f")  # never "1e+06"


def _el(tag: str, value, attrs: str = "") -> str:
    """An element only when there is something to say – XRechnung forbids empty ones."""
    if value is None or str(value).strip() == "":
        return ""
    return f"<{tag}{(' ' + attrs) if attrs else ''}>{_x(str(value).strip())}</{tag}>"


def _unit(u) -> str:
    u = fold_unit(u)
    return {"kg": "KGM", "g": "GRM", "l": "LTR", "liter": "LTR", "stk": "H87", "stueck": "H87", "st": "H87",
            "h": "HUR", "std": "HUR", "stunde": "HUR", "stunden": "HUR", "m": "MTR", "m2": "MTK", "qm": "MTK",
            "pauschal": "LS", "pausch": "LS", "psch": "LS", "karton": "XCT", "kt": "XCT", "sack": "XSA",
            "saecke": "XSA", "beutel": "XBG", "dose": "XCX", "flasche": "XBO", "paket": "XPK", "rolle": "XRO",
            "tag": "DAY", "tage": "DAY", "km": "KMT"}.get(u, "C62")


def fold_unit(u) -> str:
    from .text import fold
    return fold(str(u or "")).strip(". ")


def _vat_id(v) -> str | None:
    return "".join(str(v).split()).upper() if v else None


def xrechnung_problems(inv: dict) -> list[str]:
    """What the XRechnung rules require and the data does not have (checked before anything is written)."""
    s, b = inv.get("seller") or {}, inv.get("buyer") or {}
    out = []
    need_s = [("name", "Firmenname"), ("street", "Straße (Ihre)"), ("zip", "PLZ (Ihre)"), ("city", "Ort (Ihr)"),
              ("email", "E-Mail-Adresse (Ihre, BT-34/BT-43)"), ("phone", "Telefon (Ihres, BT-42)"), ("iban", "IBAN (BT-84)")]
    out += [label for k, label in need_s if not s.get(k)]
    if not s.get("vat_id") and not s.get("tax_no"):
        out.append("USt-IdNr. oder Steuernummer (Ihre)")
    if not b.get("name"):
        out.append("Name des Kunden")
    if not b.get("zip") or not b.get("city"):
        out.append("PLZ und Ort des Kunden")
    if not b.get("email"):
        out.append("E-Mail-Adresse des Kunden (elektronische Adresse, BT-49)")
    if not inv.get("positions"):
        out.append("Positionen")
    if not (inv.get("delivery") or inv.get("delivery_end")):
        out.append("Leistungsdatum")
    if not inv.get("number"):
        out.append("Rechnungsnummer")
    return out


def to_xrechnung(inv: dict) -> str:
    """An issued invoice as XRechnung 3.0 (UBL 2.1, EN 16931). `inv` is the invoice as issued:
    number, date, due, delivery (or period), seller and buyer, positions (text, qty, unit, price,
    total, rate), and the tax note for 0 % (category E, AE, K or G)."""
    s, b = inv["seller"] or {}, inv["buyer"] or {}
    pos = inv.get("positions") or []
    from decimal import Decimal
    groups: dict = {}
    for p in pos:
        r = _dec(p.get("rate") if p.get("rate") is not None else 0)
        r = r / 100 if r > 1 else r
        groups.setdefault(r, Decimal(0))
        groups[r] += _dec(_amt(p.get("total")))
    zero_cat = inv.get("tax_category") or "Z"
    reason = inv.get("tax_note")

    def cat(r):
        return "S" if r > 0 else zero_cat

    def pct(r):
        return format((r * 100).quantize(Decimal("0.01")).normalize(), "f")

    def tax_of(r, n):
        from decimal import ROUND_HALF_UP
        return (n * r).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

    net = sum(groups.values(), Decimal(0))
    tax = sum((tax_of(r, n) for r, n in groups.items()), Decimal(0))

    def addr(p, country_default="DE"):
        return ("<cac:PostalAddress>" + _el("cbc:StreetName", p.get("street")) + _el("cbc:CityName", p.get("city")) +
                _el("cbc:PostalZone", p.get("zip")) + "<cac:Country><cbc:IdentificationCode>" +
                _x((p.get("country") or country_default).upper()[:2]) + "</cbc:IdentificationCode></cac:Country></cac:PostalAddress>")

    lines = []
    for i, p in enumerate(pos, start=1):
        qty = _dec(p.get("qty") if p.get("qty") is not None else 1)
        price = _dec(p.get("price") if p.get("price") is not None else p.get("total"))
        total = _dec(_amt(p.get("total") if p.get("total") is not None else qty * price))
        if price < 0:  # BR-27: no negative price – a discount is a negative quantity
            price, qty = -price, -qty
        r = _dec(p.get("rate") if p.get("rate") is not None else 0)
        r = r / 100 if r > 1 else r
        lines.append(
            f"""  <cac:InvoiceLine>
    <cbc:ID>{i}</cbc:ID>
    <cbc:InvoicedQuantity unitCode="{_unit(p.get('unit'))}">{_qty(qty)}</cbc:InvoicedQuantity>
    <cbc:LineExtensionAmount currencyID="EUR">{_amt(total)}</cbc:LineExtensionAmount>
    <cac:Item>{_el("cbc:Name", p.get('text') or "Position")}{f"<cac:SellersItemIdentification><cbc:ID>{_x(p['sku'])}</cbc:ID></cac:SellersItemIdentification>" if p.get('sku') else ""}
      <cac:ClassifiedTaxCategory><cbc:ID>{cat(r)}</cbc:ID><cbc:Percent>{pct(r)}</cbc:Percent><cac:TaxScheme><cbc:ID>VAT</cbc:ID></cac:TaxScheme></cac:ClassifiedTaxCategory></cac:Item>
    <cac:Price><cbc:PriceAmount currencyID="EUR">{_amt(price)}</cbc:PriceAmount></cac:Price>
  </cac:InvoiceLine>""")
    subtotals = "".join(
        f"<cac:TaxSubtotal><cbc:TaxableAmount currencyID=\"EUR\">{_amt(n)}</cbc:TaxableAmount>"
        f"<cbc:TaxAmount currencyID=\"EUR\">{_amt(tax_of(r, n))}</cbc:TaxAmount><cac:TaxCategory><cbc:ID>{cat(r)}</cbc:ID>"
        f"<cbc:Percent>{pct(r)}</cbc:Percent>"
        + (_el("cbc:TaxExemptionReason", reason or "Steuerfrei") if r == 0 and cat(r) != "Z" else "")
        + "<cac:TaxScheme><cbc:ID>VAT</cbc:ID></cac:TaxScheme></cac:TaxCategory></cac:TaxSubtotal>"
        for r, n in sorted(groups.items()))
    ref = (f"<cac:BillingReference><cac:InvoiceDocumentReference>{_el('cbc:ID', inv['corrects'])}"
           f"{_el('cbc:IssueDate', inv.get('corrects_date'))}</cac:InvoiceDocumentReference></cac:BillingReference>") \
        if inv.get("corrects") else ""
    vat = _vat_id(s.get("vat_id"))
    seller_tax = (f"<cac:PartyTaxScheme><cbc:CompanyID>{_x(vat)}</cbc:CompanyID><cac:TaxScheme><cbc:ID>VAT</cbc:ID>"
                  f"</cac:TaxScheme></cac:PartyTaxScheme>") if vat else ""
    seller_fc = (f"<cac:PartyTaxScheme><cbc:CompanyID>{_x(s.get('tax_no'))}</cbc:CompanyID><cac:TaxScheme><cbc:ID>FC</cbc:ID>"
                 f"</cac:TaxScheme></cac:PartyTaxScheme>") if s.get("tax_no") else ""
    # BR-CO-26: a seller identifier, the register entry or the VAT id must be there
    seller_ident = "" if (vat or s.get("register")) else \
        (f"<cac:PartyIdentification><cbc:ID>{_x(s.get('tax_no'))}</cbc:ID></cac:PartyIdentification>" if s.get("tax_no") else "")
    bvat = _vat_id(b.get("vat_id"))
    period = (f"<cac:InvoicePeriod>{_el('cbc:StartDate', inv.get('delivery'))}{_el('cbc:EndDate', inv.get('delivery_end'))}</cac:InvoicePeriod>"
              if inv.get("delivery_end") else "")
    when = _el("cbc:ActualDeliveryDate", inv.get("delivery")) if inv.get("delivery") and not inv.get("delivery_end") else ""
    # BR-IC-12: an intra-community supply names the country it goes to
    where = (f"<cac:DeliveryLocation><cac:Address><cac:Country><cbc:IdentificationCode>{_x((b.get('country') or 'DE')[:2])}"
             f"</cbc:IdentificationCode></cac:Country></cac:Address></cac:DeliveryLocation>") if zero_cat == "K" else ""
    delivery = f"<cac:Delivery>{when}{where}</cac:Delivery>" if when or where else ""
    buyer_ref = b.get("leitweg") or b.get("number") or inv.get("order") or b.get("name")
    notes = _el("cbc:Note", reason) if reason else ""
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<ubl:Invoice xmlns:ubl="urn:oasis:names:specification:ubl:schema:xsd:Invoice-2"
 xmlns:cac="urn:oasis:names:specification:ubl:schema:xsd:CommonAggregateComponents-2"
 xmlns:cbc="urn:oasis:names:specification:ubl:schema:xsd:CommonBasicComponents-2">
  <cbc:CustomizationID>urn:cen.eu:en16931:2017#compliant#urn:xeinkauf.de:kosit:xrechnung_3.0</cbc:CustomizationID>
  <cbc:ProfileID>urn:fdc:peppol.eu:2017:poacc:billing:01:1.0</cbc:ProfileID>
  <cbc:ID>{_x(inv['number'])}</cbc:ID>
  <cbc:IssueDate>{inv['date']}</cbc:IssueDate>
  {_el("cbc:DueDate", inv.get('due'))}
  <cbc:InvoiceTypeCode>380</cbc:InvoiceTypeCode>
  {notes}
  <cbc:DocumentCurrencyCode>EUR</cbc:DocumentCurrencyCode>
  {_el("cbc:BuyerReference", buyer_ref)}
  {period}
  {f"<cac:OrderReference><cbc:ID>{_x(inv['order'])}</cbc:ID></cac:OrderReference>" if inv.get('order') else ""}
  {ref}
  <cac:AccountingSupplierParty><cac:Party>
    {_el("cbc:EndpointID", s.get('email'), 'schemeID="EM"')}
    {seller_ident}
    <cac:PartyName>{_el("cbc:Name", s.get('name'))}</cac:PartyName>
    {addr(s)}
    {seller_tax}{seller_fc}
    <cac:PartyLegalEntity>{_el("cbc:RegistrationName", s.get('name'))}{_el("cbc:CompanyID", s.get('register'))}</cac:PartyLegalEntity>
    <cac:Contact>{_el("cbc:Name", s.get('manager') or s.get('name'))}{_el("cbc:Telephone", s.get('phone'))}{_el("cbc:ElectronicMail", s.get('email'))}</cac:Contact>
  </cac:Party></cac:AccountingSupplierParty>
  <cac:AccountingCustomerParty><cac:Party>
    {_el("cbc:EndpointID", b.get('email'), 'schemeID="EM"')}
    {addr(b)}
    {f"<cac:PartyTaxScheme><cbc:CompanyID>{_x(bvat)}</cbc:CompanyID><cac:TaxScheme><cbc:ID>VAT</cbc:ID></cac:TaxScheme></cac:PartyTaxScheme>" if bvat else ""}
    <cac:PartyLegalEntity>{_el("cbc:RegistrationName", b.get('name'))}</cac:PartyLegalEntity>
  </cac:Party></cac:AccountingCustomerParty>
  {delivery}
  <cac:PaymentMeans><cbc:PaymentMeansCode>58</cbc:PaymentMeansCode>
    <cac:PayeeFinancialAccount>{_el("cbc:ID", (s.get('iban') or '').replace(' ', ''))}{f"<cac:FinancialInstitutionBranch><cbc:ID>{_x(s['bic'])}</cbc:ID></cac:FinancialInstitutionBranch>" if s.get('bic') else ""}</cac:PayeeFinancialAccount></cac:PaymentMeans>
  {f"<cac:PaymentTerms>{_el('cbc:Note', inv['terms'])}</cac:PaymentTerms>" if inv.get('terms') else ""}
  <cac:TaxTotal><cbc:TaxAmount currencyID="EUR">{_amt(tax)}</cbc:TaxAmount>{subtotals}</cac:TaxTotal>
  <cac:LegalMonetaryTotal>
    <cbc:LineExtensionAmount currencyID="EUR">{_amt(net)}</cbc:LineExtensionAmount>
    <cbc:TaxExclusiveAmount currencyID="EUR">{_amt(net)}</cbc:TaxExclusiveAmount>
    <cbc:TaxInclusiveAmount currencyID="EUR">{_amt(net + tax)}</cbc:TaxInclusiveAmount>
    <cbc:PayableAmount currencyID="EUR">{_amt(net + tax)}</cbc:PayableAmount>
  </cac:LegalMonetaryTotal>
{chr(10).join(lines)}
</ubl:Invoice>
"""
