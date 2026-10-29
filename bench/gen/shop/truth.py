"""Exact ground truth for each delivery, computed from the simulated world (not from the files)."""
from __future__ import annotations

from collections import Counter, defaultdict
from datetime import date, datetime, timedelta

from export import (MONEY_START, START, lex_view, netted_credits, order_state, shopify_available, stock_on_hand)
from sim import CUT, is_bday, next_bday
from world import PICKUP


def eur(c):
    return round(c / 100, 2)


def end_of(d):
    return datetime(d.year, d.month, d.day, 23, 59, 59)


# ------------------------------------------------------------------------------------------------ B2B receivables
def true_open(inv, cut, world):
    """What the customer really still owes on this document at the end of `cut` (negative = credit balance).
    A credit note the customer deducts from an invoice is allocated to that invoice from its issue date."""
    netted = netted_credits(world)
    paid = sum(p["amount"] for p in inv.payments if p["d"] <= cut)
    if inv.kind == "Gutschrift":
        if any(gu is inv for gu in netted.values()):
            return 0
        return inv.gross - paid            # refunded by transfer (the refund is a negative payment)
    gu = netted.get(inv.no)
    owed = inv.gross + (gu.gross if (gu is not None and gu.d <= cut) else 0)
    if inv.cust.skonto:
        days, pct = inv.cust.skonto
        for p in inv.payments:
            if p["d"] <= cut and p["d"] <= inv.d + timedelta(days=days) and \
               p["amount"] >= inv.gross - round(inv.gross * pct / 100) - 1:
                return owed - inv.gross    # settled with a justified Skonto deduction
    return owed - paid


def b2b_truth(world, k):
    cut = CUT[k]
    today = cut + timedelta(days=1)
    docs = []
    for inv in sorted((i for i in world.inv if i.d <= cut), key=lambda i: i.no):
        o = true_open(inv, cut, world)
        st, bopen, bpaid = lex_view(inv, cut, world)
        pays = [dict(date=p["d"].isoformat(), amount=eur(p["amount"]), channel=p["channel"], reference=p["ref"])
                for p in inv.payments if p["d"] <= cut]
        rec = dict(no=inv.no, kind=inv.kind, customer=inv.cust.kno, customer_name=inv.cust.name, date=inv.d.isoformat(),
                   due=inv.due.isoformat(), net=eur(inv.net), vat=eur(inv.vat), gross=eur(inv.gross),
                   order=inv.order.name if inv.order else None, ref=inv.ref.no if inv.ref else None,
                   payments=pays, open_true=eur(o), book_status=st, book_open=eur(bopen),
                   overdue_days=(today - inv.due).days if (o > 0 and inv.due < today and inv.kind == "Rechnung") else 0)
        if inv.kind == "Rechnung" and o == 0 and bopen > 0:
            rec["book_stale"] = True
        if inv.kind == "Rechnung" and o > 0 and bopen == 0:
            rec["book_wrongly_paid"] = True
        if any(p["channel"] == "paypal" for p in inv.payments if p["d"] <= cut):
            rec["paid_via_paypal"] = True
        if inv.cust.skonto and o == 0 and any(p["amount"] < inv.gross for p in inv.payments if p["d"] <= cut and p["amount"] > 0):
            rec["skonto_taken"] = True
        docs.append(rec)
    open_items = [d for d in docs if d["open_true"] > 0]
    overdue = [d for d in open_items if d["overdue_days"] > 0]
    credits = [d for d in docs if d["open_true"] < 0]
    per_customer = defaultdict(float)
    for d in docs:
        per_customer[d["customer"]] += d["open_true"]
    return dict(
        documents=docs,
        open_items=dict(count=len(open_items), total=round(sum(d["open_true"] for d in open_items), 2),
                        items=[(d["no"], d["customer_name"], d["open_true"], d["due"], d["overdue_days"]) for d in open_items]),
        overdue=dict(count=len(overdue), total=round(sum(d["open_true"] for d in overdue), 2),
                     items=[(d["no"], d["customer_name"], d["open_true"], d["due"], d["overdue_days"]) for d in overdue]),
        credit_balances=[(d["no"], d["customer_name"], d["open_true"]) for d in credits],
        net_receivable_per_customer={k_: round(v, 2) for k_, v in per_customer.items() if abs(v) > 0.004},
        book=dict(open_count=sum(1 for d in docs if d["kind"] == "Rechnung" and d["book_open"] > 0),
                  open_total=round(sum(d["book_open"] for d in docs if d["kind"] == "Rechnung" and d["book_open"] > 0), 2),
                  stale=[d["no"] for d in docs if d.get("book_stale")],
                  wrongly_paid=[d["no"] for d in docs if d.get("book_wrongly_paid")]),
        shopify_b2b_pending_but_paid=[],
    )


