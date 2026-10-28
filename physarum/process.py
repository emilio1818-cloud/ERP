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

import statistics
from collections import Counter, defaultdict
from datetime import date, timedelta

from . import lexicon
from .text import fold, tokens
from .values import as_date

PARTICIPLES = {"geliefert", "bezahlt", "versendet", "berechnet", "eingegangen", "erledigt", "abgeschlossen",
               "storniert", "angenommen", "unterschrieben", "gemahnt", "freigegeben", "montiert", "installiert",
               "gewartet", "beendet", "ausgetreten"}
CHILD_LABEL = {"rechnung": "berechnet", "kontobewegung": "bezahlt", "zahlung": "bezahlt", "lieferschein": "geliefert",
               "auftrag": "beauftragt", "einkauf": "bestellt"}


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
    cands = [a for a in spec["attrs"] if a["kind"] in ("date", "datetime") and a.get("role") != "due" and not a.get("hidden")]
    if not cands:
        return None
    return max(cands, key=lambda a: (a.get("fill", 0), -len(a["name"])))


def money_attrs(spec: dict) -> tuple[dict | None, dict | None]:
    """(net-ish, gross-ish) money attribute of a type (computed totals count)."""
    ms = [a for a in spec["attrs"] if a["kind"] == "money" and not a.get("hidden") and not a.get("constant")]
    if not ms:
        return None, None
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
    children = defaultdict(list)  # dst type -> [(rel, src spec, child date attr)]
    for rel in model["relations"]:
        src, dst = specs.get(rel["src"]), specs.get(rel["dst"])
        if not src or not dst or src["kind"] in ("line", "master", "document"):
            continue
        pd = _primary_date(src)
        if pd:
            children[dst["id"]].append((rel, src, pd))
    model["processes"] = []
    for spec in model["types"]:
        if spec["kind"] not in ("transaction",):
            continue
        recs = records.get(spec["id"], [])
        if len(recs) < 2:
            continue
        p = _infer_one(spec, recs, children.get(spec["id"], []), records, mention_map, by_id, today)
        if p:
            spec["process"] = p["id"]
            model["processes"].append(p)
    model["rhythms"] = _rhythm_specs(model, records)
    model["reach"] = _reach_specs(model, records)


def _instance_dates(spec, recs, cand_steps, records, mention_map):
    """dates[step_id][rid] = date"""
    out = {}
    rid_set = {r["id"] for r in recs}
    for st in cand_steps:
        d = {}
        if st["source"] == "own":
            for r in recs:
                v = as_date(r["data"].get(st["attr"]))
                if v:
                    d[r["id"]] = v
        else:
            ctype = st["type"]
            if st["rel_kind"] == "mention":
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


