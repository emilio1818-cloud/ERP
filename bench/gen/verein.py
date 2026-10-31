#!/usr/bin/env python3
"""TuS Wendelstede 1907 e.V. – ein erfundener Sportverein (562 Mitglieder, 415 Beitragskonten, fünf Abteilungen: Fußball,
Turnen/Gymnastik, Tennis, Volleyball, Leichtathletik) mit zwei Lieferungen, so wie der Ordner eines ehrenamtlichen
Kassenwarts wirklich aussieht. Ort, Menschen, Firmen, Banken, IBANs (gültige Prüfziffern) und Domains sind erfunden.

    python3 verein.py OUTDIR  ->  OUTDIR/lieferung1/   Stand Mo 21.09.2026 (Daten bis Fr 18.09.)
                                  OUTDIR/lieferung2/   Stand Fr 30.10.2026 (Daten bis Do 29.10.), kompletter neuer
                                                       Ordnerstand (alte Exporte liegen weiter darin)
                                  OUTDIR/truth.json    Format des Prüfstands (bench/one.py)
                                  OUTDIR/answer_key.json  Fallen, Mitglieder, Sollstellungen, Geld, Lastschriftläufe

Fester Seed, byte-gleiche Ausgabe; nur Standardbibliothek + openpyxl + reportlab.

Die Dateien: Mitglieder/Mitglieder_Export_<Tag>.csv (Export des Vereinsprogramms, cp1252; L1 mit den Ausgetretenen 2026,
L2 nur aktive – die alte Datei liegt daneben), Mitglieder/Beitragsordnung_ab_2026-07-01.pdf, Mitglieder/Eintritte_Austritte_
2026.xlsx, Lastschriften/LS_<Tag>_*.xml (pain.008.001.08 je Lauf am 15., FRST/RCUR), Bank/Hauptkonto/Umsaetze_Q1_2026_
StarMoney.sta (MT940 der alten Kassenwartin, Januar–März), Bank/Hauptkonto/Umsaetze_<IBAN>_<von>_bis_<bis>.csv (VR-Bank-CSV
„Bezeichnung Auftragskonto … Name Zahlungsbeteiligter …“; L1 ab 01.04., L2 zusätzlich ab 01.07. überlappend),
Bank/Tennis/<Tag>-9801234-umsatz.CSV (Sparkasse „CSV-MT940“: IBAN und BIC in den Spalten Kontonummer und BLZ),
Kasse/Kassenbuch_2026.xlsx, Kurse/Kursanmeldungen_Herbst_2026.xlsx (ein Blatt je Kurs, Pilates entfällt),
Kurse/Kurse_Fruehjahr_2026.xlsx, Feriencamp/Feriencamp_2026_Anmeldungen_Export.csv (Online-Formular, UTF-8, Komma) und
Feriencamp_2026_Teilnehmer.xlsx, Rechnungen/Rechnungsausgang_2026.xlsx (eigene Rechnungen, „bezahlt am“ bis 31.08. bzw.
15.10. nachgetragen), Rechnungen/Ausgang/*.pdf, Rechnungen/Eingang/*.pdf (Stadt, Verbände, Ausrüster, Platzpflege,
Tennistrainer als Kleinunternehmer), Vertraege/Sponsoringvertraege_2026.xlsx, Vertraege/Hallenbelegung_Fremdnutzer_
2026.xlsx, Vertraege/Pachtvertrag_Vereinsgaststaette.pdf, Uebungsleiter/UEL_Abrechnung_2026.xlsx (ein Blatt je Quartal),
Vorstand/Protokoll_MV_2026-03-20.pdf, Vorstand/Mahnliste_Stand_<Tag>.xlsx (von Hand, hinkt der Bank hinterher),
Vorstand/Protokoll_Vorstand_2026-10-05.pdf (L2), Tennis/Arbeitsstunden_Tennis_2026.xlsx, Mails/*.eml.

DAS FORMAT DER WAHRHEIT (wie bench/gen/hausverwaltung.py). Beiträge, Aufnahme-, Kurs- und Campgebühren, Arbeitsstunden-
Ersatz und die Pacht der Vereinsgaststätte haben keine Rechnungsnummer: geschuldet wird nach Beitragsordnung,
Anmeldung oder Vertrag. Ein offener Posten ist eine Sollstellung „<Personenkonto> <Sollart> <Zeitraum>“, z. B.
„1207 Beitrag Q3/2026“, „1061 Beitrag 2026“, „1053 Beitragsdifferenz H2/2026“, „1648 Aufnahmegebühr“, „1419 Kursgebühr
Herbst 2026“, „9069 Feriencamp 2026“, „1242 Arbeitsstunden 2026“, „1123 Rücklastschriftgebühr 07/2026“, „9003 Pacht
08/2026“. Personenkonto ist die Mitgliedsnummer des Beitragszahlers (Familie: das Hauptmitglied), bei Kurs, Camp und
Arbeitsstunden die Nummer der Person, bei Nichtmitgliedern die Kontaktnummer ab 9001 aus der Kurs- und Campliste. Die
eigenen Rechnungen (Sponsoring, Anzeigen, Hallennutzung) behalten ihre Nummer (2026-0xx). Fällig sind Beiträge am 15. des
ersten Monats des Zeitraums (bzw. folgender Bankarbeitstag), bei Eintritt mit dem Einzug nach dem Eintrittsmonat bzw. 14 Tage
nach Aufnahme, Kursgebühren der Lastschriftzahler am 15.10., sonst zu Kursbeginn, das Camp am 15.07., Arbeitsstunden am
15.10., Pacht am 3. Werktag, Rücklastschriftgebühren 14 Tage nach der Rückgabe. Geschuldet ist, was die Beitragsordnung sagt
– auch wenn das Programm anders eingezogen hat (V04, V07). „nicht berechnet“ kennt nur die eigenen Leistungen
(Sponsoringvertrag, Hallennutzung ohne Rechnung); ein Beitrag wird nie berechnet. „Geld ohne Rechnung“ ist Geld, das keine
Sollstellung und keine Rechnung tilgt und geklärt oder erstattet werden muss; eine Vorauszahlung (V12), eine Spende, ein
Zuschuss, eine Umbuchung, eine Bareinzahlung und die Sammelgutschrift eines Lastschriftlaufs sind es nicht (truth.json:
not_receipts). Was keine Sollstellung ist, aber Arbeit (zu zahlende Eingangsrechnungen, Mails, Betrug, Fristen), steht unter
payables, mails_waiting, risks, deadlines.

ANSWER KEY – die Fallen (Zahlen in truth.json / answer_key.json; check_traps() prüft die mit Kennung)
Lastschrift (Sammelgutschrift je Lauf auf dem Hauptkonto, Einzelposten nur in der pain.008)
V01 1123 Böttcher: Q3-Einzug (72,00) AM04 zurück am 21.07., −75,00 mit 3,00 Auslagenersatz. Mail 28.07. „buchen Sie noch
    mal ab“, Antwort: überweisen. Überweist am 03.08. 72,00, nicht die Gebühr -> L1 und L2 offen „Rücklastschriftgebühr 07/2026“ 3,00.
V02 1207 Familie Wiegand (Kontoinhaberin die Ehefrau): Q3 (114,00) AC04 „Konto erloschen“ am 20.07.; Mail 09.09. „Neue
    Bankverbindung für den Beitragseinzug“ (ein Mitglied, kein Betrug), im Programm am 10.09. -> L1 offen Q3 + Gebühr; der
    Einzug am 15.10. holt Q3, Gebühr und Q4 in einem Posten (231,00) -> L2 nichts offen.
V03 1356 Gieseking kündigt am 25.06. „zum 30.06.“ – zu spät (vier Wochen zum Quartalsende), wirksam 30.09. (Antwort 26.06.).
    Widerspricht am 02.09. dem Juli-Einzug (MD06, −54,00) -> Q3 51,00 offen in L1 und L2, keine Gebühr, kein Q4; L2-Export ohne ihn.
V04 1288 Thiele zum 30.06. ausgetreten, im Programm erst am 20.07. -> der Lauf vom 15.07. zieht Q3 (48,00) noch ein, am 24.07.
    erstattet: keine Forderung, kein Geld ohne Rechnung.
V05 1094 Dettmer zum 30.06. ausgetreten, Dauerauftrag (je 01.02./05./08./11.) läuft weiter: 03.08. 42,00 -> L1 Geld ohne
    Rechnung, am 07.10. erstattet. V05b 1530 Kröncke zum 30.06. ausgetreten, Dauerauftrag 9,00 monatlich am 3.: Juli, August,
    September -> L1 dreimal Geld ohne Rechnung (Juli liegt vor dem 60-Tage-Fenster), am 14.10. 36,00 erstattet.
V06 1462 Hespe: Q3 eingezogen und am 10.08. noch einmal überwiesen -> L1 72,00 Geld ohne Rechnung; im Oktober-Lauf ausgelassen
    und mit Q4 verrechnet -> L2 nichts.
V07 1311 Hartmann wird am 14.05. 18: ab Juni Erwachsenenbeitrag, das Programm stellt erst zum 01.10. um -> Q2 8,00 und Q3
    30,00 offen (L1, L2), Q4 richtig eingezogen.
V08 1003 (Jahreszahler): Januar-Einzug AC01 „IBAN fehlerhaft“ zurück (nur im MT940), mit Gebühr am 16.02. wieder eingezogen.
Überweisung
V09 1150 Rahe: Dauerauftrag 36,00 nach der Erhöhung -> L1 Q3 6,00 offen; der Oktober-Betrag ohne Zeitraum tilgt zuerst den
    Rest von Q3 (§ 366 BGB) -> L2 Q4 12,00 offen.
V10 Jahreszahler und Barzahler ohne die Beitragsdifferenz 2. Hj. (1053, 1061, 1309, 1415, 1425, 1426, 1492, 1513, 1587,
    1635): je 6,00–30,00 offen, die Mahnliste L2 kennt neun davon.
V11 1371/1372 Lena und Jonas Becker: der Vater (kein Mitglied) überweist für beide in einer Summe.
V12 1188 Brinkmann zahlt am 15.07. Q3 und Q4 zusammen (84,00): Q4 ist Vorauszahlung, kein Geld ohne Rechnung.
V13 1240 Strate: Q3 erst am 29.09. -> L1 offen und überfällig, L2 bezahlt. V15 1333 Fasold: Q3 30,00 statt 42,00 „Rest folgt“,
    Rest am 05.10.
V14 1266 Rohlfing: Rückstand Q4/2025 (nur in der Mahnliste), Q2 und Q3; Streichung zum 30.09. (Vorstand 05.10.), fehlt im
    L2-Export, die Forderungen bleiben (135,00).
V16 1405 Elif Demir: die Mutter Selin Yilmaz zahlt „Beitrag Elif“. V17 1517 Voss schreibt „Mitgl.-Nr. 1571“; 1571 Wittkopf
    zahlt Q3 erst am 25.09. V18 zwei Michael Schröder (1102 bar, 1609 Überweisung). V19 1444 Kranz zahlt vom Praxiskonto.
V20 1061 Meyer (Barzahler) kam nicht zur Jahreshauptversammlung: Beitrag 2026 und Differenz offen. 1024 und 1102 zahlten bar.
V21 Ehrenmitglieder (1001, 1002, 1007, 1012, 1019 …) zahlen nichts; 1007 Pape stirbt am 08.08. -> vier Trauerspenden.
V22 1180 Ellerbrock überweist Q3 aufs Tennis-Konto, Umbuchung am 03.08. (eine Zahlung, nicht zwei).
V23 1648 Sieker (Eintritt 01.08.) zahlt den Beitrag, nicht die Aufnahmegebühr (30,00). V24 1652 Wolf (Eintritt 01.10.) hat
    noch nichts gezahlt (Q4 42,00 + 30,00). 1641 Neitzel: Q3 anteilig + Aufnahmegebühr mit dem Septembereinzug.
V25 1514 Steinkamp: Ermäßigung ab Q4 per Mail mit Immatrikulationsbescheinigung (im Programm ab 01.10.).
V26 1584 Aydın: Q4-Einzug AM04 zurück (20.10.), Mail 22.10. mit neuer IBAN -> L2 Q4 51,00 + 3,00 offen.
V27 1077 Ohlendorf überweist den Jahresbeitrag im Januar und am 05.08. noch einmal (Mail 14.09.) -> L1 144,00 Geld ohne
    Rechnung, am 09.10. erstattet. 1598 Lührs überweist den Oktober zusätzlich zur Lastschrift (19.10.) -> L2 14,00.
Kurse, Camp, Arbeitsstunden
V28 Kursgebühren Herbst: Lastschriftzahler werden erst am 15.10. eingezogen (eigene pain.008) -> L1 offen, nicht überfällig;
    1463 zahlt spät (28.09.), Gast 9054 nie; 9043 und 9044 bar in der ersten Stunde (Kassenbuch); 1419: Kurs-Lastschrift AM04
    zurück (21.10.) -> L2 offen + Gebühr.
V29 Petra Hollweg (9029) meldet sich telefonisch an und zahlt am 11.09. (70,00), steht erst ab 25.09. in der Liste -> L1 Geld
    ohne Rechnung, L2 bezahlt.
V30 Gast 9039 zahlt den Frühjahrskurs nie (60,00, Mahnliste). V31 Pilates entfällt: keine Forderung, 65,00 Vorauszahlung erstattet.
V32 Feriencamp: 26 Mitglieder (139,00, Geschwister 119,00 in einer Überweisung), 14 Gäste (169,00); 9069 nie bezahlt („Kind war
    da“); 9065 überweist doppelt (27.07., erstattet 02.10.); 1385 sagt am 25.07. ab, 119,00 zurück, 20,00 Stornogebühr bezahlt.
V33 Tennis-Arbeitsstunden: Sollstellung 01.10. (15,00 je fehlende Stunde), Lastschriftzahler eingezogen 15.10., Überweiser
    zum Teil offen (L2).
Eigene Rechnungen, Verträge, Pacht
V34 2026-003 Elektro Hesse zahlt netto (1.200,00 von 1.428,00, nur im MT940), das Buch sagt „bezahlt am 10.02.“ -> 228,00
    offen; Mail 26.10.: „mit der Spende verrechnen“ (geht nicht). 2026-019 Kröger (1.785,00) spät: Mail 02.10. „gestern
    überwiesen“, Geld am 09.10. 2026-027 TV Ostheide reklamiert die Stunden (Mail 05.10.) -> offen, nicht mahnen.
V35 SV-2026-07 Bandenwerbung Kunstrasen (Autohaus Brinkmann, ab 01.08., 2.000,00 netto) ohne Rechnung -> L1 und L2 nicht
    berechnet; Mail 13.10. „bitte senden Sie uns die Rechnung“. SV-2026-06 ist Sachsponsoring (nicht berechnet ist richtig).
V36 Hallenbelegung: HB-26-007 (13.09.) erst am 02.10. berechnet -> L1 nicht berechnet; HB-26-009 (17.10.) -> L2 nicht
    berechnet; HB-26-006 (29.08.) ist berechnet (2026-028), die Liste aber nicht nachgetragen; HB-26-004 kostenlos.
V37 9003 Pacht (850,00 + USt, Vertrag = Rechnung, Dauerauftrag): August nur 600,00 („Minderung Kühlzelle“, Mail 05.08.;
    Vorstand 05.10.: unberechtigt) -> 411,50 offen in L1 und L2.
Geld, Banken, Mails
V38 Das Hauptkonto Januar–März gibt es nur als MT940 (.sta). V39 Zwei Konten: Tennis-Abteilungsanteil als Umbuchung,
    Bareinzahlungen, Rücklage aufs Tagesgeld (eigenes Geld). V40 Spenden (auch Trauerspenden) und Zuschüsse (Stadt,
    Landessportverband, Kreissportbund) sind kein Geld ohne Rechnung; Zuwendungsbestätigungen sind eine Frist.
V41 Eingangsrechnungen: Sportwerk Hegemann 26-4471 als Datei und als Mail-Anhang (einmal bezahlen); Novák als
    Kleinunternehmer vom Tennis-Konto; Stadt mit Kassenzeichen. Übungsleiter-Abrechnungen sind Ausgaben, keine Forderungen.
V42 Betrug L2: „korrigierte“ Rechnung 26-4471 von sportwerk-hegeman.example mit litauischer IBAN (21.10.); Chef-Masche: „Dieter
    Lohmann“ von einer Gmail-Adresse, 4.870,00 € sofort nach Spanien, „bitte nicht anrufen“ (27.10.).
V43 Kein Betrug: neue IBAN eines Mitglieds für die Lastschrift (V02, V26).
V47 unbekannter Zahler „D. SZYMANSKI“ (niemand dieses Namens im Verein), 25,00 „Beitrag“ (07.09.) -> L1 und L2 Geld ohne
    Rechnung.
"""
from __future__ import annotations

import calendar
import hashlib
import io
import json
import random
import re
import sys
import zipfile
from datetime import date, datetime, timedelta, timezone
from email.message import EmailMessage
from email.utils import format_datetime
from pathlib import Path
from xml.sax.saxutils import escape as xesc

import openpyxl
from openpyxl.styles import Font
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.pdfgen import canvas

SEED = 20261031


def rr(*key) -> random.Random:
    """A random stream per key: the same member gets the same numbers whatever else changes."""
    h = hashlib.sha256(("|".join(map(str, key)) + f"|{SEED}").encode()).hexdigest()
    return random.Random(int(h[:16], 16))


def D(s: str) -> date:
    return date.fromisoformat(s)


# ------------------------------------------------------------------ calendar (SEPA: TARGET days)
TARGET_HOL = {D(x) for x in ("2026-01-01", "2026-04-03", "2026-04-06", "2026-05-01", "2026-12-25", "2026-12-26")}
MONATE = ["Januar", "Februar", "März", "April", "Mai", "Juni", "Juli", "August", "September", "Oktober", "November",
          "Dezember"]


def is_bd(d: date) -> bool:
    return d.weekday() < 5 and d not in TARGET_HOL


def next_bd(d: date) -> date:
    while not is_bd(d):
        d += timedelta(days=1)
    return d


def month_end(y: int, m: int) -> date:
    return date(y, m, calendar.monthrange(y, m)[1])


def run_day(y: int, m: int) -> date:
    """Beitragsordnung § 5: collected on the 15th, or the next bank business day."""
    return next_bd(date(y, m, 15))


def werktag(y: int, m: int, n: int) -> date:
    d, k = date(y, m, 1), 0
    while True:
        if d.weekday() < 6 and d not in TARGET_HOL:  # Saturday counts as a Werktag in a lease, Sunday not
            k += 1
            if k == n:
                return d
        d += timedelta(days=1)


def dde(d: date) -> str:
    return d.strftime("%d.%m.%Y")


def dshort(d: date) -> str:
    return d.strftime("%d.%m.%y")


def de(c: int) -> str:
    s = f"{abs(c) // 100:,}".replace(",", ".") + f",{abs(c) % 100:02d}"
    return ("-" if c < 0 else "") + s


def de_plain(c: int) -> str:
    return ("-" if c < 0 else "") + f"{abs(c) // 100},{abs(c) % 100:02d}"


def xamt(c: int) -> str:
    return f"{c // 100}.{c % 100:02d}"


def eur(c: int) -> float:
    return round(c / 100, 2)


# ------------------------------------------------------------------ banking identifiers
def _mod97(s: str) -> int:
    n = "".join(str(int(ch, 36)) for ch in s)
    return int(n) % 97


def iban_de(blz: str, kto: str) -> str:
    bban = blz + kto.zfill(10)
    return f"DE{98 - _mod97(bban + 'DE00'):02d}{bban}"


def iban_cc(cc: str, bban: str) -> str:
    return f"{cc}{98 - _mod97(bban + cc + '00'):02d}{bban}"


def creditor_id(nat: str) -> str:
    """German SEPA creditor identifier: DE, check digits over the national part, business code ZZZ (not checked)."""
    return f"DE{98 - _mod97(nat + 'DE00'):02d}ZZZ{nat}"


def fmt_iban(i: str) -> str:
    return " ".join(i[k:k + 4] for k in range(0, len(i), 4))


_TR = {"ä": "ae", "ö": "oe", "ü": "ue", "Ä": "Ae", "Ö": "Oe", "Ü": "Ue", "ß": "ss", "é": "e", "è": "e", "á": "a",
       "ı": "i", "ş": "s", "ç": "c", "ğ": "g", "ć": "c", "ł": "l", "ń": "n", "ó": "o", "ś": "s", "ż": "z", "ź": "z",
       "č": "c", "ř": "r", "š": "s", "ž": "z", "ý": "y", "í": "i", "ú": "u", "ů": "u", "ě": "e", "–": "-", "&": "+"}


def sepa(s: str) -> str:
    """What survives the SEPA character set (the bank writes names without umlauts, often in capitals)."""
    s = "".join(_TR.get(ch, ch) for ch in s)
    return re.sub(r"[^A-Za-z0-9/\-?:().,'+ ]", "", s)


# ------------------------------------------------------------------ the club
CLUB = dict(name="TuS Wendelstede 1907 e.V.", short="TuS Wendelstede", street="Am Sportpark 3", zip="31799",
            city="Wendelstede", phone="05723 98 41 07", mail="kasse@tus-wendelstede.example",
            info="info@tus-wendelstede.example", web="www.tus-wendelstede.example", stnr="27/219/30418",
            vr="VR 100417, Amtsgericht Auetal", vat="DE318204771")
BOARD = dict(chair="Dieter Lohmann", vice="Karin Ostermann-Wiese", treasurer="Jens Albers",
             old_treasurer="Helga Brettschneider", office="Petra Kunze")
HEADS = dict(FB="Marco Riedel", TU="Birgit Lanz", TE="Susanne Hoppe", VB="Tim Okonkwo", LA="Gerd Pahl")
DEPTS = dict(FB="Fußball", TU="Turnen/Gymnastik", TE="Tennis", VB="Volleyball", LA="Leichtathletik")

BANKS = {  # blz: (name, bic)
    "25190088": ("Volksbank Auetal eG", "GENODEF1AUE"),
    "25551480": ("Sparkasse Wendelstede-Auetal", "NOLADE21WDS"),
    "29150090": ("Weserland Bank AG", "WELBDE2BXXX"),
    "50010599": ("Direktbank Frankfurt", "DIFFDEF1XXX"),
    "76010099": ("Postbank Nürnberg", "PBNKDEFFXXX"),
    "37040077": ("Commerzbank Hameln", "COBADEFF299"),
    "43060955": ("GLS Gemeinschaftsbank", "GENODEM1GLS"),
    "10011099": ("Onlinebank Berlin", "ONLBDEB1XXX"),
    "25040066": ("Deutsche Bank Hannover", "DEUTDE2H255"),
}
MEMBER_BLZ = ["25190088", "25190088", "25190088", "25551480", "25551480", "25551480", "29150090", "50010599",
              "76010099", "37040077", "43060955", "10011099", "25040066"]

ACCTS = {
    "HK": dict(what="Hauptkonto Volksbank Auetal", blz="25190088", kto="47110800", holder=CLUB["name"]),
    "TK": dict(what="Abteilungskonto Tennis Sparkasse", blz="25551480", kto="9801234", holder="TuS Wendelstede e.V. Abt. Tennis"),
}
for _a in ACCTS.values():
    _a["iban"] = iban_de(_a["blz"], _a["kto"])
    _a["bic"] = BANKS[_a["blz"]][1]
    _a["bank"] = BANKS[_a["blz"]][0]
CI = creditor_id("00001894512")  # the club's Gläubiger-ID


def bank_acct(*key, blz: str | None = None) -> tuple[str, str]:
    r = rr("acct", *key)
    blz = blz or r.choice(MEMBER_BLZ)
    return iban_de(blz, str(r.randint(10 ** 6, 10 ** 10 - 1))), BANKS[blz][1]


# ------------------------------------------------------------------ fees (Beitragsordnung, monthly cents: before / from 01.07.2026)
INCREASE = D("2026-07-01")
GRUND = {"Erwachsene": (1200, 1400), "Familie": (2400, 2800), "Jugend": (600, 700), "Ermäßigt": (800, 900),
         "Passiv": (400, 400), "Ehrenmitglied": (0, 0)}
ZUSCHLAG = {"TE": {"E": (900, 1000), "J": (400, 500)}, "FB": {"E": (200, 300), "J": (0, 0)},
            "VB": {"E": (100, 200), "J": (100, 200)}, "TU": {"E": (0, 0), "J": (0, 0)}, "LA": {"E": (0, 0), "J": (0, 0)}}
AUFNAHME = {"Erwachsene": 3000, "Familie": 4000, "Jugend": 1500, "Ermäßigt": 1500, "Passiv": 0, "Ehrenmitglied": 0}
RL_FEE = 300  # Auslagenersatz of the payer's bank on a returned debit, passed on to the member (§ 7 Beitragsordnung)
RHYTHM_MONTHS = {"monatlich": 1, "vierteljährlich": 3, "halbjährlich": 6, "jährlich": 12}


def at(pair: tuple[int, int], d: date) -> int:
    return pair[1] if d >= INCREASE else pair[0]


# ------------------------------------------------------------------ names
FIRST_M = ["Thomas", "Michael", "Andreas", "Stefan", "Frank", "Jürgen", "Klaus", "Peter", "Uwe", "Ralf", "Jörg", "Holger",
           "Matthias", "Christian", "Markus", "Sven", "Jan", "Dirk", "Carsten", "Torsten", "Oliver", "Daniel", "Sebastian",
           "Tobias", "Florian", "Philipp", "Jens", "Björn", "Marco", "Kai", "Dennis", "Patrick", "Heiko", "Volker",
           "Bernd", "Rainer", "Wolfgang", "Dieter", "Manfred", "Werner", "Günter", "Karl-Heinz", "Hans-Jürgen", "Lars"]
FIRST_F = ["Sabine", "Andrea", "Claudia", "Susanne", "Petra", "Kerstin", "Nicole", "Stefanie", "Anja", "Silke", "Katrin",
           "Tanja", "Birgit", "Heike", "Christina", "Julia", "Sandra", "Melanie", "Nadine", "Jessica", "Sarah", "Lisa",
           "Anna", "Laura", "Katharina", "Maren", "Britta", "Ute", "Monika", "Renate", "Ingrid", "Gisela", "Elke",
           "Karin", "Martina", "Ulrike", "Dagmar", "Ines", "Wiebke", "Imke"]
KIDS_M = ["Ben", "Paul", "Leon", "Finn", "Jonas", "Elias", "Noah", "Luis", "Felix", "Henry", "Emil", "Theo", "Anton",
          "Mats", "Jakob", "Lukas", "Ole", "Bennet", "Fynn", "Mattis", "Tom", "Max", "Niklas", "Moritz", "Linus"]
KIDS_F = ["Emma", "Mia", "Hannah", "Lea", "Lina", "Marie", "Emilia", "Sophie", "Clara", "Ella", "Ida", "Lotta", "Frieda",
          "Mila", "Greta", "Lena", "Pia", "Johanna", "Leni", "Charlotte", "Nele", "Paula", "Jule", "Merle", "Romy"]
LAST = ["Meyer", "Müller", "Schmidt", "Schulze", "Wilkening", "Bruns", "Rodewald", "Behrens", "Thies", "Kruse", "Dreyer",
        "Wöltje", "Lampe", "Stelter", "Hagemann", "Pohl", "Harting", "Bödeker", "Rinne", "Brockmann", "Heuer", "Sander",
        "Wessel", "Lindemann", "Ahrens", "Bartels", "Engelke", "Gerke", "Grote", "Hasse", "Heine", "Jäger", "Kater",
        "Klages", "Köhne", "Landwehr", "Lohse", "Mönkemeyer", "Niemeyer", "Oetker", "Prange", "Reese", "Riechers",
        "Schaper", "Seegers", "Tegtmeyer", "Twele", "Vogt", "Wehrhahn", "Wiebe", "Wolters", "Zeddies", "Busche",
        "Danne", "Evers", "Fricke", "Gödeke", "Hartje", "Ihle", "Kahle", "Lüdeke", "Marquardt", "Nolte", "Ostermann",
        "Pieper", "Quade", "Rehbock", "Sasse", "Tönnies", "Ude", "Vehling", "Warnecke", "Ziesenis", "Bente", "Clausing",
        "Deppe", "Ehlers", "Feldmann", "Gieseke", "Hische", "Imholze", "Jacobs", "Knoke", "Lahmann", "Mehrkens"]
LAST_FOREIGN = [("Yıldız", "tr"), ("Kaya", "tr"), ("Öztürk", "tr"), ("Nowak", "pl"), ("Wiśniewski", "pl"),
                ("Kowalczyk", "pl"), ("Papadopoulos", "gr"), ("Russo", "it"), ("Esposito", "it"), ("Haddad", "ar"),
                ("Petrović", "rs"), ("Novák", "cz"), ("Ivanova", "ru"), ("Fernandes", "pt"), ("Mensah", "gh")]
FOREIGN_FIRST = {"tr": (["Murat", "Emre", "Can", "Deniz"], ["Ayşe", "Elif", "Zeynep", "Derya"]),
                 "pl": (["Piotr", "Tomasz", "Marek"], ["Agnieszka", "Katarzyna", "Joanna"]),
                 "gr": (["Nikos", "Giorgos"], ["Eleni", "Maria"]), "it": (["Marco", "Luca"], ["Giulia", "Chiara"]),
                 "ar": (["Omar", "Karim"], ["Layla", "Rana"]), "rs": (["Milan", "Stefan"], ["Jelena", "Ana"]),
                 "cz": (["Pavel", "Jiří"], ["Petra", "Lucie"]), "ru": (["Alexej", "Dmitri"], ["Olga", "Irina"]),
                 "pt": (["João", "Rui"], ["Ana", "Inês"]), "gh": (["Kwame", "Kofi"], ["Abena", "Ama"])}
