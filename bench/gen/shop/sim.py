"""Ritzelwerk – Fahrradteile & Zubehör (fictional online shop, Osnabrück, 4 people).

World simulation 2026-01-01 .. 2026-11-25, seeded and deterministic.  Money is kept in integer cents.
Everything a file shows is derived from this world, so the ground truth is exact.
"""
from __future__ import annotations

import math
import random
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta

SEED = 20261029
START = date(2026, 1, 1)
D1 = date(2026, 10, 29)          # day of the first delivery (exports made in the morning)
D2 = date(2026, 11, 26)          # day of the second delivery
CUT = {1: D1 - timedelta(days=1), 2: D2 - timedelta(days=1)}
END = CUT[2]
HOL = {date(2026, 1, 1), date(2026, 4, 3), date(2026, 4, 6), date(2026, 5, 1), date(2026, 5, 14), date(2026, 5, 25),
       date(2026, 10, 3), date(2026, 10, 31), date(2026, 12, 25), date(2026, 12, 26)}

FIRM = dict(name="Ritzelwerk", legal="Ritzelwerk – Fahrradteile & Zubehör, Inh. Jana Brenner e.K.",
            street="Hasestraße 41", zip="49074", city="Osnabrück", email="info@ritzelwerk.example",
            vat_id="DE318804712", owner="Jana Brenner")


def is_bday(d: date) -> bool:
    return d.weekday() < 5 and d not in HOL


def next_bday(d: date) -> date:
    d += timedelta(days=1)
    while not is_bday(d):
        d += timedelta(days=1)
    return d


def bday_on_or_after(d: date) -> date:
    while not is_bday(d):
        d += timedelta(days=1)
    return d


def add_bdays(d: date, n: int) -> date:
    for _ in range(n):
        d = next_bday(d)
    return d


def iban(country: str, bban: str) -> str:
    s = bban + country + "00"
    num = "".join(str(int(ch, 36)) for ch in s)
    return f"{country}{98 - int(num) % 97:02d}{bban}"


def de_iban(rng: random.Random, blz: str | None = None) -> str:
    blz = blz or rng.choice(["25050180", "26550105", "28050100", "20050550", "30050110", "37050198", "44050199",
                             "50050201", "70150000", "10050000", "26590025", "28590075", "76050101", "86055592"])
    return iban("DE", blz + f"{rng.randint(0, 9999999999):010d}")


OWN_IBAN = iban("DE", "26591234" + "0004718823")
OWN_BIC = "GENODEF1HTL"

FIRST_F = ["Anna", "Lena", "Julia", "Laura", "Sarah", "Lisa", "Katharina", "Marie", "Sophie", "Hannah", "Lea", "Johanna",
           "Sabine", "Petra", "Claudia", "Andrea", "Nicole", "Stefanie", "Christina", "Melanie", "Miriam", "Jana",
           "Frauke", "Imke", "Wiebke", "Greta", "Carla", "Paula", "Nina", "Svenja", "Kerstin", "Birgit", "Ute", "Heike",
           "Marta", "Agnieszka", "Elif", "Ayşe", "Zeynep", "Fatma", "Olga", "Natalia"]
FIRST_M = ["Thomas", "Michael", "Andreas", "Stefan", "Christian", "Markus", "Jan", "Tobias", "Florian", "Sebastian",
           "Lukas", "Jonas", "Felix", "Max", "Paul", "Tim", "Niklas", "Philipp", "Daniel", "Matthias", "Martin", "Frank",
           "Jens", "Dirk", "Sven", "Uwe", "Hauke", "Fiete", "Ole", "Jannik", "Malte", "Bernd", "Klaus", "Jürgen",
           "Mehmet", "Murat", "Piotr", "Marek", "Dmitri", "Luca", "Mats", "Henning"]
LAST = ["Müller", "Schmidt", "Schneider", "Fischer", "Weber", "Meyer", "Wagner", "Becker", "Schulz", "Hoffmann",
        "Schäfer", "Koch", "Bauer", "Richter", "Klein", "Wolf", "Schröder", "Neumann", "Schwarz", "Zimmermann",
        "Braun", "Krüger", "Hofmann", "Hartmann", "Lange", "Schmitt", "Werner", "Schmitz", "Krause", "Meier",
        "Lehmann", "Schmid", "Schulze", "Maier", "Köhler", "Herrmann", "König", "Walter", "Mayer", "Huber", "Kaiser",
        "Fuchs", "Peters", "Lang", "Scholz", "Möller", "Weiß", "Jung", "Hahn", "Schubert", "Vogel", "Friedrich",
        "Keller", "Günther", "Frank", "Berger", "Winkler", "Roth", "Beck", "Lorenz", "Baumann", "Franke", "Albrecht",
        "Janßen", "Ostendorf", "Brinkmann", "Tepe", "Kampmann", "Rolfes", "Niemeyer", "Wessels", "Göken", "Rothert",
        "Kowalczyk", "Nowak", "Yılmaz", "Demir", "Öztürk", "Lindner", "Brandt", "Haase", "Sommer", "Heinrich",
        "Ernst", "Dittmann", "Siebert", "Thiele", "Wulf", "Bruns", "Behrens", "Gerdes", "Hinrichs", "Eilers"]
