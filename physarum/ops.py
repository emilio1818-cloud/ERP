"""Writing: create, edit, steps, notes, storno — with the rules a system of record needs.

* Every change is a new entry in the change log (append-only). Nothing is overwritten
  without a trace.
* Issued documents (invoices) are locked: amounts, dates, parties and numbers cannot be
  changed afterwards; they can only be cancelled (storno) with a reason. Payments, status
  and notes stay possible.
* Records other records depend on cannot be deleted.
* Formulas, defaults and numbering learned from the data fill in what is predictable.
"""
from __future__ import annotations

import re
from datetime import date, datetime, timedelta

from .store import dumps, loads, now_iso
from .text import norm_key, norm_name
from .values import _EMAIL, add_months, as_date, as_number, iban_ok, interval_months, parse_date, parse_duration, parse_number, period_text

LOCKED_CONCEPTS = {"rechnung"}


class OpError(Exception):
    pass


# --- parsing user input -------------------------------------------------------------------------

def parse_input(rt, attr: dict, raw):
    if raw is None:
        return None
    if isinstance(raw, str):
        raw = raw.strip()
        if raw == "":
            return None
    k = attr["kind"]
    if k in ("number", "money"):
        x = parse_number(str(raw), "de")
        if x is None:
            x = parse_number(str(raw), "en")
        if x is None:
            raise OpError(f"„{raw}“ ist keine Zahl")
        return round(x, 2) if k == "money" else x
    if k == "percent":
        s = str(raw).replace("%", "").strip()
        x = parse_number(s, "de")
        if x is None:
            raise OpError(f"„{raw}“ ist kein Prozentwert")
        return x / 100 if x > 1 else x
    if k == "duration":
        x = parse_number(str(raw).split()[0], "de")
        if x is None:
            raise OpError(f"„{raw}“ ist keine Anzahl Tage")
        return int(x)
    if k == "date":
        d = parse_date(str(raw))
        if d is None:
            raise OpError(f"„{raw}“ ist kein Datum")
        return (d.date() if isinstance(d, datetime) else d).isoformat()
    if k == "datetime":
        s = str(raw).replace("T", " ")
        d = parse_date(s) or parse_date(str(raw)[:10])
        if d is None:
            raise OpError(f"„{raw}“ ist kein Zeitpunkt")
        return d.isoformat(timespec="minutes") if isinstance(d, datetime) else d.isoformat()
    if k == "bool":
        return str(raw).lower() in ("1", "on", "true", "ja", "yes", "x")
    if k == "email":
        if not _EMAIL.match(str(raw)):
            raise OpError(f"„{raw}“ ist keine E-Mail-Adresse")
        return str(raw)
    if k == "iban":
        s = re.sub(r"\s+", "", str(raw)).upper()
        if not iban_ok(s):
            raise OpError(f"„{raw}“ ist keine gültige IBAN (Prüfziffer)")
        return s
    if k == "zip":
        d = re.sub(r"\D", "", str(raw))
        return d.zfill(5) if 4 <= len(d) <= 5 else str(raw)
    if k == "ref":
        if isinstance(raw, int) or (isinstance(raw, str) and raw.isdigit() and int(raw) in rt.by_id):
            rid = int(raw)
            if rt.by_id[rid]["type"] not in (attr.get("refs") or [attr.get("ref")]):
                raise OpError("Verweis auf falschen Datensatz")
            return rid
        # typed name: resolve against the target types
        name = norm_name(raw)
        for tid in attr.get("refs") or [attr.get("ref")]:
            for r in rt.records.get(tid, []):
                if norm_name(rt.title(r["id"])) == name or norm_key(rt.title(r["id"])) == norm_key(raw):
                    return r["id"]
        raise OpError(f"„{raw}“ nicht gefunden – bitte aus der Liste wählen")
    return str(raw)


# --- formulas -------------------------------------------------------------------------------------

def eval_formula(rt, f: dict, data: dict):
    op = f["op"]
    try:
        if op in ("mul", "add", "sub"):
            a, b = (as_number(data.get(x)) for x in f["args"])
            if a is None or b is None:
                return None
            return round(a * b if op == "mul" else a + b if op == "add" else a - b, 2)
        if op == "scale":
            a = as_number(data.get(f["args"][0]))
            return None if a is None else round(a * f["k"], 2)
        if op in ("date_add", "date_default"):
            d = as_date(data.get(f["args"][0]))
            return None if d is None else (d.fromordinal(d.toordinal() + int(f["days"]))).isoformat()
        if op == "period_next":
            last = as_date(data.get(f["args"][0]))
            k = interval_months(data.get(f["args"][1])) if len(f["args"]) > 1 else f.get("months")
            return None if not last or not k else period_text(add_months(last, k), f.get("like"))
        if op == "date_add_ref":
            d = as_date(data.get(f["args"][0]))
            target = rt.by_id.get(data.get(f["ref"]))
            if d is None or not target:
                return None
            n = parse_duration(target["data"].get(f["ref_attr"]))
            if n is None:
                return None
            return d.fromordinal(d.toordinal() + int(n)).isoformat()
    except (TypeError, ValueError, KeyError, OverflowError):
        return None
    return None


