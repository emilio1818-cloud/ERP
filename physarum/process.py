"""Processes from timestamps, and work from deviations.

Small companies have no event log, only snapshots: an order list with "Datum" and
"Geliefert am", an invoice book with "Fällig am" and "Bezahlt am", a bank statement.
Every date column is a milestone. Children count too: an order is "berechnet" when an
invoice points to it, an invoice is "bezahlt" when a bank transfer mentions it. The
typical order and duration of milestones is the process. Whatever deviates from it
(overdue, waiting longer than usual, stock running out, a regular customer gone quiet)
is work.
"""
from __future__ import annotations

import re
import statistics
from collections import Counter, defaultdict
from datetime import date, timedelta

from . import lexicon
from .billing import is_draft
from .text import fold, tokens
from .values import as_date, due_range, event_date, fmt_eur

RECURRING = {"monatlich", "monatspauschale", "pauschale", "mtl", "monthly", "abo", "miete", "monatsbeitrag",
             "monatsrate", "rate", "grundgebuehr", "wartungspauschale"}
PARTICIPLES = {"geliefert", "bezahlt", "versendet", "berechnet", "eingegangen", "erledigt", "abgeschlossen",
               "storniert", "angenommen", "unterschrieben", "gemahnt", "freigegeben", "montiert", "installiert",
               "gewartet", "beendet", "ausgetreten"}
CHILD_LABEL = {"lieferschein": "geliefert", "auftrag": "beauftragt", "einkauf": "bestellt"}
PAID = "bezahlt"  # the step the money settles: named by Physarum, the firm's heading stays the column's name
BILLED = "berechnet"  # the step an invoice settles


def _pct(vals: list[float], q: float) -> float:
    if not vals:
        return 0.0
    s = sorted(vals)
    i = min(len(s) - 1, max(0, int(round(q * (len(s) - 1)))))
    return s[i]


def _label_of(attr: dict) -> str:
    lab = attr.get("milestone") or lexicon.milestone_label(attr["name"])
    if lab:
        return lab
    toks = [t for t in attr["name"].replace("/", " ").split() if fold(t) not in ("am", "datum", "date", "at", "on", "vom")]
    return " ".join(toks) or attr["name"]


def _primary_date(spec: dict) -> dict | None:
    """The date a record's life starts with (learned by `_first_date`), else the fullest date column."""
    cands = [a for a in spec["attrs"] if a["kind"] in ("date", "datetime") and a.get("role") != "due" and not a.get("hidden")]
    if not cands:
        return None
    learned = next((a for a in cands if a["id"] == spec.get("first_date")), None)
    return learned or max(cands, key=lambda a: (a.get("fill", 0), -len(a["name"])))


def _first_date(spec: dict, recs: list[dict]) -> str | None:
    """Of the fullest date columns, the one the others follow: an invoice list in which every invoice is paid has
    "Bezahlt am" as full as "Rechnungsdatum" – the invoice date still comes first."""
    cands = [a for a in spec["attrs"] if a["kind"] in ("date", "datetime") and a.get("role") != "due" and not a.get("hidden")]
    top = max((a.get("fill", 0) for a in cands), default=0)
    full = [a for a in cands if a.get("fill", 0) >= top - 0.05]
    if len(full) < 2:
        return None

    def first_in(a) -> int:
        n = 0
        for r in recs[:2000]:
            v = as_date(r["data"].get(a["id"]))
            if v and all(v <= w for b in full if b is not a for w in [as_date(r["data"].get(b["id"]))] if w):
                n += 1
        return n
    return max(full, key=lambda a: (first_in(a), a.get("fill", 0), -len(a["name"])))["id"]


def money_attrs(spec: dict, recs: list[dict] | None = None) -> tuple[dict | None, dict | None]:
    """(net-ish, gross-ish) money attribute of a type (computed totals count). With the records: the gross is
    the amount no other amount of a row exceeds ("Rechnungsbetrag" over Netto, MwSt and "Offener Betrag"),
    the net the next one below it – whatever the columns are called."""
    ms = [a for a in spec["attrs"] if a["kind"] == "money" and not a.get("hidden") and not a.get("constant")]
    if not ms:
        return None, None
    if recs:
        def top(a) -> float:  # share of the rows with any amount where this one is the largest
            n = k = 0
            for r in recs:
                vs = {b["id"]: abs(r["data"][b["id"]]) for b in ms if isinstance(r["data"].get(b["id"]), (int, float))}
                if not vs:
                    continue
                n += 1
                k += a["id"] in vs and vs[a["id"]] >= max(vs.values()) - 0.005
            return k / n if n else 0.0
        share = {a["id"]: top(a) for a in ms}
        gross = max(ms, key=lambda a: share[a["id"]])
        if share[gross["id"]] >= 0.9:
            rest = [a for a in ms if a is not gross]
            fill = lambda a: sum(1 for r in recs if isinstance(r["data"].get(a["id"]), (int, float)))

            def taxed(a) -> float:  # the gross over it is a tax rate (1,19 · 1,07) – not the same amount again
                n = k = 0
                for r in recs:
                    g, v = r["data"].get(gross["id"]), r["data"].get(a["id"])
                    if isinstance(g, (int, float)) and isinstance(v, (int, float)) and v > 0:
                        n, k = n + 1, k + (1.05 <= g / v <= 1.25)
                return k / n if n else 0.0
            named = next((a for a in rest if set(tokens(a["name"])) & {"netto", "net"}), None)
            # no amount the gross is taxed on (only "Offen", "erhalten"): the net is not in the list
            net = max([a for a in rest if taxed(a) >= 0.6], key=lambda a: (share[a["id"]] + fill(a) / len(recs),
                                                                         -ms.index(a)), default=gross)
            return named or net, gross
    net = next((a for a in ms if "netto" in tokens(a["name"]) or "net" in tokens(a["name"])), None)
    gross = next((a for a in ms if set(tokens(a["name"])) & {"brutto", "gesamt", "total", "summe", "betrag", "gross"}), None)
    net = net or gross or ms[-1]
    gross = gross or net
    return net, gross


def infer_processes(model: dict, records: dict, store=None, today: date | None = None):
    today = today or date.today()
    specs = {t["id"]: t for t in model["types"]}
    by_id = {r["id"]: r for rs in records.values() for r in rs}
    mention_map = defaultdict(lambda: defaultdict(list))  # rel attr -> dst rid -> [src rids]
    if store is not None:
        for r in store.q("SELECT from_id, attr, to_id FROM refs WHERE kind='mention' AND attr!='doc'"):
            mention_map[r["attr"]][r["to_id"]].append(r["from_id"])
    for spec in model["types"]:
        spec["first_date"] = _first_date(spec, records.get(spec["id"], [])) if spec["kind"] == "transaction" else None
    children = defaultdict(list)  # dst type -> [(rel, src spec, child date attr)]
    for rel in model["relations"]:
        src, dst = specs.get(rel["src"]), specs.get(rel["dst"])
        if not src or not dst or src["kind"] in ("line", "master", "document"):
            continue
        pd = _primary_date(src)
        if pd:
            children[dst["id"]].append((rel, src, pd))
    from .reconcile import bank_specs
    banks = {b["spec"]["id"] for b in bank_specs(model)}  # by their columns, whatever the file is called
    model["processes"] = []
    for spec in model["types"]:
        if spec["kind"] not in ("transaction",):
            continue
        recs = records.get(spec["id"], [])
        if len(recs) < 2:
            continue
        p = _infer_one(spec, recs, children.get(spec["id"], []), records, mention_map, by_id, today, specs, banks)
        if p:
            spec["process"] = p["id"]
            model["processes"].append(p)
    # a child the bank pays is an invoice: what points to it is "berechnet" by it, whatever its file is called
    from .payments import invoice_specs
    billing = {ip["spec"]["id"] for ip in invoice_specs(model) if not ip["outgoing"]}
    for p in model["processes"]:
        for st in p["steps"]:
            if st["source"] == "child" and st.get("type") in billing and st["type"] != p["type"]:
                st["label"], st["phrase"] = BILLED, f"noch nicht {BILLED}"
    model["rhythms"] = _rhythm_specs(model, records)
    model["reach"] = _reach_specs(model, records)
    model["dues"] = _due_specs(model, records)


# what the bank says is a fact to read, never a record to type in ("+ Girokonto" would invent a transfer)
_FACTS = {"kontobewegung", "zahlung"}

# a corrected invoice follows its cancellation within days; a quarter later the cancellation was the decision
_VOID_GRACE = 90

_SUPPLIER = {"lieferant", "kreditor", "rechnungssteller", "supplier", "vendor"}
_DUE_WORDS = {"naechste", "naechster", "naechstes", "faellig", "faelligkeit", "next", "due", "geplant", "plan",
              "am", "bis", "datum", "spaetestens", "soll"}


def _due_specs(model: dict, records: dict) -> list[dict]:
    """Dates that lie ahead in lists without a process ("Nächste Wartung" of a maintenance contract),
    with the date that says it was done ("Letzte Wartung")."""
    out = []
    procs = {p["type"]: p for p in model.get("processes", [])}
    for spec in model["types"]:
        if spec["kind"] not in ("transaction", "master") or spec.get("concept") == "rechnung":
            continue  # invoices: due means paid, which the money decides
        p = procs.get(spec["id"])
        free = {dl["attr"] for dl in p["deadlines"] if not dl.get("step")} if p else None
        for a in spec["attrs"]:
            if a.get("role") != "due" or a.get("hidden") or not (a["kind"] in ("date", "datetime") or a.get("period")):
                continue
            recurring = bool((a.get("virtual") or {}).get("recurring"))
            if free is not None and a["id"] not in free and not recurring:
                continue  # the deadline of a step: handled with that step
            obj = set(tokens(a["name"])) - _DUE_WORDS
            done = next((b for b in spec["attrs"] if b is not a and b["kind"] in ("date", "datetime")
                         and b.get("role") != "due" and not b.get("hidden") and obj & set(tokens(b["name"]))), None)
            recs = records.get(spec["id"], [])
            if sum(1 for r in recs if due_range(r["data"].get(a["id"]))) >= 2:
                du = dict(type=spec["id"], attr=a["id"], name=a["name"], done=done["id"] if done else None,
                          done_label=(done.get("milestone") or done["name"]) if done else None,
                          recurring=recurring, follow_up=lexicon.is_follow_up(a["name"]))
                if p and not recurring:
                    du.update(_case_life(spec, p, a, recs))
                out.append(du)
    return out


def _case_life(spec, p, a, recs) -> dict:
    """For a date on a case that is still open ("nachfassen am" on an offer): which status values close
    the case, how long such a case stays worth chasing, and how far ahead the firm usually sets the date."""
    st = p.get("status") or {}
    sattr = next((x for x in spec["attrs"] if x["id"] == st.get("attr")), None)
    closed = set(st.get("negative") or [])
    for v in (sattr or {}).get("enum") or []:
        if fold(str(v)) in lexicon.DONE_STATES or any(lexicon.status_reaches(x["label"], v) for x in p["steps"]):
            closed.add(v)
    # an offer holds only as long as an answer can be expected (§ 147 BGB): the cases that were taken were
    # taken within the usual time to their first step; three times that, at least three months
    longest = acc = 0
    for x in p["steps"]:
        acc += x.get("median_days") or 0
        longest = max(longest, acc)
    offsets = [(dv - sv).days for r in recs
               if (dv := as_date(r["data"].get(a["id"]))) and (sv := as_date(r["data"].get(p["start"]["attr"])))]
    offsets = [x for x in offsets if x > 0]
    # the steps that settle the case: an order that names the offer, or the offer's own "Auftrag" column
    taken = [dict(type=x["type"], attr=x["rel_attr"], own=x["rel_kind"] == "own_ref", label=x["name"])
             for step in p["steps"] for x in [step] + step.get("also", [])
             if x["source"] == "child" and x["rel_kind"] in ("ref", "own_ref")]
    return dict(status=st.get("attr") if closed else None, closed=sorted(closed), start=p["start"]["attr"],
                lifetime=int(max(90, 3 * longest)),
                offset=int(statistics.median(offsets)) if len(offsets) >= 3 else None,
                negative=(st.get("negative") or [None])[0], taken=taken)