def _infer_one(spec, recs, kids, records, mention_map, by_id, today) -> dict | None:
    start_attr = _primary_date(spec)
    if not start_attr:
        return None
    cand = []
    for a in spec["attrs"]:
        if a["kind"] in ("date", "datetime") and a.get("role") != "due" and a["id"] != start_attr["id"] and not a.get("hidden"):
            cand.append(dict(id=f"s_{a['id']}", source="own", attr=a["id"], label=_label_of(a), name=a["name"]))
    for rel, src, pd in kids:
        lab = CHILD_LABEL.get(src.get("concept") or "", src["name"])
        cand.append(dict(id=f"c_{rel['id']}", source="child", type=src["id"], rel=rel["id"], rel_attr=rel["attr"],
                         rel_kind=rel["kind"], attr=pd["id"], label=lab, name=src["name"], child_plural=src["plural"]))
    starts = {r["id"]: as_date(r["data"].get(start_attr["id"])) for r in recs}
    starts = {k: v for k, v in starts.items() if v}
    has_due = any(a.get("role") == "due" for a in spec["attrs"])
    if len(starts) < (2 if has_due else 5):
        return None
    dates = _instance_dates(spec, recs, cand, records, mention_map)
    steps = []
    for st in cand:
        d = dates[st["id"]]
        deltas = [(d[k] - starts[k]).days for k in d if k in starts]
        if len(deltas) < max(3, 0.03 * len(starts)):
            continue
        after = sum(1 for x in deltas if x >= -1) / len(deltas)
        if after < 0.8:
            continue
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
            if fold(m["label"]) == fold(st["label"]) and kin:
                twin = m  # the same milestone reached through another link of the same kind of record
                break
            if len(both) < 3:
                continue
            near = sum(1 for k in both if abs((a[k] - b[k]).days) <= 3) / len(both)
            same = sum(1 for k in both if a[k] == b[k]) / len(both)
            if (fold(m["label"]) == fold(st["label"]) and near >= 0.8) or (same >= 0.9 and len(both) >= 10):
                twin = m
                break
        if twin:
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
    net, gross = money_attrs(spec)

    refs = [a for a in spec["attrs"] if a["kind"] == "ref" and a.get("ref") and a["id"] != spec.get("key")]
    party = next((a for a in refs if a.get("ref_kind") == "master"), None) or (refs[0] if refs else None)
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
        reached = [r for r in recs if stage_of[r["id"]] == i and str(r["data"].get(sa["id"])) not in negative]
        if len(reached) >= 5:
            ok = sum(1 for r in reached if str(r["data"].get(sa["id"])) == v)
            if ok / len(reached) >= 0.9:
                autos.append(dict(step=st["id"], attr=sa["id"], value=v, ok=ok, n=len(reached),
                                  text=f"Wenn „{st['name']}“ eingetragen wird: {sa['name']} = „{v}“"))
    # stale statuses: the status says "not yet" although a linked record says "done"
    stale = []
    for i, st in enumerate(steps, start=1):
        target = [v for v, s in mapping.items() if s == i]
        if len(target) != 1:
            continue
        for r in recs:
            v = r["data"].get(sa["id"])
            if v is None or str(v) in negative or mapping.get(str(v), i) >= i:
                continue
            if r["id"] in comb[st["id"]] and stage_of[r["id"]] < i:
                stale.append(dict(rid=r["id"], step=st["id"], value=target[0], was=str(v)))
    # how well the status values predict the stage (1.0 = perfectly)
    total = sum(sum(c.values()) for v, c in by_val.items() if v not in negative)
    purity = sum(max(c.values()) for v, c in by_val.items() if v not in negative) / total if total else 0
    quality = purity * 10 + len(set(mapping.values()))
    return dict(attr=sa["id"], name=sa["name"], map=mapping, negative=negative, initial=initial, autos=autos,
                stale=stale[:200], _quality=quality)


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
            flows.append(dict(line=line["id"], ref=rel["attr"], qty=qty["id"], parent_ref=parent_rel["attr"],
                              parent=parent_rel["dst"], date=pd["id"], label=line["plural"]))
        if flows:
            out.append(dict(type=spec["id"], stock=stock["id"], flows=flows))
    return out


# --- runtime: what needs to be done today ---------------------------------------------------------------