def apply_formulas(rt, spec: dict, data: dict, given: set) -> list[str]:
    """Fill formula targets the user did not type. Returns the attribute ids that were computed."""
    done = []
    for _ in range(3):  # chains: MwSt from Netto, then Brutto from Netto + MwSt
        for f in spec.get("formulas") or []:
            if f["op"] == "sum_children" or f["attr"] in given:
                continue
            if f.get("on_change") and data.get(f["attr"]) is not None and not set(f["args"]) & given:
                continue  # "next maintenance" moves only when the maintenance is entered
            if f["op"].startswith("date_") and data.get(f["attr"]) is not None:
                continue  # an agreed date stays: a learned offset fills a gap, it does not move what was set
            v = eval_formula(rt, f, data)
            if v is not None and data.get(f["attr"]) != v:
                data[f["attr"]] = v
                if f["attr"] not in done:
                    done.append(f["attr"])
    return done


def next_number(rt, spec: dict, today: date | None = None) -> str | None:
    nb = spec.get("numbering")
    if not nb:
        return None
    today = today or date.today()
    from .behavior import find_numbering

    fresh = find_numbering(spec, rt.records.get(spec["id"], []), today)
    return (fresh or nb)["next"]


def prefill(rt, spec: dict, today: date | None = None) -> dict:
    """What a new record of this type probably looks like."""
    today = today or date.today()
    data = {}
    for aid, d in (spec.get("defaults") or {}).items():
        data[aid] = d["value"]
    proc = next((p for p in rt.model.get("processes", []) if p["type"] == spec["id"]), None)
    if proc:
        a = rt.attr(spec["id"], proc["start"]["attr"])
        data[proc["start"]["attr"]] = today.isoformat() if a["kind"] == "date" else datetime.now().isoformat(timespec="minutes")
        st = proc.get("status")
        if st and st.get("initial"):
            data[st["attr"]] = st["initial"]
    num = next_number(rt, spec, today)
    if num and spec.get("key"):
        data[spec["key"]] = num
    apply_formulas(rt, spec, data, set())
    return data


# --- locks ----------------------------------------------------------------------------------------

def lock_state(rt, spec: dict, rec: dict) -> dict | None:
    """Issued documents are locked (GoBD): only payments, notes and storno remain possible. A
    draft made here is not issued yet and stays free."""
    from .billing import is_draft

    if spec.get("concept") not in LOCKED_CONCEPTS:
        return None
    key = spec.get("key")
    meta = rec.get("meta") or {}
    if is_draft(rec):
        return None
    issued = meta.get("issued") or meta.get("storno_of") or rec.get("origin") == "import" or \
        (key and rec["data"].get(key) is not None)
    if not issued:
        return None  # a record without number that never was issued (typed in by hand, no draft mark)
    proc = next((p for p in rt.model.get("processes", []) if p["type"] == spec["id"]), None)
    editable, steps_only = set(), set()
    if proc:
        for st in proc["steps"]:
            for s in [st] + st.get("also", []):
                if s["source"] == "own":
                    editable.add(s["attr"])
        if proc.get("status"):
            steps_only.add(proc["status"]["attr"])  # follows "bezahlt", never typed over
    for a in spec["attrs"]:
        if a.get("role") in ("notes",):
            editable.add(a["id"])
    editable.discard(key)
    cancelled = bool(meta.get("storno_by") or meta.get("storno_of"))
    from .billing import is_own_invoice
    own = is_own_invoice(rt, spec)
    here = bool(meta.get("issued") or meta.get("storno_of"))  # written in Physarum, not copied from a file
    reason = ("Rechnung eines Lieferanten: so wie sie gekommen ist. Eine Korrektur schickt der Lieferant; "
              "Zahlung und Notizen lassen sich eintragen.") if not own else \
             ("Ausgestellte Rechnung: Nummer, Datum, Kunde und Beträge sind festgeschrieben – Korrektur nur per "
              "Storno. Zahlungseingang und Notizen lassen sich weiter eintragen.") if here else \
             ("Rechnung aus Ihren Dateien (anderes Programm): dort wird sie korrigiert oder storniert. Hier lassen "
              "sich Zahlung und Notizen eintragen.")
    return dict(editable=set() if cancelled else editable, steps_only=set() if cancelled else steps_only,
                cancelled=cancelled, own=own, here=here, reason=reason)


def _parent_lock(rt, spec: dict, rec: dict) -> dict | None:
    """Lines of an issued invoice are as fixed as the invoice."""
    if spec.get("kind") != "line":
        return None
    for a in spec["attrs"]:
        if a["kind"] == "ref":
            parent = rt.by_id.get(rec["data"].get(a["id"]))
            if parent:
                pspec = rt.spec(parent["type"])
                full = rt.store.record(parent["id"])
                if pspec and full and lock_state(rt, pspec, full):
                    return dict(editable=set(), reason="Position einer ausgestellten Rechnung: festgeschrieben.")
    return None


# --- writes -----------------------------------------------------------------------------------------

