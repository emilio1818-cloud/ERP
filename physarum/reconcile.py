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
from collections import Counter, defaultdict
from datetime import date
from itertools import combinations

from .billing import is_draft
from .lexicon import SALUTATIONS, TITLES
from .infer.identity import FREEMAIL
from .text import fold, jaro_winkler, name_similarity, norm_name, tokens
from .pdfinvoice import is_own, norm
from .values import as_date, as_number, iban_ok

IBAN_RE = re.compile(r"\b([A-Z]{2}\d{2}(?:\s?[A-Z0-9]{4}){3,7}(?:\s?[A-Z0-9]{1,4})?)\b")


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
        vo, vi = as_number(data.get(out["id"])), as_number(data.get(inc["id"]))
        if vo is None and vi is None:
            return None
        return round((vi or 0.0) - abs(vo or 0.0), 2)
    return as_number(data.get(b["money"]["id"]))


def bank_specs(model: dict) -> list[dict]:
    out = []
    for t in model["types"]:
        if t["kind"] != "transaction" or t.get("incoming") or \
                (t.get("concept") or "") in ("rechnung", "angebot", "auftrag", "bestellung", "einkauf", "gutschrift"):
            continue  # a supplier's invoice names an IBAN and an amount too – it is not a bank statement
        iban = next((a for a in t["attrs"] if a["kind"] == "iban" and not a.get("hidden")), None)
        moneys = [a for a in t["attrs"] if a["kind"] == "money" and not a.get("hidden")]
        # the amount stands on every line; "Lastschrift Ursprungsbetrag" before it only on returns
        money = max(moneys, key=lambda a: a.get("fill") or 0) if moneys else None
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
    inv_types = {ip["p"]["type"] for ip in procs}
    type_of = {r["id"]: tid for tid, rs in records.items() for r in rs}
    linked_bank, about = set(), defaultdict(set)  # rows that name an invoice; what the others name
    for attr, m in mentions.items():
        for dst, srcs in m.items():
            if type_of.get(dst) in inv_types:
                linked_bank.update(srcs)
            else:
                for s in srcs:
                    about[s].add(dst)
    specs = {t["id"]: t for t in model["types"]}
    for ip in procs:
        p, step = ip["p"], ip["step"]
        party_attr = next((a for a in ip["spec"]["attrs"] if a["id"] == p["party"]), {})
        outgoing = bool(ip["spec"].get("incoming")) or (specs.get(party_attr.get("ref")) or {}).get("concept") == "lieferant"
        paid = paid_dates(p, step, records, mentions)
        neg = set((p.get("status") or {}).get("negative") or [])
        sattr = (p.get("status") or {}).get("attr")
        open_inv = []
        listed = []  # paid by the book's date alone: the bank line that paid them may be a collection
        rest = {}
        for r in records.get(p["type"], []):
            if is_draft(r):
                continue
            if ledger is not None and r["id"] in ledger:
                e = ledger[r["id"]]
                if e["state"] == "bezahlt" and e["payments"] and all(x["rid"] is None and x["how"] == "laut Liste bezahlt"
                                                                     for x in e["payments"]):
                    listed.append(r)
                    rest[r["id"]] = e["gross"] - e["credit"]
                if e["state"] not in ("offen", "teilbezahlt") or e["open"] <= 0.005:
                    continue
                rest[r["id"]] = e["open"]
                open_inv.append(r)
                continue
            if r["id"] in paid or (sattr and str(r["data"].get(sattr)) in neg):
                continue
            g = as_number(r["data"].get(p["gross"]))
            if g and g > 0:
                open_inv.append(r)
        by_party: dict[int, list] = {}
        listed_of: dict[int, list] = {}
        for r in open_inv:
            pv = r["data"].get(p["party"])
            if isinstance(pv, int):
                by_party.setdefault(pv, []).append(r)
        for r in listed:
            pv = r["data"].get(p["party"])
            if isinstance(pv, int):
                listed_of.setdefault(pv, []).append(r)
        if not outgoing:
            out.extend(_direct_debits(banks, records, open_inv + listed, rest, p, linked_bank | skip))
        iban_party = _iban_history(banks, records, ledger, p, model) if p.get("party") else {}
        start = lambda r: as_date(r["data"].get(p["start"]["attr"]))  # noqa: E731
        gross = {r["id"]: rest.get(r["id"], as_number(r["data"].get(p["gross"]))) for r in open_inv + listed}
        known_payer = defaultdict(list)  # payer -> their transfers that name no invoice and no date
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
                via_iban = False
                if not cands and b["iban"] is not None:
                    # the account is the customer's: their list gives it, or it paid their invoices with numbers
                    known = iban_party.get(str(row["data"].get(b["iban"]["id"]) or "").replace(" ", "").upper())
                    if known and len(known) == 1:
                        party = next(iter(known))
                        cands, via_iban = by_party.get(party, []), True
                if not cands and (b["name"] is not None or b["party"] is not None):
                    # who paid, as written: the name column, or the payer the lists do not know
                    payer = norm_name((row["data"].get(b["name"]["id"]) if b["name"] else None) or
                                      (((row.get("meta") or {}).get("raw") or {}).get(b["party"]["id"]) if b["party"] else None)
                                      or "")
                    if payer:
                        cands = [r for r in open_inv if isinstance(r["data"].get(p["party"]), int)
                                 and name_similarity(payer, norm_name(titles.get(r["data"][p["party"]], ""))) >= 0.85]
                        who = {r["data"][p["party"]] for r in cands}
                        if len(who) == 1 and not isinstance(party, int):
                            party = next(iter(who))  # the payer is this customer
                        if not cands:  # the invoice names someone in no list: "Fischer, Jan und Petra" pays "Fam. Fischer"
                            cands = [r for r in open_inv if not isinstance(r["data"].get(p["party"]), int) and
                                     _named_alike(payer, ((r.get("meta") or {}).get("raw") or {}).get(p["party"]))]
                text = " ".join(str(row["data"].get(a["id"]) or "") for a in b["spec"]["attrs"] if a["kind"] == "text")
                named = {as_date(m) for m in _INVOICE_OF.findall(text)} - {None}
                if named and isinstance(party, int):
                    # "Ihre Rechnung vom 31.07.2026": that one, also when the book has ticked it off already
                    dated = [r for r in by_party.get(party, []) + listed_of.get(party, []) if start(r) in named]
                    if dated:
                        out.append(_proposal(row, b, dated[:1], p, amount, when, "Rechnungsdatum wie im Zweck",
                                             abs(gross[dated[0]["id"]] - amount) < 0.005, titles, party))
                    continue  # a date of an invoice the lists do not have: not one of these
                if not cands and about.get(row["id"]):
                    # the purpose names what an invoice was for – the car "LP-PN 88", the order –, not who pays
                    cands = [r for r in open_inv if about[row["id"]] & {v for v in r["data"].values() if isinstance(v, int)}]
                if not cands and named:
                    # "Ihre Rechnung vom 15.04.2026" from someone else (the owners' association pays for the manager)
                    cands = [r for r in open_inv if start(r) in named]
                cands = [r for r in cands if (start(r) or date.min) <= when]
                if not cands:
                    continue
                if isinstance(party, int) and not named and not about.get(row["id"]) and \
                        all(r["data"].get(p["party"]) == party for r in cands):
                    known_payer[party].append((when, row["id"], row, b, amount, cands, via_iban, text))
                    continue
                exact = [r for r in cands if abs(gross[r["id"]] - amount) < 0.005]
                if len(exact) > 1 and named:
                    exact = [r for r in exact if start(r) in named] or exact  # the date the purpose names decides
                if exact:
                    exact.sort(key=lambda r: str(r["data"].get(p["start"]["attr"]) or ""))
                    out.append(_proposal(row, b, exact[:1], p, amount, when, "Betrag stimmt auf den Cent" +
                                         (" (älteste von mehreren)" if len(exact) > 1 else ""), len(exact) == 1,
                                         titles, party))
                    continue
                sk = [r for r in cands if 0.965 * gross[r["id"]] - 0.005 <= amount <= 0.985 * gross[r["id"]] + 0.005]
                if len(sk) == 1:
                    pct = round((1 - amount / gross[sk[0]["id"]]) * 100, 1)
                    out.append(_proposal(row, b, sk, p, amount, when, f"Betrag abzüglich {str(pct).replace('.', ',')} % Skonto",
                                         False, titles, party))
        # a known payer who names nothing pays the oldest open first (§ 366 Abs. 2 BGB), in the order the
        # money came: on the cent one invoice, the oldest of several alike, or the oldest few together
        for party, rows in known_payer.items():
            left = {r["id"]: gross[r["id"]] for x in rows for r in x[5]}
            for when, _rid, row, b, amount, cands, via_iban, text in sorted(rows, key=lambda x: (x[0], x[1])):
                open_ = sorted((r for r in cands if left[r["id"]] > 0.005),
                               key=lambda r: (str(r["data"].get(p["start"]["attr"]) or ""), r["id"]))
                if not open_:
                    continue
                exact = [r for r in open_ if abs(left[r["id"]] - amount) < 0.005]
                sk = [r for r in open_ if 0.965 * left[r["id"]] - 0.005 <= amount <= 0.985 * left[r["id"]] + 0.005]
                sure = True
                if exact:
                    take, how = exact[:1], "Betrag stimmt auf den Cent" + (" (älteste von mehreren)" if len(exact) > 1 else "")
                elif len(sk) == 1 and sk[0] is open_[0]:
                    pct = round((1 - amount / left[sk[0]["id"]]) * 100, 1)
                    take, how, sure = sk, f"Betrag abzüglich {str(pct).replace('.', ',')} % Skonto", False
                else:  # the oldest ones on the cent; less, or more, may be money for something else
                    take, acc = [], 0.0
                    for r in open_:
                        if acc >= amount - 0.005:
                            break
                        take.append(r)
                        acc += left[r["id"]]
                    how = f"Summe der {len(take)} ältesten offenen Rechnungen"
                    if abs(acc - amount) >= 0.005:
                        # one transfer for two, one of them perhaps ticked off in the book already
                        both = open_ + [r for r in listed_of.get(party, []) if (start(r) or date.min) <= when]
                        pairs = [c for c in combinations(both, 2) if (c[0] in open_ or c[1] in open_) and
                                 abs(left.get(c[0]["id"], gross[c[0]["id"]]) + left.get(c[1]["id"], gross[c[1]["id"]])
                                     - amount) < 0.005]
                        if len(pairs) != 1:
                            continue
                        take, how = list(pairs[0]), "Summe zweier Rechnungen"
                        sure = bool(_COLLECTIVE.search(text)) or len(open_) == 2  # "Sammelzahlung lt. Aufstellung"
                if via_iban:
                    how += ", das Konto ist das des Kunden"
                money = amount
                for r in take:
                    used = min(left.get(r["id"], gross[r["id"]]), money)
                    left[r["id"]] = left.get(r["id"], gross[r["id"]]) - used
                    money -= used
                m = _proposal(row, b, take, p, amount, when, how, sure, titles, party)
                m["in_turn"] = True  # one after the other: two of them may each pay part of the same invoice
                out.append(m)
    # sure only alone: two transfers for one invoice, or one transfer fitting two lists, is a question
    per_bank = Counter(m["bank"] for m in out)
    per_inv = Counter(i for m in out if not m.get("in_turn") for i in m["invoices"])
    turn_inv = {i for m in out if m.get("in_turn") for i in m["invoices"]}
    for m in out:
        if per_bank[m["bank"]] > 1 or any(per_inv[i] > 1 or (per_inv[i] and i in turn_inv) for i in m["invoices"]):
            m["sure"] = False
    return out