# ------------------------------------------------------------------------------------------------ orders
def order_truth(world, o, cut):
    st = order_state(o, cut, world)
    end = end_of(cut)
    refunded = sum(r.amount for r in o.refunds if r.when <= end)
    canc = o.cancelled_at and o.cancelled_at <= end
    ful = o.fulfilled_at and o.fulfilled_at <= end
    money = None
    if o.b2b:
        if o.invoice and o.invoice.d <= cut:
            op = true_open(o.invoice, cut, world)
            state = "paid" if op <= 0 else ("partially_paid" if op < o.invoice.gross else "open")
            money = eur(o.invoice.gross - op)
        else:
            state = "not_invoiced"
    elif o.gateway == "klarna":
        state = "cancelled" if canc else ("paid" if ful else "authorized")
    elif o.gateway == "vorkasse":
        got = sum(x["amount"] for x in o.money if x["d"] <= cut)
        money = eur(got)
        if canc:
            state = "cancelled_money_held" if got and refunded < got else "cancelled"
        else:
            state = "paid" if got >= o.total else ("partially_paid" if got else "pending")
    elif o.gateway == "cash":
        state = "paid" if ful else ("cancelled" if canc else "pending")
    else:
        state = "cancelled" if canc else "paid"
    if state == "paid" and refunded:
        state = "refunded" if refunded >= o.total - o.gc_amount else "partially_refunded"
    return dict(name=o.name, created=o.created.isoformat(sep=" "), b2b=o.b2b.kno if o.b2b else None,
                customer=(o.b2b.kno if o.b2b else o.cust.key), email=world.order_email(o), channel=o.gateway,
                currency=o.currency, total=eur(o.total), gift_card=eur(o.gc_amount), state_true=state,
                shopify_financial=st["fin"], fulfilled=bool(ful), cancelled=bool(canc), refunded=eur(refunded),
                lines=[(ln.v.sku, ln.v.name, ln.qty, eur(ln.price)) for ln in o.lines], money_received=money,
                invoice=o.invoice.no if (o.invoice and o.invoice.d <= cut) else None)


# ------------------------------------------------------------------------------------------------ payouts
def payouts_truth(world, k):
    lo, cut = MONEY_START[k], CUT[k]
    bank = {t.ref: t for t in world.bank if t.kind in ("paypal_payout", "shopify_payout", "klarna_payout")}
    out = dict(paypal=[], shopify=[], klarna=[])
    for p in world.pp:
        if p.kind == "withdrawal" and lo <= p.dt.date() <= cut:
            parts = [q for q in world.pp if q.withdrawal == p.code]
            t = bank.get(p.code)
            out["paypal"].append(dict(code=p.code, at=p.dt.isoformat(sep=" "), amount=eur(-p.gross),
                                      bank_date=t.d.isoformat() if t else None, bank_in_delivery=bool(t and t.d <= cut),
                                      parts=[(q.kind, q.order.name if q.order else q.name, eur(q.gross), eur(q.fee)) for q in parts],
                                      orders=sorted({q.order.name for q in parts if q.order}),
                                      check=eur(sum(q.net for q in parts if q.cur == "EUR"))))
    pids = sorted({s.payout_id for s in world.sp if s.payout_id and s.payout_date and lo <= s.payout_date <= cut})
    for pid in pids:
        parts = [s for s in world.sp if s.payout_id == pid]
        t = bank.get(pid)
        out["shopify"].append(dict(id=pid, payout_date=parts[0].payout_date.isoformat(), amount=eur(sum(s.net for s in parts)),
                                   bank_date=t.d.isoformat() if t else None, bank_in_delivery=bool(t and t.d <= cut),
                                   charges=sum(1 for s in parts if s.typ == "charge"), refunds=sum(1 for s in parts if s.typ == "refund"),
                                   fees=eur(sum(s.fee for s in parts)), orders=sorted({s.order.name for s in parts})))
    refs = sorted({kr.payout_ref for kr in world.kl if kr.payout_ref and lo <= kr.payout_date <= cut})
    for ref in refs:
        parts = [kr for kr in world.kl if kr.payout_ref == ref]
        t = bank.get(ref)
        out["klarna"].append(dict(ref=ref, payout_date=parts[0].payout_date.isoformat(), amount=eur(sum(x.amount for x in parts)),
                                  bank_date=t.d.isoformat() if t else None, bank_in_delivery=bool(t and t.d <= cut),
                                  sales=sum(1 for x in parts if x.typ == "SALE"), returns=sum(1 for x in parts if x.typ == "RETURN"),
                                  fees=eur(sum(x.amount for x in parts if x.typ == "FEE")), orders=sorted({x.order.name for x in parts})))
    in_transit = [dict(provider=prov, ref=x.get("code") or x.get("id") or x.get("ref"), amount=x["amount"], bank_date=x["bank_date"])
                  for prov in out for x in out[prov] if not x["bank_in_delivery"]]
    fees = dict(paypal=eur(sum(p.fee for p in world.pp if lo <= p.dt.date() <= cut and p.cur == "EUR")),
                paypal_chf=eur(sum(p.fee for p in world.pp if lo <= p.dt.date() <= cut and p.cur == "CHF")),
                shopify=eur(sum(s.fee for s in world.sp if lo <= s.dt.date() <= cut)),
                klarna=eur(sum(kr.amount for kr in world.kl if kr.typ == "FEE" and kr.payout_date and lo <= kr.payout_date <= cut)))
    return dict(payouts=out, counts={p: len(v) for p, v in out.items()}, in_transit=in_transit, fees_in_period=fees)


