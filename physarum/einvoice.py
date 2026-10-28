"""E-invoices (XRechnung / ZUGFeRD / Factur-X): structured anchors.

Since 2025 every German business must be able to receive e-invoices. They are exact:
number, dates, supplier, VAT id, bank account, totals and lines. Both syntaxes are read:
UBL (urn:oasis:...:Invoice-2) and UN/CEFACT CII (CrossIndustryInvoice), also when the XML
is embedded in a PDF (ZUGFeRD/Factur-X). The result is one header table and one line table
whose structure is known, so nothing has to be guessed.
"""
from __future__ import annotations

from datetime import date


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


def _ubl(r, credit=False) -> dict:
    sup = ["AccountingSupplierParty", "Party"]
    cus = ["AccountingCustomerParty", "Party"]
    lines = []
    for ln in [x for x in r if _local(x.tag) in ("InvoiceLine", "CreditNoteLine")]:
        q = _find(ln, ["InvoicedQuantity"])
        if q is None:
            q = _find(ln, ["CreditedQuantity"])
        lines.append(dict(pos=_text(ln, ["ID"]), name=_text(ln, ["Item", "Name"]) or _text(ln, ["Item", "Description"]),
                          qty=_num(q.text if q is not None else None), unit=q.get("unitCode") if q is not None else None,
                          price=_num(_text(ln, ["Price", "PriceAmount"])),
                          total=_num(_text(ln, ["LineExtensionAmount"])),
                          sku=_text(ln, ["Item", "SellersItemIdentification", "ID"])))
    return dict(
        number=_text(r, ["ID"]), date=_date(_text(r, ["IssueDate"])),
        due=_date(_text(r, ["DueDate"]) or _text(r, ["PaymentMeans", "PaymentDueDate"])),
        seller=_text(r, sup + ["PartyLegalEntity", "RegistrationName"]) or _text(r, sup + ["PartyName", "Name"]),
        seller_vat=_text(r, sup + ["PartyTaxScheme", "CompanyID"]),
        seller_mail=_text(r, sup + ["Contact", "ElectronicMail"]),
        buyer=_text(r, cus + ["PartyLegalEntity", "RegistrationName"]) or _text(r, cus + ["PartyName", "Name"]),
        iban=_text(r, ["PaymentMeans", "PayeeFinancialAccount", "ID"]),
        order=_text(r, ["OrderReference", "ID"]),
        net=_num(_text(r, ["LegalMonetaryTotal", "TaxExclusiveAmount"])),
        tax=_num(_text(r, ["TaxTotal", "TaxAmount"])),
        gross=_num(_text(r, ["LegalMonetaryTotal", "PayableAmount"]) or _text(r, ["LegalMonetaryTotal", "TaxInclusiveAmount"])),
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
                          total=_num(_text(ln, ["SpecifiedLineTradeSettlement",
                                                "SpecifiedTradeSettlementLineMonetarySummation", "LineTotalAmount"])),
                          sku=_text(ln, ["SpecifiedTradeProduct", "SellerAssignedID"])))
    summ = ["SpecifiedTradeSettlementHeaderMonetarySummation"]
    type_code = _text(doc, ["TypeCode"]) if doc is not None else None
    return dict(
        number=_text(doc, ["ID"]) if doc is not None else None,
        date=_date(_text(doc, ["IssueDateTime", "DateTimeString"])) if doc is not None else None,
        due=_date(_text(stl, ["SpecifiedTradePaymentTerms", "DueDateDateTime", "DateTimeString"])) if stl is not None else None,
        seller=_text(agr, ["SellerTradeParty", "Name"]) if agr is not None else None,
        seller_vat=_text(agr, ["SellerTradeParty", "SpecifiedTaxRegistration", "ID"]) if agr is not None else None,
        seller_mail=_text(agr, ["SellerTradeParty", "URIUniversalCommunication", "URIID"]) if agr is not None else None,
        buyer=_text(agr, ["BuyerTradeParty", "Name"]) if agr is not None else None,
        iban=_text(stl, ["SpecifiedTradeSettlementPaymentMeans", "PayeePartyCreditorFinancialAccount", "IBANID"]) if stl is not None else None,
        order=_text(agr, ["BuyerOrderReferencedDocument", "IssuerAssignedID"]) if agr is not None else None,
        net=_num(_text(stl, summ + ["TaxBasisTotalAmount"])) if stl is not None else None,
        tax=_num(_text(stl, summ + ["TaxTotalAmount"])) if stl is not None else None,
        gross=_num(_text(stl, summ + ["DuePayableAmount"]) or _text(stl, summ + ["GrandTotalAmount"])) if stl is not None else None,
        currency=_text(stl, ["InvoiceCurrencyCode"]) if stl is not None else "EUR", credit=type_code == "381",
        syntax="CII", lines=lines)


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
                 sender=inv.get("seller_mail") or inv.get("seller"), meta={"syntax": inv["syntax"]})
    return head, lines if rows else None, doc


