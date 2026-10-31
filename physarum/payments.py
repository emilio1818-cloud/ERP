"""What is paid: a ledger per invoice, by amount.

"The purpose names the invoice" is a link, not a payment. A transfer pays as much as it
carries: 300 € on 562,18 € leaves 262,18 € open, a chargeback opens the invoice again, a
collective transfer is split across the invoices it names, a second transfer of the same
amount is a double payment. A paid date in the invoice book (or set by hand) counts as
paid in full when the bank says nothing about the invoice. Everything that shows whether
an invoice is open – list, record, today's work, key figures – reads this ledger.
"""
from __future__ import annotations

import re
from collections import Counter, defaultdict
from datetime import date, timedelta
from itertools import combinations

from .billing import is_draft
from .lexicon import NEGATIVE_STATES
from .text import counts_up, fold, name_similarity, norm_key, norm_name, tokens
from .values import as_date, as_number, fmt_eur, parse_duration, skonto_terms

_NUMBER_TOKEN = re.compile(r"[A-Za-z0-9][A-Za-z0-9\-/_.]*[0-9]")
_GLUED = re.compile(r"(?<=[A-Za-z.])\d{5}$")
_DAY = re.compile(r"\b\d{1,2}\.\d{1,2}\.(?:19|20)\d{2}\b")
_ISO_DAY = re.compile(r"\b(?:19|20)\d{2}-\d{2}-\d{2}\b")
_CREDITOR_ID = re.compile(r"\b[A-Z]{2}\d{2}ZZZ[A-Z0-9]{8,28}\b")  # SEPA creditor id: on a debit and on its return

EPS = 0.01
BY_AMOUNT = "Zahlung ohne Nummer – Betrag und Zahler stimmen"        # booked by the growth
CONFIRMED = "Zuordnung über den Betrag (bestätigt)"                 # confirmed by a person
CASH_KINDS = {"bar": "Barzahlung", "ueberweisung": "Überweisung", "lastschrift": "Lastschrift", "scheck": "Scheck",
              "verrechnung": "Verrechnung", "karte": "Kartenzahlung", "erstattung": "Erstattung"}
_BANKED = {"ueberweisung", "lastschrift", "scheck", "erstattung"}  # what a later bank statement shows again
SKONTO_MAX = 0.031      # up to 3 % less …
SKONTO_DAYS = 21        # … paid within three weeks of the invoice date


def invoice_specs(model: dict) -> list[dict]:
    """Processes that end in being paid: they have an amount, a party and a step the money settles
    (the bank names them), or a day by which they are to be paid."""
    specs = {t["id"]: t for t in model["types"]}
    out = []
    for p in model.get("processes", []):
        spec = specs.get(p["type"])
        if not spec or not p.get("gross"):
            continue
        step = next((s for s in p["steps"] if fold(s["label"]) == "bezahlt"), None)
        party_attr = next((a for a in spec["attrs"] if a["id"] == p.get("party")), {}) if p.get("party") else {}
        # a supplier's invoice is paid by money going out – whether or not the supplier is a list of its own
        outgoing = bool(spec.get("incoming")) or (specs.get(party_attr.get("ref")) or {}).get("concept") == "lieferant"
        if step is None and not _pay_deadline(p):
            continue
        out.append(dict(p=p, spec=spec, step=step, outgoing=outgoing))
    return out


def billed_cases(model: dict, records: dict, invoice_types: set) -> dict[int, set]:
    """{order rid: its invoices}, as the processes learned it ("berechnet"): the invoice names the order, or
    the order its invoice; an offer has the invoices of the orders that took it up. Invoices are where this
    ends – a list that is billed itself is not one of them."""
    child = [(p, s) for p in model.get("processes", []) for s in p["steps"] if s["source"] == "child"]
    bills = [(p, s) for p, s in child if fold(s["label"]) == "berechnet" and s.get("type") in invoice_types]
    cases = {p["type"] for p, s in bills}
    out: dict[int, set] = defaultdict(set)
    for p, s in bills:
        if s["type"] in cases:
            continue
        ids = {r["id"] for r in records.get(s["type"], [])}
        if s["rel_kind"] == "ref":
            for r in records.get(s["type"], []):
                if isinstance(v := r["data"].get(s["rel_attr"]), int):
                    out[v].add(r["id"])
        elif s["rel_kind"] == "own_ref":
            for r in records.get(p["type"], []):
                if (v := r["data"].get(s["rel_attr"])) in ids:
                    out[r["id"]].add(v)
    for p, s in child:  # the offer an order took up
        if s.get("type") in cases and p["type"] not in cases and s["rel_kind"] == "ref":
            for r in records.get(s["type"], []):
                if isinstance(v := r["data"].get(s["rel_attr"]), int) and out.get(r["id"]):
                    out[v] |= out[r["id"]]
    return out


def _case_name(model: dict, rec: dict) -> str:
    spec = next((t for t in model["types"] if t["id"] == rec["type"]), {})
    return f"{spec.get('name', '')} {rec['data'].get(spec.get('key')) or _title_of(model, rec)}".strip()


def _bank_types(model: dict) -> dict:
    from .reconcile import bank_specs
    return {b["spec"]["id"]: b for b in bank_specs(model)}


_PAYABLE_WORDS = {"zahlbetrag", "zahlbar", "restbetrag", "payable"}
_DEDUCT_WORDS = {"abschlag", "abschlaege", "abschlagszahlung", "abschlagszahlungen", "anzahlung", "anzahlungen",
                 "vorauszahlung", "vorauszahlungen", "abzueglich", "abzgl"}


def _payable_attrs(spec: dict, p: dict) -> tuple[str | None, str | None]:
    """The amount actually asked for, and the down payments deducted from the total."""
    payable = deduct = None
    for a in spec["attrs"]:
        if a["kind"] not in ("money", "number") or a.get("virtual") or a["id"] == p.get("gross"):
            continue  # a column filled on few rows may read as a plain number: still an amount
        toks = set(tokens(a["name"]))
        if toks & _PAYABLE_WORDS and not toks & {"offen", "offener"} and payable is None and a["kind"] == "money":
            payable = a["id"]
        elif toks & _DEDUCT_WORDS and deduct is None:
            deduct = a["id"]
    return payable, deduct


def _received_attr(spec: dict, p: dict, recs: list[dict], own_paid: list[str]) -> str | None:
    """The book's "erhalten" column, by what it holds: the gross where the book has the invoice as paid,
    less or nothing where it has not – not a second gross, not the net."""
    if not own_paid:
        return None
    for a in spec["attrs"]:
        if a["kind"] != "money" or a.get("virtual") or a["id"] in (p.get("gross"), p.get("net")):
            continue
        paid = unpaid = ok_paid = ok_unpaid = 0
        for r in recs:
            g, v = as_number(r["data"].get(p["gross"])), as_number(r["data"].get(a["id"]))
            if not g or g <= EPS:
                continue
            if any(as_date(r["data"].get(x)) for x in own_paid):
                paid += 1
                ok_paid += v is not None and abs(v - g) <= 0.03 * g + EPS  # in full, or less a skonto
            else:
                unpaid += 1
                ok_unpaid += v is None or v < g - EPS
        if paid >= 5 and unpaid >= 3 and ok_paid >= 0.8 * paid and ok_unpaid >= 0.8 * unpaid:
            return a["id"]
    return None


_SPACED_NUMBER = re.compile(r"(?<![\w.])(?:[A-Za-z]{1,4}\.?[\s\-/]*)?(?:19|20)\d{2}[\s\-/.]{0,2}\d{3,6}(?![\w])")


def _digits(s: str) -> str:
    return re.sub(r"\D", "", s)


def _loose_numbers(by_no: dict) -> dict[str, int]:
    """Invoice numbers by their digits alone – "RE 2026 0089", "Rg. 2026/0026" and "RE20260047" are
    how payers write RE-2026-0089 – where the digits name one invoice only."""
    seen: dict[str, list] = {}
    for k, rid in by_no.items():
        d = _digits(k)
        if len(d) >= 7:
            seen.setdefault(d, []).append(rid)
    return {d: v[0] for d, v in seen.items() if len(v) == 1}