def _instance_dates(spec, recs, cand_steps, records, mention_map, start_attr: str | None = None):
    """dates[step_id][rid] = date"""
    out = {}
    rid_set = {r["id"] for r in recs}
    for st in cand_steps:
        d = {}
        if st["source"] == "own":
            for r in recs:
                v = event_date(r["data"].get(st["attr"]), as_date(r["data"].get(start_attr)) if start_attr else None)
                if v:
                    d[r["id"]] = v
        else:
            ctype = st["type"]
            if st["rel_kind"] == "own_ref":
                child_by_id = {c["id"]: c for c in records.get(ctype, [])}
                for r in recs:
                    c = child_by_id.get(r["data"].get(st["rel_attr"]))
                    v = as_date(c["data"].get(st["attr"])) if c else None
                    if v:
                        d[r["id"]] = v
            elif st["rel_kind"] == "mention":
                child_by_id = {c["id"]: c for c in records.get(ctype, [])}
                for dst, srcs in mention_map.get(st["rel_attr"], {}).items():
                    if dst not in rid_set:
                        continue
                    ds = [as_date(child_by_id[s]["data"].get(st["attr"])) for s in srcs if s in child_by_id]
                    ds = [x for x in ds if x]
                    if ds:
                        d[dst] = min(ds)
            else:
                for c in records.get(ctype, []):
                    target = c["data"].get(st["rel_attr"])
                    if target in rid_set:
                        v = as_date(c["data"].get(st["attr"]))
                        if v and (target not in d or v < d[target]):
                            d[target] = v
        out[st["id"]] = d
    return out


def _infer_one(spec, recs, kids, records, mention_map, by_id, today, specs_of: dict | None = None,
               banks: set | None = None) -> dict | None:
    specs_of = specs_of or {}
    banks = banks or set()
    start_attr = _primary_date(spec)
    if not start_attr:
        return None
    cand = []
    for a in spec["attrs"]:
        if a["kind"] in ("date", "datetime") and a.get("role") != "due" and a["id"] != start_attr["id"] and not a.get("hidden") \
                and not lexicon.is_unnamed(a["name"]):  # a date without a heading is no milestone anyone could name
            cand.append(dict(id=f"s_{a['id']}", source="own", attr=a["id"], label=_label_of(a), name=a["name"]))
    for rel, src, pd in kids:
        # a supplier's invoice for a project is a cost of it, not its billing; a bank line that names it, its payment
        lab = src["name"] if src.get("incoming") else PAID if src["id"] in banks else \
            CHILD_LABEL.get(src.get("concept") or "", src["name"])
        cand.append(dict(id=f"c_{rel['id']}", source="child", type=src["id"], rel=rel["id"], rel_attr=rel["attr"],
                         rel_kind=rel["kind"], attr=pd["id"], label=lab, name=src["name"], child_plural=src["plural"]))
    for a in spec["attrs"]:
        # the order book's own "Rechnung" column: the order was invoiced on the invoice's date
        tgt = specs_of.get(a.get("ref")) if a["kind"] == "ref" and not a.get("hidden") else None
        tpd = _primary_date(tgt) if tgt and tgt["kind"] == "transaction" and tgt["id"] != spec["id"] else None
        if tpd:
            cand.append(dict(id=f"o_{a['id']}", source="child", type=tgt["id"], rel=None, rel_attr=a["id"],
                             rel_kind="own_ref", attr=tpd["id"], label=CHILD_LABEL.get(tgt.get("concept") or "", tgt["name"]),
                             name=tgt["name"], child_plural=tgt["plural"]))
    starts = {r["id"]: as_date(r["data"].get(start_attr["id"])) for r in recs}
    starts = {k: v for k, v in starts.items() if v}
    has_due = any(a.get("role") == "due" for a in spec["attrs"])
    if len(starts) < (2 if has_due else 5):
        return None
    dates = _instance_dates(spec, recs, cand, records, mention_map, start_attr["id"] if start_attr else None)
    steps = []
    for st in cand:
        d = dates[st["id"]]
        deltas = [(d[k] - starts[k]).days for k in d if k in starts]
        if len(deltas) < max(3, 0.03 * len(starts)):
            continue
        after = sum(1 for x in deltas if x >= -1) / len(deltas)
        if after < 0.8 or (max(deltas) <= 0 and min(deltas) < 0):
            continue  # never after the start, now and then before: where a case came from (its order), no step
        if sum(1 for x in deltas if x == 0) / len(deltas) >= 0.9 and st["source"] == "own":
            continue  # "Valutadatum" next to "Buchungstag": the same moment, not a step
        st["median"] = statistics.median(deltas)
        st["share"] = round(len(deltas) / len(starts), 3)
        # coverage window: the step can only be expected where its data exists
        ds = sorted(d.values())
        st["window"] = [ds[0].isoformat(), ds[-1].isoformat()]
        steps.append(st)
    # equivalent steps (own "Bezahlt am" and the bank transfer) collapse into one
    merged = []
    for st in sorted(steps, key=lambda s: (s["source"] != "own", -s["share"])):
        twin = None
        for m in merged:
            a, b = dates[m["id"]], dates[st["id"]]
            both = [k for k in a if k in b]
            kin = st.get("type") and (m.get("type") == st.get("type") or
                                      any(x.get("type") == st.get("type") for x in m.get("also", [])))
            if fold(m["label"]) == fold(st["label"]) and (kin or "own" in (m["source"], st["source"])):
                # one name, one milestone: reached through another link of the same kind of record, or the
                # book's own "bezahlt am" next to the bank's transfer – even where their dates never overlap
                twin = m
                break
            # the book's own date that agrees with the bank's transfers is the date of payment, whatever its heading
            paying = m["source"] == "own" and st.get("type") in banks
            if len(both) < (2 if paying else 3):
                continue
            near = sum(1 for k in both if abs((a[k] - b[k]).days) <= 3) / len(both)
            same = sum(1 for k in both if a[k] == b[k]) / len(both)
            # the book notes the money after it came: the same day, or when the month's books are done
            follows = paying and sum(1 for k in both if 0 <= (a[k] - b[k]).days <= 35) / len(both) >= 0.9
            # an invoice of its own is a step of its own, though written the day the job was done
            apart = st["source"] == "child" and st.get("type") not in banks
            if ((fold(m["label"]) == fold(st["label"]) or paying) and near >= 0.8) or follows or \
                    (same >= 0.9 and len(both) >= 10 and not apart):
                twin = m
                break
        if twin:
            if st.get("type") in banks:
                twin["label"] = PAID  # what the money says, not what the column is called
            twin.setdefault("also", []).append(st)
            w0, w1 = twin["window"], st["window"]
            twin["window"] = [min(w0[0], w1[0]), max(w0[1], w1[1])]
        else:
            merged.append(st)
    steps = sorted(merged, key=lambda s: s["median"])
    if not steps:
        dues = [a for a in spec["attrs"] if a.get("role") == "due"]
        if not dues:
            return None
    # per-instance combined step dates
    comb = {}
    for st in steps:
        d = dict(dates[st["id"]])
        for tw in st.get("also", []):
            for k, v in dates[tw["id"]].items():
                if k not in d or v < d[k]:
                    d[k] = v
        comb[st["id"]] = d
    # durations from previous milestone
    prev_id = "start"
    for st in steps:
        diffs = []
        for k, v in comb[st["id"]].items():
            base = starts.get(k) if prev_id == "start" else comb[prev_id].get(k)
            if base and k in starts:
                diffs.append((v - base).days)
        st["prev"] = prev_id
        st["median_days"] = round(statistics.median(diffs), 1) if diffs else None
        st["p80_days"] = round(_pct(diffs, 0.8), 1) if diffs else None
        st["n"] = len(diffs)
        st["phrase"] = (f"noch nicht {st['label']}" if fold(st["label"]) in PARTICIPLES else f"ohne {st['label']}")
        prev_id = st["id"]
    # deadlines
    deadlines = []
    for a in [a for a in spec["attrs"] if a.get("role") == "due" and not a.get("hidden")]:
        best, best_m = None, None
        for st in steps:
            diffs = []
            for r in recs:
                dv = as_date(r["data"].get(a["id"]))
                sv = comb[st["id"]].get(r["id"])
                if dv and sv:
                    diffs.append(abs((sv - dv).days))
            if len(diffs) >= 3:
                m = statistics.median(diffs)
                lex = 0 if _lex_match(a["name"], st["label"]) else 1
                if best is None or (lex, m) < best_m:
                    best, best_m = st, (lex, m)
        deadlines.append(dict(attr=a["id"], name=a["name"], step=best["id"] if best else None))
    # status: learned from the record's own dates (status and dates come from the same file)
    status = None
    best_status = None
    own = {st["id"]: dates[st["id"]] for st in steps if st["source"] == "own"}
    for sa in [a for a in spec["attrs"] if a.get("role") == "status" and a.get("enum") and not a.get("hidden")]:
        stage_of = {}
        for r in recs:
            stage = 0
            for i, st in enumerate(steps, start=1):
                if r["id"] in own.get(st["id"], {}):
                    stage = i
            stage_of[r["id"]] = stage
        cand = _status_for(sa, recs, steps, stage_of, comb)
        if cand and (best_status is None or cand["_quality"] > best_status["_quality"]):
            best_status = cand
    if best_status:
        best_status.pop("_quality", None)
        status = best_status
        # cancelled/refunded in *any* status column ends the process ("refunded" next to "unfulfilled")
        extra_neg = []
        for sa in [a for a in spec["attrs"] if a.get("role") == "status" and a.get("enum") and not a.get("hidden")]:
            vals = [v for v in (sa.get("enum") or []) if fold(str(v)) in lexicon.NEGATIVE_STATES]
            if vals and sa["id"] != status["attr"]:
                extra_neg.append(dict(attr=sa["id"], values=vals))
        status["negative_other"] = extra_neg
    net, gross = money_attrs(spec, recs)

    refs = [a for a in spec["attrs"] if a["kind"] == "ref" and a.get("ref") and a["id"] != spec.get("key")]
    party = next((a for a in refs if a.get("ref_kind") == "master"), None)
    if party is None and spec.get("incoming"):
        # a supplier's invoice read from paper: the supplier is a name, the order it names is no party
        party = next((a for a in spec["attrs"] if a["kind"] == "text" and set(tokens(a["name"])) & _SUPPLIER), None)
    party = party or (refs[0] if refs else None)
    for st in steps:
        st.pop("median", None)
    return dict(id=f"p_{spec['id']}", type=spec["id"], name=spec["plural"], start=dict(attr=start_attr["id"],
                label=start_attr["name"]), steps=steps, deadlines=deadlines, status=status,
                net=net["id"] if net else None, gross=gross["id"] if gross else None,
                party=party["id"] if party else None, n=len(starts))