STREETS = ["Hauptstraße", "Bahnhofstraße", "Gartenstraße", "Schulstraße", "Dorfstraße", "Lindenweg", "Birkenweg",
           "Am Markt", "Kirchstraße", "Mühlenweg", "Wiesenweg", "Ringstraße", "Bergstraße", "Feldstraße", "Rosenstraße",
           "Goethestraße", "Schillerstraße", "Hafenstraße", "Deichstraße", "Heideweg", "Eichendorffstraße", "Am Ring",
           "Lerchenweg", "Ahornallee", "Kastanienallee", "Beethovenstraße", "Uhlandstraße", "Fliederweg", "Moorweg"]
CITIES_DE = [("49074", "Osnabrück", 10), ("49076", "Osnabrück", 6), ("49080", "Osnabrück", 5), ("49134", "Wallenhorst", 2),
             ("49084", "Osnabrück", 4), ("49565", "Bramsche", 2), ("49610", "Quakenbrück", 1), ("49377", "Vechta", 1.5),
             ("28195", "Bremen", 5), ("28203", "Bremen", 4), ("20095", "Hamburg", 6), ("22765", "Hamburg", 5),
             ("48143", "Münster", 6), ("48149", "Münster", 4), ("44135", "Dortmund", 4), ("50667", "Köln", 7),
             ("50823", "Köln", 4), ("80331", "München", 6), ("81667", "München", 4), ("10115", "Berlin", 6),
             ("10999", "Berlin", 6), ("12047", "Berlin", 4), ("04109", "Leipzig", 4), ("01067", "Dresden", 3),
             ("30159", "Hannover", 5), ("33602", "Bielefeld", 4), ("26122", "Oldenburg", 3), ("24103", "Kiel", 3),
             ("18055", "Rostock", 2), ("60311", "Frankfurt am Main", 5), ("70173", "Stuttgart", 4), ("90402", "Nürnberg", 3),
             ("97070", "Würzburg", 2), ("34117", "Kassel", 2), ("37073", "Göttingen", 2), ("38100", "Braunschweig", 2),
             ("39104", "Magdeburg", 1.5), ("99084", "Erfurt", 1.5), ("06108", "Halle (Saale)", 1.5), ("55116", "Mainz", 2),
             ("66111", "Saarbrücken", 1), ("76133", "Karlsruhe", 2), ("79098", "Freiburg im Breisgau", 3),
             ("86150", "Augsburg", 1.5), ("93047", "Regensburg", 1.5), ("53111", "Bonn", 2), ("45127", "Essen", 2),
             ("47051", "Duisburg", 1), ("42103", "Wuppertal", 1), ("32423", "Minden", 1), ("49808", "Lingen (Ems)", 1.5),
             ("48529", "Nordhorn", 1), ("26603", "Aurich", 1), ("21335", "Lüneburg", 1.5), ("23552", "Lübeck", 1.5),
             ("35037", "Marburg", 1.5), ("72070", "Tübingen", 2), ("69117", "Heidelberg", 2)]
CITIES_AT = [("1070", "Wien"), ("1020", "Wien"), ("5020", "Salzburg"), ("6020", "Innsbruck"), ("8010", "Graz"), ("4020", "Linz")]
CITIES_NL = [("7511 JE", "Enschede"), ("3511 AB", "Utrecht"), ("6811 CA", "Arnhem"), ("9711 HE", "Groningen")]
CITIES_CH = [("8004", "Zürich"), ("3011", "Bern"), ("4051", "Basel"), ("9000", "St. Gallen")]
MAIL_DOMAINS = [("web.de", 18), ("gmx.de", 18), ("gmail.com", 22), ("t-online.de", 8), ("posteo.de", 5),
                ("mailbox.org", 3), ("outlook.de", 6), ("icloud.com", 6), ("freenet.de", 2), ("yahoo.de", 2)]

# ----------------------------------------------------------------------------------------------- catalog
SIZE_W = {"S": 0.6, "M": 1.2, "L": 1.1, "XL": 0.7, "XXL": 0.3}


