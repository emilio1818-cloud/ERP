"""Web interface (Starlette + Jinja2, server-rendered)."""
from __future__ import annotations

import csv
import io
import json
import os
import shutil
import tempfile
import threading
import traceback
import zipfile
from collections import Counter, defaultdict
from datetime import date, datetime
from pathlib import Path

from markupsafe import Markup
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import (FileResponse, HTMLResponse, JSONResponse, PlainTextResponse, RedirectResponse,
                                 Response, StreamingResponse)
from starlette.routing import Mount, Route
from starlette.staticfiles import StaticFiles
from starlette.templating import Jinja2Templates

from .. import ops
from ..grow import Progress, ingest, record_title, regrow
from ..process import kpis
from ..questions import answer as answer_question
from ..questions import open_questions
from ..runtime import Runtime
from ..store import Store, dumps, loads, now_iso
from ..text import fold, norm_key, norm_name
from ..values import as_date, display
from . import views

HERE = Path(__file__).parent


class Jobs:
    """Growth runs in the background; the page polls its progress."""

    def __init__(self, store: Store, rt: Runtime):
        self.store, self.rt = store, rt
        self.lock = threading.Lock()

    def start(self, kind: str, fn, next_url: str = "/") -> int:
        with self.store.tx() as c:
            cur = c.execute("INSERT INTO jobs(kind,status,progress,log,started_at,result) VALUES(?,?,?,?,?,?)",
                            (kind, "running", 0.0, "[]", now_iso(), dumps(dict(next=next_url))))
            jid = cur.lastrowid
        threading.Thread(target=self._run, args=(jid, fn), daemon=True).start()
        return jid

    def _run(self, jid: int, fn):
        lines: list[str] = []

        def progress(msg, frac=None):
            lines.append(msg)
            sets, args = ["log=?"], [dumps(lines[-200:])]
            if frac is not None:
                sets.append("progress=?")
                args.append(frac)
            try:
                with self.store.tx() as c:
                    c.execute(f"UPDATE jobs SET {', '.join(sets)} WHERE id=?", (*args, jid))
            except Exception:
                pass

        with self.lock:
            try:
                fn(Progress(progress))
                with self.store.tx() as c:
                    c.execute("UPDATE jobs SET status='done', progress=1, finished_at=? WHERE id=?", (now_iso(), jid))
                    self.rt.bump(c)
                self.rt.refresh_network(force=True)
            except Exception as e:  # pragma: no cover - shown to the user
                traceback.print_exc()
                lines.append(f"Fehler: {type(e).__name__}: {e}")
                with self.store.tx() as c:
                    c.execute("UPDATE jobs SET status='error', log=?, finished_at=?, result=? WHERE id=?",
                              (dumps(lines), now_iso(), dumps(dict(error=str(e))), jid))