def _status_for(sa, recs, steps, stage_of, comb) -> dict | None:
    by_val = defaultdict(Counter)
    for r in recs:
        v = r["data"].get(sa["id"])
        if v is not None:
            by_val[str(v)][stage_of[r["id"]]] += 1
    mapping, negative = {}, []
    for v, cnt in by_val.items():
        if fold(v) in lexicon.NEGATIVE_STATES:
            negative.append(v)
            continue
        stage, c = cnt.most_common(1)[0]
        if c / sum(cnt.values()) >= 0.7:
            mapping[v] = stage
    stage0 = Counter(str(r["data"].get(sa["id"])) for r in recs if stage_of[r["id"]] == 0
                     and r["data"].get(sa["id"]) is not None and str(r["data"].get(sa["id"])) not in negative)
    initial = stage0.most_common(1)[0][0] if stage0 else None
    autos = []
    for i, st in enumerate(steps, start=1):
        vals = [v for v, s in mapping.items() if s == i]
        if len(vals) != 1 or vals[0] == initial:
            continue
        v = vals[0]
        at_step = [r for r in recs if stage_of[r["id"]] == i]
        reached = [r for r in at_step if str(r["data"].get(sa["id"])) not in negative]
        if len(at_step) - len(reached) > 0.1 * max(1, len(at_step)):
            continue  # "Entschieden am" is filled for rejected offers too: the date does not say which way
        if len(reached) >= 5:
            ok = sum(1 for r in reached if str(r["data"].get(sa["id"])) == v)
            if ok / len(reached) >= 0.9:
                autos.append(dict(step=st["id"], attr=sa["id"], value=v, ok=ok, n=len(reached),
                                  text=f"Wenn „{st['name']}“ eingetragen wird: {sa['name']} = „{lexicon.show_value(v)}“"))
    # how well the status values predict the stage (1.0 = perfectly)
    total = sum(sum(c.values()) for v, c in by_val.items() if v not in negative)
    purity = sum(max(c.values()) for v, c in by_val.items() if v not in negative) / total if total else 0
    quality = purity * 10 + len(set(mapping.values()))
    return dict(attr=sa["id"], name=sa["name"], map=mapping, negative=negative, initial=initial, autos=autos,
                _quality=quality)


def _lex_match(due_name: str, label: str) -> bool:
    d = fold(due_name)
    l = fold(label)
    if "faellig" in d or "due" in d:
        return l in ("bezahlt",)
    if "liefer" in d:
        return l in ("geliefert", "versendet")
    if "wartung" in d:
        return l in ("gewartet",)
    return False


# --- rhythms (customers gone quiet) and reach (stock running out) -------------------------------------

def _rhythm_specs(model, records) -> list[dict]:
    specs = {t["id"]: t for t in model["types"]}
    out = []
    for rel in model["relations"]:
        src, dst = specs.get(rel["src"]), specs.get(rel["dst"])
        if not src or not dst or rel["kind"] != "ref" or src["kind"] != "transaction" or dst["kind"] != "master":
            continue
        pd = _primary_date(src)
        if not pd:
            continue
        per = defaultdict(int)
        for r in records.get(src["id"], []):
            if isinstance(r["data"].get(rel["attr"]), int):
                per[r["data"][rel["attr"]]] += 1
        regular = sum(1 for v in per.values() if v >= 4)
        if regular >= 3:
            out.append(dict(rel=rel["id"], src=src["id"], dst=dst["id"], attr=rel["attr"], date=pd["id"],
                            regular=regular, label=src["plural"]))
    # invoices follow orders: keep the order channels, drop a channel whose source points to another one
    srcs_with_order_ref = set()
    for rel in model["relations"]:
        src, dst = specs.get(rel["src"]), specs.get(rel["dst"])
        if src and dst and src["kind"] == "transaction" and dst["kind"] == "transaction":
            srcs_with_order_ref.add(src["id"])
    return [r for r in out if r["src"] not in srcs_with_order_ref]


def _reach_specs(model, records) -> list[dict]:
    specs = {t["id"]: t for t in model["types"]}
    out = []
    for spec in model["types"]:
        if spec["kind"] != "master":
            continue
        stock = next((a for a in spec["attrs"] if a["kind"] == "number" and
                      set(tokens(a["name"])) & {"bestand", "lagerbestand", "stock", "vorrat", "onhand"}), None)
        if not stock:
            continue
        flows = []
        for rel in model["relations"]:
            if rel["dst"] != spec["id"]:
                continue
            line = specs.get(rel["src"])
            if not line or line["kind"] != "line":
                continue
            qty = next((a for a in line["attrs"] if a["kind"] == "number" and a.get("role") == "quantity"), None)
            parent_rel = next((r for r in model["relations"] if r["src"] == line["id"] and r["id"] != rel["id"]
                               and specs.get(r["dst"], {}).get("kind") == "transaction"), None)
            if not qty or not parent_rel:
                continue
            pd = _primary_date(specs[parent_rel["dst"]])
            if not pd:
                continue
            # goods leave when they are delivered, not when they are ordered
            pproc = next((p for p in model.get("processes", []) if p["type"] == parent_rel["dst"]), None)
            moved = None
            for st in (pproc or {}).get("steps", []):
                if fold(st["label"]) in ("geliefert", "versendet", "ausgeliefert", "verschickt"):
                    moved = next((x["attr"] for x in [st] + st.get("also", []) if x["source"] == "own"), None)
                    if moved:
                        break
            flows.append(dict(line=line["id"], ref=rel["attr"], qty=qty["id"], parent_ref=parent_rel["attr"],
                              parent=parent_rel["dst"], date=pd["id"], moved=moved, label=line["plural"]))
        if flows:
            labels = {x.get("obs") for x in stock.get("sources") or []}
            asof = max((m.get("asof") or "" for m in spec.get("members", []) if m.get("label") in labels), default="")
            out.append(dict(type=spec["id"], stock=stock["id"], flows=flows, asof=asof or None))
            if asof and not any(a["id"] == "stock_now" for a in spec["attrs"]):
                spec["attrs"].append(dict(id="stock_now", name="Bestand jetzt", kind="number", role="quantity", fill=1.0,
                                          distinct=0, enum=None, constant=False, hidden=False, sources=[],
                                          virtual=dict(stock=True),
                                          explain=f"{stock['name']} laut Liste vom {asof[8:10]}.{asof[5:7]}.{asof[:4]} "
                                                  f"minus alles, was seitdem geliefert wurde"))
    return out


def stock_now(model: dict, records: dict, today: date | None = None) -> dict[int, float]:
    """Stock as of today: what the inventory said, minus what was delivered since (cancelled and
    draft orders do not move goods)."""
    today = today or date.today()
    out = {}
    negative_of = {p["type"]: ((p.get("status") or {}).get("attr"), set((p.get("status") or {}).get("negative") or []))
                   for p in model.get("processes", [])}
    for rc in model.get("reach", []):
        base_day = as_date(rc.get("asof"))
        if not base_day:
            continue
        moved = defaultdict(float)
        for fl in rc["flows"]:
            attr, neg = negative_of.get(fl["parent"], (None, set()))
            when = {}
            for r in records.get(fl["parent"], []):
                if is_draft(r) or (attr and str(r["data"].get(attr)) in neg):
                    continue
                d = as_date(r["data"].get(fl.get("moved") or fl["date"]))
                if d and base_day < d <= today:
                    when[r["id"]] = d
            for ln in records.get(fl["line"], []):
                a, p, q = ln["data"].get(fl["ref"]), ln["data"].get(fl["parent_ref"]), ln["data"].get(fl["qty"])
                if isinstance(a, int) and p in when and isinstance(q, (int, float)) and not isinstance(q, bool):
                    moved[a] += float(q)
        for r in records.get(rc["type"], []):
            v = r["data"].get(rc["stock"])
            if isinstance(v, (int, float)) and not isinstance(v, bool):
                out[r["id"]] = round(float(v) - moved.get(r["id"], 0.0), 3)
    return out


# --- runtime: what needs to be done today ---------------------------------------------------------------

def _never_reached(spec: dict, recs: list[dict], p: dict, step_dates: dict, today: date) -> set:
    """(step, attr, value): cases of this kind never take this step. Maintenance contracts do not
    end like a website relaunch; waiting for their end is no delay."""
    out = set()
    status = (p.get("status") or {}).get("attr")
    cats = [a["id"] for a in spec["attrs"] if a.get("enum") and 2 <= len(a["enum"]) <= 12 and a["id"] != status
            and a["kind"] == "text" and a.get("role") in ("category", None) and not a.get("virtual")]
    for st in p["steps"]:
        if st.get("p80_days") is None:
            continue
        horizon = today - timedelta(days=int(st["p80_days"] * 1.25) + 2)
        done = step_dates.get(st["id"], {})
        for a in cats:
            old, did = Counter(), Counter()
            for r in recs:
                v = r["data"].get(a)
                start = as_date(r["data"].get(p["start"]["attr"]))
                if v is None or not start or start > horizon:
                    continue
                old[str(v)] += 1
                if done.get(r["id"]):
                    did[str(v)] += 1
            total_old, total_did = sum(old.values()), sum(did.values())
            share = total_did / total_old if total_old else 0
            for v, n in old.items():
                # (almost) never, while the rest mostly does: it is not their way
                if n >= 5 and total_did >= 5 and (did[v] <= 0.05 * n or (did[v] <= 0.2 * n and did[v] / n <= share / 3)):
                    out.add((st["id"], a, v))
    return out


def never_attrs(never: set) -> set:
    return {a for _s, a, _v in never}


_MAIL_COMPLAINT = ("reklamation", "beschwerde", "mangel", "maengel", "defekt", "kaputt", "falsch geliefert", "fehlt",
                   "nicht erhalten", "nicht angekommen", "rueckfrage zu rechnung", "rueckfrage zur rechnung",
                   "stimmt nicht", "doppelt berechnet", "zu viel berechnet", "widerspruch")
_MAIL_ORDER = ("bestellung", "bestelle", "bestellen", "nachbestell", "auftrag erteilt", "beauftragen", "beauftrage",
               "bitte liefern", "liefern sie bitte", "order")
_MAIL_ASK = ("anfrage", "angebot", "kostenvoranschlag", "interesse an", "was kostet", "unverbindlich", "preisanfrage")
_MAIL_BULK = ("newsletter", "no-reply", "noreply", "abmelden", "unsubscribe", "news@", "webinar", "keynote", "werbung")
_MAIL_DAYS = 30
# what a customer asks for in a sentence ("Schicken Sie uns bitte die Rechnung", "bitte Termin machen")
_MAIL_WANTS_INVOICE = ("rechnung schicken", "schicken sie uns bitte die rechnung", "schicken sie mir bitte die rechnung",
                       "bitte die rechnung", "rechnung zusenden", "rechnung senden", "rechnung zukommen")
_MAIL_WANTS_VISIT = ("termin machen", "termin vereinbaren", "bitte termin", "bitte einen termin", "terminvorschlag",
                     "jemanden schicken", "vorbeikommen", "vorbei kommen", "termin geben")
_MAIL_CANCELS = ("kuendige", "kuendigen", "kuendigung", "gekuendigt")
_PAID_CLAIM = re.compile(r"\b(?:bereits|schon|haben\s+(?:wir|ich)|wurde|ist)\b(?:[^.\n]|\.(?=\d)){0,60}?"
                         r"\b(?:ueberwiesen|bezahlt|beglichen)\b")
_SOME_DAY = re.compile(r"\b(\d{1,2}\.\d{1,2}\.(?:\d{4}|\d{2})?)")
_DEADLINE = re.compile(r"\bbis\s+(?:zum\s+|spaetestens\s+)?(\d{1,2}\.\d{1,2}\.(?:\d{4}|\d{2})?)")


def _short_day(s: str) -> str:
    """'30.10.2026' -> '30.10.'"""
    parts = [p for p in s.split(".") if p]
    return f"{parts[0].zfill(2)}.{parts[1].zfill(2)}." if len(parts) >= 2 else s


