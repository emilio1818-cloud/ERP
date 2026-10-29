"""An unseen firm for the generalisation test: Musikschule Klangwerk GmbH, Leipzig.
Direct debits (SEPA batch), VAT-exempt monthly fees, freelance teachers, instrument rental.
Writes the files a real office would have, and the ground truth (truth.json)."""
import json, random, sys
from datetime import date, timedelta
from pathlib import Path
import openpyxl

OUT = Path(sys.argv[1]); OUT.mkdir(parents=True, exist_ok=True)
(OUT / "Mails").mkdir(exist_ok=True)
R = random.Random(20261029)
TODAY = date(2026, 10, 29)

def de(d): return d.strftime("%d.%m.%Y")
def de2(d): return d.strftime("%d.%m.%y")
def eur(x): return f"{x:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")

LAST = ["Schulz", "Müller", "Schmidt", "Wagner", "Becker", "Hoffmann", "Krause", "Richter", "Wolf", "Neumann", "Schwarz",
        "Zimmermann", "Braun", "Hartmann", "Lange", "Werner", "Lehmann", "Köhler", "Herrmann", "König", "Walter", "Kaiser",
        "Fuchs", "Peters", "Lang", "Scholz", "Möller", "Weiß", "Jung", "Hahn", "Vogel", "Friedrich", "Keller", "Günther",
        "Frank", "Berger", "Winkler", "Roth", "Beck", "Lorenz", "Baumann", "Franke", "Albrecht", "Schuster", "Simon",
        "Ludwig", "Böhm", "Winter", "Kraus", "Martin", "Schumacher", "Krämer", "Vogt", "Stein", "Jäger", "Otto", "Sommer",
        "Groß", "Seidel", "Heinrich"]
KIDS = ["Mila", "Ben", "Emma", "Paul", "Lina", "Felix", "Ella", "Noah", "Clara", "Leon", "Ida", "Jonas", "Mia", "Elias",
        "Frieda", "Anton", "Lotta", "Emil", "Greta", "Theo", "Marie", "Oskar", "Hanna", "Moritz", "Sophie", "Luis", "Lea",
        "Karl", "Nele", "Jakob"]
ADULT = ["Sabine", "Thomas", "Katrin", "Michael", "Anja", "Stefan", "Julia", "Andreas", "Silke", "Jens"]
STREETS = ["Karl-Liebknecht-Str.", "Gohliser Str.", "Eisenbahnstr.", "Könneritzstr.", "Zschochersche Str.", "Arthur-Hoffmann-Str.",
           "Georg-Schwarz-Str.", "Kochstr.", "Lützner Str.", "Holbeinstr."]
PLZ = ["04107", "04155", "04315", "04229", "04179", "04275", "04177", "04277", "04249", "04105"]
TEACH = [("MW", "Maria Wolf", "Klavier", 32.0), ("TB", "Tobias Brandt", "Gitarre", 30.0), ("JL", "Jana Lorenz", "Violine", 32.0),
         ("KS", "Kai Schreiber", "Schlagzeug", 30.0), ("AH", "Anna Hoffmann", "Gesang", 31.0),
         ("RF", "Ralf Fischer", "Saxophon", 30.0), ("EM", "Elif Meyer", "Musikalische Früherziehung", 28.0)]
FORMS = [("Einzel 30 Min", 68.0), ("Einzel 45 Min", 95.0), ("Gruppe (3–4)", 42.0)]

def iban(r):
    return "DE" + "".join(str(r.randint(0, 9)) for _ in range(20))

# --- students ----------------------------------------------------------------------------------
students = []
for i in range(60):
    sid = f"S-{1001 + i}"
    last = LAST[i]
    adult = i % 9 == 4
    first = ADULT[i % len(ADULT)] if adult else KIDS[i % len(KIDS)]
    born = date(1975 + R.randint(0, 20), R.randint(1, 12), R.randint(1, 28)) if adult else date(2010 + R.randint(0, 11), R.randint(1, 12), R.randint(1, 28))
    parent = "" if adult else f"{R.choice(ADULT)} {last}"
    sepa = i % 4 != 3  # three in four pay by direct debit
    k = i % 10
    students.append(dict(id=sid, last=last, first=first, born=born, parent=parent, street=f"{STREETS[k]} {R.randint(1, 120)}",
                         plz=PLZ[k], city="Leipzig", phone=f"0341 {R.randint(100000, 999999)}",
                         mail=f"{(parent or first).split()[0].lower()}.{last.lower().replace('ö','oe').replace('ü','ue').replace('ä','ae').replace('ß','ss')}@{R.choice(['web.de','gmx.de','t-online.de','posteo.de'])}",
                         iban=iban(R) if sepa else "", mref=f"MR-{sid}" if sepa else "", sepa=sepa,
                         since=date(2022 + R.randint(0, 4), R.choice([1, 2, 8, 9, 10]), 1)))