def _proposal(row, b, invs, p, amount, when, how, sure, titles, party) -> dict:
    return dict(bank=row["id"], bank_type=b["spec"]["id"], invoices=[r["id"] for r in invs], invoice_type=p["type"],
                amount=amount, when=when.isoformat(), how=how, exact=how.startswith("Betrag stimmt"), sure=sure,
                payer=titles.get(party) if isinstance(party, int) else
                (row["data"].get(b["name"]["id"]) if b["name"] else None))


_PEOPLE = SALUTATIONS | TITLES


def _named_alike(payer: str, name) -> bool:
    """Every word of the shorter name is in the longer one, salutations aside, and it is more than an initial."""
    if not isinstance(name, str):
        return False
    a, b = ({w for w in norm_name(x).split() if w not in _PEOPLE} for x in (payer, name))
    small, big = sorted((a, b), key=len)
    return bool(small) and small <= big and sum(len(w) for w in small) >= 4


_INVOICE_OF = re.compile(r"rechnung(?:en)?\s+(?:vom|v\.)\s*(\d{1,2}\.\d{1,2}\.\d{2,4})", re.I)
_COLLECTIVE = re.compile(r"sammel|aufstellung|rechnungen\b|div\.\s*re", re.I)


def master_ibans(model: dict, records: dict) -> dict[str, set]:
    """{IBAN: the customers (or suppliers) whose own list gives that account} – for the direct debit, mostly."""
    out: dict[str, set] = {}
    for t in model["types"]:
        if t["kind"] == "master":
            for a in (a for a in t["attrs"] if a["kind"] == "iban"):
                for r in records.get(t["id"], []):
                    iv = re.sub(r"\s+", "", str(r["data"].get(a["id"]) or "")).upper()
                    if len(iv) >= 15:
                        out.setdefault(iv, set()).add(r["id"])
    return out