@dataclass
class V:
    sku: str | None
    handle: str
    title: str
    vtitle: str | None
    opts: list
    price: int            # gross EUR cents (B2C, incl. 19 %)
    cost: int             # purchase net cents
    vendor: str
    supplier: str
    grams: int
    w: float              # B2C popularity
    ptype: str
    ship: bool = True
    taxable: bool = True
    gift: bool = False
    season: str = ""
    policy: str = "deny"
    pack: int = 5
    ean: str = ""
    discontinued: bool = False

    @property
    def name(self):
        return f"{self.title} - {self.vtitle}" if self.vtitle else self.title

    @property
    def dealer_net(self):
        return int(round(self.price / 1.19 * 0.70))


def _ean(rng, n):
    base = "20" + f"{n:010d}"
    s = sum(int(c) * (1 if i % 2 == 0 else 3) for i, c in enumerate(base))
    return base + str((10 - s % 10) % 10)


def build_catalog(rng: random.Random) -> list[V]:
    vs: list[V] = []

    def add(handle, title, vendor, supplier, ptype, rows, **kw):
        for r in rows:
            vs.append(V(handle=handle, title=title, vendor=vendor, supplier=supplier, ptype=ptype, **r, **kw))

    tubes = []
    for size, code, sw in [('26"', "26", 1.0), ('27,5"', "275", 1.0), ('28" / 700c', "28", 3.2), ('29"', "29", 1.0)]:
        for valve, vcode, price, cost, vw in [("SV (Sclaverand)", "SV", 690, 210, 1.0), ("AV (Autoventil)", "AV", 650, 195, 0.8)]:
            tubes.append(dict(sku=f"SCH-{code}-{vcode}", vtitle=f"{size} / {valve.split(' ')[0]}",
                              opts=[("Größe", size), ("Ventil", valve)], price=price, cost=cost, grams=110, w=3.0 * sw * vw, pack=10))
    add("fahrradschlauch-pendlerpro", "Fahrradschlauch Pendlerpro", "Pendlerpro", "VeloTrade", "Schläuche", tubes)
    add("faltreifen-pendlerpro-stadt", "Faltreifen Pendlerpro Stadt", "Pendlerpro", "VeloTrade", "Reifen",
        [dict(sku=f"MNT-STADT-{c}", vtitle=t, opts=[("Größe", t)], price=3490, cost=1580, grams=480, w=w, pack=5)
         for t, c, w in [("28 x 1,40 (37-622)", "37", 3), ("28 x 1,60 (42-622)", "42", 4), ("28 x 2,00 (50-622)", "50", 2)]])
    add("mtb-reifen-pendlerpro-trail", "MTB-Reifen Pendlerpro Trail", "Pendlerpro", "VeloTrade", "Reifen",
        [dict(sku=f"MNT-TRAIL-{c}", vtitle=t, opts=[("Größe", t)], price=4490, cost=2050, grams=820, w=w, pack=5)
         for t, c, w in [("27,5 x 2,35", "275", 1.5), ("29 x 2,35", "29", 2)]])
    add("kette-kettenkraft-k", "Kette Kettenkraft K", "Kettenkraft", "VeloTrade", "Antrieb",
        [dict(sku=f"KET-{g:02d}", vtitle=f"{g}-fach", opts=[("Gänge", f"{g}-fach")], price=p, cost=c, grams=280, w=w, pack=5)
         for g, p, c, w in [(8, 1490, 590, 2), (9, 1990, 790, 3), (10, 2490, 1020, 3), (11, 3290, 1390, 4), (12, 4490, 1950, 3)]])
    add("kettenschloss-kettenkraft", "Kettenschloss Kettenkraft (2 Stück)", "Kettenkraft", "VeloTrade", "Antrieb",
        [dict(sku=f"KSL-{g:02d}", vtitle=f"{g}-fach", opts=[("Gänge", f"{g}-fach")], price=590, cost=180, grams=12, w=w, pack=10)
         for g, w in [(9, 1), (10, 1.5), (11, 2), (12, 1.5)]])
    add("scheibenbremsbelaege-stopp-organic", "Scheibenbremsbeläge Stopp Organic", "Stopp", "VeloTrade", "Bremsen",
        [dict(sku=s, vtitle=t, opts=[("Passend für", t)], price=p, cost=c, grams=40, w=w, pack=10)
         for s, t, p, c, w in [("BBS-B01S", "Shimano B01S/B03S", 1290, 460, 3), ("BBS-J04C", "Shimano J04C/J05A", 1290, 460, 3),
                               ("BBS-MT71", "Magura MT (Typ 7.1)", 1490, 540, 2), ("BBS-SRLV", "SRAM Level/Elixir", 1290, 460, 1.5)]])
    add("v-brake-bremsschuhe-stopp-v70", "V-Brake Bremsschuhe Stopp V70", "Stopp", "VeloTrade", "Bremsen",
        [dict(sku="BSV-70", vtitle=None, opts=[], price=890, cost=290, grams=60, w=1.5, pack=10)])
    add("kassette-kettenkraft-11-fach", "Kassette Kettenkraft 11-fach", "Kettenkraft", "VeloTrade", "Antrieb",
        [dict(sku=f"KAS-11-{c}", vtitle=f"11-{c}", opts=[("Abstufung", f"11-{c}")], price=3990, cost=1720, grams=320, w=1, pack=5)
         for c in ("32", "34")])
    jerseys = []
    for size in ("S", "M", "L", "XL", "XXL"):
        for colour, ccode, cw in [("Petrol", "PET", 0.6), ("Senf", "SNF", 0.4)]:
            jerseys.append(dict(sku=f"TRK-CL-{size}-{ccode}", vtitle=f"{size} / {colour}", opts=[("Größe", size), ("Farbe", colour)],
                                price=6900, cost=2450, grams=160, w=SIZE_W[size] * cw * 2.6, pack=1))
    add("trikot-ritzelwerk-classic", "Trikot Ritzelwerk Classic", "Ritzelwerk", "Wollweber", "Bekleidung", jerseys,
        season="textil", policy="continue")
    add("radhose-ritzelwerk-classic-bib", "Radhose Ritzelwerk Classic Bib", "Ritzelwerk", "Wollweber", "Bekleidung",
        [dict(sku=f"BIB-CL-{s}", vtitle=s, opts=[("Größe", s)], price=8900, cost=3100, grams=210, w=SIZE_W[s] * 1.0, pack=1)
         for s in ("S", "M", "L", "XL")], season="textil", policy="continue")
    add("handschuhe-griffig-sommer", "Handschuhe Griffig Sommer", "Griffig", "VeloTrade", "Bekleidung",
        [dict(sku=f"HSH-{s}", vtitle=s, opts=[("Größe", s)], price=2490, cost=940, grams=70, w=SIZE_W[s] * 1.2, pack=5)
         for s in ("S", "M", "L", "XL")], season="textil")
    add("lichtset-leuchtturm-70-lux", "Lichtset Leuchtturm 70 Lux", "Leuchtturm", "VeloTrade", "Beleuchtung",
        [dict(sku="LCH-70", vtitle=None, opts=[], price=4990, cost=2100, grams=230, w=2.5, pack=5)], season="licht")
    add("ruecklicht-leuchtturm-rot", "Rücklicht Leuchtturm Rot", "Leuchtturm", "VeloTrade", "Beleuchtung",
        [dict(sku="LCH-RT", vtitle=None, opts=[], price=1990, cost=710, grams=60, w=1.5, pack=10)], season="licht")
    add("standpumpe-druckvoll", "Standpumpe Druckvoll", "Druckvoll", "VeloTrade", "Werkzeug",
        [dict(sku="PMP-STAND", vtitle=None, opts=[], price=3990, cost=1680, grams=1400, w=1.2, pack=2)])
    add("minipumpe-druckvoll-mini", "Minipumpe Druckvoll Mini", "Druckvoll", "VeloTrade", "Werkzeug",
        [dict(sku="PMP-MINI", vtitle=None, opts=[], price=2290, cost=870, grams=120, w=1.5, pack=5)])
    add("multitool-ritzelwerk-16", "Multitool Ritzelwerk 16", "Ritzelwerk", "VeloTrade", "Werkzeug",
        [dict(sku="MTL-16", vtitle=None, opts=[], price=2790, cost=920, grams=170, w=1.3, pack=5)])
    add("kettenoel-glitsch-dry-lube-100-ml", "Kettenöl Glitsch Dry Lube 100 ml", "Glitsch", "VeloTrade", "Pflege",
        [dict(sku="OEL-DRY", vtitle=None, opts=[], price=890, cost=310, grams=130, w=3, pack=12)])
    add("kettenoel-glitsch-wet-lube-100-ml", "Kettenöl Glitsch Wet Lube 100 ml", "Glitsch", "VeloTrade", "Pflege",
        [dict(sku="OEL-WET", vtitle=None, opts=[], price=890, cost=310, grams=130, w=2.5, pack=12)])
    add("fahrradreiniger-glitsch-clean-1-l", "Fahrradreiniger Glitsch Clean 1 l", "Glitsch", "VeloTrade", "Pflege",
        [dict(sku="RNG-1L", vtitle=None, opts=[], price=1290, cost=430, grams=1100, w=1.5, pack=6)])
    add("flickzeug-pendlerpro-set", "Flickzeug Pendlerpro Set", "Pendlerpro", "VeloTrade", "Schläuche",
        [dict(sku="FLK-SET", vtitle=None, opts=[], price=490, cost=130, grams=40, w=2.5, pack=20)])
    add("lenkerband-griffig-kork", "Lenkerband Griffig Kork", "Griffig", "VeloTrade", "Cockpit",
        [dict(sku=f"LBK-{c}", vtitle=t, opts=[("Farbe", t)], price=1990, cost=690, grams=90, w=w, pack=5)
         for t, c, w in [("Schwarz", "SW", 1), ("Petrol", "PET", 0.6), ("Senf", "SNF", 0.4)]])
    add("sattel-sitzfest-comfort", "Sattel Sitzfest Comfort", "Sitzfest", "VeloTrade", "Cockpit",
        [dict(sku=f"SAT-{c}", vtitle=f"{c} mm", opts=[("Breite", f"{c} mm")], price=5990, cost=2400, grams=330, w=0.8, pack=2)
         for c in ("143", "155")])
    add("plattformpedale-tritt", "Plattformpedale Tritt", "Tritt", "VeloTrade", "Antrieb",
        [dict(sku="PED-TRITT", vtitle=None, opts=[], price=3490, cost=1350, grams=380, w=1, pack=4)])
    add("flaschenhalter-halt", "Flaschenhalter Halt", "Halt", "VeloTrade", "Zubehör",
        [dict(sku=f"FLH-{c}", vtitle=t, opts=[("Farbe", t)], price=990, cost=320, grams=45, w=w, pack=10)
         for t, c, w in [("Schwarz", "SW", 1), ("Silber", "SI", 0.5)]])
    add("trinkflasche-ritzelwerk-750-ml", "Trinkflasche Ritzelwerk 750 ml", "Ritzelwerk", "Wollweber", "Zubehör",
        [dict(sku="TFL-750", vtitle=None, opts=[], price=790, cost=220, grams=95, w=1.5, pack=1)])
    add("laufrad-pendlerpro-28-disc", "Laufrad Pendlerpro 28 Zoll Disc", "Pendlerpro", "VeloTrade", "Laufräder",
        [dict(sku=s, vtitle=t, opts=[("Position", t)], price=p, cost=c, grams=g, w=w, pack=2)
         for s, t, p, c, g, w in [("LRD-28-VR", "Vorderrad", 8900, 4100, 950, 0.9), ("LRD-28-HR", "Hinterrad (Kassette)", 11900, 5600, 1150, 0.8)]])
    add("fahrradhelm-kopfsache-urban", "Fahrradhelm Kopfsache Urban", "Kopfsache", "VeloTrade", "Helme",
        [dict(sku=f"HLM-{s}-{cc}", vtitle=f"{s} / {cn}", opts=[("Größe", s), ("Farbe", cn)], price=8900, cost=3800, grams=380,
              w={"S": 0.5, "M": 1.0, "L": 0.8}[s] * cw * 1.6, pack=2)
         for s in ("S", "M", "L") for cn, cc, cw in [("Schwarz", "SW", 0.65), ("Petrol", "PET", 0.35)]])
    add("faltschloss-sperrwerk-900", "Faltschloss Sperrwerk 900", "Sperrwerk", "VeloTrade", "Schlösser",
        [dict(sku="SLO-900", vtitle=None, opts=[], price=6990, cost=2900, grams=1100, w=1.6, pack=4)])
    add("gepaecktraegertasche-ritzelwerk-pendler", "Gepäckträgertasche Ritzelwerk Pendler 20 l", "Ritzelwerk", "Wollweber",
        "Taschen", [dict(sku=f"TSC-20-{c}", vtitle=t, opts=[("Farbe", t)], price=7900, cost=3100, grams=900, w=w, pack=1)
                    for t, c, w in [("Schwarz", "SW", 1.1), ("Senf", "SNF", 0.5)]], policy="continue")
    add("geschenkgutschein", "Geschenkgutschein Ritzelwerk", "Ritzelwerk", "", "Gutschein",
        [dict(sku=None, vtitle=f"{a} €", opts=[("Wert", f"{a} €")], price=a * 100, cost=0, grams=0, w=0, pack=1) for a in (25, 50)],
        ship=False, taxable=False, gift=True)
    add("trikot-ritzelwerk-edition-2025", "Trikot Ritzelwerk Edition 2025", "Ritzelwerk", "Wollweber", "Bekleidung",
        [dict(sku=f"TRK-25-{s}", vtitle=s, opts=[("Größe", s)], price=5900, cost=2300, grams=160, w=1.4, pack=1) for s in ("M", "L")],
        discontinued=True)
    for i, v in enumerate(vs):
        v.ean = _ean(rng, 4711000 + i * 37) if v.sku else ""
    return vs