STREETS = [("Wendelstede", "31799", ["Am Sportpark", "Hauptstraße", "Kirchweg", "Mühlenstraße", "Lindenallee", "Am Brink",
                                   "Schulstraße", "Bergstraße", "Rosenweg", "Eichendorffstraße", "Am Mühlenteich",
                                   "Bahnhofstraße", "Steinkamp", "Auestraße", "Wiesengrund", "Kastanienweg"]),
           ("Klein Wendelstede", "31799", ["Dorfstraße", "Am Anger", "Feldweg", "Hofweg"]),
           ("Ostheide", "31801", ["Heideweg", "Birkenweg", "Am Kreuzbach", "Ostheider Straße"]),
           ("Hasselbrock", "31803", ["Hasselbrocker Straße", "Im Winkel", "Lange Reihe", "Am Hagen"]),
           ("Bökenhagen", "31804", ["Bökenhagener Weg", "Tannenweg", "Zum Holze"])]
MAILS = ["gmx.example", "web.example", "t-online.example", "posteo.example", "freenet.example", "gmail.example"]


def mail_of(first: str, last: str, key) -> str:
    r = rr("mail", key)
    f, l = sepa(first).lower().replace(" ", ""), sepa(last).lower().replace(" ", "")
    style = r.choice([f"{f}.{l}", f"{f[0]}.{l}", f"{l}.{f}", f"{f}{l}{r.randint(60, 99)}", f"{f}_{l}"])
    return f"{style}@{r.choice(MAILS)}"


# ------------------------------------------------------------------ members
PERSONS: dict[int, dict] = {}   # Mitgliedsnummer -> person
ACCOUNTS: dict[int, dict] = {}  # Beitragskonto (the payer's number) -> account
GUESTS: dict[int, dict] = {}    # Kontakte (non-members) 9001 … : course and camp guests, tenants, sponsors
L1_CUT, L1_DAY = D("2026-09-18"), D("2026-09-21")
L2_CUT, L2_DAY = D("2026-10-29"), D("2026-10-30")


def person(nr, first, last, sex, born, joined, group, depts=(), left=None, why_left="", street=None, key=None,
           title="", mail=True, **kw) -> dict:
    r = rr("person", nr)
    if street is None:
        town, plz, names = STREETS[0] if r.random() < 0.62 else r.choice(STREETS[1:])
        street = (f"{r.choice(names)} {r.randint(1, 48)}{r.choice(['', '', '', 'a', 'b'])}", plz, town)
    p = dict(nr=nr, first=first, last=last, sex=sex, born=born, joined=joined, left=left, why_left=why_left,
             groups=[(date.min, group)], sw_groups=None, depts=list(depts), street=street[0], plz=street[1],
             town=street[2], title=title, acct=nr, phone=f"0{r.choice(['5723', '5724', '5725', '151', '160', '176'])} "
             f"{r.randint(100000, 9999999)}", mail=mail_of(first, last, nr) if mail else "", sw_left_known=None,
             note=kw.pop("note", ""))
    p.update(kw)
    PERSONS[nr] = p
    return p


def group_at(p: dict, d: date, sw: bool = False) -> str:
    g = None
    for since, grp in (p["sw_groups"] if sw and p["sw_groups"] else p["groups"]):
        if since <= d:
            g = grp
    return g


def klasse(grp: str) -> str:
    return "J" if grp in ("Jugend", "Ermäßigt") else "E"


def account(nr, kind, how, rhythm, holder=None, persons=(), iban=None, mref=None, mdate=None, style=None,
            habit=0, **kw) -> dict:
    p = PERSONS[nr]
    holder = holder or f"{p['first']} {p['last']}"
    if how == "Lastschrift" and not iban:
        iban, bic = bank_acct(nr)
    elif iban:
        bic = kw.pop("bic", None) or BANKS.get(iban[4:12], ("", "GENODEF1XXX"))[1]
    else:
        bic = None
    a = dict(nr=nr, kind=kind, how=how, rhythm=rhythm, holder=holder, members=[nr] + [x for x in persons if x != nr],
             iban=iban, bic=bic, mref=mref or (f"TUS-{nr}" if how == "Lastschrift" else None),
             mdate=mdate or (max(p["joined"], D("2014-02-01")) if how == "Lastschrift" else None),
             style=style, habit=habit, ibans=[], payer_iban=kw.pop("payer_iban", None))
    a.update(kw)
    if how != "Lastschrift" and a["payer_iban"] is None:
        a["payer_iban"] = bank_acct("payer", nr)
    for m in a["members"]:
        PERSONS[m]["acct"] = nr
    ACCOUNTS[nr] = a
    return a


def active_in(p: dict, y: int, m: int, sw_on: date | None = None) -> bool:
    first, last = date(y, m, 1), month_end(y, m)
    if p["joined"] > last:
        return False
    left = p["left"]
    if left and sw_on is not None and p.get("sw_left_known") and sw_on < p["sw_left_known"]:
        left = None  # the program did not know yet that this member had left
    return not (left and left < first)


def month_fee(a: dict, y: int, m: int, sw_on: date | None = None) -> int:
    """What the account owes for one month (sw_on: as the club program computed it on that day)."""
    sw = sw_on is not None
    d = date(y, m, 1)
    head = PERSONS[a["nr"]]
    total = 0
    if active_in(head, y, m, sw_on):
        total += at(GRUND[group_at(head, d, sw)], d)
    for nr in a["members"]:
        p = PERSONS[nr]
        if not active_in(p, y, m, sw_on):
            continue
        k = klasse(group_at(p, d, sw)) if group_at(p, d, sw) != "Familie" else ("J" if age_at(p, d) < 18 else "E")
        if group_at(p, d, sw) in ("Passiv", "Ehrenmitglied"):
            continue
        for dep in p["depts"]:
            total += at(ZUSCHLAG[dep][k], d)
    return total


def age_at(p: dict, d: date) -> int:
    b = p["born"]
    return d.year - b.year - ((d.month, d.day) < (b.month, b.day))


def _born(r, lo: int, hi: int) -> date:
    y = r.randint(lo, hi)
    return date(y, r.randint(1, 12), r.randint(1, 28))


def _first(r, sex: str, born: date, nat: str | None = None) -> str:
    if nat:
        return r.choice(FOREIGN_FIRST[nat][0 if sex == "m" else 1])
    if born.year >= 2008:
        return r.choice(KIDS_M if sex == "m" else KIDS_F)
    return r.choice(FIRST_M if sex == "m" else FIRST_F)


# --- the members a trap is about (numbers fixed; the answer key names them)
def build_special():
    S = person
    S(1007, "Erwin", "Pape", "m", D("1938-04-12"), D("1952-05-01"), "Ehrenmitglied", left=D("2026-08-08"),
      why_left="verstorben", note="Ehrenmitglied seit 2002, Ehrenvorsitzender")
    account(1007, "single", "Lastschrift", "jährlich", iban=None)
    S(1012, "Gisela", "Hartwig", "f", D("1941-09-30"), D("1958-03-01"), "Ehrenmitglied", depts=["TU"])
    account(1012, "single", "Überweisung", "jährlich")
    S(1019, "Heinz-Werner", "Lüttmann", "m", D("1946-01-17"), D("1961-08-01"), "Ehrenmitglied", depts=["TE"],
      note="Ehrenmitglied, Vorsitzender 1994-2014")
    account(1019, "single", "Lastschrift", "jährlich")
    S(1024, "Hildegard", "Pape", "f", D("1941-02-03"), D("1962-04-01"), "Erwachsene", depts=["TU"], mail=False)
    account(1024, "single", "Bar", "jährlich", cash=[("2026-03-20", "2026", None), ("2026-09-05", "Beitragsdifferenz H2/2026", None)])
    S(1061, "Walter", "Meyer", "m", D("1944-11-21"), D("1998-07-01"), "Erwachsene", mail=False)
    account(1061, "single", "Bar", "jährlich", cash=[])  # V20: did not come this year
    S(1077, "Renate", "Ohlendorf", "f", D("1952-06-14"), D("2002-05-01"), "Erwachsene", depts=["TU"])
    account(1077, "single", "Überweisung", "jährlich", style="jahr")
    S(1094, "Klaus", "Dettmer", "m", D("1961-03-08"), D("2005-08-01"), "Erwachsene", depts=["FB"], left=D("2026-06-30"),
      why_left="Kündigung vom 18.05.2026")
    account(1094, "single", "Überweisung", "vierteljährlich", style="dauerauftrag", standing=dict(day=1, months=(2, 5, 8, 11), amount=4200))
    S(1102, "Michael", "Schröder", "m", D("1956-10-02"), D("2006-03-01"), "Erwachsene", depts=["TE"], mail=False)
    account(1102, "single", "Bar", "jährlich", cash=[("2026-03-20", "2026", None), ("2026-09-15", "Beitragsdifferenz H2/2026", None)])
    S(1123, "Frank", "Böttcher", "m", D("1971-12-11"), D("2008-05-01"), "Erwachsene", depts=["TE"])
    account(1123, "single", "Lastschrift", "vierteljährlich")
    S(1137, "Hans-Jürgen", "Kock", "m", D("1958-07-22"), D("2009-08-01"), "Erwachsene", depts=["TU"])
    account(1137, "single", "Lastschrift", "halbjährlich")
    S(1150, "Monika", "Rahe", "f", D("1963-05-05"), D("2010-08-01"), "Erwachsene")
    account(1150, "single", "Überweisung", "vierteljährlich", style="dauerauftrag",
            standing=dict(day=10, months=(1, 4, 7, 10), amount=3600))
    S(1180, "Stefan", "Ellerbrock", "m", D("1977-08-19"), D("2012-12-01"), "Erwachsene", depts=["TE"])
    account(1180, "single", "Überweisung", "vierteljährlich", style="nr_q")
    S(1188, "Jutta", "Brinkmann", "f", D("1969-03-27"), D("2013-08-01"), "Erwachsene")
    account(1188, "single", "Überweisung", "vierteljährlich", style="text_q")
    # V02: family, direct debit returned (account closed), new bank by mail, collected again with Q4
    S(1207, "Carsten", "Wiegand", "m", D("1980-02-09"), D("2015-04-01"), "Familie", depts=["TE"],
      street=("Rosenweg 14", "31799", "Wendelstede"))
    S(1208, "Nadine", "Wiegand", "f", D("1982-07-30"), D("2015-04-01"), "Familie", depts=["TU"],
      street=("Rosenweg 14", "31799", "Wendelstede"))
    S(1209, "Paul", "Wiegand", "m", D("2012-04-02"), D("2015-04-01"), "Familie", depts=["FB"],
      street=("Rosenweg 14", "31799", "Wendelstede"), mail=False)
    S(1210, "Mia", "Wiegand", "f", D("2013-11-23"), D("2015-04-01"), "Familie", depts=["TU"],
      street=("Rosenweg 14", "31799", "Wendelstede"), mail=False)
    old_iban, old_bic = bank_acct(1207, "alt", blz="29150090")
    new_iban, new_bic = bank_acct(1207, "neu", blz="10011099")
    account(1207, "family", "Lastschrift", "vierteljährlich", holder="Nadine Wiegand", persons=[1208, 1209, 1210],
            iban=old_iban, bic=old_bic, new_iban=(D("2026-09-10"), new_iban, new_bic))
    S(1222, "Andreas", "Kühn", "m", D("1975-01-15"), D("2015-09-01"), "Erwachsene", depts=["VB"])
    account(1222, "single", "Lastschrift", "halbjährlich")
    S(1240, "Yvonne", "Strate", "f", D("1986-09-09"), D("2016-05-01"), "Erwachsene", depts=["TU"])
    account(1240, "single", "Überweisung", "vierteljährlich", style="text_q")
    S(1266, "Dennis", "Rohlfing", "m", D("1990-12-01"), D("2016-12-01"), "Erwachsene", depts=["FB"],
      left=D("2026-09-30"), why_left="Streichung durch Vorstandsbeschluss vom 05.10.2026 (Beitragsrückstand)",
      sw_left_known=D("2026-10-05"))
    account(1266, "single", "Überweisung", "vierteljährlich", style="plain")
    S(1288, "Sabine", "Thiele", "f", D("1984-04-18"), D("2017-09-01"), "Erwachsene", depts=["VB"],
      left=D("2026-06-30"), why_left="Kündigung vom 12.05.2026", sw_left_known=D("2026-07-20"))
    account(1288, "single", "Lastschrift", "vierteljährlich")
    S(1311, "Leon", "Hartmann", "m", D("2008-05-14"), D("2018-04-01"), "Jugend", depts=["FB"])
    PERSONS[1311]["groups"] = [(date.min, "Jugend"), (D("2026-06-01"), "Erwachsene")]
    PERSONS[1311]["sw_groups"] = [(date.min, "Jugend"), (D("2026-10-01"), "Erwachsene")]
    account(1311, "single", "Lastschrift", "vierteljährlich", holder="Martina Hartmann")
    S(1333, "Ingrid", "Fasold", "f", D("1959-02-28"), D("2018-11-01"), "Erwachsene")
    account(1333, "single", "Überweisung", "vierteljährlich", style="nr_q")
    S(1349, "Torsten", "Vahle", "m", D("1979-06-06"), D("2019-08-01"), "Erwachsene", depts=["TE"])
    account(1349, "single", "Lastschrift", "vierteljährlich")
    S(1356, "Marc", "Gieseking", "m", D("1988-08-08"), D("2019-09-01"), "Erwachsene", depts=["FB"], left=D("2026-09-30"),
      why_left="Kündigung vom 25.06.2026 (zum 30.06. verspätet, wirksam 30.09.)")
    account(1356, "single", "Lastschrift", "vierteljährlich")
    S(1371, "Lena", "Becker", "f", D("2011-03-12"), D("2020-04-01"), "Jugend", depts=["VB"], mail=False,
      street=("Lindenallee 7", "31799", "Wendelstede"))
    S(1372, "Jonas", "Becker", "m", D("2013-10-05"), D("2020-04-01"), "Jugend", depts=["FB"], mail=False,
      street=("Lindenallee 7", "31799", "Wendelstede"))
    becker = bank_acct("Becker", "Thomas", blz="25551480")
    account(1371, "single", "Überweisung", "vierteljährlich", holder="Thomas Becker", style="becker", payer_iban=becker)
    account(1372, "single", "Überweisung", "vierteljährlich", holder="Thomas Becker", style="becker", payer_iban=becker)
    S(1405, "Elif", "Demir", "f", D("2012-01-20"), D("2021-09-01"), "Jugend", depts=["TU"], mail=False)
    account(1405, "single", "Überweisung", "vierteljährlich", holder="Selin Yilmaz", style="vorname")
    S(1419, "Katharina", "Brüggemann", "f", D("1983-12-19"), D("2021-09-01"), "Erwachsene", depts=["TU"])
    account(1419, "single", "Lastschrift", "vierteljährlich")
    S(1444, "Andrea", "Kranz", "f", D("1974-04-04"), D("2022-08-01"), "Erwachsene", depts=["TE"])
    account(1444, "single", "Überweisung", "jährlich", holder="Physiopraxis Kranz GbR", style="kranz",
            payer_iban=bank_acct("Physiopraxis Kranz", blz="25190088"))
    S(1462, "Oliver", "Hespe", "m", D("1985-10-30"), D("2022-09-01"), "Erwachsene", depts=["TE"])
    account(1462, "single", "Lastschrift", "vierteljährlich")
    S(1467, "Finn", "Ruhnke", "m", D("2012-06-17"), D("2022-11-01"), "Jugend", depts=["FB"], left=D("2026-09-30"),
      why_left="Kündigung der Mutter vom 25.08.2026", mail=False)
    account(1467, "single", "Lastschrift", "vierteljährlich", holder="Tanja Ruhnke")
    S(1514, "Jannik", "Steinkamp", "m", D("2005-02-11"), D("2023-10-01"), "Erwachsene", depts=["FB"])
    PERSONS[1514]["groups"] = [(date.min, "Erwachsene"), (D("2026-10-01"), "Ermäßigt")]
    account(1514, "single", "Lastschrift", "vierteljährlich")
    S(1517, "Daniela", "Voss", "f", D("1990-07-07"), D("2023-10-01"), "Erwachsene", depts=["TU"])
    account(1517, "single", "Überweisung", "vierteljährlich", style="dreher")
    S(1530, "Lea", "Kröncke", "f", D("2001-08-25"), D("2024-04-01"), "Ermäßigt", depts=["VB"], left=D("2026-06-30"),
      why_left="Kündigung vom 20.05.2026")
    account(1530, "single", "Überweisung", "vierteljährlich", style="dauerauftrag",
            standing=dict(day=3, months=tuple(range(1, 13)), amount=900, until=D("2026-10-31")))
    S(1571, "Timo", "Wittkopf", "m", D("2010-09-14"), D("2024-09-01"), "Jugend", depts=["FB"], mail=False)
    account(1571, "single", "Überweisung", "vierteljährlich", holder="Bernd Wittkopf", style="text_q")
    S(1584, "Mehmet", "Aydın", "m", D("1993-03-03"), D("2024-09-01"), "Erwachsene", depts=["FB"])
    account(1584, "single", "Lastschrift", "vierteljährlich")
    S(1598, "Svenja", "Lührs", "f", D("1996-11-11"), D("2025-02-01"), "Erwachsene")
    account(1598, "single", "Lastschrift", "monatlich")
    S(1609, "Michael", "Schröder", "m", D("1992-05-26"), D("2025-07-01"), "Erwachsene", depts=["FB"])
    account(1609, "single", "Überweisung", "vierteljährlich", style="name_only")
    S(1641, "Tobias", "Neitzel", "m", D("1989-01-29"), D("2026-08-01"), "Erwachsene", depts=["FB"])
    account(1641, "single", "Lastschrift", "vierteljährlich", mdate=D("2026-07-24"))
    S(1648, "Marlene", "Sieker", "f", D("1999-06-01"), D("2026-08-01"), "Erwachsene", depts=["TU"])
    account(1648, "single", "Überweisung", "vierteljährlich", style="nr_q")
    S(1652, "Kerstin", "Wolf", "f", D("1981-04-12"), D("2026-10-01"), "Erwachsene")
    account(1652, "single", "Überweisung", "vierteljährlich", style="nr_q")


SPECIAL_NRS: set[int] = set()


def build_generic():
    """Everybody else: families, single members, the young ones, the supporting members – paying as most do."""
    SPECIAL_NRS.update(PERSONS)
    r = rr("population")
    units = []
    for i in range(58):
        units.append(("family", i))
    for kind, n in (("Erwachsene", 150), ("Jugend", 96), ("Ermäßigt", 30), ("Passiv", 32), ("Ehrenmitglied", 2)):
        units += [(kind, i) for i in range(n)]
    r.shuffle(units)
    plan = []
    for kind, i in units:
        u = rr("unit", kind, i)
        y = u.choices([u.randint(1966, 1989), u.randint(1990, 2005), u.randint(2006, 2015), u.randint(2016, 2022),
                       u.randint(2023, 2025)], weights=[5, 17, 26, 31, 21])[0]
        if kind == "Ehrenmitglied":
            y = u.randint(1958, 1975)
        if kind == "Jugend":
            y = max(y, 2016)
        plan.append((date(y, u.randint(1, 12), 1), kind, i))
    # a few who joined this spring
    plan += [(D(f"2026-0{m}-01"), k, 900 + j) for j, (m, k) in enumerate([(2, "Erwachsene"), (2, "Jugend"), (3, "family"),
                                                                       (4, "Erwachsene"), (4, "Jugend"), (5, "Ermäßigt"),
                                                                       (5, "Erwachsene"), (6, "Jugend")])]
    plan.sort()
    nr = 1001
    left_gap = rr("gaps")

    def take(n: int) -> list[int]:
        nonlocal nr
        out = []
        while len(out) < n:
            if nr not in SPECIAL_NRS and nr not in PERSONS:
                out.append(nr)
            nr += 1
        return out

    leavers = {D("2026-03-31"): 4, D("2026-06-30"): 6, D("2026-09-30"): 4, D("2026-12-31"): 6}
    # first the people of each unit, then the numbers: a club numbers its members in the order they joined
    specs = []  # (joined, unit index, position, spec)
    unit_specs = []
    for ui, (joined, kind, i) in enumerate(plan):
        u = rr("unit", kind, i)
        nat = u.choice(LAST_FOREIGN) if u.random() < 0.13 else None
        last = nat[0] if nat else u.choice(LAST)
        natc = nat[1] if nat else None
        ps = []
        if kind == "family":
            single_parent = u.random() < 0.15
            kids = u.choices([1, 2, 3], weights=[38, 46, 16])[0]
            b1 = _born(u, 1972, 1992)
            sex1 = u.choice("mf")
            if joined.year < 2026:
                joined = max(joined, date(b1.year + 6, 9, 1))  # nobody joins before school age
            ps.append(dict(first=_first(u, sex1, b1, natc), last=last, sex=sex1, born=b1, joined=joined, group="Familie",
                           depts=_depts(u, "adult")))
            if not single_parent:
                b2 = b1 + timedelta(days=u.randint(-1500, 1500))
                sex2 = "f" if sex1 == "m" else "m"
                first2 = _first(u, sex2, b2, natc)
                alt = rr("firstname", kind, i, "partner")
                while first2 == ps[0]["first"]:
                    first2 = _first(alt, sex2, b2, None)
                ps.append(dict(first=first2, last=last if u.random() < 0.85 else u.choice(LAST), sex=sex2,
                               born=b2, joined=joined, group="Familie", depts=_depts(u, "adult")))
            for k in range(kids):
                bk = _born(u, max(2009, joined.year - 8), 2021)
                sexk = u.choice("mf")
                first_k = _first(u, sexk, bk, natc)
                alt = rr("firstname", kind, i, k)  # its own stream: the rest of the unit stays as it was
                while any(x["first"] == first_k for x in ps):  # no two children of one family with the same name
                    first_k = _first(alt, sexk, bk, None)
                ps.append(dict(first=first_k, last=last, sex=sexk, born=bk,
                               joined=max(joined, date(bk.year + 3, 9, 1)), group="Familie", depts=_depts(u, "kid"),
                               mail=False))
            holder_partner = not single_parent and u.random() < 0.3
            how, rhythm = _how(u, "family")
            unit_specs.append(dict(kind="family", ps=ps, how=how, rhythm=rhythm, holder_partner=holder_partner,
                                   style=_style(u), habit=u.randint(-8, 9)))
        else:
            sex = u.choice("mf")
            if kind == "Jugend":
                b = _born(u, 2009, 2020)
                joined = max(joined, date(b.year + 4, 9, 1)) if joined.year < 2026 else joined
            elif kind == "Ermäßigt":
                b = _born(u, 1999, 2007)
            elif kind in ("Passiv", "Ehrenmitglied"):
                b = _born(u, 1938, 1965)
            else:
                b = _born(u, 1950, 2006)
            if joined.year < 2026 and kind != "Jugend":
                joined = max(joined, date(b.year + 6, 9, 1))
            ps.append(dict(first=_first(u, sex, b, natc), last=last, sex=sex, born=b, joined=joined, group=kind,
                           depts=_depts(u, {"Jugend": "kid", "Ermäßigt": "young"}.get(kind, "adult"))
                           if kind not in ("Passiv", "Ehrenmitglied") else [], mail=kind != "Jugend" and u.random() < 0.8))
            holder = f"{_first(u, u.choice('mf'), _born(u, 1975, 1990), natc)} {last}" if kind == "Jugend" else None
            how, rhythm = _how(u, kind)
            unit_specs.append(dict(kind="single", ps=ps, how=how, rhythm=rhythm, holder=holder, style=_style(u),
                                   habit=u.randint(-8, 9)))
        for k, sp in enumerate(ps):
            specs.append((sp["joined"], ui, k, sp))
    specs.sort(key=lambda x: (x[0], x[1], x[2]))
    for joined, ui, k, sp in specs:
        if joined.year < 2026 and left_gap.random() < 0.13:
            take(1)  # a number of somebody who left before 2026: not in the export
        sp["nr"] = take(1)[0]
    pool_left = []
    for us in unit_specs:
        ps = us["ps"]
        head = ps[0]
        hp = person(head["nr"], head["first"], head["last"], head["sex"], head["born"], head["joined"], head["group"],
                    depts=head["depts"], mail=head.get("mail", True))
        for sp in ps[1:]:
            person(sp["nr"], sp["first"], sp["last"], sp["sex"], sp["born"], sp["joined"], sp["group"], depts=sp["depts"],
                   mail=sp.get("mail", True), street=(hp["street"], hp["plz"], hp["town"]))
        if us["kind"] == "family":
            holder = f"{ps[1]['first']} {ps[1]['last']}" if us["holder_partner"] else None
            a = account(head["nr"], "family", us["how"], us["rhythm"], holder=holder, persons=[sp["nr"] for sp in ps[1:]],
                        style=us["style"], habit=us["habit"])
        else:
            a = account(head["nr"], "single", us["how"], us["rhythm"], holder=us["holder"], style=us["style"],
                        habit=us["habit"])
        if head["joined"].year < 2026:
            pool_left.append(a["nr"])
    # members who leave this year (Kündigung zum Quartalsende), drawn from the ordinary ones
    r2 = rr("leavers")
    cands = [n for n in pool_left if ACCOUNTS[n]["rhythm"] in ("vierteljährlich", "monatlich", "halbjährlich")]
    r2.shuffle(cands)
    for when, k in leavers.items():
        for _ in range(k):
            n = cands.pop()
            if when.month in (3, 9) and ACCOUNTS[n]["rhythm"] == "halbjährlich":
                ACCOUNTS[n]["rhythm"] = "vierteljährlich"  # leaving at the end of a quarter: paid by the quarter
            for m in ACCOUNTS[n]["members"]:
                PERSONS[m]["left"] = when
                PERSONS[m]["why_left"] = "Kündigung"
            ACCOUNTS[n]["leaves"] = when
            ACCOUNTS[n]["cancel_received"] = when - timedelta(days=r2.randint(32, 75))


def _depts(u, who: str) -> list[str]:
    w = {"adult": [("FB", 18), ("TE", 20), ("TU", 30), ("VB", 9), ("LA", 5)],
         "kid": [("FB", 46), ("TU", 32), ("LA", 12), ("TE", 9), ("VB", 6)],
         "young": [("FB", 40), ("VB", 25), ("TE", 15), ("LA", 15)]}[who]
    out = []
    if who == "adult" and u.random() < 0.22:
        return out
    first = u.choices([d for d, _ in w], weights=[x for _, x in w])[0]
    out.append(first)
    if u.random() < 0.14:
        second = u.choices([d for d, _ in w if d != first], weights=[x for d, x in w if d != first])[0]
        out.append(second)
    return sorted(out)


def _how(u, kind: str) -> tuple[str, str]:
    if kind == "Ehrenmitglied":
        return "Lastschrift", "jährlich"
    x = u.random()
    if kind == "Passiv":
        return ("Lastschrift" if x < 0.78 else "Überweisung" if x < 0.94 else "Bar"), "jährlich"
    if x < 0.84:
        return "Lastschrift", u.choices(["monatlich", "vierteljährlich", "halbjährlich", "jährlich"], weights=[16, 44, 14, 26])[0]
    if x < 0.97 or kind in ("Jugend", "family"):
        return "Überweisung", u.choices(["vierteljährlich", "halbjährlich", "jährlich"], weights=[45, 15, 40])[0]
    return "Bar", "jährlich"


def _style(u) -> str:
    return u.choices(["nr_q", "text_q", "plain", "name_only", "nr_only", "full"], weights=[22, 25, 12, 14, 9, 18])[0]


# ------------------------------------------------------------------ guests, tenants, sponsors (Kontakte 9001 …)
def guest(nr, name, kind, **kw) -> dict:
    r = rr("guest", nr)
    g = dict(nr=nr, name=name, kind=kind, iban=None, bic=None, mail="", street="", plz="", town="")
    g.update(kw)
    if not g["iban"]:
        g["iban"], g["bic"] = bank_acct("guest", nr)
    if not g["street"]:
        town, plz, names = r.choice(STREETS)
        g["street"], g["plz"], g["town"] = f"{r.choice(names)} {r.randint(1, 60)}", plz, town
    GUESTS[nr] = g
    return g


def build_guests():
    guest(9003, "Gaststätte am Sportpark, Inh. Nikos Papadakis", "pacht", street="Am Sportpark 3", plz="31799",
          town="Wendelstede", mail="papadakis.sportpark@web.example")
    guest(9011, "Autohaus Brinkmann GmbH", "sponsor", street="Industriestraße 12", plz="31799", town="Wendelstede",
          mail="buchhaltung@autohaus-brinkmann.example", contact="Herr Jörg Brinkmann")
    guest(9012, "Bäckerei Kröger", "sponsor", street="Hauptstraße 21", plz="31799", town="Wendelstede",
          mail="info@baeckerei-kroeger.example", contact="Frau Anke Kröger")
    guest(9013, "Elektro Hesse GmbH & Co. KG", "sponsor", street="Gewerbering 4", plz="31801", town="Ostheide",
          mail="buero@elektro-hesse.example", contact="Herr Ralf Hesse")
    guest(9014, "Versicherungsbüro Lorenz", "sponsor", street="Bahnhofstraße 2", plz="31799", town="Wendelstede",
          mail="lorenz@vb-lorenz.example", contact="Frau Silke Lorenz")
    guest(9015, "Getränke Wiebusch GmbH", "sponsor", street="Am Güterbahnhof 9", plz="31803", town="Hasselbrock",
          mail="info@getraenke-wiebusch.example", contact="Herr Udo Wiebusch")
    guest(9021, "TV Ostheide 1912 e.V.", "renter", street="Sportweg 1", plz="31801", town="Ostheide",
          mail="kasse@tv-ostheide.example", contact="Frau Bärbel Kamphenkel (Kassenwartin)")
    guest(9022, "Hobbyvolleyball Mittwochsgruppe (Kai Brüning)", "renter", street="Am Anger 3", plz="31799",
          town="Klein Wendelstede", mail="kai.bruening@gmx.example", contact="Herr Kai Brüning")
    guest(9023, "Förderverein Grundschule Wendelstede e.V.", "renter", street="Schulstraße 10", plz="31799",
          town="Wendelstede", mail="foerderverein@gs-wendelstede.example", contact="Frau Corinna Thies")
    guest(9024, "JSG Hasselbrock/Bökenhagen", "renter", street="Lange Reihe 30", plz="31803", town="Hasselbrock",
          mail="jugend@jsg-hasselbrock.example", contact="Herr Mirko Danne")