def _write_refs_and_search(rt, c, rid: int, spec: dict, data: dict):
    from .grow import record_text

    c.execute("DELETE FROM refs WHERE from_id=? AND kind='ref'", (rid,))
    for a in spec["attrs"]:
        if a["kind"] == "ref" and isinstance(data.get(a["id"]), int):
            c.execute("INSERT OR IGNORE INTO refs(from_id,attr,to_id,kind) VALUES(?,?,?,?)", (rid, a["id"], data[a["id"]], "ref"))
    c.execute("DELETE FROM search WHERE record_id=?", (rid,))
    c.execute("INSERT INTO search(body, record_id, type) VALUES(?,?,?)", (record_text(spec, data, rt.titles), rid, spec["id"]))


def _clean(spec: dict, data: dict) -> dict:
    keep = {a["id"] for a in spec["attrs"] if not a.get("virtual")}
    return {k: v for k, v in data.items() if k in keep and v is not None}


def create(rt, tid: str, raw: dict, actor: str, lines: list[dict] | None = None, line_type: str | None = None) -> int:
    rt.ensure()
    spec = rt.spec(tid)
    if not spec:
        raise OpError("Unbekannte Art")
    data, given, errors = {}, set(), []
    for a in spec["attrs"]:
        if a["id"] in raw and not a.get("virtual"):
            try:
                v = parse_input(rt, a, raw[a["id"]])
            except OpError as e:
                errors.append(f"{a['name']}: {e}")
                continue
            if v is not None:
                data[a["id"]] = v
                given.add(a["id"])
    if errors:
        raise OpError("; ".join(errors))
    from .billing import derive, is_invoice
    copies, _why = derive(rt, spec, data)
    for aid, v in copies.items():
        if aid not in given and v is not None:
            data[aid] = v
            given.add(aid)  # taken over from the order (VAT by the articles' rates) beats a learned formula
    proc = next((p for p in rt.model.get("processes", []) if p["type"] == tid), None)
    if proc and data.get(proc["start"]["attr"]) is None:
        # what is made here starts now (the form proposes the same)
        sa = next((a for a in spec["attrs"] if a["id"] == proc["start"]["attr"]), None)
        if sa and sa["kind"] in ("date", "datetime"):
            data[proc["start"]["attr"]] = date.today().isoformat() if sa["kind"] == "date" else \
                datetime.now().isoformat(timespec="minutes")
    draft = is_invoice(spec)
    key = spec.get("key")
    if draft:
        data.pop(key, None)  # the number comes when the invoice is issued
    elif key and data.get(key) is None:
        n = next_number(rt, spec)
        if n:
            data[key] = n
    if key and data.get(key) is not None:
        dup = [r for r in rt.records.get(tid, []) if norm_key(r["data"].get(key)) == norm_key(data[key])]
        if dup:
            raise OpError(f"{next(a['name'] for a in spec['attrs'] if a['id'] == key)} „{data[key]}“ gibt es schon")
    computed = apply_formulas(rt, spec, data, given)
    pos = None
    if draft:
        # the invoice is its lines: taken from the order, or one line from the amount typed in
        from .billing import _d, apply_totals, money_fields, positions as order_positions
        pos = order_positions(rt, dict(id=-1, type=tid, data=data, meta={}))
        if not pos:
            mf = money_fields(spec)
            net = _d(data.get(mf["net"]["id"])) if mf["net"] else None
            tax = _d(data.get(mf["tax"]["id"])) if mf["tax"] else None
            if net:
                rate = None
                if tax is not None and net:
                    r = tax / net
                    rate = next((float(x) for x in (0, 0.07, 0.19) if abs(r - _d(x)) < _d("0.005")), None)
                pos = [dict(text="", sku=None, qty=1.0, unit=None, price=float(net), rate=rate, total=float(net))]
        if pos and all(p.get("rate") is not None and p.get("total") is not None for p in pos):
            apply_totals(spec, data, pos)
    data = _clean(spec, data)
    ts = now_iso()
    with rt.store.tx() as c:
        meta = dict(w={aid: ["user", ts] for aid in data}, computed=computed)
        if draft:
            meta["draft"] = True
            meta["positions"] = pos or []
        cur = c.execute("INSERT INTO records(type,data,meta,origin,created_at,updated_at) VALUES(?,?,?,?,?,?)",
                        (tid, dumps(data), dumps(meta), "user", ts, ts))
        rid = cur.lastrowid
        idents = [f"u:{rid}"]
        if key and data.get(key) is not None:
            idents.append("k:" + norm_key(data[key]))
        for a in spec["attrs"]:
            if a["kind"] == "email" and data.get(a["id"]) and spec["kind"] == "master":
                idents.append("e:" + str(data[a["id"]]).casefold())
        if spec.get("title") and data.get(spec["title"]) and spec["kind"] == "master":
            idents.append("n:" + norm_name(data[spec["title"]]))
        c.executemany("INSERT OR IGNORE INTO idents(type,ident,record_id) VALUES(?,?,?)", [(tid, i, rid) for i in idents])
        c.execute("INSERT INTO changes(record_id,ts,actor,kind,note) VALUES(?,?,?,?,?)",
                  (rid, ts, actor, "create", "angelegt" + (f"; berechnet: {len(computed)} Feld(er)" if computed else "")))
        _write_refs_and_search(rt, c, rid, spec, data)
        if lines and line_type:
            lspec = rt.spec(line_type)
            parent_ref = next((a["id"] for a in lspec["attrs"] if a["kind"] == "ref" and a.get("ref") == tid), None)
            for ln in lines:
                ldata, lgiven = {}, set()
                for a in lspec["attrs"]:
                    if a["id"] in ln and a["id"] != parent_ref and not a.get("virtual"):
                        v = parse_input(rt, a, ln[a["id"]])
                        if v is not None:
                            ldata[a["id"]] = v
                            lgiven.add(a["id"])
                if not ldata:
                    continue
                ldata[parent_ref] = rid
                for aid, v in derive(rt, lspec, ldata)[0].items():
                    if aid not in lgiven and v is not None:
                        ldata[aid] = v  # the unit price comes from the article, as it always did
                apply_formulas(rt, lspec, ldata, lgiven)
                ldata = _clean(lspec, ldata)
                cur = c.execute("INSERT INTO records(type,data,meta,origin,created_at,updated_at) VALUES(?,?,?,?,?,?)",
                                (line_type, dumps(ldata), dumps(dict(w={k: ["user", ts] for k in ldata})), "user", ts, ts))
                lid = cur.lastrowid
                c.execute("INSERT INTO idents(type,ident,record_id) VALUES(?,?,?)", (line_type, f"u:{lid}", lid))
                c.execute("INSERT INTO changes(record_id,ts,actor,kind,note) VALUES(?,?,?,?,?)",
                          (lid, ts, actor, "create", f"Position zu {rt.title(rid) if rid in rt.titles else '#' + str(rid)}"))
                _write_refs_and_search(rt, c, lid, lspec, ldata)
        rt.bump(c)
        for aid in given:
            rt.store.flux_add(f"attr:{aid}", 1.0, c=c)
        rt.store.flux_add(f"type:{tid}", 2.0, c=c)
    return rid


