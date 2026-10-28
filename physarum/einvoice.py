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
        q = _find(ln, ["InvoicedQuantity"]) or _find(ln, ["CreditedQuantity"])
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
