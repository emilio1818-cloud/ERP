"""For the tax advisor: one ZIP per month, quarter or year with what a Steuerberatung asks for.

* The outgoing invoices as a DATEV Buchungsstapel (EXTF): one booking per invoice and VAT rate,
  debtor against the automatic revenue account of SKR03 or SKR04 – DATEV computes the tax itself.
  Incoming invoices are not booked: which expense account they belong to is the advisor's call;
  they come as a readable list with their documents.
* Both invoice books as CSV for Excel, VAT per rate and input tax, the open items.
* The documents: invoices issued here exactly as archived, suppliers' invoices as they came in.
* A protocol: what to check, a checksum of every file, the seal of the change log.

Accounts are the standard ones; the protocol asks to agree them with the advisor once.
"""
from __future__ import annotations

import csv
import hashlib
import io
import re
import zipfile
from datetime import date, datetime, timedelta

from . import billing
from .payments import _payable_attrs
from .store import loads, now_iso
from .text import norm_name
from .values import as_date, as_number

DEFAULTS = dict(berater=1001, mandant=1, skr="03", method="soll", fy_start=1)

# revenue accounts with automatic VAT (19 %, 7 %) and for the tax-free cases
ACCOUNTS = {
    "03": {0.19: "8400", 0.07: "8300", "kleinunternehmer": "8195", "13b": "8337", "eu": "8125", "ausfuhr": "8120",
           "steuerfrei": "8100", 0.0: "8200"},
    "04": {0.19: "4400", 0.07: "4300", "kleinunternehmer": "4185", "13b": "4337", "eu": "4125", "ausfuhr": "4120",
           "steuerfrei": "4100", 0.0: "4200"},
}
DEBITOR_START, KREDITOR_START = 10000, 70000

# DATEV-Format Buchungsstapel, format version 9 (Versionsnummer 700): 116 fields per booking
FIELDS = (
    ["Umsatz (ohne Soll/Haben-Kz)", "Soll/Haben-Kennzeichen", "WKZ Umsatz", "Kurs", "Basis-Umsatz", "WKZ Basis-Umsatz",
     "Konto", "Gegenkonto (ohne BU-Schlüssel)", "BU-Schlüssel", "Belegdatum", "Belegfeld 1", "Belegfeld 2", "Skonto",
     "Buchungstext", "Postensperre", "Diverse Adressnummer", "Geschäftspartnerbank", "Sachverhalt", "Zinssperre",
     "Beleglink"]
    + [x for i in range(1, 9) for x in (f"Beleginfo - Art {i}", f"Beleginfo - Inhalt {i}")]
    + ["KOST1 - Kostenstelle", "KOST2 - Kostenstelle", "Kost-Menge", "EU-Land u. UStID", "EU-Steuersatz",
       "Abw. Versteuerungsart", "Sachverhalt L+L", "Funktionsergänzung L+L", "BU 49 Hauptfunktionstyp",
       "BU 49 Hauptfunktionsnummer", "BU 49 Funktionsergänzung"]
    + [x for i in range(1, 21) for x in (f"Zusatzinformation - Art {i}", f"Zusatzinformation- Inhalt {i}")]
    + ["Stück", "Gewicht", "Zahlweise", "Forderungsart", "Veranlagungsjahr", "Zugeordnete Fälligkeit", "Skontotyp",
       "Auftragsnummer", "Buchungstyp", "USt-Schlüssel (Anzahlungen)", "EU-Land (Anzahlungen)",
       "Sachverhalt L+L (Anzahlungen)", "EU-Steuersatz (Anzahlungen)", "Erlöskonto (Anzahlungen)", "Herkunft-Kz",
       "Buchungs GUID", "KOST-Datum", "SEPA-Mandatsreferenz", "Skontosperre", "Gesellschaftername",
       "Beteiligtennummer", "Identifikationsnummer", "Zeichnernummer", "Postensperre bis",
       "Bezeichnung SoBil-Sachverhalt", "Kennzeichen SoBil-Buchung", "Festschreibung", "Leistungsdatum",
       "Datum Zuord. Steuerperiode"]
)
_BELEG_OK = re.compile(r"[^A-Za-z0-9$&%*+\-/]")  # what DATEV accepts in "Belegfeld 1"


