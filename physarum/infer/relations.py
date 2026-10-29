"""Relations: references between types, found in the values themselves.

* Structural references come from normalisation (order line -> order).
* Value references: a column whose values are (mostly) numbers, names or e-mails of
  another type's records ("Kd-Nr" -> Kunde, "Lieferant" -> Lieferant by name).
* Mentions: identifiers inside free text ("RE-2026-0130" in a bank transfer's purpose,
  an article number in an e-mail). This is how a bank statement pays invoices without
  anybody configuring a reconciliation rule.
"""
from __future__ import annotations

import re
from collections import Counter, defaultdict
from dataclasses import dataclass, field

from .. import lexicon
from ..text import fold, name_similarity, norm_key, norm_name, tokens
from .identity import FREEMAIL, Group, _within
from .unify import AttrDraft, TypeDraft

REF_ROLES = {"id", "name", "person", None, "email"}


@dataclass
class RelDraft:
    src: TypeDraft
    attr: AttrDraft
    dst: TypeDraft
    via: str                 # k (number) | e (e-mail) | n (name)
    kind: str = "ref"        # ref | parent | mention
    inclusion: float = 0.0
    coverage: float = 0.0
    hits: int = 0
    fuzzy: int = 0
    structural: bool = False
    evidence: str = ""
    rid: str | None = None
    targets: dict = field(default_factory=dict)   # src group index -> dst group index (ref) or [indices] (mention)
    unresolved: dict = field(default_factory=dict)  # src group index -> raw value
    extra: list = field(default_factory=list)       # further target types for parties: [(TypeDraft, {gi: dgi})]
    multi: set = field(default_factory=set)         # src groups linked through the first of several numbers


class IdentIndex:
    def __init__(self, groups: list[Group], title: str | None = None, alt: dict | None = None):
        self.alt = alt or {}
        self.by: dict[str, int] = {}
        self.names: dict[str, list[tuple[str, int]]] = defaultdict(list)
        self.words: dict[str, set[int]] = defaultdict(set)        # word prefix -> groups whose name has it
        self.wordsets: dict[int, list[set]] = defaultdict(list)
        ambiguous = set()
        for i, g in enumerate(groups):
            for ident in g.idents:
                if ident in self.by and self.by[ident] != i:
                    ambiguous.add(ident)
                self.by.setdefault(ident, i)
                if ident.startswith("n:"):
                    nm = ident[2:]
                    for tok in nm.split()[:2]:
                        if len(tok) >= 3:
                            self.names[tok[:3]].append((nm, i))
            # every name a thing goes by, even one two records share (then a short name cannot decide)
            spoken = {norm_name(g.values[title])} if title and g.values.get(title) else set()
            spoken |= {norm_name(v) for v, _ in (g.alts.get(title) or [])} if title else set()
            spoken |= {x[2:] for x in g.idents if x.startswith("n:")}
            for nm in spoken - {""}:
                ws = set(nm.split())
                self.wordsets[i].append(ws)
                for w in ws:
                    self.words[w[:5]].add(i)
        for ident in ambiguous:
            del self.by[ident]  # "Lena Neumann" twice: a name that cannot decide
        for k, lst in self.names.items():
            self.names[k] = [(nm, i) for nm, i in lst if "n:" + nm not in ambiguous]

    def lookup(self, value, via: str, fuzzy: bool = True) -> tuple[int | None, bool]:
        if value is None:
            return None, False
        if via.startswith("a:"):
            return (self.alt.get(via[2:]) or {}).get(norm_key(value)), True
        if via == "k":
            i = self.by.get("k:" + norm_key(value))
            if i is None and isinstance(value, str):
                i = self.by.get("n:" + norm_name(value))
            return i, True if i is not None else False
        if via == "e":
            return self.by.get("e:" + str(value).strip().casefold()), True
        nm = norm_name(value)
        i = self.by.get("n:" + nm)
        if i is not None:
            return i, True
        i = self.by.get("k:" + norm_key(value))
        if i is not None:
            return i, True
        if not fuzzy or len(nm) < 4:
            return None, False
        best, best_sim = None, 0.0
        for tok in nm.split()[:2]:
            for cand, ci in self.names.get(tok[:3], []):
                s = name_similarity(nm, cand)
                if s > best_sim:
                    best, best_sim = ci, s
        if best_sim >= 0.9:
            return best, False
        return self.short(nm), False

    def short(self, nm: str) -> int | None:
        """A short name ("Elbkind", "Dr. Behrens") names the one thing whose name contains all its words –
        if there is exactly one. Two Hafenkontors leave "Hafenkontor" unresolved."""
        small = set(nm.split())
        if not small or len(small) > 4 or sum(len(w) for w in small) < 6:
            return None
        cands = set().union(*(self.words.get(w[:5], set()) for w in small))
        hits = {i for i in cands if any(ws != small and _within(small, ws) for ws in self.wordsets[i])}
        return next(iter(hits)) if len(hits) == 1 else None


