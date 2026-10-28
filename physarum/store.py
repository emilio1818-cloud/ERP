"""Persistence: one SQLite file plus the original files. That folder *is* the company.

Layers
  substrate  sources, raw_tables, raw_rows, documents       (immutable, what was dumped in)
  organism   models (versioned), registry (stable ids), decisions (human answers)
  records    records, idents, refs, changes (append-only log), notes, search (FTS5)
  flow       flux (Physarum conductivity of things), events (usage)
"""
from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import threading
import time
from contextlib import contextmanager
from datetime import date, datetime, timedelta
from datetime import time as dtime
from decimal import Decimal
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS sources(
  id INTEGER PRIMARY KEY, name TEXT NOT NULL, sha256 TEXT NOT NULL, size INTEGER, ext TEXT,
  parent_id INTEGER, added_at TEXT NOT NULL, added_by TEXT, active INTEGER NOT NULL DEFAULT 1,
  notes TEXT, summary TEXT, UNIQUE(sha256, parent_id));
CREATE TABLE IF NOT EXISTS raw_tables(
  id INTEGER PRIMARY KEY, source_id INTEGER NOT NULL, name TEXT NOT NULL, sheet TEXT,
  columns TEXT NOT NULL, meta TEXT, n_rows INTEGER);
CREATE TABLE IF NOT EXISTS raw_rows(
  table_id INTEGER NOT NULL, idx INTEGER NOT NULL, line INTEGER, cells TEXT NOT NULL,
  PRIMARY KEY(table_id, idx));
CREATE TABLE IF NOT EXISTS documents(
  id INTEGER PRIMARY KEY, source_id INTEGER NOT NULL, kind TEXT, title TEXT, sender TEXT,
  recipients TEXT, date TEXT, body TEXT, meta TEXT);
CREATE TABLE IF NOT EXISTS models(
  version INTEGER PRIMARY KEY, created_at TEXT NOT NULL, model TEXT NOT NULL, summary TEXT);
CREATE TABLE IF NOT EXISTS registry(kind TEXT NOT NULL, key TEXT NOT NULL, id TEXT NOT NULL,
  PRIMARY KEY(kind, key));
CREATE TABLE IF NOT EXISTS counters(name TEXT PRIMARY KEY, value INTEGER NOT NULL);
CREATE TABLE IF NOT EXISTS decisions(
  id INTEGER PRIMARY KEY, kind TEXT NOT NULL, subject TEXT NOT NULL, value TEXT, actor TEXT,
  ts TEXT NOT NULL, note TEXT, UNIQUE(kind, subject));
CREATE TABLE IF NOT EXISTS questions(
  id INTEGER PRIMARY KEY, kind TEXT NOT NULL, subject TEXT NOT NULL UNIQUE, payload TEXT NOT NULL,
  impact REAL, status TEXT NOT NULL DEFAULT 'open', created_at TEXT, answered_at TEXT, answer TEXT,
  snooze_until TEXT);
CREATE TABLE IF NOT EXISTS records(
  id INTEGER PRIMARY KEY, type TEXT NOT NULL, data TEXT NOT NULL, meta TEXT, origin TEXT,
  created_at TEXT, updated_at TEXT, deleted INTEGER NOT NULL DEFAULT 0, merged_into INTEGER);
CREATE INDEX IF NOT EXISTS records_type ON records(type, deleted);
CREATE TABLE IF NOT EXISTS idents(type TEXT NOT NULL, ident TEXT NOT NULL, record_id INTEGER NOT NULL,
  PRIMARY KEY(type, ident));
CREATE INDEX IF NOT EXISTS idents_record ON idents(record_id);
CREATE TABLE IF NOT EXISTS refs(from_id INTEGER NOT NULL, attr TEXT NOT NULL, to_id INTEGER NOT NULL,
  kind TEXT NOT NULL DEFAULT 'ref', how TEXT, PRIMARY KEY(from_id, attr, to_id));
CREATE INDEX IF NOT EXISTS refs_to ON refs(to_id);
CREATE TABLE IF NOT EXISTS changes(
  id INTEGER PRIMARY KEY, record_id INTEGER NOT NULL, ts TEXT NOT NULL, actor TEXT, kind TEXT NOT NULL,
  attr TEXT, old TEXT, new TEXT, source_id INTEGER, note TEXT);