COURSES = [
    dict(code="RF", name="Rückenfit", slot="Mo 18:00–19:00, Halle 2", start=D("2026-09-14"), n=10, fee=(4500, 6500),
         lead="Birgit Lanz", spring=D("2026-03-02")),
    dict(code="YO", name="Yoga", slot="Di 19:30–21:00, Gymnastikraum", start=D("2026-09-15"), n=10, fee=(5000, 7000),
         lead="Anja Petersen", spring=D("2026-03-03")),
    dict(code="ZU", name="Zumba Fitness", slot="Mi 19:00–20:00, Halle 1", start=D("2026-09-16"), n=10, fee=(4000, 6000),
         lead="Daniela Voss", spring=D("2026-03-04")),
    dict(code="PI", name="Pilates", slot="Do 18:30–19:30, Gymnastikraum", start=D("2026-09-17"), n=10, fee=(4500, 6500),
         lead="Anja Petersen", spring=None, cancelled=True),
    dict(code="SP", name="Seepferdchen-Schwimmkurs", slot="Sa 10:00–10:45, Hallenbad Wendelstede", start=D("2026-09-19"),
         n=8, fee=(6000, 8000), lead="Gerd Pahl", spring=None, kids=True),
]
REGS: list[dict] = []   # course registrations, autumn and spring
CAMP: list[dict] = []   # summer camp participants
_guest_nr = [9030]


def new_guest(name: str, kind: str, **kw) -> dict:
    _guest_nr[0] += 1
    return guest(_guest_nr[0], name, kind, **kw)


def _payer_how(konto: int) -> str:
    if konto >= 9000:
        return "Überweisung"
    return ACCOUNTS[PERSONS[konto]["acct"]]["how"]


def build_courses():
    r = rr("courses")
    adults = [p for p in PERSONS.values() if not p["left"] and p["nr"] not in SPECIAL_NRS and age_at(p, L1_CUT) >= 20
              and group_at(p, L1_CUT) not in ("Passiv", "Ehrenmitglied") and "TU" in p["depts"]]
    adults.sort(key=lambda p: p["nr"])
    kids = [p for p in PERSONS.values() if not p["left"] and p["nr"] not in SPECIAL_NRS and 5 <= age_at(p, L1_CUT) <= 7]
    kids.sort(key=lambda p: p["nr"])
    r.shuffle(adults)
    r.shuffle(kids)
    taken = set()
    for term, first in (("Frühjahr 2026", "spring"), ("Herbst 2026", "start")):
        for c in COURSES:
            day0 = c.get(first)
            if not day0:
                continue
            n_members = 3 if c.get("cancelled") else (5 if c.get("kids") else 7)
            n_guests = 2 if c.get("cancelled") else (3 if c.get("kids") else 4)
            pool = kids if c.get("kids") else adults
            mem = [p for p in pool if (p["nr"], term) not in taken][:n_members]
            for p in mem:
                taken.add((p["nr"], term))
                pool.remove(p)
            regs = [dict(konto=p["nr"], name=f"{p['last']}, {p['first']}", member=True) for p in mem]
            for k in range(n_guests):
                g = new_guest(None, "kurs")
                u = rr("courseguest", g["nr"])
                sex = "m" if c.get("kids") and u.random() < 0.5 else ("f" if u.random() < 0.8 else "m")
                b = _born(u, 2019, 2021) if c.get("kids") else _born(u, 1958, 1996)
                first_name = _first(u, sex, b)
                last = u.choice(LAST)
                g["name"] = f"{first_name} {last}"
                g["first"], g["last"], g["born"] = first_name, last, b
                if c.get("kids"):
                    g["parent"] = f"{u.choice(FIRST_F if u.random() < 0.7 else FIRST_M)} {last}"
                g["mail"] = mail_of(g.get("parent", g["name"]).split()[0], last, g["nr"])
                regs.append(dict(konto=g["nr"], name=f"{last}, {first_name}", member=False))
            for k, reg in enumerate(regs):
                u = rr("reg", term, c["code"], k)
                reg.update(term=term, course=c["code"], fee=c["fee"][0 if reg["member"] else 1],
                           registered=day0 - timedelta(days=u.randint(6, 30)), n=k + 1)
                REGS.append(reg)
    rf = [x for x in REGS if x["term"] == "Herbst 2026" and x["course"] == "RF"]
    REGS.append(dict(konto=1419, name="Brüggemann, Katharina", member=True, term="Herbst 2026", course="RF", fee=4500,
                     registered=D("2026-08-27"), n=len(rf) + 1))
    # the cancelled Pilates course: nobody owes anything (one guest had paid in advance and gets it back)
    # a guest who registers by phone after the list was printed (V29) – she pays before she is on the list
    g = guest(9029, "Petra Hollweg", "kurs", first="Petra", last="Hollweg", born=D("1971-02-14"),
              mail="petra.hollweg@t-online.example")
    REGS.append(dict(konto=9029, name="Hollweg, Petra", member=False, term="Herbst 2026", course="YO", fee=7000,
                     registered=D("2026-09-10"), n=len([x for x in REGS if x["term"] == "Herbst 2026" and x["course"] == "YO"]) + 1,
                     listed_from=D("2026-09-25"), phone=True))


def build_camp():
    """Feriencamp 03.–07.08.2026: registration online in June, transfer by 15.07."""
    r = rr("camp")
    kids = [p for p in PERSONS.values() if not p["left"] and p["nr"] not in SPECIAL_NRS and 6 <= age_at(p, D("2026-08-03")) <= 13
            and not any(x["konto"] == p["nr"] and x["term"] == "Herbst 2026" for x in REGS)]
    kids.sort(key=lambda p: p["nr"])
    r.shuffle(kids)
    # siblings first: two children of one family account
    by_acct = {}
    for p in kids:
        by_acct.setdefault(p["acct"], []).append(p)
    sib = [ps[:2] for a, ps in sorted(by_acct.items()) if len(ps) >= 2 and ACCOUNTS[a]["kind"] == "family"][:4]
    chosen = [p for ps in sib for p in ps]
    for p in kids:
        if len(chosen) >= 26:
            break
        if p not in chosen and all(p["acct"] != q["acct"] for q in chosen):
            chosen.append(p)
    k = 0
    for p in chosen:
        k += 1
        second = any(p is ps[1] for ps in sib)
        CAMP.append(dict(n=k, konto=p["nr"], child=f"{p['first']} {p['last']}", member=True, born=p["born"],
                         parent=ACCOUNTS[p["acct"]]["holder"], fee=13900 - (2000 if second else 0),
                         registered=D("2026-06-01") + timedelta(days=rr("campreg", p["nr"]).randint(0, 27)),
                         sibling_of=next((ps[0]["nr"] for ps in sib if p is ps[1]), None)))
    for j in range(14):
        g = new_guest(None, "camp")
        u = rr("campguest", j)
        sex = u.choice("mf")
        b = _born(u, 2013, 2019)
        first_name = _first(u, sex, b)
        last = u.choice(LAST) if j != 5 else "Nowicki"
        g.update(first=first_name, last=last, born=b, name=f"{first_name} {last}",
                 parent=f"{u.choice(FIRST_F)} {last}")
        g["mail"] = mail_of(g["parent"].split()[0], last, g["nr"])
        k += 1
        CAMP.append(dict(n=k, konto=g["nr"], child=g["name"], member=False, born=b, parent=g["parent"], fee=16900,
                         registered=D("2026-06-01") + timedelta(days=u.randint(0, 27)), sibling_of=None))


# ------------------------------------------------------------------ claims (Sollstellungen) and the club's own invoices
CLAIMS: dict[str, dict] = {}
INVOICES: list[dict] = []


def claim(key, konto, art, period, amount, issued, due, label, sw=None, kind="beitrag", note="", acct=None,
          months=()) -> dict:
    assert key not in CLAIMS, key
    c = dict(key=key, konto=konto, art=art, period=period, amount=amount, sw=amount if sw is None else sw,
             issued=issued, due=due, label=label, kind=kind, note=note, acct=acct, months=list(months))
    CLAIMS[key] = c
    return c


def periods(rhythm: str) -> list[tuple[str, list[int]]]:
    if rhythm == "monatlich":
        return [(f"{m:02d}/2026", [m]) for m in range(1, 13)]
    if rhythm == "vierteljährlich":
        return [(f"Q{q}/2026", [3 * q - 2, 3 * q - 1, 3 * q]) for q in range(1, 5)]
    if rhythm == "halbjährlich":
        return [("H1/2026", list(range(1, 7))), ("H2/2026", list(range(7, 13)))]
    return [("2026", list(range(1, 13)))]


def fee_of(a: dict, months: list[int], sw_on: date | None = None, old: bool = False) -> int:
    total = 0
    for m in months:
        if old:  # a yearly payer pays in January at the rates of January
            total += month_fee_old(a, m, sw_on)
        else:
            total += month_fee(a, 2026, m, sw_on)
    return total


def month_fee_old(a: dict, m: int, sw_on: date | None = None) -> int:
    global INCREASE
    keep = INCREASE
    INCREASE = D("2099-01-01")
    try:
        return month_fee(a, 2026, m, sw_on)
    finally:
        INCREASE = keep


def first_due(a: dict, joined: date, regular: date) -> date:
    """A new member: by direct debit with the run after the month of joining, by transfer 14 days after it."""
    if a["how"] == "Lastschrift":
        y, m = (joined.year, joined.month + 1) if joined.month < 12 else (joined.year + 1, 1)
        return max(regular, run_day(y, m))
    return max(regular, joined + timedelta(days=14))


def build_fee_claims():
    for nr, a in sorted(ACCOUNTS.items()):
        head = PERSONS[nr]
        joined = head["joined"]
        for per, months in periods(a["rhythm"]):
            issued = date(2026, months[0], 1)
            due = run_day(2026, months[0])
            yearly = a["rhythm"] == "jährlich"
            amount = fee_of(a, months, old=yearly)
            sw = fee_of(a, months, sw_on=due, old=yearly)
            if joined.year == 2026 and joined <= month_end(2026, months[-1]) and joined >= issued:
                due = first_due(a, joined, due)
                issued = joined
            if amount == 0 and sw == 0:
                continue
            claim(f"{nr} Beitrag {per}", nr, "Beitrag", per, amount, issued, due, f"Mitgliedsbeitrag {per}", sw=sw,
                  months=months)
            if yearly:
                h2 = [m for m in months if m >= 7]
                diff = fee_of(a, h2) - fee_of(a, h2, old=True)
                if diff and joined < INCREASE:
                    claim(f"{nr} Beitragsdifferenz H2/2026", nr, "Beitragsdifferenz", "H2/2026", diff, D("2026-07-01"),
                          run_day(2026, 7), "Beitragserhöhung ab 01.07.2026 (Beschluss MV 20.03.2026), Differenz 2. Halbjahr",
                          kind="beitrag", months=h2)
        if joined.year == 2026 and AUFNAHME[group_at(head, joined)]:
            first = min((c for c in CLAIMS.values() if c["konto"] == nr and c["art"] == "Beitrag"), key=lambda c: c["issued"])
            claim(f"{nr} Aufnahmegebühr", nr, "Aufnahmegebühr", "", AUFNAHME[group_at(head, joined)], joined, first["due"],
                  "Aufnahmegebühr", kind="aufnahme")
    # an arrear from last year that only the dunning list knows (V14)
    claim("1266 Beitrag Q4/2025", 1266, "Beitrag", "Q4/2025", 4200, D("2025-10-01"), D("2025-10-15"),
          "Mitgliedsbeitrag Q4/2025", note="Rückstand aus 2025, nur in der Mahnliste")


def build_other_claims():
    for reg in REGS:
        c = next(x for x in COURSES if x["code"] == reg["course"])
        if c.get("cancelled"):
            continue
        member = reg["konto"] < 9000
        sepa_ = member and _payer_how(reg["konto"]) == "Lastschrift" and reg["term"] == "Herbst 2026"
        start = c["start"] if reg["term"] == "Herbst 2026" else c["spring"]
        due = run_day(2026, 10) if sepa_ else start
        reg["sepa"] = sepa_
        claim(f"{reg['konto']} Kursgebühr {reg['term']}", reg["konto"], "Kursgebühr", reg["term"], reg["fee"],
              reg["registered"], due, f"Kursgebühr {c['name']} {reg['term']}", kind="kurs")
    for x in CAMP:
        claim(f"{x['konto']} Feriencamp 2026", x["konto"], "Feriencamp", "2026", x["fee"], x["registered"],
              D("2026-07-15"), "Feriencamp 03.–07.08.2026" + (" (Geschwisterrabatt)" if x["sibling_of"] else ""),
              kind="camp")
    for m in range(1, 11):
        claim(f"9003 Pacht {m:02d}/2026", 9003, "Pacht", f"{m:02d}/2026", 101150, date(2026, m, 1), werktag(2026, m, 3),
              "Pacht Vereinsgaststätte (850,00 zzgl. 19 % USt)", kind="pacht")


WORK_HOURS: list[dict] = []


def build_work_hours():
    """Tennis: five hours of work on the courts a season, or 15,00 € per missing hour (Abteilungsordnung)."""
    tennis = [p for p in sorted(PERSONS.values(), key=lambda p: p["nr"]) if "TE" in p["depts"] and age_at(p, D("2026-04-01")) >= 18
              and group_at(p, D("2026-09-30")) not in ("Passiv", "Ehrenmitglied") and p["joined"] < D("2026-04-01")
              and not (p["left"] and p["left"] < D("2026-09-30"))]
    for p in tennis:
        u = rr("hours", p["nr"])
        done = 5 if u.random() < 0.8 else u.choice([0, 1, 2, 3, 4])
        if p["nr"] in (1123, 1462):
            done = 5
        if p["nr"] == 1349:
            done = 2
        WORK_HOURS.append(dict(nr=p["nr"], name=f"{p['last']}, {p['first']}", done=done))
        if done < 5:
            claim(f"{p['nr']} Arbeitsstunden 2026", p["nr"], "Arbeitsstunden", "2026", (5 - done) * 1500, D("2026-10-01"), run_day(2026, 10),
                  f"Ersatz für {5 - done} nicht geleistete Arbeitsstunde{'n' if 5 - done > 1 else ''} Tennis 2026", kind="arbeit")


def inv(no, d, to, subject, net, due_days=14, ref="", vat=True, note="") -> dict:
    gross = net + (round(net * 0.19) if vat else 0)
    i = dict(no=no, date=d, to=to, subject=subject, net=net, vat=gross - net, gross=gross, due=d + timedelta(days=due_days),
             ref=ref, note=note)
    INVOICES.append(i)
    claim(no, to, "Rechnung", "", gross, d, i["due"], subject, kind="rechnung")
    return i


def wednesdays(q: int) -> int:
    n = 0
    d = date(2026, 3 * q - 2, 1)
    while d <= month_end(2026, 3 * q):
        if d.weekday() == 2 and not (D("2026-07-02") <= d <= D("2026-08-12")) and d not in TARGET_HOL:
            n += 1  # no hall during the summer holidays (Lower Saxony 02.07.–12.08.2026)
        d += timedelta(days=1)
    return n


HALL: list[dict] = []
SPONSORING: list[dict] = []


def build_invoices():
    sp = [("SV-2026-01", 9011, "Bandenwerbung Rasenplatz 2026 (Kalenderjahr)", D("2026-01-01"), D("2026-12-31"), 120000),
          ("SV-2026-02", 9012, "Bandenwerbung Rasenplatz 2026 (Kalenderjahr)", D("2026-01-01"), D("2026-12-31"), 60000),
          ("SV-2026-03", 9013, "Bandenwerbung Rasenplatz 2026 (Kalenderjahr)", D("2026-01-01"), D("2026-12-31"), 120000),
          ("SV-2026-04", 9014, "Trikotsponsoring D-Jugend Saison 2025/26 (2. Rate)", D("2026-01-01"), D("2026-06-30"), 80000),
          ("SV-2026-05", 9012, "Trikotsponsoring 1. Herren Saison 2026/27", D("2026-08-01"), D("2027-06-30"), 150000),
          ("SV-2026-06", 9015, "Ausschankrecht und Werbung Vereinsheim 2026 – Gegenleistung Getränke (Sachsponsoring)",
           D("2026-01-01"), D("2026-12-31"), 0),
          ("SV-2026-07", 9011, "Bandenwerbung Kunstrasenplatz Saison 2026/27", D("2026-08-01"), D("2027-07-31"), 200000)]
    invd = {"SV-2026-01": ("2026-001", D("2026-01-05")), "SV-2026-02": ("2026-002", D("2026-01-05")),
            "SV-2026-03": ("2026-003", D("2026-01-12")), "SV-2026-04": ("2026-004", D("2026-02-02")),
            "SV-2026-05": ("2026-019", D("2026-08-03"))}
    for no, who, what, a, b, net in sp:
        SPONSORING.append(dict(no=no, who=who, what=what, start=a, end=b, net=net, inv=invd.get(no, (None, None))[0]))
    for no, (ino, d) in sorted(invd.items(), key=lambda x: x[1][0]):
        s = next(x for x in SPONSORING if x["no"] == no)
        inv(ino, d, s["who"], f"{s['what']} lt. Vertrag {no}", s["net"], due_days=28, ref=no)
    # hall time for the Wednesday volleyball group, invoiced each quarter in arrears; single events for other clubs
    hb = 0

    def hall(d, who, what, hours, rate, invoice=None, invoiced=None, free=False, listed_invoice=True, until=None):
        nonlocal hb
        hb += 1
        h = dict(no=f"HB-26-{hb:03d}", date=d, who=who, what=what, hours=hours, rate=rate, net=0 if free else int(hours * rate),
                 inv=invoice, invoiced=invoiced, free=free, listed_invoice=listed_invoice, until=until)
        HALL.append(h)
        return h
    q_inv = {1: ("2026-010", D("2026-03-31")), 2: ("2026-016", D("2026-06-30")), 3: ("2026-030", D("2026-09-30"))}
    plan = [(D("2026-03-31"), 9022, "Hallenzeit Mi 20–22 Uhr, Q1/2026", wednesdays(1) * 2, 2500, 1),
            (D("2026-04-25"), 9021, "Halle 1, Kreismeisterschaft Turnen, 08–16 Uhr", 8, 4000, None),
            (D("2026-06-30"), 9022, "Hallenzeit Mi 20–22 Uhr, Q2/2026", wednesdays(2) * 2, 2500, 2),
            (D("2026-07-11"), 9023, "Halle 1, Sommerfest der Grundschule (Kooperation, kostenlos)", 5, 4000, "free"),
            (D("2026-08-22"), 9021, "Halle 1, Volleyball-Vorbereitungsturnier, 10–16 Uhr", 6, 4000, None),
            (D("2026-08-29"), 9023, "Halle 2, Spielenachmittag Förderverein, 14–17 Uhr", 3, 4000, None),
            (D("2026-09-13"), 9021, "Halle 1, Volleyball-Turnier Damen, 09–17 Uhr", 8, 4000, None),
            (D("2026-09-30"), 9022, "Hallenzeit Mi 20–22 Uhr, Q3/2026", wednesdays(3) * 2, 2500, 3),
            (D("2026-10-17"), 9024, "Halle 1, Hallenturnier E-Jugend, 10–15 Uhr", 5, 4000, None),
            (D("2026-12-31"), 9022, "Hallenzeit Mi 20–22 Uhr, Q4/2026", wednesdays(4) * 2, 2500, "future")]
    events = []
    for d, who, what, hours, rate, q in plan:
        events.append(hall(d, who, what, hours, rate, free=q == "free"))
        events[-1]["q"] = q
    # the invoice book: numbers in the order they were written (sponsoring above, halls, the rest)
    written = [("2026-005", D("2026-01-20"), 9015, "Bandenwerbung Vereinsheim 2026 – Getränke Wiebusch (Barteil)", 25000, None)]
    hb_inv = {}
    for h in events:
        if h["q"] in (1, 2, 3):
            hb_inv[h["no"]] = q_inv[h["q"]]
    hb_inv[events[1]["no"]] = ("2026-012", D("2026-04-30"))
    hb_inv[events[4]["no"]] = ("2026-027", D("2026-08-31"))     # TV Ostheide 22.08.: invoiced, not paid (V36)
    hb_inv[events[5]["no"]] = ("2026-028", D("2026-08-31"))     # Förderverein 29.08.: invoiced, the list not updated
    hb_inv[events[6]["no"]] = ("2026-031", D("2026-10-02"))     # TV Ostheide 13.09.: invoiced only in October
    for h in events:
        if h["no"] in hb_inv:
            h["inv"], h["invoiced"] = hb_inv[h["no"]]
            h["listed_invoice"] = h is not events[5]
    for h in events:
        if h["inv"]:
            written.append((h["inv"], h["invoiced"], h["who"], f"Hallennutzung {h['what']} ({h['no']}, {dde(h['date'])})",
                            h["net"], h["no"]))
    written += [("2026-006", D("2026-02-14"), 9013, "Bewirtung Firmenlauf Elektro Hesse (Getränkestand)", 38000, None),
                ("2026-007", D("2026-02-27"), 9011, "Anzeige Stadionheft Saison 2025/26 Rückrunde", 15000, None),
                ("2026-008", D("2026-03-09"), 9014, "Anzeige Vereinszeitung 1/2026", 9000, None),
                ("2026-009", D("2026-03-20"), 9012, "Anzeige Vereinszeitung 1/2026", 9000, None),
                ("2026-011", D("2026-04-13"), 9015, "Anzeige Vereinszeitung 1/2026", 9000, None),
                ("2026-013", D("2026-05-11"), 9011, "Werbung Banner Sportfest 2026", 30000, None),
                ("2026-014", D("2026-05-29"), 9013, "Anzeige Vereinszeitung 2/2026", 9000, None),
                ("2026-015", D("2026-06-12"), 9014, "Anzeige Vereinszeitung 2/2026", 9000, None),
                ("2026-017", D("2026-07-06"), 9012, "Anzeige Vereinszeitung 2/2026", 9000, None),
                ("2026-018", D("2026-07-20"), 9015, "Werbung Banner Sommerfest 2026", 20000, None),
                ("2026-020", D("2026-08-10"), 9011, "Anzeige Stadionheft Saison 2026/27 Hinrunde", 15000, None),
                ("2026-021", D("2026-08-14"), 9013, "Anzeige Stadionheft Saison 2026/27 Hinrunde", 15000, None),
                ("2026-022", D("2026-08-14"), 9014, "Anzeige Stadionheft Saison 2026/27 Hinrunde", 15000, None),
                ("2026-023", D("2026-08-17"), 9015, "Anzeige Stadionheft Saison 2026/27 Hinrunde", 15000, None),
                ("2026-024", D("2026-08-24"), 9012, "Anzeige Stadionheft Saison 2026/27 Hinrunde", 15000, None),
                ("2026-025", D("2026-08-28"), 9013, "Werbung Banner Sportfest 2026 (Nachtrag)", 10000, None),
                ("2026-026", D("2026-08-28"), 9014, "Anzeige Vereinszeitung 3/2026", 9000, None),
                ("2026-029", D("2026-09-07"), 9011, "Anzeige Vereinszeitung 3/2026", 9000, None),
                ("2026-032", D("2026-10-08"), 9015, "Anzeige Vereinszeitung 3/2026", 9000, None),
                ("2026-033", D("2026-10-19"), 9013, "Anzeige Stadionheft Saison 2026/27 Hinrunde (2. Motiv)", 15000, None)]
    for no, d, who, what, net, ref in sorted(written):
        inv(no, d, who, what, net, due_days=14, ref=ref or "")


# ------------------------------------------------------------------ money: every movement, and which claims it settles
MONEY: list[dict] = []
RUNS: list[dict] = []      # SEPA collection files (pain.008) and their bank credit
CASHBOOK: list[dict] = []  # Kassenbuch


def money(acct, d, amount, name="", iban="", bic="", vwz="", btext="", kind="", alloc=(), **kw) -> dict:
    m = dict(id=len(MONEY) + 1, acct=acct, date=d, amount=amount, name=name, iban=iban or "", bic=bic or "", vwz=vwz,
             btext=btext, kind=kind, alloc=[], undo=[], refunds=[], e2e=kw.pop("e2e", ""), mref=kw.pop("mref", ""),
             ci=kw.pop("ci", ""), note=kw.pop("note", ""), gvc=kw.pop("gvc", ""), sammler=kw.pop("sammler", ""),
             fee=kw.pop("fee", 0))
    m.update(kw)
    for c, cents in alloc:
        m["alloc"].append((CLAIMS[c] if isinstance(c, str) else c, cents, d))
    MONEY.append(m)
    return m


def paid_by(c: dict, cut: date) -> int:
    got = 0
    for m in MONEY:
        if m["date"] > cut:
            continue
        got += sum(x for cc, x, eff in m["alloc"] if cc is c and eff <= cut)
        got -= sum(x for cc, x in m["undo"] if cc is c)
    return got


def open_of(c: dict, cut: date) -> int:
    return c["amount"] - paid_by(c, cut)


def owed_now(konto: int, d: date, kinds=("beitrag", "aufnahme", "rl"), cut: date | None = None) -> list[dict]:
    cs = [c for c in CLAIMS.values() if c["konto"] == konto and c["kind"] in kinds and c["issued"] <= d
          and open_of(c, cut or d) > 0]
    return sorted(cs, key=lambda c: (c["due"], c["key"]))


def pay_oldest(m: dict, konto: int, kinds=("beitrag", "aufnahme", "rl")) -> int:
    """§ 366 Abs. 2 BGB: money that names no period pays the oldest debt first; returns what is left."""
    left = m["amount"]
    for c in owed_now(konto, m["date"], kinds):
        take = min(left, open_of(c, m["date"]))
        if take > 0:
            m["alloc"].append((c, take, m["date"]))
            left -= take
        if left <= 0:
            break
    return left


def iban_on(a: dict, d: date) -> tuple[str, str]:
    if a.get("new_iban") and d >= a["new_iban"][0]:
        return a["new_iban"][1], a["new_iban"][2]
    return a["iban"], a["bic"]


def per_text(c: dict, style: str) -> str:
    per = c["period"]
    if per.startswith("Q"):
        q = int(per[1])
        return {"nr_q": per, "text_q": f"{q}. Quartal 2026", "full": f"Q{q} 2026", "becker": f"{q}. Quartal",
                "vorname": f"{q}. Quartal", "dreher": f"{q}. Quartal 2026"}.get(style, per)
    if per.startswith("H"):
        return {"text_q": f"{per[1]}. Halbjahr 2026", "full": f"{per[1]}. HJ 2026"}.get(style, per)
    if per == "2026":
        return {"text_q": "Jahresbeitrag 2026"}.get(style, "2026")
    return per


def purpose(c: dict, a: dict) -> str:
    p = PERSONS[a["nr"]]
    style = a["style"] or "nr_q"
    if c["kind"] == "aufnahme":
        return f"Aufnahmegebuehr {p['first']} {p['last']} Mitgl.-Nr. {a['nr']}" if style != "plain" else "Aufnahmegebuehr"
    if c["art"] == "Beitragsdifferenz":
        return rr("diffstyle", a["nr"]).choice([f"Nachzahlung Beitragserhoehung 2. Hj. 2026 {p['last']}",
                                                f"Beitragsdifferenz 2026 Mitgl.-Nr. {a['nr']}",
                                                f"Differenz Mitgliedsbeitrag 2026 {p['first']} {p['last']}"])
    pt = per_text(c, style)
    return {"nr_q": f"Mitgliedsbeitrag {pt} Mitgl.-Nr. {a['nr']}",
            "text_q": f"Beitrag {pt} {p['last']}",
            "plain": "Mitgliedsbeitrag",
            "name_only": f"Beitrag {p['first']} {p['last']}",
            "nr_only": f"{a['nr']}",
            "full": f"TuS Wendelstede Beitrag {pt} {p['first']} {p['last']} Nr {a['nr']}",
            "jahr": f"Mitgliedsbeitrag 2026 {p['first']} {p['last']}",
            "becker": f"Beitrag Lena und Jonas Becker {pt}",
            "vorname": f"Beitrag Elif {pt}",
            "kranz": "Mitgliedsbeitrag 2026 Andrea Kranz Mitgl 1444",
            "dreher": f"Beitrag {pt} Mitgl.-Nr. 1571 Voss"}[style]


def transfer_in(a: dict, d: date, amount: int, vwz: str, kind="fee", **kw) -> dict:
    iban, bic = a["payer_iban"] or (a["iban"], a["bic"])
    return money(kw.pop("acct", "HK"), d, amount, name=sepa(a["holder"]).upper() if rr("caps", a["nr"]).random() < 0.5
                 else a["holder"], iban=iban, bic=bic, vwz=vwz, btext="Gutschrift Überweisung", kind=kind, gvc="166", **kw)


def bd_on_or_after(d: date) -> date:
    return next_bd(d)


# --- SEPA collection runs: what the club program collected, per account (its own view of the fees)
RETURNS = {  # (account, run) -> (return day, reason, fee charged to the member)
    (1123, "B", D("2026-07-15")): (D("2026-07-21"), "AM04", "Deckung unzureichend", True),
    (1207, "B", D("2026-07-15")): (D("2026-07-20"), "AC04", "Konto erloschen", True),
    (1356, "B", D("2026-07-15")): (D("2026-09-02"), "MD06", "Erstattung auf Verlangen des Zahlers", False),
    (1584, "B", D("2026-10-15")): (D("2026-10-20"), "AM04", "Deckung unzureichend", True),
    (1419, "S", D("2026-10-15")): (D("2026-10-21"), "AM04", "Deckung unzureichend", True),
}
JAN_RETURN = []  # one ordinary member's January debit with a wrong IBAN, collected again in February