_MULTI = re.compile(r"\s*(?:[,;+/&]|\bund\b)\s*")


def alternate_keys(d: TypeDraft, groups: list[Group]) -> dict[str, dict[str, int]]:
    """Other programs' numbers a thing carries besides its own ("Firmen-Nr. (CRM)", the ticket system's
    company id): filled for most, unique to one thing each. A reference may speak that number."""
    out = {}
    for a in d.attrs:
        if a is d.key or a.kind != "id":
            continue
        seen: dict[str, int] = {}
        clash = filled = 0
        for gi, g in enumerate(groups):
            v = g.values.get(a.aid)
            if v is None:
                continue
            filled += 1
            k = norm_key(v)
            if k in seen and seen[k] != gi:
                clash += 1
            seen.setdefault(k, gi)
        if filled >= 3 and filled >= 0.3 * len(groups) and clash <= filled // 50:
            out[a.aid] = seen
    return out


def _vias(d: TypeDraft, alt: dict | None = None) -> list[tuple[str, AttrDraft]]:
    out = []
    if d.key is not None:
        out.append(("k", d.key))
    for a in d.attrs:
        if alt and a.aid in alt:
            out.append(("a:" + a.aid, a))
    for a in d.attrs:
        if a.kind == "email":
            out.append(("e", a))
            break
    if d.title is not None:
        out.append(("n", d.title))
    return out


def _eligible(t: TypeDraft, a: AttrDraft) -> bool:
    if a.kind not in ("id", "text", "email"):
        return False
    if a.role not in REF_ROLES:
        return False
    if a is t.key and t.kind != "line":
        return False
    return True