# ----------------------------------------------------------------------------------------------- people
@dataclass
class C:
    key: str
    first: str
    last: str
    email: str
    street: str
    zip: str
    city: str
    country: str
    phone: str
    w: float
    marketing: bool
    alias_email: str = ""
    alias_note: str = ""
    iban: str = ""
    company: str = ""

    @property
    def name(self):
        return f"{self.first} {self.last}"


def slug(s: str) -> str:
    rep = {"ä": "ae", "ö": "oe", "ü": "ue", "ß": "ss", "ı": "i", "ş": "s", "ğ": "g", "ç": "c", "é": "e", " ": ""}
    return "".join(rep.get(ch, ch) for ch in s.lower())


@dataclass
class B2B:
    kno: str
    name: str
    first: str
    last: str
    email: str
    street: str
    zip: str
    city: str
    country: str
    phone: str
    vat_id: str
    terms: int
    skonto: tuple | None
    interval: int
    first_order: date
    basket: list
    pay: str
    iban: str
    payer: str
    stop_after: date | None = None
    reverse_charge: bool = False
    price_factor: float = 0.70
    bic: str = ""
    shop_email: str = ""

    @property
    def terms_text(self):
        if self.skonto:
            return f"{self.skonto[0]} Tage {self.skonto[1]} % Skonto, {self.terms} Tage netto"
        return f"Netto {self.terms} Tage"


