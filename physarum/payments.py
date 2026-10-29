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
from .text import fold, name_similarity, norm_key, norm_name, tokens
from .values import as_date, parse_duration

_NUMBER_TOKEN = re.compile(r"[A-Za-z0-9][A-Za-z0-9\-/_.]*[0-9]")

EPS = 0.01
BY_AMOUNT = "Zahlung ohne Nummer – Betrag und Zahler stimmen"        # booked by the growth
CONFIRMED = "Zuordnung über den Betrag (bestätigt)"                 # confirmed by a person
SKONTO_MAX = 0.031      # up to 3 % less …
SKONTO_DAYS = 21        # … paid within three weeks of the invoice date


def _num(v):
    return float(v) if isinstance(v, (int, float)) and not isinstance(v, bool) else None


def invoice_specs(model: dict) -> list[dict]:
    """Processes that end in being paid: they have an amount, a party and a step 'bezahlt'."""
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
        if step is None and not any(fold(d.get("name") or "").startswith("faellig") for d in p.get("deadlines", [])):
            continue
        out.append(dict(p=p, spec=spec, step=step, outgoing=outgoing))
    return out


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
        if a["kind"] != "money" or a.get("virtual") or a["id"] == p.get("gross"):
            continue
        toks = set(tokens(a["name"]))
        if toks & _PAYABLE_WORDS and not toks & {"offen", "offener"} and payable is None:
            payable = a["id"]
        elif toks & _DEDUCT_WORDS and deduct is None:
            deduct = a["id"]
    return payable, deduct


def due_attr(p: dict) -> str | None:
    """The deadline by which an invoice is to be paid ("fällig am", "zahlbar bis")."""
    dl = next((d for d in p.get("deadlines", []) if fold(d.get("name") or "").startswith(("faellig", "zahlbar", "due"))),
              None) or (p.get("deadlines") or [None])[0]
    return dl["attr"] if dl else None