for s in students:
    if s["since"] > date(2026, 9, 1):
        s["since"] = date(2026, 2, 1)

# --- contracts ---------------------------------------------------------------------------------
contracts = []
n = 0
for i, s in enumerate(students):
    subjects = [TEACH[i % 7]] + ([TEACH[(i + 3) % 7]] if i % 6 == 0 else [])
    for t in subjects:
        n += 1
        form = FORMS[2] if t[0] == "EM" else FORMS[(i + n) % 2] if i % 5 else FORMS[2]
        fee = 35.0 if t[0] == "EM" else form[1]
        start = s["since"] if len(subjects) == 1 or t is subjects[0] else date(max(2024, s["since"].year), 9, 1)
        contracts.append(dict(id=f"V-{start.year}-{n:03d}", sid=s["id"], student=s, subject=t[2], teacher=t[0], form=form[0] if t[0] != "EM" else "Gruppe (Früherziehung)",
                              fee=fee, start=start, end=None))
# terminations: five ended in the past, three end at the end of the year
for c in contracts[5:30:5]:
    c["end"] = date(2026, 7, 31)
for c in contracts[33:60:9]:
    c["end"] = date(2026, 12, 31)

# --- monthly fee invoices Jan–Oct 2026 -----------------------------------------------------------
invoices = []
k = 0
for month in range(1, 11):
    first = date(2026, month, 1)
    for c in contracts:
        if c["start"] > first or (c["end"] and c["end"] < first):
            continue
        k += 1
        s = c["student"]
        due = date(2026, month, 5) if s["sepa"] else date(2026, month, 15)
        invoices.append(dict(no=f"BR-2026-{k:04d}", day=first, sid=s["id"], name=f"{s['first']} {s['last']}", contract=c["id"],
                             text=f"Unterrichtsbeitrag {c['subject']} ({c['form']})", period=f"{month:02d}/2026",
                             amount=c["fee"], how="Lastschrift" if s["sepa"] else "Überweisung", due=due, student=s, paid=None,
                             truth="paid"))

def collect_day(month):  # first business day on or after the 5th
    d = date(2026, month, 5)
    while d.weekday() >= 5:
        d += timedelta(days=1)
    return d

bank = []  # (day, payer, payee, purpose, kind, iban, amount, creditor-id, mref, ref)
OWN = "Musikschule Klangwerk GmbH"
GID = "DE77ZZZ00002345678"
# direct debits: one batch per month, book marks each invoice as paid on the collection day
returned = []
for month in range(1, 11):
    batch = [x for x in invoices if x["how"] == "Lastschrift" and x["day"].month == month]
    cd = collect_day(month)
    for x in batch:
        x["paid"] = cd
    if month >= 7:  # the bank statement starts on 01.07.2026
        bank.append((cd, OWN, OWN, f"SEPA-Sammellastschrift Einreichung {de(date(2026, month, 1))} {len(batch)} Posten", "Eingang", "",
                     round(sum(x["amount"] for x in batch), 2), GID, "", f"SAMMLER-2026-{month:02d}"))
# returned debits (chargebacks) in Aug–Oct
ret_specs = [(8, 3, "MD06 Rückgabe auf Verlangen des Zahlers", "repaid"), (9, 11, "AC04 Konto erloschen", "open_book_paid"),
             (9, 20, "AM04 Deckung unzureichend", "open_book_cleared"), (10, 7, "AM04 Deckung unzureichend", "open_book_paid"),
             (10, 15, "MD06 Rückgabe auf Verlangen des Zahlers", "open_book_cleared")]
for month, idx, reason, fate in ret_specs:
    batch = [x for x in invoices if x["how"] == "Lastschrift" and x["day"].month == month]
    x = batch[idx]
    d = collect_day(month) + timedelta(days=R.randint(4, 8))
    fee = 3.0
    bank.append((d, x["student"]["parent"] or x["name"], OWN,
                 f"RUECKLASTSCHRIFT {x['no']} {x['period']} MREF {x['student']['mref']} {reason} zzgl. Entgelt {eur(fee)} EUR",
                 "Ausgang", x["student"]["iban"], -round(x["amount"] + fee, 2), GID, x["student"]["mref"], ""))
    returned.append(dict(no=x["no"], fate=fate, fee=fee))
    if fate == "repaid":
        d2 = d + timedelta(days=9)
        bank.append((d2, x["student"]["parent"] or x["name"], OWN, f"{x['no']} Nachzahlung Ruecklastschrift", "Eingang",
                     iban(R), round(x["amount"] + fee, 2), "", "", ""))
        x["truth"] = "paid"
    else:
        x["truth"] = "open"
        if fate == "open_book_cleared":
            x["paid"] = None  # the office noticed and cleared "bezahlt am"