def build_b2b(rng: random.Random) -> list[B2B]:
    T = ["SCH-28-SV", "SCH-28-AV", "SCH-26-AV", "SCH-275-SV", "SCH-29-SV"]
    base_shop = [("SCH-28-SV", 10, 30, 1), ("SCH-28-AV", 5, 20, 0.9), ("SCH-26-AV", 5, 10, 0.5), ("SCH-29-SV", 5, 10, 0.5),
                 ("KET-09", 3, 6, 0.6), ("KET-10", 3, 8, 0.7), ("KET-11", 3, 8, 0.7), ("KSL-11", 5, 10, 0.5),
                 ("BBS-B01S", 5, 10, 0.8), ("BBS-J04C", 5, 10, 0.6), ("BSV-70", 5, 10, 0.4), ("OEL-DRY", 6, 12, 0.7),
                 ("FLK-SET", 10, 20, 0.5), ("MNT-STADT-42", 2, 6, 0.4), ("MNT-STADT-37", 2, 4, 0.3)]
    small = [("SCH-28-SV", 5, 10, 1), ("SCH-28-AV", 5, 10, 0.6), ("OEL-DRY", 6, 6, 0.6), ("OEL-WET", 6, 6, 0.4),
             ("FLK-SET", 10, 10, 0.5), ("KSL-10", 5, 5, 0.3), ("BBS-B01S", 3, 5, 0.4), ("TFL-750", 5, 10, 0.3),
             ("LBK-SW", 2, 4, 0.3)]
    del T
    out = [
        B2B("K-10001", "Radhaus Sielmann GmbH", "Henning", "Sielmann", "werkstatt@radhaus-sielmann.example",
            "Osterdeich 112", "28205", "Bremen", "DE", "+49 421 5583310", "DE287766120", 14, None, 21, date(2026, 1, 8),
            base_shop, "exact", de_iban(rng, "29050101"), "RADHAUS SIELMANN GMBH"),
        B2B("K-10002", "Fahrradwerkstatt Kettenblatt", "Ole", "Petersen", "ole@kettenblatt-hh.example",
            "Bahrenfelder Str. 201", "22765", "Hamburg", "DE", "+49 40 39904417", "DE301122845", 14, None, 28, date(2026, 1, 15),
            base_shop[:10], "late", de_iban(rng, "20050550"), "Fahrradwerkstatt Kettenblatt Ole Petersen"),
        B2B("K-10003", "Velo-Point Hasetal GmbH", "Birgit", "Rolfes", "einkauf@velo-point-hasetal.example",
            "Lange Straße 18", "49610", "Quakenbrück", "DE", "+49 5431 908870", "DE296610934", 30, None, 25, date(2026, 1, 14),
            base_shop, "early", de_iban(rng, "28069956"), "Velo-Point Hasetal GmbH", stop_after=date(2026, 8, 25)),
        B2B("K-10004", "Zweirad Kowalski", "Marek", "Kowalski", "info@zweirad-kowalski.example",
            "Rheinische Str. 77", "44137", "Dortmund", "DE", "+49 231 1775420", "DE309988127", 14, None, 18, date(2026, 1, 12),
            base_shop[:12], "combine", de_iban(rng, "44050199"), "Marek Kowalski"),
        B2B("K-10005", "Fahrradstation am Hauptbahnhof gGmbH", "Katrin", "Wessels", "rechnung@fahrradstation-ms.example",
            "Berliner Platz 27a", "48143", "Münster", "DE", "+49 251 4840170", "DE312200476", 30, None, 35, date(2026, 1, 20),
            [("SCH-28-SV", 10, 20, 1), ("SCH-28-AV", 10, 20, 1), ("FLK-SET", 20, 40, 0.8), ("KET-08", 5, 10, 0.6),
             ("KET-09", 5, 10, 0.6), ("BSV-70", 10, 20, 0.6), ("BBS-B01S", 5, 10, 0.5), ("LCH-RT", 5, 10, 0.4)],
            "on_due", de_iban(rng, "40050150"), "Fahrradstation am Hbf gGmbH"),
        B2B("K-10006", "Lastesel Lastenradverleih e.V.", "Wiebke", "Göken", "kasse@lastesel-os.example",
            "Lotter Straße 64", "49078", "Osnabrück", "DE", "+49 541 33019282", "", 14, None, 45, date(2026, 2, 3),
            [("MNT-STADT-50", 2, 6, 1), ("SCH-28-AV", 4, 10, 1), ("BBS-MT71", 4, 8, 0.8), ("KET-08", 2, 4, 0.5),
             ("OEL-WET", 6, 6, 0.5)], "slow", de_iban(rng, "26550105"), "Lastesel e.V."),
        B2B("K-10007", "RSG Osnabrück 1924 e.V.", "Malte", "Brinkmann", "kassenwart@rsg-osnabrueck.example",
            "Am Schölerberg 3", "49082", "Osnabrück", "DE", "+49 541 5059931", "", 14, None, 0, date(2026, 4, 14),
            [], "club", de_iban(rng, "26550105"), "RSG Osnabrueck 1924 eV", price_factor=0.80),
        B2B("K-10008", "Fahrrad-Kurier Nord GmbH", "Fiete", "Hinrichs", "buero@fahrradkurier-nord.example",
            "Stresemannstraße 44", "22769", "Hamburg", "DE", "+49 40 41916600", "DE281193350", 14, (7, 2), 14, date(2026, 1, 6),
            [("SCH-28-SV", 10, 20, 1), ("BBS-B01S", 5, 10, 0.8), ("BBS-J04C", 5, 10, 0.6), ("KET-10", 3, 6, 0.6),
             ("KET-11", 3, 6, 0.5), ("LCH-70", 2, 4, 0.4), ("LCH-RT", 2, 5, 0.4), ("OEL-WET", 6, 12, 0.6)],
            "skonto", de_iban(rng, "20070000"), "FAHRRAD-KURIER NORD GMBH"),
        B2B("K-10009", "Fietsenmakerij De Spaak B.V.", "Joost", "van Dijk", "inkoop@despaak.example",
            "Haaksbergerstraat 52", "7513 EA", "Enschede", "NL", "+31 53 4301188", "NL859912311B01", 30, None, 30,
            date(2026, 1, 21), [("SCH-28-SV", 10, 20, 1), ("SCH-28-AV", 10, 20, 0.8), ("KET-10", 5, 10, 0.6),
                                ("KET-11", 5, 10, 0.6), ("KAS-11-34", 2, 4, 0.4), ("KAS-11-32", 2, 4, 0.3)],
            "nl", iban("NL", "RABO" + f"{rng.randint(0, 9999999999):010d}"), "FIETSENMAKERIJ DE SPAAK BV",
            reverse_charge=True),
        B2B("K-10010", "Bike & Bean Café-Werkstatt UG (haftungsbeschränkt)", "Luca", "Brandt", "hallo@bikeandbean.example",
            "Katharinenstraße 12", "49078", "Osnabrück", "DE", "+49 541 20093310", "DE329901276", 14, None, 20,
            date(2026, 1, 27), small, "bean", de_iban(rng, "26550105"), "Bike & Bean Cafe-Werkstatt UG"),
    ]
    for b in out:
        b.bic = {"DE": "GENODEF1XXX", "NL": "RABONL2U"}[b.country]
    return out