def _mail_work(model: dict, records: dict, by_id: dict, title, today: date, outrefs: dict | None,
               done: set | None, ledger: dict | None = None) -> list[dict]:
    """The inbox as part of the firm's processes: an order, an inquiry or a complaint that came by mail
    and has nothing yet that answers it – no order, no offer for that customer since. A complaint
    waits until somebody marks it done."""
    if not outrefs:
        return []
    specs = {t["id"]: t for t in model["types"]}
    procs = {p["type"]: p for p in model.get("processes", [])}
    concept = {t["id"]: (t.get("concept") or "") for t in model["types"]}

    def kind_of(tid):
        return specs.get(tid, {}).get("kind")
    # what answers a mail: an order (or an offer) for that customer, dated on or after the mail
    answers: dict[str, dict[int, list[date]]] = {"order": {}, "ask": {}}
    targets: dict[str, list[tuple[str, str]]] = {"order": [], "ask": []}
    used: Counter = Counter()  # (type, customer): how this customer usually orders
    for t in sorted(model["types"], key=lambda t: concept[t["id"]] not in ("auftrag", "angebot")):
        c = concept[t["id"]]
        which = "order" if c in ("auftrag", "bestellung") else "ask" if c in ("angebot", "verkaufschance") else None
        if not which or t.get("incoming") or kind_of(t["id"]) != "transaction":
            continue
        p = procs.get(t["id"]) or {}
        party = p.get("party") or next((a["id"] for a in t["attrs"] if a["kind"] == "ref" and
                                        concept.get(a.get("ref") or "") == "kunde"), None)
        dattr = (p.get("start") or {}).get("attr") or next((a["id"] for a in t["attrs"]
                                                            if a["kind"] in ("date", "datetime")), None)
        if not party:
            continue
        targets[which].append((t["id"], party))
        for r in records.get(t["id"], []):
            pv = r["data"].get(party)
            used[(t["id"], pv)] += 1
            d = (as_date(r["data"].get(dattr)) if dattr else None) or as_date((r.get("created_at") or "")[:10])
            if isinstance(pv, int) and d:
                answers[which].setdefault(pv, []).append(d)
                if which == "order":
                    answers["ask"].setdefault(pv, []).append(d)  # an order answers an inquiry too
    from .pdfinvoice import _NEW_BANK
    invoices_of: dict[int, list[date]] = {}  # an invoice for that customer since: the asked-for invoice is written
    for t in model["types"]:
        if concept[t["id"]] == "rechnung" and not t.get("incoming"):
            p = procs.get(t["id"]) or {}
            pa, da = p.get("party"), (p.get("start") or {}).get("attr")
            for r in records.get(t["id"], []) if pa else []:
                d = (as_date(r["data"].get(da)) if da else None) or as_date((r.get("created_at") or "")[:10])
                if isinstance(r["data"].get(pa), int) and d:
                    invoices_of.setdefault(r["data"][pa], []).append(d)
    items = []
    for d in records.get("doc", []):
        dd = d["data"]
        if str(dd.get("doc_kind") or "") != "E-Mail" or (done and str(d["id"]) in done):
            continue
        when = as_date(str(dd.get("doc_date") or "")[:10])
        if not when or when > today:
            continue
        sender = fold(str(dd.get("doc_from") or ""))
        subject = str(dd.get("doc_title") or "")
        body = str(dd.get("doc_text") or "")[:3000]
        text = fold(subject + "\n" + body)
        if any(w in sender or w in text[:400] for w in _MAIL_BULK):
            continue
        refs = [to for to, attr, k, how in outrefs.get(d["id"], []) if to in by_id]
        masters = [to for to in refs if kind_of(by_id[to]["type"]) == "master"]
        invoice = next((to for to in refs if concept[by_id[to]["type"]] == "rechnung"
                        and not specs[by_id[to]["type"]].get("incoming")), None)
        entry = (ledger or {}).get(invoice) if invoice else None
        claims = bool(entry and entry["state"] in ("offen", "überfällig", "teilbezahlt") and _PAID_CLAIM.search(text))
        if (today - when).days > _MAIL_DAYS and not claims:
            continue  # an old mail – unless it says an invoice is paid that still is not
        if _NEW_BANK.search(body) or _NEW_BANK.search(subject):
            items.append(dict(rid=d["id"], title=subject or "E-Mail", party=None, days=(today - when).days, money=None,
                              mail="bank", act=None,
                              reason=f"kündigt am {when.strftime('%d.%m.')} eine neue Bankverbindung an – vor jeder "
                                     f"Zahlung beim bekannten Ansprechpartner anrufen, nicht unter der Nummer aus der Mail"))
            continue
        if any(concept[by_id[m]["type"]] == "lieferant" for m in masters):
            continue  # a supplier's mail is about our purchase, not a customer's wish (risks are checked elsewhere)
        party = next((m for m in masters if concept[by_id[m]["type"]] == "kunde"), None) or \
            next((m for m in masters if concept[by_id[m]["type"]] != "mitarbeiter"), None)
        contract = next((to for to in refs if concept[by_id[to]["type"]] == "vertrag"), None)
        subj = fold(subject)
        if claims:
            day = next((m.group(1) for m in _SOME_DAY.finditer(text[_PAID_CLAIM.search(text).start():][:120])), None)
            what = "claim"
            reason = (f"sagt am {when.strftime('%d.%m.')}, {title(invoice)} sei {('am ' + _short_day(day) + ' ') if day else ''}"
                      f"bezahlt – im Kontoauszug ist keine Zahlung zu finden")
        elif contract and any(w in text for w in _MAIL_CANCELS):
            what = "cancel"
            to_day = re.search(r"\bzum\s+(\d{1,2}\.\d{1,2}\.(?:\d{4}|\d{2})?)", text)
            noted = any("kuendig" in fold(str(v)) for v in by_id[contract]["data"].values() if isinstance(v, str))
            reason = (f"Kündigung {title(contract)}" + (f" zum {_short_day(to_day.group(1))}" if to_day else "")
                      + (" – in Ihrer Vertragsliste schon eingetragen; schriftlich bestätigt?" if noted
                         else " – noch nicht in der Vertragsliste"))
        elif any(w in text for w in _MAIL_COMPLAINT) or (invoice and subj.startswith(("rueckfrage", "frage"))):
            what = "complaint"
            until = _DEADLINE.search(text)
            reason = (f"Rückfrage oder Reklamation vom {when.strftime('%d.%m.')}" + (f" zu {title(invoice)}" if invoice else "")
                      + (f" – Frist {_short_day(until.group(1))}" if until else ""))
        elif any(w in text for w in _MAIL_WANTS_INVOICE + _MAIL_WANTS_VISIT):
            wants = [x for x, ws in (("die Rechnung", _MAIL_WANTS_INVOICE), ("einen Termin", _MAIL_WANTS_VISIT))
                     if any(w in text for w in ws)]
            if wants == ["die Rechnung"] and party is not None and any(x >= when for x in invoices_of.get(party, [])):
                continue  # the invoice was written since
            what = "request"
            reason = f"bittet am {when.strftime('%d.%m.')} um {' und '.join(wants)}"
        elif any(w in subj for w in _MAIL_ORDER) or (not subj.startswith(("aw:", "re:", "wg:", "fwd:")) and
                                                     any(w in text[:600] for w in _MAIL_ORDER[:5])):
            what = "order"
            reason = f"Bestellung per E-Mail vom {when.strftime('%d.%m.')}"
        elif any(w in subj for w in _MAIL_ASK):
            what = "ask"
            reason = f"Anfrage vom {when.strftime('%d.%m.')}"
        else:
            continue
        if what in ("order", "ask") and party is not None and any(x >= when for x in answers[what].get(party, [])):
            continue  # an order or an offer for that customer came after the mail
        act = None
        if what in ("complaint", "claim"):
            act = dict(href=f"/r/{invoice}", label="Rechnung ansehen") if invoice else None
        elif what == "cancel":
            act = dict(href=f"/r/{contract}", label="Vertrag ansehen")
        elif what == "request":
            inv_t = next((t for t in model["types"] if concept[t["id"]] == "rechnung" and not t.get("incoming")), None)
            pa = (procs.get(inv_t["id"]) or {}).get("party") if inv_t else None
            if inv_t and pa and party is not None and "Rechnung" in reason:
                act = dict(href=f"/t/{inv_t['id']}/neu?a_{pa}={party}", label=f"+ {inv_t['name']}")
        elif party is not None:
            fits = [(tid, pattr) for tid, pattr in targets[what]
                    if next((a for a in specs[tid]["attrs"] if a["id"] == pattr), {}).get("ref") == by_id[party]["type"]]
            if fits:
                tid, pattr = max(fits, key=lambda x: used[(x[0], party)])  # stable: the first (an "Auftrag") on a tie
                act = dict(href=f"/t/{tid}/neu?a_{pattr}={party}", label=f"+ {specs[tid]['name']}")
        items.append(dict(rid=d["id"], title=subject or "E-Mail", party=title(party) if party else None,
                          days=(today - when).days, money=None, reason=reason, mail=what, act=act,
                          invoice=invoice, when=when.isoformat()))
    if not items:
        return []
    order = {"bank": 0, "complaint": 1, "claim": 2, "order": 3, "request": 4, "cancel": 5, "ask": 6}
    items.sort(key=lambda x: (order[x["mail"]], -x["days"]))
    urgent = any(x["mail"] in ("bank", "complaint", "claim", "order") for x in items)
    return [dict(id="mail:open", type="doc", kind="mail", severity=2 if urgent else 1,
                 title="E-Mails, die auf Sie warten", count=len(items), amount=None, items=items[:30], action=None,
                 explain="Reklamationen, Bitten, Kündigungen, Bestellungen und Anfragen aus den eingeworfenen Mails, "
                         "zu denen noch nichts geschehen ist. Was erledigt ist, lässt sich abhaken.")]


def step_dates_of(p: dict, spec: dict, records: dict, by_id: dict, mention_refs: dict, ledger: dict | None,
                  today: date, void, draft_of: dict | None = None, cancelled=None) -> dict[str, dict[int, date]]:
    """{step id: {case rid: day}} – when each case of process `p` reached each of its steps: by its own date
    columns, by the records that point to it (the invoice of an order) or name it, by a status word, and
    for "bezahlt" by the money. `void` tells a cancelled child; `draft_of` and `cancelled` collect drafts and
    cancellations on the way."""
    recs = [r for r in records.get(p["type"], []) if not is_draft(r)]
    rid_set = {r["id"] for r in recs}
    sattr_p = (p.get("status") or {}).get("attr") or next(
        (a["id"] for a in spec["attrs"] if a.get("role") == "status" and not a.get("hidden")), None)

    def start_of(rid):
        return as_date(by_id[rid]["data"].get(p["start"]["attr"])) or today

    step_dates = {}
    for st in p["steps"]:
        d = {}
        for src in [st] + st.get("also", []):
            if src["source"] == "own":
                for r in recs:
                    v = event_date(r["data"].get(src["attr"]), as_date(r["data"].get(p["start"]["attr"])))
                    if v:
                        d[r["id"]] = min(v, d.get(r["id"], v))
            elif src["rel_kind"] == "own_ref":
                for r in recs:
                    c = by_id.get(r["data"].get(src["rel_attr"]))
                    if c and c["type"] == src["type"] and void(c):
                        if cancelled:
                            cancelled(st["id"], r["id"], c, src["attr"])
                    elif c and c["type"] == src["type"] and not is_draft(c):
                        v = as_date(c["data"].get(src["attr"]))
                        if v:
                            d[r["id"]] = min(v, d.get(r["id"], v))
            elif src["rel_kind"] == "mention":
                for dst, srcs in mention_refs.get(src["rel_attr"], {}).items():
                    if dst in rid_set:
                        ds = [as_date(by_id[s]["data"].get(src["attr"])) for s in srcs if s in by_id]
                        ds = [x for x in ds if x]
                        if ds:
                            d[dst] = min(ds + ([d[dst]] if dst in d else []))
            else:
                for c in records.get(src["type"], []):
                    t = c["data"].get(src["rel_attr"])
                    if t in rid_set and is_draft(c):
                        if draft_of is not None:
                            draft_of[t] = c["id"]  # drafted, not yet issued
                        continue
                    if t in rid_set and void(c):
                        if cancelled:
                            cancelled(st["id"], t, c, src["attr"])
                    elif t in rid_set:
                        v = as_date(c["data"].get(src["attr"]))
                        if v:
                            d[t] = min(v, d.get(t, v))
        if sattr_p and fold(st["label"]) != "bezahlt":
            # "abgerechnet" in the order book: invoiced, even where no invoice names the order
            for r in recs:
                if r["id"] not in d and lexicon.status_reaches(st["label"], r["data"].get(sattr_p)):
                    d[r["id"]] = start_of(r["id"])
        if ledger is not None and fold(st["label"]) == "bezahlt" and any(rid in ledger for rid in rid_set):
            # paid is what the money says, not what a purpose names
            d = {rid: e["paid_date"] or start_of(rid) for rid, e in ledger.items()
                 if rid in rid_set and e["state"] in ("bezahlt", "überzahlt", "verrechnet")}
        step_dates[st["id"]] = d
    return step_dates