def _iban_history(banks, records, ledger, p, model) -> dict[str, set]:
    """{IBAN: customers whose invoices it paid, or whose list gives it} – a payer is known by the account."""
    party_of = {r["id"]: r["data"].get(p["party"]) for r in records.get(p["type"], [])}
    rows = {r["id"]: (b, r) for b in banks for r in records.get(b["spec"]["id"], []) if b["iban"] is not None}
    out: dict[str, set] = {}
    for inv, e in (ledger or {}).items():
        pv = party_of.get(inv)
        if not isinstance(pv, int):
            continue
        for x in e["payments"]:
            if x.get("rid") in rows and not x.get("by_amount"):
                b, r = rows[x["rid"]]
                iv = str(r["data"].get(b["iban"]["id"]) or "").replace(" ", "").upper()
                if len(iv) >= 15:
                    out.setdefault(iv, set()).add(pv)
    for iv, rids in master_ibans(model, records).items():
        out.setdefault(iv, set(rids))  # what the account paid says more than a list (two records of one customer)
    return out


_COLLECTION = re.compile(r"lastschrift|sammler|sammel-?ls|einreichung|einzug", re.I)
_POSTEN = re.compile(r"\b(\d{1,2})\s*(?:posten|pos\.|positionen|lastschriften)\b", re.I)
_SUBMITTED = re.compile(r"einreichung\s*(?:vom\s*)?(\d{1,2}\.\d{1,2}\.\d{2,4})", re.I)
_BOILER = {"sepa", "lastschrift", "sammler", "sammel", "posten", "einreichung", "gutschrift", "eingang", "vom", "ls",
           "basis", "core", "firmen", "einzug", "lastschriften", "gesamt", "summe"}