def settings(store) -> dict:
    return {**DEFAULTS, **from_advisor(store), **(store.kv_get("tax_advisor") or {})}


def advisor_reports(store) -> list[dict]:
    """The tax advisor's own exports that were dropped in (DATEV Buchungsstapel, open items), newest first."""
    out = []
    for t in store.q("SELECT meta, source_id FROM raw_tables ORDER BY id DESC"):
        meta = loads(t["meta"]) or {}
        if meta.get("report") in ("DATEV-Buchungsstapel", "Offene-Posten-Liste"):
            out.append(meta)
    return out


def from_advisor(store) -> dict:
    """Advisor and client number, chart of accounts: as the advisor's own DATEV export says them."""
    out = {}
    for meta in advisor_reports(store):
        h = meta.get("datev") or {}
        if h.get("berater") and "berater" not in out:
            out["berater"] = int(h["berater"])
        if h.get("mandant") and "mandant" not in out:
            out["mandant"] = int(h["mandant"])
        if h.get("wj_beginn") and len(h["wj_beginn"]) == 8 and "fy_start" not in out:
            out["fy_start"] = int(h["wj_beginn"][4:6])
    return out


def advisor_accounts(store) -> dict[str, int]:
    """{invoice number: debtor account} as the advisor books them."""
    out: dict[str, int] = {}
    for meta in reversed(advisor_reports(store)):  # the newest report has the last word
        for no, acc in (meta.get("accounts") or {}).items():
            if str(acc).isdigit():
                out[str(no).strip().casefold()] = int(acc)
    return out


def save_settings(store, form: dict) -> dict:
    cfg = settings(store)
    for k in ("berater", "mandant", "fy_start"):
        try:
            cfg[k] = int(str(form.get(k) or cfg[k]).strip())
        except ValueError:
            pass
    if form.get("skr") in ACCOUNTS:
        cfg["skr"] = form["skr"]
    if form.get("method") in ("soll", "ist"):
        cfg["method"] = form["method"]
    cfg["fy_start"] = min(12, max(1, cfg["fy_start"]))
    store.kv_set("tax_advisor", cfg)
    return cfg


def period(kind: str, year: int, n: int = 1) -> tuple[date, date, str]:
    """('monat', 2026, 10) -> 1.10.–31.10.2026, '10/2026'."""
    if kind == "jahr":
        return date(year, 1, 1), date(year, 12, 31), str(year)
    if kind == "quartal":
        n = min(4, max(1, n))
        von = date(year, 3 * n - 2, 1)
        bis = (date(year + (n == 4), 1 if n == 4 else 3 * n + 1, 1)) - timedelta(days=1)
        return von, bis, f"Q{n}/{year}"
    n = min(12, max(1, n))
    von = date(year, n, 1)
    bis = date(year + (n == 12), 1 if n == 12 else n + 1, 1) - timedelta(days=1)
    return von, bis, f"{n:02d}/{year}"


def _rate(r) -> float | None:
    if r is None:
        return None
    for std in (0.19, 0.07, 0.0, 0.16, 0.05):
        if abs(float(r) - std) < 0.004:
            return std
    return None


def _de(x: float | None) -> str:
    return "" if x is None else f"{x:.2f}".replace(".", ",")


def _numbers(store, key: str) -> dict:
    """Debtor and creditor numbers stay the same from one export to the next. A partner is its record, or –
    a supplier that is only a name on its invoice – "n:" and the name."""
    return {(int(k) if str(k).isdigit() else str(k)): v for k, v in (store.kv_get(key) or {}).items()
            if str(k) not in ("None", "")}


def _partner_key(rid, name: str):
    return rid if isinstance(rid, int) else "n:" + (norm_name(name) or "?")