def update(rt, rid: int, raw: dict, actor: str, note: str | None = None, kind: str = "edit",
           allow: set | None = None) -> list[str]:
    """Apply edits. Returns names of changed attributes. `allow`: attributes an action (paid,
    reminded) may set on a locked document."""
    rt.ensure()
    rec = rt.store.record(rid)
    if not rec or rec["deleted"]:
        raise OpError("Datensatz nicht gefunden")
    spec = rt.spec(rec["type"])
    lock = lock_state(rt, spec, rec) or _parent_lock(rt, spec, rec)
    if lock and allow:
        # an action may set what follows a step (the status after "bezahlt") – never anything fixed
        lock = dict(lock, editable=set(lock["editable"]) | (set(allow) & set(lock.get("steps_only") or ())))
    data = dict(rec["data"])
    given, errors, changed = set(), [], []
    from .billing import is_draft as _is_draft, is_invoice as _is_invoice
    lines_rule = _is_invoice(spec) and _is_draft(rec) and (rec["meta"] or {}).get("positions") is not None
    for a in spec["attrs"]:
        if a["id"] not in raw or a.get("virtual"):
            continue
        try:
            v = parse_input(rt, a, raw[a["id"]])
        except OpError as e:
            errors.append(f"{a['name']}: {e}")
            continue
        if data.get(a["id"]) == v:
            continue
        if lock and a["id"] not in lock["editable"]:
            errors.append(f"{a['name']}: festgeschrieben (Storno statt Änderung)")
            continue
        if lines_rule and a["kind"] == "money":
            errors.append(f"{a['name']}: ergibt sich aus den Positionen – bitte dort ändern (Rabatt als eigene Position)")
            continue
        given.add(a["id"])
        if v is None:
            data.pop(a["id"], None)
        else:
            data[a["id"]] = v
    if errors:
        raise OpError("; ".join(errors))
    if not given:
        return []
    computed = apply_formulas(rt, spec, data, given) if not lock else []
    autos = _automations(rt, spec, rec["data"], data, given) + _step_taken_back(rt, spec, rec["data"], data, given)
    data = _clean(spec, data)
    ts = now_iso()
    meta = rec["meta"] or {}
    w = meta.get("w", {})
    with rt.store.tx() as c:
        for aid in sorted(set(given) | set(computed) | set(x for x, _ in autos)):
            old, new = rec["data"].get(aid), data.get(aid)
            if old == new:
                continue
            k = kind if aid in given else "auto"
            why = note if aid in given else next((t for x, t in autos if x == aid), "berechnet")
            c.execute("INSERT INTO changes(record_id,ts,actor,kind,attr,old,new,note) VALUES(?,?,?,?,?,?,?,?)",
                      (rid, ts, actor if aid in given else "Physarum", k, aid, dumps(old), dumps(new), why))
            prev = w.get(aid)
            # remember what the files said before the person changed it: a later file that
            # says the same again must not undo the change
            base = old if (prev is None or prev[0] == "import") else (prev[2] if len(prev) > 2 else None)
            w[aid] = ["user" if aid in given else "auto", ts, base]
            changed.append(aid)
            rt.store.flux_add(f"attr:{aid}", 1.0, c=c)
        meta["w"] = w
        c.execute("UPDATE records SET data=?, meta=?, updated_at=? WHERE id=?", (dumps(data), dumps(meta), ts, rid))
        _write_refs_and_search(rt, c, rid, spec, data)
        rt.bump(c)
    return changed