def build_runs():
    jan = next(n for n, a in sorted(ACCOUNTS.items()) if a["how"] == "Lastschrift" and a["rhythm"] == "jährlich"
               and n not in SPECIAL_NRS and PERSONS[n]["joined"] < D("2024-01-01") and a["kind"] == "single"
               and group_at(PERSONS[n], D("2026-01-01")) == "Erwachsene")
    RETURNS[(jan, "B", D("2026-01-15"))] = (D("2026-01-21"), "AC01", "IBAN fehlerhaft", True)
    JAN_RETURN.append(jan)
    for mth in range(1, 11):
        R = run_day(2026, mth)
        for kind in ("B", "S"):
            if kind == "S" and mth != 10:
                continue
            items = []
            for nr, a in sorted(ACCOUNTS.items()):
                if a["how"] != "Lastschrift":
                    continue
                kinds = ("beitrag", "aufnahme") if kind == "B" else ("kurs", "arbeit")
                cs = [c for c in CLAIMS.values() if c["konto"] in a["members"] and c["kind"] in kinds and c["due"] == R
                      and c["sw"] > 0 and (c["kind"] != "kurs" or c["period"] == "Herbst 2026")]
                if kind == "B" and mth == 10 and nr == 1462:
                    cs = []  # V06: his double payment of August is set off against Q4 – left out of the run
                extra = []
                if kind == "B" and mth == 10 and nr == 1207:
                    extra = [CLAIMS["1207 Beitrag Q3/2026"], CLAIMS["1207 Rücklastschriftgebühr 07/2026"]]
                if kind == "B" and mth == 2 and nr == jan:
                    extra = [c for c in CLAIMS.values() if c["konto"] == jan and c["period"] in ("2026",)
                             and c["kind"] == "beitrag"] + [CLAIMS[f"{jan} Rücklastschriftgebühr 01/2026"]]
                cs = cs + extra
                if not cs:
                    continue
                if any(PERSONS[x]["left"] and PERSONS[x]["left"] < R and (not PERSONS[x]["sw_left_known"] or
                                                                         PERSONS[x]["sw_left_known"] <= R)
                       for x in [nr]):
                    continue
                amount = sum(c["sw"] if c not in extra else c["amount"] for c in cs)
                iban, bic = iban_on(a, R)
                items.append(dict(a=a, claims=cs, amount=amount, iban=iban, bic=bic, e2e=f"TUS-{R:%y%m%d}-{kind}{nr}",
                                  vwz=_dd_purpose(a, cs, R, kind)))
            if not items:
                continue
            msg = f"TUSW-{R:%Y%m%d}-{'BEI' if kind == 'B' else 'KUR'}"
            total = sum(x["amount"] for x in items)
            m = money("HK", R, total, name=CLUB["name"], vwz=f"SEPA-Basislastschrift Einreichung {dde(R)} "
                      f"{'Mitgliedsbeitraege' if kind == 'B' else 'Kursgebuehren/Arbeitsstunden'} {len(items)} Posten "
                      f"MSG-ID {msg}", btext="Lastschrift-Einreichung", kind="sepa_lump", gvc="192", sammler=msg)
            for x in items:
                left = x["amount"]
                for c in x["claims"]:
                    take = min(left, c["amount"] - paid_by(c, R) if c["amount"] else 0)
                    take = max(take, 0)
                    if take:
                        m["alloc"].append((c, take, R))
                        left -= take
                x["unallocated"] = left
            RUNS.append(dict(date=R, kind=kind, msg=msg, items=items, money=m,
                             file=f"LS_{R.isoformat()}_{'Mitgliedsbeitraege' if kind == 'B' else 'Kurse_Arbeitsstunden'}.xml"))
            # returned debits of this run
            for x in items:
                key = (x["a"]["nr"], kind, R)
                if key not in RETURNS:
                    continue
                day, code, why, charge = RETURNS[key]
                back = money("HK", day, -(x["amount"] + RL_FEE), name=sepa(x["a"]["holder"]).upper(), iban=x["iban"],
                             bic=x["bic"], vwz=f"RUECKLASTSCHRIFT EREF: {x['e2e']} MREF: {x['a']['mref']} CRED: {CI} "
                             f"SVWZ: {x['vwz'][:60]} RUECKGABEGRUND: {code} {why} ENTGELT {de(RL_FEE)} EUR",
                             btext="Rücklastschrift", kind="return", gvc="109", e2e=x["e2e"], mref=x["a"]["mref"], ci=CI,
                             fee=RL_FEE, reason=code)
                for c, take, eff in m["alloc"]:
                    if c in x["claims"]:
                        back["undo"].append((c, take))
                x["returned"] = day
                if charge:
                    claim(f"{x['a']['nr']} Rücklastschriftgebühr {R:%m/%Y}", x["a"]["nr"], "Rücklastschriftgebühr",
                          f"{R:%m/%Y}", RL_FEE, day, day + timedelta(days=14),
                          f"Bankgebühr Rücklastschrift vom {dde(day)} ({code})", kind="rl")


def _dd_purpose(a: dict, cs: list[dict], R: date, kind: str) -> str:
    if kind == "S":
        parts = []
        for c in cs:
            parts.append("Kursgebuehr " + c["label"].split("Kursgebühr ")[-1] if c["kind"] == "kurs"
                         else f"Arbeitsstunden Tennis 2026 {PERSONS[c['konto']]['first']}")
        return sepa(f"TuS Wendelstede Mitgl.-Nr. {a['nr']} " + ", ".join(parts))
    pers = sorted({c["period"] for c in cs if c["kind"] == "beitrag" and c["art"] == "Beitrag"})
    txt = "Mitgliedsbeitrag " + " ".join(pers) if pers else ""
    if any(c["art"] == "Beitragsdifferenz" for c in cs):
        txt += " Beitragsanpassung 2. Hj. 2026"
    if any(c["kind"] == "aufnahme" for c in cs):
        txt += " Aufnahmegebuehr"
    if any(c["kind"] == "rl" for c in cs):
        txt += " Ruecklastschriftgebuehr"
    return sepa(f"TuS Wendelstede {txt.strip()} Mitgl.-Nr. {a['nr']}")


# --- members who pay by transfer or in cash
PLANTED_TRANSFER = {1077, 1094, 1150, 1180, 1188, 1240, 1266, 1333, 1371, 1372, 1405, 1444, 1517, 1530, 1571, 1609, 1648,
                    1652, 1061, 1024, 1102}


def build_transfers():
    for nr, a in sorted(ACCOUNTS.items()):
        if a["how"] != "Überweisung" or nr in PLANTED_TRANSFER:
            continue
        u = rr("pays", nr)
        for c in sorted((c for c in CLAIMS.values() if c["konto"] == nr and c["kind"] in ("beitrag", "aufnahme")),
                        key=lambda c: c["due"]):
            if c["art"] == "Beitragsdifferenz" and u.random() < 0.35:
                continue  # did not notice the increase (V10): the difference stays open
            day = c["due"] + timedelta(days=a["habit"])
            if c["art"] == "Beitragsdifferenz":
                day = D("2026-07-15") + timedelta(days=u.randint(5, 45))
            day = bd_on_or_after(max(day, c["issued"] - timedelta(days=3)))
            transfer_in(a, day, c["amount"], purpose(c, a), alloc=[(c, c["amount"])])
    for nr, a in sorted(ACCOUNTS.items()):
        if a["how"] != "Bar" or nr in PLANTED_TRANSFER:
            continue
        u = rr("cash", nr)
        for c in sorted((c for c in CLAIMS.values() if c["konto"] == nr and c["kind"] == "beitrag"), key=lambda c: c["due"]):
            if c["art"] == "Beitragsdifferenz":
                if u.random() < 0.5:
                    continue
                day = D("2026-08-20") + timedelta(days=u.randint(0, 25))
            else:
                day = D("2026-03-20") if u.random() < 0.7 else D("2026-01-20") + timedelta(days=u.randint(0, 30))
            while day.weekday() >= 5:
                day += timedelta(days=1)
            cash_in(day, c["amount"], f"{c['label'].replace('Mitgliedsbeitrag', 'Beitrag')} Mitgl. {nr} "
                    f"{PERSONS[nr]['last']} bar", alloc=[(c, c["amount"])])
    _planted_transfers()


def cash_in(d: date, amount: int, text: str, alloc=(), kind="fee", **kw) -> dict:
    m = money("CASH", d, amount, vwz=text, kind=kind, alloc=alloc, **kw)
    return m


def T(nr, d, amount, vwz, alloc=(), **kw):
    return transfer_in(ACCOUNTS[nr], D(d) if isinstance(d, str) else d, amount, vwz, alloc=alloc, **kw)


def _planted_transfers():
    C = CLAIMS
    # cash payers
    cash_in(D("2026-03-20"), 14400, "Beitrag 2026 Mitgl. 1024 Pape bar (JHV)", alloc=[("1024 Beitrag 2026", 14400)])
    cash_in(D("2026-09-07"), 1200, "Beitragsdifferenz 2. Hj. Mitgl. 1024 Pape bar", alloc=[("1024 Beitragsdifferenz H2/2026", 1200)])
    cash_in(D("2026-03-20"), 25200, "Beitrag 2026 Mitgl. 1102 Schröder bar (JHV)", alloc=[("1102 Beitrag 2026", 25200)])
    cash_in(D("2026-09-15"), 1800, "Beitragsdifferenz 2. Hj. Mitgl. 1102 Schröder bar", alloc=[("1102 Beitragsdifferenz H2/2026", 1800)])
    # 1077 pays the year twice (V-receipt), the difference separately
    T(1077, "2026-01-20", 14400, "Mitgliedsbeitrag 2026 Renate Ohlendorf", alloc=[("1077 Beitrag 2026", 14400)])
    T(1077, "2026-07-20", 1200, "Beitragsdifferenz 2. Hj. 2026 Ohlendorf", alloc=[("1077 Beitragsdifferenz H2/2026", 1200)])
    dup = T(1077, "2026-08-05", 14400, "Mitgliedsbeitrag 2026 Renate Ohlendorf", note="zweimal bezahlt (V27)")
    refund(dup, D("2026-10-09"), 14400, "Erstattung doppelt gezahlter Beitrag 2026")
    # 1094: left 30.06., his standing order goes on (V05)
    for d in ("2026-02-02", "2026-05-04", "2026-08-03"):
        m = T(1094, d, 4200, "Dauerauftrag Mitgliedsbeitrag K. Dettmer")
        left = pay_oldest(m, 1094)
        if left:
            m["note"] = "nach Austritt (30.06.) weiter per Dauerauftrag"
            refund(m, D("2026-10-07"), left, "Erstattung Beitrag nach Austritt 30.06.2026 – bitte Dauerauftrag loeschen")
    # 1150: standing order at the old fee (V09)
    for d in ("2026-01-12", "2026-04-10", "2026-07-10", "2026-10-12"):
        m = T(1150, d, 3600, "Dauerauftrag Mitgliedsbeitrag M. Rahe")
        assert pay_oldest(m, 1150) == 0
    # 1180: Q3 to the tennis account by mistake, moved over by the treasurer (V48)
    T(1180, "2026-01-16", 6300, purpose(C["1180 Beitrag Q1/2026"], ACCOUNTS[1180]), alloc=[("1180 Beitrag Q1/2026", 6300)])
    T(1180, "2026-04-16", 6300, purpose(C["1180 Beitrag Q2/2026"], ACCOUNTS[1180]), alloc=[("1180 Beitrag Q2/2026", 6300)])
    T(1180, "2026-07-20", 7200, purpose(C["1180 Beitrag Q3/2026"], ACCOUNTS[1180]), alloc=[("1180 Beitrag Q3/2026", 7200)],
      acct="TK", note="aufs Tennis-Konto statt aufs Hauptkonto (V48)")
    internal(D("2026-08-03"), "TK", "HK", 7200, "Umbuchung Beitrag Ellerbrock Mitgl. 1180 Q3/2026 (falsches Konto)")
    T(1180, "2026-10-14", 7200, purpose(C["1180 Beitrag Q4/2026"], ACCOUNTS[1180]), alloc=[("1180 Beitrag Q4/2026", 7200)])
    # 1188: Q3 and Q4 at once (V12)
    for q, d in ((1, "2026-01-19"), (2, "2026-04-20")):
        T(1188, d, 3600, f"Beitrag {q}. Quartal 2026 Brinkmann", alloc=[(f"1188 Beitrag Q{q}/2026", 3600)])
    T(1188, "2026-07-15", 8400, "Beitrag 3. und 4. Quartal 2026 Brinkmann",
      alloc=[("1188 Beitrag Q3/2026", 4200), ("1188 Beitrag Q4/2026", 4200)])
    # 1240: Q3 late (V13)
    for q, d in ((1, "2026-01-23"), (2, "2026-04-24"), (3, "2026-09-29"), (4, "2026-10-16")):
        c = C[f"1240 Beitrag Q{q}/2026"]
        T(1240, d, c["amount"], purpose(c, ACCOUNTS[1240]), alloc=[(c, c["amount"])])
    # 1266: pays Q1 only (V14)
    T(1266, "2026-01-30", 4200, "Mitgliedsbeitrag", alloc=[("1266 Beitrag Q1/2026", 4200)])
    # 1333: Q3 in part, the rest in October (V15)
    for q, d in ((1, "2026-01-15"), (2, "2026-04-15")):
        c = C[f"1333 Beitrag Q{q}/2026"]
        T(1333, d, c["amount"], purpose(c, ACCOUNTS[1333]), alloc=[(c, c["amount"])])
    T(1333, "2026-07-17", 3000, "Mitgliedsbeitrag Q3/2026 Teilbetrag, Rest folgt Mitgl.-Nr. 1333", alloc=[("1333 Beitrag Q3/2026", 3000)])
    T(1333, "2026-10-05", 1200, "Restbetrag Beitrag Q3/2026 Mitgl.-Nr. 1333", alloc=[("1333 Beitrag Q3/2026", 1200)])
    T(1333, "2026-10-15", 4200, purpose(C["1333 Beitrag Q4/2026"], ACCOUNTS[1333]), alloc=[("1333 Beitrag Q4/2026", 4200)])
    # 1371 + 1372: the father pays for both children in one transfer (V11)
    for q, d in ((1, "2026-01-14"), (2, "2026-04-14"), (3, "2026-07-14"), (4, "2026-10-14")):
        a, b = C[f"1371 Beitrag Q{q}/2026"], C[f"1372 Beitrag Q{q}/2026"]
        T(1371, d, a["amount"] + b["amount"], purpose(a, ACCOUNTS[1371]), alloc=[(a, a["amount"]), (b, b["amount"])])
    # 1405: the mother with another surname (V16)
    for q, d in ((1, "2026-01-21"), (2, "2026-04-21"), (3, "2026-07-21"), (4, "2026-10-21")):
        c = C[f"1405 Beitrag Q{q}/2026"]
        T(1405, d, c["amount"], purpose(c, ACCOUNTS[1405]), alloc=[(c, c["amount"])])
    # 1444: from the practice's account (V19)
    T(1444, "2026-01-26", C["1444 Beitrag 2026"]["amount"], purpose(C["1444 Beitrag 2026"], ACCOUNTS[1444]),
      alloc=[("1444 Beitrag 2026", C["1444 Beitrag 2026"]["amount"])])
    T(1444, "2026-07-22", C["1444 Beitragsdifferenz H2/2026"]["amount"], "Beitrag Diff. 2. Halbjahr A. Kranz",
      alloc=[("1444 Beitragsdifferenz H2/2026", C["1444 Beitragsdifferenz H2/2026"]["amount"])])
    # 1517 writes 1571 (V17); 1571 pays Q3 late
    for q, d in ((1, "2026-01-13"), (2, "2026-04-13"), (3, "2026-07-13"), (4, "2026-10-13")):
        c = C[f"1517 Beitrag Q{q}/2026"]
        T(1517, d, c["amount"], purpose(c, ACCOUNTS[1517]), alloc=[(c, c["amount"])])
    for q, d in ((1, "2026-01-27"), (2, "2026-04-27"), (3, "2026-09-25"), (4, "2026-10-20")):
        c = C[f"1571 Beitrag Q{q}/2026"]
        T(1571, d, c["amount"], purpose(c, ACCOUNTS[1571]), alloc=[(c, c["amount"])])
    # 1530: left 30.06., her monthly standing order goes on until she notices (V05b)
    later = []
    for mth in range(1, 11):
        d = bd_on_or_after(date(2026, mth, 3))
        m = T(1530, d, 900, "Mitgliedsbeitrag Lea Kroencke")
        if pay_oldest(m, 1530):
            m["note"] = "nach Austritt (30.06.) weiter per Dauerauftrag"
            later.append(m)
    refund_many(later, D("2026-10-14"), "Erstattung Beitraege 07-10/2026 nach Austritt 30.06. - Dauerauftrag bitte loeschen")
    # 1609: same name as the senior 1102 (V18)
    for q, d in ((1, "2026-01-16"), (2, "2026-04-16"), (3, "2026-07-16"), (4, "2026-10-19")):
        c = C[f"1609 Beitrag Q{q}/2026"]
        T(1609, d, c["amount"], purpose(c, ACCOUNTS[1609]), alloc=[(c, c["amount"])])
    # 1648: joined in August, paid the quarter, not the entry fee (V23)
    T(1648, "2026-08-20", 2800, "Mitgliedsbeitrag Q3/2026 Mitgl.-Nr. 1648 Sieker", alloc=[("1648 Beitrag Q3/2026", 2800)])
    T(1648, "2026-10-16", 4200, "Mitgliedsbeitrag Q4/2026 Mitgl.-Nr. 1648 Sieker", alloc=[("1648 Beitrag Q4/2026", 4200)])
    # 1652 joined 01.10. and has not paid yet; 1061 did not come to pay in cash (V20)
    # 1462: Q3 by direct debit and by transfer (V06)
    m = transfer_in(ACCOUNTS[1462], D("2026-08-10"), 7200, "Beitrag Q3 2026 Mitglied 1462 Hespe",
                    note="Q3 schon per Lastschrift eingezogen (V06)")
    m["alloc"].append((C["1462 Beitrag Q4/2026"], 7200, D("2026-10-15")))  # set off against Q4 on the day of the run
    # 1123 transfers the returned Q3, not the fee (V01)
    T(1123, "2026-08-03", 7200, "Beitrag Q3 Ruecklastschrift Boettcher 1123", alloc=[("1123 Beitrag Q3/2026", 7200)])
    # 1598 pays October once more by transfer (L2 receipt)
    transfer_in(ACCOUNTS[1598], D("2026-10-19"), 1400, "Beitrag Oktober Luehrs", note="Oktober schon per Lastschrift (L2)")
    # an unknown payer: no member of that name, no number (L1 and L2)
    money("HK", D("2026-09-07"), 2500, name="D. SZYMANSKI", iban=bank_acct("Szymanski")[0], bic=bank_acct("Szymanski")[1],
          vwz="Beitrag", btext="Gutschrift Überweisung", kind="unknown", gvc="166", note="Zahler unbekannt")


def refund(m: dict, d: date, amount: int, vwz: str, batch=None) -> dict:
    out = money(m["acct"] if m["acct"] != "CASH" else "HK", d, -amount, name=m["name"], iban=m["iban"], bic=m["bic"],
                vwz=vwz, btext="Überweisung", kind="refund", gvc="116", refund_of=m["id"], batch=batch)
    m["refunds"].append((d, amount))
    return out


def refund_many(ms: list[dict], d: date, vwz: str) -> dict:
    out = money(ms[0]["acct"], d, -sum(m["amount"] for m in ms), name=ms[0]["name"], iban=ms[0]["iban"], bic=ms[0]["bic"],
                vwz=vwz, btext="Überweisung", kind="refund", gvc="116", refund_of=ms[0]["id"])
    for m in ms:
        m["refunds"].append((d, m["amount"]))
    return out


def internal(d: date, frm: str, to: str, amount: int, vwz: str):
    a, b = ACCTS[frm], ACCTS[to]
    money(frm, d, -amount, name=b["holder"], iban=b["iban"], bic=b["bic"], vwz=vwz, btext="Umbuchung", kind="internal", gvc="116")
    money(to, d, amount, name=a["holder"], iban=a["iban"], bic=a["bic"], vwz=vwz, btext="Umbuchung", kind="internal", gvc="166")


# --- courses, camp, work hours
def payer_of(konto: int) -> dict:
    """The name and account a payment for this person comes from."""
    if konto >= 9000:
        g = GUESTS[konto]
        return dict(holder=g.get("parent") or g["name"], iban=g["iban"], bic=g["bic"], nr=konto)
    a = ACCOUNTS[PERSONS[konto]["acct"]]
    iban, bic = a["payer_iban"] or (a["iban"], a["bic"])
    return dict(holder=a["holder"], iban=iban, bic=bic, nr=a["nr"])


def pay_for(konto: int, d: date, amount: int, vwz: str, alloc=(), kind="kurs", **kw) -> dict:
    who = payer_of(konto)
    name = sepa(who["holder"]).upper() if rr("caps2", konto).random() < 0.5 else who["holder"]
    return money(kw.pop("acct", "HK"), d, amount, name=name, iban=who["iban"], bic=who["bic"], vwz=vwz,
                 btext="Gutschrift Überweisung", kind=kind, alloc=alloc, gvc="166", **kw)


COURSE_UNPAID = {}  # planted: which registration stays unpaid


def build_course_money():
    herbst = [x for x in REGS if x["term"] == "Herbst 2026" and x["course"] != "PI"]
    spring = [x for x in REGS if x["term"] == "Frühjahr 2026"]
    late_member = next(x for x in herbst if x["member"] and not x["sepa"] and x["course"] in ("RF", "YO", "ZU"))
    never_guest = [x for x in herbst if not x["member"] and x["course"] == "ZU"][-1]
    cash_guests = [x for x in herbst if not x["member"] and x["course"] == "RF"][:2]
    spring_never = [x for x in spring if not x["member"] and x["course"] == "ZU"][0]
    COURSE_UNPAID.update(late_member=late_member["konto"], never_guest=never_guest["konto"],
                         cash=[x["konto"] for x in cash_guests], spring_never=spring_never["konto"])
    for x in herbst + spring:
        c = CLAIMS[f"{x['konto']} Kursgebühr {x['term']}"]
        course = next(k for k in COURSES if k["code"] == x["course"])
        start = course["start"] if x["term"] == "Herbst 2026" else course["spring"]
        if x.get("sepa") or x is never_guest or x is spring_never or x["konto"] == 9029:
            continue
        name = x["name"].split(", ")
        vwz = rr("cvwz", x["konto"], x["term"]).choice([f"Kursgebuehr {course['name']} {name[1]} {name[0]}",
                                                         f"{course['name']} {x['term']}", f"Kurs {course['name']} {name[0]}",
                                                         f"Anmeldung {course['name']} {x['term']} {name[1]} {name[0]}"])
        if x in cash_guests:
            cash_in(start, c["amount"], f"Kursgebühr bar {course['name']} {x['name']} ({x['konto']})", alloc=[(c, c["amount"])],
                    kind="kurs")
            continue
        day = x["registered"] + timedelta(days=rr("cday", x["konto"], x["term"]).randint(3, 12))
        day = bd_on_or_after(min(day, start + timedelta(days=2)))
        if x is late_member:
            day = D("2026-09-28")
        pay_for(x["konto"], day, c["amount"], vwz, alloc=[(c, c["amount"])])
    # Hollweg pays before she is on the list (V29): on the list from 25.09.
    c = CLAIMS["9029 Kursgebühr Herbst 2026"]
    c["issued"] = D("2026-09-25")
    m = pay_for(9029, D("2026-09-11"), 7000, "Kursgebuehr Yoga Herbst Hollweg")
    m["alloc"].append((c, 7000, D("2026-09-25")))
    # Pilates is cancelled: the guest who paid early gets the money back
    pi = next(x for x in REGS if x["term"] == "Herbst 2026" and x["course"] == "PI" and not x["member"])
    m = pay_for(pi["konto"], D("2026-09-04"), pi["fee"], f"Pilates Herbst 2026 {pi['name']}", note="Kurs entfällt")
    refund(m, D("2026-09-16"), pi["fee"], "Erstattung Kursgebuehr Pilates - Kurs entfaellt")


CAMP_PLANT = {}


def build_camp_money():
    guests = [x for x in CAMP if not x["member"]]
    never = guests[9]
    twice = next(x for x in guests if GUESTS[x["konto"]]["last"] == "Nowicki")
    cancel = next(x for x in CAMP if x["member"] and not x["sibling_of"]
                  and not any(y["sibling_of"] == x["konto"] for y in CAMP))
    CAMP_PLANT.update(never=never["konto"], twice=twice["konto"], cancel=cancel["konto"])
    done = set()
    for x in CAMP:
        if x["konto"] in done or x is never:
            continue
        c = CLAIMS[f"{x['konto']} Feriencamp 2026"]
        sib = next((y for y in CAMP if y["sibling_of"] == x["konto"]), None)
        u = rr("campday", x["konto"])
        day = bd_on_or_after(min(x["registered"] + timedelta(days=u.randint(4, 20)), D("2026-07-15") + timedelta(days=u.randint(-3, 4))))
        if sib:
            cs = [c, CLAIMS[f"{sib['konto']} Feriencamp 2026"]]
            done.add(sib["konto"])
            pay_for(x["konto"], day, sum(k["amount"] for k in cs),
                    f"Feriencamp 2026 {x['child'].split()[0]} und {sib['child'].split()[0]} {x['child'].split()[-1]}",
                    alloc=[(k, k["amount"]) for k in cs], kind="camp")
            continue
        vwz = u.choice([f"Feriencamp {x['child']}", f"Ferienfreizeit 2026 {x['child']}", f"Camp Anmeldung {x['child']}",
                        f"FC2026 {x['child'].split()[0]}"])
        if x is cancel:
            m = pay_for(x["konto"], day, 13900, vwz, alloc=[(c, 2000)], kind="camp", note="storniert am 25.07., 20,00 einbehalten")
            c["amount"] = 2000
            c["label"] = "Feriencamp 2026 – Stornogebühr nach Absage vom 25.07."
            refund(m, D("2026-08-10"), 11900, f"Erstattung Feriencamp {x['child']} abzgl. 20,00 Stornogebuehr")
            continue
        pay_for(x["konto"], day, c["amount"], vwz, alloc=[(c, c["amount"])], kind="camp")
        if x is twice:
            m = pay_for(x["konto"], D("2026-07-27"), c["amount"], vwz, kind="camp", note="zweimal überwiesen")
            refund(m, D("2026-10-02"), c["amount"], f"Rueckzahlung doppelte Ueberweisung Feriencamp {x['child']}")


def build_work_money():
    for c in sorted((c for c in CLAIMS.values() if c["kind"] == "arbeit"), key=lambda c: c["key"]):
        a = ACCOUNTS[PERSONS[c["konto"]]["acct"]]
        if a["how"] == "Lastschrift":
            continue  # collected with the run of 15.10.
        if rr("workpay", c["key"]).random() < 0.5:
            continue
        pay_for(c["konto"], D("2026-10-14") + timedelta(days=rr("wd", c["key"]).randint(0, 8)), c["amount"],
                f"Arbeitsstunden Tennis 2026 {PERSONS[c['konto']]['last']}", alloc=[(c, c["amount"])], kind="arbeit")


# --- the rest of the club's money: lease, its own invoices, donations, grants, its own bills, cash
SUPPLIERS = {
    "STADT": dict(name="Stadt Wendelstede", sub="Fachdienst Bildung, Sport und Kultur", street="Rathausplatz 1",
                  plz="31799", town="Wendelstede", blz="25551480", kto="100500", mail="sport@wendelstede.example"),
    "HEG": dict(name="Sportwerk Hegemann GmbH", street="Am Hafen 17", plz="31785", town="Hameln-Wehrbergen",
                blz="37040077", kto="4471800", mail="rechnung@sportwerk-hegemann.example", ust="DE287114052"),
    "GL": dict(name="Grün & Linie Platzservice Diekmann", street="Im Bruch 4", plz="31803", town="Hasselbrock",
               blz="25190088", kto="66120", mail="diekmann@gruen-und-linie.example", ust="DE301447281"),
    "TA": dict(name="Teamsport Ahlers e.K.", street="Marktstraße 30", plz="31655", town="Stadtfeld",
               blz="29150090", kto="7712050", mail="info@teamsport-ahlers.example", ust="DE244091378"),
    "LSV": dict(name="Landessportverband Weserland e.V.", street="Ferdinand-Wallbrecht-Weg 2", plz="30163",
                town="Hannover-List", blz="25040066", kto="88800", mail="beitraege@lsv-weserland.example"),
    "KSB": dict(name="Kreissportbund Auetal e.V.", street="Kreishaus, Bahnhofstraße 2", plz="31799", town="Wendelstede",
                blz="25551480", kto="203040", mail="info@ksb-auetal.example"),
    "BFV": dict(name="Bezirksfußballverband Weserland e.V.", street="Sportweg 8", plz="31785", town="Hameln",
                blz="25040066", kto="404040", mail="spielbetrieb@bfv-weserland.example", ci=creditor_id("00000412870")),
    "SWW": dict(name="Stadtwerke Wendelstede GmbH", street="Wasserweg 1", plz="31799", town="Wendelstede",
                blz="25551480", kto="555000", mail="kundenservice@stadtwerke-wendelstede.example", ci=creditor_id("00000771134")),
    "NOV": dict(name="Tennisschule Marek Novák", street="Am Brink 11", plz="31799", town="Wendelstede", blz="43060955",
                kto="2209876", mail="marek@tennisschule-novak.example"),
    "TVW": dict(name="Tennisverband Weserland e.V.", street="Sportweg 8", plz="31785", town="Hameln", blz="25040066",
                kto="515151", mail="meldung@tennis-weserland.example", ci=creditor_id("00000338211")),
}
for _s in SUPPLIERS.values():
    _s["iban"] = iban_de(_s["blz"], _s["kto"])
    _s["bic"] = BANKS[_s["blz"]][1]