# ----------------------------------------------------------------------------------------------- orders, money
@dataclass
class Line:
    v: V
    qty: int
    price: int          # unit price in order currency (gross, incl. VAT where VAT applies)
    disc: int = 0       # line discount total
    net_unit: int = 0   # B2B: invoice unit net


@dataclass
class Refund:
    when: datetime
    amount: int
    items: list
    shipping: int
    reason: str
    rma: str = ""


@dataclass
class Inv:
    no: str
    d: date
    cust: B2B
    order: "Order | None"
    net: int
    vat: int
    gross: int
    due: date
    kind: str = "Rechnung"
    ref: "Inv | None" = None
    lines: list = field(default_factory=list)
    payments: list = field(default_factory=list)   # dicts: d, amount, channel, ref, exact, bank_idx/pp
    notes: str = ""


@dataclass
class Order:
    no: int
    created: datetime
    cust: C | None
    b2b: B2B | None
    lines: list
    currency: str
    country: str
    tax_rate: float
    gateway: str
    disc_code: str = ""
    disc: int = 0
    ship_method: str = ""
    ship: int = 0
    subtotal: int = 0
    taxes: int = 0
    total: int = 0
    gc_amount: int = 0
    paid_at: datetime | None = None
    authorized: bool = False
    fulfilled_at: datetime | None = None
    cancelled_at: datetime | None = None
    cancel_reason: str = ""
    refunds: list = field(default_factory=list)
    invoice: Inv | None = None
    notes: str = ""
    tags: list = field(default_factory=list)
    shopify_id: int = 0
    checkout: str = ""
    flags: set = field(default_factory=set)
    hold_until: date | None = None
    pickup_on: date | None = None
    money: list = field(default_factory=list)        # vorkasse: dicts d, amount, bank tx
    marked_paid_on: date | None = None
    ship_addr: dict | None = None
    ship_addr_changes: list = field(default_factory=list)   # (when, dict)
    pp_code: str = ""
    company_at_order: str = ""

    @property
    def name(self):
        return f"RW-{self.no}"

    def refunded(self, cut: date) -> int:
        return sum(r.amount for r in self.refunds if r.when.date() <= cut)