def _assign(mapping: dict, rid, own: str | None, start: int, end: int) -> int:
    if rid in mapping:
        return mapping[rid]
    if own and str(own).isdigit() and start <= int(own) < end and int(own) not in mapping.values():
        mapping[rid] = int(own)  # the firm's own customer number fits the debtor range: keep it
        return mapping[rid]
    n = max([v for v in mapping.values() if start <= v < end], default=start - 1) + 1
    mapping[rid] = n
    return n


def collect(rt, von: date, bis: date, cfg: dict | None = None) -> dict:
    """Everything the export contains, computed once (the page shows a preview of it)."""
    rt.ensure()
    store = rt.store
    cfg = cfg or settings(store)
    acc = ACCOUNTS[cfg["skr"]]
    debitors = _numbers(store, "datev_debitors")
    kreditors = _numbers(store, "datev_kreditors")
    theirs = advisor_accounts(store)
    out, inc, warn, copies = [], [], [], []
    vat_out: dict = {}
    vat_in: dict = {}
    for spec in rt.model["types"]:
        if spec.get("concept") != "rechnung" or not spec.get("key"):
            continue
        incoming = bool(spec.get("incoming"))
        party = billing.party_attr(rt, spec)
        if party is None and incoming:  # a supplier known only by the name its invoices give
            from .reconcile import _incoming
            party = next((pa for t, pa, *_ in _incoming(rt.model) if t["id"] == spec["id"]), None)
        proc = next((p for p in rt.model.get("processes", []) if p["type"] == spec["id"]), None)
        dattr = proc["start"]["attr"] if proc else next((a["id"] for a in spec["attrs"] if a["kind"] == "date"), None)
        payable, deduct = _payable_attrs(spec, proc or {})
        for rec in rt.active_records().get(spec["id"], []):
            if billing.is_draft(rec):
                continue
            meta = rec.get("meta") or {}
            when = (as_date(rec["data"].get(dattr)) if dattr else None) or as_date((meta.get("issued") or "")[:10])
            if not when or not (von <= when <= bis):
                continue
            doc = billing.document(rt, rec)
            pv = rec["data"].get(party["id"]) if party else None
            name = rt.title(pv) if isinstance(pv, int) else str(pv or ((rec.get("meta") or {}).get("raw") or {}).get(
                party["id"] if party else "", "") or "")  # a supplier known by its written name is still named
            e = rt.ledger.get(rec["id"]) or {}
            row = dict(rid=rec["id"], number=str(doc.get("number") or rt.title(rec["id"])), date=when, party=name,
                       party_rid=pv if isinstance(pv, int) else None, groups=[], gross=doc.get("gross"),
                       net=doc.get("net"), tax=doc.get("tax"), state=e.get("state"), open=e.get("open"),
                       paid_date=e.get("paid_date"), corrects=doc.get("corrects"), issued=bool(doc.get("issued")),
                       delivery=as_date(doc.get("delivery")), payments=e.get("payments") or [])
            if not incoming and not (meta.get("issued") or meta.get("storno_of")):
                # written in another program, copied from its book: booked there, not twice from here
                row["groups"] = [dict(rate=_rate(g.get("rate")), net=g.get("net") or 0.0, tax=g.get("tax") or 0.0)
                                 for g in doc.get("groups") or []]
                row["account"] = ""
                copies.append(row)
                continue
            if not name:
                warn.append(f"{row['number']}: ohne {'Lieferant' if incoming else 'Kunde'}")
            for g in doc.get("groups") or []:
                r = _rate(g.get("rate"))
                if r is None:
                    warn.append(f"{row['number']}: Steuersatz {g.get('rate')!r} nicht eindeutig – bitte prüfen")
                row["groups"].append(dict(rate=r, net=g.get("net") or 0.0, tax=g.get("tax") or 0.0))
            if not row["groups"] and row["gross"] is not None:
                warn.append(f"{row['number']}: ohne Netto/USt – nur der Bruttobetrag ist bekannt")
                row["groups"].append(dict(rate=None, net=row["gross"], tax=0.0))
            owed = as_number(rec["data"].get(payable)) if payable else None
            if owed is None and deduct and as_number(rec["data"].get(deduct)):
                owed = round((row["gross"] or 0) - abs(as_number(rec["data"].get(deduct))), 2)
            if row["gross"] and owed is not None and 0 <= owed < row["gross"] - 0.005:
                share = owed / row["gross"]  # the down payments were booked with their own invoices
                for g in row["groups"]:
                    g["net"], g["tax"] = round(g["net"] * share, 2), round(g["tax"] * share, 2)
                row["after_down_payments"] = owed
            if incoming:
                row["account"] = _assign(kreditors, _partner_key(row["party_rid"], name), None, KREDITOR_START, 100000)
                if any(g["rate"] == 0.0 and g["net"] for g in row["groups"]):
                    warn.append(f"{row['number']}: ohne Umsatzsteuer – bei § 13b schulden Sie die Steuer (Reverse Charge), "
                                f"sonst Kleinunternehmer oder steuerfrei; bitte prüfen")
                inc.append(row)
                for g in row["groups"]:
                    v = vat_in.setdefault(g["rate"], [0.0, 0.0])
                    v[0] += g["net"]
                    v[1] += g["tax"]
                continue
            own_no = None
            if row["party_rid"]:
                cs = rt.spec(rt.by_id[row["party_rid"]]["type"])
                own_no = rt.by_id[row["party_rid"]]["data"].get(cs.get("key")) if cs and cs.get("key") else None
            known = theirs.get(row["number"].strip().casefold())
            if known and row["party_rid"] and DEBITOR_START <= known < KREDITOR_START and \
                    debitors.get(row["party_rid"]) != known and known not in debitors.values():
                debitors[row["party_rid"]] = known  # the advisor's debtor number for this customer
            row["account"] = _assign(debitors, _partner_key(row["party_rid"], name), own_no, DEBITOR_START, KREDITOR_START)
            code = (rec.get("meta") or {}).get("tax_category") or ""
            for g in row["groups"]:
                if g["rate"] == 0.0:
                    # why there is no VAT, as written on the invoice when it was issued (UNCL 5305 code)
                    kind = {"AE": "13b", "K": "eu", "G": "ausfuhr", "E": "steuerfrei"}.get(code)
                    if billing.company(store).get("kleinunternehmer"):
                        kind = "kleinunternehmer"
                    g["account"] = acc.get(kind or 0.0)
                    if not kind and g["net"]:
                        warn.append(f"{row['number']}: 0 % ohne Grund (§ 13b, § 19, EU, Ausfuhr?) – "
                                    f"gebucht auf {g['account']}, bitte prüfen")
                else:
                    g["account"] = acc.get(g["rate"]) if g["rate"] is not None else None
                    if not g["account"] and g["rate"] is not None:
                        warn.append(f"{row['number']}: für {_pct(g['rate'])} gibt es kein Automatikkonto – "
                                    f"nicht im Buchungsstapel, bitte von Hand buchen")
                v = vat_out.setdefault(g["rate"], [0.0, 0.0])
                v[0] += g["net"]
                v[1] += g["tax"]
            out.append(row)
    out.sort(key=lambda x: (x["date"], x["number"]))
    inc.sort(key=lambda x: (x["date"], x["number"]))
    # cash accounting: the VAT of the money that came in during the period
    vat_ist: dict = {}
    if cfg["method"] == "ist":
        for spec in rt.model["types"]:
            if spec.get("concept") != "rechnung" or spec.get("incoming"):
                continue
            for rec in rt.active_records().get(spec["id"], []):
                e = rt.ledger.get(rec["id"])
                m = rec.get("meta") or {}
                if not e or not e.get("gross") or not (m.get("issued") or m.get("storno_of")):
                    continue
                got = sum(p["amount"] for p in e.get("payments") or [] if p.get("date") and von <= as_date(p["date"]) <= bis)
                if not got:
                    continue
                share = got / e["gross"]
                for g in billing.document(rt, rec).get("groups") or []:
                    v = vat_ist.setdefault(_rate(g.get("rate")), [0.0, 0.0])
                    v[0] += (g.get("net") or 0.0) * share
                    v[1] += (g.get("tax") or 0.0) * share
    # sales that are no invoice here (a web shop's orders): named, so nobody thinks they are in
    elsewhere = []
    for spec in rt.model["types"]:
        if spec.get("concept") not in ("bestellung", "kassenbeleg", "beleg") or spec["kind"] != "transaction":
            continue
        mf = billing.money_fields(spec)
        proc = next((p for p in rt.model.get("processes", []) if p["type"] == spec["id"]), None)
        dattr = proc["start"]["attr"] if proc else next((a["id"] for a in spec["attrs"] if a["kind"] in ("date", "datetime")), None)
        money = mf["gross"] or mf["net"]
        if not dattr or not money:
            continue
        rs = [r for r in rt.active_records().get(spec["id"], []) if (d := as_date(r["data"].get(dattr))) and von <= d <= bis]
        if rs:
            elsewhere.append(dict(plural=spec["plural"], n=len(rs),
                                  amount=round(sum(r["data"].get(money["id"]) or 0 for r in rs
                                                   if isinstance(r["data"].get(money["id"]), (int, float))), 2)))
    store.kv_set("datev_debitors", {str(k): v for k, v in debitors.items()})
    store.kv_set("datev_kreditors", {str(k): v for k, v in kreditors.items()})
    return dict(von=von, bis=bis, out=out, inc=inc, warnings=warn, vat_out=vat_out, vat_in=vat_in, vat_ist=vat_ist,
                cfg=cfg, debitors=debitors, kreditors=kreditors, elsewhere=elsewhere, copies=copies)