def value_chains(model: dict, records: dict, mention_refs: dict, ledger: dict | None = None,
                 today: date | None = None) -> list[dict]:
    """From the first step of a business case to the money ("bis das Geld da ist"). Processes are chained
    where a step of one is the record of another: an offer is "beauftragt" by its order, the order
    "berechnet" by its invoice, which is then "bezahlt". Per segment: the usual days and how many cases got
    there; for the whole chain: the usual days from start to end, and the segment that takes longest."""
    today = today or date.today()
    specs = {t["id"]: t for t in model["types"]}
    procs = {p["type"]: p for p in model.get("processes", []) if p["type"] in specs}
    by_id = {r["id"]: r for rs in records.values() for r in rs}
    negative_of = {p["type"]: ((p.get("status") or {}).get("attr"), set((p.get("status") or {}).get("negative") or []))
                   for p in procs.values()}

    def void(c):
        meta = c.get("meta") or {}
        attr, neg = negative_of.get(c["type"], (None, set()))
        return bool(meta.get("storno_of") or meta.get("storno_by") or (attr and str(c["data"].get(attr)) in neg))

    cache = {}

    def dates_of(p):
        if p["type"] not in cache:
            cache[p["type"]] = step_dates_of(p, specs[p["type"]], records, by_id, mention_refs, ledger, today, void)
        return cache[p["type"]]

    def link(p):
        """The step at which the case goes on in a record of its own – its invoice first, also where the invoice
        only names it ("P-2025-008" in the text); a supplier's invoice for a project is a cost, not the way to
        the money, and a ticket is no step towards it."""
        cands = [st for st in p["steps"] if st["source"] == "child" and st.get("rel_kind") in ("ref", "own_ref", "mention")
                 and st.get("type") in procs and st["type"] != p["type"] and not specs[st["type"]].get("incoming")]
        return min(cands, key=lambda st: (fold(st["label"]) != BILLED, st.get("rel_kind") == "mention",
                                          -(st.get("share") or 0)), default=None)

    def regular(st, lnk):
        return st is lnk or (st.get("share") or 1) >= 0.5  # time sheets for a tenth of the jobs are no milestone

    def children(st, rids):
        """The records the step's child type holds for these cases (the invoices of these orders)."""
        out = set()
        if st["rel_kind"] == "own_ref":
            for rid in rids:
                c = by_id.get(by_id[rid]["data"].get(st["rel_attr"]))
                if c and c["type"] == st["type"] and not void(c) and not is_draft(c):
                    out.add(c["id"])
        elif st["rel_kind"] == "mention":
            for rid in rids:
                for cid in (mention_refs.get(st["rel_attr"]) or {}).get(rid, []):
                    c = by_id.get(cid)
                    if c and c["type"] == st["type"] and not void(c) and not is_draft(c):
                        out.add(cid)
        else:
            for c in records.get(st["type"], []):
                if c["data"].get(st["rel_attr"]) in rids and not void(c) and not is_draft(c):
                    out.add(c["id"])
        return out

    chains = []
    for root in procs.values():
        hops, cur, seen = [], root, {root["type"]}
        while True:
            st = link(cur)
            upto = cur["steps"][:cur["steps"].index(st) + 1] if st else cur["steps"]
            hops.append((cur, [x for x in upto if regular(x, st)], st))
            if not st or st["type"] in seen:
                break
            seen.add(st["type"])
            cur = procs[st["type"]]
        if len(hops) < 2 or not hops[-1][1] or fold(hops[-1][1][-1]["label"]) != "bezahlt":
            continue  # the case does not go on in another record, or does not end in money
        nodes = [specs[root["type"]]["name"]] + [s["label"] for _, upto, _ in hops for s in upto]
        paths = []
        for r in records.get(root["type"], []):
            start = as_date(r["data"].get(root["start"]["attr"]))
            if not start or is_draft(r) or void(r):
                continue
            path, rids = [start], {r["id"]}
            for p, upto, st in hops:
                d = dates_of(p)
                kids = children(st, rids) if st else set()
                if len(kids) > 2:
                    kids = set()  # billed month by month: a running case, no way to one payment
                for s in upto:
                    got = [d.get(s["id"], {}).get(x) for x in rids] if rids else [None]
                    if s is st:
                        # invoiced with the last invoice (a down payment is billed before the work is done),
                        # paid when the last one is paid
                        nxt = procs[st["type"]]["start"]["attr"]
                        path.append(max((as_date(by_id[c]["data"].get(nxt)) for c in kids), default=None) if kids else None)
                    else:
                        path.append(max(got) if got and all(got) else None)
                rids = kids
            path += [None] * (len(nodes) - len(path))
            paths.append(path)
        if len(paths) < 5:
            continue
        segments = []
        for k in range(1, len(nodes)):
            days = [(x[k] - x[k - 1]).days for x in paths if x[k] and x[k - 1] and (x[k] - x[k - 1]).days >= -1]
            days = [max(0, v) for v in days]
            segments.append(dict(frm=nodes[k - 1], to=nodes[k], n=len(days), share=round(len(days) / len(paths), 3),
                                 median=statistics.median(days) if days else None,
                                 p80=_pct(days, 0.8) if days else None))
        whole = [(x[-1] - x[0]).days for x in paths if x[-1] and x[0] and x[-1] >= x[0]]
        if len(whole) < 5:
            continue
        timed = [k for k, sg in enumerate(segments) if sg["median"] is not None and sg["n"] >= 5]
        slow = max(timed, key=lambda k: segments[k]["median"]) if timed else None
        chains.append(dict(id=f"v_{root['type']}", type=root["type"], nodes=nodes, segments=segments, n=len(paths),
                           title=f"{specs[root['type']]['plural']} – bis das Geld da ist",
                           total=dict(median=statistics.median(whole), p80=_pct(whole, 0.8), n=len(whole)),
                           slowest=slow))
    chains.sort(key=lambda c: (-len(c["nodes"]), -c["n"]))
    return chains[:3]