def _direct_debits(banks, records, open_inv, rest, p, taken) -> list[dict]:
    """The firm's own direct debits come back as one credit: "SEPA-LASTSCHRIFT-SAMMLER 3 POSTEN
    EINREICHUNG 16.10.2026 WARTUNG". The open invoices it collected are the only N of them, dated
    before the submission, whose amounts add up to the cent – preferably those whose text shares the
    credit's words ("Wartung")."""
    out = []
    for b in banks:
        for row in records.get(b["spec"]["id"], []):
            if row["id"] in taken:
                continue
            text = " ".join(str(row["data"].get(a["id"]) or "") for a in b["spec"]["attrs"] if a["kind"] == "text")
            m = _POSTEN.search(text)
            if not m or not _COLLECTION.search(text):
                continue
            n = int(m.group(1))
            amount = bank_amount(b, row["data"])
            when = as_date(row["data"].get(b["date"]["id"]))
            if not (2 <= n <= 5) or not amount or amount <= 0 or not when:
                continue
            sub = _SUBMITTED.search(text)
            until = (as_date(sub.group(1)) if sub else None) or when
            cands = [r for r in open_inv if (as_date(r["data"].get(p["start"]["attr"])) or date.max) <= until
                     and (until - as_date(r["data"].get(p["start"]["attr"]))).days <= 90]
            words = {w for w in tokens(text) if len(w) >= 4 and not w.isdigit() and w not in _BOILER}
            if words:
                topical = [r for r in cands if words & set(tokens(" ".join(str(v) for v in r["data"].values()
                                                                           if isinstance(v, str))))]
                if len(topical) >= n:
                    cands = topical
            cands = sorted(cands, key=lambda r: str(r["data"].get(p["start"]["attr"]) or ""), reverse=True)[:40]
            owed = {r["id"]: rest.get(r["id"], as_number(r["data"].get(p["gross"])) or 0.0) for r in cands}
            fits = [c for c in combinations(cands, n) if abs(sum(owed[r["id"]] for r in c) - amount) < 0.005]
            if len(fits) != 1:
                continue
            out.append(dict(bank=row["id"], bank_type=b["spec"]["id"], invoices=[r["id"] for r in fits[0]],
                            invoice_type=p["type"], amount=amount, when=when.isoformat(), exact=True, sure=True,
                            how=f"Sammel-Lastschrift: {n} Posten, die Summe stimmt auf den Cent", payer=None))
    return out