def extf(data: dict, label: str, now: datetime | None = None) -> bytes:
    """The DATEV Buchungsstapel: header record, column names, one line per invoice and rate (Windows-1252)."""
    cfg = data["cfg"]
    now = now or datetime.now()
    fy = date(data["von"].year if data["von"].month >= cfg["fy_start"] else data["von"].year - 1, cfg["fy_start"], 1)
    head = ['"EXTF"', "700", "21", '"Buchungsstapel"', "9", now.strftime("%Y%m%d%H%M%S") + f"{now.microsecond // 1000:03d}",
            "", '"RE"', '""', '""', str(cfg["berater"]), str(cfg["mandant"]), fy.strftime("%Y%m%d"), "4",
            data["von"].strftime("%Y%m%d"), data["bis"].strftime("%Y%m%d"), f'"Ausgangsrechnungen {label}"', '""',
            "1", "0", "0", '"EUR"', "", '""', "", "", f'"{cfg["skr"]}"', "", "", '""', '""']
    buf = io.StringIO()
    buf.write(";".join(head) + "\r\n")
    buf.write(";".join(FIELDS) + "\r\n")
    for r in data["out"]:
        for g in r["groups"]:
            gross = round(g["net"] + g["tax"], 2)
            if not gross or not g.get("account"):
                continue
            sh = "H" if gross < 0 else "S"  # a cancellation or credit note is the same booking the other way round
            row = [""] * len(FIELDS)
            row[0] = _de(abs(gross))
            row[1] = f'"{sh}"'
            row[2] = '"EUR"'
            row[6] = str(r["account"])
            row[7] = str(g["account"])
            row[9] = r["date"].strftime("%d%m")
            row[10] = f'"{_BELEG_OK.sub("-", r["number"])[:36]}"'
            row[13] = '"' + (r["party"] or "").replace('"', "'")[:60] + '"'
            if r.get("delivery"):
                row[FIELDS.index("Leistungsdatum")] = r["delivery"].strftime("%d%m%Y")
            row[FIELDS.index("Festschreibung")] = "0"
            buf.write(";".join(row) + "\r\n")
    return buf.getvalue().encode("cp1252", "replace")