def discover(types: list[TypeDraft], groups: dict[int, list[Group]], obs_type: dict[str, TypeDraft],
             decisions: dict | None = None, log: list | None = None, ask: list | None = None) -> list[RelDraft]:
    decisions = decisions or {}
    alts = {id(t): alternate_keys(t, groups[id(t)]) for t in types if t.kind == "master"}
    idx = {id(t): IdentIndex(groups[id(t)], t.title.aid if t.title is not None else None, alts.get(id(t))) for t in types}
    rels: list[RelDraft] = []
    taken: set[tuple[int, int]] = set()  # (id(type), id(attr))

    def values_of(t: TypeDraft, a: AttrDraft) -> list[tuple[int, object]]:
        return [(i, g.values.get(a.aid)) for i, g in enumerate(groups[id(t)]) if g.values.get(a.aid) is not None]

    def build(t, a, d, via, structural, evidence) -> RelDraft | None:
        vals = values_of(t, a)
        if not vals:
            return None
        r = RelDraft(src=t, attr=a, dst=d, via=via, structural=structural, evidence=evidence)
        distinct_hit, distinct_all = set(), set()
        for gi, v in vals:
            k = norm_key(v) if via != "n" else norm_name(v)
            distinct_all.add(k)
            ti, exact = idx[id(d)].lookup(v, via)
            if ti is None and via == "k" and isinstance(v, str) and _MULTI.search(v):
                # "RE-2025-0003, RE-2025-0021": a deposit and a final invoice in one cell – link the first.
                # Only numbers are split: "Schulze & Partner" is one name.
                parts = [x.strip() for x in _MULTI.split(v) if x.strip()]
                if len(parts) >= 2 and all(any(ch.isdigit() for ch in x) for x in parts):
                    for part in parts:
                        ti = idx[id(d)].by.get("k:" + norm_key(part))
                        if ti is not None:
                            exact = True
                            r.multi.add(gi)  # the others are still read as mentions
                            break
            if ti is None:
                r.unresolved[gi] = v
                continue
            r.targets[gi] = ti
            distinct_hit.add(k)
            if not exact:
                r.fuzzy += 1
        r.hits = len(r.targets)
        r.inclusion = len(distinct_hit) / len(distinct_all) if distinct_all else 0.0
        r.coverage = r.hits / len(groups[id(t)]) if groups[id(t)] else 0.0
        return r

    # structural references from normalisation
    for t in types:
        for m in t.members:
            for col_name, target_oid in m.links:
                a = t.attr_of(m, col_name)
                d = obs_type.get(target_oid)
                if a is None or d is None or d is t or (id(t), id(a)) in taken:
                    continue
                tobs = next((o for o in d.members if o.oid == target_oid), None)
                ta = d.attr_of(tobs, tobs.key) if tobs is not None and tobs.key else None
                via = "k" if ta is d.key else "e" if (ta is not None and ta.kind == "email") else \
                    "a:" + ta.aid if ta is not None and ta.aid in (alts.get(id(d)) or {}) else "n"
                r = build(t, a, d, via, True, f"„{col_name}“ wurde aus derselben Tabelle herausgelöst")
                if r is None:
                    continue
                r.kind = "parent" if t.kind == "line" and d.kind in ("transaction",) else "ref"
                rels.append(r)
                taken.add((id(t), id(a)))
    # value references
    for t in types:
        for a in t.attrs:
            if (id(t), id(a)) in taken or not _eligible(t, a):
                continue
            n_distinct = len({norm_key(v) for _, v in values_of(t, a)})
            if n_distinct < 2:
                continue
            best = None
            name_cands = []  # (type, rel) by name against master data, for payees that can be several things
            for d in types:
                if d is t or d.kind == "line" or len(groups[id(d)]) < 2:
                    continue
                for via, va in _vias(d, alts.get(id(d))):
                    if a.kind == "email" and via != "e":
                        continue
                    if a.kind != "email" and via == "e":
                        continue
                    if a.kind == "id" and via == "n" and d.key is not None:
                        continue
                    if via.startswith("a:") and (a.kind != "id" or va is a or d is t):
                        continue  # another program's number is spoken by a number column
                    r = build(t, a, d, via, False, "")
                    if r is None or r.hits < 2:
                        continue
                    if via == "n" and d.kind == "master":
                        name_cands.append(r)
                    concept_hint = a.concept is not None and a.concept == d.concept
                    ok = r.inclusion >= 0.8 or (r.inclusion >= 0.5 and concept_hint)
                    dkey = f"rel|{t.tid}|{a.aid}|{d.tid}"  # ids stay when a type is renamed
                    dec = decisions.get(dkey) or decisions.get(f"rel|{t.name}|{a.name}|{d.name}")
                    if dec == "no":
                        ok = False
                    elif dec == "yes":
                        ok = r.hits > 0
                    elif not ok and ask is not None and r.inclusion >= 0.4 and (concept_hint or r.inclusion >= 0.6):
                        ask.append(dict(kind="relation", rel=r, key=dkey))
                    if not ok:
                        continue
                    score = r.inclusion + (0.2 if concept_hint else 0.0) - 0.1 * (r.fuzzy / max(1, r.hits))
                    if best is None or score > best[0]:
                        best = (score, r)
            if best is None and len(name_cands) >= 2:
                # together, several kinds of master data explain the column (customers *and* suppliers pay)
                name_cands.sort(key=lambda r: -r.inclusion)
                lead = name_cands[0]
                covered = {norm_name(v) for gi, v in values_of(t, a) if gi in lead.targets}
                extra = []
                for r2 in name_cands[1:]:
                    add = {gi: ti for gi, ti in r2.targets.items() if gi not in lead.targets}
                    if len(add) >= 1:
                        extra.append((r2.dst, add))
                        covered |= {norm_name(groups[id(t)][gi].values.get(a.aid)) for gi in add}
                distinct = {norm_name(v) for _, v in values_of(t, a)}
                dec = decisions.get(f"rel|{t.tid}|{a.aid}|{lead.dst.tid}") or \
                    decisions.get(f"rel|{t.name}|{a.name}|{lead.dst.name}")
                if distinct and lead.inclusion >= 0.4 and len(covered) / len(distinct) >= 0.8 and dec != "no":
                    lead.extra = extra
                    for d2, add in extra:
                        for gi in add:
                            lead.unresolved.pop(gi, None)
                    best = (lead.inclusion, lead)
            if best:
                r = best[1]
                # a payee can be a customer or a supplier: resolve the rest against other master data
                if r.unresolved and r.via == "n":
                    for d in types:
                        if d is t or d is r.dst or d.kind != "master" or d.title is None:
                            continue
                        hits = {}
                        for gi, v in r.unresolved.items():
                            ti, _exact = idx[id(d)].lookup(v, "n")
                            if ti is not None:
                                hits[gi] = ti
                        if len({norm_name(r.unresolved[g]) for g in hits}) >= 1 and len(hits) >= 2:
                            r.extra.append((d, hits))
                            for gi in hits:
                                r.unresolved.pop(gi, None)
                r.evidence = (f"{round(r.inclusion * 100)} % der Werte in „{a.name}“ sind "
                              f"{'Nummern' if r.via == 'k' or r.via.startswith('a:') else 'E-Mails' if r.via == 'e' else 'Namen'} "
                              f"von {d_plural(r.dst)}") + (f", {r.fuzzy} davon unscharf erkannt" if r.fuzzy else "")
                r.kind = "parent" if t.kind == "line" and r.dst.kind == "transaction" else "ref"
                rels.append(r)
                taken.add((id(t), id(a)))
    rels += _composite_refs(types, groups, rels, taken)
    if log is not None:
        for r in rels:
            log.append(dict(kind="relation", src=r.src.name, attr=r.attr.name, dst=r.dst.name, via=r.via,
                            inclusion=round(r.inclusion, 2), structural=r.structural, unresolved=len(r.unresolved)))
    return rels