def risk_items(model: dict, records: dict, outrefs: dict, titles: dict, ledger: dict | None = None) -> list[dict]:
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
    # whom the firm pays: only their accounts can be swapped on it (a customer's letter names the firm's own)
    payees = {r["id"] for t in model["types"] if t.get("concept") == "lieferant" for r in records.get(t["id"], [])}
    for t, sup, _iban, _when in _incoming(model):
        payees |= {v for r in records.get(t["id"], []) if isinstance(v := r["data"].get(sup["id"]), int)}
    party_of = {p["type"]: p.get("party") for p in model.get("processes", [])}
    for rid, e in (ledger or {}).items():  # the firm owes them: paid twice, a credit note not paid out
        rec = by_id.get(rid)
        if rec and (0 < e["gross"] - e.get("credit", 0.0) < e["paid"] - 0.01 or (e["gross"] < -0.01 and not e.get("credit_to") and e["open"] < -0.01)) and \
                isinstance(v := rec["data"].get(party_of.get(rec["type"])), int):
            payees.add(v)
    for b in bank_specs(model):
        if not b["iban"] or not b["party"]:
            continue
        for row in records.get(b["spec"]["id"], []):
            pv = row["data"].get(b["party"]["id"])
            iv = row["data"].get(b["iban"]["id"])
            if isinstance(pv, int) and iv:
                known.setdefault(pv, set()).add(str(iv))
                if (bank_amount(b, row["data"]) or 0) < 0:
                    payees.add(pv)
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
            unknown = sorted(x for x in found if t in payees and known.get(t) and x not in known[t])
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
    from .pdfinvoice import _NEW_BANK
    announces = set()  # a mail or letter that says the account has changed – the classic opening of the fraud
    incoming_ids = {t["id"] for t, *_ in _incoming(model)}
    for d in records.get("doc", []):
        if _NEW_BANK.search(str(d["data"].get("doc_text") or "")):
            announces |= {to for to, attr, kind, how in outrefs.get(d["id"], []) if to in by_id
                          and by_id[to]["type"] in incoming_ids}
    for t, party, iban, dattr in _incoming(model):
        mail = next((a for a in t["attrs"] if a["kind"] == "email"), None)
        for r in records.get(t["id"], []):
            raw = r["data"].get(party["id"])
            pv = _party_key(raw)
            if pv is None:
                continue
            names[pv] = titles.get(raw) if isinstance(raw, int) else raw
            when = as_date(r["data"].get(dattr["id"])) if dattr else None
            iv = re.sub(r"\s+", "", str(r["data"].get(iban["id"]) or "")).upper() if iban else ""
            sender = str(r["data"].get(mail["id"]) or "").casefold() if mail else ""
            dom = sender.rsplit("@", 1)[1] if "@" in sender else ""
            per_supplier.setdefault(pv, []).append((when or date.min, r["id"], iv, dom))
    history = sum(1 for v in per_supplier.values() if len(v) >= 2)
    for pv, invs in per_supplier.items():
        invs.sort()
        seen: set = set()
        seen_dom: set = set()
        paid = paid_to.get(pv, set()) | paid_to.get(_party_key(names.get(pv)), set())
        for k, (when, rid, iv, dom) in enumerate(invs):
            e = (ledger or {}).get(rid) or {}
            open_ = e.get("state") in (None, "offen", "teilbezahlt") and (e.get("open") is None or e.get("open", 0) > 0.005)
            recent = when != date.min and (today - when).days <= 60
            known = seen | (master_ibans.get(pv, set()) if isinstance(pv, int) else set()) | paid
            reasons = []
            if iv and known and iv not in known and (pv, iv) not in (reported or set()):
                reasons.append(f"nennt die Bankverbindung {_fmt_iban(iv)}; frühere Rechnungen und Zahlungen: "
                               f"{', '.join(_fmt_iban(x) for x in sorted(known)[:2])}")
            if dom and seen_dom and dom not in seen_dom:
                close = [x for x in sorted(seen_dom) if jaro_winkler(dom, x) >= 0.85 or x in dom or dom in x]
                if close:
                    reasons.append(f"kam von „{dom}“ – ähnlich, aber nicht gleich „{close[0]}“ der früheren Rechnungen")
            if reasons and rid in announces:
                reasons.append("dazu die Nachricht, die Bankverbindung habe sich geändert")
            if reasons and open_ and recent:
                risks.append(dict(rid=rid, partner=pv if isinstance(pv, int) else None, title=titles.get(rid, "Rechnung"),
                                  party=names.get(pv), reason="; ".join(reasons), days=0, money=e.get("open"),
                                  iban=iv or None))
            if k == 0 and history >= 3 and open_ and recent and not paid:
                checks.append(dict(rid=rid, partner=pv if isinstance(pv, int) else None, title=titles.get(rid, "Rechnung"),
                                   party=names.get(pv),
                                   reason="erste Rechnung dieses Lieferanten – vor der ersten Zahlung die Bankverbindung "
                                          "über eine bekannte Telefonnummer bestätigen", days=0, money=None))
            if iv and not reasons:
                seen.add(iv)  # an account in doubt is no evidence for the next invoice
            if dom and not reasons:
                seen_dom.add(dom)
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