def _csv(rows: list[list]) -> bytes:
    """A CSV Excel opens correctly: semicolons, decimal commas, UTF-8 with BOM; no cell starts a formula."""
    buf = io.StringIO()
    w = csv.writer(buf, delimiter=";", lineterminator="\r\n")
    for r in rows:
        w.writerow([("'" + c) if isinstance(c, str) and c[:1] in ("=", "+", "-", "@") and not _is_number(c) else c
                    for c in r])
    return ("﻿" + buf.getvalue()).encode("utf-8")


def _is_number(s: str) -> bool:
    return bool(re.fullmatch(r"-?\d+(?:,\d+)?", s))


def _pct(r) -> str:
    return "?" if r is None else f"{round(r * 100):d} %"


def books(data: dict) -> dict[str, bytes]:
    both = sorted(data["out"] + data.get("copies", []), key=lambda x: (x["date"], x["number"]))
    rates = sorted({g["rate"] for r in both for g in r["groups"] if g["rate"] is not None}, reverse=True)
    head = ["Rechnungsnr.", "Datum", "Kunde", "Debitor"] + [x for rt in rates for x in (f"Netto {_pct(rt)}", f"USt {_pct(rt)}")] + \
        ["Brutto", "Zahlung", "bezahlt am", "offen", "korrigiert", "Herkunft"]
    rows = [head]
    for r in both:
        by = {g["rate"]: g for g in r["groups"]}
        rows.append([r["number"], r["date"].strftime("%d.%m.%Y"), r["party"], r["account"]]
                    + [x for rt in rates for x in (_de(by[rt]["net"]) if rt in by else "", _de(by[rt]["tax"]) if rt in by else "")]
                    + [_de(r["gross"]), r["state"] or "", _date(r["paid_date"]), _de(r["open"]), r["corrects"] or "",
                       "Physarum (im Buchungsstapel)" if r["account"] else "Datei (anderes Programm, nicht im Stapel)"])
    out = {"Rechnungsausgangsbuch.csv": _csv(rows)}
    rows = [["Rechnungsnr.", "Datum", "Lieferant", "Kreditor", "Netto", "USt", "USt-Satz", "Brutto", "Zahlung", "bezahlt am"]]
    for r in data["inc"]:
        rows.append([r["number"], r["date"].strftime("%d.%m.%Y"), r["party"], r["account"],
                     _de(sum(g["net"] for g in r["groups"])), _de(sum(g["tax"] for g in r["groups"])),
                     ", ".join(_pct(g["rate"]) for g in r["groups"]), _de(r["gross"]), r["state"] or "", _date(r["paid_date"])])
    out["Rechnungseingangsbuch.csv"] = _csv(rows)
    rows = [["", "Bemessungsgrundlage", "Steuer"]]
    for rt_, (n, t) in sorted(data["vat_out"].items(), key=lambda kv: -(kv[0] or -1)):
        rows.append([f"Umsätze {_pct(rt_)} (nach Rechnungsdatum)", _de(n), _de(t)])
    if data["vat_ist"]:
        for rt_, (n, t) in sorted(data["vat_ist"].items(), key=lambda kv: -(kv[0] or -1)):
            rows.append([f"Umsätze {_pct(rt_)} (nach Zahlungseingang, Ist-Versteuerung)", _de(n), _de(t)])
    for rt_, (n, t) in sorted(data["vat_in"].items(), key=lambda kv: -(kv[0] or -1)):
        rows.append([f"Vorsteuer aus Eingangsrechnungen {_pct(rt_)}" if rt_ else
                     "Eingangsrechnungen ohne Umsatzsteuer (§ 13b, Kleinunternehmer, steuerfrei – bitte prüfen)", _de(n), _de(t)])
    due = sum(t for _, t in (data["vat_ist"] if data["cfg"]["method"] == "ist" else data["vat_out"]).values()) - \
        sum(t for _, t in data["vat_in"].values())
    rows.append(["Vorläufige Zahllast (ohne Gewähr, ohne weitere Vorsteuer)", "", _de(due)])
    out["Umsatzsteuer.csv"] = _csv(rows)
    return out