def _pay_deadline(p: dict) -> dict | None:
    """The deadline by which an invoice is to be paid ("fällig am", "zahlbar bis")."""
    return next((d for d in p.get("deadlines", []) if fold(d.get("name") or "").startswith(("faellig", "zahlbar", "due"))),
                None)


def due_attr(p: dict) -> str | None:
    dl = _pay_deadline(p) or (p.get("deadlines") or [None])[0]
    return dl["attr"] if dl else None


LEGAL_TERM = 30  # § 286 Abs. 3 BGB: in default 30 days after the invoice at the latest
CHARGEBACK_FEE = 15.0  # what a bank adds to a returned debit, at most


def _due_rule(spec: dict, p: dict, recs: list[dict]) -> dict | None:
    """How a due date is reckoned where the book leaves it out: the firm's own rule (invoice date
    plus the customer's payment term), else its usual term, else the 30 days of § 286 BGB."""
    da = due_attr(p)
    if not da:
        return None
    f = next((f for f in spec.get("formulas") or [] if f["attr"] == da
              and f["op"] in ("date_add", "date_default", "date_add_ref")), None)
    c = Counter()
    for r in recs:
        a, b = as_date(r["data"].get(p["start"]["attr"])), as_date(r["data"].get(da))
        if a and b and 0 <= (b - a).days <= 120:
            c[(b - a).days] += 1
    usual = None
    if c:
        k, n = c.most_common(1)[0]
        if n >= 5 and n >= 0.5 * sum(c.values()):
            usual = k
    names = {a["id"]: a["name"] for a in spec["attrs"]}
    return dict(attr=da, formula=f, usual=usual, start=p["start"]["attr"], base_name=names.get((f or {}).get("args", [None])[0]))


def _days_text(n: int) -> str:
    return "1 Tag" if n == 1 else f"{n} Tage"


def estimate_due(rule: dict, r: dict, by_id: dict) -> tuple[date, str] | None:
    """(due date, how it was reckoned) for an invoice whose book has no due date."""
    data = r["data"]
    f = rule["formula"]
    if f:
        base = as_date(data.get(f["args"][0]))
        if base and f["op"] == "date_add_ref":
            target = by_id.get(data.get(f["ref"]))
            n = parse_duration(target["data"].get(f["ref_attr"])) if target else None
            if n is not None and 0 <= n <= 365:
                return base + timedelta(days=int(n)), f"{_days_text(int(n))} Zahlungsziel des Kunden"
        elif base and f["op"] in ("date_add", "date_default"):
            return base + timedelta(days=int(f["days"])), f"{_days_text(int(f['days']))} nach {rule['base_name'] or 'Rechnungsdatum'}"
    start = as_date(data.get(rule["start"]))
    if not start:
        return None
    if rule["usual"] is not None:
        return start + timedelta(days=rule["usual"]), f"üblich {_days_text(rule['usual'])} nach Rechnungsdatum"
    return start + timedelta(days=LEGAL_TERM), "spätestens 30 Tage nach Rechnungsdatum (§ 286 BGB)"


_AMOUNT = r"(-?\d{1,3}(?:\.\d{3})*,\d{2}|-?\d+,\d{2})\s*(?:€|eur)?\s*$"
_OWED_LINE = re.compile(r"\b(restforderung|zahlbetrag|zu zahlen|restbetrag|offener betrag|noch zu zahlen)\b[^\n]*?" + _AMOUNT,
                        re.I | re.M)
_GROSS_LINE = re.compile(r"\b(gesamtbetrag(?: brutto)?|rechnungsbetrag|summe brutto|bruttobetrag|endbetrag|gesamt brutto"
                         r"|brutto)\b[^\n]*?" + _AMOUNT, re.I | re.M)


def document_total(text: str | None) -> float | None:
    """What an invoice document asks for: the remainder after down payments, else the gross total."""
    if not text:
        return None
    for rx in (_OWED_LINE, _GROSS_LINE):
        hits = rx.findall(text[:20000])
        if hits:
            v = hits[-1][1].replace(".", "").replace(",", ".")
            try:
                return round(float(v), 2)
            except ValueError:
                return None
    return None


def _documents(records: dict, by_no: dict) -> dict[int, tuple[dict, float]]:
    """The PDF of an invoice ("RE-2026-0087.pdf", the one the customer got) and its total."""
    out = {}
    for d in records.get("doc", []):
        data = d["data"]
        if str(data.get("doc_kind") or "") != "PDF":
            continue
        inv = by_no.get(norm_key(str(data.get("doc_title") or "")))
        if inv is None:
            continue
        total = document_total(data.get("doc_text"))
        if total is not None and total > 0:
            out[inv] = (d, total)
    return out


def mail_sources(store) -> set[int]:
    """Files that came inside a mail (an attachment, a ZIP in a mail): a list somebody else made. A
    customer's "Zahlungsnachweis" there names invoice numbers too – but money counts only from the
    firm's own bank statements, or from such a file once the owner has accepted it."""
    rows = {r["id"]: r for r in store.q("SELECT id, name, parent_id FROM sources")}
    accepted = {int(k) for k, v in store.decisions("payment_source").items() if v == "yes" and str(k).isdigit()}
    out = set()
    for sid, row in rows.items():
        cur, seen = row["parent_id"], set()
        while cur and cur not in seen:
            seen.add(cur)
            parent = rows.get(cur)
            if parent is None:
                break
            if str(parent["name"]).lower().endswith((".eml", ".msg")):
                out.add(sid)
                break
            cur = parent["parent_id"]
    return out - accepted


def untrusted_rows(model: dict, records: dict, untrusted: set | None) -> set[int]:
    """Bank-like rows that come only from such files."""
    if not untrusted:
        return set()
    out = set()
    for tid in _bank_types(model):
        for r in records.get(tid, []):
            src = set((r.get("meta") or {}).get("src") or [])
            if src and src <= untrusted:
                out.add(r["id"])
    return out