# transfers by those without a mandate
claim = None
for x in invoices:
    if x["how"] != "Überweisung":
        continue
    m = x["day"].month
    late_none = (m == 10 and x["sid"] in ("S-1004", "S-1012", "S-1020", "S-1028", "S-1036")) or (m == 5 and x["sid"] == "S-1008")
    if late_none:
        x["truth"] = "open"
        continue
    d = x["day"] + timedelta(days=R.randint(3, 16))
    if d > TODAY - timedelta(days=1):
        d = TODAY - timedelta(days=2)
    x["paid"] = d
    if m >= 7:
        payer = (x["student"]["parent"] or x["name"]).upper()
        style = R.random()
        if style < 0.45:
            purpose = f"{x['no']}"
        elif style < 0.8:
            purpose = f"Beitrag {['Januar','Februar','Maerz','April','Mai','Juni','Juli','August','September','Oktober'][m-1]} {x['student']['first']} {x['student']['last']}"
        else:
            purpose = f"Musikschule {x['period']} {x['student']['first']}"
        bank.append((d, payer, OWN, purpose, "Eingang", iban(R) if x["sid"] not in [b[1] for b in bank] else "", x["amount"], "", "", ""))
# the parent who says it is paid (October, not in the statement)
claim_inv = next(x for x in invoices if x["sid"] == "S-1012" and x["period"] == "10/2026")
# --- teachers' fees -------------------------------------------------------------------------------
fees = []
for month in range(1, 11):
    for code, name, subj, rate in TEACH:
        ue = sum(4 for c in contracts if c["teacher"] == code and c["start"] <= date(2026, month, 1) and not (c["end"] and c["end"] < date(2026, month, 1)))
        amount = round(ue * rate * (0.75 if code != "EM" else 1.0), 2)
        paid = date(2026, month, 28) if month < 10 else None
        fees.append(dict(month=f"{month:02d}/2026", code=code, name=name, ue=ue, rate=rate, amount=amount, paid=paid))
        if paid and month >= 7:
            bank.append((paid, OWN, name, f"Honorar {month:02d}/2026 {code}", "Ausgang", iban(R), -amount, "", "", ""))
# running costs
for month in range(7, 11):
    bank.append((date(2026, month, 1), OWN, "Immobilien Plagwitz GmbH", "Miete Unterrichtsraeume Kochstr. 12", "Ausgang", "DE40860555921090123456", -2150.00, "", "", ""))
    bank.append((date(2026, month, 15), OWN, "Stadtwerke Leipzig GmbH", f"Abschlag Strom {month:02d}/2026", "Ausgang", "DE52860555921100223344", -184.00, "", "", ""))
bank.append((date(2026, 7, 20), OWN, "GEMA", "GEMA Jahresrechnung 2026 Musikschule", "Ausgang", "DE31700500000000027000", -612.40, "", "", ""))
bank.append((date(2026, 9, 3), OWN, "Musikhaus Elster GmbH", "Rechnung ME-2026-0944", "Ausgang", "DE89860700240123456700", -416.50, "", "", ""))
bank.append((date(2026, 8, 12), "Stadt Leipzig Kulturamt", OWN, "Zuschuss Musikschulfoerderung 2026 1. Rate", "Eingang", "DE11860555920000000001", 4500.00, "", "", ""))
bank.sort(key=lambda b: b[0])

# ---- write files -----------------------------------------------------------------------------------
wb = openpyxl.Workbook(); ws = wb.active; ws.title = "Schüler"
ws.append(["Musikschule Klangwerk – Schülerverzeichnis (Stand 01.10.2026)"]); ws.append([])
ws.append(["Schüler-Nr", "Nachname", "Vorname", "geb.", "Erziehungsberechtigte/r", "Straße", "PLZ", "Ort", "Telefon", "E-Mail",
           "IBAN", "Mandatsreferenz", "Anmeldung"])
for s in students:
    ws.append([s["id"], s["last"], s["first"], s["born"], s["parent"], s["street"], s["plz"], s["city"], s["phone"], s["mail"],
               s["iban"], s["mref"], s["since"]])