def _date(v) -> str:
    d = as_date(v)
    return d.strftime("%d.%m.%Y") if d else ""


def open_items(rt) -> bytes:
    rows = [["Rechnungsnr.", "Datum", "Kunde", "Brutto", "bezahlt", "offen", "Zustand"]]
    for e in sorted(rt.ledger.values(), key=lambda e: (e.get("start") or date.min, e["rid"])):
        if e.get("outgoing") or e["state"] not in ("offen", "teilbezahlt") or e["open"] <= 0.005:
            continue
        rec = rt.by_id.get(e["rid"])
        spec = rt.spec(rec["type"]) if rec else None
        if not spec or spec.get("incoming"):
            continue
        party = billing.party_attr(rt, spec)
        pv = rec["data"].get(party["id"]) if party else None
        rows.append([rt.title(e["rid"]), _date(e.get("start")), rt.title(pv) if isinstance(pv, int) else "",
                     _de(e["gross"]), _de(e["paid"]), _de(e["open"]), rec["data"].get("pay_state") or e["state"]])
    return _csv(rows)


def partners(rt, data: dict) -> bytes:
    rows = [["Konto", "Art", "Name", "Straße", "PLZ", "Ort", "USt-IdNr.", "eigene Nummer"]]
    for kind, mapping in (("Debitor", data["debitors"]), ("Kreditor", data["kreditors"])):
        for rid, n in sorted(mapping.items(), key=lambda kv: kv[1]):
            if isinstance(rid, str):
                rows.append([n, kind, rid[2:], "", "", "", "", ""])  # known only by the name on its invoices
                continue
            if rid not in rt.by_id:
                continue
            r = billing.recipient(rt, rid)
            rows.append([n, kind, r.get("name") or "", r.get("street") or "", r.get("zip") or "", r.get("city") or "",
                         r.get("vat_id") or "", r.get("number") or ""])
    return _csv(rows)