def ledger(model: dict, records: dict, mention_refs: dict, today: date | None = None,
           untrusted: set | None = None, by_amount: dict | None = None) -> dict:
    """{invoice rid: entry}. An entry has gross, paid, open, state, paid_date, payments, notes.
    `untrusted`: source ids whose rows do not move money (see mail_sources).
    `by_amount`: {(bank rid, invoice rid): how} for links made by the amount, not by a number."""
    from .reconcile import bank_amount
    today = today or date.today()
    banks = _bank_types(model)
    skip = untrusted_rows(model, records, untrusted)
    if skip:
        records = {tid: ([r for r in rs if r["id"] not in skip] if tid in banks else rs) for tid, rs in records.items()}
    by_id = {r["id"]: r for rs in records.values() for r in rs}
    out: dict[int, dict] = {}
    claimed: set[int] = set()  # bank lines given to an invoice by amount, so no second one takes them
    # the first day the statements cover: a payment before it cannot be seen
    bank_from = min((d for b in banks.values() for row in records.get(b["spec"]["id"], [])
                     for d in [as_date(row["data"].get(b["date"]["id"]))] if d), default=None)
    def debit(row) -> bool:  # the line carries a creditor id: a direct debit, or its return
        return any(isinstance(v, str) and _CREDITOR_ID.search(v) for v in row["data"].values())
    knows_debits = {tid for tid in banks if any(debit(row) for row in records.get(tid, []))}
    procs = invoice_specs(model)
    billed = billed_cases(model, records, {ip["p"]["type"] for ip in procs})
    specs = {t["id"]: t for t in model["types"]}
    for ip in procs:
        p, spec = ip["p"], ip["spec"]
        recs = records.get(p["type"], [])
        rid_set = {r["id"] for r in recs}
        st = p.get("status") or {}
        negative = set(st.get("negative") or [])
        own_paid = [s["attr"] for st_ in p["steps"] if fold(st_["label"]) == "bezahlt"
                    for s in [st_] + st_.get("also", []) if s["source"] == "own"]  # the book's own "bezahlt am"
        # which bank rows point to which invoices: references, text mentions, confirmed amount matches
        links: dict[int, list[int]] = defaultdict(list)   # bank rid -> invoices it names
        attrs = {"match"}
        for rel in model["relations"]:
            if rel["src"] in banks and p["type"] in (rel.get("targets") or [rel["dst"]]):
                if rel["kind"] == "mention":
                    attrs.add(rel["attr"])
                else:
                    for b in records.get(rel["src"], []):
                        inv = b["data"].get(rel["attr"])
                        if isinstance(inv, int) and inv in rid_set and inv not in links[b["id"]]:
                            links[b["id"]].append(inv)
        for attr in attrs:
            for inv, srcs in mention_refs.get(attr, {}).items():
                if inv not in rid_set:
                    continue
                for b in srcs:
                    if b in by_id and by_id[b]["type"] in banks and inv not in links[b]:
                        links[b].append(inv)
        # the number in the purpose, read here: invoices written in Physarum (or added since the
        # last growth) are not in the text index of the files
        key = spec.get("key")
        by_no = {}
        nos = {r["id"]: norm_key(r["data"].get(key)) for r in recs if key and r["data"].get(key) is not None}
        plain = counts_up(nos.values())  # "31076": short, but one of a range that counts up
        for rid, k in nos.items():
            if len(k) >= 6 or (len(k) >= 5 and (plain or not k.isdigit())):
                by_no.setdefault(k, []).append(rid)
        by_no = {k: v[0] for k, v in by_no.items() if len(v) == 1}
        loose = _loose_numbers(by_no)
        if by_no:
            for btid, bs in banks.items():
                texts = [a["id"] for a in bs["spec"]["attrs"] if a["kind"] in ("text", "id") and not a.get("hidden")]
                for b in records.get(btid, []):
                    for aid in texts:
                        v = b["data"].get(aid)
                        if not isinstance(v, str):
                            continue
                        toks = _NUMBER_TOKEN.findall(v[:2000])
                        found = [by_no.get(norm_key(tok)) for tok in toks]
                        if plain:  # "Rg.Nr.31098": the number glued to its word
                            found += [by_no.get(m.group(0)) for tok in toks if (m := _GLUED.search(tok))]
                        if not any(i is not None for i in found):
                            found = [loose.get(_digits(m.group(0))) for m in _SPACED_NUMBER.finditer(v[:2000])]
                        for inv in found:
                            if inv is not None and inv not in links[b["id"]]:
                                links[b["id"]].append(inv)
        # the payer's own customer number next to an invoice number ("Kd-Nr. 10012 Rg 10060", both numberings
        # counting from 10001): not an invoice of somebody else, where the purpose names another one
        masters = {t["id"]: t for t in model["types"] if t["kind"] == "master" and t.get("key")}
        for b, invs in links.items():
            row = by_id.get(b)
            bs = banks.get(row["type"]) if row else None
            pv = row["data"].get(bs["party"]["id"]) if bs and bs.get("party") else None
            rec = by_id.get(pv) if isinstance(pv, int) else None
            own_no = norm_key(rec["data"].get(masters[rec["type"]]["key"])) if rec and rec["type"] in masters else None
            if own_no and len(invs) > 1 and key:
                rest = [i for i in invs if norm_key(by_id[i]["data"].get(key)) != own_no]
                if rest and len(rest) < len(invs):
                    links[b] = rest
        # money for an order or an offer pays the one invoice it has ("Anzahlung Angebot A-26-019"), also when
        # the invoice was written after the money came: as far as the invoice goes, in the direction it is paid
        case_no = defaultdict(set)
        for c, invs in billed.items():
            k = norm_key(by_id[c]["data"].get(specs[by_id[c]["type"]].get("key"))) if invs & rid_set else ""
            if len(k) >= 6 or (len(k) >= 5 and not k.isdigit()):
                case_no[k].add(c)
        case_no = {k: next(iter(v)) for k, v in case_no.items() if len(v) == 1}
        down = {}  # bank rid -> the orders and offers it pays
        for btid, bs in banks.items() if case_no else ():
            texts = [a["id"] for a in bs["spec"]["attrs"] if a["kind"] in ("text", "id") and not a.get("hidden")]
            for b in records.get(btid, []):
                cases = {case_no[k] for aid in texts if isinstance(v := b["data"].get(aid), str)
                         for tok in _NUMBER_TOKEN.findall(v[:2000]) if (k := norm_key(tok)) in case_no}
                invs = set().union(*(billed[c] & rid_set for c in cases))
                amt = bank_amount(bs, b["data"]) if len(invs) == 1 and not links.get(b["id"]) else None
                g = as_number(by_id[next(iter(invs))]["data"].get(p["gross"])) if amt else None
                if g and (amt < 0) == ip["outgoing"] and abs(amt) <= g + EPS:
                    links[b["id"]] = list(invs)
                    down[b["id"]] = cases
        entries = {}
        payable, deduct = _payable_attrs(spec, p)
        rule = _due_rule(spec, p, recs)
        # "Storniert am", "Cancelled at": filled, the claim is gone
        void_dates = [a["id"] for a in spec["attrs"] if a["kind"] in ("date", "datetime") and not a.get("virtual")
                      and set(tokens(a["name"])) & NEGATIVE_STATES]
        for r in recs:
            if is_draft(r) or billed.get(r["id"]):
                continue  # not issued: nobody owes anything yet; an order with its invoice is paid through that
            g = as_number(r["data"].get(p["gross"]))
            if g is None:
                continue
            # a final invoice after down payments: the customer owes what is left ("Zahlbetrag"), not the total
            owed = as_number(r["data"].get(payable)) if payable else None
            if owed is None and deduct and as_number(r["data"].get(deduct)):
                owed = round(g - abs(as_number(r["data"].get(deduct))), 2)
            if owed is not None and 0 <= owed < g - EPS:
                g = owed
            cancelled = (st.get("attr") and str(r["data"].get(st["attr"])) in negative) or \
                bool((r.get("meta") or {}).get("storno")) or any(as_date(r["data"].get(a)) for a in void_dates)
            # the book leaves the due date out now and then: reckoned the way the firm does it, and said so
            due, due_how = (as_date(r["data"].get(rule["attr"])) if rule else None), None
            if rule and not due:
                due, due_how = estimate_due(rule, r, by_id) or (None, None)
            entries[r["id"]] = dict(rid=r["id"], gross=round(g, 2), paid=0.0, payments=[], notes=[], cancelled=cancelled,
                                    start=as_date(r["data"].get(p["start"]["attr"])), type=p["type"],
                                    outgoing=ip["outgoing"],
                                    skonto_ok=_skonto_agreed(model, by_id, p, r),
                                    credit=0.0, credits=[], credit_to=None, due=due, due_how=due_how,
                                    due_attr=rule["attr"] if rule else None)
        # the PDF the customer got says what is owed when the book says something else (a typo in the list)
        for inv, (d, total) in _documents(records, by_no).items():
            e = entries.get(inv)
            if e and not e["cancelled"] and abs(total - e["gross"]) > EPS:
                e["notes"].append(f"Laut PDF {fmt_eur(total)}, im Buch {fmt_eur(e['gross'])} – gezählt wird das PDF, "
                                  f"das hat der Kunde bekommen")
                e["doc"] = dict(rid=d["id"], total=total, book=e["gross"])
                e["gross"] = total
        _settle_credits(spec, recs, entries, by_no)
        received = _received_attr(spec, p, recs, own_paid)
        got = {r["id"]: v for r in recs if received and (v := as_number(r["data"].get(received)))}
        advised = _payment_advice(records, banks, by_no, entries, links, model, by_id, p) if by_no else {}
        swapped = _transposed_numbers(model, spec, p, recs, entries, links, banks, by_id, ip["outgoing"])
        # allocate every bank row over the invoices it names, in the order the money moved:
        # oldest invoice first, whatever is left stays with the last one
        def when_of(b):
            row = by_id[b]
            return as_date(row["data"].get(banks[row["type"]]["date"]["id"])) or date.min

        named_any = {i for invs in links.values() for i in invs}
        for b in sorted(links, key=lambda b: (when_of(b), b)):
            invs = links[b]
            row = by_id[b]
            bs = banks[row["type"]]
            amt = bank_amount(bs, row["data"])
            when = as_date(row["data"].get(bs["date"]["id"]))
            if amt is None:
                continue
            invs = [i for i in invs if i in entries and not entries[i]["credit_to"]]
            if not invs:
                continue
            sign = -1.0 if ip["outgoing"] else 1.0
            value = sign * amt  # positive: money towards the invoice; negative: money back (chargeback)
            invs.sort(key=lambda i: (entries[i]["start"] or date.min, i))
            how = "Rückbuchung" if value < 0 else "Zahlung"
            if b in swapped:
                how = swapped[b]
            elif by_amount and all((b, i) in by_amount for i in invs):
                how = by_amount[(b, invs[0])]
            elif b in down:
                how = "Anzahlung zu " + ", ".join(sorted(_case_name(model, by_id[c]) for c in down[b]))
            if value < 0:
                # money back. A chargeback undoes a payment – all of it, perhaps with the bank's fee on top: the
                # claim is open again. Less than a payment is a refund: no longer owed, and it came in before
                left = -value
                for i in invs:
                    e = entries[i]
                    take = min(left, max(e["paid"], 0.0)) if i != invs[-1] else left
                    if take <= 0:
                        continue
                    owed = e["gross"] - e["credit"]
                    seen = any(x["amount"] > 0 and -EPS <= take - x["amount"] <= CHARGEBACK_FEE for x in e["payments"])
                    # a returned debit carries the creditor id like the debit did; a refund is a transfer of the firm's
                    returned = debit(row) if row["type"] in knows_debits else seen or EPS < take - owed <= CHARGEBACK_FEE
                    if returned:
                        undone = min(take, owed)
                        if seen:
                            e["paid"] -= undone
                        # else the debit it returns is not in the statements (one of a collective debit): in and out
                        e["fee"] = e.get("fee", 0.0) + round(take - undone, 2)
                    else:
                        e["refunded"] = e.get("refunded", 0.0) + take
                        how = "Erstattung"
                    e["payments"].append(dict(rid=b, date=when, amount=-round(take, 2), how=how))
                    left -= take
                continue
            book = None
            if len(invs) > 1:
                invs = _fitting(invs, entries, value) if b not in advised else invs
                if all(i in got for i in invs) and abs(sum(got[i] for i in invs) - value) <= EPS:
                    book = got  # one transfer for several: the book says how much went to each
                elif b in advised:  # as the advice lists them, each less the same skonto
                    book = {i: round((entries[i]["gross"] - entries[i]["credit"]) * (1 - advised[b]), 2) for i in invs}
            if any(_RETENTION.search(str(row["data"].get(a["id"]) or "")) for a in bs["spec"]["attrs"] if a["kind"] == "text"):
                for i in invs:
                    entries[i]["retention_hint"] = True  # "abzgl. 5% Sicherheitseinbehalt"
            more = _cut_off(invs, value, entries, recs, p, named_any, when) if not book else None
            if more:
                invs = invs + [more]
            left = value
            for k, i in enumerate(invs):
                e = entries[i]
                need = max(e["gross"] - e["credit"] - e["paid"], 0.0)
                take = left if k == len(invs) - 1 else book[i] if book else min(left, need)
                if take <= 0 and k != len(invs) - 1:
                    continue
                e["paid"] += take
                e["payments"].append(dict(rid=b, date=when, amount=round(take, 2), shared=len(invs) > 1,
                                          how="Rest der Sammelzahlung – ihr Zweck ist abgeschnitten, der Betrag passt"
                                          if i == more else how, by_amount=bool(by_amount and (b, i) in by_amount)))
                left -= take
        _net_overpayments(entries, links, {r["id"]: r["data"].get(key) for r in recs} if key else {}, when_of)
        # money the owner entered by hand: cash, a cheque, an offset, a double payment paid back – next to what
        # the bank says. A transfer entered before the statement came is the statement's payment once it shows.
        for r in recs:
            e = entries.get(r["id"])
            for m in ((r.get("meta") or {}).get("cash") or []) if e else []:
                amount, when, kind = as_number(m.get("amount")), as_date(m.get("date")), m.get("how")
                if not amount or not when:
                    continue
                signed = round(-amount if kind == "erstattung" else amount, 2)
                twin = next((x for x in e["payments"] if x.get("rid") and kind in _BANKED and not x.get("confirms")
                             and abs(x["amount"] - signed) <= EPS), None)
                if twin:
                    twin["confirms"] = m.get("id")
                    twin["how"] += f" – bestätigt Ihre Eintragung vom {when.strftime('%d.%m.')}"
                    continue
                if kind == "erstattung":
                    e["refunded"] = e.get("refunded", 0.0) + amount
                else:
                    e["paid"] += amount
                e["payments"].append(dict(rid=None, date=when, amount=signed, by_hand=m.get("id"),
                                          how=f"{CASH_KINDS.get(kind, 'Zahlung')} (von Hand eingetragen)"))
        pool = iban_party = None

        def pool_of():  # bank lines that name no invoice, and the accounts that are a customer's: the account
            nonlocal pool, iban_party  # their list gives, the accounts that paid their invoices before
            if pool is None:
                from .reconcile import master_ibans
                pool = _bank_pool(model, banks, records, by_id, set(links) | claimed, ip["outgoing"])
                iban_party = {}
                for bb, invs in links.items():
                    row = by_id.get(bb)
                    iv = _iban_of(banks[row["type"]], row) if row and row["type"] in banks else ""
                    for i in invs:
                        pv = by_id[i]["data"].get(p.get("party")) if i in by_id and p.get("party") else None
                        if len(iv) >= 15 and isinstance(pv, int):
                            iban_party.setdefault(iv, set()).add(pv)
                for iv, rids in master_ibans(model, records).items():
                    iban_party.setdefault(iv, set(rids))
            return pool, iban_party

        # the book's "erhalten" beyond what the bank shows: the customer's transfer without a number (a down
        # payment before the invoice), or money at the counter (cash, card)
        for r in recs:
            e = entries.get(r["id"])
            v = got.get(r["id"]) if e else None
            if not v:
                continue
            bank = sum(x["amount"] for x in e["payments"] if x["amount"] > 0)
            ds = [d for a in own_paid if (d := as_date(r["data"].get(a)))]
            extra = round(v - bank, 2)
            if extra <= EPS or not (bank > EPS or not ds):  # paid in the book's words: the paid date says it already
                continue
            hit = _listed_payment(model, *pool_of(), extra, e["start"], r, p, spec, by_id, window=(120, 60)) \
                if e["start"] else None
            if hit:
                claimed.add(hit["rid"])
            e["paid"] += extra
            e["payments"].append(dict(rid=hit["rid"], date=hit["date"], amount=extra,
                                      how="Zahlung ohne Nummer – Betrag und Zahler passen zum Buch") if hit else
                                 dict(rid=None, date=min(ds) if ds else e["start"], amount=extra,
                                      how="laut Buch erhalten (bar oder Karte)"))
        # paid at the counter the day of the invoice (the book says so), and a transfer of it days later: twice –
        # an exception; where most such invoices go that way, the book notes a payment in advance (a direct debit)
        twice, counter = [], 0
        for r in recs:
            e = entries.get(r["id"])
            ds = [d for a in own_paid if (d := as_date(r["data"].get(a)))] if e and e["start"] else []
            counter += bool(ds) and min(ds) <= e["start"]
            bank = [x for x in e["payments"] if x.get("rid") and x["amount"] > 0] if ds else []
            if bank and min(ds) <= e["start"] and min(x["date"] for x in bank) > min(ds) + timedelta(days=3) \
                    and not any(x["how"].startswith("laut Buch") for x in e["payments"]):
                twice.append((e, min(ds)))
        for e, day in twice if len(twice) <= max(2, 0.1 * counter) else []:
            owed = round(e["gross"] - e["credit"], 2)
            e["paid"] += owed
            e["payments"].append(dict(rid=None, date=day, amount=owed, how="laut Buch an der Kasse bezahlt"))
        # book or manual paid date: paid in full when the bank does not speak
        alone = []  # paid by the list, no transfer of their own amount: perhaps one transfer for several
        for r in recs:
            e = entries.get(r["id"])
            if not e or any(x["how"] != "Erstattung" for x in e["payments"]):
                continue
            by_hand = as_date((r.get("meta") or {}).get("paid_by_hand"))
            if by_hand:
                e["paid"] = e["gross"]
                e["payments"].append(dict(rid=None, date=by_hand, amount=e["gross"], how="von Hand eingetragen"))
                continue
            ds = [as_date(r["data"].get(a)) for a in own_paid]
            ds = [d for d in ds if d]
            if ds:
                owed = round(e["gross"] - e["credit"], 2)
                e["paid"] = owed
                w = ((r.get("meta") or {}).get("w") or {}).get(own_paid[0]) or ["import"]
                if w[0] != "user" and owed > EPS:
                    pool_of()
                    hit = _listed_payment(model, pool, iban_party, owed, min(ds), r, p, spec, by_id)
                    if hit:
                        claimed.add(hit["rid"])
                        e["payments"].append(dict(rid=hit["rid"], date=hit["date"], amount=owed,
                                                  how="Zahlung ohne Nummer – Betrag, Zahler und Tag passen zur Liste"))
                        continue
                e["payments"].append(dict(rid=None, date=min(ds), amount=owed,
                                          how="von Hand eingetragen" if w[0] == "user" else "laut Liste bezahlt"))
                if w[0] != "user" and owed > EPS:
                    alone.append((r, e, min(ds)))
        _listed_together(alone, pool, model, p, by_id, claimed, iban_party)
        notes_of = [a["id"] for a in spec["attrs"] if a["kind"] == "text" and a.get("role") in ("notes", None)]
        for r in recs:
            e = entries.get(r["id"])
            if e and any(_RETENTION.search(str(r["data"].get(a) or "")) for a in notes_of):
                e["retention_hint"] = True  # the book says so: "5 % Sicherheitseinbehalt bis Abnahme+5 J."
        for e in entries.values():
            _finish(e)
            _retained(e, records_gross=as_number(by_id[e["rid"]]["data"].get(p["gross"])))
            if bank_from and not own_paid and not st.get("attr") and e["state"] == "offen" and not e["payments"] \
                    and e["due"] and e["due"] < bank_from:
                # only the bank could say it was paid, and the statement starts after the invoice was due
                e["unseen"] = bank_from
                e["notes"].append(f"fällig am {e['due'].strftime('%d.%m.%Y')}, der Kontoauszug beginnt erst am "
                                  f"{bank_from.strftime('%d.%m.%Y')} – ob bezahlt, zeigt ein älterer Auszug")
            out[e["rid"]] = e
    return out