_STOP = {"gmbh", "mbh", "ag", "kg", "ug", "ek", "co", "und", "der", "die", "das", "e", "v", "gbr", "ohg", "eg"}
_END_WORDS = {"ende", "end", "bis", "abgeschlossen", "beendet"}


def _ctoks(v) -> list[str]:
    return [t for t in tokens(str(v)) if len(t) >= 2 and t not in _STOP and not t.isdigit()]


def _tok_match(e: str, pool: set) -> bool:
    for p in pool:
        if e == p or (len(e) >= 3 and p.startswith(e)) or (len(p) >= 4 and e.startswith(p)):
            return True
    return False


def _composite_index(d: TypeDraft, r0: RelDraft | None, groups: dict, as_date) -> list[tuple]:
    """Per record: the words of its kind of work, of its customer (as resolved and as written), its time."""
    parties = [r0.attr] if r0 is not None else [x for x in d.attrs if x.kind == "text" and x.concept in ("kunde", "lieferant")]
    if not parties:
        return []
    words = [x for x in d.attrs if x.kind == "text" and x not in parties and x is not d.key and x.role != "notes"]
    dstart = next((x for x in d.attrs if x.kind in ("date", "datetime")), None)
    dends = [x for x in d.attrs if x.kind in ("date", "datetime") and
             (set(tokens(x.name)) & _END_WORDS or x.role == "due")]
    entries = []
    for gi, g in enumerate(groups[id(d)]):
        party = set()
        for x in parties:
            party |= set(_ctoks(g.values.get(x.aid) or ""))
        ti = r0.targets.get(gi) if r0 is not None else None
        if ti is not None:
            party |= set(_ctoks(groups[id(r0.dst)][ti].values.get(r0.dst.title.aid) or ""))
        if not party:
            continue
        pool = set()
        for c in words:
            pool |= set(_ctoks(g.values.get(c.aid) or ""))
        start = as_date(g.values.get(dstart.aid)) if dstart else None
        ends = [as_date(g.values.get(x.aid)) for x in dends]
        ends = [x for x in ends if x]
        entries.append((gi, pool - party, party, start, max(ends) if ends else None))
    return entries