def _automations(rt, spec, before: dict, data: dict, given: set) -> list[tuple[str, str]]:
    """Learned rules the user switched on ("Trampelpfade"): when a step date is set, set the status."""
    out = []
    proc = next((p for p in rt.model.get("processes", []) if p["type"] == spec["id"]), None)
    if not proc or not proc.get("status"):
        return out
    on = rt.store.decisions("auto")
    for au in proc["status"].get("autos", []):
        key = f"{spec['id']}|{au['step']}|{au['attr']}"
        if on.get(key) != "on" or au["attr"] in given:
            continue
        st = next((s for s in proc["steps"] if s["id"] == au["step"]), None)
        if not st:
            continue
        attrs = [s["attr"] for s in [st] + st.get("also", []) if s["source"] == "own"]
        if any(a in given and data.get(a) and not before.get(a) for a in attrs):
            data[au["attr"]] = au["value"]
            out.append((au["attr"], f"Regel: {au['text']} (gelernt aus {au['n']} Fällen)"))
    return out


def step_attrs(rt, spec: dict) -> set:
    """Dates a quick action may set: the record's own milestones (paid, delivered, maintained)."""
    out = set()
    proc = next((p for p in rt.model.get("processes", []) if p["type"] == spec["id"]), None)
    for st in (proc or {}).get("steps", []):
        for s in [st] + st.get("also", []):
            if s["source"] == "own":
                out.add(s["attr"])
    for du in rt.model.get("dues", []):
        if du["type"] == spec["id"] and du.get("done"):
            out.add(du["done"])
    for a in spec["attrs"]:
        if a.get("milestone") and a["kind"] in ("date", "datetime"):
            out.add(a["id"])
    return out


def _step_taken_back(rt, spec, before: dict, data: dict, given: set) -> list[tuple[str, str]]:
    """"Bezahlt am" emptied: the status that came with it goes back too – never "bezahlt" next to "offen"."""
    proc = next((p for p in rt.model.get("processes", []) if p["type"] == spec["id"]), None)
    st = (proc or {}).get("status")
    if not st or st["attr"] in given:
        return []
    out = []
    for stage, step in enumerate(proc["steps"], start=1):
        own = [x["attr"] for x in [step] + step.get("also", []) if x["source"] == "own"]
        if not any(a in given and before.get(a) and not data.get(a) for a in own):
            continue
        cur = str(data.get(st["attr"]))
        if (st.get("map") or {}).get(cur) != stage:
            continue
        lower = [(k, v) for v, k in (st.get("map") or {}).items() if k < stage and v not in (st.get("negative") or [])]
        back = st.get("initial") or (max(lower)[1] if lower else None)
        if back:
            data[st["attr"]] = back
            out.append((st["attr"], f"„{step['label']}“ zurückgenommen"))
    return out


def revert_change(rt, rid: int, cid: int, actor: str) -> list[str]:
    """Undo one change from the history – and what came with it in the same action (a step and its status)."""
    rt.ensure()
    row = rt.store.q1("SELECT * FROM changes WHERE id=? AND record_id=?", (cid, rid))
    if not row or row["kind"] not in ("edit", "auto") or not row["attr"]:
        raise OpError("Diese Änderung lässt sich nicht zurücknehmen")
    rec = rt.store.record(rid)
    if not rec or rec["deleted"]:
        raise OpError("Datensatz nicht gefunden")
    spec = rt.spec(rec["type"])
    same = rt.store.q("SELECT * FROM changes WHERE record_id=? AND ts=? AND kind IN ('edit','auto') AND attr IS NOT NULL",
                      (rid, row["ts"]))
    raw = {}
    for ch in same:
        a = next((x for x in spec["attrs"] if x["id"] == ch["attr"]), None)
        if not a:
            continue
        new = loads(ch["new"]) if ch["new"] else None
        if rec["data"].get(ch["attr"]) != new:
            raise OpError(f"{a['name']} wurde seitdem wieder geändert – bitte direkt bearbeiten")
        old = loads(ch["old"]) if ch["old"] else None
        raw[ch["attr"]] = "" if old is None else _to_input(a, old)
    if not raw:
        raise OpError("Nichts zurückzunehmen")
    return update(rt, rid, raw, actor, note="rückgängig gemacht", allow=set(raw))


