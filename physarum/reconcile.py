"""Money has to add up: every euro on the bank statement belongs to a document.

Physarum's "hunger": where the balance does not close (money received, no invoice paid;
an invoice open, a matching transfer without reference), there is work or a missing link.

1. Transfers that name an invoice number are linked by mention discovery already.
2. For the rest, the amount speaks: an incoming transfer that equals exactly one open
   invoice of the same payer, the sum of two of them, or the invoice minus 2-3 % skonto.
   These are proposals until a person confirms them; confirmed links are re-created on
   every growth (stored as decisions).
3. Fraud check: a document from a known supplier that names a bank account the company
   has never paid to, or comes from a look-alike domain, is flagged before anyone pays.
"""
from __future__ import annotations

import re
from datetime import date

from .infer.identity import FREEMAIL
from .text import fold, jaro_winkler, name_similarity, norm_name
from .values import as_date, iban_ok

IBAN_RE = re.compile(r"\b([A-Z]{2}\d{2}(?:\s?[A-Z0-9]{4}){3,7}(?:\s?[A-Z0-9]{1,4})?)\b")


def _num(v):
    return float(v) if isinstance(v, (int, float)) and not isinstance(v, bool) else None


def bank_specs(model: dict) -> list[dict]:
    out = []
    for t in model["types"]:
        if t["kind"] != "transaction":
            continue
        iban = next((a for a in t["attrs"] if a["kind"] == "iban" and not a.get("hidden")), None)
        money = next((a for a in t["attrs"] if a["kind"] == "money" and not a.get("hidden")), None)
        date_a = next((a for a in t["attrs"] if a["kind"] in ("date", "datetime") and not a.get("hidden")), None)
        if t.get("concept") == "kontobewegung" or (iban and money and date_a):
            if money and date_a:
                party = next((a for a in t["attrs"] if a["kind"] == "ref"), None)
                text = next((a for a in t["attrs"] if a.get("role") == "notes" and not a.get("hidden")), None)
                name = next((a for a in t["attrs"] if a.get("role") in ("name", "person") and a["kind"] == "text"), None)
                out.append(dict(spec=t, money=money, date=date_a, party=party, iban=iban, text=text, name=name))
    return out


def invoice_processes(model: dict) -> list[dict]:
    out = []
    for p in model.get("processes", []):
        spec = next(t for t in model["types"] if t["id"] == p["type"])
        if not p.get("gross") or not p.get("party"):
            continue
        pay = next((s for s in p["steps"] if fold(s["label"]) == "bezahlt"), None)
        if pay:
            out.append(dict(p=p, spec=spec, step=pay))
    return out


def paid_dates(proc: dict, step: dict, records: dict, mentions: dict) -> dict[int, date]:
    recs = records.get(proc["type"], [])
    rid_set = {r["id"] for r in recs}
    by_id = {r["id"]: r for rs in records.values() for r in rs}
    d = {}
    for s in [step] + step.get("also", []):
        if s["source"] == "own":
            for r in recs:
                v = as_date(r["data"].get(s["attr"]))
                if v:
                    d[r["id"]] = min(v, d.get(r["id"], v))
        elif s.get("rel_kind") == "mention":
            for dst, srcs in mentions.get(s["rel_attr"], {}).items():
                if dst in rid_set:
                    for x in srcs:
                        v = as_date(by_id.get(x, {}).get("data", {}).get(s["attr"]))
                        if v:
                            d[dst] = min(v, d.get(dst, v))
    for dst, srcs in mentions.get("match", {}).items():
        if dst in rid_set:
            d.setdefault(dst, date.min)
    return d