def _composite_refs(types: list[TypeDraft], groups: dict, rels: list[RelDraft], taken: set) -> list[RelDraft]:
    """A freelancer writes "Elbkind Relaunch" or "Relaunch Tidenhub": the customer and the kind of
    work of one project. Where such names pick out exactly one project (at the time of the entry),
    they refer to it."""
    from datetime import timedelta
    from ..values import as_date
    party_of = {}
    for r in rels:
        if r.kind == "ref" and r.dst.kind == "master" and r.dst.title is not None and id(r.src) not in party_of:
            party_of[id(r.src)] = r
    out = []
    index: dict[int, list] = {}
    for t in types:
        if t.kind in ("master", "line"):
            continue
        tdate = next((x for x in t.attrs if x.kind in ("date", "datetime")), None)
        for a in t.attrs:
            if (id(t), id(a)) in taken or a.kind != "text" or a.role not in ("name", None, "category"):
                continue
            vals = [(i, g.values.get(a.aid)) for i, g in enumerate(groups[id(t)]) if isinstance(g.values.get(a.aid), str)]
            distinct = {v for _, v in vals}
            if len(vals) < 10 or len(distinct) < 3 or len(distinct) > 2000:
                continue
            vtoks = {v: _ctoks(v) for v in distinct}
            if sum(1 for v in distinct if len(vtoks[v]) >= 2) < 0.6 * len(distinct):
                continue  # single words are names or categories, not "customer + kind of work"
            best = None
            for d in types:
                r0 = party_of.get(id(d))
                if d is t or d.kind == "line" or len(groups[id(d)]) > 3000:
                    continue
                if id(d) not in index:
                    index[id(d)] = _composite_index(d, r0, groups, as_date)
                entries = index[id(d)]
                if len(entries) < 3:
                    continue
                cache = {}
                for v in distinct:
                    et = vtoks[v]
                    cache[v] = [x for x in entries if all(_tok_match(e, x[1] | x[2]) for e in et)
                                and any(_tok_match(e, x[2]) for e in et) and any(_tok_match(e, x[1]) for e in et)] \
                        if len(et) >= 2 else []
                if sum(1 for v in distinct if cache[v]) < 0.6 * len(distinct):
                    continue  # most names pick out nothing here: not this kind of reference
                targets, hit_vals = {}, set()
                for gi, v in vals:
                    cands = cache[v]
                    if len(cands) > 1 and tdate is not None:
                        when = as_date(groups[id(t)][gi].values.get(tdate.aid))
                        if when:
                            cands = [x for x in cands if (x[3] is None or x[3] - timedelta(days=14) <= when)
                                     and (x[4] is None or when <= x[4] + timedelta(days=45))]
                    if len(cands) == 1:
                        targets[gi] = cands[0][0]
                        hit_vals.add(v)
                cov, inc = len(targets) / len(vals), len(hit_vals) / len(distinct)
                if cov >= 0.6 and inc >= 0.6 and (best is None or cov > best[0]):
                    best = (cov, d, targets, inc)
            if best:
                cov, d, targets, inc = best
                r = RelDraft(src=t, attr=a, dst=d, via="c", kind="ref", inclusion=inc,
                             coverage=len(targets) / max(1, len(groups[id(t)])), hits=len(targets), fuzzy=len(targets),
                             evidence=f"{round(inc * 100)} % der Namen in „{a.name}“ nennen Kunde und Art "
                                      f"genau eines Eintrags von {d_plural(d)}")
                r.targets = targets
                r.unresolved = {gi: v for gi, v in vals if gi not in targets}
                out.append(r)
                taken.add((id(t), id(a)))
    return out