SUPINV: list[dict] = []
UEL: list[dict] = []
UEL_PEOPLE = [("ÜL-01", "Birgit Lanz", "TU", "Gesundheitssport, Rückenfit", 1500), ("ÜL-02", "Anja Petersen", "TU", "Yoga, Pilates", 1500),
              ("ÜL-03", "Daniela Voss", "TU", "Zumba, Kinderturnen", 1200), ("ÜL-04", "Marco Riedel", "FB", "1. Herren", 1500),
              ("ÜL-05", "Hakan Yıldız", "FB", "C-Jugend", 1000), ("ÜL-06", "Nils Bartels", "FB", "E-Jugend", 800),
              ("ÜL-07", "Sophie Heine", "FB", "F-Jugend/Bambini", 800), ("ÜL-08", "Tim Okonkwo", "VB", "Damen 1, Jugend", 1200),
              ("ÜL-09", "Gerd Pahl", "LA", "Leichtathletik Kinder, Schwimmkurs", 1200),
              ("ÜL-10", "Imke Wolters", "TU", "Eltern-Kind-Turnen", 1000), ("ÜL-11", "Lukas Gerke", "LA", "Lauftreff", 800),
              ("ÜL-12", "Svetlana Ivanova", "TU", "Seniorengymnastik", 1000)]


def sup(key, no, d, lines, due_days, paid=None, acct="HK", skonto=None, fmt="pdf", note="", **kw) -> dict:
    net = sum(q * p for _, q, p in lines)
    vat = 0 if key in ("STADT", "LSV", "KSB", "NOV", "TVW", "BFV") else round(net * 0.19)
    x = dict(sup=key, no=no, date=d, lines=lines, net=net, vat=vat, gross=net + vat, due=d + timedelta(days=due_days),
             paid=paid, acct=acct, skonto=skonto, fmt=fmt, note=note)
    x.update(kw)
    SUPINV.append(x)
    if paid:
        s = SUPPLIERS[key]
        money(acct, paid, -x["gross"], name=s["name"], iban=s["iban"], bic=s["bic"],
              vwz=f"{'Kassenzeichen' if key == 'STADT' else 'Rechnung'} {no} {kw.get('ref', '')}".strip(),
              btext="Überweisung", kind="cost", gvc="116")
    return x


def build_rest():
    C = CLAIMS
    gp = GUESTS[9003]
    for mth in range(1, 11):
        d = werktag(2026, mth, 2)
        while not is_bd(d):
            d += timedelta(days=1)
        c = C[f"9003 Pacht {mth:02d}/2026"]
        amt = 60000 if mth == 8 else 101150
        money("HK", d, amt, name="NIKOS PAPADAKIS", iban=gp["iban"], bic=gp["bic"],
              vwz=f"Pacht Vereinsgaststaette {MONATE[mth - 1]} 2026" + (" abzgl. Minderung Kuehlzelle" if mth == 8 else ""),
              btext="Dauerauftrag", kind="pacht", alloc=[(c, amt)], gvc="152")
    # the club's own invoices: who pays when
    special = {"2026-003": [(D("2026-02-10"), 120000, "Bandenwerbung 2026 Rg. 2026-003")],
               "2026-019": [(D("2026-10-09"), 178500, "Rechnung 2026-019 Trikotsponsoring")],
               "2026-027": [], "2026-031": [(D("2026-10-20"), None, "Rechnung 2026-031 Hallennutzung 13.09.")],
               "2026-033": [], "2026-002": [(D("2026-01-29"), None, "Bandenwerbung 2026 Baeckerei Kroeger")],
               "2026-030": [(D("2026-10-12"), None, "Hallenmiete Mittwochsgruppe 3. Quartal")]}
    for i in sorted(INVOICES, key=lambda i: i["no"]):
        g = GUESTS[i["to"]]
        c = C[i["no"]]
        pays = special.get(i["no"])
        if pays is None:
            u = rr("invpay", i["no"])
            day = bd_on_or_after(i["date"] + timedelta(days=u.randint(6, 24)))
            pays = [(day, None, u.choice([f"Rechnung {i['no']}", f"Rg.-Nr. {i['no']}", f"RE {i['no']} {g['name'][:20]}",
                                          f"Rechnungsnr. {i['no']} vom {dde(i['date'])}"]))]
        for day, amt, vwz in pays:
            amt = amt or i["gross"]
            money("HK", day, amt, name=sepa(g["name"]).upper() if i["to"] in (9011, 9013) else g["name"], iban=g["iban"],
                  bic=g["bic"], vwz=vwz, btext="Gutschrift Überweisung", kind="invoice", alloc=[(c, amt)], gvc="166")
    # donations (no claim, a donation receipt to write) and grants (no claim)
    gifts = [("HK", D("2026-02-18"), 25000, "Autohaus Brinkmann GmbH", "Spende Jugendfussball", "spende"),
             ("HK", D("2026-05-12"), 5000, "Hans-Juergen Kock", "Spende", "spende"),
             ("HK", D("2026-07-03"), 15000, "Raiffeisenmarkt Wendelstede eG", "Spende Tombola Sommerfest", "spende"),
             ("HK", D("2026-08-21"), 3000, "Ursula und Heinz Lampe", "Trauerspende Erwin Pape", "spende"),
             ("HK", D("2026-08-24"), 5000, "Dr. Johannes Wehrhahn", "Spende im Gedenken an Erwin Pape fuer die Jugend", "spende"),
             ("HK", D("2026-08-24"), 2000, "Monika Tegtmeyer", "Kondolenzspende Pape", "spende"),
             ("HK", D("2026-08-27"), 2500, "Skatclub Gut Blatt Wendelstede", "Trauerspende E. Pape", "spende"),
             ("TK", D("2026-09-14"), 10000, "Dr. Ulrike Saathoff", "Spende Tennisjugend", "spende"),
             ("HK", D("2026-10-09"), 50000, "Elektro Hesse GmbH + Co. KG", "Spende 2026", "spende"),
             ("HK", D("2026-06-18"), 350000, "Stadt Wendelstede", "Sportfoerderung 2026 Zuschuss Vereinsjugend Kassenzeichen 5.0420.0117", "zuschuss"),
             ("HK", D("2026-08-28"), 192000, "Landessportverband Weserland e.V.", "Uebungsleiterzuschuss 2026 Verein 31-0412", "zuschuss"),
             ("HK", D("2026-09-04"), 60000, "Kreissportbund Auetal e.V.", "Zuschuss Ferienfreizeit 2026", "zuschuss"),
             ("HK", D("2026-10-16"), 220000, "Stadt Wendelstede", "Zuschuss Unterhaltung Sportanlagen 2026 2. Rate", "zuschuss")]
    for acct, d, amt, name, vwz, kind in gifts:
        iban, bic = bank_acct("gift", name, d)
        if name.startswith("Stadt"):
            iban, bic = SUPPLIERS["STADT"]["iban"], SUPPLIERS["STADT"]["bic"]
        if name.startswith("Autohaus"):
            iban, bic = GUESTS[9011]["iban"], GUESTS[9011]["bic"]
        if name.startswith("Elektro"):
            iban, bic = GUESTS[9013]["iban"], GUESTS[9013]["bic"]
        money(acct, d, amt, name=name, iban=iban, bic=bic, vwz=vwz, btext="Gutschrift Überweisung", kind=kind, gvc="166")
    # the tennis department's share of the fees, moved each quarter
    for d, amt in ((D("2026-01-20"), 215000), (D("2026-04-20"), 98000), (D("2026-07-20"), 236000), (D("2026-10-20"), 104000)):
        internal(d, "HK", "TK", amt, f"Abteilungsanteil Tennis Beitraege {(d.month + 2) // 3}. Quartal 2026")
    # cash: the cash book (Kassenbuch) and its deposits
    cash_book()
    # coaches: Übungsleiterpauschale, paid each quarter for the quarter before
    for q, paid in ((4, D("2026-01-12")), (1, D("2026-04-08")), (2, D("2026-07-06")), (3, D("2026-10-06"))):
        yr = 2025 if q == 4 else 2026
        for code, name, dep, group, rate in UEL_PEOPLE:
            u = rr("uel", code, q)
            hours = u.randint(36, 52) if q != 3 else u.randint(22, 34)  # no training in the summer holidays
            amt = hours * rate
            UEL.append(dict(q=q, year=yr, code=code, name=name, dep=dep, group=group, hours=hours, rate=rate, amount=amt,
                            paid=paid))
            iban, bic = bank_acct("uel", code)
            money("HK", paid, -amt, name=name, iban=iban, bic=bic, vwz=f"Uebungsleiterpauschale {q}. Quartal {yr} {code}",
                  btext="Überweisung", kind="cost", gvc="116")
    # what the club pays: notices, invoices, debits
    sup("LSV", "B-2026-31-0412", D("2026-01-10"), [("Mitgliedsbeitrag 2026 lt. Bestandserhebung (562 Mitglieder × 5,25 €), "
                                                    "inkl. Sportversicherung", 1, 295050)], 49, paid=D("2026-02-25"))
    sup("KSB", "KSB-26-0412", D("2026-02-15"), [("Sportabgabe 2026 (562 Mitglieder × 1,20 €)", 1, 67440)], 44, paid=D("2026-03-25"))
    for q, d, paid in ((1, D("2026-01-05"), D("2026-02-13")), (2, D("2026-04-02"), D("2026-05-12")),
                       (3, D("2026-07-03"), D("2026-08-14")), (4, D("2026-10-05"), None)):
        due = date(2026, 3 * q - 1, 15)
        sup("STADT", f"5.0226.{4700 + q:06d}", d, [(f"Nutzungsentgelt städtische Sporthallen {q}. Quartal 2026 "
                                                    f"(Halle 1 und 2, lt. Belegungsplan)", 1, 241800)], (due - d).days, paid=paid,
            kind="bescheid")
    sup("HEG", "26-3120", D("2026-03-12"), [("Trainingsbälle Größe 5, Molten", 20, 2490), ("Hütchen-Set 48 tlg.", 4, 3490),
                                            ("Ballnetz 10 Bälle", 4, 1290)], 30, paid=D("2026-03-20"), skonto=(2, 10))
    sup("HEG", "26-4471", D("2026-09-10"), [("Wettspielbälle Größe 4, Derbystar", 12, 3490), ("Leibchen-Set 10 Stk.", 4, 3990),
                                            ("Minitore 2er-Set", 2, 18990), ("Koordinationsleiter", 4, 2490)], 30,
        paid=D("2026-10-06"), skonto=(2, 10))
    for mth, paid in ((4, D("2026-05-11")), (5, D("2026-06-10")), (6, D("2026-07-09")), (7, D("2026-08-10")),
                      (8, D("2026-09-28")), (9, None)):
        d = month_end(2026, mth)
        sup("GL", f"GL-2026-{mth:02d}{17 + mth}", d, [(f"Rasenpflege Hauptplatz {MONATE[mth - 1]} 2026 (Mähen, Linieren, Düngen)",
                                                    1, 100000)], 30, paid=paid)
    sup("TA", "TA-26-1187", D("2026-10-09"), [("Trikotsatz 1. Herren (16 Trikots, Beflockung Sponsor)", 1, 264700)], 30)
    for mth in range(4, 10):
        d = month_end(2026, mth)
        hours = rr("nov", mth).randint(16, 24)
        sup("NOV", f"TS-2026-{mth:02d}", d, [(f"Tennistraining Jugend und Mannschaften {MONATE[mth - 1]} 2026 (Std.)", hours, 4000)],
            14, paid=(d + timedelta(days=9)) if mth < 9 else None, acct="TK", kleinunternehmer=True)
    s = SUPPLIERS["TVW"]
    money("TK", D("2026-03-16"), -42000, name=s["name"], iban=s["iban"], bic=s["bic"], vwz="Mannschaftsmeldung Sommer 2026 "
          "6 Mannschaften", btext="Lastschrift", kind="cost", ci=s["ci"], mref="TVW-0412", gvc="105")
    for mth in range(2, 11):
        s = SUPPLIERS["BFV"]
        amt = rr("bfv", mth).randint(90, 480) * 100
        money("HK", date(2026, mth, 6) if is_bd(date(2026, mth, 6)) else next_bd(date(2026, mth, 6)), -amt, name=s["name"],
              iban=s["iban"], bic=s["bic"], vwz=f"Sammelrechnung Spielbetrieb {MONATE[mth - 2]} 2026 Verein 31-0412 "
              f"(Schiedsrichterkosten, Gebuehren)", btext="Lastschrift", kind="cost", ci=s["ci"], mref="BFV-31-0412", gvc="105")
    for mth in range(4, 11):
        s = SUPPLIERS["SWW"]
        money("HK", next_bd(date(2026, mth, 28)), -8500, name=s["name"], iban=s["iban"], bic=s["bic"],
              vwz=f"Abschlag Wasser Sportplatz Beregnung {mth:02d}/2026 Vertragskonto 4100223", btext="Lastschrift",
              kind="cost", ci=s["ci"], mref="SWW-4100223", gvc="105")
    for mth in range(1, 11):  # the artificial pitch of 2024: a loan with the house bank, and the floodlight's power
        money("HK", next_bd(date(2026, mth, 30 if mth != 2 else 27)), -148000, name="Volksbank Auetal eG",
              vwz=f"Rate Darlehen 0047110850 Kunstrasenplatz {mth:02d}/2026 Zins und Tilgung", btext="Darlehensrate",
              kind="cost", gvc="805")
        s2 = SUPPLIERS["SWW"]
        money("HK", next_bd(date(2026, mth, 10)), -(38000 if mth in (1, 2, 3, 10, 11, 12) else 16000), name=s2["name"],
              iban=s2["iban"], bic=s2["bic"], vwz=f"Abschlag Strom Flutlicht/Kabinen {mth:02d}/2026 Vertragskonto 4100224",
              btext="Lastschrift", kind="cost", ci=s2["ci"], mref="SWW-4100224", gvc="105")
    for mth in range(1, 11):  # the groundsman (Minijob) and the first team's coach
        d = month_end(2026, mth)
        while not is_bd(d):
            d -= timedelta(days=1)
        iban, bic = bank_acct("platzwart")
        money("HK", d, -53800, name="Bernd Kahle", iban=iban, bic=bic, vwz=f"Lohn Minijob Platzwart {mth:02d}/2026",
              btext="Überweisung", kind="cost", gvc="116")
        money("HK", d, -17240, name="Minijob-Zentrale", iban=iban_de("37040077", "8800101"), bic="COBADEFF299",
              vwz=f"Abgaben Minijob {mth:02d}/2026 BNR 31041277", btext="Lastschrift", kind="cost",
              ci=creditor_id("00000102034"), mref="MJZ-31041277", gvc="105")
        iban, bic = bank_acct("trainer1h")
        money("HK", d, -60000, name="Sascha Brockmann", iban=iban, bic=bic,
              vwz=f"Aufwandsentschaedigung Trainer 1. Herren {mth:02d}/2026", btext="Überweisung", kind="cost", gvc="116")
    for d in (D("2026-03-02"), D("2026-06-01"), D("2026-09-01")):
        money("HK", d, -500000, name=CLUB["name"], iban=iban_de("25190088", "47110877"), bic="GENODEF1AUE",
              vwz="Uebertrag Ruecklage Instandhaltung auf Tagesgeld 47110877", btext="Umbuchung", kind="internal", gvc="116")
    for d, fee in ((D("2026-03-31"), 3840), (D("2026-06-30"), 4110), (D("2026-09-30"), 3975)):
        money("HK", d, -fee, name="", vwz=f"Abschluss per {dde(d)} Kontofuehrung und Buchungsposten", btext="Abschluss",
              kind="cost", gvc="805")
        money("TK", d, -1250, name="", vwz=f"Entgeltabschluss {dde(d)}", btext="ENTGELTABSCHLUSS", kind="cost", gvc="805")
    # the July run collected a member who had left (V04): paid back
    run = next(r for r in RUNS if r["date"] == D("2026-07-15") and r["kind"] == "B")
    x = next(x for x in run["items"] if x["a"]["nr"] == 1288)
    out = money("HK", D("2026-07-24"), -x["amount"], name="Sabine Thiele", iban=x["iban"], bic=x["bic"],
                vwz="Erstattung Mitgliedsbeitrag Q3/2026 - Austritt zum 30.06.2026", btext="Überweisung", kind="refund",
                gvc="116", refund_of=run["money"]["id"])
    run["money"]["refunds"].append((out["date"], x["amount"]))


def cash_book():
    """The cash box of the office (Geschäftsstelle): fees and course fees paid in cash, the summer fete, deposits."""
    rows = [(D("2026-03-20"), -4120, "Getränke Jahreshauptversammlung (Beleg Getränke Wiebusch)", "out"),
            (D("2026-03-23"), -60000, "Bareinzahlung Volksbank", "deposit"),
            (D("2026-06-27"), 128450, "Sommerfest Getränke- und Speisenverkauf", "sale"),
            (D("2026-06-27"), -41280, "Sommerfest Grillgut (Beleg Fleischerei Kahle)", "out"),
            (D("2026-06-29"), -100000, "Bareinzahlung Volksbank", "deposit"),
            (D("2026-08-07"), 21600, "Feriencamp Getränke/Eis Verkauf", "sale"),
            (D("2026-09-22"), -1890, "Porto, Briefmarken Geschäftsstelle", "out"),
            (D("2026-10-05"), -30000, "Bareinzahlung Volksbank", "deposit"),
            (D("2026-10-17"), 18350, "Hallenturnier E-Jugend Kuchenverkauf", "sale")]
    for d, amt, text, kind in rows:
        money("CASH", d, amt, vwz=text, kind={"deposit": "internal", "sale": "sale", "out": "cost"}[kind])
        if kind == "deposit":
            money("HK", d, -amt, name="", vwz=f"Bareinzahlung Geschaeftsstelle {text.split()[-1]}", btext="Bareinzahlung",
                  kind="internal", gvc="082")
    for d, amt in ((D("2026-07-06"), 14000), (D("2026-09-07"), 9000)):
        money("TK", d, amt, name="", vwz="Einzahlung Gastspielgebuehren Tennis", btext="BARGELDEINZAHLUNG", kind="internal", gvc="082")


def build_all():
    build_special()
    build_generic()
    build_guests()
    build_courses()
    build_camp()
    build_fee_claims()
    build_other_claims()
    build_work_hours()
    build_invoices()
    build_runs()
    build_transfers()
    build_course_money()
    build_camp_money()
    build_work_money()
    build_rest()


# ------------------------------------------------------------------ the truth on each delivery day
DELIV = [dict(folder="lieferung1", cut=L1_CUT, today=L1_DAY), dict(folder="lieferung2", cut=L2_CUT, today=L2_DAY)]
RECEIVABLE = ("fee", "kurs", "camp", "arbeit", "pacht", "invoice", "unknown")


def receipts_at(cut: date) -> list[dict]:
    out = []
    for m in MONEY:
        if m["date"] > cut or m["amount"] <= 0 or m["kind"] not in RECEIVABLE or m["acct"] == "CASH":
            continue
        used = sum(x for c, x, eff in m["alloc"] if eff <= cut)
        back = sum(a for d, a in m["refunds"] if d <= cut)
        rest = m["amount"] - used - back
        if rest > 0:
            out.append(dict(amount=rest, date=m["date"], payer=m["name"], vwz=m["vwz"], acct=m["acct"], note=m["note"]))
    return out


def lump_rest(cut: date) -> list[tuple]:
    out = []
    for r in RUNS:
        m = r["money"]
        if m["date"] > cut:
            continue
        rest = m["amount"] - sum(x for c, x, eff in m["alloc"]) - sum(a for d, a in m["refunds"] if d <= cut)
        if rest:
            out.append((r["file"], rest))
    return out


def unbilled_at(cut: date) -> list[dict]:
    out = []
    for s in SPONSORING:
        if s["net"] and s["start"] <= cut and not s["inv"]:
            out.append(dict(id=s["no"], what=f"{s['what']} ({GUESTS[s['who']]['name']}), läuft seit {dde(s['start'])}, "
                                             f"{de(s['net'])} netto – keine Rechnung", net=eur(s["net"])))
    for h in HALL:
        if h["date"] <= cut and not h["free"] and h["net"] and (not h["inv"] or h["invoiced"] > cut) and h.get("q") != "future":
            out.append(dict(id=h["no"], what=f"{h['what']} am {dde(h['date'])} für {GUESTS[h['who']]['name']}: "
                                             f"{h['hours']} Std. × {de(h['rate'])} – keine Rechnung", net=eur(h["net"])))
    return out


def truth_for(dv: dict) -> dict:
    cut, today = dv["cut"], dv["today"]
    op = {k: c for k, c in CLAIMS.items() if c["issued"] <= cut and c["amount"] > 0 and open_of(c, cut) > 0}
    for k, c in CLAIMS.items():
        assert open_of(c, cut) >= 0 or c["issued"] > cut, (k, open_of(c, cut))
    rec = receipts_at(cut)
    assert not lump_rest(cut), lump_rest(cut)
    unb = unbilled_at(cut)
    by_kind, by_konto = {}, {}
    for k, c in op.items():
        by_kind[c["art"]] = round(by_kind.get(c["art"], 0) + eur(open_of(c, cut)), 2)
        by_konto[str(c["konto"])] = round(by_konto.get(str(c["konto"]), 0) + eur(open_of(c, cut)), 2)
    return dict(folder=dv["folder"], today=today.isoformat(), cut=cut.isoformat(),
                open={k: eur(open_of(c, cut)) for k, c in sorted(op.items())},
                open_total=eur(sum(open_of(c, cut) for c in op.values())),
                overdue=sorted(k for k, c in op.items() if c["due"] < today),
                unbilled=[u["id"] for u in unb], over_budget=[],
                receipts=sorted(eur(x["amount"]) for x in rec),
                open_detail={k: dict(art=c["art"], konto=c["konto"], zeitraum=c["period"], soll=eur(c["amount"]),
                                     bezahlt=eur(paid_by(c, cut)), offen=eur(open_of(c, cut)), faellig=c["due"].isoformat(),
                                     text=c["label"], note=c["note"]) for k, c in sorted(op.items())},
                open_by_kind=by_kind, open_by_account=dict(sorted(by_konto.items())),
                unbilled_detail=unb,
                receipts_detail=[dict(amount=eur(x["amount"]), date=x["date"].isoformat(), payer=x["payer"], vwz=x["vwz"],
                                      konto=ACCTS[x["acct"]]["what"], note=x["note"]) for x in rec])


# ------------------------------------------------------------------ writers: helpers
def csv_line(vals, sep=";", quote=True) -> str:
    out = []
    for v in vals:
        s = "" if v is None else str(v)
        out.append('"' + s.replace('"', '""') + '"' if quote else s)
    return sep.join(out)


def _fix_zip(data: bytes) -> bytes:
    """Same bytes for the same content: openpyxl stamps the time of saving into the archive and into core.xml."""
    src = zipfile.ZipFile(io.BytesIO(data))
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        for info in sorted(src.infolist(), key=lambda i: i.filename):
            zi = zipfile.ZipInfo(info.filename, date_time=(2026, 1, 5, 9, 0, 0))
            zi.compress_type = zipfile.ZIP_DEFLATED
            body = src.read(info.filename)
            if info.filename == "docProps/core.xml":
                body = re.sub(rb"(<dcterms:(?:created|modified)[^>]*>)[^<]*(</dcterms:(?:created|modified)>)",
                              rb"\g<1>2026-01-05T09:00:00Z\g<2>", body)
            z.writestr(zi, body)
    return out.getvalue()


def save_wb(wb, path: Path, who="Jens Albers"):
    wb.properties.creator = who
    wb.properties.lastModifiedBy = who
    wb.properties.created = datetime(2026, 1, 5, 9, 0)
    wb.properties.modified = datetime(2026, 1, 5, 9, 0)
    buf = io.BytesIO()
    wb.save(buf)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(_fix_zip(buf.getvalue()))


def bold_row(ws, row: int, n: int):
    for j in range(1, n + 1):
        ws.cell(row=row, column=j).font = Font(bold=True)


def known_left(p: dict, on: date) -> date | None:
    """The leaving date the club program shows on that day."""
    if not p["left"]:
        return None
    a = ACCOUNTS[p["acct"]]
    seen = p.get("sw_left_known") or a.get("cancel_received") or {
        1094: D("2026-05-18"), 1530: D("2026-05-20"), 1356: D("2026-06-26"), 1467: D("2026-08-25"),
        1007: D("2026-08-12")}.get(p["nr"]) or p["left"]
    return p["left"] if seen <= on else None


def period_amount(a: dict, on: date) -> int:
    """'Beitrag je Fälligkeit' as the program shows it: a full period at the fees it knows on that day."""
    n = RHYTHM_MONTHS[a["rhythm"]]
    m0 = on.month
    months = [((m0 - 1 + k) % 12) + 1 for k in range(n)]
    total = 0
    for m in months:
        head = PERSONS[a["nr"]]
        g = group_at(head, on, sw=True)
        total += at(GRUND[g], D("2026-07-01"))
        for nr in a["members"]:
            p = PERSONS[nr]
            if p["left"] and known_left(p, on) and p["left"] < on:
                continue
            gp = group_at(p, on, sw=True)
            if gp in ("Passiv", "Ehrenmitglied"):
                continue
            k = klasse(gp) if gp != "Familie" else ("J" if age_at(p, on) < 18 else "E")
            total += sum(at(ZUSCHLAG[dep][k], D("2026-07-01")) for dep in p["depts"])
    return total


# ------------------------------------------------------------------ writers: the club program's member export
EXPORT_HEAD = ["Mitgliedsnr.", "Anrede", "Titel", "Vorname", "Nachname", "Straße", "PLZ", "Ort", "Geburtsdatum", "Eintritt",
               "Austritt", "Status", "Beitragsgruppe", "Abteilungen", "Zahlungsweise", "Zahlungsrhythmus",
               "Beitrag je Fälligkeit", "Beitragszahler", "Kontoinhaber", "IBAN", "BIC", "Mandatsreferenz", "Mandat vom",
               "E-Mail", "Telefon", "Bemerkung"]


def write_export(path: Path, on: date, only_active: bool):
    lines = [csv_line(EXPORT_HEAD)]
    for nr, p in sorted(PERSONS.items()):
        left = known_left(p, on)
        if only_active and p["left"] and p["left"] <= on:
            continue
        if p["joined"] > on + timedelta(days=40):
            continue
        a = ACCOUNTS[p["acct"]]
        payer = a["nr"] == nr
        grp = group_at(p, on, sw=True)
        status = "verstorben" if p["why_left"] == "verstorben" and left else "ausgetreten" if left and left <= on else \
            "Ehrenmitglied" if grp == "Ehrenmitglied" else "passiv" if grp == "Passiv" else "aktiv"
        iban, bic = iban_on(a, on) if a["how"] == "Lastschrift" else (None, None)
        note = p["note"]
        if left and left > on:
            note = (note + "; " if note else "") + f"Kündigung zum {dde(left)}"
        if nr == 1514 and on >= D("2026-10-01"):
            note = "Ermäßigung lt. Studienbescheinigung ab 01.10.2026"
        if nr == 1207 and on >= D("2026-09-10"):
            note = "Bankverbindung geändert am 10.09.2026 (Mail vom 09.09.)"
        holder = a["holder"] if (a["how"] == "Lastschrift" or a["holder"] != f"{PERSONS[a['nr']]['first']} {PERSONS[a['nr']]['last']}") \
            and payer else ""
        lines.append(csv_line([
            nr, ("Herr" if p["sex"] == "m" else "Frau") if age_at(p, on) >= 18 else "", p["title"], p["first"], p["last"],
            p["street"], p["plz"], p["town"], dde(p["born"]), dde(p["joined"]), dde(left) if left else "", status, grp,
            ", ".join(DEPTS[d] for d in p["depts"]), a["how"] if payer else "über Beitragszahler",
            a["rhythm"] if payer else "", de(period_amount(a, on)) if payer and a["how"] else "0,00",
            "" if payer else a["nr"], holder, iban or "", bic or "", a["mref"] if payer and a["how"] == "Lastschrift" else "",
            dde(a["mdate"]) if payer and a["mdate"] and a["how"] == "Lastschrift" else "", p["mail"], p["phone"], note]))
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(("\r\n".join(lines) + "\r\n").encode("cp1252", errors="replace"))