def set_step(rt, rid: int, attr: str, when: str | None, actor: str) -> list[str]:
    rt.ensure()
    rec = rt.by_id.get(rid)
    if not rec:
        raise OpError("Datensatz nicht gefunden")
    if attr not in step_attrs(rt, rt.spec(rec["type"])):
        raise OpError("Das ist kein Schritt im Ablauf")
    raw = {attr: when or date.today().isoformat()}
    allow = {attr}
    if rec:
        proc = next((p for p in rt.model.get("processes", []) if p["type"] == rec["type"]), None)
        st = (proc or {}).get("status")
        if proc and st:
            stage = next((i for i, s in enumerate(proc["steps"], start=1)
                          if any(x["source"] == "own" and x["attr"] == attr for x in [s] + s.get("also", []))), None)
            vals = [v for v, k in (st.get("map") or {}).items() if k == stage]
            cur = str(rec["data"].get(st["attr"]))
            if stage and len(vals) == 1 and cur not in (st.get("negative") or []) and (st["map"].get(cur, 0) or 0) < stage:
                raw[st["attr"]] = vals[0]  # "paid" also means status "bezahlt"
                allow.add(st["attr"])
    return update(rt, rid, raw, actor, note="Schritt erledigt", allow=allow)


def follow_up(rt, rid: int, outcome: str, actor: str, today: date | None = None) -> list[str]:
    """After the call: show the case again in a while ("later"), or the customer said no ("lost")."""
    rt.ensure()
    rec = rt.by_id.get(rid)
    if not rec:
        raise OpError("Datensatz nicht gefunden")
    du = next((d for d in rt.model.get("dues", []) if d["type"] == rec["type"] and d.get("follow_up")), None)
    if not du:
        raise OpError("Hier gibt es keinen Termin zum Nachfassen")
    if outcome == "later":
        when = (today or date.today()) + timedelta(days=du.get("offset") or 14)
        return update(rt, rid, {du["attr"]: when.isoformat()}, actor, note="nachgefasst, wieder vorlegen")
    if outcome == "lost" and du.get("status") and du.get("negative"):
        return update(rt, rid, {du["status"]: du["negative"]}, actor, note="nachgefasst: abgesagt")
    raise OpError("Unbekannte Antwort")


def record_payment(rt, rid: int, amount, when: str | None, how: str, actor: str) -> float:
    """A payment the bank statement does not show (cash, a cheque, an offset) or a part of one. Returns
    what is still open."""
    from .payments import CASH_KINDS
    rt.ensure()
    rec = rt.store.record(rid)
    if not rec or rec["deleted"] or rid not in rt.ledger:
        raise OpError("Hier lässt sich keine Zahlung eintragen")
    value = parse_number(amount) if isinstance(amount, str) else amount
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        raise OpError("Bitte einen Betrag angeben")
    value = round(float(value), 2)
    if value <= 0:
        raise OpError("Der Betrag muss größer als null sein")
    d = as_date(when) if when else date.today()
    if not d:
        raise OpError("Bitte ein Datum angeben")
    if how not in CASH_KINDS:
        raise OpError("Unbekannte Zahlungsart")
    meta = dict(rec["meta"] or {})
    cash = list(meta.get("cash") or [])
    entry = dict(id=max([m.get("id", 0) for m in cash] + [0]) + 1, amount=value, date=d.isoformat(), how=how,
                 by=actor, ts=now_iso())
    cash.append(entry)
    meta["cash"] = cash
    with rt.store.tx() as c:
        c.execute("UPDATE records SET meta=?, updated_at=? WHERE id=?", (dumps(meta), entry["ts"], rid))
        c.execute("INSERT INTO changes(record_id,ts,actor,kind,attr,old,new,note) VALUES(?,?,?,?,?,?,?,?)",
                  (rid, entry["ts"], actor, "edit", None, None, dumps(entry),
                   f"{CASH_KINDS[how]} über {value:.2f} € vom {d.strftime('%d.%m.%Y')} eingetragen".replace(".", ",", 1)))
        rt.bump(c)
    rt.ensure()
    return rt.ledger.get(rid, {}).get("open", 0.0)


def remove_payment(rt, rid: int, pid: int, actor: str):
    """Take back a payment entered by hand."""
    rt.ensure()
    rec = rt.store.record(rid)
    meta = dict((rec or {}).get("meta") or {})
    cash = [m for m in meta.get("cash") or []]
    gone = next((m for m in cash if m.get("id") == pid), None)
    if not gone:
        raise OpError("Diese Zahlung gibt es nicht (mehr)")
    meta["cash"] = [m for m in cash if m is not gone]
    ts = now_iso()
    with rt.store.tx() as c:
        c.execute("UPDATE records SET meta=?, updated_at=? WHERE id=?", (dumps(meta), ts, rid))
        c.execute("INSERT INTO changes(record_id,ts,actor,kind,attr,old,new,note) VALUES(?,?,?,?,?,?,?,?)",
                  (rid, ts, actor, "edit", None, dumps(gone), None, "von Hand eingetragene Zahlung zurückgenommen"))
        rt.bump(c)


