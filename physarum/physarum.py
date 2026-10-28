"""The slime mould: Tero et al. (2010) adaptive network dynamics on the data model.

Nodes are the kinds of things (types); tubes are the relations between them. Food
sources are where substance is: record counts, money and the attention of the people
using the system. Each step sends flow between every pair of food sources through the
tube network (Kirchhoff's laws: a Laplacian system), and every tube adapts its
conductivity to the flow it carries:

    dD/dt = f(|Q|) - gamma * D,    f(q) = q^mu / (1 + q^mu)

Tubes on the shortest, strongest paths between important things thicken; redundant or
unused ones thin out. The resulting conductivities decide what the interface shows
first: order of the navigation, which related lists appear on a record, which columns a
list shows. Decay only lowers *salience*; nothing is ever deleted.

Usage flow (navigating along a relation, opening a list, editing a field) is added to
the physical flow, so the network keeps adapting to how the company actually works.
"""
from __future__ import annotations

import math
import random
import time

MU = 0.85   # < 1 keeps redundant tubes (robust network, Tero 2010); > 1 would prune to a tree
GAMMA = 1.0
DT = 0.5
ITER = 160


def _invert(m: list[list[float]]) -> list[list[float]]:
    n = len(m)
    a = [row[:] + [1.0 if i == j else 0.0 for j in range(n)] for i, row in enumerate(m)]
    for col in range(n):
        piv = max(range(col, n), key=lambda r: abs(a[r][col]))
        if abs(a[piv][col]) < 1e-12:
            raise ZeroDivisionError("singular")
        a[col], a[piv] = a[piv], a[col]
        pv = a[col][col]
        a[col] = [x / pv for x in a[col]]
        for r in range(n):
            if r != col and a[r][col] != 0.0:
                f = a[r][col]
                ra, rc = a[r], a[col]
                a[r] = [x - f * y for x, y in zip(ra, rc)]
    return [row[n:] for row in a]


def _components(n: int, edges: list[tuple[int, int, float]]) -> list[list[int]]:
    parent = list(range(n))

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    for i, j, _ in edges:
        parent[find(i)] = find(j)
    comps: dict[int, list[int]] = {}
    for v in range(n):
        comps.setdefault(find(v), []).append(v)
    return list(comps.values())


def tero(n: int, edges: list[tuple[int, int, float]], nutrients: list[float], usage: list[float] | None = None,
         iters: int = ITER, mu: float = MU) -> tuple[list[float], list[float]]:
    """Run the Physarum solver. Returns (conductivity per edge, mean |flux| per edge)."""
    m = len(edges)
    D = [1.0] * m
    usage = usage or [0.0] * m
    flux = [0.0] * m
    if m == 0:
        return D, flux
    comps = [c for c in _components(n, edges) if len(c) > 1]
    for _ in range(iters):
        Q = [0.0] * m
        total_w = 0.0
        for comp in comps:
            ground = comp[-1]
            idx = {v: k for k, v in enumerate(x for x in comp if x != ground)}
            size = len(idx)
            lap = [[0.0] * size for _ in range(size)]
            cond = []
            for e, (i, j, L) in enumerate(edges):
                if i not in idx and i != ground:
                    cond.append(0.0)
                    continue
                g = D[e] / L
                cond.append(g)
                for a, b in ((i, j), (j, i)):
                    if a in idx:
                        lap[idx[a]][idx[a]] += g
                        if b in idx:
                            lap[idx[a]][idx[b]] -= g
            try:
                G = _invert(lap)
            except ZeroDivisionError:
                continue

            def pot(v, s):  # potential at v for unit injection at s, grounded sink
                if v == ground or s == ground:
                    return 0.0
                return G[idx[v]][idx[s]]

            nodes = [v for v in comp if nutrients[v] > 0]
            for a in range(len(nodes)):
                for b in range(a + 1, len(nodes)):
                    s, t = nodes[a], nodes[b]
                    w = nutrients[s] * nutrients[t]
                    total_w += w
                    for e, (i, j, L) in enumerate(edges):
                        if cond[e] == 0.0:
                            continue
                        dp = (pot(i, s) - pot(i, t)) - (pot(j, s) - pot(j, t))
                        Q[e] += w * abs(cond[e] * dp)
        if total_w > 0:
            Q = [q / total_w for q in Q]
        change = 0.0
        for e in range(m):
            q = Q[e] + usage[e]
            f = q ** mu / (1.0 + q ** mu)
            nd = max(1e-6, D[e] + DT * (f - GAMMA * D[e]))
            change = max(change, abs(nd - D[e]))
            D[e] = nd
        flux = Q
        if change < 1e-5:
            break
    return D, flux