# ------------------------------------------------------------------ writers: SEPA files
def write_pain008(path: Path, run: dict):
    R = run["date"]
    created = datetime.combine(R - timedelta(days=3 if R.weekday() > 1 else 5), datetime.min.time()).replace(hour=19, minute=42)
    a = ACCTS["HK"]
    blocks = {"FRST": [], "RCUR": []}
    for x in run["items"]:
        acc = x["a"]
        first = acc["mdate"] and acc["mdate"] >= D("2026-01-01") and not any(
            y["a"] is acc for r in RUNS if r["date"] < R for y in r["items"])
        blocks["FRST" if first else "RCUR"].append(x)
    pmt = []
    for seq, items in blocks.items():
        if not items:
            continue
        tx = []
        for x in items:
            acc = x["a"]
            tx.append(f"""      <DrctDbtTxInf>
        <PmtId><EndToEndId>{x['e2e']}</EndToEndId></PmtId>
        <InstdAmt Ccy="EUR">{xamt(x['amount'])}</InstdAmt>
        <DrctDbtTx><MndtRltdInf><MndtId>{acc['mref']}</MndtId><DtOfSgntr>{acc['mdate'].isoformat()}</DtOfSgntr></MndtRltdInf></DrctDbtTx>
        <DbtrAgt><FinInstnId><BICFI>{x['bic']}</BICFI></FinInstnId></DbtrAgt>
        <Dbtr><Nm>{xesc(sepa(acc['holder']))}</Nm></Dbtr>
        <DbtrAcct><Id><IBAN>{x['iban']}</IBAN></Id></DbtrAcct>
        <RmtInf><Ustrd>{xesc(x['vwz'][:140])}</Ustrd></RmtInf>
      </DrctDbtTxInf>""")
        total = sum(x["amount"] for x in items)
        pmt.append(f"""    <PmtInf>
      <PmtInfId>{run['msg']}-{seq}</PmtInfId><PmtMtd>DD</PmtMtd><BtchBookg>true</BtchBookg>
      <NbOfTxs>{len(items)}</NbOfTxs><CtrlSum>{xamt(total)}</CtrlSum>
      <PmtTpInf><SvcLvl><Cd>SEPA</Cd></SvcLvl><LclInstrm><Cd>CORE</Cd></LclInstrm><SeqTp>{seq}</SeqTp></PmtTpInf>
      <ReqdColltnDt>{R.isoformat()}</ReqdColltnDt>
      <Cdtr><Nm>{xesc(sepa(CLUB['name']))}</Nm></Cdtr>
      <CdtrAcct><Id><IBAN>{a['iban']}</IBAN></Id></CdtrAcct>
      <CdtrAgt><FinInstnId><BICFI>{a['bic']}</BICFI></FinInstnId></CdtrAgt>
      <ChrgBr>SLEV</ChrgBr>
      <CdtrSchmeId><Id><PrvtId><Othr><Id>{CI}</Id><SchmeNm><Prtry>SEPA</Prtry></SchmeNm></Othr></PrvtId></Id></CdtrSchmeId>
{chr(10).join(tx)}
    </PmtInf>""")
    total = sum(x["amount"] for x in run["items"])
    xml = f"""<?xml version="1.0" encoding="UTF-8"?>
<Document xmlns="urn:iso:std:iso:20022:tech:xsd:pain.008.001.08" xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">
  <CstmrDrctDbtInitn>
    <GrpHdr><MsgId>{run['msg']}</MsgId><CreDtTm>{created.isoformat()}</CreDtTm><NbOfTxs>{len(run['items'])}</NbOfTxs>
      <CtrlSum>{xamt(total)}</CtrlSum><InitgPty><Nm>{xesc(sepa(CLUB['name']))}</Nm></InitgPty></GrpHdr>
{chr(10).join(pmt)}
  </CstmrDrctDbtInitn>
</Document>
"""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(xml.encode("utf-8"))


# ------------------------------------------------------------------ writers: bank statements in three formats
OPENING = {"HK": 2341877, "TK": 421240}


def lines_of(acct_: str, frm: date, to: date) -> list[dict]:
    return sorted((m for m in MONEY if m["acct"] == acct_ and frm <= m["date"] <= to), key=lambda m: (m["date"], m["id"]))


def balance_before(acct_: str, d: date) -> int:
    return OPENING[acct_] + sum(m["amount"] for m in MONEY if m["acct"] == acct_ and m["date"] < d)


def _mt_lines(tag: str, text: str) -> list[str]:
    out, first = [], f":{tag}:"
    s = first + text
    while s:
        out.append(s[:65])
        s = s[65:]
    return out


def _mt86(m: dict) -> str:
    """The :86: field of a German MT940: GVC, ?00 booking text, ?20 … purpose in pieces of 27, ?30/?31 bank and
    account of the other side, ?32/?33 its name."""
    gvc = m["gvc"] or ("166" if m["amount"] > 0 else "116")
    parts = [f"?00{sepa(m['btext']).upper()[:27]}", "?10931"]
    purpose = ""
    if m["e2e"]:
        purpose += f"EREF+{m['e2e']} "
    if m["mref"]:
        purpose += f"MREF+{m['mref']} "
    if m["ci"]:
        purpose += f"CRED+{m['ci']} "
    purpose += "SVWZ+" + sepa(m["vwz"])
    chunks = [purpose[k:k + 27] for k in range(0, len(purpose), 27)][:14]
    for k, ch in enumerate(chunks[:10]):
        parts.append(f"?2{k}{ch}")
    if m["bic"]:
        parts.append(f"?30{m['bic']}")
    if m["iban"]:
        parts.append(f"?31{m['iban']}")
    name = sepa(m["name"])
    if name:
        parts.append(f"?32{name[:27]}")
        if len(name) > 27:
            parts.append(f"?33{name[27:54]}")
    parts.append("?34" + ("992" if m["kind"] == "return" else "000"))
    for k, ch in enumerate(chunks[10:14]):
        parts.append(f"?6{k}{ch}")
    return gvc + "".join(parts)


def write_mt940(path: Path, acct_: str, frm: date, to: date):
    a = ACCTS[acct_]
    out = []
    seq = 0
    m0 = frm
    while m0 <= to:
        seq += 1
        last = min(month_end(m0.year, m0.month), to)
        ms = lines_of(acct_, m0, last)
        bal = balance_before(acct_, m0)
        out += [":20:STARMONEY", f":25:{a['blz']}/{a['kto'].zfill(10)}", f":28C:{seq:05d}/001",
                f":60F:{'C' if bal >= 0 else 'D'}{(m0 - timedelta(days=1)):%y%m%d}EUR{de_plain(abs(bal))}"]
        for m in ms:
            code = {"sepa_lump": "NDDT", "return": "NRTI", "cost": "NTRF", "refund": "NTRF", "internal": "NTRF"}.get(m["kind"], "NTRF")
            if m["btext"] == "Abschluss":
                code = "NCHG"
            ref = m["e2e"] or "NONREF"
            out.append(f":61:{m['date']:%y%m%d}{m['date']:%m%d}{'C' if m['amount'] > 0 else 'D'}{de_plain(abs(m['amount']))}"
                       f"{code}{ref[:16]}")
            out += _mt_lines("86", _mt86(m))
            bal += m["amount"]
        out += [f":62F:{'C' if bal >= 0 else 'D'}{last:%y%m%d}EUR{de_plain(abs(bal))}", "-"]
        m0 = last + timedelta(days=1)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(("\r\n".join(out) + "\r\n").encode("latin-1", errors="replace"))


VR_HEAD = ["Bezeichnung Auftragskonto", "IBAN Auftragskonto", "BIC Auftragskonto", "Bankname Auftragskonto", "Buchungstag",
           "Valutadatum", "Name Zahlungsbeteiligter", "IBAN Zahlungsbeteiligter", "BIC (SWIFT-Code) Zahlungsbeteiligter",
           "Buchungstext", "Verwendungszweck", "Betrag", "Waehrung", "Saldo nach Buchung", "Bemerkung", "Kategorie",
           "Steuerrelevant", "Glaeubiger ID", "Mandatsreferenz"]


def write_vr(path: Path, acct_: str, frm: date, to: date):
    a = ACCTS[acct_]
    ms = lines_of(acct_, frm, to)
    bal = balance_before(acct_, frm)
    rows = []
    for m in ms:
        bal += m["amount"]
        rows.append(csv_line(["Hauptkonto TuS", a["iban"], a["bic"], a["bank"], dde(m["date"]), dde(m["date"]), m["name"],
                              m["iban"], m["bic"], m["btext"], m["vwz"], de(m["amount"]), "EUR", de(bal), "", "", "",
                              m["ci"], m["mref"]]))
    out = [csv_line(VR_HEAD)] + list(reversed(rows))
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(("﻿" + "\r\n".join(out) + "\r\n").encode("utf-8"))


SPK_MT_HEAD = ["Auftragskonto", "Buchungstag", "Valutadatum", "Buchungstext", "Verwendungszweck",
               "Beguenstigter/Zahlungspflichtiger", "Kontonummer", "BLZ", "Betrag", "Waehrung", "Info"]
SPK_TEXT = {"Gutschrift Überweisung": "GUTSCHR. UEBERWEISUNG", "Überweisung": "ONLINE-UEBERWEISUNG", "Umbuchung": "UMBUCHUNG",
            "Lastschrift": "FOLGELASTSCHRIFT", "ENTGELTABSCHLUSS": "ENTGELTABSCHLUSS", "BARGELDEINZAHLUNG": "BARGELDEINZAHLUNG"}


def write_spk_mt940csv(path: Path, acct_: str, frm: date, to: date):
    """Sparkasse online banking, export 'CSV-MT940': IBAN and BIC stand in columns still called Kontonummer and BLZ."""
    a = ACCTS[acct_]
    rows = []
    for m in lines_of(acct_, frm, to):
        vwz = sepa(m["vwz"])
        if m["ci"]:
            vwz = f"EREF+{m['e2e'] or 'NOTPROVIDED'} MREF+{m['mref']} CRED+{m['ci']} SVWZ+{vwz}"
        rows.append(csv_line([a["kto"], dshort(m["date"]), dshort(m["date"]), SPK_TEXT.get(m["btext"], m["btext"].upper()), vwz,
                              m["name"], m["iban"], m["bic"], de_plain(m["amount"]), "EUR", "Umsatz gebucht"]))
    out = [csv_line(SPK_MT_HEAD)] + list(reversed(rows))
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(("\r\n".join(out) + "\r\n").encode("cp1252", errors="replace"))


# ------------------------------------------------------------------ writers: the treasurer's and the departments' lists
def write_cashbook(path: Path, cut: date):
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Kasse 2026"
    ws.append([f"Kassenbuch {CLUB['name']} – Geschäftsstelle"])
    ws.append([f"Stand: {dde(cut)}"])
    ws.append([])
    ws.append(["Datum", "Beleg-Nr.", "Buchungstext", "Einnahme", "Ausgabe", "Bestand"])
    bold_row(ws, 4, 6)
    bal = 41230
    ws.append([D("2026-01-01"), "", "Anfangsbestand (Übernahme Kasse H. Brettschneider)", None, None, eur(bal)])
    k = 0
    for m in sorted((m for m in MONEY if m["acct"] == "CASH" and m["date"] <= cut), key=lambda m: (m["date"], m["id"])):
        k += 1
        bal += m["amount"]
        ws.append([m["date"], f"K-26-{k:03d}", m["vwz"], eur(m["amount"]) if m["amount"] > 0 else None,
                   eur(-m["amount"]) if m["amount"] < 0 else None, eur(bal)])
    for row in ws.iter_rows(min_row=5, max_col=1):
        for c in row:
            c.number_format = "DD.MM.YYYY"
    save_wb(wb, path, who="Petra Kunze")


def _course_sheet_rows(c: dict, term: str, cut: date) -> list[list]:
    rows = []
    for reg in sorted((x for x in REGS if x["term"] == term and x["course"] == c["code"]), key=lambda x: x["n"]):
        if reg.get("listed_from") and reg["listed_from"] > cut:
            continue
        cl = CLAIMS.get(f"{reg['konto']} Kursgebühr {term}")
        paid = None
        how = "Lastschrift (mit Beitragseinzug 15.10.)" if reg.get("sepa") else "Überweisung"
        note = ""
        if cl:
            ms = [m for m in MONEY if any(cc is cl for cc, x, eff in m["alloc"]) and m["date"] <= cut]
            if ms:
                m = ms[0]
                if m["acct"] == "CASH":
                    how = "bar"
                # the head of department notes payments when she sees them – not always
                if not (m["kind"] == "sepa_lump") and rr("noted", reg["konto"], term).random() < 0.8:
                    paid = m["date"]
                elif m["kind"] == "sepa_lump":
                    paid = "LS 15.10."
            if reg["konto"] == 1419 and cut >= D("2026-10-21"):
                paid, note = None, "Lastschrift zurück (21.10.)"
            if reg["konto"] == COURSE_UNPAID.get("spring_never"):
                note = "offen – 2x erinnert"
            if reg["konto"] == 9029:
                note = "telefonisch angemeldet 10.09., nachgetragen 25.09."
        else:
            note = "Kurs entfällt – Gebühr erstattet" if c.get("cancelled") else ""
        if reg["konto"] < 9000:
            p = PERSONS[reg["konto"]]
            tel, mail, nr = p["phone"], p["mail"] or "", reg["konto"]
        else:
            g = GUESTS[reg["konto"]]
            tel, mail, nr = f"0{5723 + reg['konto'] % 3} {100000 + reg['konto'] * 7 % 900000}", g["mail"], reg["konto"]
        last, first = reg["name"].split(", ")
        rows.append([reg["n"], last, first, "ja" if reg["member"] else "nein", nr, tel, mail, eur(reg["fee"]), how, paid, note])
    return rows


def write_courses(path: Path, term: str, cut: date):
    wb = openpyxl.Workbook()
    wb.remove(wb.active)
    for c in COURSES:
        start = c["start"] if term == "Herbst 2026" else c.get("spring")
        if not start:
            continue
        title = f"{c['name']} {c['slot'].split(',')[0].split()[0]}" + (" (entfällt)" if c.get("cancelled") and term == "Herbst 2026" else "")
        ws = wb.create_sheet(title[:31])
        ws.append([f"{c['name']} – {c['slot']} – {c['n']} Termine ab {dde(start)} – Leitung: {c['lead']}"
                   + ("  ***ENTFÄLLT (zu wenig Anmeldungen)***" if c.get("cancelled") and term == "Herbst 2026" else "")])
        ws.append([f"Kursgebühr Mitglieder {de(c['fee'][0])} €, Nichtmitglieder {de(c['fee'][1])} € – Stand {dde(cut)}"])
        ws.append([])
        ws.append(["Nr.", "Name", "Vorname", "Mitglied", "Mitgl.-/Gast-Nr.", "Telefon", "E-Mail", "Gebühr", "Zahlweise",
                   "bezahlt am", "Bemerkung"])
        bold_row(ws, 4, 11)
        for r in _course_sheet_rows(c, term, cut):
            ws.append(r)
    save_wb(wb, path, who="Birgit Lanz")


def write_camp_form(path: Path):
    """The online registration form's export (UTF-8 with BOM, commas) – as the parents typed it."""
    head = ["Eingang", "Anmelde-ID", "Vorname Kind", "Nachname Kind", "Geburtsdatum", "Mitglied im TuS?", "Mitgliedsnummer",
            "Name Erziehungsberechtigte/r", "E-Mail", "Telefon", "T-Shirt-Größe", "Allergien/Unverträglichkeiten",
            "Fotoerlaubnis", "Geschwisterkind angemeldet?"]
    lines = [csv_line(head, sep=",")]
    for x in sorted(CAMP, key=lambda x: (x["registered"], x["n"])):
        u = rr("form", x["konto"])
        first, last = x["child"].split(" ", 1)
        nr = ""
        if x["member"]:
            acc = PERSONS[x["konto"]]["acct"]
            nr = str(x["konto"]) if u.random() < 0.75 else (str(acc) if acc != x["konto"] else "") if u.random() < 0.6 else ""
        mail = (PERSONS[ACCOUNTS[PERSONS[x["konto"]]["acct"]]["nr"]]["mail"] if x["member"] else GUESTS[x["konto"]]["mail"]) \
            or mail_of(x["parent"].split()[0], last, x["konto"])
        lines.append(csv_line([f"{dde(x['registered'])} {u.randint(7, 22):02d}:{u.randint(0, 59):02d}", f"#{1040 + x['n']}",
                               first, last, dde(x["born"]), "ja" if x["member"] else "nein", nr, x["parent"], mail,
                               f"01{u.choice(['51', '60', '76'])} {u.randint(1000000, 9999999)}",
                               u.choice(["116", "128", "140", "152", "S"]), u.choice(["", "", "", "Nüsse", "Laktose", "keine"]),
                               u.choice(["ja", "ja", "nein"]), "ja" if x["sibling_of"] or any(y["sibling_of"] == x["konto"] for y in CAMP)
                               else "nein"], sep=","))
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(("﻿" + "\r\n".join(lines) + "\r\n").encode("utf-8"))


def write_camp_list(path: Path, cut: date):
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Teilnehmer"
    ws.append(["Feriencamp 03.–07.08.2026 – Teilnehmer und Zahlungen"])
    ws.append([f"Mitglieder 139,00 €, Geschwister 119,00 €, Nichtmitglieder 169,00 € – Stand {dde(cut)}"])
    ws.append([])
    ws.append(["Nr.", "Kind", "geb.", "Mitgl.-/Gast-Nr.", "Erziehungsberechtigte/r", "Betrag", "bezahlt am", "Bemerkung"])
    bold_row(ws, 4, 8)
    for x in sorted(CAMP, key=lambda x: x["n"]):
        c = CLAIMS[f"{x['konto']} Feriencamp 2026"]
        ms = [m for m in MONEY if any(cc is c for cc, _, _ in m["alloc"]) and m["date"] <= cut]
        note = ""
        if x["konto"] == CAMP_PLANT["cancel"]:
            note = "abgesagt 25.07. (krank) – 119,00 erstattet am 10.08., 20,00 einbehalten"
        if x["konto"] == CAMP_PLANT["twice"]:
            note = "doppelt überwiesen (27.07.) – erstatten" if cut < D("2026-10-02") else "doppelt überwiesen, 169,00 erstattet 02.10."
        if x["konto"] == CAMP_PLANT["never"]:
            note = "noch nicht bezahlt – Kind war da"
        ws.append([x["n"], x["child"], x["born"], x["konto"], x["parent"], eur(13900 if x["konto"] == CAMP_PLANT["cancel"] else x["fee"]),
                   ms[0]["date"] if ms else None, note])
    save_wb(wb, path)


def write_invoice_book(path: Path, cut: date, noted_until: date):
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Ausgangsrechnungen 2026"
    ws.append(["Rechnungsausgangsbuch 2026 (Werbung, Sponsoring, Hallennutzung) – wirtschaftlicher Geschäftsbetrieb / Vermögensverwaltung"])
    ws.append([])
    ws.append(["Rechnungs-Nr.", "Datum", "Kunde", "Leistung", "Netto", "USt 19 %", "Brutto", "fällig am", "bezahlt am", "Bemerkung"])
    bold_row(ws, 3, 10)
    for i in sorted(INVOICES, key=lambda i: i["no"]):
        if i["date"] > cut:
            continue
        c = CLAIMS[i["no"]]
        ms = [m for m in MONEY if any(cc is c for cc, _, _ in m["alloc"]) and m["date"] <= noted_until]
        note = "Kunde hat netto gezahlt – USt fehlt" if i["no"] == "2026-003" and cut >= D("2026-10-01") else ""
        if i["no"] == "2026-027" and cut >= D("2026-10-05"):
            note = "reklamiert 05.10. (Stunden)"
        ws.append([i["no"], i["date"], GUESTS[i["to"]]["name"], i["subject"], eur(i["net"]), eur(i["vat"]), eur(i["gross"]),
                   i["due"], ms[0]["date"] if ms else None, note])
    save_wb(wb, path)


def write_sponsoring(path: Path, cut: date):
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Verträge"
    ws.append(["Sponsoring- und Werbeverträge"])
    ws.append([])
    ws.append(["Vertrag", "Sponsor", "Leistung", "Laufzeit von", "bis", "Betrag netto", "Rechnung", "Bemerkung"])
    bold_row(ws, 3, 8)
    for s in SPONSORING:
        if s["start"] > cut + timedelta(days=60):
            continue
        note = "Sachleistung, keine Rechnung" if not s["net"] else ""
        if s["no"] == "SV-2026-07":
            note = "unterschrieben 28.07.2026, Banden hängen seit 01.08."
        ws.append([s["no"], GUESTS[s["who"]]["name"], s["what"], s["start"], s["end"], eur(s["net"]) if s["net"] else None,
                   s["inv"], note])
    save_wb(wb, path)


def write_hall(path: Path, cut: date):
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Fremdnutzung 2026"
    ws.append(["Hallenbelegung durch Fremdnutzer 2026 (Halle 1 und 2, Sportpark)"])
    ws.append(["Satz Einzelveranstaltung 40,00 €/Std., Dauernutzung Mittwochsgruppe 25,00 €/Std., jeweils zzgl. 19 % USt"])
    ws.append([])
    ws.append(["Nr.", "Datum", "Nutzer", "Halle / Zeit", "Stunden", "Satz", "Betrag netto", "Rechnung", "Bemerkung"])
    bold_row(ws, 4, 9)
    for h in HALL:
        inv_ = h["inv"] if h["inv"] and h["invoiced"] <= cut and h["listed_invoice"] else None
        note = "kostenlos (Kooperation)" if h["free"] else ("Dauernutzung, Abrechnung quartalsweise" if h["who"] == 9022 else "")
        ws.append([h["no"], h["date"], GUESTS[h["who"]]["name"], h["what"], h["hours"], eur(h["rate"]),
                   eur(h["net"]) if not h["free"] else 0, inv_, note])
    save_wb(wb, path, who="Tim Okonkwo")


def write_uel(path: Path, quarters: list[int]):
    wb = openpyxl.Workbook()
    wb.remove(wb.active)
    for q in quarters:
        ws = wb.create_sheet(f"Q{q} 2026")
        ws.append([f"Übungsleiterabrechnung {q}. Quartal 2026 – Übungsleiterpauschale § 3 Nr. 26 EStG"])
        ws.append([])
        ws.append(["ÜL-Nr.", "Name", "Abteilung", "Gruppe", "Stunden", "Satz €/Std.", "Betrag", "ausgezahlt am"])
        bold_row(ws, 3, 8)
        total = 0
        for x in (x for x in UEL if x["q"] == q and x["year"] == 2026):
            ws.append([x["code"], x["name"], DEPTS[x["dep"]], x["group"], x["hours"], eur(x["rate"]), eur(x["amount"]), x["paid"]])
            total += x["amount"]
        ws.append(["Summe", None, None, None, None, None, eur(total), None])
    save_wb(wb, path)


def write_dunning(path: Path, day: date):
    """The treasurer's own dunning list – kept by hand, a little behind the bank."""
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Mahnliste"
    ws.append([f"Mahnliste Beiträge und sonstige Forderungen – Stand {dde(day)} (J. Albers)"])
    ws.append([])
    ws.append(["Mitgl.-Nr.", "Name", "Forderung", "Betrag", "fällig seit", "1. Mahnung", "2. Mahnung", "Bemerkung"])
    bold_row(ws, 3, 8)
    rows = [(1266, "Rohlfing, Dennis", "Beitrag Q4/2025", 4200, D("2025-10-15"), D("2025-11-20"), D("2026-01-15"), ""),
            (1266, "Rohlfing, Dennis", "Beitrag Q2/2026", 4200, D("2026-04-15"), D("2026-06-15"), D("2026-08-31"), ""),
            (1266, "Rohlfing, Dennis", "Beitrag Q3/2026", 5100, D("2026-07-15"), D("2026-08-31"), None,
             "Ausschluss im Vorstand ansprechen" if day < D("2026-10-05") else "gestrichen zum 30.09. (Vorstand 05.10.), Forderung bleibt"),
            (1061, "Meyer, Walter", "Beitrag 2026 (bar)", 14400, D("2026-01-15"), None, None, "war nicht zur JHV – anrufen"),
            (1207, "Wiegand, Carsten", "Rücklastschrift Q3/2026 + Gebühr", 11700, D("2026-07-20"), D("2026-08-10"), None,
             "Konto erloschen – neue IBAN angefordert"),
            (1123, "Böttcher, Frank", "Rücklastschrift Q3/2026 + Gebühr", 7500, D("2026-07-21"), D("2026-08-10"), None,
             "will überweisen"),
            (1240, "Strate, Yvonne", "Beitrag Q3/2026", 4200, D("2026-07-15"), D("2026-08-31"), None, ""),
            (1150, "Rahe, Monika", "Beitrag Q3/2026 Rest", 600, D("2026-07-15"), None, None, "Dauerauftrag noch alter Betrag"),
            (1333, "Fasold, Ingrid", "Beitrag Q3/2026 Rest", 1200, D("2026-07-15"), None, None, "hat Rest angekündigt"),
            (COURSE_UNPAID["spring_never"], GUESTS[COURSE_UNPAID["spring_never"]]["name"], "Kursgebühr Zumba Frühjahr 2026", 6000,
             D("2026-03-04"), D("2026-04-15"), D("2026-06-01"), "Nichtmitglied"),
            (CAMP_PLANT["never"], GUESTS[CAMP_PLANT["never"]]["name"], "Feriencamp 2026", 16900, D("2026-07-15"), D("2026-08-17"),
             None, "Kind hat teilgenommen"),
            ("", "Elektro Hesse GmbH & Co. KG", "Rg. 2026-003 USt-Anteil", 22800, D("2026-02-09"), D("2026-05-04"), None,
             "Hr. Hesse: 'zahlen wir mit der Spende' – klären")]
    # someone who paid since, still on the list
    stale = next(n for n, a in sorted(ACCOUNTS.items()) if a["how"] == "Überweisung" and a["rhythm"] == "vierteljährlich"
                 and n not in SPECIAL_NRS and not PERSONS[n]["left"])
    rows.append((stale, f"{PERSONS[stale]['last']}, {PERSONS[stale]['first']}", "Beitrag Q2/2026",
                 CLAIMS[f"{stale} Beitrag Q2/2026"]["amount"], D("2026-04-15"), D("2026-06-15"), None, "angeblich überwiesen?"))
    if day >= D("2026-10-01"):
        rows = [r for r in rows if r[0] not in (1207, 1123)] + [
            (1123, "Böttcher, Frank", "Rücklastschriftgebühr Q3/2026", 300, D("2026-08-04"), None, None, "Beitrag überwiesen 03.08., Gebühr fehlt"),
            (1356, "Gieseking, Marc", "Beitrag Q3/2026 (Widerspruch Lastschrift)", 5100, D("2026-07-15"), D("2026-10-05"), None,
             "meint ausgetreten zum 30.06. – Kündigung kam zu spät, wirksam 30.09."),
            (1648, "Sieker, Marlene", "Aufnahmegebühr", 3000, D("2026-08-15"), D("2026-10-05"), None, ""),
            ("", "TV Ostheide 1912 e.V.", "Rg. 2026-027 Hallennutzung 22.08.", 28560, D("2026-09-14"), D("2026-10-01"), None,
             "reklamiert Stunden (Mail 05.10.)")]
        rows = [r for r in rows if not (r[0] == 1333)]
        rows += [(c["konto"], f"{PERSONS[c['konto']]['last']}, {PERSONS[c['konto']]['first']}", "Beitragsdifferenz 2. Hj. 2026",
                  c["amount"], c["due"], None, None, "Jahreszahler, Differenz nach Beitragserhöhung")
                 for c in sorted(CLAIMS.values(), key=lambda c: c["konto"]) if c["art"] == "Beitragsdifferenz"
                 and open_of(c, D("2026-10-14")) > 0 and c["konto"] != 1061][:9]
    for r in rows:
        ws.append([r[0], r[1], r[2], eur(r[3]), r[4], r[5], r[6], r[7]])
    save_wb(wb, path)


def write_work_hours(path: Path, day: date):
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Arbeitsstunden"
    ws.append([f"Tennis – Arbeitsstunden Saison 2026 (Soll 5 Std., Ersatz 15,00 € je fehlende Stunde) – Stand {dde(day)}"])
    ws.append([])
    ws.append(["Mitgl.-Nr.", "Name", "Soll", "geleistet", "fehlend", "Ersatzbetrag", "Bemerkung"])
    bold_row(ws, 3, 7)
    for w in WORK_HOURS:
        done = w["done"]
        if day < D("2026-09-26") and done == 5 and rr("putz", w["nr"]).random() < 0.25:
            done = 3  # two hours come with the autumn clean-up on 26.09.
        miss = 5 - done
        ws.append([w["nr"], w["name"], 5, done, miss, eur(miss * 1500) if day >= D("2026-09-30") and miss else None,
                   "Herbstputz 26.09. steht noch aus" if day < D("2026-09-26") and miss else
                   ("Einzug mit Beitrag 15.10. bzw. Überweisung bis 15.10." if miss and day >= D("2026-09-30") else "")])
    save_wb(wb, path, who="Susanne Hoppe")


def write_joins(path: Path, cut: date):
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "2026"
    ws.append(["Eintritte und Austritte 2026 (Geschäftsstelle)"])
    ws.append([])
    ws.append(["Mitgl.-Nr.", "Name", "Art", "zum", "eingegangen am", "im Programm erfasst", "Bemerkung"])
    bold_row(ws, 3, 7)
    rows = []
    for nr, p in sorted(PERSONS.items()):
        if p["joined"].year == 2026 and p["joined"] <= cut + timedelta(days=5):
            rows.append((p["joined"] - timedelta(days=12), [nr, f"{p['last']}, {p['first']}", "Eintritt", p["joined"],
                                                            p["joined"] - timedelta(days=12), p["joined"] - timedelta(days=9), ""]))
        if p["left"] and ACCOUNTS[p["acct"]]["nr"] == nr:
            rec = known_left(p, cut)
            if not rec:
                continue
            got = ACCOUNTS[nr].get("cancel_received") or {1094: D("2026-05-18"), 1530: D("2026-05-20"), 1356: D("2026-06-25"),
                                                         1467: D("2026-08-25"), 1288: D("2026-05-12"), 1007: D("2026-08-12"),
                                                         1266: D("2026-10-05")}.get(nr)
            entered = p.get("sw_left_known") or (got + timedelta(days=3) if got else None)
            note = {1288: "erst am 20.07. im Programm – Q3 wurde noch eingezogen, erstattet 24.07.",
                    1356: "Kündigung vom 25.06. zum 30.06. verspätet (Frist 4 Wochen) – wirksam 30.09., Antwort 26.06.",
                    1007: "verstorben am 08.08.2026", 1266: "Streichung durch Vorstandsbeschluss (Beitragsrückstand)"}.get(nr, "")
            rows.append((got or p["left"], [nr, f"{p['last']}, {p['first']}", "Austritt" if p["why_left"] != "verstorben" else "Tod",
                                           p["left"], got, entered, note]))
    for _, r in sorted(rows, key=lambda x: (x[0], x[1][0])):
        ws.append(r)
    save_wb(wb, path, who="Petra Kunze")