_RETENTION = re.compile(r"(sicherheits|gewaehrleistungs|gewährleistungs)?einbehalt", re.I)


def _retained(e: dict, records_gross: float | None):
    """A final invoice paid but for a retention (5 % "Sicherheitseinbehalt" until the warranty ends): the
    rest is owed later, not overdue – nobody dunns it."""
    if not e.pop("retention_hint", False) or e["state"] != "teilbezahlt":
        return
    full = records_gross or e["gross"]
    if 0 < e["open"] <= 0.1 * full + EPS:
        e["retention"] = e["open"]
        e["notes"] = [n for n in e["notes"] if not n.endswith(" offen")]
        e["notes"].append(f"{fmt_eur(e['open'])} ({str(round(e['open'] / full * 100, 1)).replace('.', ',')} %) sind "
                          f"Sicherheitseinbehalt – fällig erst nach Abnahme und Gewährleistung, nicht anmahnen")


def _net_overpayments(entries: dict, links: dict, number: dict, when_of):
    """'RE-2026-0096 abzgl. Doppelzahlung vom 04.08. (RE-2026-0068)': a transfer that names an invoice paid
    twice and one still open nets the surplus of the first with the remainder of the second."""
    def owed(i):
        return entries[i]["gross"] - entries[i]["credit"]
    for b, invs in links.items():
        invs = [i for i in invs if i in entries and not entries[i]["cancelled"]]
        if len(invs) < 2:
            continue
        for a in [i for i in invs if entries[i]["paid"] - owed(i) > EPS]:
            surplus = round(entries[a]["paid"] - owed(a), 2)
            s = next((i for i in invs if i != a and abs(owed(i) - entries[i]["paid"] - surplus) <= EPS), None)
            if s is None:
                continue
            when = when_of(b)
            when = None if when == date.min else when
            entries[a]["paid"] -= surplus
            entries[a]["payments"].append(dict(rid=None, date=when, amount=-surplus,
                                               how=f"Überzahlung verrechnet mit {number.get(s) or 'einer anderen Rechnung'}"))
            entries[s]["paid"] += surplus
            entries[s]["payments"].append(dict(rid=None, date=when, amount=surplus,
                                               how=f"Überzahlung von {number.get(a) or 'einer anderen Rechnung'} verrechnet"))


