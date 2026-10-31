"""Money owed without an invoice: what the members of a list pay, period after period.

A tenant list with "Gesamtmiete", an owners' list with "Hausgeld mtl.", a club's members with "Beitrag je
Fälligkeit": nobody writes an invoice, the contract or the decision is the claim. Physarum sees it as it sees
everything else, from the data: a list whose members pay one of its amounts again and again is a list of claims
(Sollstellungen). Each member owes that amount every period – the months between its own payments: monthly,
quarterly, half-yearly or yearly – from the first period it paid, as long as the bank statements reach and the
member is still in the newest version of the list; what the member's money does not cover is open – the periods
the transfer names first, otherwise the oldest (§ 366 Abs. 2 BGB). When many members move to the list's amount in
the same month (a fee raised at the general meeting), the amount is owed from that month on; before it, what
they paid. A one-off claim on the member's account (a service-charge result) is paid by the member's money of
exactly that amount. Nothing is claimed for a member who never paid: Physarum does not know since when it is owed.
"""
from __future__ import annotations

import re
from collections import defaultdict
from datetime import date, timedelta

from .reconcile import bank_amount, bank_specs
from .text import norm_key, tokens
from .values import _MONTHS, as_date, as_number

MIN_KEEPERS = 5   # members who paid exactly their amount ...
MIN_MONTHS = 3    # ... in three months at least
MIN_SHARE = 0.5   # ... and half of the members who pay at all
EPS = 0.01
_DAY = re.compile(r"\b\d{1,2}\.\d{1,2}\.(?:19|20)\d{2}\b")
_MM = re.compile(r"\b(0?[1-9]|1[0-2])\s*[/.]\s*(20\d\d|\d\d)\b")
_QH = re.compile(r"\b([QH])\s?([1-4])\s*[/.\- ]?\s*(20\d\d)\b", re.I)  # "Beitrag Q3 2026", "H2/2026"
CADENCES = (1, 3, 6, 12)


def _month(d: date) -> tuple[int, int]:
    d = d + timedelta(days=5)  # paid on the 28th: for the next month
    return d.year, d.month


def _period(ym: tuple[int, int], k: int) -> tuple[int, int]:
    """The first month of the k-month period a month belongs to (quarters from January)."""
    return ym[0], (ym[1] - 1) // k * k + 1


def _label(p: tuple[int, int], k: int) -> str:
    return {1: f"{p[1]:02d}/{p[0]}", 3: f"Q{(p[1] - 1) // 3 + 1}/{p[0]}", 6: f"H{(p[1] - 1) // 6 + 1}/{p[0]}"}.get(k, f"{p[0]}")