def d_plural(t: TypeDraft) -> str:
    return t.plural or t.name


# --- mentions in free text ---------------------------------------------------------------------

_TOKEN = re.compile(r"[A-Za-zÄÖÜäöüß#]*[\-./]?\d[\w\-./]*")
_LONG_WORD = 200


def _compact(s: str) -> str:
    return re.sub(r"[^0-9a-z]", "", fold(s))


def distinctive(key: str) -> bool:
    c = _compact(key)
    letters = sum(ch.isalpha() for ch in c)
    digits = sum(ch.isdigit() for ch in c)
    return (len(c) >= 5 and letters >= 1 and digits >= 2) or (digits >= 6 and len(c) == digits)


class MentionIndex:
    def __init__(self, types: list[TypeDraft], groups: dict[int, list[Group]]):
        self.compact: dict[str, list[tuple[TypeDraft, int]]] = defaultdict(list)
        self.digits: dict[str, list[tuple[TypeDraft, int]]] = defaultdict(list)
        self.names: dict[str, list[tuple[TypeDraft, int]]] = defaultdict(list)
        self.emails: dict[str, list[tuple[TypeDraft, int]]] = defaultdict(list)
        self.domains: dict[str, list[tuple[TypeDraft, int]]] = defaultdict(list)
        for t in types:
            if t.kind == "line":
                continue
            gs = groups[id(t)]
            key = t.key
            if key is not None and key.kind == "id":
                keys = [(i, g.values.get(key.aid)) for i, g in enumerate(gs) if g.values.get(key.aid) is not None]
                if keys and sum(distinctive(str(k)) for _, k in keys) >= 0.8 * len(keys):
                    dig_count = Counter(re.sub(r"\D", "", str(k)) for _, k in keys)
                    for i, k in keys:
                        self.compact[_compact(str(k))].append((t, i))
                        dg = re.sub(r"\D", "", str(k))
                        if len(dg) >= 6 and dig_count[dg] == 1:
                            self.digits[dg].append((t, i))
            if t.kind == "master" and t.title is not None:
                for i, g in enumerate(gs):
                    v = g.values.get(t.title.aid)
                    if not v:
                        continue
                    nm = norm_name(v)
                    if len(nm) >= 8 and len(nm.split()) >= 2 and not lexicon.looks_like_person(str(v)):
                        self.names[nm].append((t, i))
                for a in t.attrs:
                    if a.kind != "email":
                        continue
                    for i, g in enumerate(gs):
                        v = g.values.get(a.aid)
                        if v:
                            e = str(v).strip().casefold()
                            self.emails[e].append((t, i))
                            dom = e.rsplit("@", 1)[-1]
                            if dom not in FREEMAIL:
                                self.domains[dom].append((t, i))
        self.max_name_len = max((len(k.split()) for k in self.names), default=0)

    def scan(self, text: str, names: bool = False) -> dict[tuple[int, int], tuple[TypeDraft, int, str]]:
        """Return {(id(type), group index): (type, group index, how)} for everything mentioned in text."""
        found = {}
        if not text:
            return found
        words = text.split()
        cands = []
        for i, w in enumerate(words):
            if len(w) > _LONG_WORD:
                continue  # no number is that long – and scanning it would take forever
            prev = words[i - 1] if i else ""
            for tok in _TOKEN.findall(w):
                cands.append((tok, prev))
            if i + 1 < len(words) and len(words[i + 1]) <= _LONG_WORD:
                cands.append((w + words[i + 1], prev))
        for c, prev in cands:
            cc = _compact(c)
            hit = False
            if len(cc) >= 5:
                for t, gi in self.compact.get(cc, []):
                    found[(id(t), gi)] = (t, gi, "Nummer")
                    hit = True
            if hit or any(ch.isalpha() for ch in cc):
                continue
            dg = re.sub(r"\D", "", c)
            if len(dg) < 6:
                continue
            opts = self.digits.get(dg, [])
            if len(opts) > 1:
                ctx = lexicon.concept_of(prev) if prev else None
                opts = [(t, gi) for t, gi in opts if ctx and t.concept == ctx]
            if len(opts) == 1:
                t, gi = opts[0]
                found.setdefault((id(t), gi), (t, gi, "Nummer"))
        if names and self.names:
            nt = norm_name(text).split()
            for n in range(2, min(6, self.max_name_len) + 1):
                for i in range(len(nt) - n + 1):
                    k = " ".join(nt[i:i + n])
                    for t, gi in self.names.get(k, []):
                        found.setdefault((id(t), gi), (t, gi, "Name"))
        return found

    def scan_email(self, addr: str) -> dict:
        found = {}
        m = re.search(r"[\w.+%'-]+@[\w.-]+\.[a-z]{2,}", addr or "", re.I)
        if not m:
            return found
        e = m.group(0).casefold()
        for t, gi in self.emails.get(e, []):
            found[(id(t), gi)] = (t, gi, "Absender")
        if not found:
            dom = e.rsplit("@", 1)[-1]
            hits = self.domains.get(dom, [])
            if len({(id(t), gi) for t, gi in hits}) == 1:
                t, gi = hits[0]
                found[(id(t), gi)] = (t, gi, "Absender-Domain")
        return found