def _bank_pool(model, banks, records, by_id, taken: set, outgoing: bool) -> dict:
    """Bank lines that name no invoice, by amount: candidates for payments the list knows."""
    from .reconcile import _INVOICE_OF, bank_amount
    pool: dict[float, list] = defaultdict(list)
    for btid, b in banks.items():
        for row in records.get(btid, []):
            if row["id"] in taken:
                continue
            amt = bank_amount(b, row["data"])
            value = (-1.0 if outgoing else 1.0) * amt if amt is not None else None
            when = as_date(row["data"].get(b["date"]["id"]))
            if not value or value <= 0 or not when:
                continue
            pv = row["data"].get(b["party"]["id"]) if b.get("party") else None
            name = _title_of(model, by_id.get(pv), by_id) if isinstance(pv, int) else \
                str(row["data"].get(b["name"]["id"]) or "") if b.get("name") else ""
            text = " ".join(str(row["data"].get(a["id"]) or "") for a in b["spec"]["attrs"] if a["kind"] == "text")
            pool[round(value, 2)].append(dict(rid=row["id"], date=when, party=pv if isinstance(pv, int) else None,
                                              name=norm_name(name), iban=_iban_of(b, row), text=norm_name(text),
                                              dates={as_date(x) for x in _INVOICE_OF.findall(text)} - {None}))
    return pool


def _iban_of(b: dict, row: dict) -> str:
    return str(row["data"].get(b["iban"]["id"]) or "").replace(" ", "").upper() if b.get("iban") else ""


def _listed_payment(model, pool, iban_party, owed, paid_on, r, p, spec, by_id, window=(7, 7)) -> dict | None:
    """The invoice book says "bezahlt am 13.01."; on the statement, the same customer transferred
    exactly that amount within a few days (`window`: days before, days after), without a number: that is the
    payment. "The same customer" is its name, an account that is theirs (in their list, or it paid their
    invoices before), or a purpose naming the invoice's date."""
    cands = [x for x in pool.get(round(owed, 2), []) if -window[0] <= (x["date"] - paid_on).days <= window[1]]
    if not cands:
        return None
    party = r["data"].get(p.get("party")) if p.get("party") else None
    cust = norm_name(_title_of(model, by_id.get(party), by_id)) if isinstance(party, int) else \
        norm_name(party) if isinstance(party, str) else ""  # a book without a customer list names them
    around = _names_around(model, by_id.get(party), by_id) if isinstance(party, int) else set()
    start = as_date(r["data"].get(p["start"]["attr"]))
    fit = [x for x in cands if (x["party"] is not None and x["party"] == party) or
           (cust and x["name"] and name_similarity(cust, x["name"]) >= 0.6) or
           (isinstance(party, int) and (iban_party or {}).get(x["iban"]) == {party}) or
           (start is not None and start in x["dates"]) or
           any((x["name"] and name_similarity(n, x["name"]) >= 0.85) or f" {n} " in f" {x['text']} " for n in around)]
    if not fit:
        return None
    fit.sort(key=lambda x: abs((x["date"] - paid_on).days))
    if len(fit) > 1 and abs((fit[0]["date"] - paid_on).days) == abs((fit[1]["date"] - paid_on).days):
        return None  # two equal transfers on the same day: the list cannot tell which
    hit = fit[0]
    pool[round(owed, 2)].remove(hit)
    return hit