@dataclass
class BankTx:
    d: date
    name: str
    iban: str
    bic: str
    btext: str
    purpose: str
    amount: int
    kind: str
    ref: object = None
    cred_id: str = ""
    mandate: str = ""
    valuta: date | None = None
    seq: int = 0
    balance: int = 0


@dataclass
class PPTx:
    dt: datetime
    name: str
    typ: str
    cur: str
    gross: int
    fee: int
    code: str
    impact: str = "Haben"
    status: str = "Abgeschlossen"
    sender: str = ""
    receiver: str = ""
    item_title: str = ""
    invoice_no: str = ""
    related: str = ""
    subject: str = ""
    note: str = ""
    order: Order | None = None
    kind: str = ""
    balance: int = 0
    address: dict | None = None
    withdrawal: str = ""     # code of the withdrawal that carried this movement to the bank

    @property
    def net(self):
        return self.gross + self.fee


@dataclass
class SPTx:
    dt: datetime
    typ: str
    order: Order
    brand: str
    amount: int
    fee: int
    checkout: str
    method: str
    payout_id: str = ""
    payout_date: date | None = None

    @property
    def net(self):
        return self.amount + self.fee


@dataclass
class KLRow:
    typ: str
    order: Order
    capture_id: str
    klarna_id: str
    capture_date: date
    sale_date: date
    amount: int
    vat: int
    payout_ref: str = ""
    payout_date: date | None = None
    method: str = "PAY_LATER"