LEGAL_TERM = 30  # § 286 Abs. 3 BGB: in default 30 days after the invoice at the latest


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
    for ip in invoice_specs(model):
        p, spec, step = ip["p"], ip["spec"], ip["step"]
        recs = records.get(p["type"], [])
        rid_set = {r["id"] for r in recs}
        st = p.get("status") or {}
        negative = set(st.get("negative") or [])
        own_paid = [s["attr"] for s in ([step] + step.get("also", [])) if s["source"] == "own"] if step else []
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
        for r in recs:
            k = norm_key(r["data"].get(key)) if key and r["data"].get(key) is not None else ""
            if len(k) >= 6 or (len(k) >= 5 and not k.isdigit()):
                by_no.setdefault(k, []).append(r["id"])
        by_no = {k: v[0] for k, v in by_no.items() if len(v) == 1}
        if by_no:
            for btid, bs in banks.items():
                texts = [a["id"] for a in bs["spec"]["attrs"] if a["kind"] in ("text", "id") and not a.get("hidden")]
                for b in records.get(btid, []):
                    for aid in texts:
                        v = b["data"].get(aid)
                        if not isinstance(v, str):
                            continue
                        for tok in _NUMBER_TOKEN.findall(v[:2000]):
                            inv = by_no.get(norm_key(tok))
                            if inv is not None and inv not in links[b["id"]]:
                                links[b["id"]].append(inv)
        entries = {}
        payable, deduct = _payable_attrs(spec, p)
        rule = _due_rule(spec, p, recs)
        for r in recs:
            if is_draft(r):
                continue  # not issued: nobody owes anything yet
            g = _num(r["data"].get(p["gross"]))
            if g is None:
                continue
            # a final invoice after down payments: the customer owes what is left ("Zahlbetrag"), not the total
            owed = _num(r["data"].get(payable)) if payable else None
            if owed is None and deduct and _num(r["data"].get(deduct)):
                owed = round(g - abs(_num(r["data"].get(deduct))), 2)
            if owed is not None and 0 <= owed < g - EPS:
                g = owed
            cancelled = (st.get("attr") and str(r["data"].get(st["attr"])) in negative) or bool((r.get("meta") or {}).get("storno"))
            # the book leaves the due date out now and then: reckoned the way the firm does it, and said so
            due, due_how = (as_date(r["data"].get(rule["attr"])) if rule else None), None
            if rule and not due:
                due, due_how = estimate_due(rule, r, by_id) or (None, None)
            entries[r["id"]] = dict(rid=r["id"], gross=round(g, 2), paid=0.0, payments=[], notes=[], cancelled=cancelled,
                                    start=as_date(r["data"].get(p["start"]["attr"])), type=p["type"],
                                    outgoing=ip["outgoing"], skonto_ok=_skonto_agreed(model, by_id, p, r),
                                    credit=0.0, credits=[], credit_to=None, due=due, due_how=due_how,
                                    due_attr=rule["attr"] if rule else None)
        # the PDF the customer got says what is owed when the book says something else (a typo in the list)
        for inv, (d, total) in _documents(records, by_no).items():
            e = entries.get(inv)
            if e and not e["cancelled"] and abs(total - e["gross"]) > EPS:
                e["notes"].append(f"Laut PDF {_eur(total)}, im Buch {_eur(e['gross'])} – gezählt wird das PDF, "
                                  f"das hat der Kunde bekommen")
                e["doc"] = dict(rid=d["id"], total=total, book=e["gross"])
                e["gross"] = total
        _settle_credits(spec, recs, entries, by_no)
        swapped = _transposed_numbers(model, spec, p, recs, entries, links, banks, by_id, ip["outgoing"])
        # allocate every bank row over the invoices it names, in the order the money moved:
        # oldest invoice first, whatever is left stays with the last one
        def when_of(b):
            row = by_id[b]
            return as_date(row["data"].get(banks[row["type"]]["date"]["id"])) or date.min

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
            if value < 0:
                # a chargeback undoes what was paid on the invoice(s) it names
                left = -value
                for i in invs:
                    e = entries[i]
                    take = min(left, max(e["paid"], 0.0)) if i != invs[-1] else left
                    if take > 0:
                        e["paid"] -= take
                        e["payments"].append(dict(rid=b, date=when, amount=-round(take, 2), how=how))
                        left -= take
                continue
            if len(invs) > 1:
                invs = _fitting(invs, entries, value)
            if any(_RETENTION.search(str(row["data"].get(a["id"]) or "")) for a in bs["spec"]["attrs"] if a["kind"] == "text"):
                for i in invs:
                    entries[i]["retention_hint"] = True  # "abzgl. 5% Sicherheitseinbehalt"
            left = value
            for k, i in enumerate(invs):
                e = entries[i]
                need = max(e["gross"] - e["credit"] - e["paid"], 0.0)
                take = left if k == len(invs) - 1 else min(left, need)
                if take <= 0 and k != len(invs) - 1:
                    continue
                e["paid"] += take
                e["payments"].append(dict(rid=b, date=when, amount=round(take, 2), how=how,
                                          shared=len(invs) > 1, by_amount=bool(by_amount and (b, i) in by_amount)))
                left -= take
        _net_overpayments(entries, links, {r["id"]: r["data"].get(key) for r in recs} if key else {}, when_of)
        # book or manual paid date: paid in full when the bank does not speak
        pool = None
        for r in recs:
            e = entries.get(r["id"])
            if not e or e["payments"]:
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
                    if pool is None:
                        pool = _bank_pool(model, banks, records, by_id, set(links) | claimed, ip["outgoing"])
                    hit = _listed_payment(model, pool, owed, min(ds), r, p, spec, by_id)
                    if hit:
                        claimed.add(hit["rid"])
                        e["payments"].append(dict(rid=hit["rid"], date=hit["date"], amount=owed,
                                                  how="Zahlung ohne Nummer – Betrag, Zahler und Tag passen zur Liste"))
                        continue
                e["payments"].append(dict(rid=None, date=min(ds), amount=owed,
                                          how="von Hand eingetragen" if w[0] == "user" else "laut Liste bezahlt"))
        notes_of = [a["id"] for a in spec["attrs"] if a["kind"] == "text" and a.get("role") in ("notes", None)]
        for r in recs:
            e = entries.get(r["id"])
            if e and any(_RETENTION.search(str(r["data"].get(a) or "")) for a in notes_of):
                e["retention_hint"] = True  # the book says so: "5 % Sicherheitseinbehalt bis Abnahme+5 J."
        for e in entries.values():
            _finish(e)
            _retained(e, records_gross=_num(by_id[e["rid"]]["data"].get(p["gross"])))
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
        e["notes"].append(f"{_eur(e['open'])} ({str(round(e['open'] / full * 100, 1)).replace('.', ',')} %) sind "
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


_STORNO_WORDS = ("storno", "storniert", "stornierung", "stornorechnung", "cancel")


def _bank_pool(model, banks, records, by_id, taken: set, outgoing: bool) -> dict:
    """Bank lines that name no invoice, by amount: candidates for payments the list knows."""
    from .reconcile import bank_amount
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
            pool[round(value, 2)].append(dict(rid=row["id"], date=when, party=pv if isinstance(pv, int) else None,
                                              name=norm_name(name)))
    return pool


def _listed_payment(model, pool, owed, paid_on, r, p, spec, by_id) -> dict | None:
    """The invoice book says "bezahlt am 13.01."; on the statement, the same customer transferred
    exactly that amount within a few days, without a number: that is the payment."""
    cands = [x for x in pool.get(round(owed, 2), []) if abs((x["date"] - paid_on).days) <= 7]
    if not cands:
        return None
    party = r["data"].get(p.get("party")) if p.get("party") else None
    cust = norm_name(_title_of(model, by_id.get(party), by_id)) if isinstance(party, int) else ""
    fit = [x for x in cands if (x["party"] is not None and x["party"] == party) or
           (cust and x["name"] and name_similarity(cust, x["name"]) >= 0.6)]
    if not fit:
        return None
    fit.sort(key=lambda x: abs((x["date"] - paid_on).days))
    if len(fit) > 1 and abs((fit[0]["date"] - paid_on).days) == abs((fit[1]["date"] - paid_on).days):
        return None  # two equal transfers on the same day: the list cannot tell which
    hit = fit[0]
    pool[round(owed, 2)].remove(hit)
    return hit


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
        words = ""
        for aid in texts:
            v = r["data"].get(aid)
            if not isinstance(v, str):
                continue
            words += " " + fold(v)
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
        if abs(amount - (inv["gross"] - inv["credit"])) <= EPS and (any(w in words for w in _STORNO_WORDS) or storno_of):
            inv["cancelled"] = True
            inv["notes"].append(f"storniert durch {number or 'Stornobeleg'}")
            e["notes"].append(f"storniert die Rechnung über {_eur(inv['gross'])}")
        else:
            inv["credit"] = round(inv["credit"] + amount, 2)
            inv["credits"].append(dict(rid=r["id"], amount=round(amount, 2), number=number))
            inv["notes"].append(f"Gutschrift {number or ''} über {_eur(amount)} verrechnet".replace("  ", " "))
            e["notes"].append(f"mit der Rechnung über {_eur(inv['gross'])} verrechnet")


def _skonto_agreed(model: dict, by_id: dict, p: dict, r: dict) -> bool:
    """Skonto only where the firm grants it: a skonto column of the invoice or of its customer."""
    specs = {t["id"]: t for t in model["types"]}
    for rec in (r, by_id.get(r["data"].get(p.get("party"))) if p.get("party") else None):
        if not rec:
            continue
        for a in specs.get(rec["type"], {}).get("attrs", []):
            if "skonto" in fold(a["name"]):
                v = rec["data"].get(a["id"])
                if v not in (None, "", 0, 0.0, False) and fold(str(v)) not in ("nein", "kein", "keins", "0"):
                    return True
    return False


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
            e["notes"].append(f"Zahlung über {_eur(paid)} auf eine stornierte Rechnung – zurückzahlen oder umbuchen")
        e["open"] = 0.0
        return
    if paid > g + EPS:
        e["state"] = "überzahlt"
        e["notes"].append(f"{_eur(paid - g)} zu viel gezahlt" +
                          (" (doppelt überwiesen)" if _double(pays, g) else ""))
        e["paid_date"] = e["paid_date"] or (pays[-1]["date"] if pays else None)
        return
    if e["open"] <= EPS:
        e["state"] = "verrechnet" if paid <= EPS and e.get("credit") else "bezahlt"
        e["open"] = 0.0
        return
    if g < -EPS and paid <= EPS:
        e["state"] = "offen"  # a credit note of its own: the firm owes the customer
        e["notes"].append(f"Gutschrift über {_eur(-g)} – noch mit keiner Rechnung verrechnet und nicht ausgezahlt")
        return
    if paid > EPS:
        last = pays[-1]["date"] if pays else None
        share = e["open"] / g if g else 1
        timely = last and e["start"] and (last - e["start"]).days <= SKONTO_DAYS
        if share <= SKONTO_MAX and timely and not e.get("skonto_ok"):
            e["state"] = "teilbezahlt"
            e["notes"].append(f"{str(round(share * 100, 1)).replace('.', ',')} % ({_eur(e['open'])}) abgezogen, ohne dass "
                              f"Skonto vereinbart ist – nachfordern oder bewusst ausbuchen")
            return
        if share <= SKONTO_MAX and timely:
            e["state"] = "bezahlt"
            e["skonto"] = round(e["open"], 2)
            e["notes"].append(f"mit {str(round(share * 100, 1)).replace('.', ',')} % Skonto bezahlt "
                              f"({_eur(e['open'])} weniger; Umsatzsteuer anteilig berichtigen)")
            e["open"] = 0.0
            e["paid_date"] = last
            return
        e["state"] = "teilbezahlt"
        e["notes"].append(f"{_eur(paid)} von {_eur(g)} bezahlt, {_eur(e['open'])} offen")
        return
    if any(x["how"] == "Rückbuchung" for x in e["payments"]):
        e["notes"].append("Zahlung wurde zurückgebucht (Rücklastschrift) – wieder offen")
    e["state"] = "offen"


def _double(pays, g) -> bool:
    amounts = [round(x["amount"], 2) for x in pays if x["amount"] > 0]
    return len(amounts) >= 2 and sum(1 for a in amounts if abs(a - g) < EPS) >= 2


def _eur(x: float) -> str:
    s = f"{abs(x):,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    return ("-" if x < 0 else "") + s + " €"


def bank_allocations(entries: dict) -> dict[int, list[tuple[int, float]]]:
    """bank rid -> [(invoice rid, amount)] for showing where a transfer went."""
    out: dict[int, list] = defaultdict(list)
    for inv, e in entries.items():
        for x in e["payments"]:
            if x["rid"]:
                out[x["rid"]].append((inv, x["amount"]))
    return out


def problems(entries: dict) -> list[dict]:
    """Payments that do not add up: partial, too much, on cancelled invoices, charged back."""
    out = []
    for e in entries.values():
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


def stale_statuses(model: dict, records: dict, entries: dict) -> dict[str, list[dict]]:
    """Invoices whose own status still says 'offen' (or 'gemahnt') although the money is in."""
    out: dict[str, list[dict]] = {}
    specs = {t["id"]: t for t in model["types"]}
    for ip in invoice_specs(model):
        p = ip["p"]
        st = p.get("status") or {}
        if not st.get("attr") or not ip["step"]:
            continue
        stage = next((i for i, s in enumerate(p["steps"], start=1) if s["id"] == ip["step"]["id"]), None)
        target = [v for v, s in (st.get("map") or {}).items() if s == stage]
        if len(target) != 1:
            continue
        items = []
        for r in records.get(p["type"], []):
            e = entries.get(r["id"])
            v = r["data"].get(st["attr"])
            if not e or v is None or str(v) in (st.get("negative") or []):
                continue
            if e["state"] in ("bezahlt", "überzahlt") and (st["map"].get(str(v), 0) or 0) < stage:
                items.append(dict(rid=r["id"], step=ip["step"]["id"], value=target[0], was=str(v),
                                  when=e["paid_date"].isoformat() if e["paid_date"] else None))
        if items:
            out[p["type"]] = items
    return out