def documents(rt, data: dict) -> dict[str, bytes]:
    """Invoices issued here as archived (HTML, XRechnung); suppliers' invoices as the file they came in."""
    out = {}
    store = rt.store
    for r in data["out"]:
        for a in store.q("SELECT name, content FROM archive WHERE record_id=?", (r["rid"],)):
            out[f"Belege/Ausgang/{a['name']}"] = bytes(a["content"])
    for r in data["inc"]:
        for frm, attr, kind, how in rt.backrefs.get(r["rid"], []):
            d = rt.by_id.get(frm)
            if not d or d["type"] != "doc" or not d["data"].get("doc_file"):
                continue
            name = d["data"]["doc_file"]
            src = store.q1("SELECT id, name FROM sources WHERE name=? ORDER BY id DESC", (name,))
            path = store.source_path(src["id"], src["name"]) if src else None
            if path and path.exists():
                out[f"Belege/Eingang/{_BELEG_OK.sub('_', r['number'])}_{path.name[6:]}"] = path.read_bytes()
    return out


def build(rt, von: date, bis: date, label: str, actor: str | None = None) -> tuple[bytes, dict]:
    data = collect(rt, von, bis)
    files: dict[str, bytes] = {}
    safe = label.replace("/", "-")
    files[f"EXTF_Buchungsstapel_Ausgangsrechnungen_{safe}.csv"] = extf(data, label)
    for name, content in books(data).items():
        files[name.replace(".csv", f"_{safe}.csv")] = content
    files[f"Offene_Posten_Stand_{date.today().isoformat()}.csv"] = open_items(rt)
    files[f"Debitoren_Kreditoren_{safe}.csv"] = partners(rt, data)
    files.update(documents(rt, data))
    with rt.store.tx():
        pass  # seals what is not sealed yet
    chain = rt.store.anchor_chain()  # the protocol hands the seal out: from now on the log can only grow
    lines = [f"Export für die Steuerberatung – Zeitraum {label} ({data['von'].strftime('%d.%m.%Y')} bis "
             f"{data['bis'].strftime('%d.%m.%Y')})",
             f"Erstellt am {datetime.now().strftime('%d.%m.%Y %H:%M')} von {actor or 'unbekannt'} mit Physarum.",
             "",
             f"Ausgangsrechnungen: {len(data['out'])}, Summe brutto {_de(sum(r['gross'] or 0 for r in data['out']))} €",
             f"Eingangsrechnungen: {len(data['inc'])}, Summe brutto {_de(sum(r['gross'] or 0 for r in data['inc']))} €",
             f"Kontenrahmen SKR{data['cfg']['skr']}, Berater {data['cfg']['berater']}, Mandant {data['cfg']['mandant']}, "
             f"{'Ist' if data['cfg']['method'] == 'ist' else 'Soll'}-Versteuerung.",
             "Ausgangsrechnungen sind je Steuersatz auf die Automatik-Erlöskonten gebucht (Umsatzsteuer rechnet DATEV);",
             "Eingangsrechnungen liegen als Liste und Beleg bei – die Aufwandskonten bestimmt die Steuerberatung.",
             "Die Konten bitte einmal mit der Steuerberatung abstimmen.", ""]
    if data["copies"]:
        lines.append(f"Nicht im Buchungsstapel: {len(data['copies'])} Rechnungen aus Ihren Dateien (anderes Programm), "
                     f"Summe brutto {_de(sum(x['gross'] or 0 for x in data['copies']))} € – gebucht werden sie über das "
                     f"Programm, in dem sie geschrieben wurden. Im Rechnungsausgangsbuch stehen sie mit Herkunft „Datei“.")
        lines.append("")
    for x in data["elsewhere"]:
        lines.append(f"Nicht enthalten: {x['n']} {x['plural']} ({_de(x['amount'])} €) – sie sind keine Rechnungen dieses "
                     f"Programms; meist kommen sie über den Shop oder Zahlungsanbieter zur Steuerberatung.")
    if data["elsewhere"]:
        lines.append("")
    if data["warnings"]:
        lines.append("Bitte prüfen:")
        lines += [f"  – {w}" for w in data["warnings"][:200]]
        lines.append("")
    state = "unverändert" if chain["ok"] else f"GEKÜRZT um {chain['lost']} Einträge" if chain.get("lost") else \
        f"GEBROCHEN bei Eintrag {chain.get('broken_at')}"
    lines.append(f"Änderungsprotokoll: {chain['n']} Einträge, Kette {state}, Siegel {chain['head'][:32]}")
    files_ok = rt.store.verify_files()
    if files_ok["changed"] or files_ok["missing"] or files_ok["docs_changed"]:
        lines.append(f"ACHTUNG: außerhalb von Physarum verändert – Originaldateien {len(files_ok['changed'])}, fehlend "
                     f"{len(files_ok['missing'])}, archivierte Belege {len(files_ok['docs_changed'])}")
    else:
        lines.append(f"Originaldateien ({files_ok['sources']}) und archivierte Belege ({files_ok['archived']}) unverändert.")
    lines.append("")
    lines.append("Prüfsummen (SHA-256):")
    for name in sorted(files):
        lines.append(f"  {hashlib.sha256(files[name]).hexdigest()}  {name}")
    files["Pruefprotokoll.txt"] = ("\r\n".join(lines) + "\r\n").encode("utf-8")
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for name in sorted(files):
            z.writestr(name, files[name])
    content = buf.getvalue()
    digest = hashlib.sha256(content).hexdigest()
    log = rt.store.kv_get("tax_exports") or []
    log.insert(0, dict(at=now_iso(), by=actor, label=label, von=data["von"].isoformat(), bis=data["bis"].isoformat(),
                       out=len(data["out"]), inc=len(data["inc"]), sha256=digest, chain=chain["head"]))
    rt.store.kv_set("tax_exports", log[:100])
    return content, data