# ------------------------------------------------------------------ writers: PDFs
def _pdf(draw, title="Dokument") -> bytes:
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=A4, invariant=1)
    c.setTitle(title)
    c.setAuthor("")
    draw(c)
    c.showPage()
    c.save()
    return buf.getvalue()


def _head(c, sender: list[str], to: list[str], info: list[tuple[str, str]], title: str):
    c.setFont("Helvetica-Bold", 15)
    c.drawString(20 * mm, 272 * mm, sender[0])
    c.setFont("Helvetica", 8)
    c.drawString(20 * mm, 266 * mm, " · ".join(sender[1:]))
    c.setFont("Helvetica", 7)
    c.drawString(20 * mm, 240 * mm, f"{sender[0]} · {sender[1]}")
    c.setFont("Helvetica", 10)
    for k, line in enumerate(to):
        c.drawString(20 * mm, (232 - 5 * k) * mm, line)
    c.setFont("Helvetica", 9)
    for k, (a, b) in enumerate(info):
        c.drawString(128 * mm, (240 - 5 * k) * mm, a)
        c.drawString(163 * mm, (240 - 5 * k) * mm, b)
    c.setFont("Helvetica-Bold", 13)
    c.drawString(20 * mm, 196 * mm, title)


def _table(c, y, heads, rows, widths, size=8.5):
    c.setFont("Helvetica-Bold", size)
    x = 20
    for h, w in zip(heads, widths):
        c.drawString(x * mm, y, h)
        x += w
    c.line(20 * mm, y - 2, 195 * mm, y - 2)
    y -= 13
    c.setFont("Helvetica", size)
    for row in rows:
        x = 20
        for v, w in zip(row, widths):
            c.drawString(x * mm, y, str(v))
            x += w
        y -= 12
    return y


def _lines(c, y, lines, size=9, x=20):
    c.setFont("Helvetica", size)
    for line in lines:
        if line.startswith("**"):
            c.setFont("Helvetica-Bold", size)
            c.drawString(x * mm, y, line[2:])
            c.setFont("Helvetica", size)
        else:
            c.drawString(x * mm, y, line)
        y -= size + 3.2
    return y


CLUB_SENDER = [CLUB["name"], f"{CLUB['street']} · {CLUB['zip']} {CLUB['city']}", f"Tel. {CLUB['phone']}", CLUB["mail"]]


def pdf_own_invoice(i: dict) -> bytes:
    g = GUESTS[i["to"]]
    a = ACCTS["HK"]

    def draw(c):
        _head(c, CLUB_SENDER, [g["name"]] + ([g["contact"]] if g.get("contact") else []) + [g["street"], f"{g['plz']} {g['town']}"],
              [("Rechnungs-Nr.:", i["no"]), ("Datum:", dde(i["date"])), ("Leistungsdatum:", dde(i["date"])),
               ("Kunden-Nr.:", str(i["to"]))], f"Rechnung Nr. {i['no']}")
        y = _table(c, 182 * mm, ["Pos.", "Leistung", "Netto"], [[1, i["subject"][:80], de(i["net"]) + " €"]], [12, 140, 25])
        y = _lines(c, y - 10, [f"Summe netto: {de(i['net'])} €", f"zzgl. 19 % USt: {de(i['vat'])} €", f"**Rechnungsbetrag: {de(i['gross'])} €",
                               "", f"Zahlbar bis {dde(i['due'])} ohne Abzug auf das Konto {fmt_iban(a['iban'])} ({a['bank']}).",
                               f"Bitte geben Sie die Rechnungsnummer {i['no']} als Verwendungszweck an."], 9.5)
        c.setFont("Helvetica", 7)
        c.drawString(20 * mm, 20 * mm, f"{CLUB['name']} · {CLUB['vr']} · Steuernummer {CLUB['stnr']} · USt-IdNr. {CLUB['vat']} · "
                                       f"vertreten durch den Vorstand nach § 26 BGB: {BOARD['chair']}, {BOARD['vice']}, {BOARD['treasurer']}")
    return _pdf(draw, f"Rechnung {i['no']}")


def pdf_supplier(x: dict, fraud: bool = False) -> bytes:
    s = SUPPLIERS[x["sup"]]
    iban = FRAUD_IBAN if fraud else s["iban"]

    def draw(c):
        to = [CLUB["name"], f"z. Hd. {BOARD['treasurer']} (Kassenwart)", CLUB["street"], f"{CLUB['zip']} {CLUB['city']}"]
        if x["sup"] == "STADT":
            _head(c, [s["name"], s["sub"], s["street"], f"{s['plz']} {s['town']}"], to,
                  [("Kassenzeichen:", x["no"]), ("Datum:", dde(x["date"])), ("Fällig am:", dde(x["due"]))],
                  "Entgeltbescheid Nutzung städtischer Sporthallen")
            y = _table(c, 182 * mm, ["Leistung", "Betrag"], [[x["lines"][0][0][:95], de(x["gross"]) + " €"]], [150, 25])
            _lines(c, y - 10, [f"**Zu zahlen bis {dde(x['due'])}: {de(x['gross'])} €",
                               f"Bitte überweisen Sie unter Angabe des Kassenzeichens {x['no']} auf das Konto der Stadtkasse",
                               f"IBAN {fmt_iban(iban)} ({BANKS[s['blz']][0]}). Das Entgelt ist nicht umsatzsteuerpflichtig (§ 2b UStG).",
                               "Gegen diesen Bescheid kann innerhalb eines Monats Widerspruch eingelegt werden."], 9)
            return
        _head(c, [s["name"], s["street"], f"{s['plz']} {s['town']}", s["mail"].replace("hegemann", "hegeman") if fraud else s["mail"]],
              to, [("Rechnungs-Nr.:", x["no"] + (" (korrigiert)" if fraud else "")), ("Datum:", dde(x["date"] if not fraud else D("2026-10-20"))),
                   ("Kunden-Nr.:", "40817"), ("Fällig:", dde(x["due"] if not fraud else D("2026-10-30")))],
              "Rechnung" + (" – Korrektur" if fraud else ""))
        rows = [[k + 1, t[:70], q, de(p), de(q * p)] for k, (t, q, p) in enumerate(x["lines"])]
        y = _table(c, 182 * mm, ["Pos.", "Bezeichnung", "Menge", "Einzelpreis", "Gesamt"], rows, [12, 110, 15, 22, 20])
        tail = [f"Summe netto: {de(x['net'])} €"]
        if x["vat"]:
            tail.append(f"zzgl. 19 % USt: {de(x['vat'])} €")
        elif x.get("kleinunternehmer"):
            tail.append("Gemäß § 19 UStG wird keine Umsatzsteuer berechnet.")
        tail.append(f"**Rechnungsbetrag: {de(x['gross'])} €")
        if x.get("skonto") and not fraud:
            tail.append(f"Zahlbar innerhalb von {x['skonto'][1]} Tagen mit {x['skonto'][0]} % Skonto, "
                        f"innerhalb von 30 Tagen netto.")
        else:
            tail.append(f"Zahlbar bis {dde(x['due'] if not fraud else D('2026-10-30'))} ohne Abzug.")
        tail.append(f"Bankverbindung: IBAN {fmt_iban(iban)}" + (" (Swedbank Vilnius) – bitte nur noch dieses Konto verwenden!" if fraud
                                                                  else f" ({BANKS[s['blz']][0]})"))
        if s.get("ust"):
            tail.append(f"USt-IdNr. {s['ust']}")
        _lines(c, y - 10, tail, 9)
    return _pdf(draw, f"Rechnung {x['no']}")


FRAUD_IBAN = iban_cc("LT", "73000" + "10123456789")
CEO_IBAN = iban_cc("ES", "2100" + "0418" + "45" + "0200051332")


def pdf_text(title: str, lines: list[str], sender=None) -> bytes:
    def draw(c):
        c.setFont("Helvetica-Bold", 13)
        c.drawString(20 * mm, 275 * mm, (sender or CLUB_SENDER)[0])
        c.setFont("Helvetica", 8)
        c.drawString(20 * mm, 270 * mm, " · ".join((sender or CLUB_SENDER)[1:]))
        c.setFont("Helvetica-Bold", 12)
        c.drawString(20 * mm, 255 * mm, title)
        _lines(c, 245 * mm, lines, 8.6)
    return _pdf(draw, title)


def fee_table() -> list[str]:
    out = ["**Grundbeitrag je Monat              bis 30.06.2026     ab 01.07.2026"]
    for g, (a, b) in GRUND.items():
        out.append(f"   {g:<32}{de(a):>12} €{de(b):>16} €")
    out.append("**Abteilungszuschlag je Monat (Erwachsene / Jugendliche und Ermäßigte)")
    for d, v in ZUSCHLAG.items():
        if any(v["E"]) or any(v["J"]):
            out.append(f"   {DEPTS[d]:<22} bis 30.06.: {de(v['E'][0])} / {de(v['J'][0])} €    ab 01.07.: {de(v['E'][1])} / {de(v['J'][1])} €")
    return out


def pdf_beitragsordnung() -> bytes:
    lines = ["Beschlossen von der Mitgliederversammlung am 20.03.2026, gültig ab 01.07.2026", ""] + fee_table() + [
        "", "**§ 3 Aufnahmegebühr",
        "   Erwachsene 30,00 €, Familien 40,00 €, Jugendliche und Ermäßigte 15,00 €, fördernde Mitglieder keine.",
        "**§ 4 Zahlungsweise und Fälligkeit",
        "   Die Beiträge werden im Voraus fällig, und zwar am 15. des ersten Monats des Zahlungszeitraums (monatlich,",
        "   vierteljährlich, halbjährlich oder jährlich). Monatliche Zahlung nur mit SEPA-Lastschrift. Der Einzug erfolgt am",
        "   15. bzw. am folgenden Bankarbeitstag. Wer überweist, zahlt ohne Aufforderung bis zum 15. des ersten Monats.",
        "   Neue Mitglieder zahlen ab dem Monat des Eintritts; der erste Beitrag und die Aufnahmegebühr werden mit dem",
        "   nächsten Einzug fällig, bei Überweisung binnen 14 Tagen nach Aufnahme.",
        "**§ 5 Beitragserhöhung 2026",
        "   Jahreszahler haben im Januar den Beitrag 2026 nach den bisherigen Sätzen gezahlt. Die Differenz für Juli bis",
        "   Dezember wird mit dem Einzug am 15.07.2026 eingezogen bzw. ist bis 15.07.2026 zu überweisen.",
        "**§ 6 Familienbeitrag",
        "   Familienbeitrag: Eltern bzw. ein Elternteil mit ihren Kindern bis 18 Jahre im gemeinsamen Haushalt. Die",
        "   Abteilungszuschläge zahlt jedes Familienmitglied, sie werden mit dem Familienbeitrag beim Beitragszahler eingezogen.",
        "**§ 7 Rücklastschriften",
        "   Kosten einer Rücklastschrift, die das Mitglied zu vertreten hat, trägt das Mitglied (derzeit 3,00 €).",
        "**§ 8 Ermäßigung, Altersgrenze",
        "   Schüler, Studierende und Auszubildende ab 18 Jahren zahlen auf Antrag den ermäßigten Beitrag ab dem Quartal nach",
        "   Vorlage der Bescheinigung. Ab dem Monat nach dem 18. Geburtstag gilt der Erwachsenenbeitrag (bzw. ermäßigt).",
        "**§ 9 Kündigung (Satzung § 6)",
        "   Der Austritt ist schriftlich mit einer Frist von vier Wochen zum Ende eines Kalendervierteljahres zu erklären.",
        "   Bereits gezahlte Beiträge für Zeiträume nach dem Austritt werden erstattet.",
        "**§ 10 Arbeitsstunden Abteilung Tennis",
        "   Erwachsene Mitglieder der Tennisabteilung leisten je Saison 5 Arbeitsstunden. Für jede nicht geleistete Stunde",
        "   werden 15,00 € zum 01.10. als Forderung gestellt und am 15.10. eingezogen bzw. sind bis 15.10. zu überweisen.",
        "**§ 11 Ehrenmitglieder sind beitragsfrei.",
        "", f"Kassenwart: {BOARD['treasurer']}, {CLUB['mail']} · Bankverbindung {fmt_iban(ACCTS['HK']['iban'])}",
        f"Gläubiger-Identifikationsnummer: {CI}"]
    return pdf_text("Beitragsordnung des TuS Wendelstede 1907 e.V.", lines)


def pdf_protokoll_mv() -> bytes:
    lines = ["Ort: Vereinsgaststätte am Sportpark · Beginn 19:30 Uhr · Ende 22:05 Uhr · Versammlungsleitung: Dieter Lohmann",
             "Anwesend: 87 stimmberechtigte Mitglieder (Anwesenheitsliste) · Protokoll: Karin Ostermann-Wiese", "",
             "**TOP 1 Begrüßung, Feststellung der ordnungsgemäßen Einladung und Beschlussfähigkeit",
             "**TOP 2 Kassenbericht 2025 (Helga Brettschneider)",
             "   Einnahmen 2025: 141.388,20 € (davon Mitgliedsbeiträge 79.410,00 €), Ausgaben 2025: 146.902,61 €.",
             "   Kassenbestand 31.12.2025: Hauptkonto 23.418,77 €, Tennis 4.212,40 €, Tagesgeld 18.000,00 €, Kasse 412,30 €.",
             "**TOP 3 Bericht der Kassenprüfer – keine Beanstandungen. **TOP 4 Entlastung des Vorstands – einstimmig.",
             "**TOP 5 Wahlen: Kassenwart Jens Albers (78 Ja, 2 Nein, 7 Enthaltungen). Frau Brettschneider wird nach 19 Jahren",
             "   verabschiedet und übergibt Kasse und Unterlagen am 21.03.2026.",
             "**TOP 6 Beitragserhöhung zum 01.07.2026 – Antrag des Vorstands, beschlossen mit 71 Ja, 9 Nein, 7 Enthaltungen:"] + \
        ["   " + x for x in fee_table()] + [
             "   Jahreszahler zahlen die Differenz für das 2. Halbjahr mit dem Einzug am 15.07. bzw. überweisen sie bis 15.07.",
             "**TOP 7 Arbeitsstunden Tennis: 5 Stunden je Saison, Ersatz 15,00 € je Stunde (bestätigt).",
             "**TOP 8 Verschiedenes: Darlehen Kunstrasenplatz (Rate 1.480,00 € monatlich), Sommerfest am 27.06., Feriencamp 03.-07.08.",
             "", "gez. Dieter Lohmann (Versammlungsleiter)        gez. Karin Ostermann-Wiese (Protokoll)"]
    return pdf_text("Protokoll der ordentlichen Mitgliederversammlung vom 20.03.2026", lines)


def pdf_protokoll_vorstand() -> bytes:
    lines = ["Anwesend: Dieter Lohmann, Karin Ostermann-Wiese, Jens Albers, Marco Riedel, Susanne Hoppe · Beginn 19:00 Uhr", "",
             "**1. Beitragsrückstände (Bericht Kassenwart)",
             "   Dennis Rohlfing (1266): Rückstand Q4/2025, Q2/2026 und Q3/2026 (135,00 €) trotz zweimaliger Mahnung.",
             "   Beschluss: Streichung von der Mitgliederliste zum 30.09.2026 (Satzung § 7). Die Forderung bleibt bestehen,",
             "   Mahnbescheid wird vorbereitet. – einstimmig",
             "   Marc Gieseking (1356): Widerspruch gegen den Juli-Einzug. Kündigung kam am 25.06., wirksam zum 30.09.;",
             "   Beitrag Q3 (51,00 €) wird angemahnt.",
             "**2. Pacht Vereinsgaststätte",
             "   Herr Papadakis hat im August 411,50 € wegen der defekten Kühlzelle einbehalten. Die Kühlzelle gehört laut",
             "   Pachtvertrag (§ 4) zum Inventar des Pächters. Beschluss: Minderung nicht berechtigt, Nachzahlung anfordern.",
             "**3. Hallennutzung TV Ostheide – Rechnung 2026-027 wird nach Hallenbuch (6 Std.) geprüft, bleibt bis dahin offen.",
             "**4. Feriencamp: Abrechnung liegt vor, ein Teilnehmerbeitrag noch offen. Zuschuss KSB 600,00 € eingegangen.",
             "**5. Sponsoring Kunstrasen (Autohaus Brinkmann, Vertrag SV-2026-07): Rechnung durch Kassenwart.",
             "", "gez. Karin Ostermann-Wiese (Protokoll)"]
    return pdf_text("Protokoll der Vorstandssitzung vom 05.10.2026", lines)


def pdf_pachtvertrag() -> bytes:
    lines = ["zwischen dem TuS Wendelstede 1907 e.V. (Verpächter) und Herrn Nikos Papadakis (Pächter)", "",
             "**§ 1 Pachtgegenstand: Vereinsgaststätte im Vereinsheim, Am Sportpark 3, mit Küche, Gastraum und Terrasse.",
             "**§ 2 Pachtdauer: ab 01.04.2023, unbefristet, Kündigung mit 6 Monaten zum Jahresende.",
             "**§ 3 Pacht: monatlich 850,00 € zuzüglich Umsatzsteuer (19 %) 161,50 €, zusammen 1.011,50 €, zahlbar im Voraus",
             "   bis zum 3. Werktag eines jeden Monats auf das Konto des Verpächters. Die Nebenkosten trägt der Pächter direkt.",
             "   Dieser Vertrag gilt zugleich als Rechnung im Sinne des § 14 UStG.",
             "**§ 4 Inventar: Kühlzelle, Zapfanlage und Küchengeräte sind Eigentum des Pächters; Instandhaltung durch ihn.",
             "**§ 5 Minderung oder Aufrechnung nur mit unbestrittenen oder rechtskräftig festgestellten Forderungen.",
             "", "Wendelstede, 15.03.2023     gez. Dieter Lohmann, Jens Albers (für den Verein)     gez. Nikos Papadakis",
             f"Steuernummer des Verpächters {CLUB['stnr']} · Bankverbindung {fmt_iban(ACCTS['HK']['iban'])}"]
    return pdf_text("Pachtvertrag Vereinsgaststätte am Sportpark", lines)


def pdf_enrolment() -> bytes:
    lines = ["Hiermit wird bescheinigt, dass", "", "   Herr Jannik Steinkamp, geb. 11.02.2005,", "",
             "im Wintersemester 2026/27 als ordentlicher Studierender im Studiengang Maschinenbau (B.Sc.) eingeschrieben ist.",
             "Semesterzeitraum: 01.10.2026 bis 31.03.2027.", "", "Hannover, 01.09.2026 – Immatrikulationsamt (maschinell erstellt)"]
    return pdf_text("Immatrikulationsbescheinigung", lines, sender=["Hochschule Hannover-Nord (fiktiv)", "Studierendenservice"])


# ------------------------------------------------------------------ mails
MAIL_LIST: list[dict] = []


def mail(key, when, frm, to, subject, body, att=(), reply=None, waits=(), what=""):
    MAIL_LIST.append(dict(key=key, when=when, frm=frm, to=to, subject=subject, body=body, att=list(att), reply=reply,
                          waits=set(waits), what=what))


def sig(who=None):
    who = who or f"{BOARD['treasurer']}, Kassenwart"
    return f"\n\nMit sportlichen Grüßen\n{who}\n{CLUB['name']} · {CLUB['street']} · {CLUB['zip']} {CLUB['city']}\n{CLUB['mail']}"


def build_mails():
    P = PERSONS
    kasse = f"{BOARD['treasurer']} <{CLUB['mail']}>"
    info = f"TuS Wendelstede Geschäftsstelle <{CLUB['info']}>"
    mail("m01", "2026-06-25T09:12", f"Marc Gieseking <{P[1356]['mail']}>", info, "Kündigung Mitgliedschaft",
         "Hallo,\n\nhiermit kündige ich meine Mitgliedschaft im TuS (Mitgl.-Nr. 1356) zum 30.06.2026. Bitte ab Juli "
         "nichts mehr abbuchen.\n\nGruß\nMarc Gieseking", what="Kündigung zu spät (Frist 4 Wochen) – wirksam 30.09.")
    mail("m02", "2026-06-26T11:40", kasse, f"Marc Gieseking <{P[1356]['mail']}>", "AW: Kündigung Mitgliedschaft",
         "Sehr geehrter Herr Gieseking,\n\nvielen Dank für Ihre Nachricht. Nach § 6 unserer Satzung ist der Austritt mit einer "
         "Frist von vier Wochen zum Quartalsende möglich. Ihre Kündigung ist am 25.06. eingegangen und wird deshalb zum "
         "30.09.2026 wirksam. Der Beitrag für das 3. Quartal (51,00 €) wird am 15.07. noch eingezogen." + sig(), reply="m01",
         what="eigene Antwort")
    mail("m03", "2026-07-20T18:03", f"Torsten Vahle <{P[1349]['mail']}>", kasse, "Abbuchung 72 statt 63 Euro?",
         "Hallo Herr Albers,\n\nmir wurden am 15.07. 72,00 € abgebucht, bisher waren es 63,00 € im Quartal. Stimmt da was "
         "nicht? Ich habe von einer Erhöhung nichts mitbekommen.\n\nViele Grüße\nTorsten Vahle (1349)",
         what="Beitragserhöhung nicht bemerkt")
    mail("m04", "2026-07-21T08:15", kasse, f"Torsten Vahle <{P[1349]['mail']}>", "AW: Abbuchung 72 statt 63 Euro?",
         "Hallo Herr Vahle,\n\ndie Mitgliederversammlung hat am 20.03. eine Beitragserhöhung zum 01.07. beschlossen "
         "(Grundbeitrag 14,00 €, Tennis 10,00 € im Monat). Die Abbuchung ist also richtig. Die neue Beitragsordnung hängt im "
         "Vereinsheim aus und steht auf der Homepage." + sig(), reply="m03", what="eigene Antwort")
    mail("m05", "2026-07-28T19:44", f"Frank Böttcher <{P[1123]['mail']}>", kasse, "Rücklastschrift Beitrag",
         "Hallo,\n\ndie Abbuchung vom 15.07. ist leider zurückgegangen, mein Konto war kurz nicht gedeckt. Sorry! Buchen Sie "
         "einfach noch mal ab.\n\nFrank Böttcher", what="Rücklastschrift 1123")
    mail("m06", "2026-07-29T07:58", kasse, f"Frank Böttcher <{P[1123]['mail']}>", "AW: Rücklastschrift Beitrag",
         "Hallo Herr Böttcher,\n\nbis zum nächsten Quartalseinzug dauert es leider. Bitte überweisen Sie 72,00 € für das "
         "3. Quartal zzgl. 3,00 € Rücklastschriftgebühr (§ 7 Beitragsordnung) auf unser Konto "
         f"{fmt_iban(ACCTS['HK']['iban'])}." + sig(), reply="m05", what="eigene Antwort")
    mail("m07", "2026-08-05T10:21", f"Nikos Papadakis <{GUESTS[9003]['mail']}>", "Dieter Lohmann <vorstand@tus-wendelstede.example>",
         "Pacht August – Minderung wegen Kühlzelle",
         "Hallo Dieter,\n\nseit dem 28.07. ist die Kühlzelle kaputt, ich musste Ware wegwerfen und ein Kühlmobil mieten. Ich "
         "überweise für August deshalb nur 600,00 € statt 1.011,50 €. Die Reparatur kostet über 3.000 €, das sehe ich als "
         "Sache des Vereins.\n\nGruß\nNikos", waits={"lieferung1"}, what="Minderung Pacht 08/2026 (411,50 €)")
    mail("m08", "2026-08-25T21:07", f"Tanja Ruhnke <{mail_of('Tanja', 'Ruhnke', 'tr')}>", info, "Kündigung Finn Ruhnke (1467)",
         "Sehr geehrte Damen und Herren,\n\nhiermit kündige ich die Mitgliedschaft meines Sohnes Finn Ruhnke (Mitgl.-Nr. 1467) "
         "zum 30.09.2026. Er hört mit dem Fußball auf.\n\nMit freundlichen Grüßen\nTanja Ruhnke", what="Kündigung fristgerecht")
    mail("m09", "2026-09-02T22:30", f"Marc Gieseking <{P[1356]['mail']}>", kasse, "Widerspruch Lastschrift",
         "Hallo,\n\nich habe der Abbuchung vom 15.07. bei meiner Bank widersprochen. Ich bin zum 30.06. ausgetreten, das habe "
         "ich rechtzeitig geschrieben. Ich zahle für Juli bis September nichts.\n\nMarc Gieseking",
         waits={"lieferung1", "lieferung2"}, what="Widerspruch MD06 – Q3 bleibt geschuldet")
    mail("m10", "2026-09-08T17:12", f"Jannik Steinkamp <{P[1514]['mail']}>", info, "Ermäßigung Student ab Oktober",
         "Hallo,\n\nich studiere ab Oktober in Hannover, die Immatrikulationsbescheinigung hänge ich an. Kann ich ab dem "
         "4. Quartal den ermäßigten Beitrag zahlen? Ich bleibe in der 2. Herren.\n\nDanke und Gruß\nJannik Steinkamp (1514)",
         att=[("Immatrikulationsbescheinigung_WiSe2026.pdf", ("enrol", None))], waits={"lieferung1"},
         what="Ermäßigung ab Q4 (im Programm ab 01.10.)")
    a1207 = ACCOUNTS[1207]
    mail("m11", "2026-09-09T20:48", f"Nadine Wiegand <{P[1208]['mail']}>", kasse, "Neue Bankverbindung für den Beitragseinzug",
         "Hallo Herr Albers,\n\nunser Konto bei der Weserland Bank haben wir aufgelöst, deshalb ist die Abbuchung im Juli "
         "zurückgegangen – tut uns leid. Unsere neue Bankverbindung für den Familienbeitrag (Mitgl.-Nr. 1207):\n\n"
         f"Kontoinhaberin: Nadine Wiegand\nIBAN: {fmt_iban(a1207['new_iban'][1])}\nBank: {BANKS[a1207['new_iban'][1][4:12]][0]}\n\n"
         "Bitte ziehen Sie den offenen Beitrag einfach mit dem nächsten Beitrag ein.\n\nViele Grüße\nNadine Wiegand",
         what="Mitglied ändert IBAN (kein Betrug), im Programm am 10.09.")
    mail("m12", "2026-09-14T09:03", f"Renate Ohlendorf <{P[1077]['mail']}>", kasse, "Beitrag doppelt bezahlt?",
         "Guten Tag,\n\nbeim Durchsehen meiner Kontoauszüge habe ich gesehen, dass ich den Jahresbeitrag 2026 (144,00 €) im "
         "Januar und noch einmal am 05.08. überwiesen habe. Können Sie mir den doppelten Betrag zurücküberweisen?\n\n"
         "Freundliche Grüße\nRenate Ohlendorf", waits={"lieferung1"}, what="doppelt gezahlt, erstattet 09.10.")
    mail("m13", "2026-09-10T11:30", f"Sportwerk Hegemann GmbH <{SUPPLIERS['HEG']['mail']}>", kasse, "Rechnung 26-4471",
         "Sehr geehrte Damen und Herren,\n\nanbei erhalten Sie unsere Rechnung 26-4471 vom 10.09.2026 als PDF.\n\n"
         "Mit freundlichen Grüßen\nIhr Team von Sportwerk Hegemann", att=[("RE_26-4471.pdf", ("sup", "26-4471"))],
         what="Eingangsrechnung, Skonto bis 20.09.")
    mail("m14", "2026-09-16T15:55", f"Ursula Lampe <{mail_of('Ursula', 'Lampe', 'ul')}>", kasse, "Spendenquittung",
         "Hallo,\n\nwir haben im August im Gedenken an Erwin Pape 30 € für die Jugend gespendet. Bitte schicken Sie uns dafür "
         "eine Zuwendungsbestätigung für das Finanzamt.\n\nUrsula und Heinz Lampe", waits={"lieferung1", "lieferung2"},
         what="Zuwendungsbestätigung")
    mail("m15", "2026-09-03T06:00", "Sportwerk Hegemann <newsletter@sportwerk-hegemann.example>", CLUB["mail"],
         "Herbstaktion: 15 % auf Hallenbälle", "Liebe Vereine, nur bis 30.09.: 15 % Rabatt auf alle Hallenbälle. "
         "Abmelden: hier klicken.", what="Newsletter")
    # second delivery
    mail("m16", "2026-10-02T08:40", f"Anke Kröger <{GUESTS[9012]['mail']}>", kasse, "Ihre Rechnung 2026-019",
         "Hallo Herr Albers,\n\ndie Rechnung 2026-019 (Trikotsponsoring) haben wir gestern überwiesen – entschuldigen Sie die "
         "Verspätung, unsere Buchhalterin war im Urlaub.\n\nViele Grüße\nAnke Kröger", what="sagt bezahlt; Geld am 09.10.")
    mail("m17", "2026-10-05T12:14", f"Bärbel Kamphenkel <{GUESTS[9021]['mail']}>", kasse, "Rückfrage zur Rechnung 2026-027",
         "Hallo,\n\nzu Ihrer Rechnung 2026-027: Wir waren am 22.08. nur von 10 bis 14 Uhr in der Halle, nicht sechs Stunden. "
         "Bitte korrigieren Sie die Rechnung, dann überweisen wir sofort.\n\nViele Grüße\nBärbel Kamphenkel, Kassenwartin TV Ostheide",
         waits={"lieferung2"}, what="Reklamation 2026-027 – nicht mahnen, erst klären")
    mail("m18", "2026-10-10T16:20", f"Andreas Kühn <{P[1222]['mail']}>", info, "Kündigung zum 31.12.2026",
         "Hallo zusammen,\n\nleider ziehe ich beruflich nach Bremen. Ich kündige meine Mitgliedschaft (1222, Volleyball) zum "
         "31.12.2026. Danke für die schöne Zeit!\n\nAndreas Kühn", waits={"lieferung2"}, what="Kündigung fristgerecht, bestätigen")
    mail("m19", "2026-10-13T10:05", f"Jörg Brinkmann <{GUESTS[9011]['mail']}>", kasse, "Rechnung Bandenwerbung Kunstrasen",
         "Sehr geehrter Herr Albers,\n\nfür die neue Bande am Kunstrasenplatz (Vertrag vom 28.07.2026, Saison 2026/27) haben wir "
         "noch keine Rechnung erhalten. Bitte schicken Sie uns die Rechnung, damit wir sie noch im Oktober bezahlen können.\n\n"
         "Mit freundlichen Grüßen\nJörg Brinkmann\nAutohaus Brinkmann GmbH", waits={"lieferung2"},
         what="Rechnung SV-2026-07 fehlt (nicht berechnet)")
    mail("m20", "2026-10-21T14:37", "Sportwerk Hegemann GmbH <buchhaltung@sportwerk-hegeman.example>", kasse,
         "Korrigierte Rechnung 26-4471 – neue Bankverbindung",
         "Sehr geehrte Damen und Herren,\n\nleider war unsere Rechnung 26-4471 fehlerhaft. Anbei die korrigierte Rechnung. "
         "Bitte beachten Sie unsere neue Bankverbindung, die alte ist nicht mehr gültig:\n\n"
         f"IBAN {fmt_iban(FRAUD_IBAN)}\n\nBitte überweisen Sie den Betrag bis 30.10.2026.\n\nMit freundlichen Grüßen\nBuchhaltung",
         att=[("RE_26-4471_korrigiert.pdf", ("fraud", "26-4471"))], waits={"lieferung2"},
         what="Betrug: ähnliche Domain, litauische IBAN, Rechnung längst bezahlt")
    mail("m21", "2026-10-22T19:02", f"Mehmet Aydın <{P[1584]['mail']}>", kasse, "Lastschrift zurückgegangen",
         "Hallo,\n\ndie Lastschrift vom 15.10. ist zurückgegangen, weil ich das Konto gewechselt habe. Neue Bankverbindung: "
         f"IBAN {fmt_iban(bank_acct(1584, 'neu', blz='10011099')[0])}. Bitte buchen Sie noch einmal ab.\n\nGruß Mehmet Aydın (1584)",
         waits={"lieferung2"}, what="Mitglied ändert IBAN nach Rücklastschrift")
    sp = next(p for p in sorted(PERSONS.values(), key=lambda p: p["nr"]) if p["nr"] not in SPECIAL_NRS and p["sex"] == "m"
              and age_at(p, L2_CUT) > 50 and not p["left"] and not any(r["konto"] == p["nr"] for r in REGS))
    mail("m22", "2026-10-22T20:15", f"{FIRST_F[3]} {sp['last']} <{mail_of(FIRST_F[3], sp['last'], 'w')}>", info,
         "Anmeldung Rückenfit", f"Hallo Frau Lanz,\n\nmein Mann {sp['first']} {sp['last']} (Mitglied, Nr. {sp['nr']}) möchte "
         "gern noch beim Rückenfit-Kurs montags mitmachen, falls noch ein Platz frei ist. Geht das auch nach Kursbeginn?\n\n"
         f"Viele Grüße\n{FIRST_F[3]} {sp['last']}", waits={"lieferung2"}, what="Kursanmeldung per Mail")
    mail("m23", "2026-10-26T09:48", f"Ralf Hesse <{GUESTS[9013]['mail']}>", kasse, "Spende / Zuwendungsbestätigung",
         "Hallo Herr Albers,\n\nwir haben am 09.10. 500 € für die Jugend gespendet. Bitte schicken Sie uns eine "
         "Zuwendungsbestätigung. Die offenen 228 € aus Ihrer Bandenrechnung 2026-003 verrechnen Sie bitte einfach damit.\n\n"
         "Gruß Ralf Hesse", waits={"lieferung2"}, what="Spende kann keine USt-Forderung tilgen")
    mail("m24", "2026-10-27T07:51", "Dieter Lohmann <dieter.lohmann.tusw@gmail.example>", CLUB["mail"], "Dringend – heute noch",
         "Hallo Jens,\n\nich sitze gleich den ganzen Tag in einer Sitzung beim Kreissportbund und bin nicht erreichbar. Bitte "
         "überweise heute noch 4.870,00 € Anzahlung für das Trainingslager der 1. Herren im März an\n\nSport Travel Iberia S.L.\n"
         f"IBAN {fmt_iban(CEO_IBAN)}\nVerwendungszweck: Reserva TuS-2027\n\nDie Rechnung reiche ich nach. Bitte nicht anrufen, "
         "ich melde mich heute Abend.\n\nGruß Dieter", waits={"lieferung2"}, what="Betrug (Chef-Masche), keine Rechnung")
    mail("m25", "2026-10-28T18:30", f"Svenja Lührs <{P[1598]['mail']}>", kasse, "Oktober doppelt bezahlt",
         "Hallo,\n\nich dachte, die Abbuchung im Oktober hat nicht geklappt, und habe am 19.10. noch einmal 14 € überwiesen. "
         "Jetzt sehe ich beide Buchungen. Bitte erstatten Sie mir die 14 €.\n\nLG Svenja Lührs", waits={"lieferung2"},
         what="doppelt (Lastschrift + Überweisung)")
    mail("m26", "2026-10-09T11:12", f"Teamsport Ahlers <{SUPPLIERS['TA']['mail']}>", kasse, "Ihre Rechnung TA-26-1187",
         "Guten Tag,\n\nanbei die Rechnung für den Trikotsatz der 1. Herren.\n\nMit freundlichen Grüßen\nTeamsport Ahlers",
         att=[("Rechnung_TA-26-1187.pdf", ("sup", "TA-26-1187"))], what="Eingangsrechnung")