def compute_work(model: dict, records: dict, mention_refs: dict, today: date | None = None,
                 outrefs: dict | None = None, titles_in: dict | None = None,
                 pending_payments: dict | None = None, ledger: dict | None = None) -> list[dict]:
    from .grow import record_title

    today = today or date.today()
    specs = {t["id"]: t for t in model["types"]}
    titles = {}

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
    for p in model.get("processes", []):
        spec = specs[p["type"]]
        recs = records.get(p["type"], [])
        rid_set = {r["id"] for r in recs}
        step_dates = {}

        def start_of(rid, _p=p):
            return as_date(by_id[rid]["data"].get(_p["start"]["attr"])) or today

        for st in p["steps"]:
            d = {}
            for src in [st] + st.get("also", []):
                if src["source"] == "own":
                    for r in recs:
                        v = as_date(r["data"].get(src["attr"]))
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
                        if t in rid_set and not void(c):
                            v = as_date(c["data"].get(src["attr"]))
                            if v:
                                d[t] = min(v, d.get(t, v))
            if ledger is not None and fold(st["label"]) == "bezahlt" and any(rid in ledger for rid in rid_set):
                # paid is what the money says, not what a purpose names
                d = {rid: e["paid_date"] or start_of(rid) for rid, e in ledger.items()
                     if rid in rid_set and e["state"] in ("bezahlt", "überzahlt")}
            step_dates[st["id"]] = d
        negative = set((p.get("status") or {}).get("negative") or [])
        sattr = (p.get("status") or {}).get("attr")
        other_neg = [(x["attr"], set(x["values"])) for x in (p.get("status") or {}).get("negative_other", [])]
        due_by_step = {dl["step"]: dl for dl in p["deadlines"] if dl.get("step")}
        free_dues = [dl for dl in p["deadlines"] if not dl.get("step")]
        buckets = defaultdict(list)
        for r in recs:
            if sattr and str(r["data"].get(sattr)) in negative:
                continue
            if any(str(r["data"].get(a)) in vals for a, vals in other_neg):
                continue
            start = as_date(r["data"].get(p["start"]["attr"]))
            if not start:
                continue
            last = start
            for st in p["steps"]:
                dv = step_dates[st["id"]].get(r["id"])
                if dv:
                    last = max(last, dv)
                    continue
                # first missing step: is it overdue or waiting unusually long?
                w0 = date.fromisoformat(st["window"][0]) if st.get("window") else None
                expected_by = start + timedelta(days=(st.get("median_days") or 0))
                if w0 and expected_by < w0 - timedelta(days=7):
                    break  # outside the time span covered by the data: unknown stays unknown
                money = _money(r, p)
                paid_part = None
                if ledger is not None and r["id"] in ledger and fold(st["label"]) == "bezahlt":
                    e = ledger[r["id"]]
                    money = e["open"]  # only what is still missing
                    paid_part = e["paid"] if e["paid"] > 0.005 else None
                dl = due_by_step.get(st["id"])
                due = as_date(r["data"].get(dl["attr"])) if dl else None
                if due and due < today:
                    buckets[(st["id"], "overdue")].append(dict(rid=r["id"], days=(today - due).days, money=money,
                                                               due=due.isoformat(), paid=paid_part))
                elif st.get("p80_days") is not None and st.get("n", 0) >= 5:
                    waited = (today - last).days
                    limit = max(st["p80_days"] * 1.25, (st["median_days"] or 0) + 2, 2)
                    if waited > limit and waited < 400:
                        buckets[(st["id"], "late")].append(dict(rid=r["id"], days=waited, money=money,
                                                                usual=st["median_days"]))
                    elif due and (due - today).days <= 3:
                        buckets[(st["id"], "soon")].append(dict(rid=r["id"], days=(due - today).days, money=money,
                                                                due=due.isoformat()))
                break
            for dl in free_dues:
                due = as_date(r["data"].get(dl["attr"]))
                if due and (due - today).days <= 14:
                    buckets[(dl["attr"], "due")].append(dict(rid=r["id"], days=(due - today).days, money=_money(r, p),
                                                             due=due.isoformat(), name=dl["name"]))
        for (sid, kind), items in buckets.items():
            st = next((s for s in p["steps"] if s["id"] == sid), None)
            items.sort(key=lambda x: (-x["days"] if kind in ("overdue", "late") else x["days"]))
            total = round(sum(x["money"] or 0 for x in items), 2)
            party = p.get("party")
            for x in items:
                r = by_id[x["rid"]]
                x["title"] = title(x["rid"])
                pv = r["data"].get(party) if party else None
                x["party"] = title(pv) if isinstance(pv, int) and pv in by_id else None
                if pending_payments and x["rid"] in pending_payments:
                    x["maybe_paid"] = pending_payments[x["rid"]]  # a transfer without reference fits: do not dun
            if kind == "overdue":
                head = f"{spec['plural']} {st['phrase']} – überfällig"
                sev = 3
            elif kind == "late":
                head = f"{spec['plural']} {st['phrase']} – länger als üblich"
                sev = 2
            elif kind == "soon":
                head = f"{spec['plural']} {st['phrase']} – bald fällig"
                sev = 1
            else:
                dname = items[0].get("name", "Termin")
                head = f"{spec['plural']}: {dname} steht an"
                sev = 2 if any(x["days"] < 0 for x in items) else 1
            action = None
            if st and st["source"] == "own":
                action = dict(kind="set_date", attr=st["attr"], label=st["label"])
            elif st and st["source"] == "child":
                action = dict(kind="create_child", type=st["type"], attr=st["rel_attr"], label=st["name"])
            groups.append(dict(id=f"{p['id']}:{sid}:{kind}", type=p["type"], kind=kind, severity=sev, title=head,
                               count=len(items), amount=total, items=items[:50], action=action,
                               step=st["label"] if st else None,
                               explain=_explain(p, st, kind)))
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
        from .reconcile import risk_items
        risks = risk_items(model, records, outrefs, titles_in or {r: title(r) for r in by_id})
        if risks:
            groups.append(dict(id="risk:iban", type="doc", kind="risk", severity=3,
                               title="Vorsicht: Bankverbindung oder Absender passen nicht zum Lieferanten",
                               count=len(risks), amount=None, items=risks, action=None,
                               explain="Vor einer Zahlung telefonisch beim bekannten Ansprechpartner prüfen. "
                                       "So sieht Rechnungsbetrug typischerweise aus."))
    groups += _threshold_work(model, records, title)
    groups += _rhythm_work(model, records, by_id, title, today)
    groups += _reach_work(model, records, by_id, title, today)
    groups.sort(key=lambda g: (-g["severity"], -(g["amount"] or 0), -g["count"]))
    return groups


