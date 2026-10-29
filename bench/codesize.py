"""What the code costs: lines, hand-written word rules and regular expressions (after the strategic review's
counting). A rule is an if/while/filter whose test checks a word literal or a word list."""
from __future__ import annotations

import ast
import re
from pathlib import Path

_WORD = re.compile(r"[a-zäöüß]{3,}", re.I)
# names of the program's own vocabulary (attribute kinds, roles, states), not words of a firm's files
_INTERNAL = {
    "money", "date", "datetime", "due", "ref", "master", "transaction", "line", "document", "doc", "text", "number", "id",
    "name", "person", "email", "phone", "street", "zip", "city", "country", "status", "category", "notes", "iban", "bic",
    "vat_id", "url", "unit", "quantity", "percent", "duration", "flag", "time", "mention", "parent", "own", "child", "key",
    "type", "kind", "role", "attrs", "data", "meta", "import", "user", "hidden", "virtual", "derived", "concept", "incoming",
    "outgoing", "header", "lines", "report", "structured", "open", "answered", "same", "different", "yes", "no", "ok",
    "split", "ignore", "later", "unknown", "draft", "rows", "refs", "docs", "processes", "answers", "bank", "label", "attr",
    "value", "values", "source", "sources", "records", "steps", "step", "deadlines", "start", "party", "gross", "net",
    "tax", "true", "false", "none", "null", "html", "csv", "xlsx", "json", "pdf", "eml", "zip", "txt", "docx", "xml", "utf",
    "get", "post"}


def _word_names(tree: ast.Module) -> set[str]:
    names = set()
    for n in tree.body:
        if isinstance(n, (ast.Assign, ast.AnnAssign)):
            v = n.value
            hit = isinstance(v, ast.Call) and isinstance(v.func, ast.Attribute) and v.func.attr == "compile"
            if isinstance(v, (ast.Set, ast.List, ast.Tuple, ast.Dict)):
                elts = v.keys if isinstance(v, ast.Dict) else v.elts
                hit = sum(1 for e in elts if isinstance(e, ast.Constant) and isinstance(e.value, str) and _WORD.search(e.value)) >= 2
            if hit:
                for t in (n.targets if isinstance(n, ast.Assign) else [n.target]):
                    if isinstance(t, ast.Name):
                        names.add(t.id)
    return names


def measure(root: Path) -> dict:
    lines = rules = regexes = 0
    for p in sorted((root / "physarum").rglob("*.py")):
        if "demo" in p.parts:
            continue
        src = p.read_text(encoding="utf-8")
        lines += src.count("\n")
        tree = ast.parse(src)
        for n in ast.walk(tree):
            if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) and getattr(n.func.value, "id", "") == "re" \
                    and n.func.attr in ("compile", "search", "match", "fullmatch", "findall", "finditer", "sub", "split") \
                    and n.args and isinstance(n.args[0], ast.Constant):
                regexes += 1
        if "web" in p.parts:
            continue
        names = _word_names(tree)
        for n in ast.walk(tree):
            tests = [n.test] if isinstance(n, (ast.If, ast.IfExp, ast.While)) else n.ifs if isinstance(n, ast.comprehension) else []
            for test in tests:
                for m in ast.walk(test):
                    if (isinstance(m, ast.Constant) and isinstance(m.value, str) and _WORD.search(m.value)
                            and m.value.strip().lower() not in _INTERNAL) or \
                            (isinstance(m, ast.Name) and (m.id in names or (m.id.isupper() and len(m.id) > 2))):
                        rules += 1
                        break
    return dict(lines=lines, word_rules=rules, regexes=regexes)