def assign_payment(rt, bank_rid: int, inv_rid: int, actor: str) -> bool:
    """The owner knows what a bank line pays: it pays this invoice from now on, also after the next growth.
    Returns whether a growth is needed (the first such link between the two lists)."""
    from .grow import match_attr
    from .payments import CONFIRMED
    from .questions import _stable_ident
    rt.ensure()
    row, inv = rt.by_id.get(bank_rid), rt.by_id.get(inv_rid)
    if not row or not inv or inv_rid not in rt.ledger:
        raise OpError("Zahlung oder Rechnung gibt es nicht")
    attr = match_attr(rt.model, row["type"], inv["type"])
    with rt.store.tx() as c:
        bid, iid = _stable_ident(c, row["type"], bank_rid), _stable_ident(c, inv["type"], inv_rid)
        if not bid or not iid:
            raise OpError("Diese Zeile lässt sich nicht dauerhaft zuordnen")
        rt.store.decide("payment_match", f"{row['type']}|{bid}|{inv['type']}|{iid}", "yes", actor, c=c,
                        note="an der Kontobewegung zugeordnet")
        c.execute("INSERT OR IGNORE INTO refs(from_id,attr,to_id,kind,how) VALUES(?,?,?,?,?)",
                  (bank_rid, attr, inv_rid, "mention", CONFIRMED))
        c.execute("INSERT INTO changes(record_id,ts,actor,kind,note) VALUES(?,?,?,?,?)",
                  (inv_rid, now_iso(), actor, "edit", f"Zahlung vom Konto zugeordnet: {rt.title(bank_rid)}"))
        rt.bump(c)
    return attr == "match"


def paid_by_hand(rt, rid: int, when: str | None, actor: str):
    """Mark an invoice as paid without a bank line (or take that back with when=None)."""
    rt.ensure()
    rec = rt.store.record(rid)
    if not rec or rec["deleted"]:
        raise OpError("Datensatz nicht gefunden")
    meta = dict(rec["meta"] or {})
    old = meta.get("paid_by_hand")
    if when:
        d = as_date(when)
        if not d:
            raise OpError("Bitte ein Datum angeben")
        meta["paid_by_hand"] = d.isoformat()
    else:
        meta.pop("paid_by_hand", None)
    ts = now_iso()
    with rt.store.tx() as c:
        c.execute("UPDATE records SET meta=?, updated_at=? WHERE id=?", (dumps(meta), ts, rid))
        c.execute("INSERT INTO changes(record_id,ts,actor,kind,attr,old,new,note) VALUES(?,?,?,?,?,?,?,?)",
                  (rid, ts, actor, "edit", None, dumps(old), dumps(meta.get("paid_by_hand")),
                   "als bezahlt eingetragen (ohne Kontoauszug)" if when else "„bezahlt“ zurückgenommen"))
        rt.bump(c)


def revert(rt, rid: int, attrs: list[str], actor: str) -> list[str]:
    """Undo the last change of these attributes (the "Rückgängig" after a quick action)."""
    rt.ensure()
    raw = {}
    for aid in attrs:
        row = rt.store.q1("SELECT old FROM changes WHERE record_id=? AND attr=? ORDER BY id DESC LIMIT 1", (rid, aid))
        if row is not None:
            old = loads(row["old"]) if row["old"] else None
            rec = rt.store.record(rid)
            if not rec or not rt.spec(rec["type"]):
                raise OpError("Datensatz nicht gefunden")
            a = next((x for x in rt.spec(rec["type"])["attrs"] if x["id"] == aid), None)
            raw[aid] = "" if old is None else (_to_input(a, old) if a else old)
    if not raw:
        return []
    changed = update(rt, rid, raw, actor, note="rückgängig gemacht", allow=set(raw))
    rec = rt.store.record(rid)
    meta = rec["meta"] or {}
    w = meta.get("w", {})
    back = [aid for aid in changed if len(w.get(aid) or []) > 2 and rec["data"].get(aid) == w[aid][2]]
    if back:  # what the files said again: theirs again – the next delivery may change it
        for aid in back:
            w[aid] = ["import", w[aid][1]]
            meta.get("shadow", {}).pop(aid, None)
        with rt.store.tx() as c:
            c.execute("UPDATE records SET meta=? WHERE id=?", (dumps(meta), rid))
            rt.bump(c)
    return changed


def _to_input(attr: dict, v):
    if attr["kind"] in ("money", "number") and isinstance(v, (int, float)):
        return str(v).replace(".", ",")
    if attr["kind"] == "percent" and isinstance(v, (int, float)):
        return f"{v * 100:g}".replace(".", ",")
    return v


def add_note(rt, rid: int, text: str, actor: str):
    text = (text or "").strip()
    if not text:
        return
    ts = now_iso()
    with rt.store.tx() as c:
        c.execute("INSERT INTO notes(record_id,ts,actor,text) VALUES(?,?,?,?)", (rid, ts, actor, text))
        c.execute("INSERT INTO changes(record_id,ts,actor,kind,note) VALUES(?,?,?,?,?)", (rid, ts, actor, "note", text[:200]))
        rt.bump(c)