wb.save(OUT / "Schuelerverzeichnis.xlsx")

(OUT / "Lehrkraefte.csv").write_text("Kürzel;Name;Fach;Honorar je UE;IBAN\n" + "\n".join(
    f"{c};{n};{s};{eur(r)};{iban(R)}" for c, n, s, r in TEACH) + "\n", encoding="cp1252")

wb = openpyxl.Workbook(); ws = wb.active; ws.title = "Verträge"
ws.append(["Vertrag", "Schüler-Nr", "Schüler", "Fach", "Lehrkraft", "Unterrichtsform", "Beitrag mtl.", "Beginn", "Kündigung zum", "Status"])
for c in contracts:
    s = c["student"]
    ws.append([c["id"], c["sid"], f"{s['first']} {s['last']}", c["subject"], c["teacher"], c["form"], c["fee"], c["start"],
               c["end"], "gekündigt" if c["end"] else "aktiv"])
wb.save(OUT / "Unterrichtsvertraege.xlsx")

lines = ["Beleg-Nr.;Datum;Schüler-Nr;Name;Vertrag;Leistung;Zeitraum;Betrag;Zahlweise;fällig;bezahlt am"]
for x in invoices:
    lines.append(";".join([x["no"], de(x["day"]), x["sid"], x["name"], x["contract"], x["text"], x["period"], eur(x["amount"]),
                           x["how"], de(x["due"]), de(x["paid"]) if x["paid"] else ""]))
(OUT / "Beitragsrechnungen_2026.csv").write_text("\n".join(lines) + "\n", encoding="cp1252")

head = ['"Girokonto";"DE12 1203 0000 1020 3040 50"', '""', '"Kontostand vom 28.10.2026:";"21.406,17 €"', '""',
        '"Buchungsdatum";"Wertstellung";"Status";"Zahlungspflichtige*r";"Zahlungsempfänger*in";"Verwendungszweck";"Umsatztyp";"IBAN";"Betrag (€)";"Gläubiger-ID";"Mandatsreferenz";"Kundenreferenz"']
rows = [";".join(f'"{v}"' for v in [de2(b[0]), de2(b[0]), "Gebucht", b[1], b[2], b[3], b[4], b[5], eur(b[6]), b[7], b[8], b[9]]) for b in bank]
(OUT / "Umsaetze_Girokonto_01.07.2026-28.10.2026.csv").write_text("\n".join(head + rows) + "\n", encoding="utf-8")

wb = openpyxl.Workbook(); ws = wb.active; ws.title = "Honorare 2026"
ws.append(["Monat", "Kürzel", "Lehrkraft", "UE", "Satz", "Honorar", "ausgezahlt am"])
for f in fees:
    ws.append([f["month"], f["code"], f["name"], f["ue"], f["rate"], f["amount"], f["paid"]])
wb.save(OUT / "Honorarabrechnung_Lehrkraefte_2026.xlsx")

rentals = []
INSTR = [("Violine 1/2", "Gewa"), ("Violine 3/4", "Gewa"), ("Violine 4/4", "Höfner"), ("Gitarre 3/4", "Yamaha"), ("Gitarre 4/4", "Yamaha"),
         ("Altsaxophon", "Yamaha"), ("Digitalpiano", "Kawai"), ("Querflöte", "Pearl"), ("Cello 1/2", "Gewa"),
         ("Keyboard", "Casio"), ("Tenorsaxophon", "Jupiter"), ("Violine 1/4", "Gewa")]
for i, (ins, maker) in enumerate(INSTR):
    s = students[(i * 5 + 2) % 60]
    last = date(2025, 11 + (i % 2), 10) if i in (2, 5) else date(2026, 3 + i % 6, 10)  # two are due within a month
    rentals.append(dict(no=f"INV-{101 + i}", ins=ins, maker=maker, serial=f"{maker[:2].upper()}{R.randint(100000, 999999)}",
                        sid=s["id"], who=f"{s['first']} {s['last']}", since=date(2025, 9, 1), fee=15.0 if "Violine" in ins else 25.0,
                        last=last))
wb = openpyxl.Workbook(); ws = wb.active; ws.title = "Mietinstrumente"
ws.append(["Inv.-Nr.", "Instrument", "Hersteller", "Seriennummer", "Mieter (Schüler-Nr)", "Mieter", "seit", "Miete mtl.", "letzte Wartung", "Wartung alle"])
for r in rentals:
    ws.append([r["no"], r["ins"], r["maker"], r["serial"], r["sid"], r["who"], r["since"], r["fee"], r["last"], "12 Monate"])
