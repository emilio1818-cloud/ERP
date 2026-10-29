"""The simulated world of Ritzelwerk.  Day by day from 2026-01-01 to 2026-11-25."""
from __future__ import annotations

import math
import random
import string
from collections import defaultdict
from datetime import date, datetime, timedelta

from sim import (B2B, C, CITIES_AT, CITIES_CH, CITIES_DE, CITIES_NL, CUT, D1, D2, END, FIRM, FIRST_F, FIRST_M, HOL,
                 LAST, MAIL_DOMAINS, OWN_IBAN, SEED, START, STREETS, BankTx, Inv, KLRow, Line, Mail, Order, PPTx,
                 Receipt, Refund, Ret, SInv, SPTx, V, add_bdays, bday_on_or_after, build_b2b, build_catalog, de_iban,
                 iban, is_bday, next_bday, slug)

ALNUM = string.ascii_uppercase + string.digits
HOURS = [0.4, 0.2, 0.1, 0.05, 0.05, 0.1, 0.4, 1.0, 1.6, 2.0, 2.2, 2.4, 2.6, 2.4, 2.3, 2.3, 2.4, 2.8, 3.4, 3.9, 4.2, 3.8, 2.6, 1.2]
RATE = {1: 3.6, 2: 4.3, 3: 6.4, 4: 8.3, 5: 8.9, 6: 8.3, 7: 7.5, 8: 6.9, 9: 6.1, 10: 5.0, 11: 4.2, 12: 4.7}
WEEKDAY = [1.15, 1.05, 1.0, 1.0, 0.9, 0.85, 1.05]
SEASON = {"licht": {1: 2.2, 2: 1.8, 3: 1.2, 4: 0.7, 5: 0.4, 6: 0.35, 7: 0.35, 8: 0.5, 9: 1.2, 10: 2.5, 11: 2.8, 12: 2.6},
          "textil": {1: 0.5, 2: 0.6, 3: 1.0, 4: 1.5, 5: 1.6, 6: 1.5, 7: 1.3, 8: 1.1, 9: 0.9, 10: 0.6, 11: 0.5, 12: 0.5}}
TAX = {"DE": 0.19, "AT": 0.20, "NL": 0.21, "CH": 0.0}
TAXNAME = {"DE": "DE MwSt 19%", "AT": "AT USt 20%", "NL": "NL BTW 21%"}
PAYMETHOD = {"paypal": "PayPal Express Checkout", "shopify": "Shopify Payments", "klarna": "Klarna",
             "vorkasse": "Vorkasse (Überweisung)", "cash": "Barzahlung bei Abholung", "b2b": "Kauf auf Rechnung",
             "gc_paypal": "Geschenkgutschein + PayPal Express Checkout"}
PICKUP = "Abholung in Osnabrück (Hasestraße 41)"
SIELMANN_MAIL = [("SCH-28-SV", 20), ("SCH-28-AV", 10), ("KET-10", 6), ("KET-11", 6), ("BBS-B01S", 10), ("OEL-DRY", 12)]
CHF_EUR = 1.0330          # PayPal conversion incl. spread: 1 CHF = 1.0330 EUR


def poisson(rng, lam):
    L, k, p = math.exp(-lam), 0, 1.0
    while True:
        p *= rng.random()
        if p <= L:
            return k
        k += 1


def cents(x: float) -> int:
    return int(math.floor(x + 0.5))