def create_app(folder: str | Path) -> Starlette:
    store = Store(folder)
    rt = Runtime(store)
    jobs = Jobs(store, rt)
    templates = Jinja2Templates(directory=str(HERE / "templates"))
    env = templates.env
    env.globals.update(fmt=lambda attr, v, **kw: views.fmt(rt, attr, v, **kw), money=views.money, spark=views.spark,
                       ago=views.ago, days_text=views.days_text, input_value=views.input_value,
                       title=lambda rid: rt.title(rid), status_class=views.status_class, display=display,
                       stale_days=lambda iso: (date.today() - date.fromisoformat(str(iso)[:10])).days if iso else 0)
    env.filters["de"] = lambda x, d=0: views.display(x, "number") if d == 0 else f"{x:,.{d}f}".replace(",", "X").replace(".", ",").replace("X", ".")
    env.filters["json"] = lambda x: json.dumps(x, ensure_ascii=False, default=str)

    def actor(request: Request) -> str:
        return request.cookies.get("physarum_name") or "Benutzer"

    def page(request: Request, name: str, ctx: dict, status: int = 200):
        rt.ensure()
        active, dormant = rt.nav() if rt.model else ([], [])
        nq = store.q1("SELECT COUNT(*) AS n FROM questions WHERE status='open'")["n"] if rt.model else 0
        base = dict(request=request, nav_active=active, nav_dormant=dormant, n_questions=nq, me=actor(request),
                    model=rt.model, today=views.today_text(), path=request.url.path)
        base.update(ctx)
        return templates.TemplateResponse(request, name, base, status_code=status)

    def wants_json(request: Request) -> bool:
        return request.headers.get("x-requested-with") == "fetch"

    # --- home -----------------------------------------------------------------------------------
    async def home(request: Request):
        rt.ensure()
        if not rt.model:
            return page(request, "empty.html", {})
        rt.refresh_network()
        work = rt.work()
        ks = kpis(rt.model, rt.records)
        pref = {"rechnung": 0, "auftrag": 1, "bestellung": 2, "einkauf": 4}
        ks.sort(key=lambda k: (pref.get(k.get("concept") or "", 3), -(k.get("salience") or 0)))
        open_amount = sum(g["amount"] or 0 for g in work if g["kind"] == "overdue" and g.get("step") == "bezahlt")
        allq = open_questions(store)
        pay_exact = [q for q in allq if q["kind"] == "payment_match" and q.get("exact")]
        qs = [q for q in allq if q["kind"] != "payment_match"][:3]
        payments = [q for q in allq if q["kind"] == "payment_match"][:6]
        sugg = suggestions()
        quality = []
        for t in rt.model["types"]:
            nb = t.get("numbering") or {}
            for iss in nb.get("issues", []):
                quality.append(dict(type=t, issue=iss))
        summ = store.q1("SELECT summary, created_at FROM models ORDER BY version DESC LIMIT 1")
        summary = loads(summ["summary"]) if summ else {}
        return page(request, "home.html", dict(work=work[:10], more_work=max(0, len(work) - 10), kpis=ks[:4],
                                               questions=qs, suggestions=sugg, quality=quality, summary=summary,
                                               payments=payments, pay_exact=len(pay_exact),
                                               grown_at=summ["created_at"] if summ else None, greeting=views.greeting(),
                                               overdue_amount=open_amount, growth_file=_growth_file_exists()))

    def suggestions() -> list[dict]:
        out = []
        on = store.decisions("auto")
        for p in rt.model.get("processes", []):
            st = p.get("status")
            spec = rt.spec(p["type"])
            if not st:
                continue
            for au in st.get("autos", []):
                key = f"{p['type']}|{au['step']}|{au['attr']}"
                if on.get(key) in ("on", "off"):
                    continue
                out.append(dict(kind="auto", key=key, text=au["text"], evidence=f"in {au['ok']} von {au['n']} Fällen so",
                                type=spec))
            stale = [s for s in st.get("stale", []) if str(rt.by_id.get(s["rid"], {}).get("data", {}).get(st["attr"])) == s["was"]]
            if stale:
                step = next((x for x in p["steps"] if x["id"] == stale[0]["step"]), None)
                src = ", ".join(sorted({x["name"] for x in ([step] + step.get("also", [])) if x["source"] == "child"})) if step else ""
                was = " bzw. ".join(f"„{w}“" for w in sorted({x["was"] for x in stale}))
                out.append(dict(kind="stale", type=spec, n=len(stale),
                                text=f"{len(stale)} {spec['plural']} sind laut {src or 'verknüpften Daten'} schon "
                                     f"„{stale[0]['value']}“, stehen aber noch auf {was}.",
                                items=stale[:8]))
        return out

    def _growth_file_exists() -> bool:
        return (store.folder / "beispiel" / "spaeter").exists() and not store.kv_get("growth_demo_done")

    # --- feeding --------------------------------------------------------------------------------------
    async def upload(request: Request):
        form = await request.form()
        files = []
        for f in form.getlist("files"):
            if hasattr(f, "read"):
                data = await f.read()
                if data:
                    files.append((os.path.basename(f.filename or "datei"), data))
        if not files:
            return JSONResponse(dict(error="Keine Dateien erhalten"), 400)
        who = actor(request)

        def run(progress):
            progress(f"{len(files)} Datei(en) erhalten. Verdaue …", 0.02)
            res = ingest(store, files, who, progress)
            if not any(r["new"] for r in res):
                progress("Alle Dateien waren schon bekannt – nichts Neues.", 0.9)
            regrow(store, progress, who)
        return JSONResponse(dict(job=jobs.start("upload", run)))

    async def demo(request: Request):
        from ..demo.generate import generate

        def run(progress):
            target = store.folder / "beispiel"
            if target.exists():
                shutil.rmtree(target)
            progress("Erzeuge Beispieldaten einer Kaffeerösterei (Röstwerk Hafenbohne GmbH) …", 0.02)
            res = generate(target / "dump")
            (target / "spaeter").mkdir(exist_ok=True)
            for p in res["growth"]:
                shutil.move(str(p), target / "spaeter" / p.name)
            files = [(p.name, p.read_bytes()) for p in res["initial"]]
            ingest(store, files, "Beispiel", progress)
            regrow(store, progress, "Physarum")
        return JSONResponse(dict(job=jobs.start("demo", run)))

    async def demo_growth(request: Request):
        def run(progress):
            folder = store.folder / "beispiel" / "spaeter"
            files = [(p.name, p.read_bytes()) for p in sorted(folder.glob("*")) if p.is_file()]
            progress("Neue Daten: " + ", ".join(n for n, _ in files), 0.02)
            ingest(store, files, actor(request), progress)
            regrow(store, progress, actor(request))
            store.kv_set("growth_demo_done", True)
        return JSONResponse(dict(job=jobs.start("growth", run)))

    async def grow_page(request: Request):
        jid = int(request.path_params["jid"])
        return page(request, "grow.html", dict(job=jid))

    async def job_status(request: Request):
        r = store.q1("SELECT * FROM jobs WHERE id=?", (int(request.path_params["jid"]),))
        if not r:
            return JSONResponse(dict(status="unknown"), 404)
        res = loads(r["result"]) or {}
        return JSONResponse(dict(status=r["status"], progress=r["progress"], log=loads(r["log"]) or [],
                                 next=res.get("next", "/"), error=res.get("error")))

    # --- lists ------------------------------------------------------------------------------------------
    def filtered(spec: dict, request: Request) -> tuple[list[dict], dict]:
        recs = list(rt.records.get(spec["id"], []))
        q = (request.query_params.get("q") or "").strip()
        state = dict(q=q, filters={}, sort=request.query_params.get("sort") or "")
        if q:
            ids = search_ids(q, spec["id"])
            recs = [r for r in recs if r["id"] in ids]
        for k, v in request.query_params.items():
            if k.startswith("f_") and v:
                aid = k[2:]
                state["filters"][aid] = v
                recs = [r for r in recs if str(r["data"].get(aid)) == v]
        sort = state["sort"]
        if sort:
            desc = sort.startswith("-")
            aid = sort.lstrip("-")
            a = rt.attr(spec["id"], aid)

            def key(r):
                v = r["data"].get(aid)
                if a and a["kind"] == "ref":
                    v = rt.title(v) if v is not None else None
                return (v is None, v if not isinstance(v, str) else fold(v)) if not desc else (v is not None, v if not isinstance(v, str) else fold(v))
            try:
                recs.sort(key=key, reverse=desc)
            except TypeError:
                recs.sort(key=lambda r: str(r["data"].get(aid)), reverse=desc)
        else:
            # newest first for documents with a date, otherwise by title
            proc = next((p for p in rt.model.get("processes", []) if p["type"] == spec["id"]), None)
            dattr = proc["start"]["attr"] if proc else next((a["id"] for a in spec["attrs"] if a["kind"] in ("date", "datetime")
                                                            and a.get("fill", 0) > 0.8), None)
            if dattr and spec["kind"] in ("transaction", "document"):
                recs.sort(key=lambda r: str(r["data"].get(dattr) or ""), reverse=True)
            else:
                recs.sort(key=lambda r: fold(rt.title(r["id"])))
        return recs, state

    def search_ids(q: str, tid: str | None = None) -> set[int]:
        terms = [t for t in "".join(ch if ch.isalnum() or ch in "-@." else " " for ch in q).split() if t]
        if not terms:
            return set()
        fts = " ".join(f'"{t}"*' for t in terms)
        sql = "SELECT record_id FROM search WHERE search MATCH ?"
        args = [fts]
        if tid:
            sql += " AND type=?"
            args.append(tid)
        try:
            ids = {r["record_id"] for r in store.q(sql + " LIMIT 5000", args)}
        except Exception:
            ids = set()
        # titles of referenced records count too ("Hafenblick" finds the invoices of that customer)
        return ids

    async def list_view(request: Request):
        rt.ensure()
        tid = request.path_params["tid"]
        spec = rt.spec(tid)
        if not spec:
            return page(request, "message.html", dict(title="Nicht gefunden", text="Diese Art gibt es nicht."), 404)
        recs, state = filtered(spec, request)
        cols = views.list_columns(spec, 8 if spec["kind"] != "line" else 6)
        per = 50
        pg = max(1, int(request.query_params.get("seite") or 1))
        total = len(recs)
        rows = recs[(pg - 1) * per: pg * per]
        store.event("list", f"type:{tid}")
        ctx = dict(spec=spec, cols=cols, rows=rows, total=total, page=pg, pages=max(1, (total + per - 1) // per),
                   state=state, facets=views.facets(rt, spec, rt.records.get(tid, [])),
                   lines_of=line_child(spec))
        if request.query_params.get("teil"):
            return templates.TemplateResponse(request, "list_rows.html", ctx)
        return page(request, "list.html", ctx)

    def line_child(spec: dict) -> dict | None:
        """The line type that belongs to this document type (order -> order lines)."""
        for r in rt.model["relations"]:
            if r["dst"] == spec["id"] and r["kind"] == "parent":
                return dict(rel=r, spec=rt.spec(r["src"]))
        return None

    # --- records ------------------------------------------------------------------------------------------
    async def record_view(request: Request):
        rt.ensure()
        rt.work()  # fills pending payment proposals
        rid = int(request.path_params["rid"])
        rec = store.record(rid)
        if not rec or rec["deleted"]:
            return page(request, "message.html", dict(title="Nicht gefunden", text="Dieser Datensatz existiert nicht (mehr)."), 404)
        if rec["id"] != rid:
            return RedirectResponse(f"/r/{rec['id']}", 302)
        spec = rt.spec(rec["type"])
        if rid in rt.by_id:
            rec["data"] = rt.by_id[rid]["data"]  # includes computed totals
        rel = request.query_params.get("rel")
        store.event("view", f"type:{spec['id']}" + (f",rel:{rel}" if rel else ""))
        return page(request, "record.html", record_context(rec, spec, request))

    def record_context(rec: dict, spec: dict, request: Request) -> dict:
        rid = rec["id"]
        data = rec["data"]
        sources = {r["id"]: r for r in store.sources(active_only=False)}
        prov = (rec["meta"] or {}).get("prov", {})
        alts = (rec["meta"] or {}).get("alts", {})
        raw = (rec["meta"] or {}).get("raw", {})
        computed = set((rec["meta"] or {}).get("computed", []))
        writers = (rec["meta"] or {}).get("w", {})
        facts = []
        for a in spec["attrs"]:
            if a.get("hidden"):
                continue
            v = data.get(a["id"])
            if v is None and a["id"] in raw:
                v = raw[a["id"]]
            src = []
            for sid, tid_, line in (prov.get(a["id"]) or [])[:2]:
                s = sources.get(sid)
                if s:
                    src.append(f"{s['name']}, Zeile {line}")
            calc = a["id"] in computed or (writers.get(a["id"]) or [""])[0] == "auto" or bool(a.get("virtual"))
            facts.append(dict(attr=a, value=v, src=src, alts=[x[0] for x in alts.get(a["id"], [])][:3], calc=calc,
                              unlinked=a["kind"] == "ref" and a["id"] in raw))
        # process timeline
        proc = next((p for p in rt.model.get("processes", []) if p["type"] == spec["id"]), None)
        timeline = None
        if proc:
            timeline = build_timeline(proc, rec)
        # related records, ordered by Physarum conductivity of the relation
        cond = (rt.model.get("network") or {}).get("conductivity", {})
        groups = defaultdict(list)
        for frm, attr, kind, how in rt.backrefs.get(rid, []):
            r2 = rt.by_id.get(frm)
            if not r2:
                continue
            groups[(r2["type"], attr, kind)].append(r2)
        related = []
        for (tid2, attr, kind), recs in groups.items():
            s2 = rt.spec(tid2)
            if not s2:
                continue
            relid = f"r_{tid2}_{attr}" if kind == "ref" else (f"m_{tid2}_{attr}_{spec['id']}" if attr != "doc" else f"doc_{spec['id']}")
            cols = views.list_columns(s2, 6)
            cols = [c for c in cols if not (c["kind"] == "ref" and c.get("ref") == spec["id"])]
            proc2 = next((p for p in rt.model.get("processes", []) if p["type"] == tid2), None)
            dattr = proc2["start"]["attr"] if proc2 else None
            if dattr:
                recs.sort(key=lambda r: str(r["data"].get(dattr) or ""), reverse=True)
            total_attr = next((c for c in cols if c["kind"] == "money"), None)
            total = sum(float(r["data"].get(total_attr["id"]) or 0) for r in recs if isinstance(r["data"].get(total_attr["id"]), (int, float))) if total_attr else None
            label = s2["plural"] if kind == "ref" else (f"Erwähnt in {s2['plural']}" if attr != "doc" else "Erwähnt in Dokumenten")
            related.append(dict(spec=s2, attr=attr, kind=kind, recs=recs[:100], n=len(recs), cols=cols, rel=relid,
                                cond=cond.get(relid, 0.5 if kind == "ref" else 0.3), label=label, total=total,
                                total_attr=total_attr, lines=s2["kind"] == "line"))
        related.sort(key=lambda g: (not g["lines"], -g["cond"], -g["n"]))
        # what this record mentions (bank transfer -> invoices, e-mail -> customers)
        mentions = []
        for row in store.outrefs(rid):
            if row["kind"] == "mention" and row["to_id"] in rt.by_id:
                mentions.append(dict(rid=row["to_id"], spec=rt.spec(row["type"]), how=row["how"]))
        notes = store.q("SELECT * FROM notes WHERE record_id=? ORDER BY id DESC", (rid,))
        changes = []
        attr_names = {a["id"]: a for a in spec["attrs"]}
        for ch in store.changes(rid)[:60]:
            a = attr_names.get(ch["attr"])
            changes.append(dict(ts=ch["ts"], actor=ch["actor"], kind=ch["kind"], attr=a, note=ch["note"],
                                old=loads(ch["old"]) if ch["old"] else None, new=loads(ch["new"]) if ch["new"] else None,
                                source=sources.get(ch["source_id"])))
        src_files = [sources[s] for s in (rec["meta"] or {}).get("src", []) if s in sources]
        lock = ops.lock_state(rt, spec, rec)
        children = [r for r in rt.model["relations"] if r["dst"] == spec["id"] and r["kind"] == "ref"
                    and rt.spec(r["src"]) and rt.spec(r["src"])["kind"] == "transaction"]
        refs = [a for a in spec["attrs"] if a["kind"] == "ref" and data.get(a["id"]) and a["id"] != spec.get("key")]
        party = next((a for a in refs if (rt.spec(a.get("ref")) or {}).get("kind") == "master"), None) or (refs[0] if refs else None)
        money_attr = next((a for a in spec["attrs"] if a["kind"] == "money" and not a.get("hidden")
                           and any(t in fold(a["name"]) for t in ("brutto", "gesamt", "summe", "betrag", "total"))), None) \
            or next((a for a in spec["attrs"] if a["kind"] == "money" and not a.get("hidden")), None)
        status_attr = proc["status"]["attr"] if proc and proc.get("status") else None
        reach = None
        for rc in rt.model.get("reach", []):
            if rc["type"] == spec["id"]:
                reach = rt.by_id.get(rid, {}).get("_reach")
        maybe_paid = rt.pending_payments.get(rid) if hasattr(rt, "pending_payments") else None
        return dict(rec=rec, spec=spec, facts=facts, timeline=timeline, related=related, mentions=mentions, notes=notes,
                    maybe_paid=maybe_paid,
                    changes=changes, src_files=src_files, lock=lock, children=children, party=party,
                    money_attr=money_attr, status_attr=rt.attr(spec["id"], status_attr) if status_attr else None,
                    line=line_child(spec), reach=reach)

    def build_timeline(proc: dict, rec: dict) -> dict:
        data = rec["data"]
        today = date.today()
        start = as_date(data.get(proc["start"]["attr"]))
        steps = [dict(label=proc["start"]["label"], date=start, done=bool(start), kind="start")]
        nxt = None
        due_by_step = {d["step"]: d for d in proc["deadlines"] if d.get("step")}
        for st in proc["steps"]:
            when = None
            via = None
            for s in [st] + st.get("also", []):
                if s["source"] == "own":
                    d = as_date(data.get(s["attr"]))
                    if d and (when is None or d < when):
                        when, via = d, None
                else:
                    if s["rel_kind"] == "mention":
                        srcs = rt.mentions.get(s["rel_attr"], {}).get(rec["id"], [])
                    else:
                        srcs = [c["id"] for c in rt.records.get(s["type"], []) if c["data"].get(s["rel_attr"]) == rec["id"]]
                    for x in srcs:
                        d = as_date(rt.by_id.get(x, {}).get("data", {}).get(s["attr"]))
                        if d and (when is None or d < when):
                            when, via = d, x
            dl = due_by_step.get(st["id"])
            due = as_date(data.get(dl["attr"])) if dl else None
            late = (not when) and due and due < today
            item = dict(label=st["label"], date=when, done=bool(when), via=via, due=due, late=late, step=st,
                        usual=st.get("median_days"))
            if not when and nxt is None:
                nxt = item
                own = next((s for s in [st] + st.get("also", []) if s["source"] == "own"), None)
                child = next((s for s in [st] + st.get("also", []) if s["source"] == "child"), None)
                if own:
                    item["action"] = dict(kind="set_date", attr=own["attr"], label=f"Als {st['label']} markieren"
                                          if fold(st["label"]) in ("bezahlt", "geliefert", "versendet", "eingegangen",
                                                                   "erledigt", "berechnet") else f"{st['name']} eintragen")
                elif child and child.get("rel_kind") == "ref":
                    item["action"] = dict(kind="create_child", type=child["type"], attr=child["rel_attr"],
                                          label=f"{rt.spec(child['type'])['name']} anlegen")
            steps.append(item)
        status = proc.get("status")
        negative = status and str(data.get(status["attr"])) in (status.get("negative") or [])
        return dict(steps=steps, next=nxt, negative=negative)

    async def record_update(request: Request):
        rid = int(request.path_params["rid"])
        form = await request.form()
        raw = {k[2:]: v for k, v in form.items() if k.startswith("a_")}
        try:
            ops.update(rt, rid, raw, actor(request))
        except ops.OpError as e:
            rt.ensure()
            rec = store.record(rid)
            spec = rt.spec(rec["type"])
            ctx = record_context(rec, spec, request)
            ctx["error"] = str(e)
            return page(request, "record.html", ctx, 400)
        return RedirectResponse(f"/r/{rid}?gespeichert=1", 303)

    async def record_step(request: Request):
        rid = int(request.path_params["rid"])
        form = await request.form()
        try:
            changed = ops.set_step(rt, rid, form.get("attr"), form.get("date"), actor(request))
        except ops.OpError as e:
            return JSONResponse(dict(error=str(e)))
        rt.ensure()
        names = [rt.attr(rt.by_id[rid]["type"], a)["name"] for a in changed if rid in rt.by_id]
        return JSONResponse(dict(reload=True, toast="Erledigt: " + ", ".join(names) if names else "Gespeichert"))

    async def record_note(request: Request):
        rid = int(request.path_params["rid"])
        form = await request.form()
        ops.add_note(rt, rid, form.get("text"), actor(request))
        return RedirectResponse(f"/r/{rid}#notizen", 303)

    async def record_storno(request: Request):
        rid = int(request.path_params["rid"])
        form = await request.form()
        try:
            ops.storno(rt, rid, form.get("reason") or "", actor(request))
        except ops.OpError as e:
            return JSONResponse(dict(error=str(e)))
        return JSONResponse(dict(reload=True, toast="Storniert. Der Vorgang bleibt im Protokoll erhalten."))

    async def record_delete(request: Request):
        rid = int(request.path_params["rid"])
        rec = store.record(rid)
        try:
            ops.delete(rt, rid, actor(request))
        except ops.OpError as e:
            return JSONResponse(dict(error=str(e)))
        return JSONResponse(dict(toast="Gelöscht (bleibt im Protokoll nachvollziehbar).", reload=False,
                                 next=f"/t/{rec['type']}"))

    async def record_print(request: Request):
        rt.ensure()
        rid = int(request.path_params["rid"])
        rec = store.record(rid)
        spec = rt.spec(rec["type"])
        rec["data"] = rt.by_id.get(rid, rec)["data"]
        ctx = record_context(rec, spec, request)
        return templates.TemplateResponse(request, "print.html", dict(ctx, request=request, company=company_name()))

    def company_name() -> str:
        """The company's own name: set by the user, or read off the title rows of its lists
        ("Röstwerk Hafenbohne GmbH – Kundenliste")."""
        name = store.kv_get("company")
        if name:
            return name
        cands = Counter()
        for t in store.q("SELECT meta FROM raw_tables"):
            title = (loads(t["meta"]) or {}).get("title") or ""
            for sep in (" – ", " - ", ": "):
                if sep in title:
                    head = title.split(sep)[0].strip()
                    if 3 <= len(head) <= 60 and any(w in head for w in ("GmbH", "AG", "KG", "UG", "e.K.", "GbR", "OHG")):
                        cands[head] += 1
        return cands.most_common(1)[0][0] if cands else "Ihre Firma"

    async def record_reminder(request: Request):
        """A payment reminder letter for an overdue invoice; creating it is logged and sets the status."""
        rt.ensure()
        rid = int(request.path_params["rid"])
        rec = store.record(rid)
        spec = rt.spec(rec["type"])
        rec["data"] = rt.by_id.get(rid, rec)["data"]
        ctx = record_context(rec, spec, request)
        tl = ctx["timeline"]
        nxt = tl["next"] if tl else None
        party = ctx["party"]
        cust = rt.by_id.get(rec["data"].get(party["id"])) if party else None
        addr = []
        if cust:
            cspec = rt.spec(cust["type"])
            for role in ("name", "person", "street"):
                a = next((x for x in cspec["attrs"] if x.get("role") == role and cust["data"].get(x["id"])), None)
                if a:
                    addr.append(str(cust["data"][a["id"]]))
            z = next((x for x in cspec["attrs"] if x.get("role") == "zip" and cust["data"].get(x["id"])), None)
            o = next((x for x in cspec["attrs"] if x.get("role") == "city" and cust["data"].get(x["id"])), None)
            line = " ".join(str(cust["data"][x["id"]]) for x in (z, o) if x)
            if line:
                addr.append(line)
        if request.method == "POST":
            proc = next((p for p in rt.model.get("processes", []) if p["type"] == spec["id"]), None)
            st = (proc or {}).get("status")
            raw = {}
            if st:
                enum = (rt.attr(spec["id"], st["attr"]) or {}).get("enum") or []
                dun = next((v for v in enum if fold(str(v)) in ("gemahnt", "mahnung", "erinnert", "1. mahnung")), None)
                if dun and str(rec["data"].get(st["attr"])) != dun:
                    raw[st["attr"]] = dun
            if raw:
                ops.update(rt, rid, raw, actor(request), note="Zahlungserinnerung erstellt")
            ops.add_note(rt, rid, "Zahlungserinnerung erstellt", actor(request))
            return JSONResponse(dict(toast="Erinnerung protokolliert.", reload=True))
        return templates.TemplateResponse(request, "reminder.html", dict(ctx, request=request, company=company_name(),
                                                                         address=addr, step=nxt, today=views.today_text()))

    # --- forms -------------------------------------------------------------------------------------------
    async def new_form(request: Request):
        rt.ensure()
        tid = request.path_params["tid"]
        spec = rt.spec(tid)
        data = ops.prefill(rt, spec)
        for k, v in request.query_params.items():
            if k.startswith("a_"):
                data[k[2:]] = int(v) if v.isdigit() else v
        return page(request, "form.html", form_context(spec, data))

    def form_context(spec: dict, data: dict, error: str | None = None, lines_in: list | None = None) -> dict:
        fields = [a for a in spec["attrs"] if not a.get("hidden") and not a.get("virtual")]
        fields.sort(key=lambda a: (-(a.get("salience") or 0)))
        main = [a for a in fields if (a.get("fill") or 0) >= 0.25 or a["id"] in (spec.get("key"), spec.get("title"))]
        more = [a for a in fields if a not in main]
        order = {a["id"]: i for i, a in enumerate(spec["attrs"])}
        main.sort(key=lambda a: order[a["id"]])
        more.sort(key=lambda a: order[a["id"]])
        line = line_child(spec)
        lcols, lformulas, ltotal, prices = [], [], None, {}
        if line:
            lspec = line["spec"]
            lcols = [a for a in lspec["attrs"] if not a.get("hidden") and a["id"] != line["rel"]["attr"] and not a.get("virtual")]
            lformulas = [f for f in lspec.get("formulas") or [] if f["op"] != "sum_children"]
            ltotal = next((a["id"] for a in lcols if a["kind"] == "money" and any(t in fold(a["name"]) for t in ("gesamt", "summe", "betrag"))), None) \
                or next((a["id"] for a in reversed(lcols) if a["kind"] == "money"), None)
        computed_targets = {f["attr"] for f in spec.get("formulas") or []}
        party = next((a for a in main if a["kind"] == "ref"), None)
        return dict(spec=spec, data=data, main=main, more=more, error=error, line=line, lcols=lcols,
                    formulas=[f for f in spec.get("formulas") or [] if f["op"] != "sum_children"], lformulas=lformulas,
                    ltotal=ltotal, computed=computed_targets, lines_in=lines_in or [], party=party,
                    options=enum_options(spec), loptions=enum_options(line["spec"]) if line else {})

    def enum_options(spec: dict) -> dict:
        out = {}
        for a in spec["attrs"]:
            if a.get("enum"):
                out[a["id"]] = a["enum"]
        return out

    async def new_submit(request: Request):
        rt.ensure()
        tid = request.path_params["tid"]
        spec = rt.spec(tid)
        form = await request.form()
        raw = {k[2:]: v for k, v in form.items() if k.startswith("a_")}
        lines = defaultdict(dict)
        for k, v in form.items():
            if k.startswith("l_"):
                _, n, aid = k.split("_", 2)
                lines[int(n)][aid] = v
        line = line_child(spec)
        try:
            rid = ops.create(rt, tid, raw, actor(request), [lines[n] for n in sorted(lines)] if line else None,
                             line["spec"]["id"] if line else None)
        except ops.OpError as e:
            ctx = form_context(spec, {k: v for k, v in raw.items()}, str(e), [lines[n] for n in sorted(lines)])
            return page(request, "form.html", ctx, 400)
        return RedirectResponse(f"/r/{rid}?neu=1", 303)

    # --- api for forms --------------------------------------------------------------------------------------
    async def api_search(request: Request):
        rt.ensure()
        types = [t for t in (request.query_params.get("typen") or "").split(",") if t]
        q = (request.query_params.get("q") or "").strip()
        out = []
        cands = []
        if q:
            ids = search_ids(q)
            cands = [rt.by_id[i] for i in ids if i in rt.by_id and (not types or rt.by_id[i]["type"] in types)]
        else:
            for t in types:
                cands += rt.records.get(t, [])[:30]
        nq = fold(q)
        cands.sort(key=lambda r: (not fold(rt.title(r["id"])).startswith(nq), fold(rt.title(r["id"]))))
        for r in cands[:20]:
            spec = rt.spec(r["type"])
            sub = []
            if spec.get("key") and spec.get("title") and spec["key"] != spec["title"]:
                kv = r["data"].get(spec["key"])
                if kv and str(kv) != rt.title(r["id"]):
                    sub.append(str(kv))
            out.append(dict(id=r["id"], title=rt.title(r["id"]), sub=" · ".join(sub + [spec["name"]])))
        return JSONResponse(out)

    async def api_record(request: Request):
        rt.ensure()
        rid = int(request.path_params["rid"])
        r = rt.by_id.get(rid)
        if not r:
            return JSONResponse(dict(data={}), 404)
        prices = {}
        # unit prices learned from history: line price == article price
        for lp in rt.model.get("lookups", []):
            if lp["src_type"] == r["type"]:
                v = r["data"].get(lp["src_attr"])
                if isinstance(v, (int, float)):
                    prices[lp["attr"]] = v * lp.get("k", 1)
        return JSONResponse(dict(data=r["data"], prices=prices, title=rt.title(rid)))

    async def api_like_last(request: Request):
        rt.ensure()
        tid = request.query_params.get("typ")
        party = int(request.query_params.get("partei") or 0)
        spec = rt.spec(tid)
        line = line_child(spec)
        pattr = next((a["id"] for a in spec["attrs"] if a["kind"] == "ref" and party in rt.by_id and
                      rt.by_id[party]["type"] in (a.get("refs") or [a.get("ref")])), None)
        if not line or not pattr:
            return JSONResponse(dict(lines=[]))
        proc = next((p for p in rt.model.get("processes", []) if p["type"] == tid), None)
        dattr = proc["start"]["attr"] if proc else None
        mine = [r for r in rt.records.get(tid, []) if r["data"].get(pattr) == party]
        mine.sort(key=lambda r: str(r["data"].get(dattr) or "") if dattr else r["id"], reverse=True)
        for last in mine:
            lns = [x for x in rt.records.get(line["spec"]["id"], []) if x["data"].get(line["rel"]["attr"]) == last["id"]]
            if lns:
                out = []
                for x in lns:
                    row = {}
                    for a in line["spec"]["attrs"]:
                        if a["id"] == line["rel"]["attr"] or a.get("hidden"):
                            continue
                        v = x["data"].get(a["id"])
                        if v is None:
                            continue
                        row[a["id"]] = dict(id=v, title=rt.title(v)) if a["kind"] == "ref" else v
                    out.append(row)
                return JSONResponse(dict(lines=out, **{"from": rt.title(last["id"])}))
        return JSONResponse(dict(lines=[]))

    # --- search ------------------------------------------------------------------------------------------------
    async def search_page(request: Request):
        rt.ensure()
        q = (request.query_params.get("q") or "").strip()
        groups = []
        if q:
            ids = search_ids(q)
            store.event("search", None, dict(q=q, n=len(ids)))
            by_t = defaultdict(list)
            for i in ids:
                r = rt.by_id.get(i)
                if r:
                    by_t[r["type"]].append(r)
            for tid, recs in by_t.items():
                spec = rt.spec(tid)
                groups.append(dict(spec=spec, recs=recs[:25], n=len(recs), cols=views.list_columns(spec, 4)))
            groups.sort(key=lambda g: (g["spec"]["kind"] == "line", -(g["spec"].get("salience") or 0)))
        return page(request, "search.html", dict(q=q, groups=groups))

    # --- questions -----------------------------------------------------------------------------------------------
    async def questions_page(request: Request):
        rt.ensure()
        qs = open_questions(store)
        answered = store.q("SELECT * FROM questions WHERE status='answered' ORDER BY answered_at DESC LIMIT 30")
        return page(request, "questions.html", dict(questions=qs, answered=[dict(r, payload=loads(r["payload"]),
                                                                                  answer=loads(r["answer"])) for r in answered]))

    async def question_answer(request: Request):
        qid = int(request.path_params["qid"])
        form = await request.form()
        value = form.get("value")
        res = answer_question(store, qid, value, actor(request))
        if res.get("regrow"):
            jid = jobs.start("answer", lambda progress: regrow(store, progress, actor(request)), next_url="/fragen")
            return JSONResponse(dict(job=jid))
        rt.bump()
        msg = {"later": "Ich frage morgen noch einmal.", "unknown": "In Ordnung, ich lasse es, wie es ist."}.get(value, "Danke, gemerkt.")
        if res.get("merged"):
            msg = "Zusammengeführt. Der Verlauf beider Datensätze bleibt erhalten."
        return JSONResponse(dict(toast=msg))

    async def rule_toggle(request: Request):
        form = await request.form()
        key = form.get("key")
        val = form.get("value")
        with store.tx() as c:
            store.decide("auto", key, val, actor(request), c=c)
        return JSONResponse(dict(toast="Regel eingeschaltet. Sie wirkt ab jetzt bei jeder Eingabe." if val == "on" else "Gut, ich schlage das nicht mehr vor.",
                                 reload=False))

    async def accept_payments(request: Request):
        n = 0
        regrow_needed = False
        for q in open_questions(store):
            if q["kind"] == "payment_match" and q.get("exact"):
                res = answer_question(store, q["id"], "yes", actor(request))
                regrow_needed = regrow_needed or res.get("regrow")
                n += 1
        if regrow_needed:
            jid = jobs.start("payments", lambda progress: regrow(store, progress, actor(request)))
            return JSONResponse(dict(job=jid))
        rt.bump()
        return JSONResponse(dict(toast=f"{n} Zahlungen zugeordnet.", reload=True))

    async def apply_stale(request: Request):
        tid = request.path_params["tid"]
        n = ops.apply_stale(rt, tid, actor(request))
        return JSONResponse(dict(toast=f"{n} Datensätze abgeglichen.", reload=True))

    # --- organism -------------------------------------------------------------------------------------------
    async def organism(request: Request):
        rt.ensure()
        if not rt.model:
            return RedirectResponse("/", 302)
        rt.refresh_network()
        learned = learned_items()
        versions = [dict(v=r["version"], at=r["created_at"], summary=loads(r["summary"]) or {}) for r in store.models()[:20]]
        return page(request, "organism.html", dict(svg=views.organism_svg(rt), learned=learned, versions=versions))

    def learned_items() -> list[dict]:
        m = rt.model
        out = []
        for e in m.get("log", []):
            if e["kind"] == "extract":
                out.append(dict(kind="Herausgelöst", text=f"„{e['name']}“ aus {e['table']}: {e['groups']} verschiedene "
                                                         f"„{e['determinant']}“ in {e['rows']} Zeilen; "
                                                         f"{', '.join(e['deps'][:5])} hängen davon ab.",
                                why=f"Spart {e['savings']} Bit Wiederholung bei {e['cost']} Bit Kosten für einen neuen Begriff."))
            elif e["kind"] == "merge":
                out.append(dict(kind="Vereint", text=f"{e['b']} gehört zu denselben Dingen wie {e['a']}.", why=e["reason"]))
            elif e["kind"] == "dedupe":
                out.append(dict(kind="Dublette", text=f"„{e['a']}“ = „{e['b']}“ ({e['type']})",
                                why=", ".join(e["why"]) + (" – von Ihnen bestätigt" if e.get("decided") else "")))
        for r in m["relations"]:
            src, dst = rt.spec(r["src"]), rt.spec(r["dst"])
            if not src or not dst:
                continue
            a = rt.attr(r["src"], r["attr"])
            out.append(dict(kind="Verweis" if r["kind"] != "mention" else "Erwähnung",
                            text=f"{src['plural']} → {dst['plural']} über „{(a or {}).get('orig_name') or (a or {}).get('name')}“",
                            why=r["evidence"], rel=r))
        for t in m["types"]:
            for f in t.get("formulas") or []:
                out.append(dict(kind="Formel", text=f"{t['plural']}: {f['text']}",
                                why=f"stimmt in {round(f.get('share', 1) * 100)} % von {f.get('n')} Fällen"))
            nb = t.get("numbering")
            if nb:
                out.append(dict(kind="Nummernkreis", text=f"{t['plural']}: nächste Nummer {nb['next']}",
                                why=f"{round(nb['share'] * 100)} % der {nb['n']} Nummern folgen diesem Muster"))
            for th in t.get("thresholds") or []:
                out.append(dict(kind="Regel", text=f"{t['plural']}: {th['text']}", why="aus den Spaltennamen erkannt"))
        for p in m.get("processes", []):
            chain = " → ".join([p["start"]["label"]] + [f"{s['label']} (Ø {s['median_days']:.0f} T.)" if s.get("median_days") is not None
                                                        else s["label"] for s in p["steps"]])
            out.append(dict(kind="Ablauf", text=f"{p['name']}: {chain}", why=f"aus {p['n']} Fällen"))
        return out

    async def organism_rename(request: Request):
        form = await request.form()
        tid = form.get("type")
        name, plural = (form.get("name") or "").strip(), (form.get("plural") or "").strip()
        if not name:
            return RedirectResponse("/organismus", 303)
        with store.tx() as c:
            store.decide("rename_type", tid, dict(name=name, plural=plural or name), actor(request), c=c)
            m = store.model()
            for t in m["types"]:
                if t["id"] == tid:
                    t["name"], t["plural"] = name, plural or name
            c.execute("UPDATE models SET model=? WHERE version=?", (dumps(m), m["version"]))
            rt.bump(c)
        return RedirectResponse(f"/t/{tid}", 303)

    async def organism_attr(request: Request):
        form = await request.form()
        tid, aid = form.get("type"), form.get("attr")
        action = form.get("action")
        with store.tx() as c:
            m = store.model()
            for t in m["types"]:
                for a in t["attrs"]:
                    if t["id"] == tid and a["id"] == aid:
                        if action == "rename" and form.get("name"):
                            store.decide("rename_attr", aid, form.get("name").strip(), actor(request), c=c)
                            a["name"] = form.get("name").strip()
                        elif action == "hide":
                            store.decide("hide_attr", aid, True, actor(request), c=c)
                            a["hidden"] = True
                        elif action == "show":
                            store.decide("hide_attr", aid, False, actor(request), c=c)
                            a["hidden"] = False
            c.execute("UPDATE models SET model=? WHERE version=?", (dumps(m), m["version"]))
            rt.bump(c)
        return RedirectResponse(request.headers.get("referer") or f"/t/{tid}", 303)

    async def organism_relation(request: Request):
        form = await request.form()
        key = form.get("key")
        with store.tx() as c:
            store.decide("relation", key, "no", actor(request), c=c)
        jid = jobs.start("relation", lambda progress: regrow(store, progress, actor(request)), next_url="/organismus")
        return JSONResponse(dict(job=jid))

    async def processes_page(request: Request):
        rt.ensure()
        work = rt.work()
        items = []
        for p in rt.model.get("processes", []):
            open_counts = Counter()
            for g in work:
                if g["type"] == p["type"] and g.get("step"):
                    st = next((s for s in p["steps"] if s["label"] == g["step"]), None)
                    if st:
                        open_counts[st["id"]] += g["count"]
            items.append(dict(p=p, svg=views.process_svg(rt, p, open_counts), spec=rt.spec(p["type"])))
        return page(request, "processes.html", dict(items=items))

    # --- sources -----------------------------------------------------------------------------------------------
    async def sources_page(request: Request):
        rt.ensure()
        srcs = store.sources(active_only=False)
        became = defaultdict(list)
        if rt.model:
            for t in rt.model["types"]:
                for m in t["members"]:
                    for src in m.get("sources") or [m.get("source")]:
                        became[src].append(t)
        docs = Counter(r["source_id"] for r in store.q("SELECT source_id FROM documents"))
        rows = []
        for s in srcs:
            summ = loads(s["summary"]) or {}
            rows.append(dict(s=s, summary=summ, types=list({t["id"]: t for t in became.get(s["name"], [])}.values()),
                             notes=loads(s["notes"]) or [], docs=docs.get(s["id"], 0)))
        return page(request, "sources.html", dict(rows=rows))

    def locked_in_sources(sids: list[int]) -> int:
        """Issued invoices whose every source would be taken out."""
        from ..grow import protected_attrs
        rt.ensure()
        out = 0
        gone = set(sids)
        for spec in (rt.model or {}).get("types", []):
            if not protected_attrs(spec):
                continue
            for r in rt.records.get(spec["id"], []):
                src = set((r.get("meta") or {}).get("src") or [])
                if src and src <= gone:
                    out += 1
        return out

    async def source_remove(request: Request):
        sid = int(request.path_params["sid"])
        blocked = locked_in_sources(store.descendants(sid))
        if blocked:
            return JSONResponse(dict(error=f"Diese Datei enthält {blocked} ausgestellte Rechnung(en). Belege lassen sich "
                                           "nicht herausnehmen – eine neue Fassung einwerfen ersetzt sie.", ok=False))
        with store.tx() as c:
            store.set_active(sid, False, c)
        jid = jobs.start("remove", lambda progress: regrow(store, progress, actor(request)), next_url="/quellen")
        return JSONResponse(dict(job=jid))

    async def source_restore(request: Request):
        sid = int(request.path_params["sid"])
        with store.tx() as c:
            store.set_active(sid, True, c)
        jid = jobs.start("restore", lambda progress: regrow(store, progress, actor(request)), next_url="/quellen")
        return JSONResponse(dict(job=jid))

    async def source_file(request: Request):
        sid = int(request.path_params["sid"])
        s = store.q1("SELECT * FROM sources WHERE id=?", (sid,))
        p = store.source_path(sid, s["name"])
        return FileResponse(p, filename=s["name"])

    # --- export -----------------------------------------------------------------------------------------------
    def export_rows(spec: dict) -> tuple[list[str], list[list]]:
        cols = [a for a in spec["attrs"] if not a.get("constant")]
        head = [a["name"] for a in cols]
        rows = []
        for r in rt.records.get(spec["id"], []):
            row = []
            for a in cols:
                v = r["data"].get(a["id"])
                if a["kind"] == "ref" and isinstance(v, int):
                    v = rt.title(v)
                row.append(v)
            rows.append(row)
        return head, rows

    async def export_csv(request: Request):
        rt.ensure()
        spec = rt.spec(request.path_params["tid"])
        head, rows = export_rows(spec)
        buf = io.StringIO()
        w = csv.writer(buf, delimiter=";")
        w.writerow(head)
        for row in rows:
            w.writerow([views.input_value(a, v) if v is not None else "" for a, v in zip([a for a in spec["attrs"] if not a.get("constant")], row)])
        return Response(("﻿" + buf.getvalue()).encode("utf-8"), media_type="text/csv",
                        headers={"Content-Disposition": f'attachment; filename="{spec["plural"]}.csv"'})

    async def export_xlsx(request: Request):
        import openpyxl

        rt.ensure()
        spec = rt.spec(request.path_params["tid"])
        head, rows = export_rows(spec)
        wb = openpyxl.Workbook()
        ws = wb.active
        ws.title = spec["plural"][:30]
        ws.append(head)
        attrs = [a for a in spec["attrs"] if not a.get("constant")]
        for row in rows:
            out = []
            for a, v in zip(attrs, row):
                if a["kind"] == "date" and v:
                    out.append(as_date(v))
                else:
                    out.append(v)
            ws.append(out)
        buf = io.BytesIO()
        wb.save(buf)
        return Response(buf.getvalue(), media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                        headers={"Content-Disposition": f'attachment; filename="{spec["plural"]}.xlsx"'})

    async def export_backup(request: Request):
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
            tmp = Path(tempfile.mkdtemp())
            snap = tmp / "physarum.db"
            src = store.conn()
            import sqlite3
            dst = sqlite3.connect(snap)
            src.backup(dst)
            dst.close()
            z.write(snap, "physarum.db")
            for p in (store.folder / "originale").glob("*"):
                z.write(p, f"originale/{p.name}")
            shutil.rmtree(tmp, ignore_errors=True)
        return Response(buf.getvalue(), media_type="application/zip",
                        headers={"Content-Disposition": f'attachment; filename="physarum-sicherung-{date.today().isoformat()}.zip"'})

    async def procedure_doc(request: Request):
        rt.ensure()
        decisions = store.q("SELECT * FROM decisions ORDER BY ts")
        srcs = store.sources(active_only=False)
        versions = store.models()
        nchanges = store.q1("SELECT COUNT(*) AS n FROM changes")["n"]
        by_kind = {r["kind"]: r["n"] for r in store.q("SELECT kind, COUNT(*) AS n FROM changes GROUP BY kind")}
        return page(request, "procedure.html", dict(decisions=decisions, srcs=srcs, versions=versions, nchanges=nchanges,
                                                    by_kind=by_kind, learned=learned_items() if rt.model else []))

    async def set_name(request: Request):
        form = await request.form()
        resp = RedirectResponse(request.headers.get("referer") or "/", 303)
        name = (form.get("name") or "").strip()[:40]
        if name:
            resp.set_cookie("physarum_name", name, max_age=3600 * 24 * 365, samesite="lax")
        return resp

    async def health(request: Request):
        return PlainTextResponse("ok")

    routes = [
        Route("/", home), Route("/gesund", health),
        Route("/einwerfen", upload, methods=["POST"]), Route("/beispiel", demo, methods=["POST"]),
        Route("/beispiel/wachstum", demo_growth, methods=["POST"]),
        Route("/wachsen/{jid:int}", grow_page), Route("/api/job/{jid:int}", job_status),
        Route("/t/{tid}", list_view), Route("/t/{tid}/neu", new_form), Route("/t/{tid}/neu", new_submit, methods=["POST"]),
        Route("/r/{rid:int}", record_view), Route("/r/{rid:int}", record_update, methods=["POST"]),
        Route("/r/{rid:int}/schritt", record_step, methods=["POST"]),
        Route("/r/{rid:int}/notiz", record_note, methods=["POST"]),
        Route("/r/{rid:int}/storno", record_storno, methods=["POST"]),
        Route("/r/{rid:int}/loeschen", record_delete, methods=["POST"]),
        Route("/r/{rid:int}/druck", record_print),
        Route("/r/{rid:int}/erinnerung", record_reminder, methods=["GET", "POST"]),
        Route("/suche", search_page), Route("/api/suche", api_search), Route("/api/datensatz/{rid:int}", api_record),
        Route("/api/wie-letztes-mal", api_like_last),
        Route("/fragen", questions_page), Route("/fragen/{qid:int}", question_answer, methods=["POST"]),
        Route("/regel", rule_toggle, methods=["POST"]), Route("/abgleich/{tid}", apply_stale, methods=["POST"]),
        Route("/zahlungen/zuordnen", accept_payments, methods=["POST"]),
        Route("/organismus", organism), Route("/organismus/umbenennen", organism_rename, methods=["POST"]),
        Route("/organismus/feld", organism_attr, methods=["POST"]),
        Route("/organismus/verweis", organism_relation, methods=["POST"]),
        Route("/ablaeufe", processes_page),
        Route("/quellen", sources_page), Route("/quellen/{sid:int}/entfernen", source_remove, methods=["POST"]),
        Route("/quellen/{sid:int}/zurueck", source_restore, methods=["POST"]),
        Route("/quellen/{sid:int}/datei", source_file),
        Route("/export/{tid}.csv", export_csv), Route("/export/{tid}.xlsx", export_xlsx),
        Route("/sicherung.zip", export_backup), Route("/verfahrensdoku", procedure_doc),
        Route("/ich", set_name, methods=["POST"]),
        Mount("/static", StaticFiles(directory=str(HERE / "static")), name="static"),
    ]
    app = Starlette(routes=routes)
    app.state.store = store
    app.state.rt = rt
    app.state.jobs = jobs
    return app