def _money(r, p):
    for aid in (p.get("gross"), p.get("net")):
        if aid:
            v = r["data"].get(aid)
            if isinstance(v, (int, float)) and not isinstance(v, bool):
                return float(v)
    return None


def _explain(p, st, kind) -> str:
    if not st:
        return "Termin aus den Daten"
    if kind == "overdue":
        return f"Die Frist ist abgelaufen und „{st['label']}“ fehlt noch."
    if kind == "late":
        return (f"Üblich sind {st['median_days']:.0f} Tage bis „{st['label']}“ (bei 80 % höchstens {st['p80_days']:.0f}), "
                f"gelernt aus {st['n']} Fällen.")
    if kind == "soon":
        return "Die Frist läuft in den nächsten Tagen ab."
    return ""


def _threshold_work(model, records, title) -> list[dict]:
    out = []
    for spec in model["types"]:
        for th in spec.get("thresholds") or []:
            items = []
            for r in records.get(spec["id"], []):
                v, m = r["data"].get(th["attr"]), r["data"].get(th["min"])
                if isinstance(v, (int, float)) and isinstance(m, (int, float)) and v < m:
                    items.append(dict(rid=r["id"], title=title(r["id"]), days=0, money=None, value=v, min=m))
            if items:
                a = next(x for x in spec["attrs"] if x["id"] == th["attr"])
                mn = next(x for x in spec["attrs"] if x["id"] == th["min"])
                out.append(dict(id=f"th:{spec['id']}:{th['attr']}", type=spec["id"], kind="threshold", severity=2,
                                title=f"{spec['plural']} unter {mn['name']}", count=len(items), amount=None,
                                items=items, action=None, explain=th["text"]))
    return out


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
        for target, ds in per.items():
            ds = sorted(set(ds))
            if len(ds) < 4 or target not in by_id:
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
                            explain=f"Gelernt aus dem üblichen Abstand zwischen den {rh['label']} je {dst['name']}."))
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
            stock = r["data"].get(rc["stock"])
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
        recs = records.get(p["type"], [])
        negative = set((p.get("status") or {}).get("negative") or [])
        sattr = (p.get("status") or {}).get("attr")
        months = defaultdict(float)
        prev_mtd = 0.0
        py, pm = (today.year, today.month - 1) if today.month > 1 else (today.year - 1, 12)
        for r in recs:
            if sattr and str(r["data"].get(sattr)) in negative:
                continue
            d = as_date(r["data"].get(p["start"]["attr"]))
            v = r["data"].get(aid) if aid else None
            if d and isinstance(v, (int, float)):
                months[(d.year, d.month)] += float(v)
                if (d.year, d.month) == (py, pm) and d.day <= today.day:
                    prev_mtd += float(v)
        if not months:
            continue
        series = []
        y, m = today.year, today.month
        for _ in range(13):
            series.append(dict(month=f"{y}-{m:02d}", value=round(months.get((y, m), 0.0), 2)))
            m -= 1
            if m == 0:
                y, m = y - 1, 12
        series.reverse()
        cur = series[-1]["value"]
        # same day-of-month progress last month, for a fair comparison
        prev_full = series[-2]["value"]
        aspec = next(a for a in spec["attrs"] if a["id"] == aid)
        out.append(dict(type=p["type"], name=spec["plural"], attr=aid, attr_name=aspec["name"], series=series,
                        current=cur, previous=prev_full, previous_mtd=round(prev_mtd, 2), day=today.day,
                        currency=aspec.get("currency") or "EUR", concept=spec.get("concept"),
                        salience=spec.get("salience", 0)))
    return out


def open_items(model: dict, records: dict, mention_refs: dict, today: date | None = None) -> list[dict]:
    """Per money-carrying process: how much is not yet through its final step."""
    out = []
    work = compute_work(model, records, mention_refs, today)
    for p in model.get("processes", []):
        if not p["steps"] or not (p.get("gross") or p.get("net")):
            continue
        final = p["steps"][-1]
        ws = [g for g in work if g["type"] == p["type"] and g.get("step") == final["label"]]
        out.append(dict(type=p["type"], step=final["label"], overdue=sum(g["amount"] or 0 for g in ws if g["kind"] == "overdue"),
                        n_overdue=sum(g["count"] for g in ws if g["kind"] == "overdue")))
    return out