# ------------------------------------------------------------------------------------------------ stock
def stock_truth(world, k):
    cut = CUT[k]
    end = end_of(cut)
    rows = {}
    for v in world.catalog:
        if not v.sku:
            continue
        sku = v.sku
        recv = sum(r.qty for r in world.receipts if r.sku == sku and r.d <= cut)
        shipped = sum(q for d, s, q, o in world.shipped if s == sku and d <= cut)
        rest = sum(q for d, s, q, ret in world.restocked if s == sku and d <= cut)
        oh = stock_on_hand(world, sku, cut)
        committed = sum(ln.qty for o in world.orders for ln in o.lines if ln.v.sku == sku and o.created <= end
                        and not (o.fulfilled_at and o.fulfilled_at <= end) and not (o.cancelled_at and o.cancelled_at <= end))
        lo = cut - timedelta(days=55)
        sold56 = sum(q for d, s, q, o in world.shipped if s == sku and lo <= d <= cut)
        rate = sold56 / 56
        avail = oh - committed
        cover = round(avail / rate, 1) if rate > 0 else None
        rows[sku] = dict(name=v.name, inventur_31_12_2025=world.inventur.get(sku, 0), received=recv, shipped=shipped,
                         restocked_returns=rest, on_hand=oh, committed=committed, available=avail,
                         shopify_export_qty=shopify_available(world, sku, cut) if not v.discontinued else None,
                         sold_last_56_days=sold56, cover_days=cover, discontinued=v.discontinued)
    sold_out_waiting = [s for s, r in rows.items() if r["available"] < 0 or (r["on_hand"] == 0 and r["committed"] > 0)]
    low = [s for s, r in rows.items() if r["cover_days"] is not None and r["cover_days"] < 14 and not r["discontinued"]
           and s not in sold_out_waiting]
    mismatch = {s: (r["on_hand"] - r["committed"], r["shopify_export_qty"]) for s, r in rows.items()
                if r["shopify_export_qty"] is not None and r["shopify_export_qty"] != r["available"]}
    return dict(per_sku=rows, sold_out_with_waiting_orders=sold_out_waiting, low_cover_under_14_days=low,
                shopify_vs_physical_available=mismatch)


