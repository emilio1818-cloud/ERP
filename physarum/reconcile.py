"""Money has to add up: every euro on the bank statement belongs to a document.

Physarum's "hunger": where the balance does not close (money received, no invoice paid;
an invoice open, a matching transfer without reference), there is work or a missing link.

1. Transfers that name an invoice number are linked by mention discovery already.
2. For the rest, the amount speaks: an incoming transfer that equals exactly one open
   invoice of the same payer, the sum of two of them, or the invoice minus 2-3 % skonto.
   A transfer from the payer of exactly one open invoice of exactly that amount pays it
   (booked, said so on the invoice, undone with one click); the rest are proposals until a
   person confirms them. Both are re-created on every growth (a "no" is stored as decision).
3. Fraud check: a document from a known supplier that names a bank account the company
   has never paid to, or comes from a look-alike domain, is flagged before anyone pays.
"""
from __future__ import annotations

import re
from collections import Counter
from datetime import date

from .billing import is_draft
from .infer.identity import FREEMAIL
from .text import fold, jaro_winkler, name_similarity, norm_name, tokens
from .values import as_date, iban_ok

IBAN_RE = re.compile(r"\b([A-Z]{2}\d{2}(?:\s?[A-Z0-9]{4}){3,7}(?:\s?[A-Z0-9]{1,4})?)\b")


def _num(v):
    return float(v) if isinstance(v, (int, float)) and not isinstance(v, bool) else None


_OUT_WORDS = {"soll", "debit", "ausgabe", "ausgaben", "lastschrift", "belastung", "abgang"}
_IN_WORDS = {"haben", "credit", "einnahme", "einnahmen", "gutschrift", "eingang", "zugang"}


def _split_amount(money: list[dict]) -> tuple[dict, dict] | None:
    """Statements with two amount columns, 'Soll' and 'Haben' (debit and credit), instead of one signed amount."""
    out = next((a for a in money if set(tokens(a["name"])) & _OUT_WORDS), None)
    inc = next((a for a in money if set(tokens(a["name"])) & _IN_WORDS), None)
    return (out, inc) if out and inc and out is not inc else None


def bank_amount(b: dict, data: dict) -> float | None:
    """The signed amount of a bank line: money in is positive, money out negative."""
    if b.get("split"):
        out, inc = b["split"]
        vo, vi = _num(data.get(out["id"])), _num(data.get(inc["id"]))
        if vo is None and vi is None:
            return None
        return round((vi or 0.0) - abs(vo or 0.0), 2)
    return _num(data.get(b["money"]["id"]))


def bank_specs(model: dict) -> list[dict]:
    out = []
    for t in model["types"]:
        if t["kind"] != "transaction" or t.get("incoming") or \
                (t.get("concept") or "") in ("rechnung", "angebot", "auftrag", "bestellung", "einkauf", "gutschrift"):
            continue  # a supplier's invoice names an IBAN and an amount too – it is not a bank statement
        iban = next((a for a in t["attrs"] if a["kind"] == "iban" and not a.get("hidden")), None)
        moneys = [a for a in t["attrs"] if a["kind"] == "money" and not a.get("hidden")]
        money = moneys[0] if moneys else None
        split = _split_amount(moneys)
        date_a = next((a for a in t["attrs"] if a["kind"] in ("date", "datetime") and not a.get("hidden")), None)
        purpose = any(set(tokens(a["name"])) & {"verwendungszweck", "zweck", "buchungstext", "purpose"} for a in t["attrs"])
        if t.get("concept") == "kontobewegung" or (iban and money and date_a) or (purpose and money and date_a):
            if money and date_a:
                party = next((a for a in t["attrs"] if a["kind"] == "ref"), None)
                text = next((a for a in t["attrs"] if a.get("role") == "notes" and not a.get("hidden")), None)
                name = next((a for a in t["attrs"] if a.get("role") in ("name", "person") and a["kind"] == "text"), None)
                out.append(dict(spec=t, money=split[1] if split else money, split=split, date=date_a, party=party,
                                iban=iban, text=text, name=name))
    return out


def invoice_processes(model: dict) -> list[dict]:
    """Invoices someone pays: the ledger's (a step 'bezahlt', or a due date), with a party."""
    from .payments import invoice_specs
    return [ip for ip in invoice_specs(model) if ip["p"].get("party")]


def paid_dates(proc: dict, step: dict | None, records: dict, mentions: dict) -> dict[int, date]:
    if step is None:
        return {}  # the book keeps no paid date: only the money can tell
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