def _listed_together(alone, pool, model, p, by_id, claimed, iban_party):
    """Two invoices the book marks paid within a month of each other, and one transfer of the payer
    over exactly their sum ("Sammelzahlung lt. Aufstellung August"): that transfer paid both. The book
    may give each invoice its own day; two pairs that would fit the same transfer leave it alone."""
    if not pool or len(alone) < 2:
        return
    by_party = defaultdict(list)
    for r, e, day in alone:
        pv = r["data"].get(p.get("party")) if p.get("party") else None
        if isinstance(pv, int) or (isinstance(pv, str) and norm_name(pv)):
            by_party[pv if isinstance(pv, int) else norm_name(pv)].append((r, e, day))
    for pv, items in by_party.items():
        if len(items) < 2:
            continue
        cust = norm_name(_title_of(model, by_id.get(pv), by_id)) if isinstance(pv, int) else pv
        options = defaultdict(list)  # transfer -> the pairs it would pay
        for (r1, e1, d1), (r2, e2, d2) in combinations(items, 2):
            if abs((d1 - d2).days) > 31 or e1["payments"][0]["rid"] is not None or e2["payments"][0]["rid"] is not None:
                continue
            total = round(e1["paid"] + e2["paid"], 2)
            fit = [x for x in pool.get(total, []) if all(abs((x["date"] - d).days) <= 31 for d in (d1, d2)) and
                   ((x["party"] == pv) or (cust and x["name"] and name_similarity(cust, x["name"]) >= 0.6) or
                    (iban_party or {}).get(x["iban"]) == {pv})]
            if len(fit) == 1:
                options[fit[0]["rid"]].append((fit[0], total, (e1, e2)))
        for opts in options.values():
            if len(opts) != 1:
                continue
            hit, total, pair = opts[0]
            if hit not in pool.get(total, []) or any(e["payments"][0]["rid"] is not None for e in pair):
                continue
            pool[total].remove(hit)
            claimed.add(hit["rid"])
            for e in pair:
                e["payments"][0].update(rid=hit["rid"], date=hit["date"], shared=True,
                                        how="Sammelzahlung ohne Nummern – Summe, Zahler und Tag passen zur Liste")


def _names_around(model: dict, rec: dict | None, by_id: dict, depth: int = 0) -> set[str]:
    """Who may pay for a case: its name, the people written in it (a parent, a contact person) and those of
    the records it points to (the contract's pupil) – two words at least."""
    from .lexicon import looks_like_person
    if not rec or depth > 1:
        return set()
    spec = next((t for t in model["types"] if t["id"] == rec["type"]), None) or {}
    out = {norm_name(_title_of(model, rec, by_id))}
    for a in spec.get("attrs", []):
        v = rec["data"].get(a["id"])
        if a["kind"] == "text" and isinstance(v, str) and len(v) <= 60 and looks_like_person(v):
            out.add(norm_name(v))
        elif a["kind"] == "ref" and isinstance(v, int) and v != rec["id"]:
            out |= _names_around(model, by_id.get(v), by_id, depth + 1)
    return {n for n in out if len(n.split()) >= 2}


def _title_of(model: dict, rec: dict | None, by_id: dict | None = None, depth: int = 0) -> str:
    """A record's name for comparing payers: its title, the name it points to, or its first name-like text."""
    if not rec:
        return ""
    spec = next((t for t in model["types"] if t["id"] == rec["type"]), None) or {}
    v = rec["data"].get(spec.get("title")) if spec.get("title") else None
    if isinstance(v, int) and not isinstance(v, bool):
        return _title_of(model, (by_id or {}).get(v), by_id, depth + 1) if depth < 2 else ""
    if isinstance(v, str) and v.strip():
        return v
    for a in spec.get("attrs", []):
        w = rec["data"].get(a["id"])
        if a.get("role") in ("name", "person") and isinstance(w, str) and w.strip():
            return w
    return next((w for w in rec["data"].values() if isinstance(w, str) and len(w) > 3 and not w[:1].isdigit()), "")


def _transposed(a: str, b: str) -> bool:
    """RE-2026-0120 for RE-2026-0102: the same digits, two of them swapped."""
    da, db = re.sub(r"\D", "", a), re.sub(r"\D", "", b)
    if len(da) != len(db) or da == db or sorted(da) != sorted(db) or re.sub(r"\d", "", a) != re.sub(r"\d", "", b):
        return False
    return sum(1 for x, y in zip(da, db) if x != y) == 2


def _transposed_numbers(model, spec, p, recs, entries, links, banks, by_id, outgoing) -> dict[int, str]:
    """A transfer that names an invoice of another customer, with an amount that does not fit it,
    while the payer has an open invoice over exactly that amount – the one whose number has two
    digits swapped, or the only one: the payer mistyped. The money goes to the invoice it was meant
    for. Returns {bank rid: how the payment reads}."""
    from .reconcile import bank_amount
    key, party = spec.get("key"), p.get("party")
    if not key:
        return {}
    by_rid = {r["id"]: r for r in recs}
    names = [a["id"] for a in spec["attrs"] if a.get("role") in ("name", "person") and a["kind"] == "text"]

    def customer(r) -> str:
        v = r["data"].get(party) if party else None
        if isinstance(v, int) and not isinstance(v, bool):
            return _title_of(model, by_id.get(v), by_id)
        return next((str(r["data"][a]) for a in names if isinstance(r["data"].get(a), str)), "")
    out = {}
    named = {i for invs in links.values() for i in invs}
    for b, invs in list(links.items()):
        if len(invs) != 1 or invs[0] not in entries or invs[0] not in by_rid:
            continue
        e, inv = entries[invs[0]], by_rid[invs[0]]
        row = by_id.get(b)
        bs = banks.get(row["type"]) if row else None
        if not bs or e["credit_to"]:
            continue
        amt = bank_amount(bs, row["data"])
        value = (-1.0 if outgoing else 1.0) * amt if amt is not None else None
        if not value or value <= 0 or abs(value - (e["gross"] - e["credit"])) <= EPS:
            continue
        pv = row["data"].get(bs["party"]["id"]) if bs.get("party") else None
        payer = _title_of(model, by_id.get(pv), by_id) if isinstance(pv, int) else \
            str(row["data"].get(bs["name"]["id"]) or "") if bs.get("name") else ""
        payer = norm_name(payer)
        cust = norm_name(customer(inv))
        if not payer or not cust or name_similarity(payer, cust) >= 0.6:
            continue  # the customer itself pays: a partial payment, not a typo
        number = str(inv["data"].get(key) or "")
        fits = [r for r in recs if r["id"] != inv["id"] and r["id"] in entries and r["data"].get(key) is not None
                and not entries[r["id"]]["cancelled"] and r["id"] not in named
                and abs(entries[r["id"]]["gross"] - entries[r["id"]]["credit"] - value) <= EPS
                and name_similarity(payer, norm_name(customer(r))) >= 0.6]
        swapped = [r for r in fits if _transposed(str(r["data"][key]), number)]
        if len(swapped) == 1:
            links[b] = [swapped[0]["id"]]
            out[b] = f"Zahlung (Zahlendreher: der Zweck nennt {number})"
            entries[swapped[0]["id"]]["notes"].append(f"Zahlung mit Zahlendreher im Zweck ({number}) – Kunde und Betrag passen hierher")
        elif len(fits) == 1:
            links[b] = [fits[0]["id"]]
            out[b] = f"Zahlung (der Zweck nennt {number}, eine Rechnung an {customer(inv) or 'jemand anderen'})"
            entries[fits[0]["id"]]["notes"].append(
                f"Zahlung mit falscher Nummer im Zweck ({number} ist eine Rechnung an {customer(inv) or 'jemand anderen'}) "
                f"– Zahler und Betrag passen hierher")
    return out