def compute_work(model: dict, records: dict, mention_refs: dict, today: date | None = None,
                 outrefs: dict | None = None, titles_in: dict | None = None,
                 pending_payments: dict | None = None, ledger: dict | None = None,
                 mails_done: set | None = None) -> list[dict]:
    from .grow import record_title

    today = today or date.today()
    specs = {t["id"]: t for t in model["types"]}
    titles = dict(titles_in or {})

    def title(rid):
        if rid in titles:
            return titles[rid]
        r = by_id.get(rid)
        titles[rid] = record_title(specs[r["type"]], r["data"], rid) if r else f"#{rid}"
        return titles[rid]

    by_id = {r["id"]: r for rs in records.values() for r in rs}
    negative_of = {p["type"]: ((p.get("status") or {}).get("attr"), set((p.get("status") or {}).get("negative") or []))
                   for p in model.get("processes", [])}

    def void(c):
        """A cancelled invoice (or the cancellation itself) does not bill the order."""
        meta = c.get("meta") or {}
        if meta.get("storno_of") or meta.get("storno_by"):
            return True
        attr, neg = negative_of.get(c["type"], (None, set()))
        return bool(attr and str(c["data"].get(attr)) in neg)

    groups = []
    draft_of: dict[int, int] = {}   # order -> its invoice draft
    drafts = []
    for p in model.get("processes", []):
        spec = specs[p["type"]]
        drafts += [(r, p) for r in records.get(p["type"], []) if is_draft(r)]
        recs = [r for r in records.get(p["type"], []) if not is_draft(r)]
        rid_set = {r["id"] for r in recs}

        def start_of(rid, _p=p):
            return as_date(by_id[rid]["data"].get(_p["start"]["attr"])) or today

        voided = {}  # step -> case -> (day, rid) of its latest cancelled invoice

        def cancelled(sid, rid, c, attr):
            # the day of the cancellation: Physarum's own storno knows it, a book only has the invoice's date
            v = as_date((((c.get("meta") or {}).get("storno") or {}).get("ts") or "")[:10]) or \
                as_date(c["data"].get(attr)) or as_date((c.get("created_at") or "")[:10]) or date.min
            if v >= voided.setdefault(sid, {}).get(rid, (date.min, None))[0]:
                voided[sid][rid] = (v, c["id"])

        step_dates = step_dates_of(p, spec, records, by_id, mention_refs, ledger, today, void, draft_of, cancelled)
        negative = set((p.get("status") or {}).get("negative") or [])
        sattr = (p.get("status") or {}).get("attr")
        other_neg = [(x["attr"], set(x["values"])) for x in (p.get("status") or {}).get("negative_other", [])]
        due_by_step = {dl["step"]: dl for dl in p["deadlines"] if dl.get("step")}
        covered = {(d["type"], d["attr"]) for d in model.get("dues", [])}
        free_dues = [dl for dl in p["deadlines"] if not dl.get("step") and (p["type"], dl["attr"]) not in covered]
        never = _never_reached(spec, recs, p, step_dates, today)
        skonto = _skonto_attrs(spec)
        # where reaching a step is planned (a planned end for every project that ended), a case
        # without such a date is not waiting for it: "unbefristet"
        planned = {}
        for sid, dl in due_by_step.items():
            reached = [r for r in recs if step_dates.get(sid, {}).get(r["id"])]
            if len(reached) >= 5 and sum(1 for r in reached if r["data"].get(dl["attr"]) is not None) >= 0.7 * len(reached):
                planned[sid] = dl["attr"]
        buckets = defaultdict(list)
        for r in recs:
            if sattr and str(r["data"].get(sattr)) in negative:
                continue
            if ledger is not None and (ledger.get(r["id"]) or {}).get("state") == "storniert":
                continue  # cancelled by a credit note: nothing to wait for
            if any(str(r["data"].get(a)) in vals for a, vals in other_neg):
                continue
            start = as_date(r["data"].get(p["start"]["attr"]))
            if not start:
                continue
            last = start
            reached = False  # some step after the start is done (finished, delivered)
            for si, st in enumerate(p["steps"]):
                dv = step_dates[st["id"]].get(r["id"])
                if dv:
                    last = max(last, dv)
                    reached = reached or (st.get("share") or 1) >= 0.5
                    continue
                if any(step_dates[x["id"]].get(r["id"]) for x in p["steps"][si + 1:] if (x.get("share") or 1) >= 0.5):
                    continue  # a later (regular) step happened: this one was skipped, not forgotten
                optional = (st.get("share") or 1) < 0.5  # most cases go without it (time sheets for some months)
                gone = voided.get(st["id"], {}).get(r["id"])
                if gone and (today - gone[0]).days > _VOID_GRACE:
                    break  # its invoice was cancelled long ago and none followed: decided, not forgotten
                # first missing step: is it overdue or waiting unusually long?
                w0 = date.fromisoformat(st["window"][0]) if st.get("window") else None
                expected_by = start + timedelta(days=(st.get("median_days") or 0))
                if w0 and expected_by < w0 - timedelta(days=7):
                    if optional:
                        continue  # no time sheets kept back then: says nothing about the invoice
                    break  # outside the time span covered by the data: unknown stays unknown
                money = _money(r, p)
                paid_part = None
                if ledger is not None and r["id"] in ledger and fold(st["label"]) == "bezahlt":
                    e = ledger[r["id"]]
                    if e.get("retention"):
                        break  # the rest is a retention until the warranty ends: nothing to chase
                    money = e["open"]  # only what is still missing
                    paid_part = e["paid"] if e["paid"] > 0.005 else None
                # invoiced the day the job is done, as most cases are (a web order is its own receipt)
                billing = st.get("source") == "child" and fold(st["label"]) == BILLED and st.get("median_days") == 0 \
                    and (st.get("share") or 1) >= 0.5
                dl = due_by_step.get(st["id"])
                due = as_date(r["data"].get(dl["attr"])) if dl else None
                due_how = None
                if dl and not due and ledger is not None and (ledger.get(r["id"]) or {}).get("due_attr") == dl["attr"]:
                    due, due_how = ledger[r["id"]]["due"], ledger[r["id"]]["due_how"]  # reckoned, not in the book
                entry = (ledger or {}).get(r["id"]) or {}
                if entry.get("unseen") and fold(st["label"]) == "bezahlt":
                    break  # due before the bank statement starts: unknown, not overdue
                if entry.get("outgoing") and fold(st["label"]) == "bezahlt":
                    # the firm's own bills: what to pay in the next two weeks, Skonto first
                    cut = _skonto(r, skonto, entry, today) if skonto else None
                    if due and ((due - today).days <= 14 or (cut and cut["days"] <= 7)):
                        buckets[(st["id"], "payable")].append(dict(rid=r["id"], days=(due - today).days, money=money,
                                                                   due=due.isoformat(), name=dl["name"], due_how=due_how,
                                                                   reason=cut["text"] if cut else None))
                    break
                if due and due < today:
                    buckets[(st["id"], "overdue")].append(dict(rid=r["id"], days=(today - due).days, money=money,
                                                               due=due.isoformat(), paid=paid_part, due_how=due_how))
                elif st.get("p80_days") is not None and st.get("n", 0) >= 5 and \
                        ((st.get("median_days") or 0) > 0 or billing) and \
                        not (st["id"] in planned and r["data"].get(planned[st["id"]]) is None) and \
                        not any((st["id"], a, str(r["data"].get(a))) in never for a in never_attrs(never)):
                    waited = (today - last).days
                    limit = max(st["p80_days"] * 1.25, (st["median_days"] or 0) + 2, 2)
                    # a word where the invoice's number goes ("Kulanz", "intern"): decided, nothing to invoice
                    decided = any(((r.get("meta") or {}).get("raw") or {}).get(x["rel_attr"]) not in (None, "")
                                  for x in [st] + st.get("also", []) if x.get("rel_kind") == "own_ref")
                    if reached and st.get("source") == "child" and fold(st["label"]) == BILLED and not decided \
                            and 0 <= waited < 1100:
                        # finished and not invoiced: money waiting to be asked for – all of it, the oldest first
                        buckets[(st["id"], "ready")].append(dict(
                            rid=r["id"], days=waited, money=money, usual=st["median_days"], late=waited > limit,
                            reason=f"{title(gone[1])} storniert, noch keine neue" if gone else None))
                    elif waited > limit and waited < 1100 and not optional and not decided:
                        # claims become time-barred after three years; a step most cases never reach (an offer
                        # that is never ordered) is nothing one waits for
                        buckets[(st["id"], "late")].append(dict(rid=r["id"], days=waited, money=money,
                                                                usual=st["median_days"]))
                    elif due and (due - today).days <= 3:
                        buckets[(st["id"], "soon")].append(dict(rid=r["id"], days=(due - today).days, money=money,
                                                                due=due.isoformat()))
                if optional:
                    continue
                break
            for dl in free_dues:
                if skonto and dl["attr"] == skonto["until"]:
                    continue  # a term of the invoice, shown with it
                rg = due_range(r["data"].get(dl["attr"]))
                due = rg[1] if rg else None
                e = ledger.get(r["id"]) if ledger else None
                if e and e.get("retention"):
                    continue
                due_how = None
                if not due and e and e.get("due_attr") == dl["attr"]:
                    due, due_how = e["due"], e["due_how"]  # reckoned, not in the book
                if e and (e["state"] in ("bezahlt", "überzahlt", "storniert", "verrechnet") or e.get("unseen")):
                    continue  # the money has gone out already, or the statement does not reach back that far
                if due and (due - today).days < -30 and not e:
                    continue  # long past, and nothing says whether it happened: history, not work
                cut = _skonto(r, skonto, e, today) if skonto and e and e["outgoing"] else None
                if due and ((due - today).days <= 14 or (cut and cut["days"] <= 7)):
                    kind = "payable" if e and e["outgoing"] else "due"
                    buckets[(dl["attr"], kind)].append(dict(rid=r["id"], days=(due - today).days,
                                                            money=e["open"] if e else _money(r, p),
                                                            due=due.isoformat(), name=dl["name"], due_how=due_how,
                                                            reason=cut["text"] if cut else None))
        for (sid, kind), items in buckets.items():
            st = next((s for s in p["steps"] if s["id"] == sid), None)
            items.sort(key=lambda x: (-x["days"] if kind in ("overdue", "late", "ready") else x["days"]))
            total = round(sum(x["money"] or 0 for x in items), 2)
            party = p.get("party")
            for x in items:
                r = by_id[x["rid"]]
                x["title"] = title(x["rid"])
                pv = r["data"].get(party) if party else None
                x["party"] = title(pv) if isinstance(pv, int) and pv in by_id else (pv if isinstance(pv, str) else None)
                if pending_payments and x["rid"] in pending_payments:
                    x["maybe_paid"] = pending_payments[x["rid"]]  # a transfer without reference fits: do not dun
                if x["rid"] in draft_of and st and st["source"] == "child":
                    x["draft"] = draft_of[x["rid"]]
            if kind == "overdue":
                head = f"{spec['plural']} {st['phrase']} – überfällig"
                sev = 3
            elif kind == "late":
                head = f"{spec['plural']} {st['phrase']} – länger als üblich"
                sev = 2
            elif kind == "ready":
                before = next((x["label"] for x in reversed(p["steps"][:p["steps"].index(st)]) if (x.get("share") or 1) >= 0.5),
                              None) if st in p["steps"] else None
                head = f"{spec['plural']} {before or 'erledigt'} – noch nicht {st['label']}"
                sev = 2 if any(x["late"] for x in items) else 1
            elif kind == "soon":
                head = f"{spec['plural']} {st['phrase']} – bald fällig"
                sev = 1
            elif kind == "payable":
                head = f"{spec['plural']} zu bezahlen"
                sev = 2 if any(x["days"] < 0 for x in items) else 1
            else:
                dname = items[0].get("name", "Termin")
                head = f"{spec['plural']}: {dname} steht an"
                sev = 2 if any(x["days"] < 0 for x in items) else 1
            action = None
            if kind == "payable":
                pass  # paid is what the bank statement says
            elif st and st["source"] == "own":
                action = dict(kind="set_date", attr=st["attr"], label=st["label"])
            elif st and st["source"] == "child" and (specs.get(st["type"]) or {}).get("concept") not in _FACTS:
                action = dict(kind="create_child", type=st["type"], attr=st["rel_attr"], label=st["name"])
            groups.append(dict(id=f"{p['id']}:{sid}:{kind}", type=p["type"], kind=kind, severity=sev, title=head,
                               count=len(items), amount=total, items=items[:50], action=action,
                               step=st["label"] if st else None,
                               explain=_explain(p, st, kind)))
    if drafts:
        items = []
        for r, p in drafts:
            made = as_date((r.get("created_at") or "")[:10]) or today
            pv = r["data"].get(p.get("party")) if p.get("party") else None
            items.append(dict(rid=r["id"], title=title(r["id"]), days=(today - made).days, money=_money(r, p),
                              party=title(pv) if isinstance(pv, int) and pv in by_id else None,
                              reason="Entwurf seit " + ("heute" if made == today else made.strftime("%d.%m.%Y"))))
        items.sort(key=lambda x: -x["days"])
        names = {specs[p["type"]]["plural"] for _, p in drafts}
        groups.append(dict(id="drafts", type=drafts[0][1]["type"], kind="draft", severity=2 if items[0]["days"] >= 2 else 1,
                           title=f"Entwürfe, noch nicht ausgestellt ({', '.join(sorted(names))})", count=len(items),
                           amount=round(sum(x["money"] or 0 for x in items), 2), items=items[:50], action=None,
                           explain="Erst beim Ausstellen bekommen sie ihre Nummer und werden verschickt. Bis dahin schuldet niemand etwas."))
    if ledger:
        from .payments import problems
        bad = problems(ledger)
        if bad:
            items = []
            for e in sorted(bad, key=lambda e: (e["state"] != "überzahlt", -abs(e["open"]))):
                r = by_id.get(e["rid"])
                if not r:
                    continue
                p = next((x for x in model.get("processes", []) if x["type"] == e["type"]), {})
                pv = r["data"].get(p.get("party")) if p.get("party") else None
                items.append(dict(rid=e["rid"], title=title(e["rid"]), days=0, money=e["open"] if e["open"] > 0 else None,
                                  party=title(pv) if isinstance(pv, int) and pv in by_id else None,
                                  reason="; ".join(e["notes"]) or e["state"], state=e["state"]))
            if items:
                groups.append(dict(id="pay:problems", type=bad[0]["type"], kind="payment", severity=3,
                                   title="Zahlungen, die nicht aufgehen", count=len(items),
                                   amount=round(sum(x["money"] or 0 for x in items), 2), items=items[:50], action=None,
                                   explain="Teilzahlungen, doppelte Zahlungen, Rücklastschriften und Geld auf stornierten "
                                           "Rechnungen – nach Betrag aus dem Kontoauszug, nicht nach Nummer."))
    if outrefs is not None:
        from .reconcile import risk_items, supplier_items
        tmap = titles_in or {r: title(r) for r in by_id}
        risks = risk_items(model, records, outrefs, tmap)
        more, checks = supplier_items(model, records, outrefs, tmap, ledger, today,
                                      reported={(x["partner"], x.get("iban")) for x in risks})
        risks += more
        if checks:
            groups.append(dict(id="check:incoming", type=checks[0].get("type") or "doc", kind="risk", severity=2,
                               title="Eingangsrechnungen vor dem Bezahlen prüfen", count=len(checks), amount=None,
                               items=checks, action=None,
                               explain="E-Rechnungen, deren Zahlen nicht aufgehen oder denen Pflichtangaben fehlen, "
                                       "und die erste Rechnung eines neuen Lieferanten."))
        from .reconcile import received_twice
        twice = received_twice(model, records, outrefs)
        for g in groups:
            for x in g["items"] if g["kind"] == "payable" else []:
                if x["rid"] in twice:
                    x["reason"] = "; ".join(filter(None, [x.get("reason"), "zweimal eingegangen ("
                                                          + ", ".join(twice[x["rid"]]) + ") – nur einmal bezahlen"]))
        from .reconcile import unexplained_receipts
        got = unexplained_receipts(model, records, ledger or {}, tmap, today,
                                   pending={x.get("bank") for x in (pending_payments or {}).values()})
        if got:
            groups.append(dict(id="bank:unexplained", type=got and by_id[got[0]["rid"]]["type"], kind="receipt",
                               severity=2, title="Geld erhalten – wofür?", count=len(got),
                               amount=round(sum(x["money"] for x in got), 2), items=got[:30], action=None,
                               explain="Eingänge der letzten zwei Monate, die keine Rechnung bezahlen. Eine Anzahlung "
                                       "braucht ihre Anzahlungsrechnung, eine Gutschrift gehört zum Lieferanten."))
        risky = {x["rid"] for x in risks}
        for g in groups:
            held = [x for x in g["items"] if x["rid"] in risky] if g["kind"] == "payable" else []
            if held:  # never on the list of what to pay while the account is in doubt
                g["items"] = [x for x in g["items"] if x["rid"] not in risky]
                g["count"], g["amount"] = len(g["items"]), round(sum(x["money"] or 0 for x in g["items"]), 2)
                g["explain"] += (f" {'Eine Rechnung steht' if len(held) == 1 else f'{len(held)} Rechnungen stehen'} "
                                 f"nicht hier, sondern unter „Vorsicht“.")
        groups = [g for g in groups if g["count"]]
        if risks:
            at_stake = round(sum(x.get("money") or 0 for x in risks), 2) or None
            groups.append(dict(id="risk:iban", type="doc", kind="risk", severity=3, top=True,
                               title="Vorsicht: Bankverbindung oder Absender passen nicht zum Lieferanten",
                               count=len(risks), amount=at_stake, items=risks, action=None,
                               explain="Vor einer Zahlung telefonisch beim bekannten Ansprechpartner prüfen. "
                                       "So sieht Rechnungsbetrug typischerweise aus."))
    mail = _mail_work(model, records, by_id, title, today, outrefs, mails_done, ledger)
    claims = {x["invoice"]: x for g in mail for x in g["items"] if x.get("mail") == "claim"}
    for g in groups:
        for x in g["items"] if g["kind"] == "overdue" else []:
            if x["rid"] in claims:  # the customer says it is paid: look before reminding
                x["claim"] = f"Kunde sagt: bezahlt (Mail vom {_short_day(date.fromisoformat(claims[x['rid']]['when']).strftime('%d.%m.%Y'))})"
    groups += mail
    groups += _due_work(model, records, by_id, title, today)
    groups += _threshold_work(model, records, title)
    groups += _rhythm_work(model, records, by_id, title, today)
    groups += _reach_work(model, records, by_id, title, today)
    groups += _budget_work(model, records, mention_refs, title)
    # a suspected fraud first: money about to go to the wrong account outweighs money that is late
    groups.sort(key=lambda g: (-g["severity"], not g.get("top"), -(g["amount"] or 0), -g["count"]))
    return groups