def layout(n: int, edges: list[tuple[int, int, float]], weights: list[float], seed: int = 7,
           iters: int = 400) -> list[tuple[float, float]]:
    """Deterministic force-directed layout (Fruchterman-Reingold) in the unit square."""
    rnd = random.Random(seed)
    if n == 0:
        return []
    pos = [[0.5 + 0.35 * math.cos(2 * math.pi * k / n) + rnd.uniform(-0.02, 0.02),
            0.5 + 0.35 * math.sin(2 * math.pi * k / n) + rnd.uniform(-0.02, 0.02)] for k in range(n)]
    area = 1.0
    k = math.sqrt(area / n) * 1.25
    temp = 0.1
    for it in range(iters):
        disp = [[0.0, 0.0] for _ in range(n)]
        for a in range(n):
            for b in range(a + 1, n):
                dx, dy = pos[a][0] - pos[b][0], pos[a][1] - pos[b][1]
                d = math.hypot(dx, dy) or 1e-4
                f = k * k / d
                disp[a][0] += dx / d * f
                disp[a][1] += dy / d * f
                disp[b][0] -= dx / d * f
                disp[b][1] -= dy / d * f
        for (i, j, _), w in zip(edges, weights):
            dx, dy = pos[i][0] - pos[j][0], pos[i][1] - pos[j][1]
            d = math.hypot(dx, dy) or 1e-4
            f = d * d / k * (0.4 + w)
            disp[i][0] -= dx / d * f
            disp[i][1] -= dy / d * f
            disp[j][0] += dx / d * f
            disp[j][1] += dy / d * f
        for v in range(n):
            # gentle pull to the centre keeps isolated nodes on the canvas
            disp[v][0] += (0.5 - pos[v][0]) * 0.6
            disp[v][1] += (0.5 - pos[v][1]) * 0.6
            d = math.hypot(*disp[v]) or 1e-4
            pos[v][0] += disp[v][0] / d * min(d, temp)
            pos[v][1] += disp[v][1] / d * min(d, temp)
        temp *= 0.985
    xs, ys = [p[0] for p in pos], [p[1] for p in pos]
    minx, maxx, miny, maxy = min(xs), max(xs), min(ys), max(ys)
    sx, sy = (maxx - minx) or 1, (maxy - miny) or 1
    return [((p[0] - minx) / sx, (p[1] - miny) / sy) for p in pos]


KIND_WEIGHT = {"transaction": 1.4, "master": 1.2, "line": 0.5, "document": 0.6}