def _settle_credits(spec: dict, recs: list[dict], entries: dict, by_no: dict):
    """A credit note or a cancellation document is no debt of its own: it settles the invoice it
    names ("Gutschrift zu RE-2026-0098", "Stornorechnung zu RE-2026-0463"). A cancellation over the
    whole amount cancels the invoice; a credit note lowers what the customer still owes."""
    key = spec.get("key")
    texts = [a["id"] for a in spec["attrs"] if a["kind"] in ("text", "id") and a["id"] != key and not a.get("virtual")]
    for r in recs:
        e = entries.get(r["id"])
        if not e or e["gross"] >= -EPS:
            continue
        named = []
        storno_of = (r.get("meta") or {}).get("storno_of")
        if isinstance(storno_of, int) and storno_of in entries:
            named.append(storno_of)
        for aid in texts:
            v = r["data"].get(aid)
            if not isinstance(v, str):
                continue
            for tok in _NUMBER_TOKEN.findall(v[:500]):
                i = by_no.get(norm_key(tok))
                if i is not None and i != r["id"] and i in entries and i not in named and entries[i]["gross"] > EPS:
                    named.append(i)
        if len(named) != 1:
            continue
        inv = entries[named[0]]
        amount = -e["gross"]
        number = r["data"].get(key) if key else None
        e["credit_to"] = inv["rid"]
        if abs(amount - (inv["gross"] - inv["credit"])) <= EPS:
            inv["cancelled"] = True
            inv["notes"].append(f"storniert durch {number or 'Stornobeleg'}")
            e["notes"].append(f"storniert die Rechnung über {fmt_eur(inv['gross'])}")
        else:
            inv["credit"] = round(inv["credit"] + amount, 2)
            inv["credits"].append(dict(rid=r["id"], amount=round(amount, 2), number=number))
            inv["notes"].append(f"Gutschrift {number or ''} über {fmt_eur(amount)} verrechnet".replace("  ", " "))
            e["notes"].append(f"mit der Rechnung über {fmt_eur(inv['gross'])} verrechnet")


def _skonto_agreed(model: dict, by_id: dict, p: dict, r: dict) -> tuple | bool:
    """Skonto only where the firm grants it: the terms of the invoice or of its customer ("8 Tage 2 % Skonto",
    as (days, percent)), or a skonto column."""
    specs = {t["id"]: t for t in model["types"]}
    for rec in (r, by_id.get(r["data"].get(p.get("party"))) if p.get("party") else None):
        if not rec:
            continue
        given = []
        for a in specs.get(rec["type"], {}).get("attrs", []):
            v = rec["data"].get(a["id"])
            terms = skonto_terms(v)
            if terms:
                return terms
            if "skonto" in fold(a["name"]):
                if v not in (None, "", 0, 0.0, False) and fold(str(v)) not in ("nein", "kein", "keins", "0"):
                    given.append(as_number(v))
        if len(given) == 2 and None not in given:  # "Skonto %" 2 and "Skonto Tage" 8: the share is the smaller
            pct, days = sorted(given)
            pct = pct * 100 if pct < 1 else pct
            if 0 < pct <= 10 and 1 <= days <= 60 and float(days).is_integer():
                return int(days), pct
        if given:
            return True
    return False


def _payment_advice(records: dict, banks: dict, by_no: dict, entries: dict, links: dict, model: dict, by_id: dict,
                    p: dict) -> dict[int, float]:
    """A letter that names several open invoices ("Zahlungsavis", a reminder), and within two weeks one
    transfer of exactly their sum – or of the sum of some of them (one is held back: "behalten wir ein"), or of
    their sum less the same skonto on each: the transfer pays them. On the cent comes before a skonto.
    Linked in `links`; returns {bank rid: the share deducted}."""
    from .reconcile import bank_amount
    out, used = {}, set()
    rows = [(b, row) for b in banks for row in records.get(b, []) if row["id"] not in links]
    for d in records.get("doc", []):
        text = str(d["data"].get("doc_text") or "")[:5000]
        written = _DAY.search(f"{d['data'].get('doc_title') or ''} {text}") or _ISO_DAY.search(text)  # a PDF, a SEPA
        when = as_date(d["data"].get("doc_date")) or (as_date(written.group(0)) if written else None)  # file (pain.008)
        named = sorted({i for tok in _NUMBER_TOKEN.findall(text) if (i := by_no.get(norm_key(tok))) in entries})
        if not when or len(named) < 2:
            continue
        owed = {i: round(entries[i]["gross"] - entries[i]["credit"], 2) for i in named}
        total = round(sum(owed.values()), 2)
        groups = [c for n in range(2, len(named) + 1) for c in combinations(named, n)] if len(named) <= 10 \
            else [tuple(named)]
        sums = defaultdict(list)
        for c in groups:
            sums[round(sum(owed[i] for i in c), 2)].append(c)
        sums = {v: cs[0] for v, cs in sums.items() if len(cs) == 1}  # two ways to the same sum: neither
        parties = {v for i in named if isinstance(v := by_id[i]["data"].get(p.get("party")), int)} if p.get("party") else set()
        names = {norm_name(_title_of(model, by_id.get(v), by_id)) for v in parties} - {""}
        collection = len(parties) >= 3  # a SEPA file of the firm's own: many customers, one credit of the bank
        exact, cuts = [], []
        for btid, row in rows:
            amount = bank_amount(banks[btid], row["data"]) or 0.0
            day = as_date(row["data"].get(banks[btid]["date"]["id"]))
            if row["id"] in used or amount <= EPS or not day or not 0 <= (day - when).days <= 14:
                continue
            bs = banks[btid]
            pv = row["data"].get(bs["party"]["id"]) if bs.get("party") else None
            payer = norm_name(str(row["data"].get(bs["name"]["id"]) or "")) if bs.get("name") else ""
            if not collection and not (pv in parties or (payer and any(name_similarity(payer, n) >= 0.6 for n in names))):
                continue  # somebody else's money: the advice is about the customer's invoices
            cut = round(1 - amount / total, 4) if total > EPS else 1.0
            if round(amount, 2) in sums:
                exact.append((row["id"], list(sums[round(amount, 2)]), 0.0))
            elif 0.005 <= cut <= SKONTO_MAX:
                cuts.append((row["id"], list(named), cut))
        fits = exact if exact else cuts
        if len(fits) == 1:
            links[fits[0][0]] = fits[0][1]
            out[fits[0][0]] = fits[0][2]
            used.add(fits[0][0])
    return out


def _cut_off(invs: list[int], value: float, entries: dict, recs: list[dict], p: dict, named_any: set, when) -> int | None:
    """A collective transfer whose purpose ends mid-number (140 characters): what is left after the invoices
    it names is, on the cent, one more open invoice of the same payer that no transfer names – that one."""
    left = round(value - sum(max(entries[i]["gross"] - entries[i]["credit"] - entries[i]["paid"], 0.0) for i in invs), 2)
    who = {r["data"].get(p.get("party")) for r in recs if r["id"] in invs} if p.get("party") else set()
    if left <= EPS or left >= value - EPS or len(who) != 1 or not isinstance(next(iter(who)), int):
        return None  # nothing left over, or nothing paid on what it names: the same invoice paid twice
    more = [r["id"] for r in recs if r["id"] in entries and r["id"] not in named_any and r["data"].get(p["party"]) in who
            and not entries[r["id"]]["paid"] and (entries[r["id"]]["start"] or date.min) <= (when or date.max)
            and abs(entries[r["id"]]["gross"] - entries[r["id"]]["credit"] - left) <= EPS]
    return min(more, key=lambda i: (entries[i]["start"] or date.min, i)) if more else None


def _fitting(invs: list[int], entries: dict, value: float) -> list[int]:
    """A transfer that names several invoices pays those whose open amounts it matches exactly;
    otherwise the oldest first."""
    open_ = {i: round(entries[i]["gross"] - entries[i]["credit"] - entries[i]["paid"], 2) for i in invs}
    if len(invs) <= 10:
        for n in range(1, len(invs) + 1):
            for combo in combinations(invs, n):
                if abs(sum(open_[i] for i in combo) - value) <= EPS:
                    return list(combo)
    return invs