def _cadence(lines: list[dict]) -> int:
    """The months between a member's payments, as firms collect: 1, 3, 6 or 12."""
    months = sorted({_month(ln["date"]) for ln in lines})
    gaps = sorted((b[0] - a[0]) * 12 + b[1] - a[1] for a, b in zip(months, months[1:]))
    return min(CADENCES, key=lambda k: (abs(k - gaps[len(gaps) // 2]), k)) if gaps else 12


def _sums(lines: list[dict], k: int) -> dict:
    """What a member paid in each period of k months."""
    out = defaultdict(float)
    for ln in lines:
        out[_period(_month(ln["date"]), k)] += ln["amount"]
    return {p: round(v, 2) for p, v in out.items()}


def _named_months(toks: list[str], text: str, when: date, name: set) -> list[tuple[int, int]]:
    """The months a transfer names ("Miete Juni", "KDU 09+10/2026", "Restmiete Aug Sep Okt"), nearest year – not
    the payer's name ("Jan Ahlers")."""
    out = []
    for m in _MM.finditer(text):
        y = int(m.group(2))
        out.append((y + 2000 if y < 100 else y, int(m.group(1))))
    for t in toks:
        mo = _MONTHS.get(t) if t not in name else None
        if mo:
            y = min((when.year - 1, when.year, when.year + 1), key=lambda y: abs((date(y, mo, 15) - when).days))
            out.append((y, mo))
    for m in _QH.finditer(text):  # a quarter or a half-year: its first month
        n = int(m.group(2))
        if m.group(1).upper() == "Q" or n <= 2:
            out.append((int(m.group(3)), (n - 1) * (3 if m.group(1).upper() == "Q" else 6) + 1))
    return list(dict.fromkeys(out))


def _statements(model: dict, records: dict) -> list[dict]:
    """The bank statements – not a list with numbers of its own on every row (tenants with their account, amount and
    date look like a statement, but each row has its own key; no statement of the bench firms has one)."""
    out = []
    for b in bank_specs(model):
        k = b["spec"].get("key")
        vals = [r["data"].get(k) for r in records.get(b["spec"]["id"], [])] if k else []
        if not (vals and len(set(vals)) >= 0.95 * len(vals)):
            out.append(b)
    return out


def _lines(model: dict, records: dict, used: set) -> tuple[list[dict], dict]:
    """Money that came in and no invoice took (with the payer's name), and {account: the last day its statements
    reach} – an account whose statement ends in August says nothing about September."""
    out, last = [], {}
    banks = _statements(model, records)
    partners = {b["party"]["ref"] for b in banks if b.get("party") and b["party"].get("ref")}
    name_of = {r["id"]: " ".join(str(v) for v in r["data"].values() if isinstance(v, str))
               for t in partners for r in records.get(t, [])}
    for b in banks:
        own = min((a for a in b["spec"]["attrs"] if a["kind"] == "iban" and a is not b.get("iban")),
                  key=lambda a: a.get("distinct") or 0, default=None)  # "Auftragskonto": the statement's own account
        for r in records.get(b["spec"]["id"], []):
            d = as_date(r["data"].get(b["date"]["id"]))
            acc = (b["spec"]["id"], str(r["data"].get(own["id"]) or "") if own else "")
            if d and (acc not in last or d > last[acc]):
                last[acc] = d
            v = bank_amount(b, r["data"])
            if v is None or v <= EPS or not d or r["id"] in used:
                continue
            iv = re.sub(r"\s+", "", str(r["data"].get(b["iban"]["id"]) or "")).upper() if b.get("iban") else ""
            text = " ".join(str(r["data"].get(a["id"]) or "") if a["kind"] != "ref" else name_of.get(r["data"].get(a["id"]), "")
                            for a in b["spec"]["attrs"] if a["kind"] in ("text", "id", "ref") and not a.get("hidden"))
            out.append(dict(rid=r["id"], date=d, amount=round(v, 2), iban=iv, text=text, toks=tokens(text), acc=acc))
    return out, last


def _link(spec: dict, recs: list[dict], lines: list[dict]) -> dict[int, list[dict]]:
    """{member rid: its lines}: its number in the purpose, its account, or its full name – one member only."""
    key = spec.get("key")
    names = [a["id"] for a in spec["attrs"] if a["kind"] == "text" and (a.get("role") in ("name", "person")
                                                                         or a["id"] == spec.get("title"))]
    ibans = [a["id"] for a in spec["attrs"] if a["kind"] == "iban"]
    by_key, by_iban, by_name = defaultdict(set), defaultdict(set), []
    for r in recs:
        k = norm_key(r["data"].get(key)) if key else ""
        if len(k) >= 4:
            by_key[k].add(r["id"])
        for a in ibans:
            iv = re.sub(r"\s+", "", str(r["data"].get(a) or "")).upper()
            if len(iv) >= 15:
                by_iban[iv].add(r["id"])
        for a in names:
            ts = {t for t in tokens(str(r["data"].get(a) or "")) if len(t) >= 3 and not t.isdigit()}
            if len(ts) >= 2:
                by_name.append((ts, r["id"]))
    out = defaultdict(list)
    for ln in lines:
        toks = set(ln["toks"])
        who = set().union(*(by_key.get(norm_key(t), set()) for t in toks)) | by_iban.get(ln["iban"], set())
        if not who:
            hits = [(len(ts & toks), rid) for ts, rid in by_name if len(ts & toks) >= 2]
            top = max((n for n, _ in hits), default=0)
            who = {rid for n, rid in hits if n == top}
        if len(who) == 1:
            out[next(iter(who))].append(ln)
    return out


def _stream(a: dict, payers: set, linked: dict, by_id: dict) -> dict | None:
    """Do the members pay column `a`, period after period? {"keep": {member: (months per period, amount owed
    before `since`)}, "since": the month a raised amount is owed from, or None}. A member keeps it who paid exactly
    its amount in three periods; one who paid a steady amount and then the list's (a fee raised) counts when many
    did so in the same month – then also the members who still pay their old steady amount owe the new one."""
    keep, moved, steady, old_of = {}, defaultdict(list), {}, defaultdict(set)
    for m in payers:
        v = as_number(by_id[m]["data"].get(a["id"]))
        if not v or v <= EPS:
            continue
        k = _cadence(linked[m])
        sums = _sums(linked[m], k)
        ps = sorted(sums)
        exact = [p for p in ps if abs(sums[p] - v) <= EPS]
        before = {sums[p] for p in ps if not exact or p < exact[0]}
        if len(exact) >= MIN_MONTHS and exact[0] == ps[0]:
            keep[m] = (k, None)
        elif exact and len(before) == 1 and all(abs(sums[p] - v) <= EPS for p in ps if p >= exact[0]):
            moved[exact[0]].append((m, k, next(iter(before))))
            old_of[round(v, 2)].add(next(iter(before)))
        elif not exact and len(before) == 1 and len(ps) >= MIN_MONTHS:
            steady[m] = (k, next(iter(before)))
    since = max(moved, key=lambda p: len(moved[p]), default=None)
    if since is None or len(moved[since]) < MIN_KEEPERS or len(moved[since]) < 0.6 * sum(len(x) for x in moved.values()):
        since = None
    else:
        keep.update({m: (k, old) for m, k, old in moved[since]})
        # who still pays the amount the others paid before the raise (an old standing order) owes the new one
        keep.update({m: x for m, x in steady.items() if x[1] in old_of[round(as_number(by_id[m]["data"][a["id"]]), 2)]})
    valued = sum(1 for m in payers if (as_number(by_id[m]["data"].get(a["id"])) or 0) > EPS)
    if len(keep) < MIN_KEEPERS or len(keep) < MIN_SHARE * valued:
        return None
    return dict(keep=keep, since=since)


def recurring_claims(model: dict, records: dict, ledger: dict, today: date | None = None) -> dict:
    """{"claims": {claim key: entry like the ledger's (gross, paid, open, state, due, payments) with the member},
    "lines": the bank lines that are a member's regular money – no question "wofür?"}"""
    today = today or date.today()
    banks = {b["spec"]["id"] for b in _statements(model, records)}
    used = {x["rid"] for e in ledger.values() for x in e.get("payments", []) if x.get("rid")}
    lines, bank_last = _lines(model, records, used)
    if not lines or not bank_last:
        return dict(claims={}, lines=set())
    party_of = {p["type"]: p.get("party") for p in model.get("processes", [])}
    specs = {t["id"]: t for t in model["types"]}
    rec_of = {r["id"]: r for t in {e["type"] for e in ledger.values()} for r in records.get(t, [])}
    account = defaultdict(list)  # member rid -> the one-off claims on its account (a result, a levy)
    for e in ledger.values():
        r = rec_of.get(e["rid"])
        if not r or e.get("outgoing"):
            continue
        if party_of.get(e["type"]) and isinstance(r["data"].get(party_of[e["type"]]), int):
            account[r["data"][party_of[e["type"]]]].append(e)
        elif (k := norm_key(r["data"].get(specs[e["type"]].get("key")))) and len(k) >= 4:
            account[k].append(e)  # no reference, but the member's number
    out, streams = {}, []
    for spec in model["types"]:
        recs = records.get(spec["id"], [])
        if spec["id"] in banks or spec["kind"] not in ("master", "transaction") or len(recs) < MIN_KEEPERS:
            continue
        linked = _link(spec, recs, lines)
        if len(linked) < MIN_KEEPERS:
            continue
        by_id = {r["id"]: r for r in recs}
        payers = {m for m, ls in linked.items() if len(ls) >= MIN_MONTHS}
        found, taken = [], set()
        cols = [a for a in spec["attrs"] if a["kind"] in ("money", "number") and not a.get("virtual")
                and (not a.get("hidden") or a.get("constant"))]  # one fee for all is a fee too
        while True:
            best = None
            for a in cols:
                stream = _stream(a, payers - taken, linked, by_id)
                if stream and (not best or len(stream["keep"]) > len(best[1]["keep"])):
                    best = (a, stream)
            if not best:
                break
            found.append(best)
            taken |= set(best[1]["keep"])
            cols.remove(best[0])
        if found:
            streams.append((sum(len(st["keep"]) for _, st in found), spec, found, linked, by_id))
    taken_lines: set = set()
    explained: set = set()
    for _n, spec, found, linked, by_id in sorted(streams, key=lambda x: -x[0]):
        mine = {m: [ln for ln in ls if ln["rid"] not in taken_lines] for m, ls in linked.items()}
        for a, stream in found:
            keep = {m: x for m, x in stream["keep"].items() if len(mine[m]) >= MIN_MONTHS}
            if len(keep) >= MIN_KEEPERS:
                st = next((p.get("status") or {} for p in model.get("processes", []) if p["type"] == spec["id"]), {})
                gone = (st["attr"], set(st.get("negative") or [])) if st.get("attr") else None
                out.update(_claims_of(spec, a, keep, stream["since"], mine, by_id, account, bank_last, explained, gone))
                taken_lines |= {ln["rid"] for m in keep for ln in mine[m]}
                for m, ls in mine.items():  # the others of the list who pay a steady amount of their own: known money
                    if m not in keep and as_number(by_id[m]["data"].get(a["id"])):
                        same = defaultdict(list)
                        for ln in ls:
                            same[ln["amount"]].append(ln["rid"])
                        explained |= {r for rids in same.values() if len(rids) >= MIN_MONTHS for r in rids}
    return dict(claims=out, lines=explained)


def _end(spec: dict, rec: dict, after: date, last_paid: date, gone: bool) -> date | None:
    """A day in the member's row after its claims began – it left, sold, ended ("Kowalski (bis 31.08.2026)"). A date
    column only where the member's money stopped by then ("fällig seit 15.07." with payments after it is no end) – or
    where its status says it has gone ("ausgetreten": a standing order running on is money to give back)."""
    days = [d for a in spec["attrs"] if a["kind"] in ("date", "datetime") and a.get("role") != "due" and not a.get("virtual")
            and (d := as_date(rec["data"].get(a["id"]))) and (gone or last_paid <= d + timedelta(days=15))]
    texts = [v for a in spec["attrs"] if a["kind"] == "text" and isinstance(v := rec["data"].get(a["id"]), str)]
    texts += [str(v) for alts in ((rec.get("meta") or {}).get("alts") or {}).values() for v, _src in alts]
    days += [as_date(m.group(0)) for v in texts for m in _DAY.finditer(v)]
    later = [d for d in days if d and d > after]
    return min(later) if later else None


def _claims_of(spec, a, keep, since, linked, by_id, account, bank_last, explained: set, gone=None) -> dict:
    out = {}
    # the day it is due: by when most of the members paid in the first month of their period
    days = sorted(max(0, (ln["date"] - date(*_month(ln["date"]), 1)).days) for m in keep for ln in linked[m]
                  if abs(ln["amount"] - as_number(by_id[m]["data"][a["id"]])) <= EPS)
    due_day = min(15, max(3, days[int(0.8 * (len(days) - 1))] + 1)) if days else 5
    # a whole group (all tenants of one house) stopping in the same month has ended – not ten defaults at once
    stop = {m: _month(max(ln["date"] for ln in linked[m])) for m in keep}
    ended: dict = {}
    for b in spec["attrs"]:
        if b["id"] in (a["id"], spec.get("key")) or b["kind"] not in ("text", "number", "id", "ref"):
            continue
        groups = defaultdict(list)
        for m in keep:
            v = by_id[m]["data"].get(b["id"])
            if v not in (None, ""):
                groups[v].append(m)
        for ms in groups.values():
            last_months = [stop[m] for m in ms]
            top = max(set(last_months), key=last_months.count)
            if len(ms) >= 3 and last_months.count(top) >= 0.8 * len(ms) and top < max(stop.values()):
                for m in ms:
                    ended[m] = top if m not in ended else max(ended[m], top)
    for m, (k, old) in keep.items():
        rec = by_id[m]
        amount = round(as_number(rec["data"][a["id"]]), 2)
        first = min(_period(_month(ln["date"]), k) for ln in linked[m])
        seen = max(bank_last[ln["acc"]] for ln in linked[m])  # as far as the member's accounts' statements reach
        last = _month(max(ln["date"] for ln in linked[m])) if (rec.get("meta") or {}).get("vanished") else \
            (seen.year, seen.month) if seen.day >= due_day else \
            ((seen.replace(day=1) - timedelta(days=1)).year, (seen.replace(day=1) - timedelta(days=1)).month)
        end = _end(spec, rec, date(*first, 1), max(ln["date"] for ln in linked[m]),
                   bool(gone and str(rec["data"].get(gone[0])) in gone[1]))
        if end:
            last = min(last, (end.year, end.month))
        if m in ended:
            last = min(last, ended[m])
        periods, y, mo = [], *first
        while (y, mo) <= last and len(periods) < 36:
            periods.append((y, mo))
            y, mo = (y + (mo + k - 1) // 12, (mo + k - 1) % 12 + 1)
        cut = _period(since, k) if since else None
        if cut and k > 1 and cut != since:
            periods = [x for x in periods if x != cut]  # the raise falls inside this period: what is owed for it is unclear
        # owed: the list's amount – before a fee was raised for all, what the member paid then
        claims = {x: dict(period=x, gross=amount if not since or x >= since or old is None else old, paid=0.0, payments=[])
                  for x in periods}
        who = {t for a in spec["attrs"] if a["kind"] == "text" for t in tokens(str(rec["data"].get(a["id"]) or ""))}
        # one-off claims on the member's account, paid by money of exactly their amount
        mine = [e for e in account.get(m, []) + account.get(norm_key(rec["data"].get(spec.get("key"))), [])
                if e["state"] in ("offen", "teilbezahlt") and e["open"] > EPS]
        rest = []
        for ln in sorted(linked[m], key=lambda x: (x["date"], x["rid"])):
            e = next((e for e in mine if abs(e["open"] - ln["amount"]) <= EPS and e["open"] > EPS
                      and (not e.get("start") or ln["date"] >= e["start"] - timedelta(days=7))), None)
            if e:
                e["paid"] = round(e["paid"] + ln["amount"], 2)
                e["open"] = 0.0
                e["state"] = "bezahlt"
                e["payments"].append(dict(rid=ln["rid"], date=ln["date"], amount=ln["amount"],
                                          how="Zahlung ohne Nummer – vom Konto des Mitglieds, Betrag passt"))
                continue
            rest.append(ln)
        for ln in rest:  # the months it names first, then the oldest, then ahead
            left = ln["amount"]
            explained.add(ln["rid"])
            said = [_period(x, k) for x in _named_months(ln["toks"], ln["text"], ln["date"], who)]
            named = list(dict.fromkeys(x for x in said if x in claims))
            if said and not named:
                continue  # for a month nothing is claimed for: not this money
            order = named + [p for p in periods if p not in named]
            for p in order:
                c = claims[p]
                need = round(c["gross"] - c["paid"], 2)
                if left <= EPS:
                    break
                if need <= EPS:
                    continue
                take = min(left, need)
                c["paid"] = round(c["paid"] + take, 2)
                c["payments"].append(dict(rid=ln["rid"], date=ln["date"], amount=round(take, 2)))
                left = round(left - take, 2)
            nxt = date(*_month(ln["date"]), 1)
            if left > EPS and not (abs(left - amount) <= EPS and ln["date"] >= nxt - timedelta(days=10)
                                   and _period(_month(ln["date"]), k) not in claims):
                explained.discard(ln["rid"])  # money over and above (paid twice): a question, unless it pays the next period ahead
        for e in account.get(m, []):  # a credit on the account settles the open month of exactly its amount
            credit = e.get("surplus") or 0.0
            c = next((c for p, c in claims.items() if credit and abs(c["gross"] - c["paid"] - credit) <= EPS), None)
            if c:
                c["paid"] = c["gross"]
                c["payments"].append(dict(rid=None, date=None, amount=credit, how="mit dem Guthaben verrechnet"))
        member_key = str(rec["data"].get(spec.get("key")) or m)
        for p, c in claims.items():
            c.update(open=round(c["gross"] - c["paid"], 2), member=m, type=spec["id"], attr=a["id"],
                     label=f"{member_key} {a['name']} {_label(p, k)}", when=_label(p, k),
                     due=date(p[0], p[1], due_day))
            c["state"] = "bezahlt" if c["open"] <= EPS else "teilbezahlt" if c["paid"] > EPS else "offen"
            out[f"claim:{spec['id']}:{m}:{p[0]}-{p[1]:02d}"] = c
    return out