CREATE INDEX IF NOT EXISTS changes_record ON changes(record_id);
CREATE TABLE IF NOT EXISTS notes(id INTEGER PRIMARY KEY, record_id INTEGER NOT NULL, ts TEXT NOT NULL,
  actor TEXT, text TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS flux(subject TEXT PRIMARY KEY, value REAL NOT NULL, ts REAL NOT NULL);
CREATE TABLE IF NOT EXISTS events(id INTEGER PRIMARY KEY, ts TEXT NOT NULL, kind TEXT NOT NULL,
  subject TEXT, detail TEXT);
CREATE TABLE IF NOT EXISTS jobs(id INTEGER PRIMARY KEY, kind TEXT, status TEXT, progress REAL,
  log TEXT, started_at TEXT, finished_at TEXT, result TEXT);
CREATE TABLE IF NOT EXISTS kv(key TEXT PRIMARY KEY, value TEXT);
CREATE VIRTUAL TABLE IF NOT EXISTS search USING fts5(body, record_id UNINDEXED, type UNINDEXED,
  tokenize='unicode61 remove_diacritics 2');
"""


def pair_subject(a: str, b: str) -> str:
    """Subject of a decision about a pair of things: order-free and safe for any characters."""
    return json.dumps(sorted([a, b]), ensure_ascii=False)


def parse_pair(subject: str) -> tuple[str, str] | None:
    try:
        v = json.loads(subject)
        if isinstance(v, list) and len(v) == 2:
            return str(v[0]), str(v[1])
    except (ValueError, TypeError):
        pass
    # legacy "a||b" where a and b are signatures "stem|sheet|det" (and may contain "||" themselves)
    parts = subject.split("|")
    if len(parts) == 7 and parts[3] == "":
        return "|".join(parts[:3]), "|".join(parts[4:])
    if subject.count("||") == 1:
        a, b = subject.split("||")
        return a, b
    return None


def now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _default(o):
    if isinstance(o, datetime):
        return o.isoformat(timespec="minutes")
    if isinstance(o, date):
        return o.isoformat()
    if isinstance(o, dtime):
        return o.strftime("%H:%M")
    if isinstance(o, timedelta):
        mins = int(o.total_seconds() // 60)
        return f"{mins // 60}:{mins % 60:02d}"
    if isinstance(o, (set, frozenset)):
        return sorted(o)
    if isinstance(o, Decimal):
        return float(o)
    if isinstance(o, bytes):
        return o.decode("utf-8", "replace")
    return str(o)  # whatever a file contains, it must never stop the growth


def dumps(o) -> str:
    return json.dumps(o, ensure_ascii=False, default=_default, separators=(",", ":"))


def loads(s):
    return json.loads(s) if s else None


class Store:
    def __init__(self, folder: str | Path):
        self.folder = Path(folder)
        self.folder.mkdir(parents=True, exist_ok=True)
        (self.folder / "originale").mkdir(exist_ok=True)
        self.path = self.folder / "physarum.db"
        self._local = threading.local()
        self.write_lock = threading.RLock()
        with self.write_lock:
            self.conn().executescript(SCHEMA)

    # --- connections -----------------------------------------------------------------------
    def conn(self) -> sqlite3.Connection:
        c = getattr(self._local, "conn", None)
        if c is None:
            c = sqlite3.connect(self.path, timeout=30, isolation_level=None, check_same_thread=False)
            c.row_factory = sqlite3.Row
            c.execute("PRAGMA journal_mode=WAL")
            c.execute("PRAGMA synchronous=NORMAL")
            c.execute("PRAGMA foreign_keys=OFF")
            self._local.conn = c
        return c

    @contextmanager
    def tx(self):
        c = self.conn()
        with self.write_lock:
            c.execute("BEGIN IMMEDIATE")
            try:
                yield c
                c.execute("COMMIT")
            except BaseException:
                c.execute("ROLLBACK")
                raise

    def q(self, sql: str, args=()) -> list[sqlite3.Row]:
        return self.conn().execute(sql, args).fetchall()

    def q1(self, sql: str, args=()):
        r = self.conn().execute(sql, args).fetchone()
        return r

    # --- key/value + counters -----------------------------------------------------------------
    def kv_get(self, key: str, default=None):
        r = self.q1("SELECT value FROM kv WHERE key=?", (key,))
        return loads(r["value"]) if r else default

    def kv_set(self, key: str, value, c=None):
        (c or self.conn()).execute("INSERT INTO kv(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                                   (key, dumps(value)))

    def next_id(self, name: str, c) -> int:
        r = c.execute("SELECT value FROM counters WHERE name=?", (name,)).fetchone()
        v = (r["value"] if r else 0) + 1
        c.execute("INSERT INTO counters(name,value) VALUES(?,?) ON CONFLICT(name) DO UPDATE SET value=excluded.value",
                  (name, v))
        return v

    # --- sources ---------------------------------------------------------------------------------
    def add_source(self, name: str, data: bytes, parent_id: int | None = None, actor: str | None = None,
                   c=None) -> tuple[int, bool]:
        sha = hashlib.sha256(data).hexdigest()
        own = c is None
        ctx = self.tx() if own else None
        cc = ctx.__enter__() if own else c
        try:
            r = cc.execute("SELECT id, active FROM sources WHERE sha256=? AND parent_id IS ?", (sha, parent_id)).fetchone()
            if r:
                if not r["active"]:
                    # dropped in again after it was taken out: switch it (and its contents) back on;
                    # its tables are still there, so it is not digested a second time
                    self.set_active(r["id"], True, cc)
                return r["id"], False
            ext = os.path.splitext(name)[1].lower()
            cur = cc.execute("INSERT INTO sources(name, sha256, size, ext, parent_id, added_at, added_by) VALUES(?,?,?,?,?,?,?)",
                             (name, sha, len(data), ext, parent_id, now_iso(), actor))
            sid = cur.lastrowid
            blob = self.folder / "originale" / f"{sid:05d}_{_safe(name)}"
            blob.write_bytes(data)
            return sid, True
        finally:
            if own:
                ctx.__exit__(None, None, None)

    def find_source(self, data: bytes, parent_id: int | None = None):
        sha = hashlib.sha256(data).hexdigest()
        return self.q1("SELECT id, active FROM sources WHERE sha256=? AND parent_id IS ?", (sha, parent_id))

    def descendants(self, sid: int, c=None) -> list[int]:
        """A source and everything unpacked from it (zip in zip, mail attachments)."""
        cc = c or self.conn()
        out, todo = [], [sid]
        while todo:
            x = todo.pop()
            out.append(x)
            todo.extend(r["id"] for r in cc.execute("SELECT id FROM sources WHERE parent_id=?", (x,)).fetchall())
        return out

    def set_active(self, sid: int, active: bool, c):
        ids = self.descendants(sid, c)
        c.executemany("UPDATE sources SET active=? WHERE id=?", [(1 if active else 0, i) for i in ids])
        return ids

    def source_path(self, sid: int, name: str) -> Path:
        return self.folder / "originale" / f"{sid:05d}_{_safe(name)}"

    def save_digest(self, sid: int, digest, c):
        for t in digest.tables:
            cur = c.execute("INSERT INTO raw_tables(source_id,name,sheet,columns,meta,n_rows) VALUES(?,?,?,?,?,?)",
                            (sid, t.name, t.sheet, dumps(t.columns), dumps(t.meta), len(t.rows)))
            tid = cur.lastrowid
            c.executemany("INSERT INTO raw_rows(table_id,idx,line,cells) VALUES(?,?,?,?)",
                          [(tid, i, t.lines[i] if i < len(t.lines) else i + 1, dumps(row)) for i, row in enumerate(t.rows)])
        for d in digest.docs:
            c.execute("INSERT INTO documents(source_id,kind,title,sender,recipients,date,body,meta) VALUES(?,?,?,?,?,?,?,?)",
                      (sid, d.kind, d.title, d.sender, d.recipients, d.date.isoformat() if d.date else None, d.text,
                       dumps(d.meta)))
        summary = dict(tables=[dict(name=t.name, rows=len(t.rows), columns=len(t.columns)) for t in digest.tables],
                       docs=[dict(kind=d.kind, title=d.title) for d in digest.docs], notes=digest.notes)
        c.execute("UPDATE sources SET summary=?, notes=? WHERE id=?", (dumps(summary), dumps(digest.notes), sid))

    def sources(self, active_only=True) -> list[sqlite3.Row]:
        sql = "SELECT * FROM sources" + (" WHERE active=1" if active_only else "") + " ORDER BY id"
        return self.q(sql)

    def raw_tables(self) -> list[dict]:
        out = []
        for t in self.q("SELECT t.*, s.name AS source_name, s.added_at FROM raw_tables t JOIN sources s ON s.id=t.source_id "
                        "WHERE s.active=1 ORDER BY t.id"):
            rows = self.q("SELECT idx, line, cells FROM raw_rows WHERE table_id=? ORDER BY idx", (t["id"],))
            out.append(dict(id=t["id"], source_id=t["source_id"], source_name=t["source_name"], name=t["name"],
                            sheet=t["sheet"], columns=loads(t["columns"]), meta=loads(t["meta"]) or {},
                            rows=[_revive_row(loads(r["cells"])) for r in rows], lines=[r["line"] for r in rows],
                            added_at=t["added_at"]))
        return out

    def documents(self) -> list[sqlite3.Row]:
        return self.q("SELECT d.*, s.name AS source_name FROM documents d JOIN sources s ON s.id=d.source_id "
                      "WHERE s.active=1 ORDER BY d.id")

    # --- model -------------------------------------------------------------------------------------
    def save_model(self, model: dict, summary: dict, c) -> int:
        r = c.execute("SELECT COALESCE(MAX(version),0)+1 AS v FROM models").fetchone()
        v = r["v"]
        model["version"] = v
        c.execute("INSERT INTO models(version, created_at, model, summary) VALUES(?,?,?,?)",
                  (v, now_iso(), dumps(model), dumps(summary)))
        return v

    def model(self) -> dict | None:
        r = self.q1("SELECT model FROM models ORDER BY version DESC LIMIT 1")
        return loads(r["model"]) if r else None

    def models(self) -> list[sqlite3.Row]:
        return self.q("SELECT version, created_at, summary FROM models ORDER BY version DESC")

    # --- registry (stable ids) ----------------------------------------------------------------------
    def registry(self, kind: str) -> dict[str, str]:
        return {r["key"]: r["id"] for r in self.q("SELECT key, id FROM registry WHERE kind=?", (kind,))}

    def register(self, kind: str, mapping: dict[str, str], c):
        c.executemany("INSERT INTO registry(kind,key,id) VALUES(?,?,?) ON CONFLICT(kind,key) DO UPDATE SET id=excluded.id",
                      [(kind, k, v) for k, v in mapping.items()])

    # --- decisions ---------------------------------------------------------------------------------
    def decisions(self, kind: str | None = None) -> dict[str, str]:
        if kind:
            rows = self.q("SELECT subject, value FROM decisions WHERE kind=?", (kind,))
        else:
            rows = self.q("SELECT kind || '|' || subject AS subject, value FROM decisions")
        return {r["subject"]: loads(r["value"]) for r in rows}

    def decide(self, kind: str, subject: str, value, actor: str | None = None, note: str | None = None, c=None):
        (c or self.conn()).execute(
            "INSERT INTO decisions(kind,subject,value,actor,ts,note) VALUES(?,?,?,?,?,?) "
            "ON CONFLICT(kind,subject) DO UPDATE SET value=excluded.value, actor=excluded.actor, ts=excluded.ts, note=excluded.note",
            (kind, subject, dumps(value), actor, now_iso(), note))

    # --- records -----------------------------------------------------------------------------------
    def record(self, rid: int) -> dict | None:
        r = self.q1("SELECT * FROM records WHERE id=?", (rid,))
        if r is None:
            return None
        if r["merged_into"]:
            return self.record(r["merged_into"])
        return dict(id=r["id"], type=r["type"], data=loads(r["data"]) or {}, meta=loads(r["meta"]) or {},
                    origin=r["origin"], created_at=r["created_at"], updated_at=r["updated_at"], deleted=r["deleted"])

    def records_of(self, type_id: str, include_deleted=False) -> list[dict]:
        sql = "SELECT id, data, meta, origin, created_at, updated_at FROM records WHERE type=?"
        if not include_deleted:
            sql += " AND deleted=0"
        return [dict(id=r["id"], type=type_id, data=loads(r["data"]) or {}, meta=loads(r["meta"]) or {},
                     origin=r["origin"], created_at=r["created_at"], updated_at=r["updated_at"])
                for r in self.q(sql + " ORDER BY id", (type_id,))]

    def all_records(self) -> dict[str, list[dict]]:
        out: dict[str, list[dict]] = {}
        for r in self.q("SELECT id, type, data, meta, origin, created_at, updated_at FROM records WHERE deleted=0 ORDER BY id"):
            out.setdefault(r["type"], []).append(dict(id=r["id"], type=r["type"], data=loads(r["data"]) or {},
                                                      meta=loads(r["meta"]) or {}, origin=r["origin"],
                                                      created_at=r["created_at"], updated_at=r["updated_at"]))
        return out

    def changes(self, rid: int) -> list[sqlite3.Row]:
        return self.q("SELECT * FROM changes WHERE record_id=? ORDER BY id DESC", (rid,))

    def backrefs(self, rid: int) -> list[sqlite3.Row]:
        return self.q("SELECT r.from_id, r.attr, r.kind, r.how, rec.type FROM refs r JOIN records rec ON rec.id=r.from_id "
                      "WHERE r.to_id=? AND rec.deleted=0", (rid,))

    def outrefs(self, rid: int) -> list[sqlite3.Row]:
        return self.q("SELECT r.to_id, r.attr, r.kind, r.how, rec.type FROM refs r JOIN records rec ON rec.id=r.to_id "
                      "WHERE r.from_id=? AND rec.deleted=0", (rid,))

    # --- flow ----------------------------------------------------------------------------------------
    def flux_add(self, subject: str, amount: float = 1.0, tau_days: float = 21.0, c=None):
        """Physarum conductivity: D <- D * exp(-dt/tau) + amount (the ODE solution for impulse flow)."""
        cc = c or self.conn()
        now = time.time()
        r = cc.execute("SELECT value, ts FROM flux WHERE subject=?", (subject,)).fetchone()
        if r:
            decay = pow(2.718281828, -(now - r["ts"]) / (tau_days * 86400))
            v = r["value"] * decay + amount
        else:
            v = amount
        cc.execute("INSERT INTO flux(subject,value,ts) VALUES(?,?,?) ON CONFLICT(subject) DO UPDATE SET value=excluded.value, ts=excluded.ts",
                   (subject, v, now))

    def flux(self, prefix: str = "", tau_days: float = 21.0) -> dict[str, float]:
        now = time.time()
        out = {}
        for r in self.q("SELECT subject, value, ts FROM flux WHERE subject LIKE ?", (prefix + "%",)):
            out[r["subject"]] = r["value"] * pow(2.718281828, -(now - r["ts"]) / (tau_days * 86400))
        return out

    def event(self, kind: str, subject: str | None = None, detail=None):
        try:
            with self.tx() as c:
                c.execute("INSERT INTO events(ts,kind,subject,detail) VALUES(?,?,?,?)",
                          (now_iso(), kind, subject, dumps(detail) if detail is not None else None))
                if subject:
                    for s in subject.split(","):
                        self.flux_add(s, 1.0, c=c)
        except sqlite3.OperationalError:
            pass  # usage tracking must never break the app


def _safe(name: str) -> str:
    keep = "".join(ch if ch.isalnum() or ch in "._-" else "_" for ch in name)
    return keep[-120:] or "datei"


def _revive_row(cells: list) -> list:
    out = []
    for v in cells:
        if isinstance(v, str) and len(v) in (10, 16, 19) and v[4:5] == "-" and v[7:8] == "-":
            try:
                if len(v) == 10:
                    out.append(date.fromisoformat(v))
                else:
                    out.append(datetime.fromisoformat(v))
                continue
            except ValueError:
                pass
        out.append(v)
    return out