def find_matches(model: dict, records: dict, mentions: dict, titles: dict, ledger: dict | None = None,
                 skip: set | None = None) -> list[dict]:
    """Proposals for transfers without a usable reference. With a ledger, an invoice is open by
    the money that is still missing (a partial payment leaves its remainder to be matched).
    `skip`: rows that do not move money (a list that came by mail)."""
    out = []
    skip = skip or set()
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
        outgoing = bool(ip["spec"].get("incoming")) or (specs.get(party_attr.get("ref")) or {}).get("concept") == "lieferant"
        paid = paid_dates(p, step, records, mentions)
        neg = set((p.get("status") or {}).get("negative") or [])
        sattr = (p.get("status") or {}).get("attr")
        open_inv = []
        rest = {}
        for r in records.get(p["type"], []):
            if is_draft(r):
                continue
            if ledger is not None and r["id"] in ledger:
                e = ledger[r["id"]]
                if e["state"] not in ("offen", "teilbezahlt") or e["open"] <= 0.005:
                    continue
                rest[r["id"]] = e["open"]
                open_inv.append(r)
                continue
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
                if row["id"] in linked_bank or row["id"] in skip:
                    continue
                amount = bank_amount(b, row["data"])
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
                gross = {r["id"]: rest.get(r["id"], _num(r["data"].get(p["gross"]))) for r in cands}
                exact = [r for r in cands if abs(gross[r["id"]] - amount) < 0.005]
                match, how, sure = None, None, False
                if exact:
                    exact.sort(key=lambda r: str(r["data"].get(p["start"]["attr"]) or ""))
                    match, how = [exact[0]], "Betrag stimmt auf den Cent" + (" (älteste von mehreren)" if len(exact) > 1 else "")
                    sure = len(exact) == 1  # the payer has exactly one open invoice of exactly this amount
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
                                    exact=how.startswith("Betrag stimmt"), sure=sure,
                                    payer=titles.get(party) if isinstance(party, int) else
                                    (row["data"].get(b["name"]["id"]) if b["name"] else None)))
    # sure only alone: two transfers for one invoice, or one transfer fitting two lists, is a question
    per_bank = Counter(m["bank"] for m in out)
    per_inv = Counter(i for m in out for i in m["invoices"])
    for m in out:
        if per_bank[m["bank"]] > 1 or any(per_inv[i] > 1 for i in m["invoices"]):
            m["sure"] = False
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
                                reason="; ".join(reasons), days=0, money=None, iban=unknown[0] if unknown else None))
    return out


_SUPPLIER_WORDS = {"lieferant", "kreditor", "rechnungssteller", "supplier", "vendor", "verkaeufer", "seller"}


def _party_key(v):
    """A supplier as a record, or – where there is no list of suppliers – by its written name."""
    if isinstance(v, int) and not isinstance(v, bool):
        return v
    return norm_name(v) or None if isinstance(v, str) else None


def _incoming(model: dict) -> list[tuple[dict, dict, dict | None, dict | None]]:
    """Kinds of supplier invoices: (type, supplier attribute, IBAN attribute, date attribute)."""
    specs = {t["id"]: t for t in model["types"]}
    out = []
    for t in model["types"]:
        if not t.get("incoming") or t["kind"] != "transaction":
            continue
        party = next((a for a in t["attrs"] if a["kind"] == "ref" and (specs.get(a.get("ref")) or {}).get("kind") == "master"), None) \
            or next((a for a in t["attrs"] if a["kind"] == "text" and set(tokens(a["name"])) & _SUPPLIER_WORDS), None)
        if not party:
            continue
        iban = next((a for a in t["attrs"] if a["kind"] == "iban"), None)
        proc = next((p for p in model.get("processes", []) if p["type"] == t["id"]), None)
        dattr = next((a for a in t["attrs"] if proc and a["id"] == proc["start"]["attr"]), None) or \
            next((a for a in t["attrs"] if a["kind"] in ("date", "datetime")), None)
        out.append((t, party, iban, dattr))
    return out