def _s(x, sign):
    return None if x is None else round(sign * x, 2)


# --- writing: outgoing invoices as XRechnung (UBL) --------------------------------------------------

def _x(s) -> str:
    from xml.sax.saxutils import escape
    return escape(str(s if s is not None else ""))


def _amt(x) -> str:
    return f"{float(x or 0):.2f}"


def _unit(u) -> str:
    u = fold_unit(u)
    return {"kg": "KGM", "g": "GRM", "l": "LTR", "stk": "H87", "stueck": "H87", "h": "HUR", "std": "HUR",
            "m": "MTR", "pauschal": "LS", "karton": "CT", "sack": "SA"}.get(u, "C62")


def fold_unit(u) -> str:
    from .text import fold
    return fold(str(u or "")).strip(". ")


def to_xrechnung(inv: dict) -> str:
    """An issued invoice as XRechnung 3.0 (UBL 2.1, EN 16931). `inv` carries number, date, due,
    delivery, seller and buyer (dicts), positions (text, qty, unit, price, total, rate) and the
    totals by VAT rate."""
    s, b = inv["seller"], inv["buyer"]
    groups = inv["groups"]
    net = round(sum(g["net"] for g in groups), 2)
    tax = round(sum(g["tax"] for g in groups), 2)
    code = "384" if inv.get("corrects") else "380"

    def pct(r):
        x = r * 100 if r is not None and r <= 1 else (r or 0)
        return f"{x:.2f}".rstrip("0").rstrip(".")

    def addr(p):
        return (f"<cac:PostalAddress><cbc:StreetName>{_x(p.get('street'))}</cbc:StreetName>"
                f"<cbc:CityName>{_x(p.get('city'))}</cbc:CityName><cbc:PostalZone>{_x(p.get('zip'))}</cbc:PostalZone>"
                f"<cac:Country><cbc:IdentificationCode>DE</cbc:IdentificationCode></cac:Country></cac:PostalAddress>")

    lines = []
    for i, p in enumerate(inv["positions"], start=1):
        qty = p.get("qty") if p.get("qty") is not None else 1
        total = p.get("total") if p.get("total") is not None else round((p.get("price") or 0) * qty, 2)
        price = p.get("price") if p.get("price") is not None else (round(total / qty, 4) if qty else total)
        lines.append(
            f"""  <cac:InvoiceLine>
    <cbc:ID>{i}</cbc:ID>
    <cbc:InvoicedQuantity unitCode="{_unit(p.get('unit'))}">{qty:g}</cbc:InvoicedQuantity>
    <cbc:LineExtensionAmount currencyID="EUR">{_amt(total)}</cbc:LineExtensionAmount>
    <cac:Item><cbc:Name>{_x(p.get('text'))}</cbc:Name>{f"<cac:SellersItemIdentification><cbc:ID>{_x(p['sku'])}</cbc:ID></cac:SellersItemIdentification>" if p.get('sku') else ""}
      <cac:ClassifiedTaxCategory><cbc:ID>S</cbc:ID><cbc:Percent>{pct(p.get('rate'))}</cbc:Percent><cac:TaxScheme><cbc:ID>VAT</cbc:ID></cac:TaxScheme></cac:ClassifiedTaxCategory></cac:Item>
    <cac:Price><cbc:PriceAmount currencyID="EUR">{_amt(price)}</cbc:PriceAmount></cac:Price>
  </cac:InvoiceLine>""")
    subtotals = "".join(
        f"<cac:TaxSubtotal><cbc:TaxableAmount currencyID=\"EUR\">{_amt(g['net'])}</cbc:TaxableAmount>"
        f"<cbc:TaxAmount currencyID=\"EUR\">{_amt(g['tax'])}</cbc:TaxAmount><cac:TaxCategory><cbc:ID>S</cbc:ID>"
        f"<cbc:Percent>{pct(g['rate'])}</cbc:Percent><cac:TaxScheme><cbc:ID>VAT</cbc:ID></cac:TaxScheme></cac:TaxCategory>"
        f"</cac:TaxSubtotal>" for g in groups)
    ref = (f"<cac:BillingReference><cac:InvoiceDocumentReference><cbc:ID>{_x(inv['corrects'])}</cbc:ID>"
           f"</cac:InvoiceDocumentReference></cac:BillingReference>") if inv.get("corrects") else ""
    seller_tax = (f"<cac:PartyTaxScheme><cbc:CompanyID>{_x(s.get('vat_id'))}</cbc:CompanyID><cac:TaxScheme><cbc:ID>VAT</cbc:ID>"
                  f"</cac:TaxScheme></cac:PartyTaxScheme>") if s.get("vat_id") else ""
    seller_fc = (f"<cac:PartyTaxScheme><cbc:CompanyID>{_x(s.get('tax_no'))}</cbc:CompanyID><cac:TaxScheme><cbc:ID>FC</cbc:ID>"
                 f"</cac:TaxScheme></cac:PartyTaxScheme>") if s.get("tax_no") else ""
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<ubl:Invoice xmlns:ubl="urn:oasis:names:specification:ubl:schema:xsd:Invoice-2"
 xmlns:cac="urn:oasis:names:specification:ubl:schema:xsd:CommonAggregateComponents-2"
 xmlns:cbc="urn:oasis:names:specification:ubl:schema:xsd:CommonBasicComponents-2">
  <cbc:CustomizationID>urn:cen.eu:en16931:2017#compliant#urn:xeinkauf.de:kosit:xrechnung_3.0</cbc:CustomizationID>
  <cbc:ProfileID>urn:fdc:peppol.eu:2017:poacc:billing:01:1.0</cbc:ProfileID>
  <cbc:ID>{_x(inv['number'])}</cbc:ID>
  <cbc:IssueDate>{inv['date']}</cbc:IssueDate>
  {f"<cbc:DueDate>{inv['due']}</cbc:DueDate>" if inv.get('due') else ""}
  <cbc:InvoiceTypeCode>{code}</cbc:InvoiceTypeCode>
  <cbc:DocumentCurrencyCode>EUR</cbc:DocumentCurrencyCode>
  <cbc:BuyerReference>{_x(b.get('number') or b.get('name'))}</cbc:BuyerReference>
  {f"<cac:OrderReference><cbc:ID>{_x(inv['order'])}</cbc:ID></cac:OrderReference>" if inv.get('order') else ""}
  {ref}
  <cac:AccountingSupplierParty><cac:Party>
    <cbc:EndpointID schemeID="EM">{_x(s.get('email'))}</cbc:EndpointID>
    <cac:PartyName><cbc:Name>{_x(s.get('name'))}</cbc:Name></cac:PartyName>
    {addr(s)}
    {seller_tax}{seller_fc}
    <cac:PartyLegalEntity><cbc:RegistrationName>{_x(s.get('name'))}</cbc:RegistrationName></cac:PartyLegalEntity>
    <cac:Contact><cbc:Name>{_x(s.get('manager') or s.get('name'))}</cbc:Name><cbc:Telephone>{_x(s.get('phone'))}</cbc:Telephone><cbc:ElectronicMail>{_x(s.get('email'))}</cbc:ElectronicMail></cac:Contact>
  </cac:Party></cac:AccountingSupplierParty>
  <cac:AccountingCustomerParty><cac:Party>
    <cbc:EndpointID schemeID="EM">{_x(b.get('email') or s.get('email'))}</cbc:EndpointID>
    {addr(b)}
    {f"<cac:PartyTaxScheme><cbc:CompanyID>{_x(b['vat_id'])}</cbc:CompanyID><cac:TaxScheme><cbc:ID>VAT</cbc:ID></cac:TaxScheme></cac:PartyTaxScheme>" if b.get('vat_id') else ""}
    <cac:PartyLegalEntity><cbc:RegistrationName>{_x(b.get('name'))}</cbc:RegistrationName></cac:PartyLegalEntity>
  </cac:Party></cac:AccountingCustomerParty>
  {f"<cac:Delivery><cbc:ActualDeliveryDate>{inv['delivery']}</cbc:ActualDeliveryDate></cac:Delivery>" if inv.get('delivery') else ""}
  <cac:PaymentMeans><cbc:PaymentMeansCode>58</cbc:PaymentMeansCode>
    <cac:PayeeFinancialAccount><cbc:ID>{_x((s.get('iban') or '').replace(' ', ''))}</cbc:ID>{f"<cac:FinancialInstitutionBranch><cbc:ID>{_x(s['bic'])}</cbc:ID></cac:FinancialInstitutionBranch>" if s.get('bic') else ""}</cac:PayeeFinancialAccount></cac:PaymentMeans>
  {f"<cac:PaymentTerms><cbc:Note>{_x(inv['terms'])}</cbc:Note></cac:PaymentTerms>" if inv.get('terms') else ""}
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