# ------------------------------------------------------------------------------------------------ supplier invoices
def supplier_truth(world, k):
    cut = CUT[k]
    today = cut + timedelta(days=1)
    rows = []
    for si in world.sinv:
        dump = 1 if (date(2026, 8, 1) <= si.d <= CUT[1]) else (2 if CUT[1] < si.d <= CUT[2] else 0)
        if dump == 0 or dump > k:
            continue
        paid = si.paid and si.paid <= cut
        rows.append(dict(supplier=si.supplier, no=si.no, date=si.d.isoformat(), gross=eur(si.gross), net=eur(si.net),
                         due=si.due.isoformat(), skonto_until=si.skonto_until.isoformat() if si.skonto_until else None,
                         skonto_amount=eur(si.gross - round(si.gross * 0.02)) if si.skonto_until else None,
                         direct_debit=si.direct_debit, paid=bool(paid), paid_on=si.paid.isoformat() if paid else None,
                         paid_amount=eur(si.paid_amount) if paid else None, in_delivery=dump,
                         overdue_days=(today - si.due).days if (not paid and si.due < today) else 0))
    to_pay = [r for r in rows if not r["paid"] and not r["direct_debit"]]
    debit_pending = [r for r in rows if not r["paid"] and r["direct_debit"]]
    lo = MONEY_START[k]
    docs = {r["no"] for r in rows}
    undocumented = [dict(date=t.d.isoformat(), name=t.name, amount=eur(t.amount), purpose=t.purpose) for t in world.bank
                    if t.kind == "supplier" and lo <= t.d <= cut and not any(no in t.purpose for no in docs)]
    return dict(invoices=rows, to_pay=to_pay, direct_debit_pending=debit_pending,
                to_pay_total=round(sum(r["gross"] for r in to_pay), 2),
                supplier_payments_without_document_in_dump=len(undocumented))