def find_matches(model: dict, records: dict, mentions: dict, titles: dict) -> list[dict]:
    """Proposals for transfers without a usable reference."""
    out = []
    banks = bank_specs(model)
    procs = invoice_processes(model)
    if not banks or not procs:
        return out
    linked_bank = set()
    for attr, m in mentions.items():
        for dst, srcs in m.items():
            linked_bank.update(srcs)
    specs = {t["id"]: t for t in model["types"]}
    for ip in procs:
        p, step = ip["p"], ip["step"]
        party_attr = next((a for a in ip["spec"]["attrs"] if a["id"] == p["party"]), {})
        outgoing = (specs.get(party_attr.get("ref")) or {}).get("concept") == "lieferant"
        paid = paid_dates(p, step, records, mentions)
        neg = set((p.get("status") or {}).get("negative") or [])
        sattr = (p.get("status") or {}).get("attr")
        open_inv = []
        for r in records.get(p["type"], []):
            if r["id"] in paid or (sattr and str(r["data"].get(sattr)) in neg):
                continue
            g = _num(r["data"].get(p["gross"]))
            if g and g > 0:
                open_inv.append(r)
        by_party: dict[int, list] = {}
        for r in open_inv:
            pv = r["data"].get(p["party"])
            if isinstance(pv, int):
                by_party.setdefault(pv, []).append(r)
        for b in banks:
            for row in records.get(b["spec"]["id"], []):
                if row["id"] in linked_bank:
                    continue
                amount = _num(row["data"].get(b["money"]["id"]))
                when = as_date(row["data"].get(b["date"]["id"]))
                if not amount or not when or (amount < 0) != outgoing:
                    continue
                amount = abs(amount)
                party = row["data"].get(b["party"]["id"]) if b["party"] else None
                cands = by_party.get(party, []) if isinstance(party, int) else []
                if not cands and b["name"] is not None:
                    payer = norm_name(row["data"].get(b["name"]["id"]) or "")
                    if payer:
                        cands = [r for r in open_inv if isinstance(r["data"].get(p["party"]), int)
                                 and name_similarity(payer, norm_name(titles.get(r["data"][p["party"]], ""))) >= 0.85]
                cands = [r for r in cands if (as_date(r["data"].get(p["start"]["attr"])) or date.min) <= when]
                if not cands:
                    continue
                gross = {r["id"]: _num(r["data"].get(p["gross"])) for r in cands}
                exact = [r for r in cands if abs(gross[r["id"]] - amount) < 0.005]
                match, how = None, None
                if exact:
                    exact.sort(key=lambda r: str(r["data"].get(p["start"]["attr"]) or ""))
                    match, how = [exact[0]], "Betrag stimmt auf den Cent" + (" (älteste von mehreren)" if len(exact) > 1 else "")
                else:
                    sk = [r for r in cands if 0.965 * gross[r["id"]] - 0.005 <= amount <= 0.985 * gross[r["id"]] + 0.005]
                    if len(sk) == 1:
                        pct = round((1 - amount / gross[sk[0]["id"]]) * 100, 1)
                        match, how = sk, f"Betrag abzüglich {str(pct).replace('.', ',')} % Skonto"
                    else:
                        pairs = []
                        for i in range(len(cands)):
                            for j in range(i + 1, len(cands)):
                                if abs(gross[cands[i]["id"]] + gross[cands[j]["id"]] - amount) < 0.005:
                                    pairs.append([cands[i], cands[j]])
                        if len(pairs) == 1:
                            match, how = pairs[0], "Summe zweier offener Rechnungen"
                if match:
                    out.append(dict(bank=row["id"], bank_type=b["spec"]["id"], invoices=[r["id"] for r in match],
                                    invoice_type=p["type"], amount=amount, when=when.isoformat(), how=how,
                                    exact=how.startswith("Betrag stimmt"),
                                    payer=titles.get(party) if isinstance(party, int) else
                                    (row["data"].get(b["name"]["id"]) if b["name"] else None)))
    return out


def risk_items(model: dict, records: dict, outrefs: dict, titles: dict) -> list[dict]:
    """Documents that name an unknown bank account of a known partner, or come from a look-alike domain."""
    specs = {t["id"]: t for t in model["types"]}
    by_id = {r["id"]: r for rs in records.values() for r in rs}
    known: dict[int, set] = {}
    domains: dict[int, set] = {}
    for t in model["types"]:
        if t["kind"] != "master":
            continue
        ibans = [a["id"] for a in t["attrs"] if a["kind"] == "iban"]
        mails = [a["id"] for a in t["attrs"] if a["kind"] == "email"]
        for r in records.get(t["id"], []):
            for a in ibans:
                if r["data"].get(a):
                    known.setdefault(r["id"], set()).add(str(r["data"][a]))
            for a in mails:
                e = str(r["data"].get(a) or "").casefold()
                if "@" in e and e.rsplit("@", 1)[1] not in FREEMAIL:
                    domains.setdefault(r["id"], set()).add(e.rsplit("@", 1)[1])
    for b in bank_specs(model):
        if not b["iban"] or not b["party"]:
            continue
        for row in records.get(b["spec"]["id"], []):
            pv = row["data"].get(b["party"]["id"])
            iv = row["data"].get(b["iban"]["id"])
            if isinstance(pv, int) and iv:
                known.setdefault(pv, set()).add(str(iv))
    out = []
    for d in records.get("doc", []):
        text = f"{d['data'].get('doc_title') or ''}\n{d['data'].get('doc_text') or ''}"
        found = {re.sub(r"\s+", "", m).upper() for m in IBAN_RE.findall(text)}
        found = {x for x in found if iban_ok(x)}
        targets = [to for to, attr, kind, how in outrefs.get(d["id"], [])
                   if attr == "doc" and to in by_id and specs.get(by_id[to]["type"], {}).get("kind") == "master"]
        sender = str(d["data"].get("doc_from") or "")
        m = re.search(r"@([\w.-]+\.[a-z]{2,})", sender, re.I)
        sdom = m.group(1).lower() if m else None
        for t in targets:
            reasons = []
            unknown = sorted(x for x in found if known.get(t) and x not in known[t])
            if unknown:
                reasons.append(f"nennt die Bankverbindung {_fmt_iban(unknown[0])}, an die bisher nie gezahlt wurde "
                               f"(bekannt: {', '.join(_fmt_iban(x) for x in sorted(known[t])[:2])})")
            if sdom and domains.get(t) and sdom not in domains[t]:
                close = [x for x in domains[t] if jaro_winkler(sdom, x) >= 0.85]
                if close:
                    reasons.append(f"kommt von „{sdom}“ – ähnlich, aber nicht gleich „{close[0]}“")
            if reasons:
                out.append(dict(rid=d["id"], partner=t, title=titles.get(d["id"], "Dokument"), party=titles.get(t),
                                reason="; ".join(reasons), days=0, money=None))
    return out


def _fmt_iban(s: str) -> str:
    return " ".join(s[i:i + 4] for i in range(0, len(s), 4))