def supplier_items(model: dict, records: dict, outrefs: dict, titles: dict, ledger: dict | None = None,
                   today: date | None = None, reported: set | None = None) -> tuple[list[dict], list[dict]]:
    """Two looks at every supplier invoice before it is paid.
    Risks: it names a bank account none of the supplier's earlier invoices named (and no payment went to).
    Checks: an e-invoice whose figures do not add up, or the first invoice of a supplier nobody knew."""
    today = today or date.today()
    by_id = {r["id"]: r for rs in records.values() for r in rs}
    paid_to: dict = {}
    for b in bank_specs(model):
        who = b["party"] or b["name"]
        if not b["iban"] or not who:
            continue
        for row in records.get(b["spec"]["id"], []):
            iv = row["data"].get(b["iban"]["id"])
            keys = {_party_key(row["data"].get(who["id"]))}
            if b["party"] and b["name"]:
                keys.add(_party_key(row["data"].get(b["name"]["id"])))
            if b["party"] and isinstance(row["data"].get(b["party"]["id"]), int):
                keys.add(_party_key(titles.get(row["data"][b["party"]["id"]])))
            for k in keys - {None}:
                if iv:
                    paid_to.setdefault(k, set()).add(re.sub(r"\s+", "", str(iv)).upper())
    master_ibans: dict[int, set] = {}
    for t in model["types"]:
        if t["kind"] == "master":
            for a in (a for a in t["attrs"] if a["kind"] == "iban"):
                for r in records.get(t["id"], []):
                    if r["data"].get(a["id"]):
                        master_ibans.setdefault(r["id"], set()).add(re.sub(r"\s+", "", str(r["data"][a["id"]])).upper())
    risks, checks = [], []
    per_supplier: dict = {}
    names: dict = {}
    for t, party, iban, dattr in _incoming(model):
        for r in records.get(t["id"], []):
            raw = r["data"].get(party["id"])
            pv = _party_key(raw)
            if pv is None:
                continue
            names[pv] = titles.get(raw) if isinstance(raw, int) else raw
            when = as_date(r["data"].get(dattr["id"])) if dattr else None
            iv = re.sub(r"\s+", "", str(r["data"].get(iban["id"]) or "")).upper() if iban else ""
            per_supplier.setdefault(pv, []).append((when or date.min, r["id"], iv))
    history = sum(1 for v in per_supplier.values() if len(v) >= 2)
    for pv, invs in per_supplier.items():
        invs.sort()
        seen: set = set()
        paid = paid_to.get(pv, set()) | paid_to.get(_party_key(names.get(pv)), set())
        for k, (when, rid, iv) in enumerate(invs):
            e = (ledger or {}).get(rid) or {}
            open_ = e.get("state") in (None, "offen", "teilbezahlt") and (e.get("open") is None or e.get("open", 0) > 0.005)
            recent = when != date.min and (today - when).days <= 60
            known = seen | (master_ibans.get(pv, set()) if isinstance(pv, int) else set()) | paid
            if iv and known and iv not in known and open_ and recent and (pv, iv) not in (reported or set()):
                risks.append(dict(rid=rid, partner=pv if isinstance(pv, int) else None, title=titles.get(rid, "Rechnung"),
                                  party=names.get(pv),
                                  reason=f"nennt die Bankverbindung {_fmt_iban(iv)}; frühere Rechnungen und Zahlungen: "
                                         f"{', '.join(_fmt_iban(x) for x in sorted(known)[:2])}", days=0, money=None))
            if k == 0 and history >= 3 and open_ and recent and not paid:
                checks.append(dict(rid=rid, partner=pv if isinstance(pv, int) else None, title=titles.get(rid, "Rechnung"),
                                   party=names.get(pv),
                                   reason="erste Rechnung dieses Lieferanten – vor der ersten Zahlung die Bankverbindung "
                                          "über eine bekannte Telefonnummer bestätigen", days=0, money=None))
            if iv:
                seen.add(iv)
    for d in records.get("doc", []):
        note = d["data"].get("doc_check")
        if not note:
            continue
        partner = next((to for to, attr, kind, how in outrefs.get(d["id"], []) if to in by_id and
                        any(by_id[to]["type"] == t["id"] for t, *_ in _incoming(model))), None)
        if partner is not None:
            e = (ledger or {}).get(partner) or {}
            if e.get("state") in ("bezahlt", "überzahlt", "verrechnet", "storniert"):
                continue  # paid long ago: no longer a reason to look before paying
        checks.append(dict(rid=d["id"], partner=partner, title=titles.get(d["id"], "E-Rechnung"),
                           party=titles.get(partner) if partner else None, reason=note, days=0, money=None))
    return risks, checks


def _fmt_iban(s: str) -> str:
    return " ".join(s[i:i + 4] for i in range(0, len(s), 4))