def storno(rt, rid: int, reason: str, actor: str, render=None) -> int | None:
    """Cancel. An issued invoice is cancelled by a cancellation invoice of its own (returns its
    id); a draft is simply discarded; anything else gets its negative status."""
    from .billing import BillingError, cancel, is_draft, is_invoice

    rt.ensure()
    rec = rt.store.record(rid)
    if not rec or rec["deleted"]:
        raise OpError("Datensatz nicht gefunden")
    spec = rt.spec(rec["type"])
    if not reason or not reason.strip():
        raise OpError("Bitte einen Grund für das Storno angeben")
    if is_invoice(spec) and is_draft(rec):
        delete(rt, rid, actor, reason=f"Entwurf verworfen: {reason}")
        return None
    if is_invoice(spec) and lock_state(rt, spec, rec):
        try:
            return cancel(rt, rid, reason, actor, render=render)
        except BillingError as e:
            raise OpError(str(e)) from e
    proc = next((p for p in rt.model.get("processes", []) if p["type"] == spec["id"]), None)
    st = (proc or {}).get("status")
    value = next(iter(st["negative"]), None) if st and st.get("negative") else None
    ts = now_iso()
    with rt.store.tx() as c:
        data = dict(rec["data"])
        if value and st:
            old = data.get(st["attr"])
            data[st["attr"]] = value
            c.execute("INSERT INTO changes(record_id,ts,actor,kind,attr,old,new,note) VALUES(?,?,?,?,?,?,?,?)",
                      (rid, ts, actor, "storno", st["attr"], dumps(old), dumps(value), reason))
        meta = rec["meta"] or {}
        meta["storno"] = dict(ts=ts, actor=actor, reason=reason)
        c.execute("UPDATE records SET meta=? WHERE id=?", (dumps(meta), rid))
        if not (value and st):
            c.execute("INSERT INTO changes(record_id,ts,actor,kind,note) VALUES(?,?,?,?,?)",
                      (rid, ts, actor, "storno", reason))
        c.execute("UPDATE records SET data=?, updated_at=? WHERE id=?", (dumps(data), ts, rid))
        c.execute("INSERT INTO notes(record_id,ts,actor,text) VALUES(?,?,?,?)", (rid, ts, actor, f"Storniert: {reason}"))
        rt.bump(c)
    return None


def delete(rt, rid: int, actor: str, reason: str | None = None):
    """Delete what was made here; hide (with a reason) what came from a file – it does not come
    back with the next growth, and it can be shown again."""
    rt.ensure()
    rec = rt.store.record(rid)
    if not rec or rec["deleted"]:
        raise OpError("Datensatz nicht gefunden")
    spec = rt.spec(rec["type"])
    if lock_state(rt, spec, rec):
        raise OpError("Ausgestellte Rechnungen können nicht gelöscht werden – bitte stornieren.")
    users = [b for b in rt.backrefs.get(rid, []) if b[2] == "ref" and b[0] in rt.by_id]
    if users:
        raise OpError(f"Wird von {len(users)} anderen Datensätzen verwendet und kann deshalb nicht gelöscht werden.")
    imported = rec.get("origin") == "import" or bool(rt.store.q1(
        "SELECT 1 AS x FROM changes WHERE record_id=? AND kind='import' LIMIT 1", (rid,)))
    if imported and not (reason or "").strip():
        raise OpError("Dieser Datensatz stammt aus einer Datei. Er wird nicht gelöscht, sondern ausgeblendet – "
                      "bitte einen Grund angeben.")
    ts = now_iso()
    with rt.store.tx() as c:
        c.execute("UPDATE records SET deleted=1, updated_at=? WHERE id=?", (ts, rid))
        if imported:
            idents = [r["ident"] for r in c.execute("SELECT ident FROM idents WHERE record_id=?", (rid,)).fetchall()]
            for i in idents:
                rt.store.decide("hidden_record", f"{rec['type']}|{i}", reason.strip(), actor, c=c)
            c.execute("INSERT INTO changes(record_id,ts,actor,kind,note) VALUES(?,?,?,?,?)",
                      (rid, ts, actor, "hide", f"ausgeblendet: {reason.strip()}"))
        else:
            c.execute("INSERT INTO changes(record_id,ts,actor,kind,note) VALUES(?,?,?,?,?)",
                      (rid, ts, actor, "delete", reason or "gelöscht"))
        c.execute("DELETE FROM search WHERE record_id=?", (rid,))
        c.execute("DELETE FROM refs WHERE from_id=?", (rid,))
        rt.bump(c)


def unhide(rt, rid: int, actor: str):
    rec = rt.store.record(rid)
    if not rec:
        raise OpError("Datensatz nicht gefunden")
    ts = now_iso()
    with rt.store.tx() as c:
        idents = [r["ident"] for r in c.execute("SELECT ident FROM idents WHERE record_id=?", (rid,)).fetchall()]
        c.executemany("DELETE FROM decisions WHERE kind='hidden_record' AND subject=?",
                      [(f"{rec['type']}|{i}",) for i in idents])
        c.execute("UPDATE records SET deleted=0, updated_at=? WHERE id=?", (ts, rid))
        c.execute("INSERT INTO changes(record_id,ts,actor,kind,note) VALUES(?,?,?,?,?)",
                  (rid, ts, actor, "unhide", "wieder eingeblendet"))
        rt.bump(c)