wb.save(OUT / "Mietinstrumente.xlsx")

def eml(name, frm, to, subj, day, body):
    (OUT / "Mails" / name).write_text(
        f"From: {frm}\nTo: {to}\nSubject: {subj}\nDate: {day.strftime('%a, %d %b %Y')} 09:14:00 +0200\n"
        f"MIME-Version: 1.0\nContent-Type: text/plain; charset=utf-8\n\n{body}\n", encoding="utf-8")
canc = next(c for c in contracts if c["sid"] == "S-1001")
eml("kuendigung.eml", "Sabine Schulz <sabine.schulz@web.de>", "info@klangwerk-leipzig.de", f"Kündigung Unterrichtsvertrag {canc['id']}",
    date(2026, 10, 20), f"Sehr geehrte Damen und Herren,\n\nhiermit kündigen wir den Unterrichtsvertrag {canc['id']} ({canc['subject']}) für unsere Tochter Mila fristgerecht zum 31.12.2026.\nBitte bestätigen Sie uns die Kündigung.\n\nMit freundlichen Grüßen\nSabine Schulz")
eml("schon_ueberwiesen.eml", "Thomas Neumann <thomas.neumann@gmx.de>", "info@klangwerk-leipzig.de", f"Ihre Zahlungserinnerung {claim_inv['no']}",
    date(2026, 10, 27), f"Guten Tag,\n\nden Beitrag für Oktober ({claim_inv['no']}) haben wir bereits am 14.10. überwiesen. Bitte prüfen Sie das noch einmal.\n\nViele Grüße\nThomas Neumann")
eml("probestunde.eml", "Katrin Vogel <k.vogel@posteo.de>", "info@klangwerk-leipzig.de", "Anfrage Probestunde Gitarre",
    date(2026, 10, 26), "Hallo,\n\nunser Sohn (8) möchte gern Gitarre lernen. Hätten Sie im November einen Termin für eine Probestunde, gern nachmittags?\n\nDanke und Grüße\nKatrin Vogel\n0176 5551234")
eml("newsletter.eml", "Musikhaus Elster <newsletter@musikhaus-elster.de>", "info@klangwerk-leipzig.de", "Herbstaktion: 20 % auf Notenpulte",
    date(2026, 10, 2), "Liebe Kundinnen und Kunden, nur bis Ende Oktober ...")
eml("bankverbindung.eml", "Buchhaltung Musikhaus Elster <buchhaltung@musikhaus-elster-gmbh.de>", "info@klangwerk-leipzig.de",
    "Wichtig: Neue Bankverbindung", date(2026, 10, 28),
    "Sehr geehrte Kunden,\n\nab sofort lautet unsere Bankverbindung IBAN DE55 1001 1001 2620 4466 31 (N26). Bitte überweisen Sie offene Rechnungen nur noch auf dieses Konto.\n\nMusikhaus Elster GmbH")

truth = dict(
    today=TODAY.isoformat(),
    students=len(students), teachers=len(TEACH), contracts=len(contracts), active_contracts=sum(1 for c in contracts if not c["end"] or c["end"] >= TODAY),
    invoices=len(invoices), fees=len(fees), rentals=len(rentals),
    open_invoices=sorted(x["no"] for x in invoices if x["truth"] == "open"),
    open_amount=round(sum(x["amount"] for x in invoices if x["truth"] == "open"), 2),
    overdue=sorted(x["no"] for x in invoices if x["truth"] == "open" and x["due"] < TODAY),
    returned=returned, claim=claim_inv["no"], cancellation=canc["id"],
    maintenance_due=sorted(r["no"] for r in rentals if r["last"] + timedelta(days=365) <= TODAY + timedelta(days=31)),
    batches={f"{m:02d}": round(sum(x["amount"] for x in invoices if x["how"] == "Lastschrift" and x["day"].month == m), 2) for m in range(7, 11)},
    bank_lines=len(bank),
    expected_today=["Rücklastschriften offen (4)", "Überweiser Oktober offen/überfällig (5) + Mai (1)", "Kündigung per Mail (V nicht in Liste)",
                    "Kunde sagt bezahlt (S-1012 Okt.)", "Probestunde-Anfrage", "Betrugsverdacht neue Bankverbindung Musikhaus",
                    "Wartung Mietinstrumente (2)"],
)
(OUT.parent / (OUT.name + "_truth.json")).write_text(json.dumps(truth, ensure_ascii=False, indent=1, default=str))
print(json.dumps(truth, ensure_ascii=False, indent=1, default=str))