def write_eml(path: Path, m: dict, ids: dict) -> str:
    dt = datetime.fromisoformat(m["when"])
    dt = dt.replace(tzinfo=timezone(timedelta(hours=1 if dt.date() >= D("2026-10-25") else 2)))
    msg = EmailMessage()
    msg["From"] = m["frm"]
    msg["To"] = m["to"]
    msg["Date"] = format_datetime(dt)
    msg["Subject"] = m["subject"]
    dom = m["frm"].split("@")[-1].strip(">")
    mid = f"<{hashlib.md5(m['key'].encode()).hexdigest()[:20]}@{dom}>"
    msg["Message-ID"] = mid
    if m["reply"] and m["reply"] in ids:
        msg["In-Reply-To"] = ids[m["reply"]]
        msg["References"] = ids[m["reply"]]
    msg.set_content(m["body"])
    for name, (kind, ref) in m["att"]:
        if kind == "enrol":
            data = pdf_enrolment()
        else:
            x = next(s for s in SUPINV if s["no"] == ref)
            data = pdf_supplier(x, fraud=kind == "fraud")
        msg.add_attachment(data, maintype="application", subtype="pdf", filename=name)
    if m["att"]:
        msg.set_boundary("==" + hashlib.md5((m["key"] + "|b").encode()).hexdigest()[:24] + "==")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(bytes(msg))
    return mid


def slug(s: str) -> str:
    tr = {"ä": "ae", "ö": "oe", "ü": "ue", "Ä": "Ae", "Ö": "Oe", "Ü": "Ue", "ß": "ss", "–": "-", "ı": "i"}
    s = "".join(tr.get(ch, ch) for ch in s)
    return "".join(ch if ch.isalnum() else "_" for ch in s).strip("_")[:60]


# ------------------------------------------------------------------ the deliveries
def write_delivery(root: Path, dv: dict) -> list[str]:
    out, cut = root / dv["folder"], dv["cut"]
    l2 = dv["folder"] == "lieferung2"
    write_export(out / "Mitglieder" / "Mitglieder_Export_2026-09-18.csv", L1_CUT, only_active=False)
    if l2:
        write_export(out / "Mitglieder" / "Mitglieder_Export_2026-10-29.csv", L2_CUT, only_active=True)
    (out / "Mitglieder" / "Beitragsordnung_ab_2026-07-01.pdf").write_bytes(pdf_beitragsordnung())
    write_joins(out / "Mitglieder" / "Eintritte_Austritte_2026.xlsx", cut)
    for r in RUNS:
        if r["date"] <= cut:
            write_pain008(out / "Lastschriften" / r["file"], r)
    write_mt940(out / "Bank" / "Hauptkonto" / "Umsaetze_Q1_2026_StarMoney.sta", "HK", D("2026-01-01"), D("2026-03-31"))
    write_vr(out / "Bank" / "Hauptkonto" / f"Umsaetze_{ACCTS['HK']['iban']}_2026-04-01_bis_2026-09-18.csv", "HK",
             D("2026-04-01"), L1_CUT)
    if l2:
        write_vr(out / "Bank" / "Hauptkonto" / f"Umsaetze_{ACCTS['HK']['iban']}_2026-07-01_bis_2026-10-29.csv", "HK",
                 D("2026-07-01"), L2_CUT)
    write_spk_mt940csv(out / "Bank" / "Tennis" / f"20260918-{ACCTS['TK']['kto']}-umsatz.CSV", "TK", D("2026-01-01"), L1_CUT)
    if l2:
        write_spk_mt940csv(out / "Bank" / "Tennis" / f"20261029-{ACCTS['TK']['kto']}-umsatz.CSV", "TK", D("2026-01-01"), L2_CUT)
    write_cashbook(out / "Kasse" / "Kassenbuch_2026.xlsx", cut)
    write_courses(out / "Kurse" / "Kursanmeldungen_Herbst_2026.xlsx", "Herbst 2026", cut)
    write_courses(out / "Kurse" / "Kurse_Fruehjahr_2026.xlsx", "Frühjahr 2026", cut)
    write_camp_form(out / "Feriencamp" / "Feriencamp_2026_Anmeldungen_Export.csv")
    write_camp_list(out / "Feriencamp" / "Feriencamp_2026_Teilnehmer.xlsx", cut)
    write_invoice_book(out / "Rechnungen" / "Rechnungsausgang_2026.xlsx", cut, D("2026-10-15") if l2 else D("2026-08-31"))
    for no in ("2026-019", "2026-027", "2026-028") + (("2026-031", "2026-033") if l2 else ()):
        i = next(i for i in INVOICES if i["no"] == no)
        (out / "Rechnungen" / "Ausgang").mkdir(parents=True, exist_ok=True)
        (out / "Rechnungen" / "Ausgang" / f"Rechnung_{no}_{slug(GUESTS[i['to']]['name'])[:30]}.pdf").write_bytes(pdf_own_invoice(i))
    for x in SUPINV:
        if x["date"] > cut or x["no"] == "TA-26-1187":
            continue
        name = f"{x['date'].isoformat()}_{slug(SUPPLIERS[x['sup']]['name'])[:24]}_{slug(x['no'])}.pdf"
        (out / "Rechnungen" / "Eingang").mkdir(parents=True, exist_ok=True)
        (out / "Rechnungen" / "Eingang" / name).write_bytes(pdf_supplier(x))
    write_sponsoring(out / "Vertraege" / "Sponsoringvertraege_2026.xlsx", cut)
    write_hall(out / "Vertraege" / "Hallenbelegung_Fremdnutzer_2026.xlsx", cut)
    (out / "Vertraege" / "Pachtvertrag_Vereinsgaststaette.pdf").write_bytes(pdf_pachtvertrag())
    write_uel(out / "Uebungsleiter" / "UEL_Abrechnung_2026.xlsx", [1, 2, 3] if l2 else [1, 2])
    (out / "Vorstand").mkdir(parents=True, exist_ok=True)
    (out / "Vorstand" / "Protokoll_MV_2026-03-20.pdf").write_bytes(pdf_protokoll_mv())
    write_dunning(out / "Vorstand" / "Mahnliste_Stand_2026-08-31.xlsx", D("2026-08-31"))
    if l2:
        write_dunning(out / "Vorstand" / "Mahnliste_Stand_2026-10-15.xlsx", D("2026-10-15"))
        (out / "Vorstand" / "Protokoll_Vorstand_2026-10-05.pdf").write_bytes(pdf_protokoll_vorstand())
    write_work_hours(out / "Tennis" / "Arbeitsstunden_Tennis_2026.xlsx", D("2026-09-30") if l2 else D("2026-09-13"))
    ids = {}
    for m in sorted(MAIL_LIST, key=lambda m: m["when"]):
        if datetime.fromisoformat(m["when"]).date() > cut:
            continue
        ids[m["key"]] = write_eml(out / "Mails" / f"{m['when'][:10]}_{slug(m['subject'])[:40]}.eml", m, ids)
    return sorted(str(p.relative_to(out)) for p in out.rglob("*") if p.is_file())


def payables_at(cut: date) -> list[dict]:
    return [dict(supplier=SUPPLIERS[x["sup"]]["name"], invoice=x["no"], date=x["date"].isoformat(), gross=eur(x["gross"]),
                 due=x["due"].isoformat(), konto=ACCTS[x["acct"]]["what"])
            for x in SUPINV if x["date"] <= cut and (x["paid"] is None or x["paid"] > cut)]


def extra_truth(dv: dict) -> dict:
    cut = dv["cut"]
    waiting = [dict(when=m["when"][:10], subject=m["subject"], what=m["what"]) for m in MAIL_LIST
               if dv["folder"] in m["waits"] and datetime.fromisoformat(m["when"]).date() <= cut]
    risks = []
    if cut >= D("2026-10-21"):
        risks.append(dict(what="Mail von sportwerk-hegeman.example (echt: sportwerk-hegemann.example) mit litauischer IBAN und "
                               "„korrigierter“ Rechnung 26-4471 – die echte Rechnung ist am 06.10. bezahlt", invoice="26-4471"))
    if cut >= D("2026-10-27"):
        risks.append(dict(what="Chef-Masche: angeblich der Vorsitzende von einer Gmail-Adresse, 4.870,00 € sofort nach Spanien, "
                               "„bitte nicht anrufen“", invoice=None))
    not_risks = [dict(what="Mail 09.09. Wiegand: neue IBAN für den Beitragseinzug – ein Mitglied, an das der Verein nichts zahlt")]
    if cut >= D("2026-10-22"):
        not_risks.append(dict(what="Mail 22.10. Aydın: neue IBAN für die Lastschrift – kein Betrug"))
    not_receipts = [dict(date=m["date"].isoformat(), amount=eur(m["amount"]), who=m["name"], what=m["vwz"], why=m["kind"])
                    for m in MONEY if m["date"] <= cut and m["amount"] > 0 and m["acct"] != "CASH"
                    and m["kind"] in ("spende", "zuschuss", "internal", "sepa_lump")]
    deadlines = [dict(what="Zuwendungsbestätigungen für die Spenden 2026 ausstellen", until="2027-01-31", why="Spenden "
                      + ", ".join(de(m["amount"]) for m in MONEY if m["kind"] == "spende" and m["date"] <= cut))]
    if cut >= D("2026-10-10"):
        deadlines.append(dict(what="Kündigung 1222 Kühn zum 31.12.2026 bestätigen", until="2026-12-31", why=""))
    return dict(payables=payables_at(cut), mails_waiting=waiting, risks=risks, not_risks=not_risks,
                not_receipts=not_receipts, deadlines=deadlines,
                not_unbilled=[dict(id=h["no"], why="kostenlos" if h["free"] else f"berechnet mit {h['inv']}, Liste nicht nachgetragen"
                                   if not h["listed_invoice"] else "noch nicht stattgefunden")
                              for h in HALL if h["free"] or not h["listed_invoice"] or (h["date"] > cut)] +
                             [dict(id="SV-2026-06", why="Sachsponsoring, keine Rechnung"),
                              dict(id="Beiträge", why="Mitgliedsbeiträge, Kurs- und Campgebühren, Pacht werden nie berechnet: "
                                                      "geschuldet nach Beitragsordnung, Anmeldung oder Pachtvertrag")],
                same_name=[dict(a="1102", b="1609", why="zwei Michael Schröder")],
                payer_is_other=[dict(konto="1405", payer="Selin Yilmaz"), dict(konto="1371+1372", payer="Thomas Becker"),
                                dict(konto="1444", payer="Physiopraxis Kranz GbR")],
                lump_debits=[dict(file=r["file"], date=r["date"].isoformat(), posten=len(r["items"]),
                                  total=eur(r["money"]["amount"])) for r in RUNS if r["date"] <= cut])


def main(outdir: str) -> None:
    root = Path(outdir)
    root.mkdir(parents=True, exist_ok=True)
    build_all()
    build_mails()
    truth = dict(firm=f"{CLUB['name']} (Sportverein, Review 11)", deliveries=[])
    files = {}
    for dv in DELIV:
        files[dv["folder"]] = write_delivery(root, dv)
        t = truth_for(dv)
        t.update(extra_truth(dv))
        truth["deliveries"].append(t)
    check_traps(truth)
    (root / "truth.json").write_text(json.dumps(truth, ensure_ascii=False, indent=1), encoding="utf-8")
    key = dict(traps=TRAPS,
               members={str(n): dict(name=f"{p['first']} {p['last']}", joined=p["joined"].isoformat(),
                                     left=p["left"].isoformat() if p["left"] else None, group=[(str(a), g) for a, g in p["groups"]],
                                     depts=p["depts"], konto=p["acct"]) for n, p in sorted(PERSONS.items())},
               accounts={str(n): dict(how=a["how"], rhythm=a["rhythm"], holder=a["holder"], members=a["members"])
                         for n, a in sorted(ACCOUNTS.items())},
               claims={k: dict(konto=c["konto"], art=c["art"], period=c["period"], amount=eur(c["amount"]),
                               program=eur(c["sw"]), issued=c["issued"].isoformat(), due=c["due"].isoformat())
                       for k, c in sorted(CLAIMS.items())},
               money=[dict(acct=m["acct"], date=m["date"].isoformat(), amount=eur(m["amount"]), name=m["name"], vwz=m["vwz"],
                           kind=m["kind"], alloc=[(c["key"], eur(x), e.isoformat()) for c, x, e in m["alloc"]],
                           refunds=[(d.isoformat(), eur(a)) for d, a in m["refunds"]]) for m in MONEY if m["kind"] != "cost"],
               runs=[dict(file=r["file"], date=r["date"].isoformat(), items=[dict(konto=x["a"]["nr"], amount=eur(x["amount"]),
                                                                                 claims=[c["key"] for c in x["claims"]],
                                                                                 returned=x.get("returned", None) and
                                                                                 x["returned"].isoformat())
                                                                            for x in r["items"]]) for r in RUNS],
               planted=dict(course=COURSE_UNPAID, camp=CAMP_PLANT, january_return=JAN_RETURN), files=files)
    (root / "answer_key.json").write_text(json.dumps(key, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    for d in truth["deliveries"]:
        print(d["folder"], d["today"], "offen:", len(d["open"]), d["open_total"], "überfällig:", len(d["overdue"]),
              "nicht berechnet:", d["unbilled"], "Geld ohne Rechnung:", d["receipts"], "nach Art:", d["open_by_kind"])


TRAPS: list[dict] = []


def check_traps(truth: dict):
    """The header promises these; if a change breaks one, the generator says so."""
    l1, l2 = truth["deliveries"]
    o1, o2 = l1["open"], l2["open"]
    TRAPS.clear()

    def trap(code, text, ok):
        assert ok, (code, text)
        TRAPS.append(dict(id=code, text=text))
    trap("V01", "1123 Rücklastschrift Q3, Beitrag überwiesen, Gebühr offen", o1.get("1123 Rücklastschriftgebühr 07/2026") == 3.0
         and "1123 Beitrag Q3/2026" not in o1 and o2.get("1123 Rücklastschriftgebühr 07/2026") == 3.0)
    trap("V02", "1207 Familie: Rücklastschrift AC04, neue IBAN per Mail, mit Q4 nachgezogen",
         o1.get("1207 Beitrag Q3/2026") == 114.0 and o1.get("1207 Rücklastschriftgebühr 07/2026") == 3.0
         and not [k for k in o2 if k.startswith("1207")])
    trap("V03", "1356 Widerspruch MD06 nach Wochen, Kündigung verspätet: Q3 geschuldet, kein Q4",
         o1.get("1356 Beitrag Q3/2026") == 51.0 and o2.get("1356 Beitrag Q3/2026") == 51.0 and "1356 Beitrag Q4/2026" not in o2
         and not [k for k in o1 if k.startswith("1356 Rücklast")])
    trap("V04", "1288 ausgetreten 30.06., Q3 trotzdem eingezogen, erstattet: keine Forderung, kein Geld ohne Rechnung",
         not [k for k in o1 if k.startswith("1288")] and CLAIMS["1288 Beitrag Q3/2026"]["sw"] == 4800)
    trap("V05", "1094 ausgetreten 30.06., Dauerauftrag läuft weiter: 42,00 Geld ohne Rechnung (L1), erstattet 07.10.",
         42.0 in l1["receipts"] and 42.0 not in l2["receipts"])
    trap("V05b", "1530 ausgetreten 30.06., monatlicher Dauerauftrag 9,00: drei Eingänge ohne Forderung (L1), erstattet 14.10.",
         l1["receipts"].count(9.0) == 3 and 9.0 not in l2["receipts"])
    trap("V06", "1462 Lastschrift und Überweisung Q3: L1 72,00 Geld ohne Rechnung, L2 mit Q4 verrechnet",
         72.0 in l1["receipts"] and "1462 Beitrag Q4/2026" not in o2 and 72.0 not in l2["receipts"])
    trap("V07", "1311 wird 18, Programm stellt die Gruppe zu spät um: Q2 8,00 und Q3 30,00 offen",
         o1.get("1311 Beitrag Q2/2026") == 8.0 and o1.get("1311 Beitrag Q3/2026") == 30.0 and o2.get("1311 Beitrag Q3/2026") == 30.0
         and "1311 Beitrag Q4/2026" not in o2)
    trap("V09", "1150 Dauerauftrag mit altem Betrag: Q3 6,00 (L1); nach § 366 Q4 12,00 (L2)",
         o1.get("1150 Beitrag Q3/2026") == 6.0 and o2.get("1150 Beitrag Q4/2026") == 12.0 and "1150 Beitrag Q3/2026" not in o2)
    diffs = [k for k in o1 if "Beitragsdifferenz" in k]
    trap("V10", "Jahreszahler ohne Differenz nach der Beitragserhöhung", [k.split()[0] for k in diffs] == [
        "1053", "1061", "1309", "1415", "1425", "1426", "1492", "1513", "1587", "1635"] and all(k in o2 for k in diffs))
    trap("V28c", "spät und nie bezahlte Kursgebühren", COURSE_UNPAID["late_member"] == 1463 and "1463 Kursgebühr Herbst 2026" in o1
         and "1463 Kursgebühr Herbst 2026" not in o2 and o2.get("9054 Kursgebühr Herbst 2026") == 60.0)
    trap("V32b", "Absage Camp", CAMP_PLANT == dict(never=9069, twice=9065, cancel=1385))
    trap("V11", "Vater zahlt für Lena und Jonas Becker in einer Überweisung", not [k for k in o1 if k.startswith(("1371", "1372"))])
    trap("V12", "1188 zahlt Q3 und Q4 auf einmal: Q4 im Voraus, kein Geld ohne Rechnung", not [k for k in o2 if k.startswith("1188")]
         and 84.0 not in l1["receipts"])
    trap("V13", "1240 zahlt Q3 erst am 29.09.", o1.get("1240 Beitrag Q3/2026") == 42.0 and "1240 Beitrag Q3/2026" not in o2)
    trap("V14", "1266 Rückstand seit Q4/2025, gestrichen zum 30.09., fehlt im Export L2",
         [k for k in o1 if k.startswith("1266")] == ["1266 Beitrag Q2/2026", "1266 Beitrag Q3/2026", "1266 Beitrag Q4/2025"]
         and [k for k in o2 if k.startswith("1266")] == ["1266 Beitrag Q2/2026", "1266 Beitrag Q3/2026", "1266 Beitrag Q4/2025"])
    trap("V15", "1333 zahlt Q3 in Teilen", o1.get("1333 Beitrag Q3/2026") == 12.0 and "1333 Beitrag Q3/2026" not in o2)
    trap("V16", "1405 Mutter mit anderem Namen zahlt", not [k for k in o1 if k.startswith("1405")])
    trap("V17", "1517 schreibt 1571, 1571 zahlt Q3 spät", not [k for k in o1 if k.startswith("1517")]
         and o1.get("1571 Beitrag Q3/2026") == 21.0 and "1571 Beitrag Q3/2026" not in o2)
    trap("V20", "1061 Barzahler war nicht da", o2.get("1061 Beitrag 2026") == 144.0)
    trap("V21", "Ehrenmitglieder beitragsfrei", not [k for k in CLAIMS if k.startswith(("1007 ", "1012 ", "1019 "))])
    trap("V23", "1648 Aufnahmegebühr nicht gezahlt", o1.get("1648 Aufnahmegebühr") == 30.0 and o2.get("1648 Aufnahmegebühr") == 30.0)
    trap("V24", "1652 neu ab 01.10., noch nichts gezahlt", o2.get("1652 Beitrag Q4/2026") == 42.0 and o2.get("1652 Aufnahmegebühr") == 30.0)
    trap("V26", "1584 Rücklastschrift Q4", o2.get("1584 Beitrag Q4/2026") == 51.0 and o2.get("1584 Rücklastschriftgebühr 10/2026") == 3.0)
    sepa_courses = [k for k in o1 if "Kursgebühr Herbst" in k and k not in l1["overdue"]]
    trap("V28", "Kursgebühren der Lastschriftzahler erst am 15.10. fällig: offen, nicht überfällig (L1), eingezogen (L2)",
         len(sepa_courses) >= 15 and not [k for k in sepa_courses if k in o2 and not k.startswith("1419")])
    trap("V28b", "1419 Kursgebühr-Lastschrift zurück", o2.get("1419 Kursgebühr Herbst 2026") == 45.0
         and o2.get("1419 Rücklastschriftgebühr 10/2026") == 3.0)
    trap("V29", "Hollweg zahlt vor der Anmeldung in der Liste: L1 Geld ohne Rechnung, L2 bezahlt",
         70.0 in l1["receipts"] and "9029 Kursgebühr Herbst 2026" not in o2 and 70.0 not in l2["receipts"])
    trap("V30", "Nichtmitglied zahlt Frühjahrskurs nie", o2.get(f"{COURSE_UNPAID['spring_never']} Kursgebühr Frühjahr 2026") == 60.0)
    trap("V31", "Pilates entfällt: keine Forderung", not [k for k in CLAIMS if CLAIMS[k]["kind"] == "kurs" and "Pilates" in CLAIMS[k]["label"]])
    trap("V32", "Feriencamp: einer nie bezahlt, einer doppelt, eine Absage mit Stornogebühr",
         o2.get(f"{CAMP_PLANT['never']} Feriencamp 2026") == 169.0 and 169.0 in l1["receipts"] and 169.0 not in l2["receipts"]
         and f"{CAMP_PLANT['cancel']} Feriencamp 2026" not in o1)
    trap("V34", "eigene Rechnungen: netto gezahlt (2026-003), spät (2026-019), reklamiert (2026-027)",
         o1.get("2026-003") == 228.0 and o2.get("2026-003") == 228.0 and o1.get("2026-019") == 1785.0 and "2026-019" not in o2
         and o2.get("2026-027") == 285.6)
    trap("V35", "Sponsoringvertrag ohne Rechnung", "SV-2026-07" in l1["unbilled"] and "SV-2026-07" in l2["unbilled"])
    hb = {h["date"].isoformat(): h["no"] for h in HALL}
    trap("V36", "Hallennutzung 13.09. erst im Oktober berechnet, 17.10. nicht berechnet, 29.08. berechnet aber Liste leer",
         l1["unbilled"] == ["SV-2026-07", hb["2026-09-13"]] and l2["unbilled"] == ["SV-2026-07", hb["2026-10-17"]])
    trap("V37", "Pacht August gemindert", o1.get("9003 Pacht 08/2026") == 411.5 and o2.get("9003 Pacht 08/2026") == 411.5
         and not [k for k in o2 if k.startswith("9003") and k != "9003 Pacht 08/2026"])
    trap("V47", "unbekannter Zahler 25,00", 25.0 in l1["receipts"] and 25.0 in l2["receipts"])
    trap("V27", "1077 zahlt das Jahr zweimal", 144.0 in l1["receipts"] and 144.0 not in l2["receipts"])
    trap("V22", "1180 überweist Q3 aufs Tennis-Konto, umgebucht", "1180 Beitrag Q3/2026" not in o1)
    trap("V27b", "1598 zahlt Oktober doppelt", l2["receipts"] == [14.0, 25.0])
    trap("R1", "L1 Geld ohne Rechnung genau", l1["receipts"] == [9.0, 9.0, 9.0, 25.0, 42.0, 70.0, 72.0, 144.0, 169.0])
    trap("V41", "zu bezahlen", [p["invoice"] for p in l1["payables"]] == ["26-4471", "GL-2026-0825"]
         and [p["invoice"] for p in l2["payables"]] == ["5.0226.004704", "GL-2026-0926", "TA-26-1187", "TS-2026-09"])
    trap("V08", "1003: Januar-Einzug zurück (AC01), im Februar mit Gebühr nachgeholt",
         JAN_RETURN == [1003] and not [k for k in o1 if k.startswith("1003 ")]
         and any(x["a"]["nr"] == 1003 for r in RUNS if r["date"] == D("2026-02-16") for x in r["items"]))
    trap("V25", "1514 ermäßigt ab Q4", CLAIMS["1514 Beitrag Q4/2026"]["amount"] == 2700)
    trap("V33", "Arbeitsstunden: Sollstellung zum 01.10.", not [k for k in o1 if "Arbeitsstunden" in k]
         and [k for k in o2 if "Arbeitsstunden" in k])
    trap("V42", "Betrug in L2", len(l2["risks"]) == 2 and not l1["risks"])


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit("Aufruf: python3 verein.py OUTDIR")
    main(sys.argv[1])