# ------------------------------------------------------------------------------------------------ the whole truth
def compute_truth(world, k, mails, files):
    cut = CUT[k]
    today = cut + timedelta(days=1)
    end = end_of(cut)
    known = [o for o in world.orders if o.created.date() <= cut]
    export = [o for o in world.orders if START[k] <= o.created.date() <= cut]
    orders = {o.name: order_truth(world, o, cut) for o in known}
    b2c = [o for o in known if not o.b2b]
    persons = {o.cust.key for o in b2c}
    emails = {world.order_email(o) for o in b2c}
    emails_folded = {e.lower() for e in emails}
    b2b_companies = sorted({o.b2b.kno for o in known if o.b2b} | {b.kno for b in world.b2b if (b.kno != "K-10011" or k == 2)})
    b2b = b2b_truth(world, k)
    pays = payouts_truth(world, k)
    stock = stock_truth(world, k)
    sup = supplier_truth(world, k)
    rets = []
    for ret in world.returns:
        if ret.arrived > cut:
            continue
        refunded = bool(ret.refund_on and ret.refund_on <= cut)
        rets.append(dict(rma=ret.rma, order=ret.order.name, customer=ret.order.cust.name, arrived=ret.arrived.isoformat(),
                         items=ret.items, amount=eur(ret.amount), refunded=refunded,
                         refunded_on=ret.refund_on.isoformat() if refunded else None, channel=ret.order.gateway,
                         days_since_arrival=(today - ret.arrived).days, sheet_says_refunded=bool(
                             ret.sheet_refund_on and ret.sheet_refund_on <= cut and not (getattr(ret, "sheet_lag", False) and k == 1))))
    not_refunded = [r for r in rets if not r["refunded"]]

    # ---------------------------------------------------------------- Vorkasse and other order-money cases
    vk_paid_not_marked, vk_unpaid_old, vk_under, after_cancel, ship_now, backorders, waiting = [], [], [], [], [], [], []
    for o in known:
        st = order_state(o, cut, world)
        t = orders[o.name]
        got = sum(x["amount"] for x in o.money if x["d"] <= cut)
        canc = o.cancelled_at and o.cancelled_at <= end
        ful = o.fulfilled_at and o.fulfilled_at <= end
        if o.gateway == "vorkasse" and not canc:
            if got >= o.total and st["fin"] == "pending":
                vk_paid_not_marked.append((o.name, o.cust.name, eur(o.total), min(x["d"] for x in o.money).isoformat(),
                                           [x["tx"].name for x in o.money][0], [x["tx"].purpose for x in o.money][0]))
            if got == 0 and st["fin"] == "pending" and (today - o.created.date()).days > 7:
                vk_unpaid_old.append((o.name, o.cust.name, eur(o.total), (today - o.created.date()).days))
            if 0 < got < o.total:
                vk_under.append((o.name, o.cust.name, eur(o.total), eur(got), eur(o.total - got), bool(ful)))
        if o.gateway == "vorkasse" and canc and got:
            refunded = sum(r.amount for r in o.refunds if r.when <= end)
            if refunded < got:
                after_cancel.append((o.name, o.cust.name, eur(got - refunded)))
        if not ful and not canc and o.ship_method != PICKUP and not all(ln.v.gift for ln in o.lines):
            ready = (o.b2b is not None) or (st["fin"] in ("paid", "partially_paid", "authorized")) or \
                    (o.gateway == "vorkasse" and got >= o.total)
            if not ready:
                continue
            age_bd = 0
            d = o.created.date()
            while d < today:
                d = next_bday(d)
                if d <= today:
                    age_bd += 1
            short = [ln.v.sku for ln in o.lines if ln.v.sku and stock_on_hand(world, ln.v.sku, cut) < ln.qty]
            item = (o.name, (o.b2b.name if o.b2b else o.cust.name), o.created.date().isoformat(), age_bd, short)
            waiting.append(item)
            if short:
                backorders.append(item)
            elif age_bd > 2 or (o.gateway == "vorkasse" and got >= o.total and st["fin"] == "pending"):
                ship_now.append(item)
    # money in the bank that nothing explains
    unknown = [dict(date=t.d.isoformat(), payer=t.name, amount=eur(t.amount), purpose=t.purpose) for t in world.bank
               if t.kind == "unknown" and MONEY_START[1] <= t.d <= cut]
    # B2B rhythm
    rhythm = []
    for b in world.b2b:
        ods = sorted(o.created.date() for o in known if o.b2b is b)
        if len(ods) >= 4 and b.interval:
            gaps = [(y - x).days for x, y in zip(ods, ods[1:])]
            typical = sorted(gaps)[len(gaps) // 2]
            since = (today - ods[-1]).days
            if since > 2 * typical:
                rhythm.append(dict(customer=b.kno, name=b.name, last_order=ods[-1].isoformat(), typical_gap_days=typical,
                                   days_since=since))
    dispute = None
    sc = world.scenario
    if "dispute" in sc and date.fromisoformat(sc["dispute"]["opened"]) <= cut:
        released = date(2026, 11, 6) <= cut
        dispute = dict(sc["dispute"], open=not released, respond_by="2026-11-03")
    mails_t = [dict(file=m_.fname, date=m_.when.isoformat(sep=" "), sender=m_.sender, subject=m_.subject,
                    needs_action=m_.needs_action, kind=m_.kind, refs=m_.refs) for m_ in mails if m_.delivery == k]

    todo = []

    def add(cat, ref, amount=None, why="", prio=2):
        todo.append(dict(category=cat, ref=ref, amount=amount, why=why, priority=prio))

    for no, name, amt, due, days in b2b["overdue"]["items"]:
        add("B2B-Rechnung überfällig", no, amt, f"{name}, fällig {due}, {days} Tage überfällig", 1 if days > 30 else 2)
    for no, name, amt in b2b["credit_balances"]:
        add("Guthaben/Doppelzahlung erstatten", no, amt, f"{name} hat zu viel gezahlt", 2)
    for x in vk_paid_not_marked:
        add("Vorkasse bezahlt, in Shopify offen – als bezahlt markieren und versenden", x[0], x[2],
            f"{x[1]}: Geld am {x[3]} von '{x[4]}' ('{x[5]}')", 1)
    for x in vk_unpaid_old:
        add("Vorkasse ohne Zahlung > 7 Tage – erinnern/stornieren", x[0], x[2], f"{x[1]}, seit {x[3]} Tagen", 3)
    for x in vk_under:
        add("Vorkasse unterbezahlt", x[0], x[4], f"{x[1]} zahlte {x[3]} statt {x[2]}" + (" (schon versandt)" if x[5] else ""), 3)
    for x in after_cancel:
        add("Zahlung nach Stornierung – erstatten oder Bestellung reaktivieren", x[0], x[2], x[1], 1)
    for u in unknown:
        add("Geldeingang ohne Zuordnung klären", u["payer"], u["amount"], u["purpose"], 2)
    for x in ship_now:
        add("Bezahlt, aber nicht versandt", x[0], None, f"{x[1]}, bestellt {x[2]}, {x[3]} Werktage", 1)
    for x in backorders:
        add("Wartet auf Ware (ausverkauft) – Kunde informieren", x[0], None, f"{x[1]}: {', '.join(x[4])}", 2)
    for r in not_refunded:
        add("Retoure eingegangen, nicht erstattet", r["rma"], r["amount"],
            f"{r['customer']} ({r['order']}), seit {r['days_since_arrival']} Tagen" + (" – Frist 14 Tage überschritten!" if r["days_since_arrival"] > 14 else ""),
            1 if r["days_since_arrival"] > 10 else 2)
    if dispute and dispute["open"]:
        add("PayPal-Konflikt beantworten (Sendungsnachweis)", dispute["order"], eur(dispute["amount"]),
            f"{dispute['customer']}, eröffnet {dispute['opened']}, Antwort bis {dispute['respond_by']}", 1)
    for r in sup["to_pay"]:
        if r["overdue_days"] > 0:
            add("Lieferantenrechnung überfällig – bezahlen", r["no"], r["gross"], f"{r['supplier']}, fällig {r['due']}", 1)
        elif r["skonto_until"] and r["skonto_until"] >= today.isoformat():
            add("Lieferantenrechnung mit Skonto bezahlen", r["no"], r["skonto_amount"],
                f"{r['supplier']}, Skonto bis {r['skonto_until']} (sonst {r['gross']} bis {r['due']})", 1)
        else:
            add("Lieferantenrechnung fällig demnächst", r["no"], r["gross"], f"{r['supplier']}, fällig {r['due']}", 3)
    for m_ in mails_t:
        if m_["needs_action"]:
            add(f"Mail beantworten ({m_['kind']})", m_["file"], None, m_["subject"], 2)
    for s in stock["sold_out_with_waiting_orders"]:
        add("Ausverkauft mit wartenden Bestellungen – nachbestellen", s, None, stock["per_sku"][s]["name"], 2)
    for s in stock["low_cover_under_14_days"]:
        r = stock["per_sku"][s]
        add("Bestand knapp (< 14 Tage Reichweite)", s, None, f"{r['name']}: verfügbar {r['available']}, ~{r['cover_days']} Tage", 3)
    for x in rhythm:
        add("B2B-Kunde bestellt ungewöhnlich lange nicht", x["customer"], None,
            f"{x['name']}: letzte Bestellung {x['last_order']}, sonst alle ~{x['typical_gap_days']} Tage", 3)
    forgot = {x["sku"]: x for key_, x in world.scenario.items() if key_.startswith("forgot_") and x["date"] <= cut.isoformat()}
    for s, (phys, shp) in stock["shopify_vs_physical_available"].items():
        if s in forgot:
            add("Wareneingang nicht in Shopify gebucht – Bestand korrigieren", s, None,
                f"physisch verfügbar {phys}, Shopify {shp} (Lieferschein {forgot[s]['note']}, {forgot[s]['qty']} Stk.)", 3)

    traps = dict(
        b2c_paid_online_not_in_bank_individually=sum(1 for o in b2c if o.gateway in ("paypal", "shopify", "klarna", "gc_paypal")),
        payout_bank_lines=sum(1 for t in world.bank if t.kind.endswith("_payout") and MONEY_START[k] <= t.d <= cut),
        b2b_paid_but_book_not_yet=[d["no"] for d in b2b["documents"] if d.get("book_stale")],
        b2b_paid_via_paypal=[d["no"] for d in b2b["documents"] if d.get("paid_via_paypal")],
        b2b_skonto_settled=[d["no"] for d in b2b["documents"] if d.get("skonto_taken")],
        b2b_shopify_pending_but_paid=sorted(o.name for o in known if o.b2b and orders[o.name]["shopify_financial"] == "pending"
                                            and orders[o.name]["state_true"] == "paid"),
        direct_debit_supplier_invoices=[r["no"] for r in sup["invoices"] if r["direct_debit"]],
        gift_card_orders=[n for n in sc.get("gc_sales", []) if n in orders],
        cancelled_orders=sorted(n for n, t in orders.items() if t["cancelled"]),
        cash_pickup_orders=sum(1 for o in known if o.gateway == "cash"),
        chf_orders=sorted(o.name for o in known if o.currency == "CHF"),
        automated_or_answered_mails=[m_["file"] for m_ in mails_t if not m_["needs_action"]],
        one_time_b2c_customers=sum(1 for c, n in Counter(o.cust.key for o in b2c).items() if n == 1),
    )
    by_state = Counter(t["state_true"] for t in orders.values())
    counts = dict(
        orders_known=len(known), orders_in_this_export=len(export), orders_b2b=sum(1 for o in known if o.b2b),
        orders_b2c=len(b2c), order_lines_known=sum(len(o.lines) for o in known),
        order_lines_in_this_export=sum(len(o.lines) for o in export), orders_by_true_state=dict(by_state),
        orders_by_shopify_status_in_export=dict(Counter(order_state(o, cut, world)["fin"] for o in export)),
        b2c_persons=len(persons), b2c_distinct_emails_in_files=len(emails), b2c_distinct_emails_casefolded=len(emails_folded),
        b2b_customers=len(b2b_companies), customers_total=len(persons) + len(b2b_companies),
        products_in_catalog=len({v.handle for v in world.catalog if not v.discontinued}),
        variants_in_catalog=sum(1 for v in world.catalog if not v.discontinued),
        skus_in_catalog=sum(1 for v in world.catalog if v.sku and not v.discontinued),
        skus_total_incl_discontinued=sum(1 for v in world.catalog if v.sku),
        skus_sold_known=len({ln.v.sku for o in known for ln in o.lines if ln.v.sku}),
        b2b_invoices=sum(1 for i in world.inv if i.d <= cut and i.kind == "Rechnung"),
        b2b_credit_notes=sum(1 for i in world.inv if i.d <= cut and i.kind == "Gutschrift"),
        bank_lines_in_this_file=files["bank"], bank_lines_known=sum(1 for t in world.bank if t.d <= cut),
        paypal_rows_in_this_file=files["paypal"], paypal_rows_known=sum(1 for p in world.pp if p.dt.date() <= cut),
        shopify_payments_rows_in_this_file=files["sp"], shopify_payments_rows_known=sum(1 for s in world.sp if s.dt.date() <= cut),
        klarna_rows_in_this_file=files["klarna"],
        klarna_rows_known=sum(1 for kr in world.kl if kr.payout_date and kr.payout_date <= cut),
        payouts=pays["counts"], returns_rma=len(rets), return_rows=files["returns"],
        suppliers=5, supplier_invoices_in_dump=len(sup["invoices"]), goods_receipt_rows=files["receipts"],
        inventory_rows=files.get("inventur"), mails_in_this_delivery=len(mails_t),
    )
    identity = dict(
        same_person_two_emails=[dict(name=c.name, emails=[c.email, c.alias_email], city=c.city,
                                     orders=[o.name for o in b2c if o.cust is c])
                                for key_, c in world.special.items() if key_.startswith("alias:")],
        same_name_different_people=[dict(name=c.name, email=c.email, city=c.city, orders=[o.name for o in b2c if o.cust is c])
                                    for key_, c in world.special.items() if key_.startswith("twin:")],
        email_in_capitals_once=sc.get("caps_done"),
        b2b_renamed_in_delivery_2="K-10010 Bike & Bean Café-Werkstatt UG (haftungsbeschränkt) -> Bike & Bean GmbH" if k == 2 else None,
        b2b_pays_from_private_account="K-10004 Zweirad Kowalski pays as 'Marek Kowalski'",
    )
    return dict(
        as_of=today.isoformat(), data_through=cut.isoformat(), delivery=k,
        firm="Ritzelwerk – Fahrradteile & Zubehör, Inh. Jana Brenner e.K., Osnabrück (fictional)",
        counts=counts, identity=identity, b2b=b2b, payouts=pays, stock=stock, suppliers=sup,
        returns=dict(all=rets, not_refunded=not_refunded), mails=mails_t,
        order_cases=dict(vorkasse_paid_not_marked=vk_paid_not_marked, vorkasse_unpaid_over_7_days=vk_unpaid_old,
                         vorkasse_underpaid=vk_under, paid_after_cancel=after_cancel, ship_now=ship_now,
                         backorders=backorders, all_waiting_for_shipment=waiting, unknown_money=unknown,
                         b2b_rhythm_break=rhythm, paypal_dispute=dispute),
        todo=sorted(todo, key=lambda x: x["priority"]), traps=traps, scenario={k_: (v if isinstance(v, (str, int, list, dict, bool)) and k_ not in ("kb_gu", "ds_gu") else str(v)) for k_, v in sc.items() if k_ not in ("kb_gu", "ds_gu", "kb_gu_pending")},
        orders=orders,
    )