def grow_network(model: dict, store=None, keep_layout: bool = True):
    """Compute conductivities (relations), salience (types, attributes) and a layout."""
    types = [t for t in model["types"]]
    ids = [t["id"] for t in types]
    pos_of = {tid: k for k, tid in enumerate(ids)}
    flux = store.flux() if store is not None else {}
    edges, eids = [], []
    for r in model["relations"]:
        if r["src"] not in pos_of or r["dst"] not in pos_of or r["src"] == r["dst"]:
            continue
        cov = r.get("coverage") or 0.0
        L = 1.0 / (0.25 + cov) * (1.4 if r["kind"] == "mention" else 1.0)
        edges.append((pos_of[r["src"]], pos_of[r["dst"]], L))
        eids.append(r["id"])
    # documents connect to what they mention
    doc_links = {}
    if store is not None:
        for row in store.q("SELECT r2.type AS t, COUNT(*) AS n FROM refs r JOIN records r1 ON r1.id=r.from_id "
                           "JOIN records r2 ON r2.id=r.to_id WHERE r.attr='doc' AND r1.deleted=0 GROUP BY r2.type"):
            doc_links[row["t"]] = row["n"]
    doc = next((t for t in types if t["kind"] == "document"), None)
    if doc and doc_links:
        for tid, n in doc_links.items():
            if tid in pos_of:
                edges.append((pos_of[doc["id"]], pos_of[tid], 1.0 / (0.25 + min(1.0, n / 10)) * 1.6))
                eids.append(f"doc_{tid}")
    nutrients = []
    for t in types:
        cnt = t.get("count") or 0
        use = flux.get(f"type:{t['id']}", 0.0)
        nutrients.append(math.log1p(cnt) * KIND_WEIGHT.get(t["kind"], 1.0) + 2.0 * math.log1p(use))
    tot = sum(nutrients) or 1.0
    nutrients = [x / tot for x in nutrients]
    usage = []
    for e in eids:
        u = flux.get(f"rel:{e}", 0.0)
        usage.append(0.02 * math.log1p(u))
    t0 = time.time()
    D, Q = tero(len(types), edges, nutrients, usage)
    dmax = max(D) if D else 1.0
    cond = {e: round(d / dmax, 4) for e, d in zip(eids, D)}
    # salience of types: substance + throughput + attention
    through = [0.0] * len(types)
    for (i, j, _), q in zip(edges, Q):
        through[i] += q
        through[j] += q
    tmax = max(through) or 1.0
    nmax = max(nutrients) or 1.0
    sal = {}
    for k, t in enumerate(types):
        use = flux.get(f"type:{t['id']}", 0.0)
        s = 0.55 * nutrients[k] / nmax + 0.3 * through[k] / tmax + 0.15 * min(1.0, math.log1p(use) / 4)
        if t["kind"] == "line":
            s *= 0.5
        sal[t["id"]] = round(s, 4)
    # layout (kept stable across regrowths so the organism does not jump around)
    prev = (store.kv_get("layout") if store is not None else None) or {}
    pts = layout(len(types), edges, [cond[e] for e in eids])
    positions = {}
    for k, t in enumerate(types):
        positions[t["id"]] = prev.get(t["id"]) if keep_layout and t["id"] in prev else [round(pts[k][0], 4), round(pts[k][1], 4)]
    if store is not None:
        store.kv_set("layout", positions)
    model["network"] = dict(conductivity=cond, salience=sal, positions=positions, solved_ms=round((time.time() - t0) * 1000),
                            edges=[dict(id=e, a=ids[i], b=ids[j]) for e, (i, j, _) in zip(eids, edges)])
    for t in types:
        t["salience"] = sal[t["id"]]
        for a in t["attrs"]:
            a["salience"] = attr_salience(t, a, flux)


def attr_salience(t: dict, a: dict, flux: dict) -> float:
    if a.get("hidden"):
        return 0.0
    base = {"name": 1.0, "id": 0.95, "person": 0.6, "money": 0.85, "status": 0.85, "date": 0.75, "due": 0.8,
            "email": 0.55, "phone": 0.5, "city": 0.5, "category": 0.55, "quantity": 0.7, "percent": 0.4,
            "notes": 0.3, "street": 0.35, "zip": 0.3, "iban": 0.2, "duration": 0.35, "flag": 0.4}.get(a.get("role") or "", 0.45)
    if a["kind"] == "ref":
        base = 0.9
    if a["id"] == t.get("key"):
        base = 1.0
    if a["id"] == t.get("title"):
        base = 1.05
    fill = a.get("fill", 1.0)
    use = flux.get(f"attr:{a['id']}", 0.0)
    return round(base * (0.35 + 0.65 * fill) * (1 + 0.25 * math.log1p(use)), 4)


def refresh_salience(model: dict, store):
    """Cheap re-run used on page loads: usage changes salience without a full regrowth."""
    grow_network(model, store)
