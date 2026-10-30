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
from datetime import date, timedelta
from pathlib import Path

from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import FileResponse, JSONResponse, PlainTextResponse, RedirectResponse, Response
from starlette.concurrency import run_in_threadpool
from starlette.middleware import Middleware
from starlette.routing import Mount, Route
from starlette.staticfiles import StaticFiles
from starlette.templating import Jinja2Templates

from .. import ops
from ..grow import Progress, ingest, regrow
from ..process import kpis
from ..questions import answer as answer_question
from ..questions import CONSEQUENCES, hints, open_questions
from ..runtime import Runtime
from ..store import Store, dumps, loads, now_iso
from ..text import fold, norm_name
from ..values import as_date, display, event_date, fmt_number
from .. import billing, lexicon
from ..payments import bank_allocations
from . import views
from .guard import Guard

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
                    self.rt.bump(c)
                progress("Seiten werden vorbereitet …", 0.97)
                try:
                    # the first page after growing must not wait: build the picture before saying "fertig"
                    self.rt.ensure()
                    self.rt.work()
                    self.rt.refresh_network(force=True)
                except Exception:  # noqa: BLE001 - the pages build it themselves then
                    traceback.print_exc()
                with self.store.tx() as c:
                    c.execute("UPDATE jobs SET status='done', progress=1, finished_at=? WHERE id=?", (now_iso(), jid))
            except Exception as e:  # pragma: no cover - shown to the user
                traceback.print_exc()
                lines.append(f"Fehler: {type(e).__name__}: {e}")
                with self.store.tx() as c:
                    c.execute("UPDATE jobs SET status='error', log=?, finished_at=?, result=? WHERE id=?",
                              (dumps(lines), now_iso(), dumps(dict(error=str(e))), jid))


def _attachment(name: str) -> str:
    """Content-Disposition for any file name (umlauts, arrows): ASCII fallback plus UTF-8."""
    from urllib.parse import quote
    ascii_name = "".join(ch if 32 <= ord(ch) < 127 and ch not in '"\\' else "_" for ch in name)
    return f'attachment; filename="{ascii_name}"; filename*=UTF-8\'\'{quote(name)}'


def local_path(p: str | None, default: str = "/") -> str:
    """A way back that stays inside Physarum: '/t/t5?seite=2', never 'javascript:…' or '//elsewhere'."""
    if not p:
        return default
    if p.startswith(("http://", "https://")):
        from urllib.parse import urlsplit
        u = urlsplit(p)
        p = u.path + (f"?{u.query}" if u.query else "")
    if not p.startswith("/") or p.startswith("//") or "\\" in p or any(ord(ch) < 32 for ch in p):
        return default
    return p


def formed(fn):
    """A writing handler gets its form, then runs in a worker thread like every other page:
    the server stays responsive while one request computes."""
    async def endpoint(request: Request):
        form = await request.form()
        return await run_in_threadpool(fn, request, form)
    endpoint.__name__ = fn.__name__
    return endpoint