def received_twice(model: dict, records: dict, outrefs: dict) -> dict[int, list[str]]:
    """Supplier invoices that came in as two files (the PDF from the mail and a scan of the printout):
    the same number and amount – one invoice, to be paid once."""
    from .pdfinvoice import read
    incoming = {t["id"] for t, *_ in _incoming(model)}
    by_id = {r["id"]: r for t in incoming for r in records.get(t, [])}
    files: dict[int, dict] = {}
    for d in records.get("doc", []):
        if str(d["data"].get("doc_kind") or "") != "PDF":
            continue
        targets = {to for to, attr, kind, how in outrefs.get(d["id"], []) if to in by_id}
        if not targets:
            continue
        inv = read(str(d["data"].get("doc_text") or ""))
        if not inv:
            continue
        for to in targets:
            key = (inv["number"], round(inv["gross"], 2))
            name = str(d["data"].get("doc_file") or d["data"].get("doc_title"))
            files.setdefault(to, {}).setdefault(key, []).append(name.replace("\\", "/").rsplit("/", 1)[-1])
    return {rid: sorted(fs) for rid, per in files.items() for fs in per.values() if len(set(fs)) >= 2}


_KEYLIKE = re.compile(r"\b[A-Z]{1,4}-?\d{2,4}-\d{2,5}\b|\b[A-Z]{1,3}\d{2}-\d{3,4}\b")
_OWN_MOVES = ("umbuchung", "uebertrag", "kontouebertrag", "eigene", "sparbuch", "tagesgeld")