class World:
    def __init__(self):
        self.r = random.Random(SEED)
        self.catalog = build_catalog(random.Random(SEED + 1))
        self.sku = {v.sku: v for v in self.catalog if v.sku}
        self.gift = {v.vtitle: v for v in self.catalog if v.gift}
        self.b2b = build_b2b(random.Random(SEED + 2))
        self.bb = {b.kno: b for b in self.b2b}
        self.cust: list[C] = []
        self.special: dict[str, C] = {}
        self.build_customers(random.Random(SEED + 3))
        self.orders: list[Order] = []
        self.no = 10234
        self.oid = 5912034411000
        self.on_hand: dict[str, int] = {}
        self.committed = defaultdict(int)
        self.on_order = defaultdict(int)
        self.deliveries = defaultdict(list)       # date -> [(supplier, [(sku, qty)], note)]
        self.receipts: list[Receipt] = []
        self.shipped: list[tuple] = []            # (date, sku, qty, order)
        self.restocked: list[tuple] = []          # (date, sku, qty, ret)
        self.bank: list[BankTx] = []
        self.pp: list[PPTx] = []
        self.sp: list[SPTx] = []
        self.kl: list[KLRow] = []
        self.inv: list[Inv] = []
        self.inv_seq = 0
        self.gu_seq = 0
        self.sinv: list[SInv] = []
        self.returns: list[Ret] = []
        self.mails: list[Mail] = []
        self.todo_vorkasse_pay = defaultdict(list)    # date -> [(order, amount, payer, purpose, iban)]
        self.b2b_pay = defaultdict(list)              # date -> [(inv, amount, purpose, channel)]
        self.marks = defaultdict(list)                # date -> [order]  (Jana marks Vorkasse paid)
        self.refund_due = defaultdict(list)           # date -> [ret]
        self.pickups = defaultdict(list)
        self.cancels = defaultdict(list)              # date -> [(order, reason)]
        self.b2b_next = {}
        self.vt_seq = 4100
        self.ls_seq = 381200
        self.ww_seq = 380
        self.kf_seq = 1150
        self.ship_count = defaultdict(lambda: defaultdict(int))   # month -> kind -> n
        self.notes = []
        self.scenario = {}
        self.forgotten = defaultdict(int)
        self.pending_restock = defaultdict(int)
        self.r_codes = random.Random(SEED + 9)

    # ------------------------------------------------------------------------------------------- helpers
    def code(self, n=17):
        return "".join(self.r_codes.choice(ALNUM) for _ in range(n))

    def uuid(self):
        h = "".join(self.r_codes.choice("0123456789abcdef") for _ in range(32))
        return f"{h[:8]}-{h[8:12]}-{h[12:16]}-{h[16:20]}-{h[20:]}"

    def build_customers(self, rng):
        doms = [d for d, _ in MAIL_DOMAINS]
        dw = [w for _, w in MAIL_DOMAINS]
        used = set()

        def mk(first, last, country=None, city=None, email=None, w=None):
            if country is None:
                x = rng.random()
                country = "DE" if x < 0.93 else "AT" if x < 0.97 else "NL" if x < 0.985 else "CH"
            if city is None:
                if country == "DE":
                    city = rng.choices(CITIES_DE, weights=[c[2] for c in CITIES_DE])[0][:2]
                else:
                    city = rng.choice({"AT": CITIES_AT, "NL": CITIES_NL, "CH": CITIES_CH}[country])
            if email is None:
                for _ in range(20):
                    style = rng.random()
                    loc = (f"{slug(first)}.{slug(last)}" if style < 0.45 else f"{slug(first)[0]}.{slug(last)}" if style < 0.6
                           else f"{slug(first)}{slug(last)}{rng.randint(1, 99)}" if style < 0.85 else f"{slug(last)}.{slug(first)}{rng.randint(60, 99)}")
                    dom = rng.choices(doms, weights=dw)[0]
                    if country == "AT" and rng.random() < 0.5:
                        dom = rng.choice(["gmx.at", "aon.at", "chello.at"])
                    if country == "CH" and rng.random() < 0.6:
                        dom = rng.choice(["bluewin.ch", "gmx.ch", "sunrise.ch"])
                    if country == "NL" and rng.random() < 0.6:
                        dom = rng.choice(["ziggo.nl", "kpnmail.nl", "hotmail.nl"])
                    email = f"{loc}@{dom}"
                    if email not in used:
                        break
            used.add(email)
            street = f"{rng.choice(STREETS)} {rng.randint(1, 140)}{rng.choice(['', '', '', 'a', 'b'])}"
            if country == "NL":
                street = f"{rng.choice(['Oude Markt', 'Langestraat', 'Kerkstraat', 'Molenweg'])} {rng.randint(1, 90)}"
            phone = {"DE": f"+49 1{rng.choice(['51', '52', '57', '60', '62', '70', '76'])} {rng.randint(1000000, 99999999)}",
                     "AT": f"+43 66{rng.randint(0, 9)} {rng.randint(100000, 9999999)}",
                     "NL": f"+31 6 {rng.randint(10000000, 99999999)}", "CH": f"+41 7{rng.randint(6, 9)} {rng.randint(1000000, 9999999)}"}[country]
            c = C(key=email, first=first, last=last, email=email, street=street, zip=city[0], city=city[1], country=country,
                  phone=phone if rng.random() < 0.55 else "", w=w if w is not None else rng.paretovariate(1.9),
                  marketing=rng.random() < 0.38)
            return c

        for i in range(2600):
            fem = rng.random() < 0.42
            first = rng.choice(FIRST_F if fem else FIRST_M)
            last = rng.choice(LAST)
            self.cust.append(mk(first, last))
        # identity traps
        # (a) the same person with two e-mail addresses (same name, same address)
        for first, last, alias in [("Lena", "Hoffmann", "lena.h@posteo.de"), ("Jürgen", "Tepe", "j.tepe@t-online.de"),
                                   ("Svenja", "Eilers", "svenja.eilers@icloud.com")]:
            c = mk(first, last, country="DE", w=14.0)
            c.alias_email = alias
            c.alias_note = "same person, second address"
            self.cust.append(c)
            self.special[f"alias:{first} {last}"] = c
        # (b) different people with the same name
        for first, last in [("Thomas", "Müller"), ("Anna", "Schmidt"), ("Michael", "Weber"), ("Julia", "Fischer")]:
            cities = rng.sample([c for c in CITIES_DE if not c[0].startswith("49")], 2)
            for k, city in enumerate(cities):
                c = mk(first, last, country="DE", city=city[:2], w=9.0)
                self.cust.append(c)
                self.special[f"twin:{first} {last}:{k}"] = c
        # (c) e-mail written once in capitals
        c = mk("Jonas", "Becker", country="DE", email="jonas.becker@gmx.de", w=14.0)
        self.cust.append(c)
        self.special["caps:Jonas Becker"] = c
        # scripted customers
        for key, first, last, email, city in [
            ("forgotten", "Sabine", "Krüger", "sabine.krueger71@web.de", ("30159", "Hannover")),
            ("latepay", "Dennis", "Rothert", "dennis.rothert@gmx.de", ("33602", "Bielefeld")),
            ("lindner", "Klaus", "Lindner", "k.lindner@t-online.de", ("48149", "Münster")),
            ("underpay", "Imke", "Gerdes", "imke.gerdes@posteo.de", ("26122", "Oldenburg")),
            ("gloves", "Hauke", "Janßen", "hauke.janssen@gmail.com", ("24103", "Kiel")),
            ("brakes", "Mehmet", "Öztürk", "m.oeztuerk@outlook.de", ("44135", "Dortmund")),
            ("vatinv", "Christina", "Haase", "christina.haase@web.de", ("50667", "Köln")),
            ("jersey", "Paula", "Siebert", "paula.siebert@gmail.com", ("04109", "Leipzig")),
            ("thanks", "Bernd", "Thiele", "bernd.thiele@freenet.de", ("37073", "Göttingen")),
            ("damaged", "Natalia", "Nowak", "natalia.nowak@gmx.de", ("10999", "Berlin")),
            ("refundwait", "Florian", "Dittmann", "florian.dittmann@web.de", ("90402", "Nürnberg")),
        ]:
            c = mk(first, last, country="DE", city=city, email=email, w=0.0)
            self.cust.append(c)
            self.special[key] = c
        self.rsg_members = [c for c in self.cust if c.zip.startswith("49") and c.w > 0][:14]

    def new_order(self, dt, cust, b2b, lines, currency, country, gateway, **kw) -> Order:
        self.oid += self.r.randint(1200, 90000)
        o = Order(no=self.no, created=dt, cust=cust, b2b=b2b, lines=lines, currency=currency, country=country,
                  tax_rate=0.0 if (b2b and b2b.reverse_charge) else TAX[country], gateway=gateway, shopify_id=self.oid,
                  checkout=f"c{self.r.randint(10 ** 13, 10 ** 14 - 1)}.1", **kw)
        self.no += 1
        self.orders.append(o)
        for ln in lines:
            if ln.v.sku:
                self.committed[ln.v.sku] += ln.qty
        return o

    def totals(self, o: Order):
        gross_items = sum(ln.price * ln.qty for ln in o.lines)
        o.disc = sum(ln.disc for ln in o.lines)
        o.subtotal = gross_items - o.disc
        o.total = o.subtotal + o.ship
        rate = o.tax_rate
        if rate:
            t = sum(cents((ln.price * ln.qty - ln.disc) * rate / (1 + rate)) for ln in o.lines if ln.v.taxable)
            t += cents(o.ship * rate / (1 + rate))
            o.taxes = t
        else:
            o.taxes = 0

    def available(self, sku):
        """What Shopify believes is available: physical stock minus open orders, minus receipts Tom forgot to book,
        minus returns that are back on the shelf but not yet refunded (Shopify restocks on refund)."""
        return self.on_hand.get(sku, 0) - self.committed[sku] - self.forgotten[sku] - self.pending_restock[sku]

    def arrive_return(self, ret, d):
        if ret.condition == "OK":
            for sku, q in ret.items:
                self.on_hand[sku] = self.on_hand.get(sku, 0) + q
                self.restocked.append((d, sku, q, ret))
                self.pending_restock[sku] += q

    # ------------------------------------------------------------------------------------------- demand model
    def b2c_share(self, d: date) -> dict:
        w = {}
        for v in self.catalog:
            if not v.sku or v.gift:
                continue
            f = SEASON.get(v.season, {}).get(d.month, 1.0) if v.season else 1.0
            if v.ptype == "Beleuchtung":
                f = SEASON["licht"][d.month]
            w[v.sku] = v.w * f
        return w

    def expected_rate(self, sku: str, d: date) -> float:
        """Expected units per day (B2C + B2B), used by the purchasing routine."""
        w = self.b2c_share(d)
        tot = sum(w.values())
        b2c = RATE.get(d.month, 3.0) * 1.75 * 1.25 * w.get(sku, 0) / tot
        b2b = 0.0
        for b in self.b2b:
            if not b.interval or (b.stop_after and d > b.stop_after):
                continue
            for s, lo, hi, p in b.basket:
                if s == sku:
                    b2b += p * (lo + hi) / 2 / b.interval
        return b2c + b2b

    # ------------------------------------------------------------------------------------------- B2C orders
    def pick_lines(self, d: date, k: int, country: str, rng) -> list[Line]:
        w = self.b2c_share(d)
        lines, taken = [], set()
        for _ in range(k):
            cand = []
            for sku, wt in w.items():
                v = self.sku[sku]
                if sku in taken or wt <= 0:
                    continue
                if v.discontinued and (d >= date(2026, 4, 15) or self.available(sku) <= 0):
                    continue
                if v.policy == "deny" and self.available(sku) <= 0:
                    continue
                if v.discontinued:
                    wt = 2.5
                cand.append((sku, wt))
            if not cand:
                break
            sku = rng.choices([c[0] for c in cand], weights=[c[1] for c in cand])[0]
            v = self.sku[sku]
            taken.add(sku)
            if v.ptype == "Schläuche" and sku.startswith("SCH"):
                q = rng.choices([1, 2, 4], weights=[50, 45, 5])[0]
            else:
                q = rng.choices([1, 2, 3], weights=[80, 17, 3])[0]
            if v.policy == "deny":
                q = max(1, min(q, self.available(sku)))
            price = v.price
            if country == "CH":
                price = math.ceil(v.price / 1.19 / 0.94 / 100) * 100 - 10
            lines.append(Line(v, q, price))
        return lines

    def b2c_order(self, dt: datetime, rng, cust: C | None = None, lines=None, gateway=None, code=None, ship_kind=None,
                  flags=()):
        d = dt.date()
        if cust is None:
            pool = [c for c in self.cust if c.w > 0]
            cust = rng.choices(pool, weights=[c.w for c in pool])[0]
        country = cust.country
        if lines is None:
            k = rng.choices([1, 2, 3, 4], weights=[45, 30, 15, 10])[0]
            lines = self.pick_lines(d, k, country, rng)
            if not lines:
                return None
        currency = "CHF" if country == "CH" else "EUR"
        first_order = not any(o.cust is cust for o in self.orders[-400:]) and not any(o.cust is cust for o in self.orders)
        # discount code
        pct, disc_code = 0.0, ""
        if code is not None:
            disc_code = code
            pct = {"WILLKOMMEN10": 0.10, "SOMMER15": 0.15, "RADLGRETA20": 0.20, "RSG-TEAM": 0.10, "VERSANDFREI": 0.0}.get(code, 0)
        elif country != "CH":
            x = rng.random()
            if cust in self.rsg_members and x < 0.7:
                disc_code, pct = "RSG-TEAM", 0.10
            elif first_order and x < 0.07:
                disc_code, pct = "WILLKOMMEN10", 0.10
            elif date(2026, 6, 15) <= d <= date(2026, 8, 31) and x < 0.10:
                disc_code, pct = "SOMMER15", 0.15
            elif date(2026, 4, 10) <= d <= date(2026, 5, 31) and x < 0.06:
                disc_code, pct = "RADLGRETA20", 0.20
            elif x < 0.03:
                disc_code = "VERSANDFREI"
        for ln in lines:
            ln.disc = cents(ln.price * ln.qty * pct) if pct and not ln.v.gift else 0
        items = sum(ln.price * ln.qty - ln.disc for ln in lines)
        only_gift = all(ln.v.gift for ln in lines)
        # shipping
        if only_gift:
            method, ship = "", 0
        elif country == "CH":
            method, ship = "DHL Paket Schweiz", 1990
        elif country in ("AT", "NL"):
            method, ship = "DHL Paket International", 0 if items >= 10000 else 1290
        else:
            near = cust.zip[:3] in ("490", "491", "495")
            if ship_kind == "pickup" or (ship_kind is None and near and rng.random() < 0.12):
                method, ship = PICKUP, 0
            elif ship_kind == "express" or (ship_kind is None and rng.random() < 0.04):
                method, ship = "DHL Express", 1290
            elif disc_code == "VERSANDFREI" or items >= 5000:
                method, ship = "DHL Paket (kostenlos ab 50 €)", 0
            else:
                method, ship = "DHL Paket", 490
        if gateway is None:
            if country == "CH":
                gateway = "paypal"
            elif method == PICKUP:
                gateway = rng.choices(["cash", "paypal", "shopify"], weights=[60, 25, 15])[0]
            else:
                opts = [("paypal", 42), ("shopify", 26), ("klarna", 20), ("vorkasse", 10 if country in ("DE", "AT") else 0)]
                gateway = rng.choices([g for g, _ in opts], weights=[w for _, w in opts])[0]
        o = self.new_order(dt, cust, None, lines, currency, country, gateway, disc_code=disc_code, ship_method=method,
                           ship=ship, flags=set(flags))
        if cust.alias_email:
            n_before = sum(1 for x in self.orders if x.cust is cust) - 1
            if n_before % 2 == 1:
                o.flags.add("alias_email")
        if cust is self.special.get("caps:Jonas Becker") and "caps_done" not in self.scenario:
            o.flags.add("caps_email")
            self.scenario["caps_done"] = o.name
        if method == PICKUP:
            o.tags.append("Abholung")
            pd = dt.date() + timedelta(days=rng.randint(1, 4))
            if pd.weekday() == 6:
                pd += timedelta(days=1)
            o.pickup_on = pd
            self.pickups[pd].append(o)
        if disc_code == "RSG-TEAM":
            o.tags.append("RSG")
        if rng.random() < 0.06 and not only_gift:
            o.notes = rng.choice(["Bitte beim Nachbarn abgeben, falls nicht da.", "Geschenk – bitte ohne Preise beilegen.",
                                  "Bitte an Packstation liefern, Postnummer steht in Adresszusatz.",
                                  "Kann das Paket bis Freitag da sein?", "Bitte Rechnung beilegen."])
        self.totals(o)
        self.pay_at_checkout(o, rng)
        if only_gift:
            o.fulfilled_at = dt + timedelta(minutes=1)
        return o

    def pay_at_checkout(self, o: Order, rng):
        dt = o.created
        if o.gateway in ("paypal", "gc_paypal"):
            o.paid_at = dt + timedelta(seconds=rng.randint(3, 40))
            amount = o.total - o.gc_amount
            if o.currency == "CHF":
                fee = -(cents(amount * 0.0498) + 50)
            else:
                fee = -(cents(amount * 0.0299) + 39)
            code = self.code()
            o.pp_code = code
            c = o.cust
            email = self.order_email(o)
            self.pp.append(PPTx(o.paid_at, c.name, "Express-Checkout-Zahlung", o.currency, amount, fee, code, "Haben",
                                sender=email, receiver="paypal@ritzelwerk.example",
                                item_title=f"Ritzelwerk Bestellung {o.name}", invoice_no=o.name, order=o, kind="sale",
                                address=dict(street=c.street, city=c.city, zip=c.zip, country=c.country)))
            if o.currency == "CHF":
                net = amount + fee
                eur = cents(net * CHF_EUR)
                t = o.paid_at + timedelta(seconds=2)
                self.pp.append(PPTx(t, "", "Allgemeine Währungsumrechnung", "CHF", -net, 0, self.code(), "Soll",
                                    related=code, order=o, kind="fx_out"))
                self.pp.append(PPTx(t, "", "Allgemeine Währungsumrechnung", "EUR", eur, 0, self.code(), "Haben",
                                    related=code, order=o, kind="fx_in"))
        elif o.gateway == "shopify":
            o.paid_at = dt + timedelta(seconds=self.r.randint(2, 25))
            brand = rng.choices(["visa", "master", "american_express", "apple_pay", "google_pay"], weights=[38, 34, 4, 18, 6])[0]
            method = {"apple_pay": "apple_pay", "google_pay": "google_pay"}.get(brand, "card")
            fee = -(cents(o.total * 0.021) + 30)
            self.sp.append(SPTx(o.paid_at, "charge", o, "visa" if brand in ("apple_pay", "google_pay") else brand,
                                o.total, fee, o.checkout, method))
        elif o.gateway == "klarna":
            o.authorized = True
        elif o.gateway == "vorkasse":
            self.plan_vorkasse(o, rng)
        elif o.gateway == "cash":
            pass

    def order_email(self, o: Order) -> str:
        c = o.cust
        if o.b2b:
            return o.b2b.shop_email or o.b2b.email
        if "caps_email" in o.flags:
            return "Jonas.Becker@GMX.DE"
        if "alias_email" in o.flags and c.alias_email:
            return c.alias_email
        return c.email

    # ------------------------------------------------------------------------------------------- Vorkasse
    def plan_vorkasse(self, o: Order, rng, force=None):
        d = o.created.date()
        c = o.cust
        if force == "never" or (force is None and rng.random() < 0.07):
            cday = bday_on_or_after(d + timedelta(days=15))
            self.cancels[cday].append((o, "Keine Zahlung eingegangen"))
            return
        delay = force if isinstance(force, int) else rng.choices([rng.randint(0, 3), rng.randint(4, 7), rng.randint(8, 13)],
                                                               weights=[60, 25, 15])[0]
        book = bday_on_or_after(d + timedelta(days=delay + 1))
        amount = o.total
        if force is None and o.ship and rng.random() < 0.02:
            amount = o.total - o.ship
            o.flags.add("underpaid")
        x = rng.random()
        num = str(o.no)
        if x < 0.35:
            purpose = f"Bestellung {o.name}"
        elif x < 0.55:
            purpose = f"{o.name}"
        elif x < 0.70:
            purpose = f"Bestellnummer {num}"
        elif x < 0.80:
            purpose = f"Ritzelwerk RW {num} {c.name}"
        elif x < 0.89:
            purpose = f"{c.name} Bestellung"
            o.flags.add("no_number")
        elif x < 0.95:
            purpose = rng.choice(["Kette und Schlauch", "Fahrradteile", "Onlinebestellung", "Ritzelwerk"])
            o.flags.add("no_number")
        else:
            wrong = str(o.no + rng.choice([-9, 9, -18, 27]))
            purpose = f"Bestellung RW-{wrong}"
            o.flags.add("wrong_number")
        y = rng.random()
        if y < 0.75:
            payer = c.name
        elif y < 0.90:
            other = rng.choice(FIRST_F if c.first not in FIRST_F else FIRST_M)
            payer = f"{other} {c.last}"
            o.flags.add("other_payer")
        else:
            payer = f"{c.last.upper()} {c.first.upper()}"
        if not c.iban:
            c.iban = de_iban(rng)
        self.todo_vorkasse_pay[book].append((o, amount, payer, purpose, c.iban))

    # ------------------------------------------------------------------------------------------- B2B
    def b2b_order(self, d: date, b: B2B, rng, lines_spec=None, hour=None):
        lines = []
        spec = lines_spec
        if spec is None:
            spec = []
            for sku, lo, hi, p in b.basket:
                if rng.random() < p:
                    q = rng.randint(lo, hi)
                    pk = 5 if sku.startswith("SCH") else 1
                    q = max(pk, int(round(q / pk)) * pk)
                    spec.append((sku, q))
            if len(spec) < 3:
                extra = [x for x in b.basket if x[0] not in {s for s, _ in spec}]
                for sku, lo, hi, p in extra[:3 - len(spec)]:
                    spec.append((sku, lo))
        for sku, q in spec:
            v = self.sku[sku]
            unit_net = cents(v.price / 1.19 * b.price_factor)
            price = unit_net if b.reverse_charge else cents(unit_net * 1.19)
            lines.append(Line(v, q, price, 0, unit_net))
        dt = datetime(d.year, d.month, d.day, hour if hour is not None else rng.randint(8, 12), rng.randint(0, 59), rng.randint(0, 59))
        goods_net = sum(ln.net_unit * ln.qty for ln in lines)
        local = b.zip.startswith("49")
        ship_net = 0 if (local or goods_net >= 15000) else 690
        ship = ship_net if b.reverse_charge else cents(ship_net * 1.19)
        method = "Lieferung durch Ritzelwerk" if local else "DHL Paket (gewerblich)"
        c = C(key=b.kno, first=b.first, last=b.last, email=b.email, street=b.street, zip=b.zip, city=b.city,
              country=b.country, phone=b.phone, w=0, marketing=False, company=b.name)
        o = self.new_order(dt, c, b, lines, "EUR", b.country, "b2b", ship_method=method, ship=ship)
        o.ship_net = ship_net
        o.tags += ["B2B", "Händler"] if b.kno != "K-10007" else ["B2B", "Verein"]
        o.company_at_order = b.name
        self.totals(o)
        if b.reverse_charge:
            o.taxes = 0
        return o

    def invoice_for(self, o: Order, d: date):
        b = o.b2b
        self.inv_seq += 1
        net = sum(ln.net_unit * ln.qty for ln in o.lines) + o.ship_net
        vat = 0 if b.reverse_charge else cents(net * 0.19)
        inv = Inv(no=f"RE2026-{self.inv_seq:03d}", d=d, cust=b, order=o, net=net, vat=vat, gross=net + vat,
                  due=d + timedelta(days=b.terms),
                  lines=[(ln.v.sku, ln.v.name, ln.qty, ln.net_unit) for ln in o.lines] + ([("VERSAND", "Versandkosten", 1, o.ship_net)] if o.ship_net else []))
        o.invoice = inv
        self.inv.append(inv)
        self.plan_b2b_payment(inv)
        return inv

    def credit_note(self, d: date, ref: Inv, lines, note):
        b = ref.cust
        self.gu_seq += 1
        net = sum(q * u for _, _, q, u in lines)
        vat = 0 if b.reverse_charge else cents(net * 0.19)
        gu = Inv(no=f"GU2026-{self.gu_seq:03d}", d=d, cust=b, order=None, net=-net, vat=-vat, gross=-(net + vat), due=d,
                 kind="Gutschrift", ref=ref, lines=[(s, n, q, -u) for s, n, q, u in lines], notes=note)
        self.inv.append(gu)
        return gu

    def plan_b2b_payment(self, inv: Inv):
        b, rng, no = inv.cust, self.r, inv.no
        num = no.split("-")[1]
        sc = self.scenario
        if b.pay == "exact":
            day = bday_on_or_after(inv.due + timedelta(days=rng.randint(-4, 1)))
            purpose = no if rng.random() < 0.9 else f"Rechnung {no} Kd-Nr. {b.kno}"
            self.b2b_pay[day].append((inv, inv.gross, purpose, "bank"))
        elif b.pay == "late":
            if inv.d >= date(2026, 8, 20):
                if "kb_open1" not in sc:
                    sc["kb_open1"] = no
                    gu = sc.pop("kb_gu_pending", None)
                    if gu:
                        sc["gu2"]["offset"] = no
                        self.b2b_pay[date(2026, 11, 10)].append((inv, inv.gross + gu.gross, f"RE2026{num} abzgl. Gutschrift {gu.no}", "bank"))
                    else:
                        self.b2b_pay[date(2026, 11, 10)].append((inv, inv.gross, f"RE2026{num}", "bank"))
                elif "kb_open2" not in sc:
                    sc["kb_open2"] = no          # stays unpaid through both deliveries
                else:
                    sc.setdefault("kb_more", []).append(no)
                    self.b2b_pay[bday_on_or_after(inv.due + timedelta(days=rng.randint(12, 30)))].append((inv, inv.gross, f"Rg {num}", "bank"))
                return
            day = bday_on_or_after(inv.due + timedelta(days=rng.randint(3, 20)))
            x = rng.random()
            purpose = (f"RE2026{num}" if x < 0.4 else f"Rg 2026-{int(num)}" if x < 0.7 else f"Rechnung vom {inv.d:%d.%m.}" if x < 0.85
                       else "Kettenblatt Rechnung")
            if "kb_gu" in sc and sc["kb_gu"]["inv"] is inv:
                gu = sc["kb_gu"]["gu"]
                self.b2b_pay[day].append((inv, inv.gross + gu.gross, f"{no} abzgl. Gutschrift {gu.no}", "bank"))
                return
            self.b2b_pay[day].append((inv, inv.gross, purpose, "bank"))
        elif b.pay == "early":
            day = bday_on_or_after(inv.d + timedelta(days=rng.randint(19, 25)))
            self.b2b_pay[day].append((inv, inv.gross, f"Re-Nr. {no}", "bank"))
        elif b.pay == "combine":
            pass  # paid by the Friday routine
        elif b.pay == "on_due":
            self.b2b_pay[bday_on_or_after(inv.due)].append((inv, inv.gross, f"{no} / Kst 4711 Fahrradstation", "bank"))
        elif b.pay == "slow":
            if inv.d >= date(2026, 7, 15) and "le_open" not in sc:
                sc["le_open"] = no
                self.b2b_pay[date(2026, 11, 24)].append((inv, inv.gross, f"{no} Lastesel", "bank"))
                return
            day = bday_on_or_after(inv.due + timedelta(days=rng.randint(5, 25)))
            self.b2b_pay[day].append((inv, inv.gross, f"Lastesel e.V. {no}", "bank"))
        elif b.pay == "club":
            if inv.d < date(2026, 7, 1):
                self.b2b_pay[bday_on_or_after(inv.d + timedelta(days=22))].append((inv, inv.gross, f"Vereinstrikots {no}", "bank"))
            else:
                part = cents(inv.gross * 0.8 / 100) * 100
                sc["rsg_partial"] = dict(inv=no, paid=part)
                self.b2b_pay[bday_on_or_after(inv.due)].append((inv, part, f"Anzahlung Teamtrikots {no}", "bank"))
                self.b2b_pay[date(2026, 11, 16)].append((inv, inv.gross - part, f"Rest {no} RSG", "bank"))
        elif b.pay == "skonto":
            sk = cents(inv.gross * 0.02)
            if inv.d >= date(2026, 10, 8) and "kurier_late_skonto" not in sc:
                day = bday_on_or_after(inv.d + timedelta(days=13))
                sc["kurier_late_skonto"] = dict(inv=no, deducted=sk, paid_on=day.isoformat())
                self.b2b_pay[day].append((inv, inv.gross - sk, f"{no} abzgl. 2% Skonto", "bank"))
                return
            day = bday_on_or_after(inv.d + timedelta(days=rng.randint(3, 6)))
            if day > inv.d + timedelta(days=7):
                day = inv.d + timedelta(days=7)
                while not is_bday(day):
                    day -= timedelta(days=1)
            self.b2b_pay[day].append((inv, inv.gross - sk, f"{no} abzgl. 2% Skonto", "bank"))
        elif b.pay == "nl":
            day = bday_on_or_after(inv.d + timedelta(days=rng.randint(24, 31)))
            if "ds_gu" in sc and sc["ds_gu"]["inv"] is inv:
                gu = sc["ds_gu"]["gu"]
                self.b2b_pay[day].append((inv, inv.gross + gu.gross, f"INV {no} MINUS CN {gu.no}", "bank"))
                return
            self.b2b_pay[day].append((inv, inv.gross, f"INV {no} DE SPAAK", "bank"))
        elif b.pay == "bean":
            if inv.d >= date(2026, 8, 25) and "bean_pp" not in sc:
                sc["bean_pp"] = no
                self.b2b_pay[bday_on_or_after(inv.d + timedelta(days=9))].append((inv, inv.gross, f"Rechnung {no}", "paypal"))
                return
            if inv.d >= date(2026, 9, 22) and "bean_double" not in sc:
                sc["bean_double"] = no
                d1 = bday_on_or_after(inv.due - timedelta(days=1))
                self.b2b_pay[d1].append((inv, inv.gross, no, "bank"))
                self.b2b_pay[next_bday(d1)].append((inv, inv.gross, f"{no}", "bank"))
                return
            day = bday_on_or_after(inv.due + timedelta(days=rng.randint(-3, 4)))
            self.b2b_pay[day].append((inv, inv.gross, no, "bank"))

    # ------------------------------------------------------------------------------------------- bank
    def book(self, d, name, ib, bic, btext, purpose, amount, kind, ref=None, cred="", mandate=""):
        tx = BankTx(d=d, name=name, iban=ib, bic=bic, btext=btext, purpose=purpose, amount=amount, kind=kind, ref=ref,
                    cred_id=cred, mandate=mandate, valuta=d, seq=len(self.bank))
        self.bank.append(tx)
        return tx

    # ------------------------------------------------------------------------------------------- the day loop
    def run(self):
        r = self.r
        self.initial_stock()
        self.schedule_suppliers()
        for b in self.b2b:
            if b.interval:
                self.b2b_next[b.kno] = bday_on_or_after(b.first_order)
        d = START
        while d <= END:
            self.day(d, r)
            d += timedelta(days=1)
        self.finish()

    def initial_stock(self):
        rng = random.Random(SEED + 5)
        for v in self.catalog:
            if not v.sku:
                continue
            if v.discontinued:
                self.on_hand[v.sku] = {"TRK-25-M": 9, "TRK-25-L": 7}[v.sku]
                continue
            rate = self.expected_rate(v.sku, date(2026, 1, 15))
            q = int(rate * rng.uniform(38, 60)) + rng.randint(2, 6)
            if v.pack > 1:
                q = int(math.ceil(q / v.pack) * v.pack)
            self.on_hand[v.sku] = q
        self.inventur = dict(self.on_hand)

    def schedule_suppliers(self):
        # Kartonfix (packaging) – fixed deliveries
        for d in [date(2026, 1, 20), date(2026, 3, 3), date(2026, 4, 14), date(2026, 5, 26), date(2026, 7, 7),
                  date(2026, 8, 18), date(2026, 9, 29), date(2026, 11, 10)]:
            self.deliveries[d].append(("Kartonfix", None, None))
        for d in [date(2026, 2, 12), date(2026, 5, 8), date(2026, 8, 6), date(2026, 10, 14), date(2026, 11, 5)]:
            self.deliveries[d].append(("Wollweber", "regular", None))

    def day(self, d: date, r):
        sc = self.scenario
        # supplier deliveries (morning)
        for sup, kind, payload in self.deliveries.get(d, []):
            self.receive(d, sup, kind, payload)
        # incoming money (bank)
        if is_bday(d):
            for o, amount, payer, purpose, ib in self.todo_vorkasse_pay.get(d, []):
                tx = self.book(d, payer, ib, "", "Gutschrift", purpose, amount, "vorkasse", o)
                o.money.append(dict(d=d, amount=amount, tx=tx))
                if o.cancelled_at is not None:
                    o.flags.add("paid_after_cancel")
                    continue
                if "hold_mark" in o.flags:
                    continue
                lag = 0 if r.random() < 0.4 else 1
                if "no_number" in o.flags or "other_payer" in o.flags or "wrong_number" in o.flags:
                    lag = r.choice([0, 1, 1, 3])
                mark = add_bdays(d, lag)
                self.marks[mark].append(o)
            for inv, amount, purpose, channel in self.b2b_pay.get(d, []):
                self.pay_b2b(d, inv, amount, purpose, channel)
            if d.weekday() == 4:
                self.kowalski_friday(d)
        else:
            # payments planned for a non-banking day slip to the next banking day
            nd = next_bday(d)
            self.todo_vorkasse_pay[nd] += self.todo_vorkasse_pay.pop(d, [])
            self.b2b_pay[nd] += self.b2b_pay.pop(d, [])
        # Jana marks Vorkasse orders as paid (morning)
        for o in self.marks.get(d, []):
            if o.cancelled_at is None and o.paid_at is None:
                paid = sum(m["amount"] for m in o.money)
                o.paid_at = datetime(d.year, d.month, d.day, 8, r.randint(5, 55), r.randint(0, 59))
                o.marked_paid_on = d
                if paid < o.total:
                    o.flags.add("partially_paid")
        if not is_bday(d) and self.marks.get(d):
            self.marks[next_bday(d)] += self.marks.pop(d)
        # scripted events of the day
        self.scripted(d, r)
        # cancellations
        for o, reason in self.cancels.get(d, []):
            if o.paid_at is None and o.fulfilled_at is None and o.cancelled_at is None:
                self.cancel(o, datetime(d.year, d.month, d.day, 9, r.randint(0, 59)), reason)
        # B2C orders of the day
        n = poisson(r, RATE[d.month] * WEEKDAY[d.weekday()])
        times = sorted(r.choices(range(24), weights=HOURS, k=n))
        for h in times:
            dt = datetime(d.year, d.month, d.day, h, r.randint(0, 59), r.randint(0, 59))
            o = self.b2c_order(dt, r)
            if o and o.gateway in ("paypal", "shopify", "klarna") and r.random() < 0.005 and o.fulfilled_at is None:
                o.flags.add("customer_cancel")
        # B2B orders (business days)
        if is_bday(d):
            for b in self.b2b:
                nxt = self.b2b_next.get(b.kno)
                if nxt and nxt <= d:
                    if b.stop_after and d > b.stop_after:
                        self.b2b_next[b.kno] = None
                        continue
                    if b.kno == "K-10001" and date(2026, 10, 12) <= d <= date(2026, 11, 10):
                        # this time they order by mail on 28.10. (see mails) – Jana enters it on 29.10.
                        self.b2b_next[b.kno] = date(2026, 11, 11) if d >= date(2026, 10, 29) else date(2026, 10, 29)
                        if d == date(2026, 10, 29):
                            o = self.b2b_order(d, b, r, lines_spec=SIELMANN_MAIL, hour=9)
                            self.scenario["sielmann_mail_order"] = o.name
                            self.b2b_next[b.kno] = date(2026, 11, 19)
                        continue
                    self.b2b_order(d, b, r)
                    step = int(round(b.interval * r.uniform(0.75, 1.3)))
                    self.b2b_next[b.kno] = bday_on_or_after(d + timedelta(days=step))
        # customer cancellations within hours
        for o in self.orders[-12:]:
            if "customer_cancel" in o.flags and o.cancelled_at is None and o.fulfilled_at is None and o.created.date() == d:
                self.cancel(o, o.created + timedelta(hours=r.randint(1, 6)), "Kunde hat storniert")
        # pickups (Mon–Sat)
        if d.weekday() < 6 and d not in HOL:
            for o in sorted(self.pickups.pop(d, []), key=lambda o: o.created):
                if o.cancelled_at:
                    continue
                if all(self.on_hand.get(ln.v.sku, 0) >= ln.qty for ln in o.lines if ln.v.sku):
                    t = datetime(d.year, d.month, d.day, r.randint(10, 17), r.randint(0, 59))
                    self.ship(o, t)
                    if o.gateway == "cash":
                        o.paid_at = t
                else:
                    self.pickups[d + timedelta(days=2)].append(o)
        elif self.pickups.get(d):
            self.pickups[d + timedelta(days=1)] += self.pickups.pop(d)
        # fulfilment (business days, afternoon)
        if is_bday(d):
            self.fulfil(d, r)
        # returns arriving and refunds
        if is_bday(d):
            for ret in [x for x in self.returns if x.arrived == d and not getattr(x, "scripted", False)]:
                self.arrive_return(ret, d)
            for ret in self.refund_due.pop(d, []):
                self.refund_return(ret, datetime(d.year, d.month, d.day, r.randint(9, 16), r.randint(0, 59)))
        elif self.refund_due.get(d):
            self.refund_due[next_bday(d)] += self.refund_due.pop(d)
        # purchasing (Monday) – VeloTrade, delivered Thursday
        if d.weekday() == 0 and is_bday(d):
            self.purchase_velotrade(d)
        # payouts
        if d.weekday() == 4 and is_bday(d):
            self.shopify_payout(d)
        if d.weekday() == 2 and is_bday(d):
            self.klarna_settlement(d)
        # recurring bank items
        self.recurring(d, r)
        # PayPal withdrawal at 06:30 on Mondays (Tuesday after a holiday Monday) – computed at the end of the
        # day so that everything that happened before 06:30 exists
        if d.weekday() == 0 or (d.weekday() == 1 and (d - timedelta(days=1)) in HOL):
            if is_bday(d):
                self.paypal_withdrawal(datetime(d.year, d.month, d.day, 6, 30))

    # ------------------------------------------------------------------------------------------- fulfilment
    def ready(self, o: Order, d: date) -> bool:
        if o.fulfilled_at or o.cancelled_at:
            return False
        if o.ship_method == PICKUP:
            return False
        if o.hold_until and d < o.hold_until:
            return False
        if o.b2b:
            return d > o.created.date()
        if o.gateway in ("paypal", "shopify", "gc_paypal"):
            return o.paid_at is not None and (o.created.date() < d or o.created.hour < 13)
        if o.gateway == "klarna":
            return o.created.date() < d or o.created.hour < 13
        if o.gateway == "vorkasse":
            return o.paid_at is not None
        return False

    def fulfil(self, d: date, r):
        for o in sorted((o for o in self.orders if self.ready(o, d)), key=lambda o: ("priority" not in o.flags, o.created)):
            if any(ln.v.sku and self.on_hand.get(ln.v.sku, 0) < ln.qty for ln in o.lines):
                o.flags.add("waited")
                continue
            t = datetime(d.year, d.month, d.day, r.randint(14, 17), r.randint(0, 59), r.randint(0, 59))
            self.ship(o, t)

    def ship(self, o: Order, t: datetime):
        o.fulfilled_at = t
        d = t.date()
        for ln in o.lines:
            if ln.v.sku:
                self.on_hand[ln.v.sku] -= ln.qty
                self.committed[ln.v.sku] -= ln.qty
                self.shipped.append((d, ln.v.sku, ln.qty, o))
        if o.ship_method != PICKUP and not all(ln.v.gift for ln in o.lines):
            kind = "express" if o.ship_method == "DHL Express" else "intl" if o.country != "DE" else "paket"
            self.ship_count[(d.year, d.month)][kind] += 1
        if o.gateway == "klarna":
            o.paid_at = t
            fee = -(cents(o.total * 0.0299) + 35)
            cap = self.uuid()
            kid = self.uuid()
            o.klarna_id = kid
            self.kl.append(KLRow("SALE", o, cap, kid, d, o.created.date(), o.total, o.taxes))
            self.kl.append(KLRow("FEE", o, cap, kid, d, o.created.date(), fee, 0))
        if o.b2b:
            self.invoice_for(o, d)
        elif o.ship_method != PICKUP:
            self.maybe_return(o, d)

    def maybe_return(self, o: Order, d: date):
        r = self.r
        if o.country == "CH" or o.gateway in ("cash",) or all(ln.v.gift for ln in o.lines) or "no_return" in o.flags:
            return
        textile = [ln for ln in o.lines if ln.v.ptype == "Bekleidung"]
        p = 0.15 if textile else 0.04
        if "force_return" not in o.flags and r.random() >= p:
            return
        if textile:
            items = [(ln.v.sku, ln.qty) for ln in textile]
            reason = "Größe passt nicht"
        elif r.random() < 0.3:
            items = [(ln.v.sku, ln.qty) for ln in o.lines if ln.v.sku]
            reason = r.choice(["Gefällt nicht", "Falsch bestellt", "Doppelt bestellt"])
        else:
            ln = r.choice([ln for ln in o.lines if ln.v.sku])
            items = [(ln.v.sku, ln.qty)]
            reason = r.choice(["Passt nicht ans Rad", "Falsch bestellt", "Defekt", "Gefällt nicht"])
        arrived = bday_on_or_after(d + timedelta(days=r.randint(5, 16)))
        cond = "OK" if r.random() < 0.85 and reason != "Defekt" else "beschädigt"
        amount = 0
        for sku, q in items:
            ln = next(x for x in o.lines if x.v.sku == sku)
            amount += ln.price * q - (cents(ln.disc * q / ln.qty) if ln.disc else 0)
        full = sorted(items) == sorted((ln.v.sku, ln.qty) for ln in o.lines if ln.v.sku)
        if full:
            amount += o.ship
        ret = Ret(rma="", order=o, arrived=arrived, items=items, reason=reason, condition=cond, refund_on=None,
                  amount=amount)
        ret.ship_part = o.ship if full else 0
        self.returns.append(ret)
        refund_day = add_bdays(arrived, r.randint(1, 3))
        ret.refund_on = refund_day
        self.refund_due[refund_day].append(ret)

    def refund_return(self, ret: Ret, t: datetime):
        o = ret.order
        if ret.refund_on and t.date() != ret.refund_on:
            ret.refund_on = t.date()
        ret.refund_on = t.date()
        if ret.condition == "OK":
            for sku, q in ret.items:
                self.pending_restock[sku] -= q
        full_amount = ret.amount
        rf = Refund(t, full_amount, ret.items, getattr(ret, "ship_part", 0), ret.reason, ret.rma)
        o.refunds.append(rf)
        self.money_back(o, t, full_amount, f"Retoure {ret.reason}")

    def money_back(self, o: Order, t: datetime, amount: int, why: str):
        if o.gateway in ("paypal", "gc_paypal"):
            self.pp.append(PPTx(t, o.cust.name, "Rückzahlung", o.currency, -amount, 0, self.code(), "Soll",
                                receiver=self.order_email(o), related=o.pp_code, invoice_no=o.name,
                                item_title=f"Ritzelwerk Bestellung {o.name}", order=o, kind="refund", note=why))
        elif o.gateway == "shopify":
            self.sp.append(SPTx(t, "refund", o, "", -amount, 0, o.checkout, "card"))
        elif o.gateway == "klarna":
            kid = getattr(o, "klarna_id", self.uuid())
            self.kl.append(KLRow("RETURN", o, self.uuid(), kid, t.date(), o.created.date(), -amount, 0))
        elif o.gateway == "vorkasse":
            d = bday_on_or_after(t.date())
            self.book(d, o.cust.name, o.cust.iban, "", "Überweisung", f"Erstattung {why} Bestellung {o.name}", -amount,
                      "refund_out", o)

    def cancel(self, o: Order, t: datetime, reason: str):
        o.cancelled_at = t
        o.cancel_reason = reason
        for ln in o.lines:
            if ln.v.sku:
                self.committed[ln.v.sku] -= ln.qty
        if o.paid_at and o.gateway in ("paypal", "shopify"):
            o.refunds.append(Refund(t, o.total, [(ln.v.sku, ln.qty) for ln in o.lines], o.ship, reason))
            self.money_back(o, t, o.total, "Stornierung")
        if o.gateway == "klarna":
            o.authorized = False

    # ------------------------------------------------------------------------------------------- B2B money
    def pay_b2b(self, d, inv: Inv, amount, purpose, channel):
        b = inv.cust
        if channel == "paypal":
            t = datetime(d.year, d.month, d.day, 11, 4, 51)
            fee = -(cents(amount * 0.0299) + 39)
            code = self.code()
            self.pp.append(PPTx(t, b.name.replace(" (haftungsbeschränkt)", ""), "Allgemeine Zahlung", "EUR", amount, fee,
                                code, "Haben", sender=b.email, receiver="paypal@ritzelwerk.example", subject=purpose,
                                note=f"{purpose} – danke!", kind="b2b_paypal", order=None))
            inv.payments.append(dict(d=d, amount=amount, channel="paypal", ref=purpose, exact=True, code=code))
            return
        payer = b.payer
        ib = b.iban
        if b.kno == "K-10004":
            payer, ib = "Marek Kowalski", self.kowalski_private_iban()
        tx = self.book(d, payer, ib, b.bic, "Gutschrift" if b.country == "DE" else "SEPA-Gutschrift", purpose, amount,
                       "b2b", inv)
        inv.payments.append(dict(d=d, amount=amount, channel="bank", ref=purpose, exact=inv.no in purpose, tx=tx.seq))

    def kowalski_private_iban(self):
        if not hasattr(self, "_kow_iban"):
            self._kow_iban = de_iban(random.Random(SEED + 77), "44010046")
        return self._kow_iban

    def kowalski_friday(self, d: date):
        b = self.bb["K-10004"]
        open_inv = [i for i in self.inv if i.cust is b and i.kind == "Rechnung" and not i.payments and i.due <= d + timedelta(days=7)]
        if not open_inv or (d.isocalendar()[1] % 2 == 1 and len(open_inv) < 2 and all(i.due > d for i in open_inv)):
            return
        if len(open_inv) == 1:
            purpose = f"Rechnung {open_inv[0].no}"
        else:
            nums = [i.no for i in open_inv]
            purpose = " ".join(nums[:1] + [n.split("-")[1] for n in nums[1:]]) if self.r.random() < 0.5 else " + ".join(nums)
        total = sum(i.gross for i in open_inv)
        tx = self.book(d, "Marek Kowalski", self.kowalski_private_iban(), "GENODEM1DOR", "Gutschrift", purpose, total,
                       "b2b", [i for i in open_inv])
        for i in open_inv:
            i.payments.append(dict(d=d, amount=i.gross, channel="bank", ref=purpose, exact=False, tx=tx.seq, combined=True))

    # ------------------------------------------------------------------------------------------- payouts
    def paypal_withdrawal(self, t: datetime):
        bal = sum(p.net for p in self.pp if p.cur == "EUR" and p.dt <= t and p.kind != "withdrawal"
                  and p.impact != "Memo") + sum(p.net for p in self.pp if p.kind == "withdrawal")
        if bal <= 0:
            return
        code = self.code()
        w = PPTx(t, "", "Allgemeine Abbuchung", "EUR", -bal, 0, code, "Soll", kind="withdrawal",
                 note="Abbuchung auf Bankkonto (Volksbank Hasetal eG, ...8823)")
        self.pp.append(w)
        for p in self.pp:
            if p.cur == "EUR" and p.dt <= t and not p.withdrawal and p.kind != "withdrawal":
                p.withdrawal = code
        bd = next_bday(t.date())
        tx = self.book(bd, "PayPal Europe S.a.r.l. et Cie S.C.A", iban("LU", "751" + "0001350400012E"[:13]), "PPLXLULL",
                       "Gutschrift", f"PAYPAL AUSZAHLUNG {code} RITZELWERK", bal, "paypal_payout", code)
        w.bank_seq = tx.seq

    def shopify_payout(self, f: date):
        cutoff = datetime(f.year, f.month, f.day) - timedelta(days=3) + timedelta(hours=23, minutes=59, seconds=59)
        txs = [s for s in self.sp if not s.payout_id and s.dt <= cutoff]
        if not txs:
            return
        pid = str(104587231 + 13 * len({s.payout_id for s in self.sp if s.payout_id}))
        for s in txs:
            s.payout_id, s.payout_date = pid, f
        total = sum(s.net for s in txs)
        bd = next_bday(f)
        self.book(bd, "SHOPIFY PAYMENTS EUROPE LTD", iban("IE", "BOFI" + "90001710027952"), "BOFIIE2D", "Gutschrift",
                  f"SHOPIFY PAYMENTS AUSZAHLUNG {pid} RITZELWERK", total, "shopify_payout", pid)

    def klarna_settlement(self, w: date):
        lo, hi = w - timedelta(days=9), w - timedelta(days=3)
        rows = [k for k in self.kl if not k.payout_ref and lo <= k.capture_date <= hi]
        if not rows:
            return
        ref = str(5240018 + len({k.payout_ref for k in self.kl if k.payout_ref}))
        for k in rows:
            k.payout_ref, k.payout_date = ref, w
        total = sum(k.amount for k in rows)
        bd = next_bday(w)
        self.book(bd, "Klarna Bank AB (publ)", iban("SE", "9500" + "0099604201234567"[:16]), "NDEASESS", "Gutschrift",
                  f"Klarna Settlement {ref} Ritzelwerk Payout {w:%d.%m.%Y}", total, "klarna_payout", ref)

    # ------------------------------------------------------------------------------------------- purchasing & receipts
    def purchase_velotrade(self, d: date):
        lines = []
        for v in self.catalog:
            if not v.sku or v.supplier != "VeloTrade" or v.discontinued:
                continue
            rate = self.expected_rate(v.sku, d + timedelta(days=10))
            pos = self.on_hand.get(v.sku, 0) + self.on_order[v.sku] - self.committed[v.sku]
            if pos < rate * 16 + 1:
                q = rate * 35 + v.pack - pos
                q = int(math.ceil(q / v.pack) * v.pack)
                if q > 0:
                    lines.append((v.sku, q))
                    self.on_order[v.sku] += q
        if lines:
            arrive = add_bdays(d, 3)
            self.deliveries[arrive].append(("VeloTrade", "order", lines))

    def receive(self, d: date, sup: str, kind, payload):
        rng = self.r
        if sup == "VeloTrade":
            self.ls_seq += rng.randint(40, 140)
            note = f"LS-{self.ls_seq}"
            for sku, q in payload:
                self.on_hand[sku] += q
                self.on_order[sku] -= q
                rc = Receipt(d, "VeloTrade Großhandel GmbH", note, sku, q)
                if (sku == "SLO-900" and d >= date(2026, 9, 20) and "forgot_mtl" not in self.scenario) or \
                   (sku == "BSV-70" and d >= date(2026, 8, 17) and "forgot_bsv" not in self.scenario):
                    rc.booked_in_shopify = False
                    self.forgotten[sku] += q
                    self.scenario["forgot_mtl" if sku == "SLO-900" else "forgot_bsv"] = dict(date=d.isoformat(), sku=sku, qty=q, note=note)
                self.receipts.append(rc)
            self.vt_seq += rng.randint(9, 23)
            lines = [(sku, self.sku[sku].name, q, self.sku[sku].cost) for sku, q in payload]
            net = sum(q * u for _, _, q, u in lines)
            if net < 30000:
                lines.append(("FRACHT", "Frachtkostenpauschale", 1, 990))
                net += 990
            vat = cents(net * 0.19)
            si = SInv("VeloTrade", f"VT-26-0{self.vt_seq}", d, lines, net, vat, net + vat, d + timedelta(days=30),
                      d + timedelta(days=10), 2.0, delivery_note=note)
            pay = d + timedelta(days=8)
            while not is_bday(pay):
                pay -= timedelta(days=1)
            si.paid = pay
            si.paid_amount = si.gross - cents(si.gross * 0.02)
            self.sinv.append(si)
        elif sup == "Wollweber":
            lines = []
            if kind == "rsg":
                self.receive_special(d, payload)
                return
            special = kind if kind not in ("regular", "nachlieferung") else None
            if special:
                lines = payload
            else:
                for v in self.catalog:
                    if v.supplier != "Wollweber" or not v.sku or v.discontinued:
                        continue
                    if d == date(2026, 10, 14):
                        # small Nachlieferung – Petrol in M is still not produced
                        if self.available(v.sku) < 3 and v.sku != "TRK-CL-M-PET":
                            lines.append((v.sku, 6))
                        continue
                    exp = sum(self.expected_rate(v.sku, d + timedelta(days=k)) for k in range(0, 100, 5)) * 5
                    if v.sku == "TRK-CL-M-PET" and d == date(2026, 8, 6):
                        exp *= 0.30       # under-ordered: sells out in October
                    q = int(math.ceil(exp - self.available(v.sku)))
                    if q > 0:
                        lines.append((v.sku, q))
            if not lines:
                return
            self.ww_seq += rng.randint(3, 11)
            note = f"WW-LS-{self.ww_seq + 9000}"
            for sku, q in lines:
                self.on_hand[sku] += q
                self.receipts.append(Receipt(d, "Wollweber Textildruck GmbH", note, sku, q))
            il = [(sku, self.sku[sku].name, q, self.sku[sku].cost) for sku, q in lines]
            net = sum(q * u for _, _, q, u in il)
            vat = cents(net * 0.19)
            si = SInv("Wollweber", f"WW-2026-0{self.ww_seq}", d, il, net, vat, net + vat, d + timedelta(days=30),
                      delivery_note=note)
            pay = si.due - timedelta(days=rng.randint(0, 3))
            si.paid = bday_on_or_after(pay) if bday_on_or_after(pay) <= si.due else pay
            while not is_bday(si.paid):
                si.paid -= timedelta(days=1)
            si.paid_amount = si.gross
            self.sinv.append(si)
        elif sup == "Kartonfix":
            self.kf_seq += rng.randint(5, 14)
            il = [("KF-S", "Versandkarton S 250x175x100, 100 Stk.", rng.randint(2, 4), 3290),
                  ("KF-M", "Versandkarton M 350x250x150, 100 Stk.", rng.randint(2, 5), 4690),
                  ("KF-L", "Versandkarton L 600x400x200, 50 Stk.", rng.randint(1, 2), 5980),
                  ("KF-FUELL", "Füllmaterial Papierpolster, Rolle 450 m", rng.randint(1, 3), 3850),
                  ("KF-KLEBE", "Papierklebeband 50 mm, 36 Rollen", 1, 6120)]
            net = sum(q * u for _, _, q, u in il)
            vat = cents(net * 0.19)
            si = SInv("Kartonfix", f"KF-26-{self.kf_seq}", d, il, net, vat, net + vat, d + timedelta(days=14),
                      delivery_note=f"KF-L{self.kf_seq}")
            if d == date(2026, 9, 29):
                si.paid = date(2026, 11, 3)
                si.reminder = date(2026, 11, 2)
                self.scenario["kartonfix_overdue"] = si.no
            else:
                si.paid = bday_on_or_after(d + timedelta(days=10))
            si.paid_amount = si.gross
            self.sinv.append(si)

    # ------------------------------------------------------------------------------------------- scripted scenarios
    def scripted(self, d: date, r):
        sc = self.scenario
        S = self.special
        rs = random.Random(SEED + d.toordinal())

        def at(h, m):
            return datetime(d.year, d.month, d.day, h, m, rs.randint(0, 59))

        def L(*pairs):
            out = []
            for sku, q in pairs:
                v = self.sku[sku] if sku in self.sku else self.gift[sku]
                out.append(Line(v, q, v.price))
            return out

        # --- gift cards
        gc_sales = {date(2026, 2, 10): "50 €", date(2026, 5, 8): "25 €", date(2026, 6, 14): "50 €",
                    date(2026, 9, 20): "25 €", date(2026, 10, 12): "50 €", date(2026, 10, 25): "25 €"}
        if d in gc_sales:
            o = self.b2c_order(at(19, 12), rs, lines=L((gc_sales[d], 1)), gateway=rs.choice(["paypal", "shopify"]), code="")
            o.tags.append("Gutschein")
            sc.setdefault("gc_sales", []).append(o.name)
        if d in (date(2026, 3, 2), date(2026, 7, 19), date(2026, 10, 20)):
            lines = L(("LCH-70", 1), ("OEL-DRY", 1)) if d.month != 7 else L(("TRK-CL-L-SNF", 1))
            de = [c for c in self.cust if c.w > 0 and c.country == "DE"]
            cust = de[100 + 7 * d.month]
            o = self.new_order(at(20, 41), cust, None, lines, "EUR", "DE", "gc_paypal", ship_method="DHL Paket (kostenlos ab 50 €)",
                               ship=0, disc_code="")
            self.totals(o)
            if o.total < 5000:
                o.ship, o.ship_method = 490, "DHL Paket"
                self.totals(o)
            o.gc_amount = 2500 if d.month != 7 else 5000
            o.tags.append("Gutschein eingelöst")
            o.flags.add("no_return")
            self.pay_at_checkout(o, rs)
            sc.setdefault("gc_redeemed", []).append(dict(order=o.name, gift_card=o.gc_amount, paypal=o.total - o.gc_amount))
        # --- RSG club kits (Wollweber produces for the club, the order follows the delivery)
        if d in (date(2026, 4, 9), date(2026, 9, 17)):
            big = d.month == 9
            spec = [("TRK-CL-S-PET", 3 if big else 2), ("TRK-CL-M-PET", 8 if big else 6), ("TRK-CL-L-PET", 9 if big else 7),
                    ("TRK-CL-XL-PET", 6 if big else 5), ("TRK-CL-XXL-PET", 4 if big else 2),
                    ("BIB-CL-S", 2 if big else 2), ("BIB-CL-M", 6 if big else 5), ("BIB-CL-L", 7 if big else 6),
                    ("BIB-CL-XL", 5 if big else 4)]
            o = self.b2b_order(d, self.bb["K-10007"], rs, lines_spec=spec, hour=10)
            o.flags.add("priority")
            sc.setdefault("rsg_orders", []).append(o.name)
            self.deliveries[add_bdays(d, 2)].append(("Wollweber", "rsg", spec))
        # --- credit notes
        if d == date(2026, 5, 12):
            b = self.bb["K-10001"]
            ref = [i for i in self.inv if i.cust is b and i.kind == "Rechnung" and i.d < d][-1]
            v = self.sku["KET-10"]
            gu = self.credit_note(d, ref, [("KET-10", v.name, 3, cents(v.price / 1.19 * 0.70))], "3 Ketten defekt (Reklamation)")
            self.book(add_bdays(d, 2), "Radhaus Sielmann GmbH", b.iban, b.bic, "Überweisung", f"Gutschrift {gu.no} zu {ref.no}",
                      gu.gross, "credit_out", gu)
            gu.payments.append(dict(d=add_bdays(d, 2), amount=gu.gross, channel="bank", ref=gu.no, exact=True))
            sc["gu1"] = gu.no
        if d == date(2026, 8, 4):
            b = self.bb["K-10002"]
            ref = [i for i in self.inv if i.cust is b and i.kind == "Rechnung"][-1]
            v = self.sku["KET-11"]
            gu = self.credit_note(d, ref, [("KET-11", v.name, 2, cents(v.price / 1.19 * 0.70))], "2 Ketten Transportschaden")
            if not ref.payments:
                # the planned payment of ref is replaced by one net of the credit note
                for day, lst in self.b2b_pay.items():
                    for x in list(lst):
                        if x[0] is ref:
                            lst.remove(x)
                            lst.append((ref, ref.gross + gu.gross, f"{ref.no} abzgl. Gutschrift {gu.no}", "bank"))
                sc["gu2"] = dict(no=gu.no, inv=ref.no, offset=ref.no)
            else:
                sc["kb_gu_pending"] = gu          # netted with the next payment
                sc["gu2"] = dict(no=gu.no, inv=ref.no, offset=None)
        if d == date(2026, 10, 12):
            b = self.bb["K-10009"]
            open_ = [i for i in self.inv if i.cust is b and i.kind == "Rechnung" and not i.payments]
            assert open_, "De Spaak has no open invoice on 12.10."
            ref = open_[-1]
            v = self.sku["KAS-11-34"]
            gu = self.credit_note(d, ref, [("KAS-11-34", f"Preiskorrektur {v.name}", 2, 680)], "Preiskorrektur Kassetten")
            sc["ds_gu"] = dict(inv=ref, gu=gu)
            for day, lst in self.b2b_pay.items():
                for x in list(lst):
                    if x[0] is ref:
                        lst.remove(x)
                        lst.append((ref, ref.gross + gu.gross, f"INV {ref.no} MINUS CN {gu.no}", "bank"))
            sc["gu3"] = dict(no=gu.no, inv=ref.no)
        # --- Vorkasse: paid after the order was cancelled
        if d == date(2026, 10, 1):
            o = self.new_order(at(19, 5), S["latepay"], None, L(("KET-11", 1), ("KSL-11", 1)), "EUR", "DE", "vorkasse",
                               ship_method="DHL Paket", ship=490)
            self.totals(o)
            self.cancels[date(2026, 10, 16)].append((o, "Keine Zahlung eingegangen"))
            self.todo_vorkasse_pay[date(2026, 10, 20)].append((o, o.total, "Dennis Rothert", f"Bestellung {o.name}",
                                                                de_iban(rs)))
            S["latepay"].iban = self.todo_vorkasse_pay[date(2026, 10, 20)][-1][4]
            sc["paid_after_cancel"] = o.name
        if d == date(2026, 10, 30) and "paid_after_cancel" in sc:
            o = next(x for x in self.orders if x.name == sc["paid_after_cancel"])
            o.refunds.append(Refund(at(10, 2), o.total, [], 0, "Zahlung nach Stornierung"))
            self.book(d, o.cust.name, o.cust.iban, "", "Überweisung", f"Rückzahlung Ihre Überweisung zu {o.name} (storniert)",
                      -o.total, "refund_out", o)
        # --- Vorkasse: someone else paid without a number; Jana cannot match it before 29.10.
        if d == date(2026, 10, 19):
            o = self.new_order(at(20, 14), S["lindner"], None, L(("MNT-STADT-42", 2)), "EUR", "DE", "vorkasse",
                               ship_method="DHL Paket (kostenlos ab 50 €)", ship=0)
            self.totals(o)
            o.flags.add("hold_mark")
            S["lindner"].iban = de_iban(rs)
            self.todo_vorkasse_pay[date(2026, 10, 22)].append((o, o.total, "Petra Lindner", "Fahrradteile", S["lindner"].iban))
            self.marks[date(2026, 10, 29)].append(o)
            sc["unmatched_vorkasse"] = o.name
        # --- Vorkasse underpaid (shipping forgotten)
        if d == date(2026, 10, 15):
            o = self.new_order(at(9, 31), S["underpay"], None, L(("SCH-28-SV", 2), ("FLK-SET", 1)), "EUR", "DE", "vorkasse",
                               ship_method="DHL Paket", ship=490)
            self.totals(o)
            o.flags.add("hold_mark")
            S["underpay"].iban = de_iban(rs)
            self.todo_vorkasse_pay[date(2026, 10, 19)].append((o, o.total - o.ship, "Imke Gerdes", f"Bestellung {o.name}",
                                                                S["underpay"].iban))
            self.marks[date(2026, 10, 20)].append(o)
            o.flags.add("underpaid")
            sc["underpaid"] = dict(order=o.name, missing=o.ship)
        # --- jersey M/Petrol: the last two go on 14.10., two more orders wait for the November delivery
        if d == date(2026, 10, 14):
            avail = self.available("TRK-CL-M-PET")
            if avail > 0:
                c = [x for x in self.cust if x.w > 0 and x.country == "DE"][333]
                o = self.b2c_order(at(12, 51), rs, cust=c, lines=L(("TRK-CL-M-PET", avail)), gateway="shopify", code="",
                                   ship_kind="paket")
                o.flags.add("no_return")
                sc["mpet_last"] = dict(order=o.name, qty=avail)
        if d in (date(2026, 10, 20), date(2026, 10, 22)):
            c = [x for x in self.cust if x.w > 0 and x.country == "DE"][444 + d.day]
            extra = ("HSH-M", 1) if d.day == 20 else ("FLH-SW", 1)
            o = self.b2c_order(at(19, 33), rs, cust=c, lines=L(("TRK-CL-M-PET", 1), extra),
                               gateway="paypal" if d.day == 20 else "shopify", code="", ship_kind="paket")
            o.flags.add("no_return")
            sc.setdefault("backorders", []).append(o.name)
        # --- forgotten parcel
        if d == date(2026, 10, 21):
            o = self.b2c_order(at(11, 42), rs, cust=S["forgotten"], lines=L(("LCH-70", 1), ("PMP-MINI", 1)), gateway="paypal",
                               code="", ship_kind="paket")
            o.hold_until = date(2026, 10, 29)
            o.flags.add("no_return")
            sc["forgotten"] = o.name
        # --- orders that the mails refer to
        if d == date(2026, 10, 16):
            o = self.b2c_order(at(18, 3), rs, cust=S["gloves"], lines=L(("HSH-L", 1), ("OEL-WET", 1)), gateway="klarna",
                               code="", ship_kind="paket")
            o.flags.add("no_return")
            sc["gloves_order"] = o.name
        if d == date(2026, 10, 19):
            o = self.b2c_order(at(7, 55), rs, cust=S["brakes"], lines=L(("BBS-J04C", 2)), gateway="shopify", code="",
                               ship_kind="paket")
            o.flags.add("no_return")
            sc["brakes_order"] = o.name
        if d == date(2026, 10, 13):
            o = self.b2c_order(at(12, 20), rs, cust=S["vatinv"], lines=L(("LCH-70", 1), ("LCH-RT", 1), ("SCH-28-SV", 2)),
                               gateway="paypal", code="", ship_kind="paket")
            o.flags.add("no_return")
            sc["vatinv_order"] = o.name
        if d == date(2026, 10, 9):
            o = self.b2c_order(at(21, 7), rs, cust=S["thanks"], lines=L(("SAT-155", 1)), gateway="paypal", code="",
                               ship_kind="paket")
            o.flags.add("no_return")
            sc["thanks_order"] = o.name
        if d == date(2026, 11, 16):
            o = self.b2c_order(at(8, 40), rs, cust=S["damaged"], lines=L(("PMP-STAND", 1)), gateway="shopify", code="",
                               ship_kind="paket")
            o.flags.add("no_return")
            sc["damaged_order"] = o.name
        if d == date(2026, 10, 30):
            o = self.b2c_order(at(17, 12), rs, cust=S["refundwait"], lines=L(("TRK-CL-L-PET", 1)), gateway="paypal", code="",
                               ship_kind="paket")
            o.flags.add("no_return")
            sc["refundwait_order"] = o.name
        # returns tied to mails (arrive in the second period)
        if d == date(2026, 11, 4) and "gloves_order" in sc:
            o = self.find(sc["gloves_order"])
            v = self.sku["HSH-L"]
            ret = Ret("", o, d, [("HSH-L", 1)], "Größe passt nicht", "OK", None, v.price)
            ret.ship_part = 0
            ret.scripted = True
            self.returns.append(ret)
            self.arrive_return(ret, d)
            ret.refund_on = date(2026, 11, 6)
            self.refund_due[date(2026, 11, 6)].append(ret)
        if d == date(2026, 11, 2) and "brakes_order" in sc:
            o = self.find(sc["brakes_order"])
            ret = Ret("", o, d, [("BBS-J04C", 2)], "Passt nicht ans Rad", "OK", None, 2 * 1290)
            ret.ship_part = 0
            ret.scripted = True
            self.returns.append(ret)
            self.arrive_return(ret, d)
            ret.refund_on = date(2026, 11, 4)
            self.refund_due[date(2026, 11, 4)].append(ret)
        if d == date(2026, 11, 12) and "refundwait_order" in sc:
            o = self.find(sc["refundwait_order"])
            ret = Ret("", o, d, [("TRK-CL-L-PET", 1)], "Größe passt nicht", "OK", None, 6900 + o.ship)
            ret.ship_part = o.ship
            ret.scripted = True
            self.returns.append(ret)
            self.arrive_return(ret, d)
            ret.refund_on = None      # not refunded before the second delivery
            sc["refundwait_return"] = True
        # --- a return of late September is simply forgotten (refunded only on 30.10.)
        if d == date(2026, 9, 29):
            cand = [x for x in self.returns if date(2026, 9, 24) <= x.arrived <= date(2026, 9, 29) and x.refund_on and x.refund_on >= d]
            if cand:
                ret = cand[0]
                self.refund_due[ret.refund_on].remove(ret)
                ret.refund_on = date(2026, 10, 30)
                self.refund_due[date(2026, 10, 30)].append(ret)
                sc["forgotten_return"] = dict(order=ret.order.name, arrived=ret.arrived.isoformat())
        # --- Mia is on holiday 19.–30.10.: refunds pile up and are done on 29./30.10.
        if d == date(2026, 10, 19):
            sc["mia_holiday"] = []
        if date(2026, 10, 19) <= d <= date(2026, 10, 28) and d in self.refund_due:
            for ret in self.refund_due.pop(d):
                nd = date(2026, 10, 29) if len(sc["mia_holiday"]) % 2 == 0 else date(2026, 10, 30)
                ret.refund_on = nd
                self.refund_due[nd].append(ret)
                sc["mia_holiday"].append(ret.order.name)
        # --- PayPal dispute
        if d == date(2026, 10, 24):
            cand = [o for o in self.orders if o.gateway == "paypal" and o.fulfilled_at and o.currency == "EUR"
                    and date(2026, 10, 1) <= o.fulfilled_at.date() <= date(2026, 10, 6) and o.total >= 4000 and not o.refunds]
            o = cand[0]
            t = at(10, 12)
            self.pp.append(PPTx(t, o.cust.name, "Einbehaltung für offenen Konflikt", "EUR", -o.total, 0, self.code(), "Soll",
                                related=o.pp_code, invoice_no=o.name, order=o, kind="hold", status="Ausstehend",
                                note="Konflikt PP-D-" + str(rs.randint(10 ** 9, 10 ** 10 - 1)) + ": Artikel nicht erhalten"))
            sc["dispute"] = dict(order=o.name, amount=o.total, opened="2026-10-24", customer=o.cust.name)
        if d == date(2026, 11, 6) and "dispute" in sc:
            o = self.find(sc["dispute"]["order"])
            self.pp.append(PPTx(at(14, 2), o.cust.name, "Aufhebung der Einbehaltung", "EUR", o.total, 0, self.code(), "Haben",
                                related=o.pp_code, invoice_no=o.name, order=o, kind="release"))
        # --- unknown money
        if d == date(2026, 10, 23):
            self.book(d, "Hermann Ostendorf", de_iban(rs, "26550105"), "", "Gutschrift", "Gutschein Weihnachten Enkel",
                      2500, "unknown")
            sc["unknown_money"] = dict(date="2026-10-23", amount=2500, payer="Hermann Ostendorf")
        # --- Meta ads via PayPal, 3rd of each month
        if d.day == 3:
            amt = rs.randint(14000, 32000)
            self.pp.append(PPTx(at(4, 12), "Meta Platforms Ireland Limited", "Zahlung im Einzugsverfahren mit Zahlungsrechnung",
                                "EUR", -amt, 0, self.code(), "Soll", receiver="ads@meta.example", kind="meta",
                                item_title="Facebook-Werbung", invoice_no=f"FBADS-{rs.randint(10 ** 9, 10 ** 10 - 1)}"))
        # --- Bike & Bean double payment refunded
        if d == date(2026, 11, 5) and "bean_double" in sc:
            inv = next(i for i in self.inv if i.no == sc["bean_double"])
            b = inv.cust
            self.book(d, "Bike & Bean GmbH", b.iban, b.bic, "Überweisung", f"Rückerstattung Doppelzahlung {inv.no}", -inv.gross,
                      "credit_out", inv)
            inv.payments.append(dict(d=d, amount=-inv.gross, channel="bank", ref="Rückerstattung Doppelzahlung", exact=True))
        # --- new B2B customer in November
        if d == date(2026, 11, 13):
            b = B2B("K-10011", "Radsport Ems GmbH", "Gerrit", "Wulf", "einkauf@radsport-ems.example", "Kaiserstraße 9",
                    "49808", "Lingen (Ems)", "DE", "+49 591 9122047", "DE330018762", 14, None, 0, d,
                    [], "exact", de_iban(rs, "26650001"), "RADSPORT EMS GMBH")
            b.bic = "GENODEF1XXX"
            self.b2b.append(b)
            self.bb[b.kno] = b
            o = self.b2b_order(d, b, rs, lines_spec=[("SCH-28-SV", 20), ("SCH-29-SV", 10), ("KET-11", 6), ("KET-12", 4),
                                                     ("BBS-B01S", 10), ("OEL-DRY", 12)], hour=9)
            sc["new_b2b_order"] = o.name
        # --- Bike & Bean renames itself on 3.11.
        if d == date(2026, 11, 3):
            self.bb["K-10010"].name_new = "Bike & Bean GmbH"
            self.bb["K-10010"].street_new = "Hasestraße 63"
            self.bb["K-10010"].zip_new = "49074"

    def receive_special(self, d, spec):
        self.ww_seq += 5
        note = f"WW-LS-{self.ww_seq + 9000}"
        for sku, q in spec:
            self.on_hand[sku] += q
            self.receipts.append(Receipt(d, "Wollweber Textildruck GmbH", note, sku, q))
        il = [(sku, f"{self.sku[sku].name} – Vereinsdruck RSG", q, self.sku[sku].cost + 350) for sku, q in spec]
        net = sum(q * u for _, _, q, u in il)
        vat = cents(net * 0.19)
        si = SInv("Wollweber", f"WW-2026-0{self.ww_seq}", d, il, net, vat, net + vat, d + timedelta(days=30), delivery_note=note)
        p = si.due - timedelta(days=2)
        while not is_bday(p):
            p -= timedelta(days=1)
        si.paid, si.paid_amount = p, si.gross
        self.sinv.append(si)

    def find(self, name) -> Order:
        return next(o for o in self.orders if o.name == name)

    # ------------------------------------------------------------------------------------------- recurring bank items
    def recurring(self, d: date, r):
        if not is_bday(d):
            return
        rs = random.Random(SEED * 3 + d.toordinal())
        first_bday = bday_on_or_after(d.replace(day=1)) == d
        nxt = next_bday(d)
        last_bday = nxt.month != d.month
        if first_bday:
            mon = ["Januar", "Februar", "März", "April", "Mai", "Juni", "Juli", "August", "September", "Oktober",
                   "November", "Dezember"][d.month - 1]
            self.book(d, "Gewerbehof Hasetor GmbH", iban("DE", "26550105" + "0000981127"), "NOLADE21OSN", "Dauerauftrag",
                      f"Miete Halle 3 inkl. NK {mon} 2026", -95000, "rent")
            self.book(d, "Haufe-Lexware GmbH & Co. KG", iban("DE", "68050101" + "0012418830"), "FRSPDE66XXX", "SEPA-Lastschrift",
                      f"lexoffice XL Abo {d:%m/%Y} Kd 5583921", -2190, "software", cred="DE36ZZZ00000167233",
                      mandate="LX-5583921")
        if last_bday:
            self.book(d, "Tom Wieczorek", iban("DE", "26550105" + "0004415511"), "NOLADE21OSN", "Lohn/Gehalt",
                      f"Lohn {d:%m/%Y}", -204837, "salary")
            self.book(d, "Mia Schulte", iban("DE", "26550105" + "0006617293"), "NOLADE21OSN", "Lohn/Gehalt",
                      f"Minijob {d:%m/%Y}", -60300, "salary")
            self.book(d, "Volksbank Hasetal eG", "", "", "Abschluss", f"Kontoführung {d:%m/%Y}", -1490, "bankfee")
        if d.day in (15, 16, 17) and bday_on_or_after(d.replace(day=15)) == d:
            self.book(d, "Minijob-Zentrale", iban("DE", "37050198" + "0001906011"), "COLSDE33XXX", "SEPA-Lastschrift",
                      f"Beiträge Minijob {d:%m/%Y} BNR 49870012", -18994, "social", cred="DE92ZZZ00000012345")
            self.book(d, "Techniker Krankenkasse", iban("DE", "20010020" + "0008771200"), "PBNKDEFFXXX", "SEPA-Lastschrift",
                      f"Beitragsnachweis {d:%m/%Y} BNR 49870012", -98366, "social", cred="DE88ZZZ00000058611")
        if d.day in (10, 11, 12) and bday_on_or_after(d.replace(day=10)) == d:
            prev = (d.replace(day=1) - timedelta(days=1))
            ust = self.vat_payable(prev)
            self.book(d, "Finanzamt Osnabrück-Land", iban("DE", "25000000" + "0025601511"), "MARKDEF1250", "SEPA-Lastschrift",
                      f"USt-VZ {prev:%m/%Y} StNr 66/123/45678", -ust, "tax", cred="DE12ZZZ00000001234")
            self.book(d, "Finanzamt Osnabrück-Land", iban("DE", "25000000" + "0025601511"), "MARKDEF1250", "SEPA-Lastschrift",
                      f"LSt {prev:%m/%Y} StNr 66/123/45678", -27150, "tax", cred="DE12ZZZ00000001234")
        if d.day in (20, 21, 22) and bday_on_or_after(d.replace(day=20)) == d:
            self.book(d, "Telekom Deutschland GmbH", iban("DE", "30010700" + "0222222222"), "DEUTDEDDXXX", "SEPA-Lastschrift",
                      f"Kd-Nr 4471230051 Rechnung {d:%m/%Y}", -5995, "phone", cred="DE79ZZZ00000082231")
            self.book(d, "VR Bank Kreditkarte", "", "", "Kartenabrechnung", f"Mastercard Business Abrechnung {d:%m/%Y}",
                      -(3600 + 2900 + rs.randint(4000, 18000)), "creditcard")
        if d.month in (1, 4, 7, 10) and d.day in (15, 16, 17) and bday_on_or_after(d.replace(day=15)) == d:
            self.book(d, "Hanse Assekuranz AG", iban("DE", "20050550" + "1211993388"), "HASPDEHHXXX", "SEPA-Lastschrift",
                      "Betriebshaftpflicht + Inhalt Vers.-Nr. BH-2209118 Quartal", -31240, "insurance", cred="DE55ZZZ00000077123")
        if d.day in (25, 26, 27) and bday_on_or_after(d.replace(day=25)) == d:
            self.book(d, "Jana Brenner", iban("DE", "26550105" + "0007710441"), "NOLADE21OSN", "Überweisung", "Privatentnahme",
                      -220000, "private")
        # supplier invoices to pay today
        for si in self.sinv:
            if si.paid == d and si.supplier in ("VeloTrade", "Wollweber", "Kartonfix") and not getattr(si, "_booked", False):
                si._booked = True
                if si.supplier == "VeloTrade":
                    self.book(d, "VeloTrade Großhandel GmbH", iban("DE", "48050161" + "0071188830"), "SPBIDE3BXXX",
                              "Überweisung", f"{si.no} abzgl. 2% Skonto Kd-Nr. 40877", -si.paid_amount, "supplier", si)
                elif si.supplier == "Wollweber":
                    self.book(d, "Wollweber Textildruck GmbH", iban("DE", "26050001" + "0058812271"), "NOLADE21GOE",
                              "Überweisung", f"Rechnung {si.no}", -si.paid_amount, "supplier", si)
                else:
                    self.book(d, "Kartonfix Verpackungen GmbH", iban("DE", "70020270" + "0659912210"), "HYVEDEMMXXX",
                              "Überweisung", f"RG {si.no}", -si.paid_amount, "supplier", si)
        # DHL monthly invoice: 3rd business day of the month for the previous month; debited 10 days later
        if add_bdays(d.replace(day=1) - timedelta(days=1), 3) == d:
            prev = d.replace(day=1) - timedelta(days=1)
            cnt = self.ship_count.get((prev.year, prev.month), {})
            if cnt:
                lines = [("PAKET", "DHL Paket national bis 5 kg", cnt.get("paket", 0), 439),
                         ("EXPRESS", "DHL Express national", cnt.get("express", 0), 1190),
                         ("INTL", "DHL Paket International (EU)", cnt.get("intl", 0), 1350)]
                lines = [x for x in lines if x[2]]
                net = sum(q * u for _, _, q, u in lines)
                vat = cents(net * 0.19)
                no = f"50{23 * 10 ** 6 + prev.month * 10007 + 41:08d}"
                si = SInv("DHL", no, d, lines, net, vat, net + vat, bday_on_or_after(d + timedelta(days=10)), direct_debit=True,
                          period=f"{prev:%m/%Y}")
                si.paid, si.paid_amount = si.due, si.gross
                self.sinv.append(si)
        for si in self.sinv:
            if si.supplier == "DHL" and si.paid == d:
                self.book(d, "DHL Paket GmbH", iban("DE", "37010050" + "0000920504"), "PBNKDEFFXXX", "SEPA-Lastschrift",
                          f"Rechnung {si.no} Kd-Nr 6312345678 Abrechnung {si.period}", -si.gross, "supplier", si,
                          cred="DE07ZZZ00000040212", mandate="6312345678-001")
        # Google Ads: invoice 1st business day, debited 3 business days later
        if bday_on_or_after(d.replace(day=1)) == d and d.month > 1:
            prev = d.replace(day=1) - timedelta(days=1)
            amt = rs.randint(28000, 69000)
            no = f"52{(prev.month * 7919 + 1000003):08d}"
            si = SInv("Google", no, d, [("ADS", f"Google Ads {prev:%m/%Y} Konto 412-889-2071", 1, amt)], amt, 0, amt,
                      add_bdays(d, 3), direct_debit=True, period=f"{prev:%m/%Y}")
            si.paid, si.paid_amount = si.due, si.gross
            self.sinv.append(si)
        for si in self.sinv:
            if si.supplier == "Google" and si.paid == d:
                self.book(d, "Google Ireland Limited", iban("IE", "CITI" + "99005112345678"), "CITIIE2X", "SEPA-Lastschrift",
                          f"Google Ads 412-889-2071 Rechnung {si.no}", -si.gross, "supplier", si, cred="IE70ZZZ300123",
                          mandate="GOOGLE-ADS-4128892071")

    def vat_payable(self, month_end: date) -> int:
        """USt-Voranmeldung of a month: output VAT (B2C fulfilled + B2B invoices) minus input VAT; at least 0."""
        y, m = month_end.year, month_end.month
        out = sum(o.taxes for o in self.orders if o.fulfilled_at and (o.fulfilled_at.year, o.fulfilled_at.month) == (y, m)
                  and not o.b2b and o.country == "DE")
        out += sum(i.vat for i in self.inv if (i.d.year, i.d.month) == (y, m))
        inp = sum(s.vat for s in self.sinv if (s.d.year, s.d.month) == (y, m))
        return max(0, out - inp)

    # ------------------------------------------------------------------------------------------- end
    def finish(self):
        # RMA numbers in order of arrival; the sheet lags for one refund
        self.returns.sort(key=lambda x: (x.arrived, x.order.no))
        for i, ret in enumerate(self.returns, 1):
            ret.rma = f"RT-26-{i:03d}"
            for rf in ret.order.refunds:
                if rf.items == ret.items and not rf.rma:
                    rf.rma = ret.rma
        rng = random.Random(SEED + 11)
        for ret in self.returns:
            ret.sheet_refund_on = ret.refund_on
            x = rng.random()
            n = ret.order.no
            ret.sheet_order_text = (f"RW-{n}" if x < 0.6 else f"{n}" if x < 0.8 else f"rw{n}" if x < 0.9 else f"RW {n}")
        lagging = [x for x in self.returns if x.refund_on and date(2026, 10, 20) <= x.refund_on <= date(2026, 10, 27)]
        if lagging:
            lagging[0].sheet_lag = True
            self.scenario["sheet_lag"] = lagging[0].rma
        # bank: sort by day, then sequence; running balance
        self.bank.sort(key=lambda t: (t.d, t.seq))
        bal = 2138455
        for t in self.bank:
            bal += t.amount
            t.balance = bal
        self.opening_balance = 2138455
        # PayPal running balances per currency
        self.pp.sort(key=lambda p: (p.dt, 0 if p.kind != "withdrawal" else 1))
        bals = defaultdict(int)
        for p in self.pp:
            if p.impact != "Memo":
                bals[p.cur] += p.net
            p.balance = bals[p.cur]