def discover_mentions(types: list[TypeDraft], groups: dict[int, list[Group]], index: MentionIndex,
                      taken: set, log: list | None = None, refs: list | None = None) -> list[RelDraft]:
    """Free-text attributes (Verwendungszweck, Notiz, Betreff) that mention other records. A column
    that mostly holds plain numbers is a reference; its other values ("RE-2026-0031 Teilzahlung")
    are still read as text."""
    rels = []
    by_attr = {(id(r.src), id(r.attr)): r for r in (refs or [])}
    for t in types:
        for a in t.attrs:
            resolved: set = set()
            if (id(t), id(a)) in taken:
                r0 = by_attr.get((id(t), id(a)))
                if r0 is None or a.kind not in ("text", "id", "ref"):
                    continue
                resolved = (set(r0.targets) - r0.multi) | {gi for _d, hits in r0.extra for gi in hits}
            elif a.kind != "text" or a.role not in ("notes", None, "category"):
                continue
            gs = groups[id(t)]
            per_dst: dict[int, RelDraft] = {}
            rows_with = Counter()
            for gi, g in enumerate(gs):
                if gi in resolved:
                    continue
                v = g.values.get(a.aid)
                if not v or len(str(v)) < 5:
                    continue
                hits = index.scan(str(v))
                for (_tid, _gi), (d, dgi, how) in hits.items():
                    if d is t:
                        continue
                    r = per_dst.get(id(d))
                    if r is None:
                        r = per_dst[id(d)] = RelDraft(src=t, attr=a, dst=d, via="k", kind="mention")
                    r.targets.setdefault(gi, []).append(dgi)
                    rows_with[id(d)] += 1
            for did, r in per_dst.items():
                share = len(r.targets) / len(gs) if gs else 0
                if resolved and r.dst is by_attr[(id(t), id(a))].dst and len(r.targets) >= 1:
                    share = max(share, 0.1)  # the rest of a reference column, same target
                if len(r.targets) >= (1 if resolved else 2) and share >= 0.1:
                    r.hits = len(r.targets)
                    r.coverage = share
                    r.inclusion = share
                    r.evidence = (f"in {len(r.targets)} von {len(gs)} {d_plural(t)} steht in „{a.name}“ eine "
                                  f"Nummer von {d_plural(r.dst)}")
                    rels.append(r)
                    if log is not None:
                        log.append(dict(kind="mention", src=t.name, attr=a.name, dst=r.dst.name, rows=len(r.targets)))
    return rels