def unexplained_receipts(model: dict, records: dict, ledger: dict, titles: dict, today: date,
                         pending: set | None = None, days: int = 60, own: set | None = None) -> list[dict]:
    """Money that came in and pays no invoice: an advance on an order nobody invoiced yet, a supplier's
    credit for a return, or something to ask about. The last two months. A payer whose money comes
    again and again without ever paying an invoice (the shop's weekly payout, a tenant's rent) is a
    known source of income, not a question."""
    specs = {t["id"]: t for t in model["types"]}
    by_id = {r["id"]: r for rs in records.values() for r in rs}
    used = {p.get("rid") for e in (ledger or {}).values() for p in e.get("payments", [])}
    keyed: dict[str, int] = {}
    for t in model["types"]:
        if (t.get("concept") or "") in ("angebot", "auftrag", "vertrag", "projekt") and t.get("key"):
            for r in records.get(t["id"], []):
                k = r["data"].get(t["key"])
                if isinstance(k, str) and len(k) >= 5:
                    keyed[k.upper()] = r["id"]
    suppliers = {}  # the IBAN or the name of a supplier whose invoices we pay
    for t, party, iban, _d in _incoming(model):
        for r in records.get(t["id"], []):
            name = r["data"].get(party["id"])
            name = titles.get(name) if isinstance(name, int) else name
            if iban and r["data"].get(iban["id"]):
                suppliers[re.sub(r"\s+", "", str(r["data"][iban["id"]])).upper()] = name
            if isinstance(name, str):
                suppliers[norm_name(name)] = name
    inv = next((t for t in model["types"] if t.get("concept") == "rechnung" and not t.get("incoming")), None)

    def who_of(b, r):  # as written, or the partner the name column links to
        if b["name"]:
            return r["data"].get(b["name"]["id"])
        v = r["data"].get(b["party"]["id"]) if b["party"] else None
        return titles.get(v) if isinstance(v, int) else (((r.get("meta") or {}).get("raw") or {}).get(b["party"]["id"])
                                                         if b["party"] else None)

    def payer(b, r):
        iv = re.sub(r"\s+", "", str(r["data"].get(b["iban"]["id"]) or "")).upper() if b["iban"] else ""
        who = who_of(b, r)
        return iv if len(iv) >= 15 else norm_name(str(who)) if who else ""

    days_of, paying = defaultdict(set), set()  # payer -> days money came in; payers whose money paid invoices
    for b in bank_specs(model):
        for r in records.get(b["spec"]["id"], []):
            v = r["data"].get(b["money"]["id"])
            when = as_date(r["data"].get(b["date"]["id"]))
            k = payer(b, r)
            if k and isinstance(v, (int, float)) and not isinstance(v, bool) and v > 0.005 and when:
                days_of[k].add(when)
                if r["id"] in used:
                    paying.add(k)
    regular = {k for k, ds in days_of.items() if len(ds) >= 3 and k not in paying}
    out = []
    for b in bank_specs(model):
        for r in records.get(b["spec"]["id"], []):
            v = r["data"].get(b["money"]["id"])
            when = as_date(r["data"].get(b["date"]["id"]))
            if not isinstance(v, (int, float)) or isinstance(v, bool) or v <= 0.005 or not when \
                    or (today - when).days > days or when > today or r["id"] in used or r["id"] in (pending or ()):
                continue
            text = str(r["data"].get(b["text"]["id"]) or "") if b["text"] else ""
            who = who_of(b, r)
            mine = {norm(n) for n in own or ()}
            selves = sum(1 for v in r["data"].values() if isinstance(v, str) and mine and is_own(v, mine))
            if any(w in fold(text) for w in _OWN_MOVES) or (mine and who and is_own(str(who), mine)) or selves >= 2:
                continue  # money from the firm to the firm: between its accounts, its collective debit, its cash
            if payer(b, r) in regular:
                continue  # comes every week or month and never pays an invoice: a known income
            iv = re.sub(r"\s+", "", str(r["data"].get(b["iban"]["id"]) or "")).upper() if b["iban"] else ""
            supplier = suppliers.get(iv) or suppliers.get(norm_name(who)) if (iv or who) else None
            item = dict(rid=r["id"], title=titles.get(r["id"]) or f"{when.strftime('%d.%m.%Y')} · {v:.2f} €",
                        party=str(who) if who else None, days=(today - when).days, money=round(float(v), 2), act=None)
            named = [keyed[m.group(0).upper()] for m in _KEYLIKE.finditer(text) if m.group(0).upper() in keyed]
            if supplier:
                item["reason"] = f"von {supplier} (Lieferant) – eine Gutschrift oder Erstattung, keine Kundenzahlung"
            elif named:
                case = by_id[named[0]]
                order = case
                if (specs[case["type"]].get("concept") or "") == "angebot":
                    # the offer the customer accepted: its order is what the advance is for
                    order = next((by_id[x] for x in case["data"].values() if isinstance(x, int) and x in by_id
                                  and (specs[by_id[x]["type"]].get("concept") or "") == "auftrag"), None) or \
                        next((o for t in model["types"] if t.get("concept") == "auftrag" for o in records.get(t["id"], [])
                              if case["id"] in o["data"].values()), case)
                what = titles.get(case["id"]) + (f" (Auftrag {titles.get(order['id'])})" if order is not case else "")
                item["reason"] = f"Anzahlung zu {what} – dazu gibt es noch keine Rechnung"
                refs = [a for a in (inv or {}).get("attrs", []) if a["kind"] == "ref" and not a.get("hidden")]
                ref = next((a["id"] for a in refs if a.get("ref") == order["type"]), None)
                if ref:
                    item["act"] = dict(href=f"/t/{inv['id']}/neu?a_{ref}={order['id']}", label="+ Anzahlungsrechnung")
                else:  # the invoice book names no orders: an invoice for the customer of that order
                    who_ref = next(((a["id"], v) for a in refs for v in order["data"].values()
                                    if isinstance(v, int) and v in by_id and by_id[v]["type"] == a.get("ref")), None)
                    if who_ref:
                        item["act"] = dict(href=f"/t/{inv['id']}/neu?a_{who_ref[0]}={who_ref[1]}",
                                           label="+ Anzahlungsrechnung")
            else:
                item["reason"] = "keiner Rechnung zugeordnet – wofür war das?"
            if not item["act"]:
                item["act"] = dict(href=f"/r/{r['id']}#zuordnen", label="Zuordnen")
            out.append(item)
    out.sort(key=lambda x: -x["money"])
    return out


def _fmt_iban(s: str) -> str:
    return " ".join(s[i:i + 4] for i in range(0, len(s), 4))