def _finish(e: dict):
    if e.get("credit_to"):
        e["paid"] = round(e["paid"], 2)
        e["open"], e["paid_date"], e["skonto"] = 0.0, None, None
        e["state"] = "verrechnet"  # a credit note or cancellation document, settled with its invoice
        return
    g, paid = round(e["gross"] - e.get("credit", 0.0), 2), round(e["paid"], 2)  # what is owed after credit notes
    if e.get("refunded"):  # what was paid twice goes back first; nobody refunds what never came in
        paid = max(round(paid - min(e["refunded"], max(paid - g, 0.0)), 2), round(min(e["refunded"], g), 2))
        e["notes"].append(f"{fmt_eur(e['refunded'])} erstattet")
    e["paid"] = paid
    e["open"] = round(g - max(paid, 0.0), 2)
    pays = sorted([x for x in e["payments"] if x["date"]], key=lambda x: x["date"])
    e["paid_date"] = None
    e["skonto"] = None
    cum = 0.0
    for x in pays:
        cum += x["amount"]
        if cum >= g - EPS and e["paid_date"] is None:
            e["paid_date"] = x["date"]
        elif cum < g - EPS:
            e["paid_date"] = None
    if e["cancelled"]:
        e["state"] = "storniert"
        if paid > EPS:
            e["notes"].append(f"Zahlung über {fmt_eur(paid)} auf eine stornierte Rechnung – zurückzahlen oder umbuchen")
        e["open"] = 0.0
        return
    if g + EPS < paid <= g + e.get("fee", 0.0) + EPS:
        paid = e["paid"] = g  # what came in on top is the bank's fee for the returned debit
    if paid > g + EPS:
        e["state"] = "überzahlt"
        counter = any(x["how"] == "laut Buch an der Kasse bezahlt" for x in pays)
        e["notes"].append(f"{fmt_eur(paid - g)} zu viel gezahlt" +
                          (" (an der Kasse und per Überweisung)" if counter else
                           " (doppelt überwiesen)" if _double(pays, g) else ""))
        e["paid_date"] = e["paid_date"] or (pays[-1]["date"] if pays else None)
        return
    if e["open"] <= EPS:
        e["state"] = "verrechnet" if paid <= EPS and e.get("credit") else "bezahlt"
        e["open"] = 0.0
        return
    if g < -EPS and paid <= EPS:
        e["state"] = "offen"  # a credit note of its own: the firm owes the customer
        e["notes"].append(f"Gutschrift über {fmt_eur(-g)} – noch mit keiner Rechnung verrechnet und nicht ausgezahlt")
        return
    if paid > EPS:
        last = pays[-1]["date"] if pays else None
        share = e["open"] / g if g else 1
        terms = e.get("skonto_ok") if isinstance(e.get("skonto_ok"), tuple) else None
        timely = last and e["start"] and (last - e["start"]).days <= SKONTO_DAYS
        if terms and timely:  # as agreed: no more than the percentage, paid within the days (and a few bank days)
            e["skonto_ok"] = share <= terms[1] / 100 + 0.001 and (last - e["start"]).days <= terms[0] + 5
        if share <= SKONTO_MAX and timely and not e.get("skonto_ok"):
            e["state"] = "teilbezahlt"
            e["deducted"] = True  # taken off, not paid later: to claim, whether due or not
            late = terms and share <= terms[1] / 100 + 0.001
            e["notes"].append(f"{str(round(share * 100, 1)).replace('.', ',')} % ({fmt_eur(e['open'])}) abgezogen, "
                              + (f"aber erst nach {(last - e['start']).days} Tagen gezahlt – Skonto gilt {terms[0]} Tage"
                                 if late else "ohne dass Skonto vereinbart ist") + " – nachfordern oder bewusst ausbuchen")
            return
        if share <= SKONTO_MAX and timely:
            e["state"] = "bezahlt"
            e["skonto"] = round(e["open"], 2)
            e["notes"].append(f"mit {str(round(share * 100, 1)).replace('.', ',')} % Skonto bezahlt "
                              f"({fmt_eur(e['open'])} weniger; Umsatzsteuer anteilig berichtigen)")
            e["open"] = 0.0
            e["paid_date"] = last
            return
        e["state"] = "teilbezahlt"
        e["notes"].append(f"{fmt_eur(paid)} von {fmt_eur(g)} bezahlt, {fmt_eur(e['open'])} offen")
        return
    if any(x["how"] == "Rückbuchung" for x in e["payments"]):
        e["notes"].append("Zahlung wurde zurückgebucht (Rücklastschrift) – wieder offen")
    e["state"] = "offen"


def _double(pays, g) -> bool:
    amounts = [round(x["amount"], 2) for x in pays if x["amount"] > 0]
    return len(amounts) >= 2 and sum(1 for a in amounts if abs(a - g) < EPS) >= 2


def bank_allocations(entries: dict) -> dict[int, list[tuple[int, float]]]:
    """bank rid -> [(invoice rid, amount)] for showing where a transfer went."""
    out: dict[int, list] = defaultdict(list)
    for inv, e in entries.items():
        for x in e["payments"]:
            if x["rid"]:
                out[x["rid"]].append((inv, x["amount"]))
    return out


def problems(entries: dict, today: date | None = None) -> list[dict]:
    """Payments that do not add up: partial, too much, on cancelled invoices, charged back."""
    out = []
    today = today or date.today()
    for e in entries.values():
        if e.get("retention"):
            continue  # paid as agreed: the rest is kept back until the warranty ends
        if e["state"] == "teilbezahlt" and not e.get("deducted") and e.get("due") and e["due"] >= today:
            continue  # a down payment, a first rate: the rest is not due yet
        if e["state"] in ("teilbezahlt", "überzahlt") or (e["state"] == "storniert" and e["paid"] > EPS) or \
                (e["state"] == "offen" and any(x["how"] == "Rückbuchung" for x in e["payments"])):
            out.append(e)
    return out


PAY_STATE, PAY_OPEN = "pay_state", "pay_open"
STATES = ["offen", "überfällig", "teilbezahlt", "bezahlt", "überzahlt", "storniert", "verrechnet"]


def apply_to_records(model: dict, records: dict, entries: dict, today: date | None = None):
    """Show the ledger where people look: two computed fields on every invoice. An open invoice
    past its due date says so ("überfällig") – the question "who owes me what" starts there."""
    today = today or date.today()
    types = {e["type"] for e in entries.values()}
    for t in model["types"]:
        if t["id"] not in types or any(a["id"] == PAY_STATE for a in t["attrs"]):
            continue
        t["attrs"].append(dict(id=PAY_STATE, name="Zahlung", kind="text", role="status", fill=1.0, distinct=len(STATES),
                               enum=STATES, constant=False, hidden=False, sources=[], virtual=dict(payments=True),
                               explain="aus den Zahlungen im Kontoauszug, nach Betrag"))
        t["attrs"].append(dict(id=PAY_OPEN, name="Offen", kind="money", role="money", fill=1.0, distinct=0, enum=None,
                               constant=False, hidden=False, sources=[], currency="EUR", virtual=dict(payments=True),
                               explain="Bruttobetrag abzüglich der zugeordneten Zahlungen"))
        for a in t["attrs"]:
            # the file's own "Offener Betrag" is yesterday's state: the payments say what is open now
            if a["kind"] == "money" and not a.get("virtual") and set(tokens(a["name"])) & {"offen", "offener", "rest",
                                                                                              "restbetrag", "outstanding"}:
                a["hidden"] = True
                a["superseded"] = PAY_OPEN
    for tid in types:
        for r in records.get(tid, []):
            e = entries.get(r["id"])
            if e:
                state = e["state"]
                due = e.get("due")
                if state == "offen" and e["open"] > EPS and due and due < today:
                    state = "überfällig"
                r["data"][PAY_STATE] = state
                r["data"][PAY_OPEN] = e["open"]
    # who owes how much: on the customer, the sum of their open invoices
    owed: dict[int, float] = defaultdict(float)
    for p in model.get("processes", []):
        for r in records.get(p["type"], []) if p["type"] in types and p.get("party") else []:
            e, who = entries.get(r["id"]), r["data"].get(p["party"])
            if e and isinstance(who, int) and not e.get("outgoing") and e["state"] in ("offen", "teilbezahlt") and e["open"] > EPS:
                owed[who] += e["open"]
    for t in model["types"]:
        if t["id"] in types or t.get("kind") != "master":
            continue
        rs = records.get(t["id"], [])
        if not any(r["id"] in owed for r in rs) and not any(a["id"] == PAY_OPEN for a in t["attrs"]):
            continue
        if not any(a["id"] == PAY_OPEN for a in t["attrs"]):
            t["attrs"].append(dict(id=PAY_OPEN, name="Offen", kind="money", role="money", fill=1.0, distinct=0, enum=None,
                                   constant=False, hidden=False, sources=[], currency="EUR", virtual=dict(payments=True),
                                   explain="die offenen Rechnungen, nach den Zahlungen im Kontoauszug"))
        for r in rs:
            r["data"][PAY_OPEN] = round(owed[r["id"]], 2) if r["id"] in owed else None