_RUNNING = {"retainer", "monatlich", "monthly", "laufend", "recurring", "abo", "abonnement", "subscription",
            "monatspauschale", "pauschale", "wiederkehrend"}
_BUDGET_WORDS = {"budget", "festpreis", "auftragswert", "kostenrahmen", "angebotssumme", "projektbudget",
                 "pauschalpreis", "auftragssumme"}
_RATE_WORDS = {"rate", "satz", "stundensatz", "preis", "einzelpreis", "stueckpreis", "tarif"}


def _budget_work(model, records, mention_refs, title) -> list[dict]:
    """A fixed budget and the work booked on it: more than a fifth over is worth a look while
    there is still time (and a lesson for the next quote when it is too late)."""
    specs = {t["id"]: t for t in model["types"]}
    out = []
    for spec in model["types"]:
        budget = next((a for a in spec["attrs"] if a["kind"] == "money" and not a.get("hidden") and
                       not a.get("virtual") and set(tokens(a["name"])) & _BUDGET_WORDS), None)
        if not budget:
            continue
        recs = records.get(spec["id"], [])
        effort = defaultdict(float)
        sources = []
        invoices = defaultdict(int)
        for rel in model["relations"]:
            src = specs.get(rel["src"])
            if not src or rel["dst"] != spec["id"] or src["kind"] != "transaction":
                continue
            if src.get("concept") == "rechnung" and src.get("incoming"):
                continue  # a freelancer's invoice is a cost of the project, not how it is billed
            if src.get("concept") == "rechnung":
                # how often the thing is invoiced: a retainer every month, a fixed price once or twice
                if rel["kind"] == "mention":
                    for to, frm in mention_refs.get(rel["attr"], {}).items():
                        invoices[to] += len(frm)
                else:
                    for r in records.get(src["id"], []):
                        if isinstance(r["data"].get(rel["attr"]), int):
                            invoices[r["data"][rel["attr"]]] += 1
                continue
            if src.get("concept") != "zeiteintrag" or rel["kind"] not in ("ref", "parent"):
                continue
            vals = [a["id"] for a in src["attrs"] if a["kind"] == "money" and not a.get("virtual")
                    and not set(tokens(a["name"])) & _RATE_WORDS]
            if not vals:
                continue
            sources.append(src["plural"])
            for r in records.get(src["id"], []):
                to = r["data"].get(rel["attr"])
                v = next((r["data"][a] for a in vals if isinstance(r["data"].get(a), (int, float))), None)
                if isinstance(to, int) and v:
                    effort[to] += float(v)
        if not effort:
            continue
        cats = [a["id"] for a in spec["attrs"] if a["kind"] == "text" and a.get("enum")]
        items = []
        for r in recs:
            b = r["data"].get(budget["id"])
            e = effort.get(r["id"], 0.0)
            if not isinstance(b, (int, float)) or b <= 0 or e <= 1.2 * b or invoices.get(r["id"], 0) > 2:
                continue
            if any(set(tokens(str(r["data"].get(a) or ""))) & _RUNNING for a in cats):
                continue  # a retainer's budget is per month
            items.append(dict(rid=r["id"], title=title(r["id"]), money=round(e - b, 2), days=0,
                              reason=f"Aufwand {fmt_eur(e)} bei {budget['name']} {fmt_eur(b)} "
                                     f"({round(e / b * 100)} %)"))
        if items:
            items.sort(key=lambda x: -x["money"])
            out.append(dict(id=f"budget:{spec['id']}", type=spec["id"], kind="budget", severity=2,
                            title=f"{spec['plural']} deutlich über {budget['name']}", count=len(items),
                            amount=round(sum(x["money"] for x in items), 2), items=items[:30], action=None,
                            explain=f"Summe der {' und '.join(dict.fromkeys(sources))} je {spec['name']} verglichen mit "
                                    f"„{budget['name']}“ – ab 120 %. Laufend abgerechnete (mehr als zwei Rechnungen) "
                                    f"bleiben außen vor."))
    return out


def _due_work(model, records, by_id, title, today) -> list[dict]:
    out = []
    specs = {t["id"]: t for t in model["types"]}
    for du in model.get("dues", []):
        spec = specs.get(du["type"])
        if not spec:
            continue
        party = next((a["id"] for a in spec["attrs"] if a["kind"] == "ref" and not a.get("hidden")), None)
        proc = next((x for x in model.get("processes", []) if x["type"] == du["type"]), None)
        closed = set(du.get("closed") or [])
        settled = set()
        for x in du.get("taken") or []:
            if not x["own"]:
                settled |= {c["data"].get(x["attr"]) for c in records.get(x["type"], [])}
        own_taken = [x["attr"] for x in du.get("taken") or [] if x["own"]]
        lead = du.get("offset") or 14  # how far ahead the firm sets the day
        items, lapsed = [], 0
        for r in records.get(du["type"], []):
            v = r["data"].get(du["attr"])
            rg = due_range(v)
            if not rg:
                continue
            start, end = rg
            done = as_date(r["data"].get(du["done"])) if du.get("done") else None
            if done and done >= start - timedelta(days=45):
                continue  # done for this round (a little early counts)
            if du.get("status") and str(r["data"].get(du["status"])) in closed:
                continue  # taken or turned down: nobody to call any more
            if r["id"] in settled or any(r["data"].get(a) not in (None, "") for a in own_taken):
                continue  # an order names it: taken
            if (start - today).days > (30 if du.get("recurring") else 0 if du.get("follow_up") else 14):
                continue  # a maintenance visit is arranged a month ahead; a call is made on the day
            began = as_date(r["data"].get(du["start"])) if du.get("start") else None
            if du.get("lifetime") and (today - end).days > du["lifetime"] - lead:
                lapsed += 1  # months without an answer: lapsed, not a call to make (a day set anew starts afresh)
                continue
            pv = r["data"].get(party) if party else None
            it = dict(rid=r["id"], title=title(r["id"]), days=(end - today).days, money=None,
                      due=end.isoformat(), label=str(v) if start != end else None, name=du["name"],
                      party=title(pv) if isinstance(pv, int) and pv in by_id else None)
            if du.get("follow_up"):
                d = it["days"]
                it["money"] = _money(r, proc) if proc else None  # what the call is worth
                it["reason"] = ((f"vom {began.strftime('%d.%m.')} · " if began else "")
                                + ("heute nachfassen" if d == 0 else f"nachfassen seit {-d} {'Tag' if d == -1 else 'Tagen'}"))
            items.append(it)
        if not items:
            continue
        items.sort(key=lambda x: x["days"])
        late = sum(1 for x in items if x["days"] < 0)
        if du.get("follow_up"):
            make = next((x for x in du.get("taken") or [] if not x["own"]), None)
            action = dict(kind="follow_up", attr=du["attr"], days=du.get("offset") or 14, status=du.get("status"),
                          negative=du.get("negative"),
                          create=dict(type=make["type"], attr=make["attr"], label=make["label"]) if make else None)
            explain = "Nachfassen laut Ihrer Liste – noch keine Zu- oder Absage. "
            if lapsed:
                weeks = (du["lifetime"] - lead) // 7
                explain += (f"{lapsed} ältere {'bleibt' if lapsed == 1 else 'bleiben'} außen vor: "
                            f"{'sein' if lapsed == 1 else 'ihr'} Termin ist seit über {weeks} Wochen vorbei – nach so "
                            f"langer Zeit ohne Antwort {'gilt es' if lapsed == 1 else 'gelten sie'} als verlaufen.")
        else:
            action = dict(kind="set_date", attr=du["done"], label=du["done_label"]) if du.get("done") else None
            explain = ((f"{late} davon schon überschritten. " if late else "") + "Termin aus Ihrer Liste"
                       + ("; mit „✓“ wird er als erledigt eingetragen." if action else "."))
        out.append(dict(id=f"due:{du['type']}:{du['attr']}", type=du["type"], kind="due", severity=2 if late else 1,
                        title=_due_title(spec["plural"], du), count=len(items), amount=None,
                        items=items[:50], step=du.get("done_label"), action=action, explain=explain))
    return out


def _due_title(plural: str, du: dict) -> str:
    """'Angebote nachfassen', 'Fahrzeuge: HU fällig', 'Werkzeug: nächste Prüfung steht an'."""
    name = du["name"].strip()
    words = name.split()
    if du.get("follow_up"):
        verb = [w for w in words if fold(w) not in ("am", "bis", "datum", "termin", "ab")]
        if len(verb) == 1 and fold(verb[0]).endswith("en"):
            return f"{plural} {verb[0].lower()}"
        return f"{plural}: {name}"
    if any(fold(w) in ("faellig", "due") for w in words):
        return f"{plural}: {name}"
    return f"{plural}: {name} steht an"


def _skonto_attrs(spec) -> dict | None:
    """"Skonto bis" and "Skonto %" of a supplier's invoice."""
    until = next((a["id"] for a in spec["attrs"] if a["kind"] in ("date", "datetime") and "skonto" in fold(a["name"])),
                 None)
    if not until:
        return None
    pct = next((a["id"] for a in spec["attrs"] if a["kind"] in ("percent", "number") and "skonto" in fold(a["name"])),
               None)
    return dict(until=until, pct=pct)


def _skonto(r, sk, e, today) -> dict | None:
    """Until when the discount holds, or that it is gone."""
    until = as_date(r["data"].get(sk["until"]))
    if not until or not e or e.get("paid", 0) > 0.005:
        return None
    pct = r["data"].get(sk["pct"]) if sk.get("pct") else None
    pct = float(pct) if isinstance(pct, (int, float)) and not isinstance(pct, bool) else None
    if pct is not None and pct < 1:
        pct *= 100  # a share, not a percentage
    if until < today:
        return dict(days=(until - today).days, text=f"Skonto-Frist {until.strftime('%d.%m.')} verpasst")
    pct_s = f"{pct:g}".replace(".", ",") + " % " if pct else ""
    save = f" ({fmt_eur(e['open'] * pct / 100)})" if pct and e.get("open") else ""
    when = "heute" if until == today else f"bis {until.strftime('%d.%m.')}"
    return dict(days=(until - today).days, text=f"{pct_s}Skonto{save} nur noch {when}")