def create_app(folder: str | Path, hosts: set[str] | None = None, any_ip: bool = False) -> Starlette:
    store = Store(folder)
    rt = Runtime(store)
    jobs = Jobs(store, rt)
    templates = Jinja2Templates(directory=str(HERE / "templates"))
    env = templates.env
    env.globals.update(fmt=lambda attr, v, **kw: views.fmt(rt, attr, v, **kw), money=views.money, spark=views.spark,
                       ago=views.ago, days_text=views.days_text, input_value=views.input_value,
                       after_days=views.after_days,
                       title=lambda rid: rt.title(rid), status_class=views.status_class, display=display,
                       show_value=views.show_value, consequences_of=lambda kind, v: CONSEQUENCES.get((kind, v), ""),
                       stale_days=lambda iso: (date.today() - date.fromisoformat(str(iso)[:10])).days if iso else 0)
    env.filters["de"] = lambda x, d=0: views.display(x, "number") if d == 0 else fmt_number(x, d)
    env.filters["json"] = lambda x: json.dumps(x, ensure_ascii=False, default=str)
    # VAT rates, highest first; an unclear rate (None) last
    env.filters["by_rate"] = lambda d: sorted((d or {}).items(), key=lambda kv: (kv[0] is None, -(kv[0] or 0)))
    env.filters["iban"] = lambda x: " ".join((lambda s: [s[i:i + 4] for i in range(0, len(s), 4)])("".join(str(x or "").split())))
    env.finalize = lambda x: "" if x is None else x  # a missing value prints as nothing, never as "None"

    def actor(request: Request) -> str:
        return request.cookies.get("physarum_name") or "Benutzer"

    def page(request: Request, name: str, ctx: dict, status: int = 200):
        rt.ensure()
        active, dormant = rt.nav() if rt.model else ([], [])
        nq = store.q1("SELECT COUNT(*) AS n FROM questions WHERE status='open'")["n"] if rt.model else 0
        base = dict(request=request, nav_active=active, nav_dormant=dormant, n_questions=nq, me=actor(request),
                    model=rt.model, today=views.today_text(), path=request.url.path, today_iso=date.today().isoformat())
        base.update(ctx)
        return templates.TemplateResponse(request, name, base, status_code=status)

    def wants_json(request: Request) -> bool:
        return request.headers.get("x-requested-with") == "fetch"

    # --- home -----------------------------------------------------------------------------------
    def home(request: Request):
        rt.ensure()
        if not rt.model:
            return page(request, "empty.html", {})
        rt.refresh_network()
        work = rt.work()
        ks = kpis(rt.model, rt.active_records())
        pref = {"rechnung": 0, "auftrag": 1, "bestellung": 2, "einkauf": 4}
        ks.sort(key=lambda k: (pref.get(k.get("concept") or "", 3), -(k.get("salience") or 0)))
        open_amount = sum(g["amount"] or 0 for g in work if g["kind"] == "overdue" and g.get("step") == "bezahlt")
        open_items = None
        by_type = defaultdict(list)
        for e in rt.ledger.values():
            if not e["outgoing"]:
                by_type[e["type"]].append(e)
        if by_type:
            tid, es = max(by_type.items(), key=lambda kv: len(kv[1]))
            op = [e for e in es if e["state"] in ("offen", "teilbezahlt") and e["open"] > 0]
            if op:
                open_items = dict(type=tid, plural=rt.spec(tid)["plural"], amount=round(sum(e["open"] for e in op), 2),
                                  n=sum(1 for e in op if e["state"] == "offen"),
                                  partial=sum(1 for e in op if e["state"] == "teilbezahlt"), overdue=open_amount)
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
        n_files = store.q1("SELECT COUNT(*) n FROM sources WHERE active=1 AND parent_id IS NULL")["n"]
        glance = views.at_a_glance(rt, open_items, n_files)
        shown = views.cards(work[:40], lambda tid: (rt.spec(tid) or {}).get("plural", ""))
        n_items = sum(c["count"] for c in shown if c["severity"] >= 2)  # what the cards hold; hints (a quiet customer) wait
        return page(request, "home.html", dict(work=shown, more_work=sum(1 for c in shown if c["hidden"]), kpis=ks[:1],
                                               glance=glance,
                                               consequences=CONSEQUENCES,
                                               questions=qs, suggestions=sugg, quality=quality, summary=summary,
                                               payments=payments, pay_exact=len(pay_exact),
                                               grown_at=summ["created_at"] if summ else None, greeting=views.greeting(),
                                               overdue_amount=open_amount, growth_file=_growth_file_exists(),
                                               n_items=n_items, open_items=open_items, bank_until=bank_until()))

    def bank_until() -> dict | None:
        """The newest day the bank statements reach, when it lies more than a week back: what is overdue may be
        paid since – the owner should know before reminding anyone."""
        from ..reconcile import bank_specs
        days = [d for b in bank_specs(rt.model) for r in rt.records.get(b["spec"]["id"], [])
                if (d := as_date(r["data"].get(b["date"]["id"])))]
        last = max(days, default=None)
        if last is None:  # no statement at all: what is open and overdue is only what the lists say
            return dict(day=None, days=None) if rt.ledger else None
        age = (date.today() - last).days
        return dict(day=last, days=age) if age > 7 else None

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

    def demo(request: Request):
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

    def demo_growth(request: Request):
        def run(progress):
            folder = store.folder / "beispiel" / "spaeter"
            files = [(p.name, p.read_bytes()) for p in sorted(folder.glob("*")) if p.is_file()]
            progress("Neue Daten: " + ", ".join(n for n, _ in files), 0.02)
            ingest(store, files, actor(request), progress)
            regrow(store, progress, actor(request))
            store.kv_set("growth_demo_done", True)
        return JSONResponse(dict(job=jobs.start("growth", run)))

    def grow_page(request: Request):
        jid = int(request.path_params["jid"])
        return page(request, "grow.html", dict(job=jid))

    def job_status(request: Request):
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
                wanted = v.split("|")
                recs = [r for r in recs if r["data"].get(aid) is not None and
                        (views.facet_key(r["data"].get(aid)) in wanted or str(r["data"].get(aid)) in wanted)]
        von, bis = request.query_params.get("von"), request.query_params.get("bis")
        if von or bis:
            proc = next((p for p in rt.model.get("processes", []) if p["type"] == spec["id"]), None)
            feld = request.query_params.get("feld") or (proc["start"]["attr"] if proc else None)
            a = rt.attr(spec["id"], feld) if feld else None
            lo, hi = as_date(von) if von else None, as_date(bis) if bis else None
            if a and (lo or hi):
                recs = [r for r in recs if as_date(r["data"].get(feld)) and (not lo or as_date(r["data"][feld]) >= lo)
                        and (not hi or as_date(r["data"][feld]) <= hi)]
                label = f"{a['name']}: {display(von, 'date') if von else '…'} – {display(bis, 'date') if bis else '…'}"
                if lo and hi and lo.day == 1 and lo.year == hi.year and lo.month == hi.month:
                    label = f"{a['name']}: {views.MONTHS[lo.month - 1]} {lo.year}"
                state["range"] = dict(von=von or "", bis=bis or "", feld=feld, label=label)
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
            default_order(spec, recs)
        return recs, state

    def default_order(spec: dict, recs: list[dict]) -> None:
        """Newest first for things with a date (invoices, mails, bank lines), otherwise by title."""
        proc = next((p for p in rt.model.get("processes", []) if p["type"] == spec["id"]), None)
        dattr = proc["start"]["attr"] if proc else next((a["id"] for a in spec["attrs"] if a["kind"] in ("date", "datetime")
                                                        and a.get("fill", 0) > 0.8), None)
        if dattr and spec["kind"] in ("transaction", "document", "line"):
            recs.sort(key=lambda r: str(r["data"].get(dattr) or ""), reverse=True)
        else:
            recs.sort(key=lambda r: fold(rt.title(r["id"])))

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

    def list_view(request: Request):
        rt.ensure()
        tid = request.path_params["tid"]
        spec = rt.spec(tid)
        if not spec:
            now = next((t["id"] for t in rt.model.get("types", []) if tid in (t.get("former") or [])), None)
            if now:  # two lists became one
                return RedirectResponse(f"/t/{now}", 303)
            return page(request, "message.html", dict(title="Nicht gefunden", text="Diese Art gibt es nicht."), 404)
        recs, state = filtered(spec, request)
        pins = store.decisions("list_cols").get(tid) or {}
        cols = views.list_columns(spec, 8 if spec["kind"] != "line" else 6, pins)
        per = 50
        try:
            pg = max(1, int(request.query_params.get("seite") or 1))
        except ValueError:
            pg = 1
        total = len(recs)
        rows = recs[(pg - 1) * per: pg * per]
        store.event("list", f"type:{tid}")
        sums = {}
        for c in cols:
            # the sum of unit prices in a price list says nothing; that of invoices does
            if c["kind"] == "money" and spec["kind"] in ("transaction", "line") and \
                    not set(billing.words(c["name"])) & {"preis", "einzelpreis", "stueckpreis", "satz", "stundensatz",
                                                         "rate", "listenpreis", "ek", "vk", "tarif"}:
                vals = [r["data"].get(c["id"]) for r in recs]
                vals = [v for v in vals if isinstance(v, (int, float)) and not isinstance(v, bool)]
                if vals:
                    sums[c["id"]] = round(sum(vals), 2)
        ctx = dict(spec=spec, cols=cols, rows=rows, total=total, page=pg, pages=max(1, (total + per - 1) // per),
                   state=state, facets=views.facets(rt, spec, rt.records.get(tid, [])), sums=sums,
                   col_ids={c["id"] for c in cols}, lines_of=line_child(spec), hints=hints(store, tid))
        if request.query_params.get("teil"):
            return templates.TemplateResponse(request, "list_rows.html", ctx)
        return page(request, "list.html", ctx)

    def pin_column(request: Request, form):
        tid = request.path_params["tid"]
        aid, action = form.get("attr"), form.get("action")
        cur = store.decisions("list_cols").get(tid) or {"pin": [], "unpin": []}
        pin, unpin = [x for x in cur.get("pin", []) if x != aid], [x for x in cur.get("unpin", []) if x != aid]
        (pin if action == "pin" else unpin).append(aid)
        with store.tx() as c:
            store.decide("list_cols", tid, dict(pin=pin, unpin=unpin), actor(request), c=c)
        return JSONResponse(dict(reload=True, toast="Spalte " + ("angeheftet." if action == "pin" else "aus der Liste genommen.")))

    def line_child(spec: dict) -> dict | None:
        """The line type that belongs to this document type (order -> order lines)."""
        for r in rt.model["relations"]:
            if r["dst"] == spec["id"] and r["kind"] == "parent":
                return dict(rel=r, spec=rt.spec(r["src"]))
        return None

    # --- records ------------------------------------------------------------------------------------------
    def record_view(request: Request):
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

    from ..payments import BY_AMOUNT, CASH_KINDS, CONFIRMED

    def _assign_candidates(rid: int, spec: dict, data: dict, alloc: list) -> list[dict] | None:
        """For a bank line that pays nothing (or not all): the open invoices it may pay, the likeliest first –
        the same amount, then the same payer."""
        from ..reconcile import bank_specs
        from ..text import name_similarity
        b = next((x for x in bank_specs(rt.model) if x["spec"]["id"] == spec["id"]), None)
        amount = data.get(b["money"]["id"]) if b else None
        if not b or not isinstance(amount, (int, float)) or isinstance(amount, bool) or abs(amount) < 0.005:
            return None
        rest = abs(float(amount)) - sum(x["amount"] for x in alloc)
        if rest <= 0.005:
            return None
        payer = norm_name(data.get(b["name"]["id"])) if b.get("name") and data.get(b["name"]["id"]) else ""
        out = []
        for irid, e in rt.ledger.items():
            if e["state"] not in ("offen", "teilbezahlt") or bool(e.get("outgoing")) != (amount < 0) or e["open"] <= 0.005:
                continue
            r = rt.by_id.get(irid)
            if not r:
                continue
            p = next((x for x in rt.model.get("processes", []) if x["type"] == r["type"]), None)
            pv = r["data"].get(p["party"]) if p and p.get("party") else None
            who = rt.title(pv) if isinstance(pv, int) and pv in rt.by_id else (pv if isinstance(pv, str) else "")
            same = name_similarity(payer, norm_name(who)) if payer and who else 0.0
            out.append((abs(e["open"] - rest) > 0.005, -round(same, 1), abs(e["open"] - rest),
                        dict(rid=irid, label=f"{rt.title(irid)} · {who or '–'} · offen {views.money(e['open'])}",
                             exact=abs(e["open"] - rest) <= 0.005)))
        out.sort(key=lambda x: x[:3])
        return [x[3] for x in out[:15]]

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
            w = writers.get(a["id"]) or [""]
            if w[0] == "user":
                src.append(f"von Hand eingetragen am {display(str(w[1])[:10], 'date')}" if len(w) > 1 else "von Hand eingetragen")
            else:
                for sid, tid_, line in (prov.get(a["id"]) or [])[:2]:
                    s = sources.get(sid)
                    if s:
                        src.append(f"{s['name']}, Zeile {line}")
            calc = a["id"] in computed or w[0] == "auto" or bool(a.get("virtual"))
            sh = ((rec["meta"] or {}).get("shadow") or {}).get(a["id"])
            facts.append(dict(attr=a, value=v, src=src, alts=[x[0] for x in alts.get(a["id"], [])][:3], calc=calc,
                              unlinked=a["kind"] == "ref" and a["id"] in raw and not isinstance(data.get(a["id"]), int),
                              shadow=dict(value=sh[0], source=sh[1]) if sh else None))
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
            a2 = rt.attr(r2["type"], attr) if kind == "ref" else None
            if a2 and a2.get("hidden") and a2.get("derived"):
                continue  # the same link once more under another column ("Kunde" next to "Kd-Nr")
            groups[(r2["type"], attr, kind)].append(r2)
        related = []
        for (tid2, attr, kind), recs in groups.items():
            s2 = rt.spec(tid2)
            if not s2:
                continue
            relid = f"r_{tid2}_{attr}" if kind == "ref" else (f"m_{tid2}_{attr}_{spec['id']}" if attr != "doc" else f"doc_{spec['id']}")
            proc2 = next((p for p in rt.model.get("processes", []) if p["type"] == tid2), None)
            dattr = proc2["start"]["attr"] if proc2 else None
            if dattr:
                recs.sort(key=lambda r: str(r["data"].get(dattr) or ""), reverse=True)
            cols = views.related_columns(s2, recs, spec["id"], 6)
            money_cols = [c for c in s2["attrs"] if c["kind"] == "money" and not c.get("hidden")]
            lines = s2["kind"] == "line"
            # a unit price adds up to nothing: 2 × 9,52 € are not 9,52 €
            per_piece = [c for c in money_cols if billing.words(c["name"]) & {"einzelpreis", "preis", "price", "ep",
                                                                              "stueckpreis", "einheitspreis"}
                         and not billing.words(c["name"]) & {"gesamt", "summe", "total", "gp", "gesamtpreis"}]
            sums = [c for c in money_cols if c not in per_piece]
            total_attr = next((c for c in sums if set(billing.words(c["name"])) & {"gesamt", "summe", "total", "betrag",
                                                                                 "brutto", "offen"}), None) \
                or (sums[-1] if sums else None)
            total = sum(float(r["data"].get(total_attr["id"]) or 0) for r in recs if isinstance(r["data"].get(total_attr["id"]), (int, float))) if total_attr else None
            qty = billing.attr_by(s2, kind="number", role="quantity") if lines and per_piece and not total_attr else None
            if qty:  # the lines' worth: quantity × price
                total = round(sum(float(r["data"][qty["id"]]) * float(r["data"][per_piece[0]["id"]]) for r in recs
                                  if isinstance(r["data"].get(qty["id"]), (int, float))
                                  and isinstance(r["data"].get(per_piece[0]["id"]), (int, float))), 2)
                total_attr = dict(name=f"Summe (Menge × {per_piece[0]['name']})", currency=per_piece[0].get("currency"))
            label = s2["plural"] if kind == "ref" else (f"Erwähnt in {s2['plural']}" if attr != "doc" else "Erwähnt in Dokumenten")
            shown = recs[:100] if lines else recs[:10]  # an invoice's positions in full; of 34 invoices the newest
            related.append(dict(spec=s2, attr=attr, kind=kind, recs=shown, n=len(recs), cols=cols, rel=relid,
                                cond=cond.get(relid, 0.5 if kind == "ref" else 0.3), label=label, total=total,
                                total_attr=total_attr, lines=lines,
                                more=f"/t/{tid2}?f_{attr}={rid}" if kind == "ref" and len(recs) > len(shown) else None))
        related.sort(key=lambda g: (not g["lines"], -g["cond"], -g["n"]))
        # what this record mentions (bank transfer -> invoices, e-mail -> customers)
        mentions = []
        for row in store.outrefs(rid):
            if row["kind"] == "mention" and row["to_id"] in rt.by_id:
                how = row["how"]
                if how == CONFIRMED:
                    how = "von Ihnen zugeordnet"  # a person said so – the amount may not even fit
                elif how == BY_AMOUNT:
                    how = "ohne Nummer – Betrag und Zahler stimmen"
                mentions.append(dict(rid=row["to_id"], spec=rt.spec(row["type"]), how=how))
        notes = store.q("SELECT * FROM notes WHERE record_id=? ORDER BY id DESC", (rid,))
        changes = []
        attr_names = {a["id"]: a for a in spec["attrs"]}
        for ch in store.changes(rid)[:60]:
            a = attr_names.get(ch["attr"])
            new = loads(ch["new"]) if ch["new"] else None
            changes.append(dict(id=ch["id"], ts=ch["ts"], actor=ch["actor"], kind=ch["kind"], attr=a, note=ch["note"],
                                old=loads(ch["old"]) if ch["old"] else None, new=new,
                                source=sources.get(ch["source_id"]),
                                undoable=bool(a and ch["kind"] in ("edit", "auto") and ch["actor"] != "Physarum"
                                              and data.get(a["id"]) == new and ch["note"] != "rückgängig gemacht")))
        src_files = [sources[s] for s in (rec["meta"] or {}).get("src", []) if s in sources]
        lock = ops.lock_state(rt, spec, rec)
        def comes_before(src_tid: str) -> bool:
            """An order names its invoice ("Rechnung" in the order book), but it is not made from it."""
            p = next((x for x in rt.model.get("processes", []) if x["type"] == src_tid), None)
            return bool(p) and any(x.get("type") == spec["id"] for st in p["steps"] for x in [st] + st.get("also", []))
        children = [r for r in rt.model["relations"] if r["dst"] == spec["id"] and r["kind"] == "ref"
                    and rt.spec(r["src"]) and rt.spec(r["src"])["kind"] == "transaction" and not comes_before(r["src"])]
        # two columns naming the customer (who orders, who pays): one button, by the column the process follows
        party_of = {p["type"]: p.get("party") for p in rt.model.get("processes", [])}
        children = list({r["src"]: r for r in sorted(children, key=lambda r: r["attr"] == party_of.get(r["src"]))}.values())
        offered = {r["src"] for r in children}
        for g in related:  # and none again above each list
            g["add"] = g["kind"] == "ref" and g["spec"]["kind"] != "line" and g["spec"]["id"] not in offered
            if g["add"]:
                offered.add(g["spec"]["id"])
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
        pay = rt.ledger.get(rid)
        alloc = [dict(rid=i, amount=a) for i, a in bank_allocations(rt.ledger).get(rid, [])]
        assign = _assign_candidates(rid, spec, data, alloc)
        inv = billing.is_invoice(spec)
        draft = inv and billing.is_draft(rec)
        meta = rec["meta"] or {}
        doc = billing.document(rt, rec) if inv else None
        conflicts = []
        for aid, (v, src_name) in (meta.get("conflicts") or {}).items():
            a = attr_names.get(aid)
            if a:
                conflicts.append(dict(attr=a, value=v, source=src_name))
        imported = rec.get("origin") == "import" or any(c["kind"] == "import" for c in changes)
        issue_ctx = {}
        if inv and draft:
            dv = billing.delivery_of(rt, spec, rec)
            pos_now = billing.draft_positions(rt, rec)
            t_now = billing.tax_by_lines(pos_now) if pos_now else None
            from ..einvoice import xrechnung_problems
            issue_ctx = dict(
                problems=[p for p in billing.issue_problems(rt, spec, rec, extra_ok=True, here_ok=True) if not p.startswith("Leistungsdatum")
                          and not p.startswith("Grund für 0 %")],
                xr_problems=[p for p in xrechnung_problems(dict(doc or {}, number="x", delivery="x"))],
                edit_positions=pos_now, delivery_value=dv.isoformat() if dv else None,
                delivery_hint="aus dem Auftrag" if dv else "bitte angeben",
                zero_rate=bool(t_now and any(abs(g["rate"]) < 1e-9 for g in t_now["groups"])),
                other_invoices=billing.other_invoices(rt, spec, rec), handover=billing.handover(rt, spec))
        effort = _effort(spec, rec)
        owes = _owes(spec, rec) if spec["kind"] == "master" else None
        # one status in the header: where the file's status speaks of payment ("offen", "bezahlt"), the bank has the say
        own_status = rec["data"].get(status_attr) if status_attr else None
        pay_status = rec["data"].get("pay_state") if pay else None
        status_is_payment = bool(pay_status and own_status and fold(str(own_status)) in _PAY_WORDS)
        return dict(rec=rec, spec=spec, facts=facts, timeline=timeline, related=related, mentions=mentions, notes=notes,
                    effort=effort, owes=owes, own_status=own_status, pay_status=pay_status, status_is_payment=status_is_payment,
                    issued_here=bool(meta.get("issued")), incoming=bool(spec.get("incoming")), **issue_ctx,
                    draft_lines=bool(draft and meta.get("positions") is not None),
                    maybe_paid=maybe_paid, pay=pay, alloc=alloc, assign=assign, cash_kinds=CASH_KINDS,
                    caution=[x for g in rt.work() if g["kind"] == "risk" for x in g["items"] if x["rid"] == rid],
                    invoice=inv, draft=draft, doc=doc,
                    missing=billing.missing_for_issue(rt, spec, rec) if draft else [],
                    company_missing=billing.company_missing(store) if inv else [], conflicts=conflicts,
                    storno_of=meta.get("storno_of"), storno_by=meta.get("storno_by"), imported=imported,
                    can_edit=any(not f["attr"].get("virtual") and (not lock or f["attr"]["id"] in lock["editable"])
                                 for f in facts),
                    changes=changes, src_files=src_files, lock=lock, children=children, party=party,
                    money_attr=money_attr, status_attr=rt.attr(spec["id"], status_attr) if status_attr else None,
                    line=line_child(spec), reach=reach)

    _PAY_WORDS = {"offen", "bezahlt", "teilbezahlt", "teilweise bezahlt", "ueberfaellig", "gemahnt", "ueberzahlt",
                  "unbezahlt", "nicht bezahlt", "open", "paid", "unpaid", "overdue", "mahnung", "1. mahnung", "2. mahnung",
                  "zahlungserinnerung", "erinnert", "ausstehend"}

    def _owes(spec: dict, rec: dict) -> list[dict]:
        """What a customer still owes (or what is still to be paid to a supplier), per kind of invoice."""
        out = []
        for p in rt.model.get("processes", []):
            party = p.get("party")
            s2 = rt.spec(p["type"])
            if not party or not s2 or rt.attr(p["type"], party) is None or rt.attr(p["type"], party).get("ref") != spec["id"]:
                continue
            total = late = 0.0
            n = 0
            for r in rt.records.get(p["type"], []):
                if r["data"].get(party) != rec["id"]:
                    continue
                e = rt.ledger.get(r["id"])
                if not e or e["state"] not in ("offen", "teilbezahlt") or e["open"] <= 0.005:
                    continue
                total += e["open"]
                n += 1
                if r["data"].get("pay_state") == "überfällig":
                    late += e["open"]
            if n:
                out.append(dict(type=p["type"], plural=s2["plural"], total=round(total, 2), late=round(late, 2), n=n,
                                incoming=bool(s2.get("incoming")),
                                href=f"/t/{p['type']}?f_{party}={rec['id']}&f_pay_state=offen|überfällig|teilbezahlt"))
        return out

    def _effort(spec: dict, rec: dict) -> dict | None:
        """A budget and the work booked on it (time entries with an amount)."""
        from ..process import _BUDGET_WORDS, _RATE_WORDS
        budget = next((a for a in spec["attrs"] if a["kind"] == "money" and not a.get("hidden") and not a.get("virtual")
                       and set(billing.words(a["name"])) & _BUDGET_WORDS), None)
        b = rec["data"].get(budget["id"]) if budget else None
        if not isinstance(b, (int, float)) or b <= 0:
            return None
        total, n = 0.0, 0
        for frm, attr, kind, _how in rt.backrefs.get(rec["id"], []):
            r2 = rt.by_id.get(frm)
            s2 = rt.spec(r2["type"]) if r2 else None
            if not s2 or kind != "ref" or s2.get("concept") != "zeiteintrag":
                continue
            v = next((r2["data"][a["id"]] for a in s2["attrs"] if a["kind"] == "money" and not a.get("virtual")
                      and not set(billing.words(a["name"])) & _RATE_WORDS and isinstance(r2["data"].get(a["id"]), (int, float))), None)
            if v:
                total += float(v)
                n += 1
        if not n:
            return None
        return dict(total=round(total, 2), budget=b, budget_name=budget["name"], share=round(total / b * 100), n=n)

    def _void(rid: int) -> bool:
        r = rt.by_id.get(rid)
        if not r:
            return True
        meta = r.get("meta") or {}
        e = rt.ledger.get(rid)
        return bool(meta.get("storno_by") or meta.get("storno") or meta.get("storno_of") or (e and e["state"] == "storniert"))

    def build_timeline(proc: dict, rec: dict) -> dict:
        data = rec["data"]
        today = date.today()
        start = as_date(data.get(proc["start"]["attr"]))
        steps = [dict(label=proc["start"]["label"], date=start, done=bool(start), kind="start", usual=None, due=None,
                      late=False, via=None, by_status=False)]
        nxt = None
        due_by_step = {d["step"]: d for d in proc["deadlines"] if d.get("step")}
        for st in proc["steps"]:
            when = None
            via = None
            for s in [st] + st.get("also", []):
                if s["source"] == "own":
                    d = event_date(data.get(s["attr"]), start)
                    if d and (when is None or d < when):
                        when, via = d, None
                else:
                    if s["rel_kind"] == "own_ref":
                        srcs = [data[s["rel_attr"]]] if isinstance(data.get(s["rel_attr"]), int) else []
                    elif s["rel_kind"] == "mention":
                        srcs = rt.mentions.get(s["rel_attr"], {}).get(rec["id"], [])
                    else:
                        srcs = [c["id"] for c in rt.records.get(s["type"], []) if c["data"].get(s["rel_attr"]) == rec["id"]]
                    for x in srcs:
                        if _void(x):
                            continue  # a cancelled invoice did not invoice the order
                        d = as_date(rt.by_id.get(x, {}).get("data", {}).get(s["attr"]))
                        if d and (when is None or d < when):
                            when, via = d, x
            dl = due_by_step.get(st["id"])
            due = as_date(data.get(dl["attr"])) if dl else None
            due_how = None
            e = rt.ledger.get(rec["id"])
            if dl and not due and e and e.get("due_attr") == dl["attr"]:
                due, due_how = e["due"], e["due_how"]  # the book has no due date: reckoned, and said so
            sattr = (proc.get("status") or {}).get("attr")
            by_status = not when and fold(st["label"]) != "bezahlt" and sattr and lexicon.status_reaches(st["label"], data.get(sattr))
            late = (not when) and not by_status and due and due < today
            item = dict(label=st["label"], date=when, done=bool(when) or bool(by_status), via=via, due=due, late=late, step=st,
                        usual=st.get("median_days"), by_status=by_status, due_how=due_how)
            if (st.get("share") or 1) < 0.5 and not item["done"] and not due:
                continue  # most cases go without it (a ticket, a supplier's invoice): no step to wait for
            if not when and not by_status and nxt is None:
                nxt = item
                own = next((s for s in [st] + st.get("also", []) if s["source"] == "own"), None)
                child = next((s for s in [st] + st.get("also", []) if s["source"] == "child"), None)
                if own:
                    item["action"] = dict(kind="set_date", attr=own["attr"], label=f"Als {st['label']} markieren"
                                          if fold(st["label"]) in ("bezahlt", "geliefert", "versendet", "eingegangen",
                                                                   "erledigt", "berechnet") else f"{st['name']} eintragen")
                elif child and child.get("rel_kind") in ("ref", "own_ref"):
                    item["action"] = dict(kind="create_child", type=child["type"],
                                          attr=child["rel_attr"] if child["rel_kind"] == "ref" else None,
                                          label=f"{rt.spec(child['type'])['name']} anlegen")
            steps.append(item)
        status = proc.get("status")
        negative = status and str(data.get(status["attr"])) in (status.get("negative") or [])
        return dict(steps=steps, next=nxt, negative=negative)

    def record_update(request: Request, form):
        rid = int(request.path_params["rid"])
        raw = typed_refs({k[2:]: v for k, v in form.items() if k.startswith("a_")}, form, "t_")
        try:
            ops.update(rt, rid, raw, actor(request))
        except ops.OpError as e:
            rt.ensure()
            rec = store.record(rid)
            if not rec:
                return not_found(request)
            spec = rt.spec(rec["type"])
            ctx = record_context(rec, spec, request)
            ctx["error"] = str(e)
            return page(request, "record.html", ctx, 400)
        return RedirectResponse(f"/r/{rid}?gespeichert=1", 303)

    def record_step(request: Request, form):
        rid = int(request.path_params["rid"])
        try:
            changed = ops.set_step(rt, rid, form.get("attr"), form.get("date"), actor(request))
        except ops.OpError as e:
            return JSONResponse(dict(error=str(e)))
        rt.ensure()
        names = [rt.attr(rt.by_id[rid]["type"], a)["name"] for a in changed if rid in rt.by_id]
        when = form.get("date") or date.today().isoformat()
        return JSONResponse(dict(reload=True, toast=("Eingetragen: " + ", ".join(names) + f" ({display(when, 'date')})")
                                 if names else "Gespeichert",
                                 undo=dict(url=f"/r/{rid}/rueckgaengig", body=dict(attrs=",".join(changed)))))

    def record_payment(request: Request, form):
        """Cash, a cheque, an offset, a part payment: what the bank statement does not show."""
        rid = int(request.path_params["rid"])
        try:
            left = ops.record_payment(rt, rid, form.get("amount") or "", form.get("date") or None,
                                      form.get("how") or "bar", actor(request))
        except ops.OpError as e:
            return JSONResponse(dict(error=str(e)))
        rec = store.record(rid)
        pid = max(m["id"] for m in (rec["meta"] or {}).get("cash") or [{"id": 0}])
        return JSONResponse(dict(reload=True, toast="Eingetragen – " + ("damit bezahlt." if left <= 0.005 else
                                                                         f"noch offen {views.money(left)}."),
                                 undo=dict(url=f"/r/{rid}/zahlung-entfernen", body=dict(id=str(pid)))))

    def remove_payment(request: Request, form):
        rid = int(request.path_params["rid"])
        try:
            ops.remove_payment(rt, rid, int(form.get("id") or 0), actor(request))
        except (ops.OpError, ValueError) as e:
            return JSONResponse(dict(error=str(e)))
        return JSONResponse(dict(reload=True, toast="Zahlung zurückgenommen."))

    def record_assign(request: Request, form):
        """A bank line the owner knows better: it pays this invoice."""
        rid = int(request.path_params["rid"])
        try:
            inv = int(form.get("invoice") or 0)
            grow_needed = ops.assign_payment(rt, rid, inv, actor(request))
        except (ops.OpError, ValueError) as e:
            return JSONResponse(dict(error=str(e) if isinstance(e, ops.OpError) else "Bitte eine Rechnung wählen"))
        if grow_needed:
            jid = jobs.start("assign", lambda progress: regrow(store, progress, actor(request)), next_url=f"/r/{rid}")
            return JSONResponse(dict(job=jid))
        rt.ensure()
        state = (rt.ledger.get(inv) or {}).get("state")
        return JSONResponse(dict(reload=True, toast=f"Zugeordnet: {rt.title(inv)}" + (f" – {state}." if state else "."),
                                 undo=dict(url=f"/r/{inv}/zahlung-loesen", body=dict(bank=str(rid)))))

    def record_follow_up(request: Request, form):
        rid = int(request.path_params["rid"])
        try:
            changed = ops.follow_up(rt, rid, form.get("outcome") or "", actor(request))
        except ops.OpError as e:
            return JSONResponse(dict(error=str(e)))
        rt.ensure()
        rec = rt.by_id.get(rid)
        if not changed or not rec:
            return JSONResponse(dict(reload=True, toast="Gespeichert"))
        a = rt.attr(rec["type"], changed[0])
        toast = (f"Wieder vorlegen am {display(rec['data'].get(changed[0]), 'date')}" if form.get("outcome") == "later"
                 else f"{a['name']}: {rec['data'].get(changed[0])}")
        return JSONResponse(dict(reload=True, toast=toast,
                                 undo=dict(url=f"/r/{rid}/rueckgaengig", body=dict(attrs=",".join(changed)))))

    def record_undo(request: Request, form):
        rid = int(request.path_params["rid"])
        attrs = [a for a in (form.get("attrs") or "").split(",") if a]
        try:
            if form.get("change"):
                ops.revert_change(rt, rid, int(form.get("change")), actor(request))
            else:
                ops.revert(rt, rid, attrs, actor(request))
        except (ops.OpError, ValueError) as e:
            return JSONResponse(dict(error=str(e)))
        return JSONResponse(dict(reload=True, toast="Rückgängig gemacht."))

    def render_invoice(doc: dict, rec: dict) -> str:
        """The printed invoice exactly as it is archived when issued."""
        return templates.get_template("invoice.html").render(d=doc, rec=rec, company_missing=[], archived=None,
                                                              printed=views.today_text())

    def record_issue(request: Request, form):
        rid = int(request.path_params["rid"])
        try:
            number = billing.issue(rt, rid, actor(request), delivery=form.get("leistung") or None,
                                   delivery_end=form.get("leistung_bis") or None,
                                   tax_note=form.get("steuerhinweis") or None, extra_ok=bool(form.get("zusatz")),
                                   render=render_invoice, here_ok=bool(form.get("hier")))
        except billing.BillingError as e:
            return JSONResponse(dict(error=str(e)))
        return JSONResponse(dict(reload=True, toast=f"Ausgestellt als {number}, festgeschrieben und archiviert."))

    def record_unpay(request: Request, form):
        """A transfer without a number was given to this invoice by its amount – the owner knows better."""
        from ..payments import BY_AMOUNT, CONFIRMED
        from ..questions import _stable_ident
        rid = int(request.path_params["rid"])
        bank = int(form.get("bank") or 0)
        rt.ensure()
        inv, row = rt.by_id.get(rid), rt.by_id.get(bank)
        if not inv or not row:
            return JSONResponse(dict(error="Diese Zahlung gibt es nicht mehr."), status_code=404)
        with store.tx() as c:
            gone = c.execute("DELETE FROM refs WHERE from_id=? AND to_id=? AND kind='mention' AND how IN (?, ?)",
                             (bank, rid, BY_AMOUNT, CONFIRMED)).rowcount
            bid, iid = _stable_ident(c, row["type"], bank), _stable_ident(c, inv["type"], rid)
            if not gone or not bid or not iid:
                return JSONResponse(dict(error="Diese Zahlung ist über eine Nummer zugeordnet, nicht über den Betrag."))
            store.decide("payment_match", f"{row['type']}|{bid}|{inv['type']}|{iid}", "no", actor(request), c=c,
                         note="Zuordnung an der Rechnung gelöst")
            rt.bump(c)
        return JSONResponse(dict(reload=True, toast="Gelöst – die Überweisung gehört zu keiner Rechnung, die Rechnung ist wieder offen."))

    def correction_seen(request: Request, form):
        """The owner has seen that an invoice of the other program was corrected after it was issued."""
        rid = int(request.path_params["rid"])
        with store.tx() as c:
            row = c.execute("SELECT meta FROM records WHERE id=?", (rid,)).fetchone()
            meta = loads(row["meta"]) if row else None
            if not meta or not meta.get("corrected"):
                return JSONResponse(dict(error="Hier gibt es keine Korrektur zu bestätigen."), status_code=404)
            meta.pop("corrected")
            c.execute("UPDATE records SET meta=? WHERE id=?", (dumps(meta), rid))
            c.execute("INSERT INTO changes(record_id,ts,actor,kind,note) VALUES(?,?,?,?,?)",
                      (rid, now_iso(), actor(request), "note", "Korrektur nach der Ausstellung zur Kenntnis genommen"))
            rt.bump(c)
        return JSONResponse(dict(reload=True, toast="Vermerkt."))

    def record_positions(request: Request, form):
        rid = int(request.path_params["rid"])
        rows = defaultdict(dict)
        for k, v in form.items():
            if k.startswith("pos_"):
                _, n, field = k.split("_", 2)
                if n.isdigit():
                    rows[int(n)][field] = v
        try:
            billing.set_positions(rt, rid, [rows[n] for n in sorted(rows)], actor(request))
        except billing.BillingError as e:
            return JSONResponse(dict(error=str(e)))
        return JSONResponse(dict(reload=True, toast="Positionen gespeichert – Summen neu berechnet."))

    def record_unhide(request: Request):
        rid = int(request.path_params["rid"])
        try:
            ops.unhide(rt, rid, actor(request))
        except ops.OpError as e:
            return JSONResponse(dict(error=str(e)), status_code=404)
        return JSONResponse(dict(next=f"/r/{rid}", toast="Wieder eingeblendet."))

    def record_xrechnung(request: Request):
        rt.ensure()
        rid = int(request.path_params["rid"])
        rec = store.record(rid)
        spec = rt.spec(rec["type"]) if rec else None
        if not rec or not billing.is_invoice(spec) or billing.is_draft(rec):
            return page(request, "message.html", dict(title="Keine ausgestellte Rechnung",
                                                      text="Eine E-Rechnung gibt es nur für ausgestellte Rechnungen."), 404)
        arch = billing.archive_get(store, rid, "xml")
        if not arch:
            from ..einvoice import to_xrechnung, xrechnung_problems
            if not (rec.get("meta") or {}).get("issued"):
                return page(request, "message.html", dict(
                    title="Abschrift – keine E-Rechnung",
                    text="Diese Rechnung wurde in einem anderen Programm erstellt. Die E-Rechnung dazu kommt aus jenem "
                         "Programm; Physarum zeigt nur eine Abschrift der Zahlen."), 404)
            doc = billing.document(rt, rec)
            probs = xrechnung_problems(doc)
            if probs:
                return page(request, "message.html", dict(
                    title="Für die E-Rechnung fehlt noch etwas",
                    text="Die XRechnung verlangt: " + "; ".join(probs) + ". Diese Rechnung wurde ohne diese Angaben "
                         "ausgestellt und bleibt so, wie sie ist – als gedruckte bzw. PDF-Rechnung ist sie gültig. Damit "
                         "künftige Rechnungen auch als E-Rechnung gehen, ergänzen Sie die Angaben vor dem Ausstellen "
                         "(Ihre Firmendaten bzw. beim Kunden)."), 409)
            with store.tx() as c:
                billing.archive_put(c, rid, "xml", f"XRechnung_{doc['number']}.xml".replace("/", "-"),
                                    to_xrechnung(doc).encode("utf-8"))
            arch = billing.archive_get(store, rid, "xml")
        return Response(arch["content"], media_type="application/xml",
                        headers={"Content-Disposition": _attachment(arch["name"])})

    def record_note(request: Request, form):
        rid = int(request.path_params["rid"])
        if not store.record(rid):
            return not_found(request)
        ops.add_note(rt, rid, form.get("text"), actor(request))
        return RedirectResponse(f"/r/{rid}#notizen", 303)

    def record_storno(request: Request, form):
        rid = int(request.path_params["rid"])
        try:
            nid = ops.storno(rt, rid, form.get("reason") or "", actor(request), render=render_invoice)
        except ops.OpError as e:
            return JSONResponse(dict(error=str(e)))
        if nid:
            return JSONResponse(dict(next=f"/r/{nid}", toast="Storniert. Die Stornorechnung ist angelegt."))
        rt.ensure()
        if rid not in rt.by_id:
            return JSONResponse(dict(next="/", toast="Entwurf verworfen."))
        return JSONResponse(dict(reload=True, toast="Storniert. Der Vorgang bleibt im Protokoll erhalten."))

    def record_delete(request: Request, form):
        rid = int(request.path_params["rid"])
        rec = store.record(rid)
        try:
            ops.delete(rt, rid, actor(request), reason=form.get("reason"))
        except ops.OpError as e:
            return JSONResponse(dict(error=str(e)))
        return JSONResponse(dict(toast="Ausgeblendet (lässt sich wieder einblenden)." if form.get("reason")
                                 else "Gelöscht (bleibt im Protokoll nachvollziehbar).", reload=False,
                                 next=f"/t/{rec['type']}"))

    def not_found(request: Request):
        return page(request, "message.html", dict(title="Nicht gefunden", text="Dieser Datensatz existiert nicht (mehr)."), 404)

    def record_print(request: Request):
        rt.ensure()
        rid = int(request.path_params["rid"])
        rec = store.record(rid)
        if not rec or rec["deleted"] or not rt.spec(rec["type"]):
            return not_found(request)
        spec = rt.spec(rec["type"])
        rec["data"] = rt.by_id.get(rid, rec)["data"]
        ctx = record_context(rec, spec, request)
        if billing.is_invoice(spec):
            arch = billing.archive_get(store, rid, "html")
            if arch:
                # the original as it went out; a reprint says so
                html = arch["content"].decode("utf-8")
                stamp = (f'<div class="copy-stamp">Kopie · Original archiviert am {display(arch["created_at"], "datetime")} '
                         f'· SHA-256 {arch["sha256"][:16]}…</div>')
                html = html.replace("<body>", "<body>" + stamp, 1)
                return Response(html, media_type="text/html; charset=utf-8")
            miss = billing.company_missing(store)
            if miss and billing.is_draft(rec):
                pass  # a draft preview may show gaps
            return templates.TemplateResponse(request, "invoice.html", dict(ctx, request=request, d=ctx["doc"],
                                                                            printed=views.today_text()))
        return templates.TemplateResponse(request, "print.html", dict(ctx, request=request, company=company_name(),
                                                                      printed=views.today_text()))

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

    def record_reminder(request: Request):
        """The old door to a reminder: it opens the customer's letter with everything overdue."""
        rt.ensure()
        rid = int(request.path_params["rid"])
        rec = rt.by_id.get(rid)
        proc = next((p for p in rt.model.get("processes", []) if rec and p["type"] == rec["type"]), None)
        pid = rec["data"].get(proc["party"]) if rec and proc and proc.get("party") else None
        if not isinstance(pid, int):
            return page(request, "message.html", dict(title="Kein Kunde", text="Diese Rechnung hat keinen Kunden, an den man schreiben könnte."), 404)
        return RedirectResponse(f"/mahnung/{pid}?typ={rec['type']}", 303)

    def reminder_letter(request: Request):
        """One letter per customer: every overdue invoice, the level each has reached, the bank details."""
        from .. import dunning
        rt.ensure()
        pid = int(request.path_params["pid"])
        tid = request.query_params.get("typ") or ""
        items = dunning.overdue_of(rt, pid, tid)
        cust = rt.by_id.get(pid)
        if not cust or not rt.spec(tid):
            return page(request, "message.html", dict(title="Nicht gefunden", text="Kunde oder Liste gibt es nicht."), 404)
        send = [x for x in items if not x["complaint"] and not x["maybe_paid"]]
        held = [x for x in items if x["complaint"] or x["maybe_paid"]]
        waiting = [x for x in send if x["wait"]]
        send = [x for x in send if not x["wait"]]
        sent = None
        if waiting and not send:  # the letter that went out, as it went out – the next one waits for its day
            send, waiting = waiting, []
            sent = dict(on=max(x["sent"] for x in send), until=max(x["wait"] for x in send))
        level = max((x["level"] for x in send), default=1)
        addr = billing.recipient(rt, pid)
        lack = [n for k, n in (("street", "Straße"), ("zip", "PLZ"), ("city", "Ort")) if not addr.get(k)]
        # what the customer wrote lately, about these invoices or at all: read before a letter goes out
        talk = {}
        for frm, attr, kind, how in rt.backrefs.get(pid, []) + [b for x in items for b in rt.backrefs.get(x["rid"], [])]:
            d = rt.by_id.get(frm)
            day = as_date(str(d["data"].get("doc_date") or "")[:10]) if d and d["type"] == "doc" else None
            if day and 0 <= (date.today() - day).days <= 90:
                talk[frm] = dict(rid=frm, title=rt.title(frm), day=day)
        return templates.TemplateResponse(request, "reminder.html", dict(
            request=request, items=send, held=held, waiting=waiting, sent=sent, cust=cust, addr=addr, lack=lack,
            level=level, title_text=dunning.LEVELS[level], company=billing.company(store),
            company_missing=billing.company_missing(store), total=round(sum(x["open"] for x in send), 2), tid=tid,
            pid=pid, today=views.today_text(sent["on"] if sent else None), spec=rt.spec(tid),
            talk=sorted(talk.values(), key=lambda x: x["day"], reverse=True)[:5]))

    def reminder_sent(request: Request, form):
        from .. import dunning
        pid = int(request.path_params["pid"])
        n = dunning.record_sent(rt, pid, form.get("typ") or "", actor(request))
        if not n:
            return JSONResponse(dict(error="Nichts zu protokollieren – keine überfällige Rechnung ohne Reklamation, "
                                           "deren letzter Brief schon abgelaufen ist."))
        return JSONResponse(dict(reload=True, toast=f"Versand protokolliert: {n} {'Rechnung' if n == 1 else 'Rechnungen'}, "
                                                     f"jede mit Eintrag im Verlauf."))

    # --- the firm itself ------------------------------------------------------------------------------------
    def company_page(request: Request):
        rt.ensure()
        cur = billing.company(store)
        guess = billing.guess_company(rt) if rt.model else {}
        values = {k: cur.get(k) or guess.get(k) or "" for k, _ in billing.COMPANY_FIELDS}
        values["kleinunternehmer"] = bool(cur.get("kleinunternehmer"))
        return page(request, "company.html", dict(fields=billing.COMPANY_FIELDS, values=values, guessed=
                                                  {k for k in guess if not cur.get(k)},
                                                  back=local_path(request.query_params.get("zurueck"), ""),
                                                  missing=[x for x in (request.query_params.get("fehlt") or "").split(",") if x]))

    def company_save(request: Request, form):
        data = {k: (form.get(k) or "").strip() for k, _ in billing.COMPANY_FIELDS}
        if data.get("iban"):
            data["iban"] = data["iban"].replace(" ", "").upper()
        data["kleinunternehmer"] = bool(form.get("kleinunternehmer"))
        old = billing.company(store)
        ts = now_iso()
        with store.tx() as c:
            store.kv_set("company_profile", data, c)
            # every change of the firm's own data is in the log with old and new value (the IBAN above all)
            labels = dict(billing.COMPANY_FIELDS, kleinunternehmer="Kleinunternehmer (§ 19 UStG)")
            for k, label in labels.items():
                if (old.get(k) or "") != (data.get(k) or ""):
                    c.execute("INSERT INTO changes(record_id,ts,actor,kind,attr,old,new,note) VALUES(?,?,?,?,?,?,?,?)",
                              (0, ts, actor(request), "company", k, dumps(old.get(k)), dumps(data.get(k)),
                               f"Firmendaten: {label} geändert"))
        return RedirectResponse(local_path(form.get("back")), 303)

    def api_derive(request: Request):
        """What a new record takes over from the record it refers to (an invoice from its order)."""
        rt.ensure()
        spec = rt.spec(request.query_params.get("typ") or "")
        aid = request.query_params.get("attr")
        try:
            rid = int(request.query_params.get("id") or 0)
        except ValueError:
            rid = 0
        if not spec or not aid or rid not in rt.by_id:
            return JSONResponse(dict(values={}, why=[]))
        vals, why = billing.derive(rt, spec, {aid: rid})
        out = {}
        for k, v in vals.items():
            a = rt.attr(spec["id"], k)
            if not a:
                continue
            out[k] = dict(id=v, title=rt.title(v)) if a["kind"] == "ref" and isinstance(v, int) else views.input_value(a, v)
        return JSONResponse(dict(values=out, why=why))

    # --- forms -------------------------------------------------------------------------------------------
    def new_form(request: Request):
        rt.ensure()
        tid = request.path_params["tid"]
        spec = rt.spec(tid)
        if not spec:
            return page(request, "message.html", dict(title="Nicht gefunden", text="Diese Art gibt es nicht."), 404)
        data = ops.prefill(rt, spec)
        why = []
        case = rt.by_id.get(int(request.query_params["aus"])) if request.query_params.get("aus", "").isdigit() else None
        if case and billing.is_invoice(spec) and billing.billed_by_own_ref(rt, case, spec):
            vals, _lines, why = billing.from_case(rt, spec, case)  # the order names its invoice: from the order
            data.update(vals)
        else:
            case = None
        for k, v in request.query_params.items():
            if k.startswith("a_"):
                data[k[2:]] = int(v) if v.isdigit() else v
        if any(k.startswith("a_") for k in request.query_params):
            vals, why = billing.derive(rt, spec, data)
            for k, v in vals.items():
                if not request.query_params.get("a_" + k):
                    data[k] = v
            ops.apply_formulas(rt, spec, data, set(data))
        hints, readonly = {}, set()
        if billing.is_invoice(spec):
            data.pop(spec.get("key"), None)  # the number comes when it is issued
            due = billing.usual_due(rt, spec, data)
            if due:
                data[due["attr"]] = due["value"]
                why.append(due["why"])
                hints[due["attr"]] = due["hint"]
            if any("Steuersätzen" in w for w in why):
                # the amounts are the order's lines with their own VAT rates: no learned formula overrides them
                readonly = {a["id"] for a in spec["attrs"] if a["kind"] == "money"}
        ctx = form_context(spec, data, why=why)
        ctx["hints"] = hints
        ctx["readonly"] = readonly
        ctx["case"] = case["id"] if case else None
        if readonly:
            ctx["formulas"] = [f for f in ctx["formulas"] if f["attr"] not in readonly]
        return page(request, "form.html", ctx)

    def form_context(spec: dict, data: dict, error: str | None = None, lines_in: list | None = None,
                     why: list | None = None) -> dict:
        fields = [a for a in spec["attrs"] if not a.get("hidden") and not a.get("virtual")]
        if billing.is_invoice(spec):
            fields = [a for a in fields if a["id"] != spec.get("key")]  # the number comes when it is issued
        # what happens later in the process (paid on, delivered on, status) is not asked when creating
        proc = next((p for p in rt.model.get("processes", []) if p["type"] == spec["id"]), None)
        later_ids = set()
        if proc:
            for st in proc["steps"]:
                for x in [st] + st.get("also", []):
                    if x.get("source") == "own":
                        later_ids.add(x["attr"])
            if proc.get("status"):
                later_ids.add(proc["status"]["attr"])
        later = [a for a in fields if a["id"] in later_ids]
        fields = [a for a in fields if a["id"] not in later_ids]
        fields.sort(key=lambda a: (-(a.get("salience") or 0)))
        main = [a for a in fields if (a.get("fill") or 0) >= 0.25 or a["id"] in (spec.get("key"), spec.get("title"))]
        more = [a for a in fields if a not in main]
        order = {a["id"]: i for i, a in enumerate(spec["attrs"])}
        main.sort(key=lambda a: order[a["id"]])
        more.sort(key=lambda a: order[a["id"]])
        later.sort(key=lambda a: order[a["id"]])
        line = line_child(spec)
        lcols, lformulas, ltotal = [], [], None
        if line:
            lspec = line["spec"]
            lcols = [a for a in lspec["attrs"] if not a.get("hidden") and a["id"] != line["rel"]["attr"] and not a.get("virtual")]
            lformulas = [f for f in lspec.get("formulas") or [] if f["op"] != "sum_children"]
            ltotal = next((a["id"] for a in lcols if a["kind"] == "money" and any(t in fold(a["name"]) for t in ("gesamt", "summe", "betrag"))), None) \
                or next((a["id"] for a in reversed(lcols) if a["kind"] == "money"), None)
        computed_targets = {f["attr"] for f in spec.get("formulas") or []}
        party = next((a for a in main if a["kind"] == "ref"), None)
        return dict(spec=spec, data=data, main=main, more=more, later=later, error=error, line=line, lcols=lcols, why=why or [],
                    draft=billing.is_invoice(spec),
                    formulas=[f for f in spec.get("formulas") or [] if f["op"] != "sum_children"], lformulas=lformulas,
                    ltotal=ltotal, computed=computed_targets, lines_in=lines_in or [], party=party,
                    options=enum_options(spec), loptions=enum_options(line["spec"]) if line else {})

    def enum_options(spec: dict) -> dict:
        out = {}
        for a in spec["attrs"]:
            if a.get("enum"):
                out[a["id"]] = a["enum"]
        return out

    def new_submit(request: Request, form):
        rt.ensure()
        tid = request.path_params["tid"]
        spec = rt.spec(tid)
        if not spec:
            return page(request, "message.html", dict(title="Nicht gefunden", text="Diese Art gibt es nicht."), 404)
        raw = typed_refs({k[2:]: v for k, v in form.items() if k.startswith("a_")}, form, "t_")
        lines = defaultdict(dict)
        for k, v in form.items():
            if k.startswith("l_"):
                _, n, aid = k.split("_", 2)
                lines[int(n)][aid] = v
        for k, v in form.items():
            if k.startswith("lt_") and v:
                _, n, aid = k.split("_", 2)
                if not lines[int(n)].get(aid):
                    lines[int(n)][aid] = v
        line = line_child(spec)
        case = rt.by_id.get(int(form["aus"])) if (form.get("aus") or "").isdigit() else None
        try:
            rid = ops.create(rt, tid, raw, actor(request), [lines[n] for n in sorted(lines)] if line else None,
                             line["spec"]["id"] if line else None)
            if case and billing.is_invoice(spec) and billing.billed_by_own_ref(rt, case, spec):
                billing.link_case(rt, rid, case["id"], actor(request))
        except ops.OpError as e:
            shown = {k: (int(v) if isinstance(v, str) and v.isdigit() and int(v) in rt.by_id else v) for k, v in raw.items()}
            ctx = form_context(spec, shown, str(e), [lines[n] for n in sorted(lines)])
            ctx["case"] = case["id"] if case else None
            return page(request, "form.html", ctx, 400)
        except Exception as e:  # noqa: BLE001 - never lose what was typed
            traceback.print_exc()
            ctx = form_context(spec, {k: v for k, v in raw.items()}, f"Das hat nicht geklappt ({type(e).__name__}). "
                                                                     "Ihre Eingaben sind noch da.",
                               [lines[n] for n in sorted(lines)])
            return page(request, "form.html", ctx, 400)
        return RedirectResponse(f"/r/{rid}?neu=1", 303)

    def typed_refs(raw: dict, form, prefix: str) -> dict:
        """A name typed into a reference field without picking it from the list still counts."""
        for k, v in form.items():
            if k.startswith(prefix) and (v or "").strip():
                aid = k[len(prefix):]
                if not (raw.get(aid) or "").strip():
                    raw[aid] = v.strip()
        return raw

    # --- api for forms --------------------------------------------------------------------------------------
    def api_search(request: Request):
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

    def api_record(request: Request):
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

    def api_like_last(request: Request):
        rt.ensure()
        tid = request.query_params.get("typ")
        party = request.query_params.get("partei") or ""
        party = int(party) if party.isdigit() else 0
        spec = rt.spec(tid)
        if not spec:
            return JSONResponse(dict(lines=[]))
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
    def search_page(request: Request):
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
            qf = fold(q)
            words = qf.split()
            for tid, recs in by_t.items():
                spec = rt.spec(tid)
                default_order(spec, recs)

                # the thing itself first ("RE-2026-0311" → the invoice, then the bank line and the mail naming it),
                # then what carries the words in its own name, then what only points at it
                def rank(r):
                    t = fold(rt.title(r["id"]))
                    if qf in (fold(str(r["data"].get(spec.get("key")) or "")), t):
                        return 0
                    return 1 if all(w in t for w in words) else 2
                ranks = {r["id"]: rank(r) for r in recs}
                recs.sort(key=lambda r: ranks[r["id"]])  # stable: the date order stays within each rank
                groups.append(dict(spec=spec, recs=recs[:25], n=len(recs), cols=views.list_columns(spec, 4),
                                   best=min(ranks.values())))
            groups.sort(key=lambda g: (g["best"], g["spec"]["kind"] != "master", g["spec"]["kind"] == "line",
                                       -(g["spec"].get("salience") or 0)))
        return page(request, "search.html", dict(q=q, groups=groups))

    # --- questions -----------------------------------------------------------------------------------------------
    def questions_page(request: Request):
        rt.ensure()
        qs = open_questions(store)
        answered = store.q("SELECT * FROM questions WHERE status='answered' ORDER BY answered_at DESC LIMIT 60")
        return page(request, "questions.html", dict(questions=qs, consequences=CONSEQUENCES,
                                                    answered=[dict(r, payload=loads(r["payload"]), answer=loads(r["answer"]))
                                                              for r in answered]))

    def question_answer(request: Request, form):
        qid = int(request.path_params["qid"])
        value = form.get("value")
        if value == "reopen":
            from ..questions import reopen
            reopen(store, qid)
            return JSONResponse(dict(reload=True, toast="Die Frage ist wieder offen."))
        q = store.q1("SELECT status, payload, kind FROM questions WHERE id=?", (qid,))
        options = {str(o[0]) for o in ((loads(q["payload"]) or {}).get("options") or [])} if q else set()
        if not q or not value or (options and value not in options | {"later", "unknown"}):
            return JSONResponse(dict(error="Diese Antwort passt nicht zur Frage."), status_code=400)
        kind, payload = q["kind"], loads(q["payload"]) or {}
        res = answer_question(store, qid, value, actor(request))
        if res.get("regrow"):
            jid = jobs.start("answer", lambda progress: regrow(store, progress, actor(request)),
                             next_url=local_path(form.get("back"), "/fragen"))
            return JSONResponse(dict(job=jid))
        rt.bump()
        msg = {"later": "Ich frage morgen noch einmal.", "unknown": "In Ordnung, ich lasse es, wie es ist."}.get(value, "Danke, gemerkt.")
        if res.get("merged"):
            msg = "Zusammengeführt. Der Verlauf beider Datensätze bleibt erhalten."
        if kind == "payment_match" and value == "yes":
            rt.ensure()
            invs = (payload.get("records") or [])[1:]
            states = [f"{rt.title(i)}: {rt.ledger[i]['state']}" for i in invs if i in rt.ledger]
            msg = "Zugeordnet" + (f" – {', '.join(states)}." if states else ".")
            return JSONResponse(dict(toast=msg, reload=True))
        return JSONResponse(dict(toast=msg))

    def payment_source(request: Request, form):
        """The owner accepts a list that came by mail as a source of payments (or takes it back)."""
        sid = int(request.path_params["sid"])
        if not store.q1("SELECT id FROM sources WHERE id=?", (sid,)):
            return JSONResponse(dict(error="Diese Datei gibt es nicht."), status_code=404)
        with store.tx() as c:
            store.decide("payment_source", str(sid), "no" if form.get("undo") else "yes", actor(request), c=c)
        rt.bump()
        return JSONResponse(dict(toast="Wieder nicht gezählt." if form.get("undo") else "Anerkannt – die Zahlungen darin zählen jetzt.",
                                 reload=True, undo=None if form.get("undo") else dict(url=f"/zahlungsquelle/{sid}", body=dict(undo="1"))))

    def mail_done(request: Request, form):
        """A mail that is answered leaves "Heute"; the mail itself stays among the documents."""
        rid = int(request.path_params["rid"])
        with store.tx() as c:
            if form.get("undo"):
                c.execute("DELETE FROM decisions WHERE kind='mail_done' AND subject=?", (str(rid),))
            else:
                store.decide("mail_done", str(rid), "done", actor(request), c=c)
        rt.bump()
        if form.get("undo"):
            return JSONResponse(dict(toast="Wieder offen.", reload=True))
        return JSONResponse(dict(toast="Abgehakt. Die Mail bleibt unter den Dokumenten.", reload=True,
                                 undo=dict(url=f"/post/{rid}/erledigt", body=dict(undo="1"))))

    def record_split(request: Request, form):
        """Undo a join made on a guess ("Wattwurm" is not Wattwurm Reisen GmbH): remembered for good."""
        rid = int(request.path_params["rid"])
        rec = store.q1("SELECT meta FROM records WHERE id=?", (rid,))
        joins = (loads(rec["meta"]) or {}).get("joins") or [] if rec else []
        j = next((x for x in joins if x.get("key") == form.get("key")), None)
        if not j:
            return JSONResponse(dict(error="Diese Zusammenführung gibt es nicht mehr."), status_code=400)
        with store.tx() as c:
            store.decide("same_record", j["key"], "different", actor(request), c=c)
        jid = jobs.start("split", lambda progress: regrow(store, progress, actor(request)), next_url=f"/r/{rid}")
        return JSONResponse(dict(job=jid))

    def rule_toggle(request: Request, form):
        key = form.get("key")
        val = form.get("value")
        if not key:
            return JSONResponse(dict(error="Welche Regel?"), status_code=400)
        with store.tx() as c:
            store.decide("auto", key, val, actor(request), c=c)
        return JSONResponse(dict(toast="Regel eingeschaltet. Sie wirkt ab jetzt bei jeder Eingabe." if val == "on" else "Gut, ich schlage das nicht mehr vor.",
                                 reload=False))

    def accept_payments(request: Request):
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

    # --- organism -------------------------------------------------------------------------------------------
    def organism(request: Request):
        rt.ensure()
        if not rt.model:
            return RedirectResponse("/", 302)
        rt.refresh_network()
        learned = learned_items()
        versions = [dict(v=r["version"], at=r["created_at"], summary=loads(r["summary"]) or {}) for r in store.models()[:20]]
        from ..coverage import coverage
        return page(request, "organism.html", dict(svg=views.organism_svg(rt), learned=learned, versions=versions,
                                                   cov=coverage(rt), hints=hints(store)))

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
            dls = [d["name"] for d in p.get("deadlines", []) if not d.get("step") and d.get("name")]
            if not p["steps"] and not dls:
                continue  # a date alone is no course
            chain = " → ".join([p["start"]["label"]] + [f"{s['label']} (Ø {s['median_days']:.0f} T.)" if s.get("median_days") is not None
                                                        else s["label"] for s in p["steps"]])
            if dls:
                chain += " · Frist: " + ", ".join(dict.fromkeys(dls))
            out.append(dict(kind="Ablauf", text=f"{p['name']}: {chain}", why=f"aus {p['n']} Fällen"))
        return out

    def organism_rename(request: Request, form):
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

    def organism_attr(request: Request, form):
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
        return RedirectResponse(local_path(request.headers.get("referer"), f"/t/{tid}"), 303)

    def organism_relation(request: Request, form):
        key = form.get("key")
        if not key:
            return JSONResponse(dict(error="Welcher Verweis?"), status_code=400)
        with store.tx() as c:
            store.decide("relation", key, "no", actor(request), c=c)
        jid = jobs.start("relation", lambda progress: regrow(store, progress, actor(request)), next_url="/organismus")
        return JSONResponse(dict(job=jid))

    def processes_page(request: Request):
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
        from ..process import value_chains
        chains = [views.chain_view(c) for c in value_chains(rt.model, rt.records, rt.mentions, rt.ledger)]
        return page(request, "processes.html", dict(items=items, chains=chains))

    # --- sources -----------------------------------------------------------------------------------------------
    def sources_page(request: Request):
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
        from ..coverage import coverage
        return page(request, "sources.html", dict(rows=rows, cov=coverage(rt) if rt.model else None))

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

    def source_remove(request: Request):
        sid = int(request.path_params["sid"])
        if not store.q1("SELECT id FROM sources WHERE id=?", (sid,)):
            return JSONResponse(dict(error="Diese Datei gibt es nicht.", ok=False), status_code=404)
        blocked = locked_in_sources(store.descendants(sid))
        if blocked:
            return JSONResponse(dict(error=f"Diese Datei enthält {blocked} ausgestellte Rechnung(en). Belege lassen sich "
                                           "nicht herausnehmen – eine neue Fassung einwerfen ersetzt sie.", ok=False))
        with store.tx() as c:
            store.set_active(sid, False, c)
        jid = jobs.start("remove", lambda progress: regrow(store, progress, actor(request)), next_url="/quellen")
        return JSONResponse(dict(job=jid))

    def source_restore(request: Request):
        sid = int(request.path_params["sid"])
        if not store.q1("SELECT id FROM sources WHERE id=?", (sid,)):
            return JSONResponse(dict(error="Diese Datei gibt es nicht.", ok=False), status_code=404)
        with store.tx() as c:
            store.set_active(sid, True, c)
        jid = jobs.start("restore", lambda progress: regrow(store, progress, actor(request)), next_url="/quellen")
        return JSONResponse(dict(job=jid))

    def source_file(request: Request):
        sid = int(request.path_params["sid"])
        s = store.q1("SELECT * FROM sources WHERE id=?", (sid,))
        p = store.source_path(sid, s["name"]) if s else None
        if not s or not s["active"] or not p.exists():
            return page(request, "message.html", dict(title="Nicht gefunden",
                                                      text="Diese Datei gibt es nicht oder sie wurde herausgenommen."), 404)
        return FileResponse(p, filename=s["name"])

    # --- export -----------------------------------------------------------------------------------------------
    def export_rows(spec: dict, request: Request | None = None) -> tuple[list[str], list[list]]:
        cols = [a for a in spec["attrs"] if not a.get("constant")]
        head = [a["name"] for a in cols]
        rows = []
        recs = filtered(spec, request)[0] if request is not None and request.query_params else rt.records.get(spec["id"], [])
        for r in recs:
            row = []
            raw = (r.get("meta") or {}).get("raw") or {}
            for a in cols:
                v = r["data"].get(a["id"])
                if a["kind"] == "ref":
                    v = rt.title(v) if isinstance(v, int) else (v if v is not None else raw.get(a["id"]))
                row.append(v)
            rows.append(row)
        return head, rows

    def _cell_safe(v):
        """A text that starts like a formula stays text in Excel (no '=HYPERLINK(...)' from a file)."""
        from ..values import parse_number
        if isinstance(v, str) and v[:1] in ("=", "+", "-", "@", "\t", "\r") and parse_number(v) is None:
            return "'" + v
        return v

    def export_csv(request: Request):
        rt.ensure()
        spec = rt.spec(request.path_params["tid"])
        if not spec:
            return PlainTextResponse("Diese Art gibt es nicht.", 404)
        head, rows = export_rows(spec, request)
        buf = io.StringIO()
        w = csv.writer(buf, delimiter=";")
        w.writerow(head)
        for row in rows:
            w.writerow([_cell_safe(views.input_value(a, v)) if v is not None else ""
                        for a, v in zip([a for a in spec["attrs"] if not a.get("constant")], row)])
        return Response(("﻿" + buf.getvalue()).encode("utf-8"), media_type="text/csv",
                        headers={"Content-Disposition": _attachment(f'{spec["plural"]}.csv')})

    def export_xlsx(request: Request):
        import openpyxl

        rt.ensure()
        spec = rt.spec(request.path_params["tid"])
        if not spec:
            return PlainTextResponse("Diese Art gibt es nicht.", 404)
        head, rows = export_rows(spec, request)
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
            for cell in ws[ws.max_row]:
                if isinstance(cell.value, str) and cell.value.startswith("="):
                    cell.data_type = "s"  # text from a file is never a live formula
        buf = io.BytesIO()
        wb.save(buf)
        return Response(buf.getvalue(), media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                        headers={"Content-Disposition": _attachment(f'{spec["plural"]}.xlsx')})

    def export_backup(request: Request):
        store.event("backup", None, dict(by=actor(request)))
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

    # --- for the tax advisor ------------------------------------------------------------------------------
    def _tax_period(params):
        from .. import taxexport
        today = date.today()
        prev = today.replace(day=1) - timedelta(days=1)
        art = params.get("art") or "monat"
        try:
            jahr = int(params.get("jahr") or (prev.year if art == "monat" else today.year))
            nr = int(params.get("nr") or (prev.month if art == "monat" else (today.month - 1) // 3 + 1))
        except ValueError:
            jahr, nr = prev.year, prev.month
        jahr = min(max(jahr, 2000), today.year + 1)
        if art not in ("monat", "quartal", "jahr"):
            art = "monat"
        von, bis, label = taxexport.period(art, jahr, nr)
        return art, jahr, nr, von, bis, label

    def tax_page(request: Request):
        from .. import taxexport
        rt.ensure()
        art, jahr, nr, von, bis, label = _tax_period(request.query_params)
        data = taxexport.collect(rt, von, bis) if rt.model else None
        return page(request, "taxadvisor.html", dict(art=art, jahr=jahr, nr=nr, label=label, data=data,
                                                     cfg=taxexport.settings(store), exports=store.kv_get("tax_exports") or [],
                                                     theirs=taxexport.from_advisor(store) if not store.kv_get("tax_advisor") else {},
                                                     their_accounts=len(taxexport.advisor_accounts(store)),
                                                     years=list(range(date.today().year, date.today().year - 6, -1))))

    def tax_settings(request: Request, form):
        from .. import taxexport
        taxexport.save_settings(store, form)
        from urllib.parse import urlencode
        back = "/steuerberatung?" + urlencode({k: form.get(k) for k in ("art", "nr", "jahr") if form.get(k)})
        return RedirectResponse(back, 303)

    def tax_download(request: Request, form):
        from .. import taxexport
        rt.ensure()
        art, jahr, nr, von, bis, label = _tax_period(form)
        content, data = taxexport.build(rt, von, bis, label, actor(request))
        store.event("tax_export", None, dict(label=label, out=len(data["out"]), inc=len(data["inc"])))
        name = f"Steuerberatung_{label.replace('/', '-')}.zip"
        return Response(content, media_type="application/zip", headers={"Content-Disposition": f'attachment; filename="{name}"'})

    def procedure_doc(request: Request):
        from .. import procedure
        rt.ensure()
        with store.tx():
            pass  # seal what is not sealed yet, then check the whole chain
        chain = store.verify_chain()
        files = store.verify_files()
        srcs = store.sources(active_only=False)
        versions = store.models()
        by_kind = {r["kind"]: r["n"] for r in store.q("SELECT kind, COUNT(*) AS n FROM changes GROUP BY kind")}
        actors = [r["actor"] for r in store.q("SELECT actor, COUNT(*) n FROM changes WHERE actor IS NOT NULL AND actor NOT IN "
                                                "('import', 'Physarum', 'Test') GROUP BY actor ORDER BY n DESC LIMIT 12")]
        kinds = [dict(plural=t["plural"], n=len(rt.records.get(t["id"], []))) for t in (rt.model or {}).get("types", [])
                 if t["kind"] in ("master", "transaction") and rt.records.get(t["id"])]
        kinds.sort(key=lambda k: -k["n"])
        quality = []
        for t in (rt.model or {}).get("types", []):
            for iss in (t.get("numbering") or {}).get("issues", []):
                quality.append(dict(type=t["plural"], text=f"{iss['count']} {'Lücke(n)' if iss['kind'] == 'gap' else 'doppelte Nummer(n)'}"
                                                           + (f" ({iss['year']})" if iss.get("year") else "")))
        issued = store.q1("SELECT COUNT(*) n FROM changes WHERE kind='issue'")["n"]
        store.flush_events()
        last_backup = next((e["ts"] for e in store.q("SELECT ts FROM events WHERE kind='backup' ORDER BY id DESC LIMIT 1")), None)
        return page(request, "procedure.html", dict(decisions=procedure.decisions(rt) if rt.model else [], srcs=srcs,
                                                    versions=versions, by_kind=by_kind, chain=chain, files=files, actors=actors,
                                                    kinds=kinds[:8], quality=quality, issued=issued,
                                                    firm=billing.company(store).get("name"), last_backup=last_backup,
                                                    exports=store.kv_get("tax_exports") or [],
                                                    learned=learned_items() if rt.model else []))

    def set_name(request: Request, form):
        resp = RedirectResponse(local_path(request.headers.get("referer")), 303)
        name = (form.get("name") or "").strip()[:40]
        if name:
            resp.set_cookie("physarum_name", name, max_age=3600 * 24 * 365, samesite="lax")
        else:
            resp.delete_cookie("physarum_name")
        return resp

    def health(request: Request):
        return PlainTextResponse("ok")

    routes = [
        Route("/", home), Route("/gesund", health),
        Route("/einwerfen", upload, methods=["POST"]), Route("/beispiel", demo, methods=["POST"]),
        Route("/beispiel/wachstum", demo_growth, methods=["POST"]),
        Route("/wachsen/{jid:int}", grow_page), Route("/api/job/{jid:int}", job_status),
        Route("/t/{tid}", list_view), Route("/t/{tid}/spalte", formed(pin_column), methods=["POST"]),
        Route("/t/{tid}/neu", new_form), Route("/t/{tid}/neu", formed(new_submit), methods=["POST"]),
        Route("/r/{rid:int}", record_view), Route("/r/{rid:int}", formed(record_update), methods=["POST"]),
        Route("/r/{rid:int}/trennen", formed(record_split), methods=["POST"]),
        Route("/post/{rid:int}/erledigt", formed(mail_done), methods=["POST"]),
        Route("/zahlungsquelle/{sid:int}", formed(payment_source), methods=["POST"]),
        Route("/r/{rid:int}/schritt", formed(record_step), methods=["POST"]),
        Route("/r/{rid:int}/nachfassen", formed(record_follow_up), methods=["POST"]),
        Route("/r/{rid:int}/zahlung", formed(record_payment), methods=["POST"]),
        Route("/r/{rid:int}/zahlung-entfernen", formed(remove_payment), methods=["POST"]),
        Route("/r/{rid:int}/zuordnen", formed(record_assign), methods=["POST"]),
        Route("/r/{rid:int}/notiz", formed(record_note), methods=["POST"]),
        Route("/r/{rid:int}/storno", formed(record_storno), methods=["POST"]),
        Route("/r/{rid:int}/loeschen", formed(record_delete), methods=["POST"]),
        Route("/r/{rid:int}/rueckgaengig", formed(record_undo), methods=["POST"]),
        Route("/r/{rid:int}/ausstellen", formed(record_issue), methods=["POST"]),
        Route("/r/{rid:int}/positionen", formed(record_positions), methods=["POST"]),
        Route("/r/{rid:int}/zahlung-loesen", formed(record_unpay), methods=["POST"]),
        Route("/r/{rid:int}/korrektur-gesehen", formed(correction_seen), methods=["POST"]),

        Route("/r/{rid:int}/einblenden", record_unhide, methods=["POST"]),
        Route("/r/{rid:int}/xrechnung", record_xrechnung),
        Route("/firma", company_page), Route("/firma", formed(company_save), methods=["POST"]),
        Route("/api/ableiten", api_derive),
        Route("/r/{rid:int}/druck", record_print),
        Route("/r/{rid:int}/erinnerung", record_reminder),
        Route("/mahnung/{pid:int}", reminder_letter),
        Route("/mahnung/{pid:int}", formed(reminder_sent), methods=["POST"]),
        Route("/suche", search_page), Route("/api/suche", api_search), Route("/api/datensatz/{rid:int}", api_record),
        Route("/api/wie-letztes-mal", api_like_last),
        Route("/fragen", questions_page), Route("/fragen/{qid:int}", formed(question_answer), methods=["POST"]),
        Route("/regel", formed(rule_toggle), methods=["POST"]),
        Route("/zahlungen/zuordnen", accept_payments, methods=["POST"]),
        Route("/organismus", organism), Route("/organismus/umbenennen", formed(organism_rename), methods=["POST"]),
        Route("/organismus/feld", formed(organism_attr), methods=["POST"]),
        Route("/organismus/verweis", formed(organism_relation), methods=["POST"]),
        Route("/ablaeufe", processes_page),
        Route("/quellen", sources_page), Route("/quellen/{sid:int}/entfernen", source_remove, methods=["POST"]),
        Route("/quellen/{sid:int}/zurueck", source_restore, methods=["POST"]),
        Route("/quellen/{sid:int}/datei", source_file),
        Route("/export/{tid}.csv", export_csv), Route("/export/{tid}.xlsx", export_xlsx),
        Route("/sicherung.zip", export_backup), Route("/verfahrensdoku", procedure_doc),
        Route("/steuerberatung", tax_page), Route("/steuerberatung/einstellungen", formed(tax_settings), methods=["POST"]),
        Route("/steuerberatung/export", formed(tax_download), methods=["POST"]),
        Route("/ich", formed(set_name), methods=["POST"]),
        Mount("/static", StaticFiles(directory=str(HERE / "static")), name="static"),
    ]
    app = Starlette(routes=routes, middleware=[Middleware(Guard, allowed=hosts, any_ip=any_ip)])
    app.state.store = store
    app.state.rt = rt
    app.state.jobs = jobs
    return app