@dataclass
class SInv:
    supplier: str
    no: str
    d: date
    lines: list           # (sku, desc, qty, unit_net)
    net: int
    vat: int
    gross: int
    due: date
    skonto_until: date | None = None
    skonto_pct: float = 0
    paid: date | None = None
    paid_amount: int = 0
    delivery_note: str = ""
    fmt: str = "pdf"
    direct_debit: bool = False
    period: str = ""
    in_dump: int = 0      # 0 = not in dump, 1/2 = delivery
    reminder: date | None = None


@dataclass
class Receipt:
    d: date
    supplier: str
    note: str
    sku: str
    qty: int
    booked_in_shopify: bool = True


@dataclass
class Ret:
    rma: str
    order: Order
    arrived: date
    items: list            # (sku, qty)
    reason: str
    condition: str
    refund_on: date | None
    amount: int
    note: str = ""
    sheet_refund_on: date | None = None     # what Tom's sheet says (may lag)
    sheet_order_text: str = ""


@dataclass
class Mail:
    fname: str
    when: datetime
    sender: str
    to: str
    subject: str
    body: str
    needs_action: bool
    kind: str
    refs: list = field(default_factory=list)
    attachment: tuple | None = None       # (filename, bytes-producer key)
    delivery: int = 1
    reply_to_msgid: str = ""
    msgid: str = ""
    html: bool = False