def _money(r, p):
    for aid in (p.get("gross"), p.get("net")):
        if aid:
            v = r["data"].get(aid)
            if isinstance(v, (int, float)) and not isinstance(v, bool):
                return float(v)
    return None


def _explain(p, st, kind) -> str:
    if kind == "payable":
        return ("Fällig laut Rechnung des Lieferanten, noch keine Zahlung im Kontoauszug. Vor dem Überweisen die "
                "Bankverbindung mit der bekannten vergleichen.")
    if not st:
        return "Termin aus den Daten"
    if kind == "overdue":
        return f"Die Frist ist abgelaufen und „{st['label']}“ fehlt noch."
    if kind == "late":
        m, p80 = round(st["median_days"] or 0), round(st["p80_days"] or 0)
        usual = "am selben Tag" if m <= 0 else ("1 Tag" if m == 1 else f"{m} Tage")
        return (f"Üblich {'ist' if m == 1 else 'sind'} {usual} bis „{st['label']}“ (bei 80 % höchstens "
                f"{p80} {'Tag' if p80 == 1 else 'Tage'}), gelernt aus {st['n']} Fällen."
                if m > 0 else f"Üblich passiert „{st['label']}“ am selben Tag, gelernt aus {st['n']} Fällen.")
    if kind == "soon":
        return "Die Frist läuft in den nächsten Tagen ab."
    return ""


def _threshold_work(model, records, title) -> list[dict]:
    out = []
    for spec in model["types"]:
        for th in spec.get("thresholds") or []:
            items = []
            stock_attr = next((rc["stock"] for rc in model.get("reach", []) if rc["type"] == spec["id"]), None)
            for r in records.get(spec["id"], []):
                v, m = r["data"].get(th["attr"]), r["data"].get(th["min"])
                if th["attr"] == stock_attr and isinstance(r["data"].get("stock_now"), (int, float)):
                    v = r["data"]["stock_now"]  # today's stock, not the inventory's
                if isinstance(v, (int, float)) and isinstance(m, (int, float)) and v < m:
                    items.append(dict(rid=r["id"], title=title(r["id"]), days=0, money=None, value=v, min=m))
            if items:
                a = next(x for x in spec["attrs"] if x["id"] == th["attr"])
                mn = next(x for x in spec["attrs"] if x["id"] == th["min"])
                out.append(dict(id=f"th:{spec['id']}:{th['attr']}", type=spec["id"], kind="threshold", severity=2,
                                title=f"{spec['plural']} unter {mn['name']}", count=len(items), amount=None,
                                items=items, action=None, explain=th["text"]))
    return out


_EXIT_WORDS = {"austritt", "ausgeschieden", "ausscheiden", "kuendigung", "gekuendigt", "inaktiv", "ende", "bis",
               "exit", "terminated", "termination", "end"}


def _inactive(spec: dict, rec: dict, today: date) -> bool:
    """Someone who left the firm, a customer who cancelled: their silence is no news."""
    if (rec.get("meta") or {}).get("vanished"):
        return True
    for a in spec.get("attrs", []):
        v = rec["data"].get(a["id"])
        if v is None:
            continue
        if a["kind"] in ("date", "datetime") and set(tokens(a["name"])) & _EXIT_WORDS:
            d = as_date(v)
            if d and d <= today:
                return True
        if a.get("role") == "status" and fold(str(v)) in lexicon.NEGATIVE_STATES:
            return True
    return False


def _rhythm_work(model, records, by_id, title, today) -> list[dict]:
    out = []
    specs = {t["id"]: t for t in model["types"]}
    for rh in model.get("rhythms", []):
        per = defaultdict(list)
        for r in records.get(rh["src"], []):
            t = r["data"].get(rh["attr"])
            d = as_date(r["data"].get(rh["date"]))
            if isinstance(t, int) and d:
                per[t].append(d)
        items = []
        dspec = specs.get(rh["dst"]) or {}
        for target, ds in per.items():
            ds = sorted(set(ds))
            if len(ds) < 4 or target not in by_id or _inactive(dspec, by_id[target], today):
                continue
            gaps = [(b - a).days for a, b in zip(ds, ds[1:]) if (b - a).days > 0]
            if len(gaps) < 3:
                continue
            m = statistics.median(gaps)
            silent = (today - ds[-1]).days
            if silent > max(3 * m, m + 21) and silent < 365:
                items.append(dict(rid=target, title=title(target), days=silent, usual=round(m), money=None,
                                  last=ds[-1].isoformat(), count=len(ds), weight=len(ds) * silent / max(m, 1)))
        if items:
            items.sort(key=lambda x: -x["weight"])
            dst = specs[rh["dst"]]
            out.append(dict(id=f"rh:{rh['rel']}", type=rh["dst"], kind="rhythm", severity=1,
                            title=f"{dst['plural']}, die ungewöhnlich lange keine {rh['label']} mehr hatten",
                            count=len(items), amount=None, items=items[:30], action=None,
                            explain=f"Gelernt aus dem üblichen Abstand zwischen den {lexicon.dative_plural(rh['label'])} je {dst['name']}."))
    return out


def _reach_work(model, records, by_id, title, today) -> list[dict]:
    out = []
    since = today - timedelta(days=90)
    for rc in model.get("reach", []):
        use = defaultdict(float)
        for fl in rc["flows"]:
            parents = {r["id"]: as_date(r["data"].get(fl["date"])) for r in records.get(fl["parent"], [])}
            for ln in records.get(fl["line"], []):
                a = ln["data"].get(fl["ref"])
                p = ln["data"].get(fl["parent_ref"])
                q = ln["data"].get(fl["qty"])
                d = parents.get(p)
                if isinstance(a, int) and isinstance(q, (int, float)) and d and d >= since:
                    use[a] += float(q)
        items = []
        for r in records.get(rc["type"], []):
            stock = r["data"].get("stock_now", r["data"].get(rc["stock"]))
            per_day = use.get(r["id"], 0) / 90
            if not isinstance(stock, (int, float)) or per_day <= 0:
                continue
            days = stock / per_day
            r.setdefault("_reach", round(days, 1))
            if days < 21:
                items.append(dict(rid=r["id"], title=title(r["id"]), days=round(days), money=None, stock=stock,
                                  per_week=round(per_day * 7, 1)))
        if items:
            items.sort(key=lambda x: x["days"])
            spec = next(t for t in model["types"] if t["id"] == rc["type"])
            out.append(dict(id=f"reach:{rc['type']}", type=rc["type"], kind="reach", severity=2,
                            title=f"{spec['plural']}, die in weniger als 3 Wochen ausgehen", count=len(items),
                            amount=None, items=items, action=None,
                            explain="Reichweite = Bestand ÷ Verbrauch der letzten 90 Tage."))
    return out


def _not_yet_invoiced(data: dict, gross: str | None, payable: str | None, deduct: str | None) -> float:
    """The share of a final invoice that is new revenue: the down payments it deducts were revenue of
    their own invoices already (otherwise a job is counted twice)."""
    g = data.get(gross) if gross else None
    if not isinstance(g, (int, float)) or isinstance(g, bool) or abs(g) < 0.005:
        return 1.0
    owed = data.get(payable) if payable else None
    if not isinstance(owed, (int, float)) or isinstance(owed, bool):
        less = data.get(deduct) if deduct else None
        owed = g - abs(less) if isinstance(less, (int, float)) and not isinstance(less, bool) else g
    share = owed / g
    return share if 0 <= share < 1 else 1.0


def kpis(model: dict, records: dict, today: date | None = None) -> list[dict]:
    """Monthly sums of the money-carrying documents."""
    today = today or date.today()
    specs = {t["id"]: t for t in model["types"]}
    out = []
    for p in model.get("processes", []):
        spec = specs[p["type"]]
        aid = p.get("net") or p.get("gross")
        if not aid:
            agg = next((a for a in model.get("aggregates", []) if a["type"] == p["type"]), None)
            if not agg:
                continue
        recs = [r for r in records.get(p["type"], []) if not is_draft(r)]
        negative = set((p.get("status") or {}).get("negative") or [])
        sattr = (p.get("status") or {}).get("attr")
        other_neg = [(x["attr"], set(x["values"])) for x in (p.get("status") or {}).get("negative_other", [])]
        aspec = next((a for a in spec["attrs"] if a["id"] == aid), None) if aid else None
        if aspec and set(tokens(aspec["name"], camel=False)) & RECURRING:
            # a monthly fee is not revenue of the month the contract started: show what runs per month
            running = 0.0
            n_run = 0
            end = next((a["id"] for a in spec["attrs"] if a["kind"] in ("date", "datetime") and
                        set(tokens(a["name"])) & {"ende", "bis", "gekuendigt", "end", "kuendigung"}), None)
            for r in recs:
                if sattr and str(r["data"].get(sattr)) in negative:
                    continue
                if any(str(r["data"].get(a)) in vals for a, vals in other_neg):
                    continue
                e = as_date(r["data"].get(end)) if end else None
                v = r["data"].get(aid)
                if (e is None or e >= today) and isinstance(v, (int, float)):
                    running += float(v)
                    n_run += 1
            if n_run:
                out.append(dict(type=p["type"], name=spec["plural"], attr=aid, attr_name=aspec["name"], series=[],
                                current=round(running, 2), previous=None, previous_mtd=None, day=today.day,
                                currency=aspec.get("currency") or "EUR", concept=spec.get("concept"),
                                salience=spec.get("salience", 0), recurring=True, n=n_run,
                                date_attr=p["start"]["attr"], month_end=None))
            continue
        valid = []
        from .payments import _payable_attrs
        payable, deduct = _payable_attrs(spec, p) if p.get("gross") else (None, None)
        for r in recs:
            if sattr and str(r["data"].get(sattr)) in negative:
                continue
            if any(str(r["data"].get(a)) in vals for a, vals in other_neg):
                continue  # refunded shop orders are not revenue
            d = as_date(r["data"].get(p["start"]["attr"]))
            v = r["data"].get(aid) if aid else None
            if d and isinstance(v, (int, float)):
                valid.append((d, float(v) * _not_yet_invoiced(r["data"], p.get("gross"), payable, deduct)))
        if not valid:
            continue
        # a list that ends before this month (delivered on 15.09.) is not "−100 %" in October:
        # its months are compared as of its own last day
        latest = max(d for d, _ in valid)
        ref = latest if latest < date(today.year, today.month, 1) else today
        months = defaultdict(float)
        prev_mtd = 0.0
        py, pm = (ref.year, ref.month - 1) if ref.month > 1 else (ref.year - 1, 12)
        for d, v in valid:
            months[(d.year, d.month)] += v
            if (d.year, d.month) == (py, pm) and d.day <= ref.day:
                prev_mtd += v
        series = []
        y, m = ref.year, ref.month
        for _ in range(13):
            series.append(dict(month=f"{y}-{m:02d}", value=round(months.get((y, m), 0.0), 2)))
            m -= 1
            if m == 0:
                y, m = y - 1, 12
        series.reverse()
        cur = series[-1]["value"]
        # same day-of-month progress last month, for a fair comparison
        prev_full = series[-2]["value"]
        import calendar
        last = calendar.monthrange(ref.year, ref.month)[1]
        out.append(dict(type=p["type"], name=spec["plural"], attr=aid, attr_name=aspec["name"], series=series,
                        current=cur, previous=prev_full, previous_mtd=round(prev_mtd, 2), day=ref.day,
                        currency=aspec.get("currency") or "EUR", concept=spec.get("concept"),
                        salience=spec.get("salience", 0), date_attr=p["start"]["attr"],
                        month_end=f"{ref.year}-{ref.month:02d}-{last:02d}",
                        asof=ref.isoformat() if ref != today else None))
    return out
