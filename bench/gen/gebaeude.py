#!/usr/bin/env python3
"""Ostermeier Gebäudedienste GmbH, Hildesheim – eine erfundene Gebäudereinigung (gewerbliche
Unterhaltsreinigung, 26 Leute, 50 Objekte, 47 Kunden) mit zwei Lieferungen, so wie die Ablage einer
solchen Firma wirklich aussieht.

    python3 gen_firm.py OUTDIR  ->  OUTDIR/lieferung1/   Stand Do 17.09.2026 (Bank bis 16.09.)
                                    OUTDIR/lieferung2/   Stand Do 29.10.2026 (Bank bis 28.10.), kompletter
                                                         neuer Ordnerstand, gleiche Dateinamen
                                    OUTDIR/truth.json    Format des Prüfstands (bench/one.py)
                                    OUTDIR/answer_key.json

Fester Seed; nur Standardbibliothek + openpyxl + reportlab.

Die Dateien: Objektliste_Vertraege.xlsx (Abschnittszeilen, Summenzeile, Blatt "beendet"),
Kunden_Export.csv (cp1252, aus der Faktura), Rechnungsausgangsbuch_2026.xlsx (Status "laut Datei",
nachgepflegt bis zum letzten Abgleich), Sonderauftraege_2026.xlsx, Angebote_2026.xlsx, Mitarbeiter.xlsx,
Bank/Sparkasse_Umsaetze_2026.csv (CAMT-CSV mit Vorspann, neueste zuerst, ab 01.01. – also auch Zahlungen
auf Rechnungen von 2025, die im Buch 2026 nicht stehen), Bank/SEPA-LS_*.xml (pain.008 je Sammellastschrift),
Stunden/Stundennachweis_2026-MM.xlsx (ein Blatt je Mitarbeiterin), Eingangsrechnungen/*.pdf, Mails/*.eml,
Stadt_XRechnung/*.xml (L2).

ANSWER KEY – die Fallen (die Zahlen stehen in truth.json / answer_key.json)
K01 Vertragsmonat ohne Rechnung: OB-107 Coworking Altstadt, Vertrag ab 01.07.2026 (Objektliste), die
    Dauerrechnung wurde erst im August angelegt – Juli nie berechnet. L1 und L2: nicht berechnet "OB-107".
K02 Vertragsmonat ohne Rechnung: OB-132 Grundschule Am Lindenhof (Stadt). Die Stadt will ab Leistungsmonat
    September nur noch XRechnung über das Portal (Mail 14.09.); die Septemberrechnung wurde nie geschrieben.
    L2: nicht berechnet "OB-132".
K03 Preisanpassung im Buch nicht nachgezogen: OB-102 Brückner, laut Objektliste ab 01.07. 725,00 statt
    690,00 netto; das Buch schreibt Juli–September weiter 690,00 (je 41,65 brutto zu wenig). Keine offene
    Rechnung, aber Geld, das fehlt ("underbilled" in truth.json).
K04 Rücklastschrift mit Gebühr in derselben Zeile (Auslagenersatz 3,00): PowerHouse, Augustrechnung aus der
    Sammellastschrift vom 10.09., zurück am 14.09. (AM04). Das Buch führt sie als "bezahlt" (LS). L1: offen
    1.011,50, überfällig. L2: am 24.09. überwiesen -> bezahlt.
K05 Rücklastschrift MD06 (Widerspruch) ohne Gebühr in der Zeile, Gebühr 3,50 am Folgetag als eigene Zeile:
    Notariat Rehberg, Septemberrechnung (Einzug 12.10., zurück 14.10.); Buch "bezahlt". L2: offen, überfällig.
K06 Kündigung zum Monatsende: OB-105 Krämer zum 31.08.2026 (Mail 20.05.); danach keine Rechnung – das ist
    richtig und keine Falle für "nicht berechnet". L2: Vertrag steht im Blatt "beendet".
K07 Doppelzahlung: Lenz überweist die Augustrechnung am 03.09. und am 08.09. L1: Geld ohne Rechnung 470,05.
    L2: Lenz bittet um Erstattung (Mail 29.09.), Rücküberweisung 30.09. -> nichts mehr offen.
K08 Doppelzahlung: MVZ zahlt die Septemberrechnung OB-120 in der Sammelzahlung vom 09.10. und am 15.10. noch
    einmal einzeln. L2: Geld ohne Rechnung 2.499,00.
K09 Zahlungen ohne Nummer: Kaya, Kreativraum, Dr. Schäfer (Sarstedt), WEG Gartenstraße 5, Kita (L2,
    Grundreinigung), Kirchengemeinde (Quartal), Stadtkasse (nur Kassenzeichen + "Rechnung vom ...").
K10 Sammelüberweisung einer Hausverwaltung (Kröger & Partner, 4 Objekte) mit auf 140 Zeichen abgeschnittenem
    Verwendungszweck: die vierte Nummer fehlt (Augustrechnungen, 10.09.). Alle vier bezahlt.
K11 Sammelüberweisung 3 von 4 mit Zahlungsavis per Mail (09.10.), Haus Godehard wegen Reklamation (Mail
    08.10.) einbehalten. L2: Godehard-Septemberrechnung offen und überfällig.
K12 Gutschrift wegen Reklamation: Okonkwo (keine Reinigung 03.–07.08., Mails 12.08.), Gutschrift über 25 %
    der Augustpauschale (-142,80), Kunde zahlt Rechnung minus Gutschrift (428,40). Beide erledigt.
K13 Kunde doppelt im Stamm: "Physiotherapie am Markt GbR" (10015, Lastschrift) und "Physio am Markt
    Brinkmann & Vogel GbR" (10041, Überweisung), gleiche Adresse, Telefon, E-Mail, IBAN. Seit Juni gehen die
    Rechnungen von OB-115 an 10041 (die Objektliste nennt weiter 10015).
K14 Zwei Kunden gleichen Namens: "Zahnarztpraxis Dr. Schäfer" Hildesheim (10012, zahlt mit Nummer) und
    Sarstedt (10013, zahlt ohne Nummer). Nicht zusammenführen.
K15 Lieferantenrechnung mit Skonto: Nordhaus 2 % / 10 Tage. L1: 2026-32410 (Skonto bis 20.09.), L2: 2026-34102
    (Skonto bis 31.10.). Frühere mit Skonto bezahlt.
K16 Dauerauftrag mit altem Betrag nach Preisanpassung: Hoffmann zahlt jeden 15. weiter 535,50 statt 562,28;
    je Rechnung seit Juli 26,78 offen (Zuordnung Monat für Monat, wie das Buch sie führt; das Buch sagt
    "bezahlt"). L1: Juli + August je 26,78, L2: Juli–September je 26,78, alle überfällig.
K17 Skonto zu Unrecht: Autohaus Wendt hat 2 % / 8 Tage; die Augustrechnung zahlt es am 15.09. (Tag 15) mit 2 %
    Abzug. 26,66 bleiben offen (L1 nicht fällig, netto 30 Tage; L2 überfällig). Pünktliche Skontozahlungen
    sind vollständig bezahlt.
K18 Anzahlung ohne Rechnung: Dr. Behrens zahlt am 15.09. 1.500,00 "Anzahlung Bauendreinigung A-26-019". L1:
    Geld ohne Rechnung 1.500,00. L2: Schlussrechnung 06.10. "abzgl. Anzahlung", Rest 1.951,00 am 16.10.
    bezahlt -> nichts offen.
K19 Fertig, nicht berechnet (Sonderaufträge): SA-26-024 Kita Grundreinigung (L1; in L2 berechnet),
    SA-26-027 Autohaus Glasreinigung (L1 und L2), SA-26-033 Kröger Glasreinigung (L2), SA-26-032 Hörakustik
    Grundreinigung (L2, schwer: Liste sagt "geplant", erledigt laut Stundennachweis 15.10. und Dankesmail).
K20 Berechnet, aber Auftragsliste nicht nachgetragen: SA-26-029 (Rechnung 11.09. nennt "SA-26-029") – nicht
    "nicht berechnet".
K21 Nachreinigung kostenlos (SA-26-030, Preis 0,00) – nicht "nicht berechnet".
K22 Zahlendreher: Pension Domblick überweist die Augustrechnung mit vertauschten Ziffern; die genannte Nummer
    gehört einem anderen Kunden mit anderem Betrag.
K23 Jahreswechsel: Die Bank beginnt am 01.01.2026; im Januar/Februar kommen Zahlungen auf Rechnungen von
    Dezember 2025 (nicht im Buch). Die Stadtkasse zahlt jede Rechnung ~35 Tage später mit "Rechnung vom
    TT.MM.JJJJ" ohne Nummer – wer nur nach Betrag geht, verschiebt alle Monate um eins und hält die offene
    Augustrechnung (L1) für bezahlt. Bildungswerk zahlt mit der (unbekannten) Nummer 2025-05xx.
K24 WEG-Konten: Fünf WEG-Kunden c/o Hausverwaltung Brandes (gleiche Adresse, gleiche Mail) – fünf Kunden,
    keine Dubletten; jede WEG zahlt von ihrem eigenen Konto.
K25 Säumiger Kunde: Tanzschule zahlt seit Juni nicht (Erinnerung 20.08., Bitte um Raten 01.09.); L2 kommt
    "Rate 1 Rückstand" 357,00 ohne Nummer -> auf die älteste (Juni).
K26 Storno: SA-26-005 zuerst an den falschen Kunden berechnet, storniert, neu an den richtigen.
K27 Kunde ist auch Lieferant: Steuerberatung Engel (Lastschrift-Kunde OB-145) schickt monatlich ihre
    Rechnung für Lohn-/Finanzbuchhaltung (PDF) – Verbindlichkeit, keine Forderung.
K28 Subunternehmer mit § 13b UStG (Petrovic): Rechnung ohne Umsatzsteuer ist richtig.
K29 Lieferantenrechnung als Kopie/Zweitschrift (Nordhaus 2026-31877 KOPIE) und Rechnungs-PDF zugleich als
    Mail-Anhang: nicht zweimal bezahlen.
K30 Betrug (L2): Mail von nordhaus-hygiene.co (echt: .de) mit "neuer Bankverbindung" (LT-IBAN) und
    "korrigierter" Rechnung 2026-34102.
K31 Kündigung per Mail (L2, Neuland zum 31.12.), noch nicht in der Objektliste; Rechnungen laufen bis Dezember.
K32 Eigene XRechnung (L2) für die Stadt (Augustrechnung nachgereicht) – eigene Ausgangsrechnung, keine
    Lieferantenrechnung.
K33 Neuer Vertrag ab 01.10. (OB-151 Albers) – noch nicht fällig. Albers überweist am 02.10. "Vorauszahlung
    Oktober" 499,80 -> L2 Geld ohne Rechnung.
K34 Genossenschaft zahlt zwei Monate je Überweisung, Nummern mit Schrägstrich ("Rg. 2026/0377 u. 2026/0410").
K35 Erstattung der Krankenkasse (AOK U1) – Geld, das keine Kundenrechnung bezahlt, aber auch keine Aufgabe ist.
K36 Kirchengemeinde zahlt quartalsweise ohne Nummer. L1: Juli und August offen und überfällig; L2 bezahlt.
K37 Bildungswerk zahlt rund drei Wochen nach Fälligkeit; Bürogemeinschaft Hohnsen ein paar Tage zu spät.
K38 PowerHouse wechselt die Bank (neues Mandat, neue IBAN) – die Septemberlastschrift geht vom neuen Konto.
K39 Mails, die auf Antwort warten: Anfragen (16.09., 28.10.), Raten-Bitte (01.09.), Stadt/XRechnung (14.09.),
    Kündigung Neuland (06.10.), Reklamation Kröger (08.10.), Widerspruch Rehberg (14.10.), Auftrag Grund-
    reinigung Dr. Schäfer am 07.11. (21.10., noch nicht in der Auftragsliste).
K40 Angebote zum Nachfassen: L1 A-26-021 (15.09.), L2 A-26-022 (05.10.) und A-26-023 (27.10.).
"""
from __future__ import annotations

import calendar
import hashlib
import json
import random
import sys
from datetime import date, datetime, timedelta, timezone
from email.message import EmailMessage
from email.utils import format_datetime
from pathlib import Path
from xml.sax.saxutils import escape as xesc

import openpyxl
from openpyxl.styles import Alignment, Font, PatternFill
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.pdfgen import canvas

SEED = 20260917


def rr(*key) -> random.Random:
    """A random generator that depends only on the key (stable when other parts change)."""
    h = hashlib.sha256(("|".join(map(str, key)) + f"|{SEED}").encode()).hexdigest()
    return random.Random(int(h[:16], 16))


def D(s: str) -> date:
    return date.fromisoformat(s)


# ------------------------------------------------------------------ calendar
HOL = {D(x) for x in ("2025-12-25", "2025-12-26", "2026-01-01", "2026-04-03", "2026-04-06", "2026-05-01",
                      "2026-05-14", "2026-05-25", "2026-10-03", "2026-10-31", "2026-12-25", "2026-12-26")}
MONATE = ["Januar", "Februar", "März", "April", "Mai", "Juni", "Juli", "August", "September", "Oktober",
          "November", "Dezember"]
WT = ["Mo", "Di", "Mi", "Do", "Fr", "Sa", "So"]


def is_wd(d: date) -> bool:
    return d.weekday() < 5 and d not in HOL


def next_wd(d: date) -> date:
    while not is_wd(d):
        d += timedelta(days=1)
    return d


def last_wd(y: int, m: int) -> date:
    d = date(y, m, calendar.monthrange(y, m)[1])
    while not is_wd(d):
        d -= timedelta(days=1)
    return d


def month_end(y: int, m: int) -> date:
    return date(y, m, calendar.monthrange(y, m)[1])


def third_last_wd(y: int, m: int) -> date:
    d, n = month_end(y, m), 0
    while True:
        if is_wd(d):
            n += 1
            if n == 3:
                return d
        d -= timedelta(days=1)


def coll_date(y: int, m: int) -> date:
    """SEPA collection for the invoices of month m: the 10th of the next month (next bank day)."""
    y2, m2 = (y + 1, 1) if m == 12 else (y, m + 1)
    return next_wd(date(y2, m2, 10))


def dde(d: date) -> str:
    return d.strftime("%d.%m.%Y")


def dshort(d: date) -> str:
    return d.strftime("%d.%m.%y")


# ------------------------------------------------------------------ money (cents)
def vat19(net: int) -> int:
    s = 1 if net >= 0 else -1
    return s * ((abs(net) * 19 + 50) // 100)


def de(c: int) -> str:
    s = f"{abs(c) // 100:,}".replace(",", ".") + f",{abs(c) % 100:02d}"
    return ("-" if c < 0 else "") + s


def csvamt(c: int) -> str:
    return ("-" if c < 0 else "") + f"{abs(c) // 100},{abs(c) % 100:02d}"


def xamt(c: int) -> str:
    return f"{c // 100}.{c % 100:02d}"


def eur(c: int) -> float:
    return round(c / 100, 2)


def pct(c: int, p: float) -> int:
    return int(round(c * p / 100))


# ------------------------------------------------------------------ banks
BANKS = {
    "SPK": ("25950130", "NOLADE21HIK", "Sparkasse Hildesheim Goslar Peine"),
    "VB": ("25193331", "GENODEF1PAT", "Volksbank eG Hildesheim-Lehrte-Pattensen"),
    "COM": ("25940033", "COBADEFFXXX", "Commerzbank"),
    "DB": ("25970074", "DEUTDEDB259", "Deutsche Bank"),
    "PB": ("25010030", "PBNKDEFFXXX", "Postbank"),
    "APO": ("30060601", "DAAEDEDDXXX", "Deutsche Apotheker- und Ärztebank"),
    "EB": ("52060410", "GENODEF1EK1", "Evangelische Bank"),
    "DKB": ("12030000", "BYLADEM1001", "Deutsche Kreditbank"),
    "SPKH": ("25050180", "SPKHDE2HXXX", "Sparkasse Hannover"),
    "HVB": ("25020600", "HYVEDEMM250", "UniCredit Bank – HypoVereinsbank"),
}


def iban(blz: str, kto: int) -> str:
    bban = f"{blz}{kto:010d}"
    chk = 98 - int(bban + "131400") % 97
    return f"DE{chk:02d}{bban}"


def acct(bank: str, *key) -> tuple[str, str]:
    blz, bic, _ = BANKS[bank]
    kto = rr("kto", *key).randrange(10 ** 8, 10 ** 10)
    return iban(blz, kto), bic


def fmt_iban(i: str) -> str:
    return " ".join(i[k:k + 4] for k in range(0, len(i), 4))


def creditor_id(nat: str) -> str:
    return f"DE{98 - int(nat + '131400') % 97:02d}ZZZ{nat}"


FIRM = dict(name="Ostermeier Gebäudedienste GmbH", short="Ostermeier", street="Bavenstedter Straße 48",
            plz="31135", city="Hildesheim", phone="05121 99876-0", mail="info@ostermeier-gd.de",
            buch="buchhaltung@ostermeier-gd.de", gf="Katrin Ostermeier", ustid="DE312456789",
            stnr="30/210/45678", hrb="HRB 203117, Amtsgericht Hildesheim")
FIRM["iban"] = iban("25950130", 912345678)
FIRM["bic"] = "NOLADE21HIK"
FIRM["ci"] = creditor_id("00000845123")
SEPA_FIRM = "Ostermeier Gebaeudedienste GmbH"

# deliveries: the day the owner drops the folder; the bank export ends the day before; the bookkeeper
# reconciled the book on 'recon' (status "laut Datei" reflects payments up to then)
DELIV = [dict(n=1, folder="lieferung1", today=D("2026-09-17"), cut=D("2026-09-16"), recon=D("2026-09-03"),
              obj_stand=D("2026-09-15")),
         dict(n=2, folder="lieferung2", today=D("2026-10-29"), cut=D("2026-10-28"), recon=D("2026-10-05"),
              obj_stand=D("2026-10-27"))]

# ------------------------------------------------------------------ customers
CUSTOMERS: dict[str, dict] = {}


def C(kd, name, zusatz, contact, street, plz, city, phone, email, pay, bank, payer, profile, terms=14,
      skonto=None, since="2019-01-01", leitweg="", ustid="", note="", from_l2=False, same_iban_as=None):
    if same_iban_as:
        ib, bic = CUSTOMERS[same_iban_as]["iban"], CUSTOMERS[same_iban_as]["bic"]
    else:
        ib, bic = acct(bank, kd)
    CUSTOMERS[kd] = dict(kd=kd, name=name, zusatz=zusatz, contact=contact, street=street, plz=plz, city=city,
                         phone=phone, email=email, pay=pay, bank=bank, bankname=BANKS[bank][2], iban=ib, bic=bic,
                         payer=payer, profile=profile, terms=terms, skonto=skonto, since=D(since),
                         mandate=(f"OST-{kd}-01" if pay == "Lastschrift" else ""), leitweg=leitweg, ustid=ustid,
                         note=note, from_l2=from_l2)


C("10001", "Steuerkanzlei Hoffmann & Partner mbB", "", "Frau Dr. Ulrike Hoffmann", "Zingel 12", "31134", "Hildesheim",
  "05121 13450", "kanzlei@hoffmann-partner-stb.de", "Überweisung", "VB", "HOFFMANN UND PARTNER MBB STEUERBERATER",
  "dauerauftrag", since="2019-03-01")
C("10002", "Rechtsanwälte Brückner & Sohn", "", "Herr RA Klaus Brückner", "Almsstraße 28", "31134", "Hildesheim",
  "05121/304481", "info@brueckner-anwaelte.de", "Überweisung", "SPK", "RAE BRUECKNER UND SOHN", "ue_num",
  since="2018-09-01")
C("10003", "Architekturbüro Lenz", "Dipl.-Ing. Tobias Lenz", "Herr Lenz", "Kardinal-Bertram-Straße 9", "31134",
  "Hildesheim", "05121 280610", "buero@lenz-architektur.de", "Überweisung", "DKB", "TOBIAS LENZ ARCHITEKTURBUERO",
  "ue_num", since="2021-05-01")
C("10004", "IT-Systemhaus Neuland GmbH", "", "Frau Sandra Petersen (Office)", "Daimlerring 5", "31135", "Hildesheim",
  "05121 70900", "office@neuland-it.de", "Lastschrift", "COM", "NEULAND IT-SYSTEMHAUS GMBH", "ls", since="2017-01-01",
  ustid="DE284113920")
C("10005", "Versicherungsbüro Krämer", "Generalagentur", "Herr Jürgen Krämer", "Schuhstraße 31", "31134",
  "Hildesheim", "05121 37712", "j.kraemer@kraemer-versicherungen.de", "Überweisung", "SPK", "JUERGEN KRAEMER",
  "ue_num", since="2020-02-01", note="Vertrag gekündigt zum 31.08.2026")
C("10006", "Ingenieurbüro Sander & Kühn", "", "Frau Kühn", "Senator-Braun-Allee 33", "31135", "Hildesheim",
  "05121 51022", "info@sander-kuehn.de", "Lastschrift", "VB", "INGENIEURBUERO SANDER UND KUEHN", "ls",
  since="2022-04-01")
C("10007", "Coworking Altstadt UG (haftungsbeschränkt)", "", "Herr Malte Rieck", "Andreasplatz 2", "31134",
  "Hildesheim", "0176 44132290", "hallo@coworking-altstadt.de", "Überweisung", "DKB", "COWORKING ALTSTADT UG",
  "ue_num", since="2026-06-20")
C("10008", "Immobilien Fahrenholz", "Inh. Petra Fahrenholz", "Frau Fahrenholz", "Bahnhofsallee 21", "31134",
  "Hildesheim", "05121 993140", "pf@fahrenholz-immobilien.de", "Lastschrift", "SPK", "PETRA FAHRENHOLZ", "ls",
  since="2023-01-01")
C("10009", "Werbeagentur Kreativraum GmbH", "", "Frau Nadine Ost (Buchhaltung)", "Goschenstraße 61", "31134",
  "Hildesheim", "05121 87663", "buchhaltung@kreativraum-hi.de", "Überweisung", "VB", "KREATIVRAUM GMBH",
  "ue_nonum", since="2020-10-01")
C("10010", "Bildungswerk Innerste e.V.", "", "Herr Bernd Wolters", "Steuerwalder Straße 60", "31137", "Hildesheim",
  "05121 76200", "verwaltung@bildungswerk-innerste.de", "Überweisung", "SPK", "BILDUNGSWERK INNERSTE E.V.",
  "ue_late", since="2019-08-01")
C("10011", "Zahnarztpraxis Dr. Okonkwo", "Dr. med. dent. Chidi Okonkwo", "Frau Claudia Weiß (Praxismanagement)",
  "Bischof-Janssen-Straße 4", "31134", "Hildesheim", "05121 13838", "praxis@zahnarzt-okonkwo.de", "Überweisung",
  "APO", "DR. CHIDI OKONKWO", "ue_num", since="2021-01-01")
C("10012", "Zahnarztpraxis Dr. Schäfer", "Dr. med. dent. Martin Schäfer", "Herr Dr. Schäfer", "Almsstraße 15",
  "31134", "Hildesheim", "05121 32525", "info@zahnarzt-schaefer-hildesheim.de", "Überweisung", "APO",
  "DR. MARTIN SCHAEFER", "ue_num", since="2020-06-01")
C("10013", "Zahnarztpraxis Dr. Schäfer", "Dr. med. dent. Julia Schäfer", "Frau Dr. Schäfer", "Holztorstraße 7",
  "31157", "Sarstedt", "05066 60417", "praxis@dr-julia-schaefer.de", "Überweisung", "SPKH",
  "DR. MED. DENT. JULIA SCHAEFER", "ue_nonum", since="2022-11-01")
C("10014", "Hausarztpraxis Dr. Yıldız & Kollegen", "", "Frau Bauer (Anmeldung)", "Peiner Straße 14", "31137",
  "Hildesheim", "05121 44040", "praxis@hausarzt-yildiz.de", "Lastschrift", "APO", "GEMEINSCHAFTSPRAXIS DR. YILDIZ",
  "ls", since="2018-04-01")
C("10015", "Physiotherapie am Markt GbR", "", "Frau Katja Brinkmann", "Markt 6", "31134", "Hildesheim", "05121 20606",
  "info@physio-am-markt.de", "Lastschrift", "SPK", "PHYSIOTHERAPIE AM MARKT", "ls", since="2021-09-01")
C("10016", "Tierarztpraxis Dr. Albers", "Dr. med. vet. Carsten Albers", "Herr Dr. Albers", "Ottostraße 70", "31137",
  "Hildesheim", "05121 51818", "praxis@tierarzt-albers.de", "Lastschrift", "VB", "DR. CARSTEN ALBERS", "ls",
  since="2026-09-12", from_l2=True)
C("10017", "Praxis für Ergotherapie Kaya", "Inh. Derya Kaya", "Frau Kaya", "Ostertor 3", "31134", "Hildesheim",
  "05121 912447", "kontakt@ergo-kaya.de", "Überweisung", "VB", "DERYA KAYA", "ue_nonum", since="2023-03-01")
C("10018", "Augenarztpraxis Dr. Lindqvist", "", "Frau Dr. Anna Lindqvist", "Hindenburgplatz 5", "31134",
  "Hildesheim", "05121 17272", "praxis@augen-lindqvist.de", "Lastschrift", "APO", "DR. ANNA LINDQVIST", "ls",
  since="2019-01-01")
C("10019", "MVZ Hildesheim Nord GmbH", "", "Herr Stefan Albrecht (Verwaltung)", "Senkingstraße 12", "31137",
  "Hildesheim", "05121 50800", "verwaltung@mvz-hildesheim-nord.de", "Überweisung", "DB", "MVZ HILDESHEIM NORD GMBH",
  "mvz", since="2020-01-01", ustid="DE301556712")
C("10020", "Kinderarztpraxis Dr. Behrens", "", "Frau Dr. Ines Behrens", "Lucienvörder Allee 2", "31141",
  "Hildesheim", "05121 26262", "info@kinderarzt-behrens.de", "Lastschrift", "APO", "DR. INES BEHRENS", "ls",
  since="2022-02-01")
for _kd, _weg, _payer, _prof, _since in (
        ("10021", "WEG Lindenstraße 12", "WEG LINDENSTR. 12 HILDESHEIM", "weg", "2016-05-01"),
        ("10022", "WEG Gartenstraße 5", "WEG GARTENSTRASSE 5", "weg_nonum", "2018-01-01"),
        ("10023", "WEG Am Wall 3", "WEG AM WALL 3", "weg", "2017-07-01"),
        ("10024", "WEG Moltkestraße 40", "WEG MOLTKESTR. 40", "weg", "2015-03-01"),
        ("10025", "WEG Kaiserstraße 17", "WEG KAISERSTRASSE 17 HI", "weg", "2018-06-01")):
    C(_kd, _weg, "c/o Hausverwaltung Brandes GmbH", "Herr Tim Brandes", "Schuhstraße 9", "31134", "Hildesheim",
      "05121 39900", "verwaltung@hv-brandes.de", "Überweisung", "SPK", _payer, _prof, since=_since)
C("10026", "Kröger & Partner Immobilienverwaltung GmbH", "", "Frau Melanie Kröger", "Hannoversche Straße 88",
  "31137", "Hildesheim", "05121 70880", "buchhaltung@kroeger-partner.de", "Überweisung", "COM",
  "KROEGER + PARTNER IMMOBILIENVERWALTUNG GMBH TREUHANDKONTO", "kroeger", since="2019-01-01")
C("10027", "Wohnungsbaugenossenschaft Innerste eG", "", "Herr Uwe Gerke (Technik)", "Moritzberger Weg 1", "31139",
  "Hildesheim", "05121 23040", "technik@wbg-innerste.de", "Überweisung", "VB",
  "WOHNUNGSBAUGENOSSENSCHAFT INNERSTE EG", "geno", terms=30, since="2014-01-01")
C("10028", "Stadt Hildesheim", "Fachbereich 65 – Gebäudemanagement", "Frau Sabine Kirchner", "Markt 3", "31134",
  "Hildesheim", "05121 301-0", "s.kirchner@stadt-hildesheim.de", "Überweisung", "SPK", "STADTKASSE HILDESHEIM",
  "stadt", terms=30, since="2024-08-01", leitweg="03254021-65000-17")
C("10029", "Ev.-luth. Kindertagesstätte Sonnenblume", "Träger: Ev.-luth. Kirchenkreis Hildesheim-Sarstedt",
  "Frau Heike Rust (Leitung)", "Elzer Straße 41", "31137", "Hildesheim", "05121 41780", "kita.sonnenblume@evlka-hi.de",
  "Überweisung", "EB", "EV.-LUTH. KIRCHENKREIS HILDESHEIM-SARSTEDT", "ue_num", since="2019-08-01")
C("10030", "Ambulanter Pflegedienst Lebenszeit GmbH", "", "Herr Kai Nowak", "Goslarsche Straße 55", "31134",
  "Hildesheim", "05121 66630", "info@pflegedienst-lebenszeit.de", "Lastschrift", "SPK", "PFLEGEDIENST LEBENSZEIT GMBH",
  "ls", since="2023-06-01")
C("10031", "Autohaus Wendt GmbH", "", "Herr Frank Wendt", "Porschestraße 10", "31135", "Hildesheim", "05121 94040",
  "rechnung@autohaus-wendt.de", "Überweisung", "COM", "AUTOHAUS WENDT GMBH", "skonto", terms=30, skonto=(2, 8),
  since="2018-03-01", ustid="DE115482771")
C("10032", "Fitnessstudio PowerHouse", "Inh. Sven Kowalski", "Herr Kowalski", "Cheruskerring 19", "31137",
  "Hildesheim", "05121 27799", "info@powerhouse-hildesheim.de", "Lastschrift", "PB", "SVEN KOWALSKI POWERHOUSE", "ls",
  since="2022-09-01")
C("10033", "Bäckerei Rosenthal", "Verwaltung und Backstube", "Frau Rosenthal", "Rosenthaler Straße 2", "31141",
  "Hildesheim", "05121 55011", "verwaltung@baeckerei-rosenthal.de", "Lastschrift", "VB", "BAECKEREI ROSENTHAL", "ls",
  since="2021-03-01")
C("10034", "Pension Domblick", "Inh. Familie Gerdes", "Frau Gerdes", "Domhof 22", "31134", "Hildesheim",
  "05121 15050", "gerdes@pension-domblick.de", "Überweisung", "SPK", "PENSION DOMBLICK GERDES", "ue_num",
  since="2020-05-01")
C("10035", "Möbelhaus Sievers KG", "", "Herr Sievers jun.", "Am Marienfriedhof 1", "31134", "Hildesheim",
  "05121 8800", "buchhaltung@moebel-sievers.de", "Lastschrift", "SPK", "MOEBELHAUS SIEVERS KG", "ls",
  since="2017-10-01")
C("10036", "Notariat Dr. Rehberg", "Dr. jur. Hans-Georg Rehberg, Notar", "Frau Kaiser (Büro)", "Wollenweberstraße 5",
  "31134", "Hildesheim", "05121 33030", "kanzlei@notar-rehberg.de", "Lastschrift", "DB", "DR. HANS-GEORG REHBERG",
  "ls", since="2019-04-01")
C("10037", "Logistik Nord-Süd GmbH", "", "Frau Elke Busch (Kreditorenbuchhaltung)", "Lerchenkamp 30", "31137",
  "Hildesheim", "05121 77700", "kreditoren@logistik-nord-sued.de", "Überweisung", "COM", "LOGISTIK NORD-SUED GMBH",
  "ue_num", since="2016-11-01", ustid="DE209337154")
C("10038", "Druckerei Hansen & Co. KG", "", "Herr Hansen", "Bavenstedter Straße 77", "31135", "Hildesheim",
  "05121 48210", "info@druckerei-hansen.de", "Lastschrift", "VB", "DRUCKEREI HANSEN UND CO KG", "ls",
  since="2020-02-01")
C("10039", "Tanzschule Rhythmus", "Inh. Marco Bellini", "Herr Bellini", "Kaiserstraße 50", "31134", "Hildesheim",
  "05121 93030", "info@tanzschule-rhythmus.de", "Überweisung", "PB", "MARCO BELLINI", "tanz", since="2022-01-01")
C("10040", "Steuerberatung Engel", "StB Christiane Engel", "Frau Engel", "Theaterstraße 6", "31141", "Hildesheim",
  "05121 26660", "kanzlei@stb-engel.de", "Lastschrift", "SPK", "CHRISTIANE ENGEL STEUERBERATERIN", "ls",
  since="2021-07-01", note="ist auch unsere Steuerberaterin (Lohn/Fibu)")
C("10041", "Physio am Markt Brinkmann & Vogel GbR", "", "Frau Brinkmann", "Markt 6", "31134", "Hildesheim",
  "05121-20606", "info@physio-am-markt.de", "Überweisung", "SPK", "PHYSIOTHERAPIE AM MARKT", "ue_num",
  since="2026-05-28", same_iban_as="10015")
C("10042", "Hörakustik Meyer", "Inh. Lars Meyer", "Herr Meyer", "Scheelenstraße 18", "31134", "Hildesheim",
  "05121 14141", "meyer@hoerakustik-meyer.de", "Lastschrift", "VB", "LARS MEYER HOERAKUSTIK", "ls", since="2023-09-01")
C("10043", "Ev.-luth. Kirchengemeinde St. Andreas", "Gemeindehaus", "Frau Pastorin Lehnhoff", "Andreasplatz 5",
  "31134", "Hildesheim", "05121 34141", "gemeindebuero@st-andreas-hi.de", "Überweisung", "EB",
  "EV.-LUTH. KIRCHENGEMEINDE ST. ANDREAS", "kirche", since="2020-01-01")
C("10044", "Café Leinetal", "Inh. Sabrina Kohl", "Frau Kohl", "Dammstraße 30", "31134", "Hildesheim", "05121 81919",
  "cafe-leinetal@web.de", "Lastschrift", "SPK", "SABRINA KOHL", "ls", since="2024-04-01")
C("10045", "Bürogemeinschaft Hohnsen 4", "c/o Dr. Petra Lange", "Frau Dr. Lange", "Hohnsen 4", "31134", "Hildesheim",
  "05121 20404", "lange@hohnsen4.de", "Überweisung", "DB", "BUEROGEMEINSCHAFT HOHNSEN 4", "ue_slightlylate",
  since="2022-05-01")
C("10046", "Optik Sehwerk", "Inh. Jonas Reuter", "Herr Reuter", "Hoher Weg 12", "31134", "Hildesheim", "05121 10303",
  "info@sehwerk-optik.de", "Lastschrift", "VB", "JONAS REUTER OPTIK", "ls", since="2024-10-01")
C("10047", "Fahrschule Lenkrad", "Inh. Uwe Brandes", "Herr Brandes", "Bahnhofsallee 5", "31134", "Hildesheim",
  "05121 31313", "info@fahrschule-lenkrad.de", "Überweisung", "SPK", "UWE BRANDES FAHRSCHULE", "ue_num",
  since="2021-01-01", note="Vertrag beendet 31.12.2025")
POWERHOUSE_NEW = acct("DKB", "10032", "neu")  # PowerHouse changes banks in September (K38)

# ------------------------------------------------------------------ objects / contracts
OBJECTS: list[dict] = []
SECTIONS = {"Büro": "BÜRO & VERWALTUNG", "Praxis": "PRAXEN & GESUNDHEIT", "Wohnen": "WOHNUNGSWIRTSCHAFT",
            "Öffentlich": "ÖFFENTLICH & SOZIALES", "Gewerbe": "GEWERBE & HANDEL"}


def O(ob, kurz, name, street, plz, kd, art, leistung, days, net, beginn, alt=None, ab=None, frist="3 Monate zum Monatsende",
      gek=None, glas="nach Aufwand", ol="Arslan", bem="", city="Hildesheim", text=None):
    OBJECTS.append(dict(ob=ob, kurz=kurz, name=name, street=street, plz=plz, city=city, kd=kd, art=art,
                        leistung=leistung, days=days, net=net, alt=alt, ab=D(ab) if ab else None, beginn=D(beginn),
                        frist=frist, gek=D(gek) if gek else None, glas=glas, ol=ol, bem=bem,
                        text=text or ("Treppenhausreinigung" if art == "Wohnen" else "Unterhaltsreinigung")))


PA = "2026-07-01"  # the price adjustment of July (Preisgleitklausel, Schreiben vom 12.05.2026)
O("OB-101", "Hoffmann", "Steuerkanzlei Hoffmann & Partner", "Zingel 12", "31134", "10001", "Büro",
  "Unterhaltsreinigung Büro 240 m², Sanitär, Teeküche", "Mo,Do", 47250, "2019-03-01", 45000, PA,
  bem="Preisgleitklausel § 6 – Schreiben 12.05.2026; Kunde zahlt per Dauerauftrag")
O("OB-102", "Brückner", "Kanzlei Brückner & Sohn", "Almsstraße 28", "31134", "10002", "Büro",
  "Unterhaltsreinigung Kanzlei 310 m²", "Mo,Mi,Fr", 72500, "2018-09-01", 69000, PA, frist="3 Monate zum Quartalsende",
  bem="Preisgleitklausel § 6 – Schreiben 12.05.2026")
O("OB-103", "Lenz", "Architekturbüro Lenz", "Kardinal-Bertram-Straße 9", "31134", "10003", "Büro",
  "Unterhaltsreinigung 180 m²", "Di,Fr", 39500, "2021-05-01")
O("OB-104", "Neuland", "IT-Systemhaus Neuland", "Daimlerring 5", "31135", "10004", "Büro",
  "Unterhaltsreinigung Büro 620 m², Sozialräume, Teeküchen", "Mo,Di,Mi,Do,Fr", 198000, "2017-01-01", 189000, PA,
  frist="6 Monate zum Jahresende", glas="4x jährlich inklusive", ol="Demir")
O("OB-105", "Krämer", "Versicherungsbüro Krämer", "Schuhstraße 31", "31134", "10005", "Büro",
  "Unterhaltsreinigung 110 m²", "Mi", 31000, "2020-02-01", gek="2026-08-31", bem="Kündigung per Mail 20.05.2026")
O("OB-106", "Sander & Kühn", "Ingenieurbüro Sander & Kühn", "Senator-Braun-Allee 33", "31135", "10006", "Büro",
  "Unterhaltsreinigung 260 m²", "Mo,Do", 56000, "2022-04-01", ol="Demir")
O("OB-107", "Coworking", "Coworking Altstadt", "Andreasplatz 2", "31134", "10007", "Büro",
  "Unterhaltsreinigung 290 m², Küche, Sanitär", "Mo,Mi,Fr", 64000, "2026-07-01", bem="neu, Angebot A-26-011")
O("OB-108", "Fahrenholz", "Immobilien Fahrenholz", "Bahnhofsallee 21", "31134", "10008", "Büro",
  "Unterhaltsreinigung Büro 90 m²", "Fr", 26000, "2023-01-01")
O("OB-109", "Kreativraum", "Werbeagentur Kreativraum", "Goschenstraße 61", "31134", "10009", "Büro",
  "Unterhaltsreinigung 160 m²", "Di,Fr", 38000, "2020-10-01", 36000, PA)
O("OB-110", "Bildungswerk", "Bildungswerk Innerste – Seminarhaus", "Steuerwalder Straße 60", "31137", "10010", "Büro",
  "Unterhaltsreinigung Seminarräume, Flure, Sanitär 520 m²", "Mo,Mi,Fr", 89000, "2019-08-01", ol="Kowalczyk")
O("OB-111", "Okonkwo", "Zahnarztpraxis Dr. Okonkwo", "Bischof-Janssen-Straße 4", "31134", "10011", "Praxis",
  "Praxisreinigung inkl. Flächendesinfektion Behandlungsräume", "Mo,Mi,Fr", 48000, "2021-01-01", text="Praxisreinigung")
O("OB-112", "Schäfer HI", "Zahnarztpraxis Dr. Schäfer", "Almsstraße 15", "31134", "10012", "Praxis",
  "Praxisreinigung inkl. Desinfektion", "Mo,Mi,Fr", 52000, "2020-06-01", 49500, PA, text="Praxisreinigung")
O("OB-113", "Schäfer Sarstedt", "Zahnarztpraxis Dr. Schäfer (Sarstedt)", "Holztorstraße 7", "31157", "10013", "Praxis",
  "Praxisreinigung", "Di,Do", 38000, "2022-11-01", city="Sarstedt", ol="Kowalczyk", text="Praxisreinigung")
O("OB-114", "Yıldız", "Hausarztpraxis Dr. Yıldız & Kollegen", "Peiner Straße 14", "31137", "10014", "Praxis",
  "Praxisreinigung 280 m² inkl. Desinfektion", "Mo,Di,Mi,Do,Fr", 74000, "2018-04-01", 71000, PA, ol="Demir",
  text="Praxisreinigung")
O("OB-115", "Physio Markt", "Physiotherapie am Markt", "Markt 6", "31134", "10015", "Praxis",
  "Praxisreinigung, Behandlungsliegen, Sanitär", "Di,Fr", 35000, "2021-09-01", text="Praxisreinigung")
O("OB-117", "Ergo Kaya", "Praxis für Ergotherapie Kaya", "Ostertor 3", "31134", "10017", "Praxis",
  "Praxisreinigung 95 m²", "Mi", 29000, "2023-03-01", text="Praxisreinigung")
O("OB-118", "Lindqvist", "Augenarztpraxis Dr. Lindqvist", "Hindenburgplatz 5", "31134", "10018", "Praxis",
  "Praxisreinigung", "Mo,Mi,Fr", 61000, "2019-01-01", 58000, PA, text="Praxisreinigung")
O("OB-119", "MVZ Praxis", "MVZ Hildesheim Nord – Praxisräume EG/1. OG", "Senkingstraße 12", "31137", "10019",
  "Praxis", "Unterhaltsreinigung Praxisräume 780 m²", "Mo,Di,Mi,Do,Fr", 145000, "2020-01-01",
  frist="6 Monate zum Jahresende", ol="Demir")
O("OB-120", "MVZ OP", "MVZ Hildesheim Nord – Eingriffsräume/Sterilgut", "Senkingstraße 12", "31137", "10019", "Praxis",
  "Hygienereinigung Eingriffsräume nach RKI-Empfehlung, Desinfektion", "Mo,Di,Mi,Do,Fr", 210000, "2020-01-01",
  frist="6 Monate zum Jahresende", ol="Demir", text="Hygienereinigung Eingriffsräume")
O("OB-121", "Behrens", "Kinderarztpraxis Dr. Behrens", "Lucienvörder Allee 2", "31141", "10020", "Praxis",
  "Praxisreinigung inkl. Spielecke", "Mo,Mi,Fr", 43000, "2022-02-01", ol="Kowalczyk", text="Praxisreinigung",
  bem="Praxis zieht 11/2026 in den Neubau Marienburger Höhe")
O("OB-122", "WEG Linden 12", "WEG Lindenstraße 12", "Lindenstraße 12", "31134", "10021", "Wohnen",
  "Treppenhausreinigung wöchentl., Keller monatl.", "Mi", 19000, "2016-05-01", ol="Kowalczyk")
O("OB-123", "WEG Garten 5", "WEG Gartenstraße 5", "Gartenstraße 5", "31141", "10022", "Wohnen",
  "Treppenhausreinigung wöchentl.", "Do", 14500, "2018-01-01", ol="Kowalczyk")
O("OB-124", "WEG Am Wall 3", "WEG Am Wall 3", "Am Wall 3", "31134", "10023", "Wohnen",
  "Treppenhausreinigung wöchentl., Aufzug", "Di", 23000, "2017-07-01", ol="Kowalczyk")
O("OB-125", "WEG Moltke 40", "WEG Moltkestraße 40 (2 Aufgänge)", "Moltkestraße 40", "31135", "10024", "Wohnen",
  "Treppenhausreinigung 2 Aufgänge wöchentl.", "Mo", 26000, "2015-03-01", 24500, PA, ol="Kowalczyk")
O("OB-126", "WEG Kaiser 17", "WEG Kaiserstraße 17", "Kaiserstraße 17", "31134", "10025", "Wohnen",
  "Treppenhausreinigung wöchentl.", "Fr", 17500, "2018-06-01", ol="Kowalczyk")
O("OB-127", "Ostend", "Wohnanlage Ostend (4 Häuser)", "Ostender Straße 2–8", "31135", "10026", "Wohnen",
  "Treppenhausreinigung 4 Häuser wöchentl., Außenanlage 14-tägl.", "Mo,Do", 68000, "2019-01-01", 64500, PA,
  ol="Kowalczyk")
O("OB-128", "Steinberg", "Wohnpark Steinberg", "Am Steinberg 20–24", "31139", "10026", "Wohnen",
  "Treppenhausreinigung 3 Aufgänge, Aufzüge", "Di,Fr", 52000, "2020-04-01", ol="Kowalczyk")
O("OB-129", "Godehard", "Haus Godehard", "Godehardsplatz 9", "31134", "10026", "Wohnen",
  "Treppenhausreinigung, Müllplatz", "Mi", 24000, "2021-06-01", ol="Kowalczyk")
O("OB-130", "Ärztehaus KBS", "Ärztehaus Kardinal-Bertram-Straße 30", "Kardinal-Bertram-Straße 30", "31134", "10026",
  "Wohnen", "Reinigung Allgemeinflächen, Treppenhaus, Aufzug", "Mo,Mi,Fr", 46000, "2019-10-01", ol="Kowalczyk",
  text="Unterhaltsreinigung Allgemeinflächen")
O("OB-131", "Moritzberg", "Wohnanlage Moritzberg (6 Häuser)", "Bergstraße 40–50", "31139", "10027", "Wohnen",
  "Treppenhausreinigung 6 Häuser wöchentl.", "Mo,Di,Mi", 124000, "2014-01-01", 118000, PA,
  frist="6 Monate zum Jahresende", ol="Kowalczyk")
O("OB-132", "GS Lindenhof", "Grundschule Am Lindenhof", "Lindenhofweg 1", "31141", "10028", "Öffentlich",
  "Unterhaltsreinigung Schule 2.150 m² (Klassen, Flure, Sanitär, Turnhalle) an Schultagen", "Mo,Di,Mi,Do,Fr",
  485000, "2024-08-01", frist="Laufzeit bis 31.07.2027 (Vergabe 2024)", glas="2x jährlich inklusive", ol="Arslan",
  bem="Rechnung ab Leistungsmonat 09/2026 nur als XRechnung (Leitweg-ID 03254021-65000-17)",
  text="Unterhaltsreinigung Schule")
O("OB-133", "Kita Sonnenblume", "Ev. Kita Sonnenblume", "Elzer Straße 41", "31137", "10029", "Öffentlich",
  "Unterhaltsreinigung Kita 4 Gruppen, Sanitär, Küche", "Mo,Di,Mi,Do,Fr", 98000, "2019-08-01", 93000, PA)
O("OB-134", "Lebenszeit", "Pflegedienst Lebenszeit – Büro/Umkleiden", "Goslarsche Straße 55", "31134", "10030",
  "Gewerbe", "Unterhaltsreinigung Büro, Umkleiden", "Di,Fr", 33000, "2023-06-01")
O("OB-135", "Autohaus Wendt", "Autohaus Wendt – Showroom & Kundenbereich", "Porschestraße 10", "31135", "10031",
  "Gewerbe", "Unterhaltsreinigung Showroom 450 m², Kundenbereich, Büros", "Mo,Mi,Fr", 112000, "2018-03-01", 106000, PA,
  ol="Demir")
O("OB-136", "PowerHouse", "Fitnessstudio PowerHouse", "Cheruskerring 19", "31137", "10032", "Gewerbe",
  "Unterhaltsreinigung Trainingsflächen, Umkleiden, Duschen", "Mo,Di,Mi,Do,Fr", 85000, "2022-09-01", ol="Demir")
O("OB-137", "Rosenthal", "Bäckerei Rosenthal – Verwaltung/Sozialräume", "Rosenthaler Straße 2", "31141", "10033",
  "Gewerbe", "Unterhaltsreinigung Büro, Sozialräume", "Di,Fr", 24000, "2021-03-01")
O("OB-138", "Domblick", "Pension Domblick – Frühstücksraum, Flure", "Domhof 22", "31134", "10034", "Gewerbe",
  "Reinigung Frühstücksraum, Flure, Treppenhaus (ohne Zimmer)", "Mo,Mi,Fr", 76000, "2020-05-01")
O("OB-139", "Sievers", "Möbelhaus Sievers – Ausstellung, Büros", "Am Marienfriedhof 1", "31134", "10035", "Gewerbe",
  "Unterhaltsreinigung Ausstellung 1.200 m² (maschinell), Büros", "Mo,Mi,Fr", 139000, "2017-10-01", 132000, PA,
  ol="Demir")
O("OB-140", "Rehberg", "Notariat Dr. Rehberg", "Wollenweberstraße 5", "31134", "10036", "Büro",
  "Unterhaltsreinigung Notariat 260 m²", "Mo,Do", 54800, "2019-04-01", 52000, PA,
  bem="Preisgleitklausel § 6 – Schreiben 12.05.2026")
O("OB-141", "Logistik Büro", "Logistik Nord-Süd – Verwaltung", "Lerchenkamp 30", "31137", "10037", "Gewerbe",
  "Unterhaltsreinigung Verwaltung 700 m²", "Mo,Di,Mi,Do,Fr", 168000, "2016-11-01", 160000, PA, ol="Demir")
O("OB-142", "Logistik Halle 2", "Logistik Nord-Süd – Sozialräume Halle 2", "Lerchenkamp 32", "31137", "10037",
  "Gewerbe", "Reinigung Sozialräume, Umkleiden, Sanitär Halle 2", "Mo,Mi,Fr", 54000, "2021-01-01", ol="Demir")
O("OB-143", "Hansen", "Druckerei Hansen – Büro/Sozialräume", "Bavenstedter Straße 77", "31135", "10038", "Gewerbe",
  "Unterhaltsreinigung Büro, Sozialräume", "Di,Fr", 47000, "2020-02-01")
O("OB-144", "Tanzschule", "Tanzschule Rhythmus", "Kaiserstraße 50", "31134", "10039", "Gewerbe",
  "Reinigung Säle (Parkett), Foyer, Sanitär", "Mo,Do", 30000, "2022-01-01")
O("OB-145", "Engel", "Steuerberatung Engel", "Theaterstraße 6", "31141", "10040", "Büro",
  "Unterhaltsreinigung 150 m²", "Mi", 28000, "2021-07-01")
O("OB-146", "Hörakustik", "Hörakustik Meyer", "Scheelenstraße 18", "31134", "10042", "Gewerbe",
  "Reinigung Ladenlokal, Werkstatt", "Di", 19000, "2023-09-01")
O("OB-147", "St. Andreas", "Gemeindehaus St. Andreas", "Andreasplatz 5", "31134", "10043", "Öffentlich",
  "Reinigung Gemeindesaal, Gruppenräume, Küche", "Mo,Do", 41000, "2020-01-01", bem="Gemeinde zahlt quartalsweise")
O("OB-148", "Café Leinetal", "Café Leinetal – Gastraum", "Dammstraße 30", "31134", "10044", "Gewerbe",
  "Reinigung Gastraum, Sanitär (nach Schließung)", "Mo,Mi,Fr", 22000, "2024-04-01")
O("OB-149", "Hohnsen 4", "Bürogemeinschaft Hohnsen 4", "Hohnsen 4", "31134", "10045", "Büro",
  "Unterhaltsreinigung 140 m²", "Di,Fr", 36000, "2022-05-01")
O("OB-150", "Sehwerk", "Optik Sehwerk", "Hoher Weg 12", "31134", "10046", "Gewerbe",
  "Reinigung Ladenlokal", "Mo", 18000, "2024-10-01")
O("OB-151", "Albers", "Tierarztpraxis Dr. Albers", "Ottostraße 70", "31137", "10016", "Praxis",
  "Praxisreinigung inkl. Desinfektion OP", "Mo,Mi,Fr", 42000, "2026-10-01", ol="Kowalczyk",
  bem="neu, Angebot A-26-020 (angenommen 12.09.)", text="Praxisreinigung")
O("OB-099", "Fahrschule", "Fahrschule Lenkrad – Schulungsraum", "Bahnhofsallee 5", "31134", "10047", "Büro",
  "Reinigung Schulungsraum, WC", "Mi", 15000, "2021-01-01", gek="2025-12-31", bem="gekündigt durch Kunden (Umzug)")
OBJ = {o["ob"]: o for o in OBJECTS}

# ------------------------------------------------------------------ employees
EMP = {}
for _p, _n, _v, _f, _e, _a, _h, _lg, _lohn in [
        (101, "Arslan", "Mehmet", "Objektleiter", "2015-04-01", "Vollzeit", 40, "LG 6", "19,80"),
        (102, "Fiedler", "Renate", "Büro/Buchhaltung", "2017-02-01", "Teilzeit", 25, "Angestellte", "–"),
        (103, "Demir", "Aylin", "Vorarbeiterin", "2016-09-01", "Vollzeit", 39, "LG 3", "16,40"),
        (104, "Kowalczyk", "Irena", "Vorarbeiterin", "2018-03-01", "Vollzeit", 39, "LG 3", "16,40"),
        (105, "Bondarenko", "Olena", "Reinigungskraft", "2022-10-01", "Teilzeit", 30, "LG 1", "14,85"),
        (106, "Popescu", "Maria", "Reinigungskraft", "2019-05-01", "Teilzeit", 25, "LG 1", "14,85"),
        (107, "Yılmaz", "Fatma", "Reinigungskraft", "2020-01-15", "Teilzeit", 20, "LG 1", "14,85"),
        (108, "Nowak", "Agnieszka", "Reinigungskraft", "2019-11-01", "Teilzeit", 30, "LG 1", "14,85"),
        (109, "Kruse", "Sabine", "Reinigungskraft", "2021-04-01", "Minijob", 9, "LG 1", "14,85"),
        (110, "Dumitru", "Elena", "Reinigungskraft", "2020-06-01", "Teilzeit", 25, "LG 1", "14,85"),
        (111, "Weber", "Svetlana", "Reinigungskraft", "2023-02-01", "Teilzeit", 20, "LG 1", "14,85"),
        (112, "Haidari", "Ahmad", "Glas- und Gebäudereiniger", "2018-08-01", "Vollzeit", 40, "LG 6", "18,20"),
        (113, "Brandt", "Monika", "Reinigungskraft (Springerin)", "2022-03-01", "Minijob", 9, "LG 1", "14,85"),
        (114, "Kaya", "Hatice", "Reinigungskraft", "2021-09-01", "Teilzeit", 25, "LG 1", "14,85"),
        (115, "Sokolova", "Natalia", "Reinigungskraft", "2023-08-01", "Teilzeit", 30, "LG 1", "14,85"),
        (116, "Lorenz", "Gabriele", "Reinigungskraft", "2020-09-01", "Minijob", 9, "LG 1", "14,85"),
        (117, "Hoffmann", "Daniel", "Reinigungskraft/Fahrer", "2019-01-01", "Vollzeit", 40, "LG 2", "15,40"),
        (118, "Marin", "Ioana", "Reinigungskraft", "2024-01-15", "Teilzeit", 20, "LG 1", "14,85"),
        (119, "Schulz", "Petra", "Reinigungskraft", "2017-05-01", "Minijob", 9, "LG 1", "14,85"),
        (120, "Aydın", "Yasemin", "Reinigungskraft", "2021-02-01", "Teilzeit", 25, "LG 1", "14,85"),
        (121, "Wiśniewska", "Katarzyna", "Reinigungskraft (Hygiene)", "2020-03-01", "Teilzeit", 30, "LG 2", "15,40"),
        (122, "Haddad", "Lina", "Reinigungskraft", "2024-06-01", "Teilzeit", 20, "LG 1", "14,85"),
        (123, "Gerlach", "Thomas", "Sonderreinigung/Maschinen", "2016-01-01", "Vollzeit", 40, "LG 3", "16,40"),
        (124, "Ferreira", "Rosa", "Reinigungskraft (Hygiene)", "2022-07-01", "Teilzeit", 25, "LG 2", "15,40"),
        (125, "Novák", "Jana", "Reinigungskraft (Springerin)", "2023-05-01", "Minijob", 9, "LG 1", "14,85"),
        (126, "Engel", "Brigitte", "Reinigungskraft", "2026-04-01", "Minijob", 9, "LG 1", "14,85")]:
    EMP[_p] = dict(p=_p, name=_n, vorname=_v, funktion=_f, eintritt=D(_e), art=_a, h=_h, lg=_lg, lohn=_lohn)

ASSIGN = {"OB-101": [108], "OB-102": [108], "OB-103": [118], "OB-104": [106, 118], "OB-105": [109], "OB-106": [110],
          "OB-107": [122], "OB-108": [109], "OB-109": [111], "OB-110": [111, 120], "OB-111": [107], "OB-112": [120],
          "OB-113": [116], "OB-114": [114], "OB-115": [119], "OB-117": [107], "OB-118": [120], "OB-119": [110],
          "OB-120": [121, 124], "OB-121": [114], "OB-122": [119], "OB-123": [119], "OB-124": [116], "OB-125": [104],
          "OB-126": [116], "OB-127": [104, 113], "OB-128": [104], "OB-129": [126], "OB-130": [104],
          "OB-131": [104, 125, 126], "OB-132": [105, 108, 115], "OB-133": [122, 114], "OB-134": [111],
          "OB-135": [103], "OB-136": [103], "OB-137": [110], "OB-138": [106], "OB-139": [103, 117], "OB-140": [118],
          "OB-141": [121, 124], "OB-142": [117], "OB-143": [113], "OB-144": [125], "OB-145": [107], "OB-146": [109],
          "OB-147": [126], "OB-148": [113], "OB-149": [122], "OB-150": [125], "OB-151": [122]}
SPRINGER = [113, 125, 116, 126]
SCHOOL_HOLIDAYS = [(D("2026-07-02"), D("2026-08-12")), (D("2026-10-12"), D("2026-10-24"))]

# ------------------------------------------------------------------ special jobs (Sonderaufträge)
SONDER = []


def S(sa, eingang, kd, ob, leistung, termin, done, std, net, inv, angebot="", bem="", emps=(), sub=False, list_done=True):
    SONDER.append(dict(sa=sa, eingang=D(eingang), kd=kd, ob=ob, leistung=leistung, termin=D(termin),
                       done=D(done) if done else None, std=std, net=net, inv=D(inv) if inv else None,
                       angebot=angebot, bem=bem, emps=list(emps), sub=sub, list_done=list_done))


S("SA-26-001", "2026-01-12", "10035", "OB-139", "Glasreinigung Schaufenster und Ausstellung", "2026-01-21", "2026-01-21", 9.0, 38000, "2026-01-23", emps=[112])
S("SA-26-002", "2026-02-02", "10026", "OB-130", "Grundreinigung Treppenhaus und Aufzug Ärztehaus", "2026-02-11", "2026-02-11", 14.0, 64000, "2026-02-13", emps=[123, 117])
S("SA-26-003", "2026-02-09", "10019", "OB-120", "Desinfektion Eingriffsräume nach Umbau", "2026-02-18", "2026-02-18", 12.0, 52000, "2026-02-20", emps=[123, 121])
S("SA-26-004", "2026-02-23", "10037", "OB-141", "Teppichreinigung Büroetage (Sprühextraktion)", "2026-03-04", "2026-03-04", 16.0, 89000, "2026-03-06", emps=[123, 117])
S("SA-26-005", "2026-03-02", "10038", "OB-143", "Glasreinigung Büro und Sozialräume", "2026-03-12", "2026-03-12", 6.0, 26000, "2026-03-18", bem="erst an falschen Kunden berechnet, storniert", emps=[112])
S("SA-26-006", "2026-03-09", "10031", "OB-135", "Glasreinigung Showroom Frühjahr", "2026-03-20", "2026-03-20", 14.0, 69000, "2026-03-23", emps=[112, 117])
S("SA-26-007", "2026-03-30", "10006", "OB-106", "Glasreinigung Fenster und Glastrennwände", "2026-04-08", "2026-04-08", 7.0, 31000, "2026-04-10", emps=[112])
S("SA-26-008", "2026-04-01", "10014", "OB-114", "Grundreinigung PVC-Böden Praxis mit Neueinpflege", "2026-04-15", "2026-04-15", 15.0, 76000, "2026-04-17", emps=[123, 114])
S("SA-26-009", "2026-04-13", "10021", "OB-122", "Grundreinigung Treppenhaus und Keller", "2026-04-22", "2026-04-22", 8.5, 42000, "2026-04-24", emps=[123])
S("SA-26-010", "2026-04-27", "10034", "OB-138", "Polsterreinigung Frühstücksraum (32 Stühle)", "2026-05-06", "2026-05-06", 7.0, 34000, "2026-05-08", emps=[117])
S("SA-26-011", "2026-05-04", "10004", "OB-104", "Teppichreinigung Großraumbüro (Samstag)", "2026-05-16", "2026-05-16", 26.0, 145000, "2026-05-19", emps=[123, 117, 106])
S("SA-26-012", "2026-05-26", "10029", "OB-133", "Desinfektion Gruppenräume (Norovirus)", "2026-05-27", "2026-05-27", 6.0, 29000, "2026-05-29", emps=[123])
S("SA-26-013", "2026-05-25", "10041", "OB-115", "Glasreinigung Praxis", "2026-06-03", "2026-06-03", 5.0, 24000, "2026-06-05", bem="neue GbR – Kundensatz neu angelegt", emps=[112])
S("SA-26-014", "2026-06-01", "10035", "OB-139", "Glasreinigung Schaufenster und Ausstellung", "2026-06-10", "2026-06-10", 9.0, 38000, "2026-06-12", emps=[112])
S("SA-26-015", "2026-06-08", "10010", "OB-110", "Grundreinigung Seminarräume (Linoleum)", "2026-06-24", "2026-06-24", 19.0, 98000, "2026-06-26", emps=[123, 117])
S("SA-26-016", "2026-06-22", "10027", "OB-131", "Fassadenreinigung Eingangsbereiche 6 Häuser", "2026-07-08", "2026-07-08", 22.0, 118000, "2026-07-10", angebot="A-26-013", emps=[123, 117])
S("SA-26-017", "2026-07-06", "10002", "OB-102", "Teppichreinigung Kanzleiräume", "2026-07-15", "2026-07-15", 10.0, 52000, "2026-07-17", emps=[123])
S("SA-26-018", "2026-06-10", "10028", "OB-132", "Grundreinigung Klassenräume und Flure (Sommerferien)", "2026-08-03", "2026-08-07", 64.0, 340000, "2026-08-10", angebot="A-26-012", bem="Sommerferien 02.07.–12.08.", emps=[123, 117, 105, 115])
S("SA-26-019", "2026-07-13", "10022", "OB-123", "Grundreinigung Treppenhaus", "2026-07-22", "2026-07-22", 7.5, 38000, "2026-07-24", emps=[123])
S("SA-26-020", "2026-07-20", "10018", "OB-118", "Glasreinigung Praxis", "2026-07-29", "2026-07-29", 6.0, 29000, "2026-07-31", emps=[112])
S("SA-26-021", "2026-07-21", "10042", "OB-146", "Glasreinigung Schaufenster", "2026-07-30", "2026-07-30", 3.0, 16000, "2026-07-31", emps=[112])
S("SA-26-022", "2026-07-27", "10033", "OB-137", "Grundreinigung Sozialräume Backstube", "2026-08-05", "2026-08-05", 6.5, 31000, "2026-08-07", emps=[123])
S("SA-26-023", "2026-07-30", "10012", "OB-112", "Grundreinigung Behandlungsräume (Praxisurlaub)", "2026-08-12", "2026-08-12", 11.0, 56000, "2026-08-14", emps=[123, 120])
S("SA-26-024", "2026-06-15", "10029", "OB-133", "Grundreinigung Gruppenräume und Flure (Sommerschließung)", "2026-08-10", "2026-08-14", 36.0, 186000, "2026-09-25", angebot="A-26-014", emps=[123, 117, 114])
S("SA-26-025", "2026-08-10", "10037", "OB-142", "Grundreinigung Sozialräume Halle 2", "2026-08-19", "2026-08-19", 9.0, 47000, "2026-08-21", emps=[123])
S("SA-26-026", "2026-08-17", "10003", "OB-103", "Glasreinigung Büro", "2026-08-26", "2026-08-26", 4.5, 21000, "2026-08-28", emps=[112])
S("SA-26-027", "2026-07-20", "10031", "OB-135", "Glasreinigung Showroom Herbst (Hubsteiger, Fa. Petrovic)", "2026-09-04", "2026-09-04", 4.0, 115000, None, angebot="A-26-016", bem="Hubsteiger und Glasreiniger über Petrovic (Sub)", emps=[112], sub=True)
S("SA-26-028", "2026-08-24", "10019", "OB-119", "Grundreinigung Wartezimmer und Flure", "2026-09-02", "2026-09-02", 13.0, 68000, "2026-09-04", emps=[123, 110])
S("SA-26-029", "2026-08-31", "10002", "OB-102", "Polsterreinigung Besprechungsraum", "2026-09-09", "2026-09-09", 6.0, 34000, "2026-09-11", emps=[117])
S("SA-26-030", "2026-08-12", "10011", "OB-111", "Nachreinigung nach Reklamation", "2026-08-14", "2026-08-14", 4.0, 0, None, bem="Reklamation 12.08. – kostenlos", emps=[103])
S("SA-26-031", "2026-08-25", "10020", "", "Bauendreinigung Neubau Praxis Marienburger Höhe 14", "2026-09-28", "2026-09-30", 52.0, 290000, "2026-10-06", angebot="A-26-019", bem="Anzahlung 1.500,00 € vereinbart", emps=[123, 117, 112, 105])
S("SA-26-032", "2026-09-28", "10042", "OB-146", "Grundreinigung Teppich Ladenlokal", "2026-10-15", "2026-10-15", 6.0, 29000, None, emps=[123, 117], list_done=False)
S("SA-26-033", "2026-09-22", "10026", "OB-127", "Glasreinigung Treppenhausfenster Ostend, Steinberg, Ärztehaus (Hubsteiger, Fa. Petrovic)", "2026-10-12", "2026-10-14", 8.0, 148000, None, bem="eine Rechnung für OB-127, OB-128, OB-130 (Mail 22.09.)", emps=[112], sub=True)
S("SA-26-034", "2026-10-01", "10029", "OB-133", "Desinfektion Gruppenräume (Norovirus)", "2026-10-02", "2026-10-02", 6.0, 29000, "2026-10-05", emps=[123])
S("SA-26-035", "2026-09-30", "10014", "OB-114", "Glasreinigung Praxis", "2026-10-07", "2026-10-07", 5.0, 26000, "2026-10-09", emps=[112])
S("SA-26-036", "2026-10-19", "10038", "OB-143", "Teppichreinigung Büro", "2026-10-27", "2026-10-27", 8.0, 43000, "2026-10-28", emps=[123])
SA = {s["sa"]: s for s in SONDER}

# ------------------------------------------------------------------ invoices
INV: list[dict] = []   # 2026, in the book
PREV: list[dict] = []  # 2025, not in the book (their payments arrive in January)


def price(o: dict, y: int, m: int, booked: bool = True) -> int:
    if o["alt"] and (o["ab"] is None or date(y, m, 1) < o["ab"]):
        return o["alt"]
    if booked and o["ob"] == "OB-102" and o["alt"]:  # K03: the book never got the new price
        return o["alt"]
    return o["net"]


def active(o: dict, y: int, m: int) -> bool:
    first, last = date(y, m, 1), month_end(y, m)
    return o["beginn"] <= last and (o["gek"] is None or o["gek"] >= first)


MISSING = {("OB-107", 7), ("OB-132", 9)}  # K01, K02


def inv_customer(o: dict, y: int, m: int) -> str:
    if o["ob"] == "OB-115" and (y, m) >= (2026, 6):
        return "10041"  # K13: since June the invoices go to the duplicate record
    return o["kd"]


def build_invoices():
    reqs = []
    for m in range(1, 10):
        run = last_wd(2026, m)
        for i, o in enumerate(OBJECTS):
            if o["ob"] == "OB-099" or not active(o, 2026, m) or (o["ob"], m) in MISSING:
                continue
            kd = inv_customer(o, 2026, m)
            net = price(o, 2026, m)
            reqs.append(dict(date=run, order=(0, i), kind="Rechnung", kd=kd, ob=o["ob"], net=net,
                             text=f"{o['text']} lt. Vertrag {m:02d}/2026", period=f"{m:02d}/2026", month=m,
                             zahlart=CUSTOMERS[kd]["pay"], sa=""))
    for s in SONDER:
        if s["inv"] is None:
            continue
        if s["sa"] == "SA-26-005":  # K26: first to the wrong customer, storno, then right
            reqs.append(dict(date=D("2026-03-16"), order=(1, 4), kind="Rechnung", kd="10037", ob="OB-143",
                             net=s["net"], text=f"{s['leistung']} lt. Auftrag {s['sa']}", period="03/2026", month=None,
                             zahlart="Überweisung", sa=s["sa"], tag="wrong"))
            reqs.append(dict(date=D("2026-03-18"), order=(1, 4), kind="Storno", kd="10037", ob="OB-143",
                             net=-s["net"], text="Storno zu Rechnung {wrong} (falscher Rechnungsempfänger)",
                             period="03/2026", month=None, zahlart="", sa=s["sa"], tag="storno"))
        txt = f"{s['leistung']} lt. Auftrag {s['sa']}"
        if s["sa"] == "SA-26-031":
            txt += " (Angebot A-26-019)"
        reqs.append(dict(date=s["inv"], order=(1, int(s["sa"][-3:])), kind="Rechnung", kd=s["kd"], ob=s["ob"],
                         net=s["net"], text=txt, period=f"{s['done'].month:02d}/2026", month=None,
                         zahlart="Überweisung", sa=s["sa"], tag="sonder"))
    # K12: credit note for Okonkwo, 25 % of the August fee
    reqs.append(dict(date=D("2026-09-03"), order=(2, 0), kind="Gutschrift", kd="10011", ob="OB-111", net=-12000,
                     text="Gutschrift zu Rechnung {aug111} – Reklamation 03.–07.08.2026 (25 % Monatspauschale)",
                     period="08/2026", month=None, zahlart="", sa="", tag="credit"))
    reqs.sort(key=lambda r: (r["date"], r["order"]))
    for n, r in enumerate(reqs, start=1):
        r["no"] = f"2026-{n:04d}"
        r["vat"] = vat19(r["net"])
        r["gross"] = r["net"] + r["vat"]
        cu = CUSTOMERS[r["kd"]]
        if r["kind"] != "Rechnung":
            r["due"] = r["date"]
        elif r["zahlart"] == "Lastschrift":
            r["due"] = coll_date(2026, r["month"])
        else:
            r["due"] = r["date"] + timedelta(days=cu["terms"])
        INV.append(r)
    by = {(r["ob"], r["month"]): r for r in INV if r["month"]}
    wrong = next(r for r in INV if r.get("tag") == "wrong")
    for r in INV:
        r["text"] = r["text"].replace("{wrong}", wrong["no"]).replace("{aug111}", by[("OB-111", 8)]["no"])
        if r.get("tag") == "storno":
            r["ref"] = wrong["no"]
        if r.get("tag") == "credit":
            r["ref"] = by[("OB-111", 8)]["no"]
        if r["sa"] == "SA-26-031" and r.get("tag") == "sonder":
            r["bem"] = "abzgl. Anzahlung 1.500,00 € vom 15.09.2026 – Zahlbetrag " + de(r["gross"] - 150000) + " €"
    # December 2025 (and a few older ones): only their payments are in the 2026 bank export
    n = 531
    for o in OBJECTS:
        if not active(o, 2025, 12) or o["ob"] in ("OB-107", "OB-151"):
            continue
        net = price(o, 2025, 12)
        PREV.append(dict(no=f"2025-{n:04d}", date=D("2025-12-31"), kd=o["kd"], ob=o["ob"], net=net,
                         gross=net + vat19(net), month=12, zahlart=CUSTOMERS[o["kd"]]["pay"],
                         due=(D("2026-01-12") if CUSTOMERS[o["kd"]]["pay"] == "Lastschrift" else
                              D("2025-12-31") + timedelta(days=CUSTOMERS[o["kd"]]["terms"]))))
        n += 1
    for no, d, ob in (("2025-0418", "2025-10-31", "OB-147"), ("2025-0469", "2025-11-28", "OB-147"),
                      ("2025-0471", "2025-11-28", "OB-131")):
        o = OBJ[ob]
        net = price(o, 2025, 11)
        PREV.append(dict(no=no, date=D(d), kd=o["kd"], ob=ob, net=net, gross=net + vat19(net), month=int(d[5:7]),
                         zahlart="Überweisung", due=D(d) + timedelta(days=14)))


def inv_of(ob: str, m: int) -> dict:
    return next(r for r in INV if r["ob"] == ob and r["month"] == m)


def inv_sa(sa: str) -> dict:
    return next(r for r in INV if r["sa"] == sa and r.get("tag") == "sonder")


def prev_of(ob: str, m: int = 12) -> dict:
    return next(r for r in PREV if r["ob"] == ob and r["month"] == m)


# ------------------------------------------------------------------ money
EV: list[dict] = []  # bank lines and internal settlements


def ev(d, amount, **kw) -> dict:
    e = dict(date=d, amount=amount, btext="", vwz="", payer="", iban="", bic="", ci="", mandate="", e2e="",
             sammler="", urspr="", auslagen="", alloc=[], deferred=[], cust=None, bank=True, other=False,
             refund_of=None, note="", prev=False, id=len(EV))
    e.update(kw)
    EV.append(e)
    return e


def transfer_in(d, cu, amount, vwz, alloc, **kw):
    c = CUSTOMERS[cu]
    return ev(next_wd(d), amount, btext=kw.pop("btext", "GUTSCHR. UEBERWEISUNG"), vwz=vwz, payer=kw.pop("payer", c["payer"]),
              iban=kw.pop("iban", c["iban"]), bic=kw.pop("bic", c["bic"]), e2e="NOTPROVIDED", alloc=alloc, cust=cu,
              **kw)


def vwz_style(cu: str, no: str, m: int | None, y: int = 2026) -> str:
    mm = f"{m:02d}" if m else ""
    mon = MONATE[m - 1] if m else ""
    styles = {
        "10002": f"Rechnung {no}", "10003": f"RE {no} Architekturbuero Lenz", "10005": f"Rg {no}",
        "10007": f"Rechnungsnr. {no}", "10011": f"Re {no}", "10012": f"Rechnung Nr. {no} Praxisreinigung",
        "10029": f"Rechnung {no} Kita Sonnenblume", "10034": f"Rechnung {no}", "10037": f"ReNr {no} KredNr 70412",
        "10041": f"{no}", "10045": f"Rechnung {no} Hohnsen 4", "10039": f"Rechnung {no}",
        "10010": f"Rechnung {no} Seminarhaus", "10047": f"Rechnung {no} Fahrschule",
        "10021": f"Treppenhausreinigung RG {no}", "10023": f"Rg. {no} TH-Reinigung", "10024": f"Reinigung {no}",
        "10025": f"RE{no.replace('-', '')}",
        "10013": f"Praxisreinigung {mon} {y}", "10017": f"Reinigung {mm}/{str(y)[2:]} Ergotherapie Kaya",
        "10009": f"Bueroreinigung {mon}", "10022": f"Hausreinigung {mon} Gartenstr. 5",
    }
    return styles.get(cu, f"Rechnung {no}")


def gen_payments():
    batches: dict[date, list] = {}

    def pay_generic(r, prev=False):
        cu = r["kd"]
        c = CUSTOMERS[cu]
        prof = c["profile"]
        g = rr("pay", r["no"])
        m = r["month"]
        y = r["date"].year
        alloc = [] if prev else [(r["no"], r["gross"])]
        tag = r.get("tag")
        if r["zahlart"] == "Lastschrift" and not tag:
            batches.setdefault(r["due"], []).append(r)
            return
        if prof == "skonto":
            sk = pct(r["gross"], 2)
            d = r["date"] + timedelta(days=g.randint(5, 7))
            if not prev:
                alloc = [(r["no"], r["gross"] - sk)]
            e = transfer_in(d, cu, r["gross"] - sk, f"RE {r['no']} abzgl. 2% Skonto", alloc, prev=prev)
            if not prev:
                ev(e["date"], 0, bank=False, alloc=[(r["no"], sk)], note="Skonto innerhalb 8 Tagen (vereinbart)")
        elif prof in ("ue_num", "ls", "weg", "ue_nonum", "weg_nonum", "mvz", "kroeger") or tag == "sonder":
            d = r["date"] + timedelta(days=g.randint(6, 12))
            vw = vwz_style(cu, r["no"], m, y) if not tag else (
                f"Rechnung {r['no']}" if prof in ("ls", "ue_nonum", "weg_nonum") else vwz_style(cu, r["no"], None, y))
            if prof == "weg_nonum" and tag:
                vw = "Grundreinigung Treppenhaus Gartenstr. 5"
            transfer_in(d, cu, r["gross"], vw, alloc, prev=prev)
        elif prof == "ue_late":
            transfer_in(r["due"] + timedelta(days=g.randint(18, 25)), cu, r["gross"], vwz_style(cu, r["no"], m, y), alloc, prev=prev)
        elif prof == "ue_slightlylate":
            transfer_in(r["due"] + timedelta(days=g.randint(3, 6)), cu, r["gross"], vwz_style(cu, r["no"], m, y), alloc, prev=prev)
        elif prof == "stadt":
            d = r["date"] + timedelta(days=g.randint(33, 37))
            kz = f"5.6100.{g.randint(100000, 999999)}.{g.randint(1, 9)}"
            vw = (f"KASSENZEICHEN {kz} IHRE RECHNUNG VOM {dde(r['date'])} GEBAEUDEREINIGUNG GS AM LINDENHOF" if not tag
                  else f"KASSENZEICHEN {kz} RECHNUNG {r['no']} GRUNDREINIGUNG")
            transfer_in(d, cu, r["gross"], vw, alloc, prev=prev)
        elif prof == "tanz":
            if r["date"] < D("2026-06-01"):
                transfer_in(r["date"] + timedelta(days=g.randint(5, 10)), cu, r["gross"], vwz_style(cu, r["no"], m, y), alloc, prev=prev)
        elif prof in ("dauerauftrag", "geno", "kirche"):
            pass  # group logic below
        else:
            raise ValueError(prof)

    special = set()
    # --- K07 Lenz: August paid twice
    r = inv_of("OB-103", 8)
    special.add(r["no"])
    transfer_in(D("2026-09-03"), "10003", r["gross"], vwz_style("10003", r["no"], 8), [(r["no"], r["gross"])])
    dbl = transfer_in(D("2026-09-08"), "10003", r["gross"], vwz_style("10003", r["no"], 8), [])
    c = CUSTOMERS["10003"]
    ev(D("2026-09-30"), -r["gross"], btext="ONLINE-UEBERWEISUNG", vwz=f"Erstattung Doppelzahlung RE {r['no']} vom 08.09.2026",
       payer="Architekturbuero Lenz", iban=c["iban"], bic=c["bic"], e2e="NOTPROVIDED", refund_of=dbl["id"], cust="10003")
    # --- K12 Okonkwo pays August minus the credit note
    r = inv_of("OB-111", 8)
    gs = next(x for x in INV if x.get("tag") == "credit")
    special.add(r["no"])
    transfer_in(D("2026-09-10"), "10011", r["gross"] + gs["gross"], f"Re {r['no']} abzgl. Gutschrift {gs['no']}",
                [(r["no"], r["gross"]), (gs["no"], gs["gross"])])
    # --- K22 Domblick August with swapped digits
    r = inv_of("OB-138", 8)
    special.add(r["no"])
    nums = {x["no"]: x for x in INV}
    tail = r["no"][-4:]
    swapped = None
    for i in range(3):
        t = list(tail)
        t[i], t[i + 1] = t[i + 1], t[i]
        cand = "2026-" + "".join(t)
        if cand != r["no"] and cand in nums and nums[cand]["kd"] != r["kd"] and nums[cand]["gross"] != r["gross"]:
            swapped = cand
            break
    assert swapped, "no digit swap target"
    transfer_in(D("2026-09-09"), "10034", r["gross"], f"Rechnung {swapped}", [(r["no"], r["gross"])],
                note=f"Zahlendreher: meint {r['no']}")
    ANSWERS["K22_swapped"] = dict(meant=r["no"], written=swapped)
    # --- K17 Autohaus: August paid on day 15 with 2 % off
    r = inv_of("OB-135", 8)
    special.add(r["no"])
    sk = pct(r["gross"], 2)
    transfer_in(D("2026-09-15"), "10031", r["gross"] - sk, f"RE {r['no']} abzgl. 2% Skonto", [(r["no"], r["gross"] - sk)],
                note="Skonto nach Ablauf der 8 Tage – nicht berechtigt")
    # --- K04 PowerHouse: returned debit, then transfer
    r = inv_of("OB-136", 8)
    batches.setdefault(r["due"], []).append(r)
    special.add(r["no"])
    c = CUSTOMERS["10032"]
    ev(D("2026-09-14"), -(r["gross"] + 300), btext="RUECKLASTSCHRIFT",
       vwz=f"RUECKLASTSCHRIFT AM04 DECKUNG UNZUREICHEND RECHNUNG {r['no']} UNTERHALTSREINIGUNG 08/2026 OB-136",
       payer=c["payer"], iban=c["iban"], bic=c["bic"], ci=FIRM["ci"], mandate=c["mandate"], e2e=r["no"],
       sammler=f"LS-{r['due'].isoformat()}", urspr=csvamt(r["gross"]), auslagen="3,00", alloc=[(r["no"], -r["gross"])],
       cust="10032", note="Rücklastschrift, 3,00 Gebühr in der Zeile")
    transfer_in(D("2026-09-24"), "10032", r["gross"], f"Rechnung {r['no']} nach Ruecklastschrift", [(r["no"], r["gross"])],
                iban=POWERHOUSE_NEW[0], bic=POWERHOUSE_NEW[1])
    # --- K05 Rehberg: September returned (MD06), fee as own line
    r = inv_of("OB-140", 9)
    batches.setdefault(r["due"], []).append(r)
    special.add(r["no"])
    c = CUSTOMERS["10036"]
    ev(D("2026-10-14"), -r["gross"], btext="RUECKLASTSCHRIFT", vwz="RUECKLASTSCHRIFT MD06 RUECKGABE AUF VERLANGEN DES ZAHLERS",
       payer=c["payer"], iban=c["iban"], bic=c["bic"], ci=FIRM["ci"], mandate=c["mandate"], e2e=r["no"],
       sammler=f"LS-{r['due'].isoformat()}", urspr=csvamt(r["gross"]), alloc=[(r["no"], -r["gross"])], cust="10036",
       note="Widerspruch des Zahlers")
    ev(D("2026-10-15"), -350, btext="ENTGELT", vwz="ENTGELT RUECKLASTSCHRIFT 1 POSTEN MANDAT OST-10036-01",
       payer="Sparkasse Hildesheim Goslar Peine", note="Gebühr zur Rücklastschrift Rehberg")
    # --- K08 MVZ pays September OB-120 twice; K11/K10 Kröger; these customers pay in groups
    # --- K18 Behrens Anzahlung
    s31 = inv_sa("SA-26-031")
    special.add(s31["no"])
    transfer_in(D("2026-09-15"), "10020", 150000, "Anzahlung Bauendreinigung Angebot A-26-019 Dr. Behrens", [],
                deferred=[(s31["no"], 150000)], note="Anzahlung ohne Rechnung")
    transfer_in(D("2026-10-16"), "10020", s31["gross"] - 150000, f"RE {s31['no']} Restbetrag Bauendreinigung",
                [(s31["no"], s31["gross"] - 150000)])
    # --- K33 Albers pays October in advance
    transfer_in(D("2026-10-02"), "10016", 42000 + vat19(42000), "Reinigung Oktober Tierarztpraxis Dr. Albers Vorauszahlung",
                [], note="Vorauszahlung, Rechnung kommt Ende Oktober")
    # --- Kita: Grundreinigung paid without number (L2)
    r = inv_sa("SA-26-024")
    special.add(r["no"])
    transfer_in(D("2026-10-20"), "10029", r["gross"], "Grundreinigung Sommerferien Kita Sonnenblume", [(r["no"], r["gross"])])
    # --- Stadt Sonder: paid with number, Kassenzeichen
    r = inv_sa("SA-26-018")
    special.add(r["no"])
    transfer_in(D("2026-09-14"), "10028", r["gross"], f"KASSENZEICHEN 5.6100.004711.3 RECHNUNG {r['no']} GRUNDREINIGUNG",
                [(r["no"], r["gross"])])
    # --- Lenz Glasreinigung separately on 03.09.
    r = inv_sa("SA-26-026")
    special.add(r["no"])
    transfer_in(D("2026-09-03"), "10003", r["gross"], f"RE {r['no']} Glasreinigung", [(r["no"], r["gross"])])
    # --- SA-26-029 paid 24.09., SA-26-036 open, SA-26-034/035 paid in October
    for sa_, d_ in (("SA-26-029", "2026-09-24"), ("SA-26-034", "2026-10-19"), ("SA-26-035", "2026-10-21"),
                    ("SA-26-028", "2026-09-15")):
        r = inv_sa(sa_)
        special.add(r["no"])
        transfer_in(D(d_), r["kd"], r["gross"], f"RE {r['no']}", [(r["no"], r["gross"])])
    special.add(inv_sa("SA-26-036")["no"])
    # --- SA-26-015 Bildungswerk late
    r = inv_sa("SA-26-015")
    special.add(r["no"])
    transfer_in(D("2026-07-31"), "10010", r["gross"], f"Rechnung {r['no']} Grundreinigung", [(r["no"], r["gross"])])
    # --- SA-26-016 Geno with slash
    r = inv_sa("SA-26-016")
    special.add(r["no"])
    transfer_in(D("2026-07-30"), "10027", r["gross"], f"Rg. {r['no'].replace('-', '/')} Fassadenreinigung", [(r["no"], r["gross"])])
    # --- Storno pair settles itself; the right invoice is paid by Hansen
    wrong = next(x for x in INV if x.get("tag") == "wrong")
    sto = next(x for x in INV if x.get("tag") == "storno")
    special.update({wrong["no"], sto["no"]})
    ev(sto["date"], 0, bank=False, alloc=[(wrong["no"], wrong["gross"]), (sto["no"], sto["gross"])], note="Storno")
    r = inv_sa("SA-26-005")
    special.add(r["no"])
    transfer_in(D("2026-03-30"), "10038", r["gross"], f"Rechnung {r['no']} Glasreinigung", [(r["no"], r["gross"])])
    # --- credit note settled via Okonkwo's payment
    special.add(gs["no"])
    # --- Autohaus Sonder SA-26-006 (skonto in time) handled by generic skonto
    # --- Tanzschule: June onwards unpaid; Rate 1 on 12.10. -> June
    r = inv_of("OB-144", 6)
    transfer_in(D("2026-10-12"), "10039", r["gross"], "Rate 1 Rueckstand Reinigung Tanzschule", [(r["no"], r["gross"])],
                note="Teilzahlung auf den Rückstand – älteste Rechnung")

    # group payers ---------------------------------------------------------------
    # Hoffmann: standing order of the old amount on the 15th, month by month (K16)
    for m in range(1, 11):
        d = next_wd(date(2026, m, 15))
        if m == 1:
            alloc, prev_no = [], prev_of("OB-101")["no"]
        else:
            r = inv_of("OB-101", m - 1)
            special.add(r["no"])
            alloc = [(r["no"], min(53550, r["gross"]))]
        transfer_in(d, "10001", 53550, "REINIGUNG LT. VERTRAG HOFFMANN + PARTNER", alloc, btext="GUTSCHR. UEBERW. DAUERAUFTR",
                    note="Dauerauftrag" + (" (zahlt Rechnung Dezember 2025)" if m == 1 else ""), prev=(m == 1))
    # Kröger: one collective transfer a month for its four objects (K10, K11)
    for m in range(1, 10):
        rs = [inv_of(ob, m) for ob in ("OB-127", "OB-128", "OB-129", "OB-130")]
        special.update(x["no"] for x in rs)
        d = rs[0]["date"] + timedelta(days=rr("kroeger", m).randint(8, 11))
        if m == 8:
            d = D("2026-09-10")
            names = ["Wohnanlage Ostend", "Wohnpark Steinberg", "Haus Godehard", "Aerztehaus KBS"]
            full = "Sammelzahlung 08/2026 " + ", ".join(f"{n_} RE {x['no']}" for n_, x in zip(names, rs))
            cut = full[:140]
            assert rs[3]["no"] not in cut and rs[2]["no"] in cut and cut.endswith(rs[3]["no"][:7]), cut
            vw = cut
            ANSWERS["K10_vwz"] = vw
        elif m == 9:
            rs = [x for x in rs if x["ob"] != "OB-129"]
            d = D("2026-10-09")
            vw = "Zahlungsavis vom 09.10.2026 Kroeger + Partner 3 Belege"
        else:
            vw = f"Sammelzahlung {m:02d}/2026 RE " + " ".join(x["no"] for x in rs)
        transfer_in(d, "10026", sum(x["gross"] for x in rs), vw, [(x["no"], x["gross"]) for x in rs])
    pr = [prev_of(ob) for ob in ("OB-127", "OB-128", "OB-129", "OB-130")]
    transfer_in(D("2026-01-12"), "10026", sum(x["gross"] for x in pr), "Sammelzahlung 12/2025 RE " + " ".join(x["no"] for x in pr), [], prev=True)
    # MVZ: both objects in one transfer (K08 double in October)
    for m in range(1, 10):
        rs = [inv_of("OB-119", m), inv_of("OB-120", m)]
        special.update(x["no"] for x in rs)
        d = rs[0]["date"] + timedelta(days=rr("mvz", m).randint(9, 12))
        transfer_in(d, "10019", rs[0]["gross"] + rs[1]["gross"], f"RE {rs[0]['no']} u. {rs[1]['no']}",
                    [(x["no"], x["gross"]) for x in rs])
        if m == 9:
            transfer_in(D("2026-10-15"), "10019", rs[1]["gross"], f"RE {rs[1]['no']} Hygienereinigung", [],
                        note="Doppelzahlung")
    pr = [prev_of("OB-119"), prev_of("OB-120")]
    transfer_in(D("2026-01-13"), "10019", pr[0]["gross"] + pr[1]["gross"], f"RE {pr[0]['no']} u. {pr[1]['no']}", [], prev=True)
    # Genossenschaft: two months per transfer, numbers with a slash (K34)
    for (m1, m2), d in (((1, 2), "2026-03-06"), ((3, 4), "2026-05-06"), ((5, 6), "2026-07-06"), ((7, 8), "2026-09-07")):
        rs = [inv_of("OB-131", m1), inv_of("OB-131", m2)]
        special.update(x["no"] for x in rs)
        transfer_in(D(d), "10027", sum(x["gross"] for x in rs),
                    f"Rg. {rs[0]['no'].replace('-', '/')} u. {rs[1]['no'].replace('-', '/')} Treppenhausreinigung",
                    [(x["no"], x["gross"]) for x in rs])
    special.add(inv_of("OB-131", 9)["no"])  # open, due 30.10.
    pr = [next(x for x in PREV if x["no"] == "2025-0471"), prev_of("OB-131")]
    transfer_in(D("2026-01-08"), "10027", sum(x["gross"] for x in pr),
                f"Rg. {pr[0]['no'].replace('-', '/')} u. {pr[1]['no'].replace('-', '/')} Treppenhausreinigung", [], prev=True)
    # Kirchengemeinde: quarterly, no numbers (K36)
    for q, ms, d in ((1, (1, 2, 3), "2026-04-07"), (2, (4, 5, 6), "2026-07-07"), (3, (7, 8, 9), "2026-10-06")):
        rs = [inv_of("OB-147", m) for m in ms]
        special.update(x["no"] for x in rs)
        transfer_in(D(d), "10043", sum(x["gross"] for x in rs), f"Reinigung Gemeindehaus {q}. Quartal 2026",
                    [(x["no"], x["gross"]) for x in rs])
    pr = [x for x in PREV if x["ob"] == "OB-147"]
    transfer_in(D("2026-01-08"), "10043", sum(x["gross"] for x in pr), "Reinigung Gemeindehaus 4. Quartal 2025", [], prev=True)

    # everybody else ---------------------------------------------------------------
    for r in INV:
        if r["no"] in special or r["kind"] != "Rechnung":
            continue
        pay_generic(r)
    for r in PREV:
        if r["kd"] in ("10001", "10026", "10019", "10027", "10043"):
            continue
        if r["zahlart"] == "Lastschrift":
            batches.setdefault(r["due"], []).append(r)
            continue
        pay_generic(r, prev=True)
    # direct debit batches (one credit line per batch, details in the pain.008 file)
    for d in sorted(batches):
        rs = sorted(batches[d], key=lambda x: x["no"])
        alloc = [(x["no"], x["gross"]) for x in rs if not x["no"].startswith("2025")]
        e = ev(d, sum(x["gross"] for x in rs), btext="SEPA-LS EINREICHUNG",
               vwz=f"SEPA-LASTSCHRIFTEN {len(rs)} POSTEN EINREICHUNG VOM {dde(d - timedelta(days=2))}",
               ci=FIRM["ci"], sammler=f"LS-{d.isoformat()}", alloc=alloc, cust="LS", note="Sammellastschrift")
        BATCHES.append(dict(date=d, items=rs, event=e))


BATCHES: list[dict] = []
ANSWERS: dict = {}

# ------------------------------------------------------------------ the firm's own expenses and other income
SUPPLIERS = {
    "nordhaus": dict(name="Nordhaus Hygiene-Großhandel GmbH", street="Lister Damm 112", plz="30163", city="Hannover",
                     phone="0511 6 47 33-0", mail="rechnung@nordhaus-hygiene.de", web="www.nordhaus-hygiene.de",
                     bank="COM", ustid="DE118775304", hrb="HRB 55120, Amtsgericht Hannover", gf="Jörg Nordhaus",
                     kdnr="48812"),
    "petrovic": dict(name="Glas & Fassade Petrovic", owner="Dragan Petrovic", street="Am Kupferstrange 12",
                     plz="31137", city="Hildesheim", phone="0171 5 88 41 20", mail="petrovic-glas@t-online.de",
                     web="", bank="SPK", ustid="", stnr="30/144/22871", hrb="", gf="Inhaber Dragan Petrovic",
                     kdnr="O-07"),
    "kraft": dict(name="BerufsMode Kraft GmbH", street="Woltorfer Straße 40", plz="31224", city="Peine",
                  phone="05171 29 33 0", mail="buchhaltung@berufsmode-kraft.de", web="www.berufsmode-kraft.de",
                  bank="VB", ustid="DE231004856", hrb="HRB 1140, Amtsgericht Hildesheim", gf="Silke Kraft", kdnr="20371"),
    "bode": dict(name="Reinigungstechnik Bode GmbH", street="Industriestraße 7", plz="38239", city="Salzgitter",
                 phone="05341 88 21 0", mail="service@bode-reinigungstechnik.de", web="www.bode-reinigungstechnik.de",
                 bank="DB", ustid="DE145882031", hrb="HRB 3307, Amtsgericht Braunschweig", gf="Andreas Bode", kdnr="K-1180"),
    "engel": dict(name="Steuerberatung Engel", owner="StB Christiane Engel", street="Theaterstraße 6", plz="31141",
                  city="Hildesheim", phone="05121 26660", mail="kanzlei@stb-engel.de", web="", bank="SPK",
                  ustid="DE267331908", hrb="", gf="Steuerberaterin Christiane Engel", kdnr="2214"),
}
for _k, _s in SUPPLIERS.items():
    _s["iban"], _s["bic"] = acct(_s["bank"], "supplier", _k)
SUPPLIERS["engel"]["iban"], SUPPLIERS["engel"]["bic"] = CUSTOMERS["10040"]["iban"], CUSTOMERS["10040"]["bic"]
FRAUD_IBAN = "LT413250024719384410"

NORDHAUS_ITEMS = [("Allzweckreiniger neutral, 10-l-Kanister", "Kan.", 2890), ("Sanitärunterhaltsreiniger sauer, 10 l", "Kan.", 3450),
                  ("Glasreiniger alkoholisch, 10 l", "Kan.", 2240), ("Flächendesinfektion VAH-gelistet, 5 l", "Kan.", 4180),
                  ("Müllbeutel 120 l, reißfest, 250 Stk.", "Rolle", 3190), ("Falthandtücher 2-lagig, 3.200 Bl.", "Karton", 3360),
                  ("Toilettenpapier 3-lagig, 72 Rollen", "Pack", 3980), ("Mikrofasertücher 40×40, 4 Farben, 50 Stk.", "Pack", 4750),
                  ("Wischmopp Baumwolle 50 cm", "Stk.", 690), ("Schaumseife 800 ml Kartusche", "Stk.", 545),
                  ("Einweghandschuhe Nitril M, 100 Stk.", "Box", 640), ("Bodenpflege Wischpflege, 10 l", "Kan.", 3320)]


def supplier_invoices():
    """The incoming invoices (PDF) and their payments."""
    out = []

    def nord(no, d, picks, paid=None, skonto_paid=True):
        lines = []
        for i, (idx, qty) in enumerate(picks, start=1):
            t, u, p = NORDHAUS_ITEMS[idx]
            lines.append((i, t, qty, u, p))
        out.append(dict(sup="nordhaus", no=no, date=D(d), lines=lines, vat=19, skonto=(2, 10), due_days=30,
                        paid=D(paid) if paid else None, skonto_paid=skonto_paid, file=f"Nordhaus_{no}.pdf"))
    nord("2026-29911", "2026-06-18", [(0, 6), (1, 4), (4, 8), (5, 6), (6, 5), (10, 10)], "2026-06-26")
    nord("2026-31877", "2026-08-20", [(0, 8), (1, 5), (3, 6), (4, 10), (5, 8), (6, 6), (7, 4)], "2026-08-28")
    nord("2026-32410", "2026-09-10", [(0, 4), (2, 3), (4, 6), (5, 5), (9, 12), (11, 3)], "2026-09-18")
    nord("2026-34102", "2026-10-21", [(0, 8), (1, 6), (3, 8), (4, 12), (5, 10), (6, 8), (7, 6), (11, 4)], None)
    out.append(dict(sup="petrovic", no="097/2026", date=D("2026-06-30"), vat=0, skonto=None, due_days=14,
                    lines=[(1, "Glasreinigung mit Hubarbeitsbühne, Möbelhaus Sievers (SA-26-014), 10.06.2026", 1, "pauschal", 98000)],
                    paid=D("2026-07-10"), file="Petrovic_097-2026.pdf"))
    out.append(dict(sup="petrovic", no="118/2026", date=D("2026-09-07"), vat=0, skonto=None, due_days=14,
                    lines=[(1, "Glasreinigung Showroom Autohaus Wendt mit Hubsteiger 18 m, 04.09.2026", 1, "pauschal", 52000),
                           (2, "Stellung Hubsteiger inkl. An-/Abfahrt", 1, "pauschal", 16000)],
                    paid=D("2026-09-21"), file="Petrovic_118-2026.pdf"))
    out.append(dict(sup="petrovic", no="131/2026", date=D("2026-10-16"), vat=0, skonto=None, due_days=14,
                    lines=[(1, "Glasreinigung TH-Fenster Wohnanlage Ostend, 12.10.2026", 1, "pauschal", 42000),
                           (2, "Glasreinigung TH-Fenster Wohnpark Steinberg, 13.10.2026", 1, "pauschal", 36000),
                           (3, "Glasreinigung TH-Fenster Ärztehaus Kardinal-Bertram-Str., 14.10.2026", 1, "pauschal", 24000),
                           (4, "Hubsteiger 3 Tage inkl. An-/Abfahrt", 3, "Tag", 4000)],
                    paid=None, file="Petrovic_131-2026.pdf"))
    out.append(dict(sup="kraft", no="2026-0588", date=D("2026-07-15"), vat=19, skonto=None, due_days=30,
                    lines=[(1, "Kasack Damen, grau, mit Logostick", 14, "Stk.", 3290), (2, "Bundhose Herren/Damen, anthrazit", 10, "Stk.", 2990),
                           (3, "Poloshirt mit Logostick", 20, "Stk.", 1890), (4, "Sicherheitsschuh S2, Halbschuh", 4, "Paar", 5490)],
                    paid=D("2026-08-12"), file="BerufsMode_Kraft_2026-0588.pdf"))
    out.append(dict(sup="bode", no="R-26-1204", date=D("2026-08-03"), vat=19, skonto=None, due_days=14,
                    lines=[(1, "Reparatur Scheuersaugmaschine: Saugmotor 24 V getauscht", 1, "Stk.", 31800),
                           (2, "Arbeitszeit Servicetechniker", 2.5, "Std.", 6900), (3, "Anfahrtspauschale", 1, "pauschal", 4200)],
                    paid=D("2026-08-14"), file="Bode_R-26-1204.pdf"))
    for no, d, m, n_abr, paid in (("2026/0712", "2026-07-31", 7, 25, "2026-08-10"), ("2026/0815", "2026-08-31", 8, 26, "2026-09-09"),
                                  ("2026/0921", "2026-09-30", 9, 26, "2026-10-09")):
        out.append(dict(sup="engel", no=no, date=D(d), vat=19, skonto=None, due_days=14,
                        lines=[(1, f"Lohnbuchhaltung {m:02d}/2026: {n_abr} Abrechnungen", n_abr, "Abr.", 1650),
                               (2, f"Finanzbuchhaltung {m:02d}/2026 (laufende Buchführung, USt-VA)", 1, "pauschal", 24000),
                               (3, "Auslagenpauschale (§ 16 StBVV)", 1, "pauschal", 2000)],
                        paid=D(paid), file=f"StB_Engel_{no.replace('/', '-')}.pdf"))
    for x in out:
        net = sum(int(round(q * p)) for _, _, q, _, p in x["lines"])
        x["net"] = net
        x["vatc"] = vat19(net) if x["vat"] == 19 else 0
        x["gross"] = net + x["vatc"]
        x["due"] = x["date"] + timedelta(days=x["due_days"])
        x["skonto_until"] = x["date"] + timedelta(days=x["skonto"][1]) if x["skonto"] else None
    return out


SUPINV: list[dict] = []


def gen_other_bank():
    """Wages, social security, tax, rent, leasing … and the supplier payments."""
    for x in SUPINV:
        if not x["paid"]:
            continue
        s = SUPPLIERS[x["sup"]]
        amt = x["gross"]
        vw = f"Re. {x['no']} KdNr {s['kdnr']}"
        if x["skonto"] and x.get("skonto_paid") and x["paid"] <= x["skonto_until"]:
            amt -= pct(x["gross"], x["skonto"][0])
            vw += f" abzgl. {x['skonto'][0]}% Skonto"
        ev(x["paid"], -amt, btext="ONLINE-UEBERWEISUNG", vwz=vw, payer=s["name"], iban=s["iban"], bic=s["bic"],
           e2e="NOTPROVIDED", other=True)
    # Nordhaus invoices before June (no PDFs kept) and Engel before July
    for i, (d, no, amt) in enumerate((("2026-01-22", "2026-19876", 98450), ("2026-02-19", "2026-21544", 76320),
                                      ("2026-03-24", "2026-23971", 112380), ("2026-04-23", "2026-25890", 88710),
                                      ("2026-05-21", "2026-27731", 94530))):
        s = SUPPLIERS["nordhaus"]
        ev(D(d), -(amt - pct(amt, 2)), btext="ONLINE-UEBERWEISUNG", vwz=f"Re. {no} KdNr 48812 abzgl. 2% Skonto",
           payer=s["name"], iban=s["iban"], bic=s["bic"], e2e="NOTPROVIDED", other=True)
    for m in range(1, 7):
        s = SUPPLIERS["engel"]
        n_abr = 24 if m < 4 else 25
        gross = (n_abr * 1650 + 24000 + 2000) + vat19(n_abr * 1650 + 24000 + 2000)
        ev(next_wd(month_end(2026, m) + timedelta(days=10)), -gross, btext="ONLINE-UEBERWEISUNG",
           vwz=f"Re. 2026/0{m}{10 + m} Lohn/Fibu {m:02d}/2026", payer=s["name"], iban=s["iban"], bic=s["bic"],
           e2e="NOTPROVIDED", other=True)
    end = DELIV[-1]["cut"]
    for m in range(1, 11):
        g = rr("bank", m)
        def o(d, amt, btext, vwz, payer, ci="", mandate="", ib=""):
            d = next_wd(d)
            if d <= end:
                ev(d, amt, btext=btext, vwz=vwz, payer=payer, ci=ci, mandate=mandate, iban=ib, other=True)
        o(date(2026, m, 1), -165000, "DAUERAUFTRAG", f"Miete Buero/Lager Bavenstedter Str. 48 {m:02d}/2026",
          "Grundstuecksgemeinschaft Bavenstedter Str. 48 GbR", ib=iban("25950130", 700112233))
        for k in (1, 2, 3):
            o(date(2026, m, 2), -38940, "FOLGELASTSCHRIFT", f"Vertrag 77-31045/{k} Rate {m:02d}/2026 VW Crafter",
              "NORDLEASE FAHRZEUGLEASING GMBH", ci="DE71ZZZ00000431886", mandate=f"NL-77-31045-{k}")
        o(date(2026, m, 5), -31260, "FOLGELASTSCHRIFT", f"Kfz-Versicherung 3 Fahrzeuge {m:02d}/2026 VS-Nr 4411-882",
          "VGH Versicherungen", ci="DE55ZZZ00000082311", mandate="VGH-4411-882")
        o(date(2026, m, 8), -9480, "FOLGELASTSCHRIFT", f"Rechnung {m:02d}/2026 Kundenkonto 551 882 1044",
          "Telekom Deutschland GmbH", ci="DE93ZZZ00000078611", mandate="TK-5518821044")
        if m > 1:
            o(date(2026, m, 10), -(g.randint(128000, 152000)), "FOLGELASTSCHRIFT", f"StNr 30/210/45678 LSt {m - 1:02d}/2026",
              "Finanzamt Hildesheim", ci="DE19ZZZ00000094567", mandate="FA-LST-45678")
            o(date(2026, m, 10), -(g.randint(590000, 660000)), "FOLGELASTSCHRIFT",
              f"StNr 30/210/45678 USt-VZ {m - 1:02d}/2026", "Finanzamt Hildesheim", ci="DE19ZZZ00000094567",
              mandate="FA-UST-45678")
        o(date(2026, m, 12), -(g.randint(68000, 94000)), "FOLGELASTSCHRIFT", f"Tankkartenabrechnung {m:02d}/2026 Kd 600112",
          "ARAL CARD SERVICE", ci="DE30ZZZ00000153300", mandate="ARAL-600112")
        o(date(2026, m, 15), -4990, "FOLGELASTSCHRIFT", f"Lexware Faktura+Lohn Abo {m:02d}/2026", "Haufe Service Center GmbH",
          ci="DE81ZZZ00000214567", mandate="HSC-339120")
        if m in (2, 5, 8):
            o(date(2026, m, 15), -138000, "FOLGELASTSCHRIFT", f"Beitragsvorschuss {m:02d}/2026 Mitgl-Nr 140.33871",
              "BG BAU", ci="DE47ZZZ00000101044", mandate="BGBAU-14033871")
        if m <= 10:
            d = third_last_wd(2026, m)
            for payer, lo, hi, ci in (("AOK Niedersachsen", 421000, 452000, "DE02ZZZ00000013111"),
                                      ("BARMER", 105000, 118000, "DE77ZZZ00000040400"),
                                      ("Techniker Krankenkasse", 88000, 97000, "DE86ZZZ00000012345"),
                                      ("Knappschaft-Bahn-See Minijob-Zentrale", 182000, 196000, "DE97ZZZ00000017711")):
                o(d, -g.randint(lo, hi), "FOLGELASTSCHRIFT", f"Beitrag {m:02d}/2026 Betriebsnr. 41827651", payer, ci=ci,
                  mandate="BBNR-41827651")
            o(last_wd(2026, m), -g.randint(2050000, 2140000), "SAMMEL-UEBERWEISUNG",
              f"SAMMLER 25 POSTEN LOEHNE/GEHAELTER {m:02d}/2026", "Ostermeier Gebaeudedienste GmbH")
        for k in range(g.randint(1, 3)):
            shop, lo, hi = g.choice([("OBI MARKT HILDESHEIM", 1890, 12900), ("METRO HANNOVER", 4500, 18700),
                                     ("BAUHAUS HILDESHEIM", 2300, 9900), ("ROSSMANN 2214 HILDESHEIM", 690, 3400)])
            dd = date(2026, m, g.randint(3, 27))
            o(dd, -g.randint(lo, hi), "KARTENZAHLUNG", f"{dd.isoformat()}T{g.randint(8, 17):02d}:{g.randint(0, 59):02d} Debitk.1 2028-12 {shop}",
              shop)
        if m in (3, 6, 9):
            o(month_end(2026, m), -(g.randint(3850, 4590)), "ENTGELTABSCHLUSS", f"Entgeltabrechnung {m - 2:02d}-{m:02d}/2026 siehe Anlage",
              "Sparkasse Hildesheim Goslar Peine")
    for d, amt, z in (("2026-03-18", 51240, "02/2026 PNR 0110"), ("2026-06-09", 73310, "05/2026 PNR 0107"),
                      ("2026-08-20", 128430, "07/2026 PNR 0106 0121"), ("2026-09-09", 61280, "08/2026 PNR 0107"),
                      ("2026-10-08", 94020, "09/2026 PNR 0114")):
        ev(D(d), amt, btext="GUTSCHR. UEBERWEISUNG", vwz=f"Erstattung U1 Entgeltfortzahlung {z} BBNR 41827651",
           payer="AOK Niedersachsen", iban=iban("25050000", 101400), bic="NOLADE2HXXX", e2e="NOTPROVIDED", other=True,
           note="Erstattung der Krankenkasse – keine Kundenzahlung")


# ------------------------------------------------------------------ truth
def truth_for(dv: dict) -> dict:
    cut, today = dv["cut"], dv["today"]
    known = {r["no"]: r for r in INV if r["date"] <= cut}
    open_ = {no: r["gross"] for no, r in known.items()}
    receipts = []
    refunded = {e["refund_of"] for e in EV if e["refund_of"] is not None and e["date"] <= cut}
    for e in sorted(EV, key=lambda e: (e["date"], e["id"])):
        if e["date"] > cut:
            continue
        for no, c in e["alloc"]:
            if no in open_:
                open_[no] -= c
            elif not no.startswith("2025"):
                raise AssertionError(f"allocation to unknown invoice {no} on {e['date']}")
        rest = 0
        for no, c in e["deferred"]:
            if no in open_:
                open_[no] -= c
            else:
                rest += c
        cust_money = e["cust"] not in (None, "LS") and e["amount"] > 0 and not e["other"]
        if cust_money:
            unalloc = e["amount"] - sum(c for _, c in e["alloc"]) - sum(c for no, c in e["deferred"] if no in open_)
            if unalloc > 0 and not e["prev"] and e["id"] not in refunded:
                receipts.append(dict(amount=unalloc, date=e["date"], payer=e["payer"], vwz=e["vwz"], note=e["note"]))
    for no, c in open_.items():
        assert c >= 0, (no, c)
    op = {no: c for no, c in open_.items() if c > 0 and known[no]["gross"] > 0}
    overdue = sorted(no for no in op if known[no]["due"] < today)
    unbilled = []
    for (ob, m) in sorted(MISSING):
        if month_end(2026, m) <= cut:
            unbilled.append(dict(id=ob, what=f"{OBJ[ob]['name']} – Vertragsmonat {m:02d}/2026 nicht berechnet",
                                 net=price(OBJ[ob], 2026, m, booked=False)))
    for s in SONDER:
        if s["done"] and s["done"] <= cut and s["net"] > 0 and (s["inv"] is None or s["inv"] > cut):
            unbilled.append(dict(id=s["sa"], what=f"{s['leistung']} ({CUSTOMERS[s['kd']]['name']}), erledigt {dde(s['done'])}",
                                 net=s["net"], hard=not s["list_done"]))
    under = []
    o = OBJ["OB-102"]
    for r in INV:
        if r["ob"] == "OB-102" and r["month"] and r["date"] <= cut and r["net"] != price(o, 2026, r["month"], booked=False):
            want = price(o, 2026, r["month"], booked=False)
            under.append(dict(invoice=r["no"], object="OB-102", month=r["period"], booked_net=eur(r["net"]),
                              contract_net=eur(want), missing_gross=eur(want + vat19(want) - r["gross"])))
    payables = []
    for x in SUPINV:
        if x["date"] <= cut and (x["paid"] is None or x["paid"] > cut):
            payables.append(dict(supplier=SUPPLIERS[x["sup"]]["name"], invoice=x["no"], gross=eur(x["gross"]),
                                 due=x["due"].isoformat(),
                                 skonto_until=x["skonto_until"].isoformat() if x["skonto_until"] else None,
                                 skonto_amount=eur(x["gross"] - pct(x["gross"], 2)) if x["skonto"] else None))
    return dict(folder=dv["folder"], today=today.isoformat(),
                open={no: eur(c) for no, c in sorted(op.items())},
                overdue=overdue,
                unbilled=[u["id"] for u in unbilled],
                receipts=sorted(eur(x["amount"]) for x in receipts),
                open_total=eur(sum(op.values())),
                unbilled_detail=unbilled,
                receipts_detail=[dict(amount=eur(x["amount"]), date=x["date"].isoformat(), payer=x["payer"],
                                      vwz=x["vwz"], note=x["note"]) for x in receipts],
                underbilled=under,
                payables=payables)


# ------------------------------------------------------------------ writers
def xl_title(ws, rows):
    for i, (txt, bold) in enumerate(rows, start=1):
        ws.cell(row=i, column=1, value=txt).font = Font(bold=bold, size=13 if i == 1 else 10)


def xl_header(ws, row, heads, widths=None):
    for j, h in enumerate(heads, start=1):
        c = ws.cell(row=row, column=j, value=h)
        c.font = Font(bold=True)
        c.fill = PatternFill("solid", fgColor="DDE7F0")
        c.alignment = Alignment(wrap_text=True, vertical="top")
        if widths:
            ws.column_dimensions[c.column_letter].width = widths[j - 1]


def fixed_props(wb):
    wb.properties.creator = "Renate Fiedler"
    wb.properties.created = datetime(2026, 1, 5, 8, 0, 0)
    wb.properties.modified = datetime(2026, 1, 5, 8, 0, 0)


def write_objektliste(path: Path, dv: dict):
    wb = openpyxl.Workbook()
    fixed_props(wb)
    ws = wb.active
    ws.title = "Objekte"
    xl_title(ws, [("Objektliste & Reinigungsverträge", True),
                  (f"Ostermeier Gebäudedienste GmbH – Stand {dde(dv['obj_stand'])} (KO)", False)])
    heads = ["Obj.-Nr.", "Kurzbez.", "Objekt", "Straße", "PLZ", "Ort", "Kd.-Nr.", "Auftraggeber", "Leistungsumfang",
             "Turnus", "Std./Monat", "Pauschale netto/Monat", "Preisanpassung ab", "vorher netto", "Vertragsbeginn",
             "Kündigungsfrist", "gekündigt zum", "Glasreinigung", "Objektleitung", "Bemerkung"]
    xl_header(ws, 4, heads, [9, 14, 34, 24, 7, 11, 8, 34, 44, 16, 9, 12, 12, 11, 12, 22, 12, 18, 12, 40])
    row = 5
    ended = []
    total = 0
    for art, title in SECTIONS.items():
        objs = [o for o in OBJECTS if o["art"] == art]
        rows = []
        for o in objs:
            if o["ob"] == "OB-099":
                ended.append(o)
                continue
            if o["gek"] and dv["n"] == 2 and o["gek"] < dv["today"]:
                ended.append(o)
                continue
            rows.append(o)
        if not rows:
            continue
        ws.cell(row=row, column=1, value=title).font = Font(bold=True)
        row += 1
        for o in rows:
            kd = o["kd"]
            cu = CUSTOMERS[kd]
            if cu["from_l2"] and dv["n"] == 1:
                kd_cell, auftr = "", cu["name"] + " (Kd.-Nr. folgt)"
            else:
                kd_cell, auftr = kd, cu["name"] + (f" ({cu['zusatz'].replace('c/o ', 'HV ')})" if cu["zusatz"].startswith("c/o") else "")
            hours = round(o["net"] / 100 / 27.5, 1)
            vals = [o["ob"], o["kurz"], o["name"], o["street"], o["plz"], o["city"], kd_cell, auftr, o["leistung"],
                    o["days"].replace(",", ", "), hours, round(o["net"] / 100, 2),
                    o["ab"] if o["ab"] else None, round(o["alt"] / 100, 2) if o["alt"] else None, o["beginn"],
                    o["frist"], o["gek"], o["glas"], o["ol"], o["bem"]]
            for j, v in enumerate(vals, start=1):
                c = ws.cell(row=row, column=j, value=v)
                if isinstance(v, date):
                    c.number_format = "DD.MM.YYYY"
                if j in (12, 14):
                    c.number_format = "#,##0.00"
            total += o["net"]
            row += 1
        row += 1
    ws.cell(row=row, column=8, value="Summe Monatspauschalen (aktive Verträge)").font = Font(bold=True)
    c = ws.cell(row=row, column=12, value=round(total / 100, 2))
    c.number_format = "#,##0.00"
    c.font = Font(bold=True)
    ws.freeze_panes = "C5"
    ws2 = wb.create_sheet("beendet")
    xl_title(ws2, [("Beendete Verträge", True), ("", False)])
    xl_header(ws2, 4, ["Obj.-Nr.", "Objekt", "Kd.-Nr.", "Auftraggeber", "Pauschale netto/Monat", "Vertragsbeginn",
                       "Vertragsende", "Grund"], [9, 34, 8, 34, 12, 12, 12, 40])
    for i, o in enumerate(sorted(ended, key=lambda o: o["ob"]), start=5):
        for j, v in enumerate([o["ob"], o["name"], o["kd"], CUSTOMERS[o["kd"]]["name"], round(o["net"] / 100, 2),
                               o["beginn"], o["gek"], o["bem"]], start=1):
            c = ws2.cell(row=i, column=j, value=v)
            if isinstance(v, date):
                c.number_format = "DD.MM.YYYY"
    wb.save(path)


def write_kunden(path: Path, dv: dict):
    heads = ["Kundennr", "Firma", "Zusatz", "Ansprechpartner", "Strasse", "PLZ", "Ort", "Telefon", "E-Mail",
             "Zahlungsart", "IBAN", "BIC", "Bank", "Mandatsreferenz", "Mandat vom", "Zahlungsziel (Tage)", "Skonto %",
             "Skonto Tage", "USt-IdNr", "Leitweg-ID", "angelegt am", "Notiz"]
    lines = [";".join(f'"{h}"' for h in heads)]
    for kd in sorted(CUSTOMERS):
        c = CUSTOMERS[kd]
        if c["from_l2"] and dv["n"] == 1:
            continue
        ib, bic, mand, mdat, bank = c["iban"], c["bic"], c["mandate"], c["since"], c["bankname"]
        if kd == "10032" and dv["n"] == 2:
            ib, bic, mand, mdat, bank = POWERHOUSE_NEW[0], POWERHOUSE_NEW[1], "OST-10032-02", D("2026-09-21"), BANKS["DKB"][2]
        vals = [kd, c["name"], c["zusatz"], c["contact"], c["street"], c["plz"], c["city"], c["phone"], c["email"],
                c["pay"], fmt_iban(ib), bic, bank, mand, dde(mdat) if mand else "", str(c["terms"]),
                (str(c["skonto"][0]) if c["skonto"] else ""), (str(c["skonto"][1]) if c["skonto"] else ""),
                c["ustid"], c["leitweg"], dde(c["since"]), c["note"]]
        lines.append(";".join('"' + str(v).replace('"', "'") + '"' for v in vals))
    path.write_bytes(("\r\n".join(lines) + "\r\n").encode("cp1252", errors="replace"))


def book_status(r: dict, dv: dict) -> tuple[str, date | None, str]:
    """What the bookkeeper's book says (laut Datei) – reconciled up to dv['recon']; LS marked at batch creation."""
    recon, cut = dv["recon"], dv["cut"]
    tag = r.get("tag")
    if tag in ("wrong", "storno"):
        return "storniert", None, ""
    if tag == "credit":
        return ("verrechnet", D("2026-09-10"), "") if D("2026-09-10") <= recon else ("offen", None, "")
    if r["zahlart"] == "Lastschrift":
        if r["due"] - timedelta(days=2) <= cut:
            if r["ob"] == "OB-136" and r["month"] == 8 and dv["n"] == 2:
                return "bezahlt", D("2026-09-24"), "Rücklastschrift 14.09., überwiesen 24.09."
            return "bezahlt", r["due"], "LS"
        return "offen", None, ""
    paid, last = 0, None
    for e in EV:
        if e["date"] > recon:
            continue
        for no, c in e["alloc"]:
            if no == r["no"]:
                paid += c
                last = e["date"]
        for no, c in e["deferred"]:
            if no == r["no"] and r["date"] <= recon:
                paid += c
    if r["kd"] == "10001" and paid > 0:
        return "bezahlt", last, ""  # K16: the bookkeeper did not notice the old amount
    if r["kd"] == "10031" and 0 < paid < r["gross"]:
        return "teilbezahlt", last, "Skonto unberechtigt – nachfordern"
    if paid >= r["gross"] and r["gross"] > 0:
        return "bezahlt", last, ""
    if r["kd"] == "10039" and r["due"] < D("2026-08-20"):
        return "gemahnt", None, "Zahlungserinnerung 20.08.2026"
    return "offen", None, ""


def write_rechnungsbuch(path: Path, dv: dict):
    wb = openpyxl.Workbook()
    fixed_props(wb)
    ws = wb.active
    ws.title = "Rechnungsausgang 2026"
    xl_title(ws, [("Rechnungsausgangsbuch 2026", True),
                  (f"Ostermeier Gebäudedienste GmbH – Export aus Lexware Faktura, Stand {dde(dv['cut'])}", False)])
    heads = ["Re.-Nr.", "Belegart", "Datum", "Kd.-Nr.", "Kunde", "Obj.-Nr.", "Leistung", "Zeitraum", "Netto", "USt",
             "Brutto", "Zahlart", "fällig am", "Status", "bezahlt am", "Bemerkung"]
    xl_header(ws, 4, heads, [11, 10, 11, 8, 38, 9, 58, 9, 11, 10, 11, 12, 11, 11, 11, 40])
    row = 5
    sn = sv = sb = 0
    for r in INV:
        if r["date"] > dv["cut"]:
            continue
        st, paid_on, bem = book_status(r, dv)
        bem = r.get("bem", "") or bem
        if r.get("tag") == "credit":
            bem = "verrechnet mit " + r["ref"] if st == "verrechnet" else "Gutschrift zu " + r["ref"]
        vals = [r["no"], r["kind"], r["date"], r["kd"], CUSTOMERS[r["kd"]]["name"], r["ob"] or None, r["text"],
                r["period"], r["net"] / 100, r["vat"] / 100, r["gross"] / 100, r["zahlart"] or None,
                r["due"] if r["kind"] == "Rechnung" else None, st, paid_on, bem or None]
        for j, v in enumerate(vals, start=1):
            c = ws.cell(row=row, column=j, value=v)
            if isinstance(v, date):
                c.number_format = "DD.MM.YYYY"
            if j in (9, 10, 11):
                c.number_format = "#,##0.00"
        sn += r["net"]
        sv += r["vat"]
        sb += r["gross"]
        row += 1
    row += 1
    ws.cell(row=row, column=7, value="Summe").font = Font(bold=True)
    for j, v in ((9, sn), (10, sv), (11, sb)):
        c = ws.cell(row=row, column=j, value=v / 100)
        c.number_format = "#,##0.00"
        c.font = Font(bold=True)
    ws.freeze_panes = "A5"
    wb.save(path)


def write_sonder(path: Path, dv: dict):
    wb = openpyxl.Workbook()
    fixed_props(wb)
    ws = wb.active
    ws.title = "Sonderreinigung 2026"
    xl_title(ws, [("Sonderaufträge 2026 (Glas, Grund-, Teppich-, Bauendreinigung)", True),
                  (f"Stand {dde(dv['cut'])}", False)])
    heads = ["Auftrag", "Eingang", "Kd.-Nr.", "Kunde", "Obj.-Nr.", "Leistung", "Termin", "erledigt am", "Std. (Ist)",
             "Preis netto", "Angebot", "Re.-Nr.", "Status", "Bemerkung"]
    xl_header(ws, 4, heads, [11, 11, 8, 36, 9, 62, 11, 11, 9, 11, 10, 11, 11, 44])
    row = 5
    cut = dv["cut"]
    for s in SONDER:
        if s["eingang"] > cut:
            continue
        inv = next((r for r in INV if r["sa"] == s["sa"] and r.get("tag") == "sonder" and r["date"] <= cut), None)
        done = s["done"] if (s["done"] and s["done"] <= cut and s["list_done"]) else None
        re_no = inv["no"] if inv else None
        if s["sa"] == "SA-26-029":
            re_no = None  # K20: invoiced, list not updated
        if re_no:
            status = "berechnet"
        elif done:
            status = "erledigt"
        elif s["termin"]:
            status = "geplant"
        else:
            status = "angefragt"
        bem = s["bem"]
        if s["sa"] == "SA-26-031" and dv["n"] == 1:
            bem = "Anzahlung 1.500,00 € vereinbart, Termin 28.–30.09."
        vals = [s["sa"], s["eingang"], s["kd"], CUSTOMERS[s["kd"]]["name"], s["ob"] or None, s["leistung"], s["termin"],
                done, s["std"] if done else None, s["net"] / 100, s["angebot"] or None, re_no, status, bem or None]
        for j, v in enumerate(vals, start=1):
            c = ws.cell(row=row, column=j, value=v)
            if isinstance(v, date):
                c.number_format = "DD.MM.YYYY"
            if j == 10:
                c.number_format = "#,##0.00"
        row += 1
    wb.save(path)


ANGEBOTE = [
    ("A-26-002", "2026-01-19", "Logopädie Wortschatz", "Bahnhofsallee 9", "Praxisreinigung 120 m², 2x/Woche", "Vertrag", 34000, "abgelehnt", None, "zu teuer, anderer Anbieter"),
    ("A-26-005", "2026-02-16", "Möbelhaus Sievers KG", "Am Marienfriedhof 1", "Glasreinigung Schaufenster 2026 (3 Termine)", "Sonder", 38000, "angenommen", None, "SA-26-001, -014, ..."),
    ("A-26-008", "2026-03-23", "Autohaus Wendt GmbH", "Porschestraße 10", "Glasreinigung Showroom Frühjahr", "Sonder", 69000, "angenommen", None, "SA-26-006"),
    ("A-26-011", "2026-05-28", "Coworking Altstadt UG", "Andreasplatz 2", "Unterhaltsreinigung 290 m², 3x/Woche", "Vertrag", 64000, "angenommen", None, "Vertrag ab 01.07.2026 (OB-107)"),
    ("A-26-012", "2026-06-02", "Stadt Hildesheim, FB 65", "Lindenhofweg 1", "Grundreinigung Schule Sommerferien", "Sonder", 340000, "angenommen", None, "SA-26-018"),
    ("A-26-013", "2026-06-10", "Wohnungsbaugenossenschaft Innerste eG", "Bergstraße 40–50", "Fassadenreinigung Eingänge", "Sonder", 118000, "angenommen", None, "SA-26-016"),
    ("A-26-014", "2026-06-15", "Ev. Kita Sonnenblume", "Elzer Straße 41", "Grundreinigung Sommerschließung", "Sonder", 186000, "angenommen", None, "SA-26-024"),
    ("A-26-016", "2026-07-20", "Autohaus Wendt GmbH", "Porschestraße 10", "Glasreinigung Showroom Herbst mit Hubsteiger", "Sonder", 115000, "angenommen", None, "SA-26-027"),
    ("A-26-017", "2026-07-28", "Gästehaus Am Galgenberg", "Am Galgenberg 3", "Unterhaltsreinigung Flure/Frühstücksraum", "Vertrag", 52000, "abgelehnt", None, "macht es selbst"),
    ("A-26-019", "2026-08-25", "Kinderarztpraxis Dr. Behrens", "Marienburger Höhe 14", "Bauendreinigung Neubau Praxis", "Sonder", 290000, "angenommen", None, "Anzahlung 1.500 €, SA-26-031"),
    ("A-26-020", "2026-08-28", "Tierarztpraxis Dr. Albers", "Ottostraße 70", "Praxisreinigung inkl. OP, 3x/Woche, ab 01.10.", "Vertrag", 42000, "angenommen", None, "angenommen 12.09., OB-151"),
    ("A-26-021", "2026-08-31", "Steuerbüro Wilkens", "Zingel 30", "Unterhaltsreinigung 210 m², 2x/Woche", "Vertrag", 48000, "offen", D("2026-09-15"), "Herr Wilkens wollte im Urlaub entscheiden"),
]
ANGEBOTE_L2 = [
    ("A-26-022", "2026-09-21", "Logopädie Sprachraum", "Goslarsche Straße 12", "Praxisreinigung 140 m², 2x/Woche, ab 01.11.", "Vertrag", 36000, "offen", D("2026-10-05"), "Anfrage per Mail 16.09., Besichtigung 21.09."),
    ("A-26-023", "2026-10-12", "Autohaus Wendt GmbH", "Porschestraße 10", "Fassadenreinigung Werkstatthalle", "Sonder", 240000, "offen", D("2026-10-27"), ""),
    ("A-26-024", "2026-10-14", "Zahnarztpraxis Dr. Schäfer", "Almsstraße 15", "Grundreinigung PVC 4 Behandlungsräume mit Einpflege", "Sonder", 62000, "offen", D("2026-10-28"), "telefonisch zugesagt?"),
]


def write_angebote(path: Path, dv: dict):
    wb = openpyxl.Workbook()
    fixed_props(wb)
    ws = wb.active
    ws.title = "Angebote"
    xl_title(ws, [("Angebote 2026", True), ("", False)])
    xl_header(ws, 3, ["Angebot", "Datum", "Interessent / Kunde", "Objektadresse", "Leistung", "Art", "Preis netto",
                      "Status", "Nachfassen am", "Bemerkung"], [10, 11, 34, 26, 50, 8, 11, 11, 13, 40])
    rows = list(ANGEBOTE) + (ANGEBOTE_L2 if dv["n"] == 2 else [])
    for i, a in enumerate(rows, start=4):
        a = list(a)
        if dv["n"] == 2 and a[0] == "A-26-021":
            a[7], a[8], a[9] = "abgelehnt", None, "Absage per Telefon 28.09. (zu teuer)"
        if dv["n"] == 2 and a[0] == "A-26-024":
            a[7], a[8], a[9] = "angenommen", None, "Auftrag per Mail 21.10. für 07.11."
        for j, v in enumerate([a[0], D(a[1]), a[2], a[3], a[4], a[5], a[6] / 100, a[7], a[8], a[9] or None], start=1):
            c = ws.cell(row=i, column=j, value=v)
            if isinstance(v, date):
                c.number_format = "DD.MM.YYYY"
            if j == 7:
                c.number_format = "#,##0.00"
    wb.save(path)


def write_mitarbeiter(path: Path, dv: dict):
    wb = openpyxl.Workbook()
    fixed_props(wb)
    ws = wb.active
    ws.title = "Personal"
    xl_title(ws, [("Mitarbeiterliste", True), (f"Stand {dde(dv['cut'])}", False)])
    xl_header(ws, 3, ["Pers.-Nr.", "Name", "Vorname", "Funktion", "Eintritt", "Beschäftigung", "Wochenstd.", "Lohngruppe",
                      "Std.-Lohn €", "Stammobjekte"], [9, 14, 12, 28, 11, 12, 10, 12, 10, 60])
    for i, (p, e) in enumerate(sorted(EMP.items()), start=4):
        objs = ", ".join(OBJ[ob]["kurz"] for ob, ps in ASSIGN.items() if p in ps and (ob != "OB-151" or dv["n"] == 2))
        for j, v in enumerate([p, e["name"], e["vorname"], e["funktion"], e["eintritt"], e["art"], e["h"], e["lg"], e["lohn"],
                               objs or None], start=1):
            c = ws.cell(row=i, column=j, value=v)
            if isinstance(v, date):
                c.number_format = "DD.MM.YYYY"
    wb.save(path)


START = {"Büro": 17.5, "Praxis": 19.0, "Wohnen": 9.0, "Öffentlich": 15.0, "Gewerbe": 6.5}


def absences():
    """(persnr, from, to, kind, substitute?) – summer holidays and sick days; Okonkwo week without cover (K12)."""
    out = [(107, D("2026-08-03"), D("2026-08-07"), "krank (AU)", False)]
    for p in EMP:
        if p in (101, 102):
            continue
        g = rr("abs", p)
        if p in (105, 108, 115):
            s = D("2026-07-13") + timedelta(days=7 * g.randint(0, 2))
        else:
            s = D("2026-06-22") + timedelta(days=7 * g.randint(0, 9))
        if p == 107:
            s = D("2026-06-29")
        out.append((p, s, s + timedelta(days=11), "Urlaub", True))
        if g.random() < 0.6:
            s2 = D("2026-06-01") + timedelta(days=g.randint(0, 140))
            if not (p == 107 and D("2026-07-27") <= s2 <= D("2026-08-10")):
                out.append((p, s2, s2 + timedelta(days=g.randint(1, 4)), "krank (AU)", True))
    return out


def timesheet_rows(y: int, m: int, cut: date) -> dict[int, list]:
    rows = {p: [] for p in EMP if p != 102}
    absn = absences()

    def absent(p, d):
        for q, a, b, kind, sub in absn:
            if q == p and a <= d <= b:
                return kind, sub
        return None

    last = min(month_end(y, m), cut)
    d = date(y, m, 1)
    pool = [p for p in EMP if p not in (101, 102, 112, 123)]
    while d <= last:
        if d.weekday() < 6 and d not in HOL:
            wd_ = WT[d.weekday()]
            for p in rows:
                a = absent(p, d)
                if a and d.weekday() < 5:
                    rows[p].append([d, wd_, "", None, None, None, None, a[0]])
            plan: dict[int, list] = {}
            load: dict[int, float] = {}
            for o in OBJECTS:
                if o["ob"] == "OB-099" or not (o["beginn"] <= d and (o["gek"] is None or d <= o["gek"])):
                    continue
                if wd_ not in o["days"].split(","):
                    continue
                if o["ob"] == "OB-132" and any(a <= d <= b for a, b in SCHOOL_HOLIDAYS):
                    continue
                visits = len(o["days"].split(",")) * 4.33
                h_total = max(1.0, round(o["net"] / 100 / 27.5 / visits * 4) / 4)
                staff = ASSIGN.get(o["ob"], [113])
                share = round(h_total / len(staff) * 4) / 4
                for p in staff:
                    who, bem = p, ""
                    a = absent(p, d)
                    if a:
                        if not a[1]:
                            continue  # nobody went (Okonkwo, 03.-07.08.)
                        free = [q for q in pool if not absent(q, d) and q not in staff]
                        who = min(free, key=lambda q: (load.get(q, 0) + (2.0 if EMP[q]["art"] == "Minijob" else 0), q))
                        bem = f"Vertretung {EMP[p]['name']}"
                    load[who] = load.get(who, 0) + share
                    plan.setdefault(who, []).append((START[o["art"]], o, share, bem))
            for who, vis in plan.items():
                vis.sort(key=lambda v: (v[0], v[1]["ob"]))
                cur, morning = None, 5.5
                for pref, o, share, bem in vis:
                    st = pref if cur is None or pref >= cur else cur
                    if st + share > 22.5:
                        st = morning
                        morning = st + share + 0.5
                    else:
                        cur = st + share + 0.5
                    rows[who].append([d, wd_, o["kurz"], st, st + share, 0, share, bem])
            if d.weekday() < 5 and d.day % 3 == 0:
                o = OBJECTS[(d.toordinal() // 3) % (len(OBJECTS) - 2)]
                rows[101].append([d, wd_, o["kurz"], 10.0, 11.0, 0, 1.0, "Objektkontrolle"])
            for s in SONDER:
                if s["done"] and s["termin"] <= d <= s["done"] and d <= cut:
                    ndays = sum(1 for k in range((s["done"] - s["termin"]).days + 1)
                                if (s["termin"] + timedelta(days=k)).weekday() < 6)
                    team = [p if not absent(p, d) else 117 for p in s["emps"]]
                    team = [p for p in dict.fromkeys(team) if not absent(p, d)]
                    hh = round(s["std"] / ndays / max(1, len(team)) * 4) / 4
                    for p in team:
                        txt = f"Sonderreinigung {s['sa']} – {s['leistung'].split(' (')[0]}"
                        if s["sub"]:
                            txt += " mit Fa. Petrovic"
                        rows[p].append([d, wd_, OBJ[s["ob"]]["kurz"] if s["ob"] else "Neubau Dr. Behrens", 7.0, 7.0 + hh, 0,
                                        hh, txt])
        d += timedelta(days=1)
    for p in rows:
        rows[p].sort(key=lambda r: (r[0], r[3] if r[3] is not None else -1))
    return rows


def hm(x):
    if x is None:
        return None
    h = int(x)
    return f"{h:02d}:{int(round((x - h) * 60)):02d}"


def write_stunden(path: Path, y: int, m: int, cut: date):
    wb = openpyxl.Workbook()
    fixed_props(wb)
    wb.remove(wb.active)
    rows = timesheet_rows(y, m, cut)
    for p, rs in sorted(rows.items()):
        e = EMP[p]
        ws = wb.create_sheet(f"{p} {e['name']}"[:31])
        ws.cell(row=1, column=1, value=f"Stundennachweis {MONATE[m - 1]} {y}").font = Font(bold=True, size=12)
        ws.cell(row=2, column=1, value=f"Mitarbeiter/in: {e['vorname']} {e['name']}   Pers.-Nr. {p}   ({e['art']}, {e['h']} Std./Woche)")
        xl_header(ws, 4, ["Datum", "Tag", "Objekt", "Beginn", "Ende", "Pause (Min.)", "Std.", "Bemerkung"],
                  [11, 5, 18, 7, 7, 8, 6, 52])
        r = 5
        tot = 0.0
        for dd, wd_, obj, st, en, pause, h, bem in rs:
            vals = [dd, wd_, obj or None, hm(st), hm(en), pause, h, bem or None]
            for j, v in enumerate(vals, start=1):
                c = ws.cell(row=r, column=j, value=v)
                if isinstance(v, date):
                    c.number_format = "DD.MM.YYYY"
            tot += h or 0
            r += 1
        ws.cell(row=r + 1, column=3, value="Summe").font = Font(bold=True)
        ws.cell(row=r + 1, column=7, value=round(tot, 2)).font = Font(bold=True)
        ws.cell(row=r + 3, column=1, value="Unterschrift Mitarbeiter/in: ____________   Objektleitung: ____________")
    wb.save(path)


def write_bank(path: Path, dv: dict):
    cut = dv["cut"]
    heads = ["Auftragskonto", "Buchungstag", "Valutadatum", "Buchungstext", "Verwendungszweck", "Glaeubiger ID",
             "Mandatsreferenz", "Kundenreferenz (End-to-End)", "Sammlerreferenz", "Lastschrift Ursprungsbetrag",
             "Auslagenersatz Ruecklastschrift", "Beguenstigter/Zahlungspflichtiger", "Kontonummer/IBAN",
             "BIC (SWIFT-Code)", "Betrag", "Waehrung", "Info"]
    evs = [e for e in EV if e["bank"] and e["date"] <= cut]
    bal = 3148217 + sum(e["amount"] for e in evs)
    q = lambda v: '"' + str(v).replace('"', "'") + '"'
    lines = [";".join(q(x) for x in ("Umsätze Girokonto", fmt_iban(FIRM["iban"]))),
             ";".join(q(x) for x in ("Kontoinhaber:", FIRM["name"])),
             ";".join(q(x) for x in ("Zeitraum:", f"01.01.2026 - {dde(cut)}")),
             ";".join(q(x) for x in (f"Kontostand vom {dde(cut)}:", de(bal) + " EUR")),
             "",
             ";".join(q(h) for h in heads)]
    for e in sorted(evs, key=lambda e: (e["date"], e["id"]), reverse=True):
        vals = [FIRM["iban"], dshort(e["date"]), dshort(e["date"]), e["btext"], e["vwz"], e["ci"], e["mandate"], e["e2e"],
                e["sammler"], e["urspr"], e["auslagen"], e["payer"], e["iban"], e["bic"], csvamt(e["amount"]), "EUR",
                "Umsatz gebucht"]
        lines.append(";".join(q(v) for v in vals))
    path.write_bytes(("\r\n".join(lines) + "\r\n").encode("cp1252", errors="replace"))


def sepa_name(s: str) -> str:
    tr = {"ä": "ae", "ö": "oe", "ü": "ue", "Ä": "Ae", "Ö": "Oe", "Ü": "Ue", "ß": "ss", "ı": "i", "–": "-", "&": "+"}
    return "".join(tr.get(ch, ch) for ch in s)[:70]


def write_sepa(path: Path, b: dict):
    d = b["date"]
    created = datetime.combine(d - timedelta(days=2), datetime.min.time()).replace(hour=16, minute=42)
    total = sum(x["gross"] for x in b["items"])
    tx = []
    for x in b["items"]:
        c = CUSTOMERS[x["kd"]]
        ib, bic, mand, mdat = c["iban"], c["bic"], c["mandate"], c["since"]
        if x["kd"] == "10032" and d >= D("2026-10-01"):
            ib, bic, mand, mdat = POWERHOUSE_NEW[0], POWERHOUSE_NEW[1], "OST-10032-02", D("2026-09-21")
        per = x.get("period") or "12/2025"
        tx.append(f"""      <DrctDbtTxInf>
        <PmtId><EndToEndId>{x['no']}</EndToEndId></PmtId>
        <InstdAmt Ccy="EUR">{xamt(x['gross'])}</InstdAmt>
        <DrctDbtTx><MndtRltdInf><MndtId>{mand}</MndtId><DtOfSgntr>{mdat.isoformat()}</DtOfSgntr></MndtRltdInf></DrctDbtTx>
        <DbtrAgt><FinInstnId><BICFI>{bic}</BICFI></FinInstnId></DbtrAgt>
        <Dbtr><Nm>{xesc(sepa_name(c['name']))}</Nm></Dbtr>
        <DbtrAcct><Id><IBAN>{ib}</IBAN></Id></DbtrAcct>
        <RmtInf><Ustrd>{xesc(sepa_name(f"Rechnung {x['no']} Reinigung {per} {x['ob']}"))}</Ustrd></RmtInf>
      </DrctDbtTxInf>""")
    xml = f"""<?xml version="1.0" encoding="UTF-8"?>
<Document xmlns="urn:iso:std:iso:20022:tech:xsd:pain.008.001.08" xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">
  <CstmrDrctDbtInitn>
    <GrpHdr>
      <MsgId>OST-LS-{created.strftime('%Y%m%d%H%M')}</MsgId>
      <CreDtTm>{created.strftime('%Y-%m-%dT%H:%M:%S')}</CreDtTm>
      <NbOfTxs>{len(b['items'])}</NbOfTxs>
      <CtrlSum>{xamt(total)}</CtrlSum>
      <InitgPty><Nm>{SEPA_FIRM}</Nm></InitgPty>
    </GrpHdr>
    <PmtInf>
      <PmtInfId>LS-{d.isoformat()}</PmtInfId>
      <PmtMtd>DD</PmtMtd>
      <BtchBookg>true</BtchBookg>
      <NbOfTxs>{len(b['items'])}</NbOfTxs>
      <CtrlSum>{xamt(total)}</CtrlSum>
      <PmtTpInf><SvcLvl><Cd>SEPA</Cd></SvcLvl><LclInstrm><Cd>CORE</Cd></LclInstrm><SeqTp>RCUR</SeqTp></PmtTpInf>
      <ReqdColltnDt>{d.isoformat()}</ReqdColltnDt>
      <Cdtr><Nm>{SEPA_FIRM}</Nm></Cdtr>
      <CdtrAcct><Id><IBAN>{FIRM['iban']}</IBAN></Id></CdtrAcct>
      <CdtrAgt><FinInstnId><BICFI>{FIRM['bic']}</BICFI></FinInstnId></CdtrAgt>
      <ChrgBr>SLEV</ChrgBr>
      <CdtrSchmeId><Id><PrvtId><Othr><Id>{FIRM['ci']}</Id><SchmeNm><Prtry>SEPA</Prtry></SchmeNm></Othr></PrvtId></Id></CdtrSchmeId>
{chr(10).join(tx)}
    </PmtInf>
  </CstmrDrctDbtInitn>
</Document>
"""
    path.write_text(xml, encoding="utf-8")


def write_xrechnung(path: Path, r: dict):
    c = CUSTOMERS[r["kd"]]
    dd = r["date"].strftime("%Y%m%d")
    xml = f"""<?xml version="1.0" encoding="UTF-8"?>
<rsm:CrossIndustryInvoice xmlns:rsm="urn:un:unece:uncefact:data:standard:CrossIndustryInvoice:100" xmlns:ram="urn:un:unece:uncefact:data:standard:ReusableAggregateBusinessInformationEntity:100" xmlns:udt="urn:un:unece:uncefact:data:standard:UnqualifiedDataType:100" xmlns:qdt="urn:un:unece:uncefact:data:standard:QualifiedDataType:100">
  <rsm:ExchangedDocumentContext>
    <ram:BusinessProcessSpecifiedDocumentContextParameter><ram:ID>urn:fdc:peppol.eu:2017:poacc:billing:01:1.0</ram:ID></ram:BusinessProcessSpecifiedDocumentContextParameter>
    <ram:GuidelineSpecifiedDocumentContextParameter><ram:ID>urn:cen.eu:en16931:2017#compliant#urn:xeinkauf.de:kosit:xrechnung_3.0</ram:ID></ram:GuidelineSpecifiedDocumentContextParameter>
  </rsm:ExchangedDocumentContext>
  <rsm:ExchangedDocument>
    <ram:ID>{r['no']}</ram:ID>
    <ram:TypeCode>380</ram:TypeCode>
    <ram:IssueDateTime><udt:DateTimeString format="102">{dd}</udt:DateTimeString></ram:IssueDateTime>
    <ram:IncludedNote><ram:Content>{xesc(r['text'])} – Objekt {r['ob']} Grundschule Am Lindenhof (Zweitschrift als XRechnung)</ram:Content></ram:IncludedNote>
  </rsm:ExchangedDocument>
  <rsm:SupplyChainTradeTransaction>
    <ram:IncludedSupplyChainTradeLineItem>
      <ram:AssociatedDocumentLineDocument><ram:LineID>1</ram:LineID></ram:AssociatedDocumentLineDocument>
      <ram:SpecifiedTradeProduct><ram:Name>{xesc(r['text'])}</ram:Name></ram:SpecifiedTradeProduct>
      <ram:SpecifiedLineTradeAgreement><ram:NetPriceProductTradePrice><ram:ChargeAmount>{xamt(r['net'])}</ram:ChargeAmount></ram:NetPriceProductTradePrice></ram:SpecifiedLineTradeAgreement>
      <ram:SpecifiedLineTradeDelivery><ram:BilledQuantity unitCode="MON">1</ram:BilledQuantity></ram:SpecifiedLineTradeDelivery>
      <ram:SpecifiedLineTradeSettlement>
        <ram:ApplicableTradeTax><ram:TypeCode>VAT</ram:TypeCode><ram:CategoryCode>S</ram:CategoryCode><ram:RateApplicablePercent>19</ram:RateApplicablePercent></ram:ApplicableTradeTax>
        <ram:SpecifiedTradeSettlementLineMonetarySummation><ram:LineTotalAmount>{xamt(r['net'])}</ram:LineTotalAmount></ram:SpecifiedTradeSettlementLineMonetarySummation>
      </ram:SpecifiedLineTradeSettlement>
    </ram:IncludedSupplyChainTradeLineItem>
    <ram:ApplicableHeaderTradeAgreement>
      <ram:BuyerReference>{c['leitweg']}</ram:BuyerReference>
      <ram:SellerTradeParty>
        <ram:Name>{xesc(FIRM['name'])}</ram:Name>
        <ram:DefinedTradeContact><ram:PersonName>Renate Fiedler</ram:PersonName><ram:TelephoneUniversalCommunication><ram:CompleteNumber>{FIRM['phone']}</ram:CompleteNumber></ram:TelephoneUniversalCommunication><ram:EmailURIUniversalCommunication><ram:URIID>{FIRM['buch']}</ram:URIID></ram:EmailURIUniversalCommunication></ram:DefinedTradeContact>
        <ram:PostalTradeAddress><ram:PostcodeCode>{FIRM['plz']}</ram:PostcodeCode><ram:LineOne>{xesc(FIRM['street'])}</ram:LineOne><ram:CityName>{FIRM['city']}</ram:CityName><ram:CountryID>DE</ram:CountryID></ram:PostalTradeAddress>
        <ram:URIUniversalCommunication><ram:URIID schemeID="EM">{FIRM['buch']}</ram:URIID></ram:URIUniversalCommunication>
        <ram:SpecifiedTaxRegistration><ram:ID schemeID="VA">{FIRM['ustid']}</ram:ID></ram:SpecifiedTaxRegistration>
      </ram:SellerTradeParty>
      <ram:BuyerTradeParty>
        <ram:Name>{xesc(c['name'] + ', ' + c['zusatz'])}</ram:Name>
        <ram:PostalTradeAddress><ram:PostcodeCode>{c['plz']}</ram:PostcodeCode><ram:LineOne>{xesc(c['street'])}</ram:LineOne><ram:CityName>{c['city']}</ram:CityName><ram:CountryID>DE</ram:CountryID></ram:PostalTradeAddress>
        <ram:URIUniversalCommunication><ram:URIID schemeID="EM">{c['email']}</ram:URIID></ram:URIUniversalCommunication>
      </ram:BuyerTradeParty>
    </ram:ApplicableHeaderTradeAgreement>
    <ram:ApplicableHeaderTradeDelivery><ram:ActualDeliverySupplyChainEvent><ram:OccurrenceDateTime><udt:DateTimeString format="102">{dd}</udt:DateTimeString></ram:OccurrenceDateTime></ram:ActualDeliverySupplyChainEvent></ram:ApplicableHeaderTradeDelivery>
    <ram:ApplicableHeaderTradeSettlement>
      <ram:InvoiceCurrencyCode>EUR</ram:InvoiceCurrencyCode>
      <ram:SpecifiedTradeSettlementPaymentMeans><ram:TypeCode>58</ram:TypeCode><ram:PayeePartyCreditorFinancialAccount><ram:IBANID>{FIRM['iban']}</ram:IBANID><ram:AccountName>{xesc(FIRM['name'])}</ram:AccountName></ram:PayeePartyCreditorFinancialAccount></ram:SpecifiedTradeSettlementPaymentMeans>
      <ram:ApplicableTradeTax><ram:CalculatedAmount>{xamt(r['vat'])}</ram:CalculatedAmount><ram:TypeCode>VAT</ram:TypeCode><ram:BasisAmount>{xamt(r['net'])}</ram:BasisAmount><ram:CategoryCode>S</ram:CategoryCode><ram:RateApplicablePercent>19</ram:RateApplicablePercent></ram:ApplicableTradeTax>
      <ram:BillingSpecifiedPeriod><ram:StartDateTime><udt:DateTimeString format="102">{r['date'].strftime('%Y%m')}01</udt:DateTimeString></ram:StartDateTime><ram:EndDateTime><udt:DateTimeString format="102">{month_end(r['date'].year, r['date'].month).strftime('%Y%m%d')}</udt:DateTimeString></ram:EndDateTime></ram:BillingSpecifiedPeriod>
      <ram:SpecifiedTradePaymentTerms><ram:Description>Zahlbar innerhalb von 30 Tagen ohne Abzug</ram:Description><ram:DueDateDateTime><udt:DateTimeString format="102">{r['due'].strftime('%Y%m%d')}</udt:DateTimeString></ram:DueDateDateTime></ram:SpecifiedTradePaymentTerms>
      <ram:SpecifiedTradeSettlementHeaderMonetarySummation>
        <ram:LineTotalAmount>{xamt(r['net'])}</ram:LineTotalAmount>
        <ram:TaxBasisTotalAmount>{xamt(r['net'])}</ram:TaxBasisTotalAmount>
        <ram:TaxTotalAmount currencyID="EUR">{xamt(r['vat'])}</ram:TaxTotalAmount>
        <ram:GrandTotalAmount>{xamt(r['gross'])}</ram:GrandTotalAmount>
        <ram:DuePayableAmount>{xamt(r['gross'])}</ram:DuePayableAmount>
      </ram:SpecifiedTradeSettlementHeaderMonetarySummation>
    </ram:ApplicableHeaderTradeSettlement>
  </rsm:SupplyChainTradeTransaction>
</rsm:CrossIndustryInvoice>
"""
    path.write_text(xml, encoding="utf-8")


def pdf_invoice(path: Path, x: dict, copy: bool = False, fraud: bool = False) -> bytes:
    s = SUPPLIERS[x["sup"]]
    ib, bic = (FRAUD_IBAN, "REVOLT21XXX") if fraud else (s["iban"], s["bic"])
    c = canvas.Canvas(str(path), pagesize=A4, invariant=1)
    c.setTitle(f"Rechnung {x['no']}")
    W, H = A4
    c.setFont("Helvetica-Bold", 15)
    c.drawString(20 * mm, H - 22 * mm, s["name"])
    c.setFont("Helvetica", 8.5)
    c.drawString(20 * mm, H - 28 * mm, f"{s['street']} · {s['plz']} {s['city']} · Tel. {s['phone']} · "
                 f"{'buchhaltung@nordhaus-hygiene.co' if fraud else s['mail']}")
    if copy:
        c.setFont("Helvetica-Bold", 22)
        c.setFillGray(0.6)
        c.drawString(140 * mm, H - 22 * mm, "KOPIE")
        c.setFillGray(0)
    c.setFont("Helvetica", 7)
    c.drawString(20 * mm, H - 45 * mm, f"{s['name']}, {s['street']}, {s['plz']} {s['city']}")
    c.setFont("Helvetica", 10)
    for i, t in enumerate([FIRM["name"], "z. Hd. Buchhaltung", FIRM["street"], f"{FIRM['plz']} {FIRM['city']}"]):
        c.drawString(20 * mm, H - (51 + 5 * i) * mm, t)
    meta = [("Rechnung Nr.", x["no"]), ("Rechnungsdatum", dde(x["date"])), ("Kunden-Nr.", s["kdnr"]),
            ("Leistungsdatum", dde(x["date"]) if x["sup"] != "engel" else f"{x['date'].month:02d}/{x['date'].year}")]
    if copy:
        meta.append(("Zweitschrift vom", "02.09.2026"))
    for i, (k, v) in enumerate(meta):
        c.drawString(125 * mm, H - (51 + 5 * i) * mm, k)
        c.drawRightString(190 * mm, H - (51 + 5 * i) * mm, v)
    c.setFont("Helvetica-Bold", 13)
    c.drawString(20 * mm, H - 88 * mm, ("Korrigierte Rechnung " if fraud else "Rechnung ") + x["no"])
    y = H - 100 * mm
    c.setFont("Helvetica-Bold", 9)
    for xx, t in ((20, "Pos."), (32, "Bezeichnung"), (139, "Menge"), (141, "Einheit"), (172, "E-Preis €"), (190, "Gesamt €")):
        (c.drawRightString if t.endswith("€") or t == "Menge" else c.drawString)(xx * mm, y, t)
    c.line(20 * mm, y - 2 * mm, 190 * mm, y - 2 * mm)
    c.setFont("Helvetica", 9)
    y -= 7 * mm
    for pos, t, q, u, p in x["lines"]:
        c.drawString(20 * mm, y, str(pos))
        c.setFont("Helvetica", 8.5)
        c.drawString(32 * mm, y, t[:64])
        c.setFont("Helvetica", 9)
        c.drawRightString(139 * mm, y, (f"{q:.1f}".replace(".", ",") if isinstance(q, float) else str(q)))
        c.drawString(141 * mm, y, u)
        c.drawRightString(172 * mm, y, de(p))
        c.drawRightString(190 * mm, y, de(int(round(q * p))))
        y -= 5.5 * mm
    c.line(120 * mm, y, 190 * mm, y)
    y -= 6 * mm
    rows = [("Summe netto", de(x["net"]))]
    if x["vat"] == 19:
        rows.append(("zzgl. 19 % USt", de(x["vatc"])))
    else:
        rows.append(("Umsatzsteuer", "0,00"))
    rows.append(("Rechnungsbetrag", de(x["gross"]) + " €"))
    for k, v in rows:
        c.setFont("Helvetica-Bold" if k == "Rechnungsbetrag" else "Helvetica", 10)
        c.drawString(120 * mm, y, k)
        c.drawRightString(190 * mm, y, v)
        y -= 6 * mm
    c.setFont("Helvetica", 9)
    y -= 4 * mm
    notes = []
    if x["vat"] == 0:
        notes.append("Steuerschuldnerschaft des Leistungsempfängers (§ 13b Abs. 2 Nr. 8 UStG) – Gebäudereinigungsleistung.")
        notes.append(f"Ihre Bescheinigung USt 1 TG liegt uns vor. Steuernummer {s.get('stnr', '')}.")
    if x["skonto"]:
        notes.append(f"Zahlbar bis {dde(x['skonto_until'])} mit {x['skonto'][0]} % Skonto "
                     f"({de(x['gross'] - pct(x['gross'], x['skonto'][0]))} €) oder bis {dde(x['due'])} netto.")
    else:
        notes.append(f"Zahlbar ohne Abzug bis {dde(x['due'])}.")
    if fraud:
        notes.append("ACHTUNG: Bitte beachten Sie unsere NEUE Bankverbindung. Zahlungen auf das alte Konto")
        notes.append("können nicht mehr zugeordnet werden.")
    for t in notes:
        c.drawString(20 * mm, y, t)
        y -= 5 * mm
    c.setFont("Helvetica", 7.5)
    bank_name = "Revolut Bank UAB" if fraud else BANKS[s["bank"]][2]
    foot = [f"{s['name']} · {s['gf']}" + (f" · {s['hrb']}" if s["hrb"] else ""),
            f"Bankverbindung: {bank_name} · IBAN {fmt_iban(ib)} · BIC {bic}",
            (f"USt-IdNr. {s['ustid']}" if s["ustid"] else f"Steuernummer {s.get('stnr', '')}") + (f" · {s['web']}" if s["web"] else "")]
    for i, t in enumerate(foot):
        c.drawString(20 * mm, 22 * mm - i * 4 * mm, t)
    c.showPage()
    c.save()
    return path.read_bytes()


def tz_for(d: date):
    return timezone(timedelta(hours=1 if d >= D("2026-10-25") else 2))


def write_eml(path: Path, frm: str, to: str, when: str, subject: str, body: str, attachments=(), reply_to_id=None, mid=None):
    dt = datetime.fromisoformat(when)
    dt = dt.replace(tzinfo=tz_for(dt.date()))
    msg = EmailMessage()
    msg["From"] = frm
    msg["To"] = to
    msg["Date"] = format_datetime(dt)
    msg["Subject"] = subject
    dom = frm.split("@")[-1].strip(">")
    msg["Message-ID"] = mid or f"<{hashlib.md5((when + subject).encode()).hexdigest()[:16]}@{dom}>"
    if reply_to_id:
        msg["In-Reply-To"] = reply_to_id
        msg["References"] = reply_to_id
    msg["MIME-Version"] = "1.0"
    msg.set_content(body)
    for name, data in attachments:
        msg.add_attachment(data, maintype="application", subtype="pdf", filename=name)
    path.write_bytes(bytes(msg))
    return msg["Message-ID"]


OWN = f"Katrin Ostermeier <k.ostermeier@ostermeier-gd.de>"
OWN_INFO = "Ostermeier Gebäudedienste <info@ostermeier-gd.de>"
SIG = "\n\nMit freundlichen Grüßen\nKatrin Ostermeier\nGeschäftsführerin\n\nOstermeier Gebäudedienste GmbH\nBavenstedter Straße 48 · 31135 Hildesheim\nTel. 05121 99876-0 · www.ostermeier-gd.de\n"


def write_mails(folder: Path, dv: dict, pdfs: dict):
    cut = dv["cut"]
    n = dv["n"]
    a103, a111, a136, a144 = inv_of("OB-103", 8), inv_of("OB-111", 8), inv_of("OB-136", 8), [inv_of("OB-144", m) for m in (6, 7)]
    gs = next(x for x in INV if x.get("tag") == "credit")
    mails = []

    def M(when, fname, *args, **kw):
        if D(when[:10]) <= cut:
            mails.append((when, fname, args, kw))

    M("2026-05-20T10:14:00", "Kündigung Reinigungsvertrag Schuhstraße 31.eml",
      "Jürgen Krämer <j.kraemer@kraemer-versicherungen.de>", OWN_INFO, "Kündigung Reinigungsvertrag Schuhstraße 31",
      "Sehr geehrte Frau Ostermeier,\n\nhiermit kündige ich den Reinigungsvertrag für unser Büro in der Schuhstraße 31 "
      "(Ihr Objekt OB-105) fristgerecht zum 31.08.2026. Wir legen das Büro mit der Agentur in Hildesheim-Ost zusammen, "
      "dort ist die Reinigung über den Vermieter geregelt.\n\nMit Ihrer Arbeit waren wir immer sehr zufrieden – bitte "
      "richten Sie Frau Kruse unseren Dank aus.\n\nBitte bestätigen Sie mir kurz den Eingang der Kündigung.\n\n"
      "Mit freundlichen Grüßen\nJürgen Krämer\nVersicherungsbüro Krämer – Generalagentur\nSchuhstraße 31, 31134 Hildesheim\n")
    M("2026-05-21T08:40:00", "AW Kündigung Reinigungsvertrag Schuhstraße 31.eml", OWN, "Jürgen Krämer <j.kraemer@kraemer-versicherungen.de>",
      "AW: Kündigung Reinigungsvertrag Schuhstraße 31",
      "Sehr geehrter Herr Krämer,\n\nvielen Dank für Ihre Nachricht. Hiermit bestätigen wir die Kündigung des Reinigungs"
      "vertrags für die Schuhstraße 31 zum 31.08.2026. Die letzte Unterhaltsreinigung findet am Mittwoch, 26.08.2026, "
      "statt; den Schlüssel gibt Frau Kruse danach bei Ihnen ab.\n\nVielen Dank für die langjährige Zusammenarbeit!" + SIG)
    M("2026-06-24T14:02:00", "Angebot A-26-014 Grundreinigung Sommerschließung.eml",
      "Heike Rust <kita.sonnenblume@evlka-hi.de>", OWN_INFO, "Angebot A-26-014 Grundreinigung Sommerschließung",
      "Sehr geehrte Frau Ostermeier,\n\nwir nehmen Ihr Angebot A-26-014 vom 15.06.2026 über die Grundreinigung unserer "
      "Gruppenräume und Flure während der Sommerschließung zum Preis von 1.860,00 € netto an. Die Kita ist vom 10. bis "
      "14. August geschlossen, den Schlüssel bekommen Sie wie immer über Frau Kaya.\n\nRechnung bitte wie immer an die "
      "Kita, Kostenstelle 4711.\n\nViele Grüße\nHeike Rust\nLeitung Ev. Kita Sonnenblume\n")
    m_rek = None
    M("2026-08-12T07:52:00", "Reklamation - Reinigung fand letzte Woche nicht statt.eml",
      "Praxis Dr. Okonkwo <praxis@zahnarzt-okonkwo.de>", OWN_INFO, "Reklamation – Reinigung fand letzte Woche nicht statt",
      "Sehr geehrte Damen und Herren,\n\nin der vergangenen Woche (03.–07.08.) ist unsere Praxis an keinem der vereinbarten "
      "Tage gereinigt worden. Die Abfallbehälter in den Behandlungsräumen waren am Montag überfüllt, die Böden im "
      "Wartebereich nicht gewischt. Für eine Zahnarztpraxis ist das hygienisch nicht hinnehmbar.\n\nWir erwarten, dass die "
      "ausgefallenen Reinigungen bei der Abrechnung für August berücksichtigt werden und dass so etwas nicht noch einmal "
      "vorkommt.\n\nMit freundlichen Grüßen\nClaudia Weiß\nPraxismanagerin – Zahnarztpraxis Dr. Okonkwo\n",
      mid="<rek-0812@zahnarzt-okonkwo.de>")
    M("2026-08-12T11:30:00", "AW Reklamation - Reinigung fand letzte Woche nicht statt.eml", OWN,
      "Praxis Dr. Okonkwo <praxis@zahnarzt-okonkwo.de>", "AW: Reklamation – Reinigung fand letzte Woche nicht statt",
      "Sehr geehrte Frau Weiß,\n\nbitte entschuldigen Sie den Ausfall. Unsere Mitarbeiterin war erkrankt, und die "
      "Vertretung hat in dieser Woche leider nicht geklappt – das hätte nicht passieren dürfen.\n\nWir kommen am Freitag, "
      "14.08., für eine gründliche Nachreinigung (selbstverständlich kostenlos) und schreiben Ihnen für August eine "
      "Gutschrift über 25 % der Monatspauschale.\n\nIch habe mit unserer Objektleitung vereinbart, dass Ihre Praxis künftig "
      "eine feste Vertretung hat." + SIG, reply_to_id="<rek-0812@zahnarzt-okonkwo.de>")
    M("2026-08-20T09:10:00", "Zahlungserinnerung Tanzschule Rhythmus.eml", "Renate Fiedler <buchhaltung@ostermeier-gd.de>",
      "Marco Bellini <info@tanzschule-rhythmus.de>", "Zahlungserinnerung – offene Rechnungen Juni und Juli",
      f"Sehr geehrter Herr Bellini,\n\nbei der Durchsicht unserer Konten ist uns aufgefallen, dass folgende Rechnungen "
      f"noch offen sind:\n\n  {a144[0]['no']} vom {dde(a144[0]['date'])}   {de(a144[0]['gross'])} €\n"
      f"  {a144[1]['no']} vom {dde(a144[1]['date'])}   {de(a144[1]['gross'])} €\n\nSicher ist das nur übersehen worden. "
      f"Bitte überweisen Sie den Betrag von {de(a144[0]['gross'] + a144[1]['gross'])} € bis zum 31.08.2026.\n\n"
      "Mit freundlichen Grüßen\nRenate Fiedler\nBuchhaltung\nOstermeier Gebäudedienste GmbH\n", mid="<erinn-0820@ostermeier-gd.de>")
    M("2026-09-01T19:44:00", "AW Zahlungserinnerung - offene Rechnungen Juni und Juli.eml", "Marco Bellini <info@tanzschule-rhythmus.de>",
      "Renate Fiedler <buchhaltung@ostermeier-gd.de>", "AW: Zahlungserinnerung – offene Rechnungen Juni und Juli",
      "Hallo Frau Fiedler,\n\ndie Sommerpause war hart, wir hatten kaum Einnahmen. Ich möchte die Rückstände ab Oktober in "
      "Raten zahlen, jeweils eine Monatsrechnung zusätzlich. Wäre das für Sie in Ordnung? Die laufenden Rechnungen zahle "
      "ich dann wieder regelmäßig.\n\nGruß\nMarco Bellini\nTanzschule Rhythmus\n", reply_to_id="<erinn-0820@ostermeier-gd.de>")
    M("2026-09-02T12:15:00", "Termin Glasreinigung Showroom.eml", "Frank Wendt <rechnung@autohaus-wendt.de>",
      "Mehmet Arslan <m.arslan@ostermeier-gd.de>", "Termin Glasreinigung Showroom",
      "Hallo Herr Arslan,\n\nwie besprochen passt uns Freitag, 04.09., ab 7 Uhr für die Glasreinigung mit dem Hubsteiger "
      "(Ihr Angebot A-26-016). Bitte bis 9 Uhr fertig sein, dann kommen die ersten Kunden.\n\nGruß\nFrank Wendt\n")
    p118 = pdfs["Petrovic_118-2026.pdf"]
    M("2026-09-07T17:20:00", "Rechnung 118-2026.eml", "Dragan Petrovic <petrovic-glas@t-online.de>",
      "Ostermeier Buchhaltung <buchhaltung@ostermeier-gd.de>", "Rechnung 118/2026",
      "Hallo Frau Fiedler,\n\nanbei meine Rechnung für die Glasreinigung beim Autohaus Wendt am Freitag.\n\nGruß\nDragan Petrovic\n",
      attachments=[("Petrovic_118-2026.pdf", p118)])
    M("2026-09-10T08:12:00", "Ihre Rechnung 2026-32410.eml", "Nordhaus Hygiene-Großhandel <rechnung@nordhaus-hygiene.de>",
      "buchhaltung@ostermeier-gd.de", "Ihre Rechnung 2026-32410",
      "Sehr geehrte Damen und Herren,\n\nanbei erhalten Sie Ihre Rechnung 2026-32410 vom 10.09.2026 als PDF.\n\nMit "
      "freundlichen Grüßen\nIhr Nordhaus-Team\n\nNordhaus Hygiene-Großhandel GmbH · Lister Damm 112 · 30163 Hannover\n",
      attachments=[("Nordhaus_2026-32410.pdf", pdfs["Nordhaus_2026-32410.pdf"])])
    M("2026-09-14T09:05:00", "Rechnungsstellung ab Oktober nur noch als XRechnung.eml",
      "Kirchner, Sabine <s.kirchner@stadt-hildesheim.de>", OWN_INFO,
      "Rechnungsstellung ab Oktober nur noch als XRechnung – Grundschule Am Lindenhof",
      "Sehr geehrte Damen und Herren,\n\nab dem 01.10.2026 nimmt die Stadt Hildesheim Rechnungen ausschließlich als "
      "XRechnung über das Rechnungseingangsportal an. Das gilt bereits für die Rechnung für den Leistungsmonat September "
      "2026 (Unterhaltsreinigung Grundschule Am Lindenhof).\n\nBitte verwenden Sie die Leitweg-ID 03254021-65000-17. "
      "Papier- und PDF-Rechnungen können ab diesem Zeitpunkt nicht mehr bearbeitet werden. Die Rechnung für August senden "
      "Sie uns bitte zusätzlich ebenfalls als XRechnung.\n\nMit freundlichen Grüßen\nIm Auftrag\nSabine Kirchner\n"
      "Stadt Hildesheim – Fachbereich 65 Gebäudemanagement\nMarkt 3, 31134 Hildesheim\n")
    M("2026-09-15T13:31:00", "Rücklastschrift.eml", "Sven Kowalski <info@powerhouse-hildesheim.de>", OWN_INFO, "Rücklastschrift",
      f"Hallo,\n\nsorry für die Rücklastschrift – wir haben das Konto gewechselt und vergessen, Ihnen die neue "
      f"Bankverbindung zu geben. Ich überweise die Augustrechnung ({a136['no']}) nächste Woche.\n\nNeue IBAN für die "
      f"Lastschrift ab September: {fmt_iban(POWERHOUSE_NEW[0])} (DKB). Das neue Mandat schicke ich Ihnen unterschrieben "
      f"per Post.\n\nGruß\nSven Kowalski\nPowerHouse Hildesheim\n")
    M("2026-09-16T16:40:00", "Anfrage Unterhaltsreinigung Praxis.eml", "Anja Rosenberg <info@logopaedie-sprachraum.de>", OWN_INFO,
      "Anfrage Unterhaltsreinigung Praxis",
      "Guten Tag,\n\nwir eröffnen am 01.11. eine logopädische Praxis in der Goslarschen Straße 12 (ca. 140 m², vier "
      "Therapieräume, Wartebereich, zwei WC) und suchen eine Reinigung zweimal pro Woche.\n\nKönnen Sie uns ein Angebot "
      "machen? Eine Besichtigung wäre ab nächster Woche möglich.\n\nViele Grüße\nAnja Rosenberg\nLogopädie Sprachraum\n")
    # ---- delivery 2
    M("2026-09-22T10:48:00", "Auftrag Glasreinigung Treppenhausfenster.eml", "Melanie Kröger <buchhaltung@kroeger-partner.de>", OWN_INFO,
      "Auftrag Glasreinigung Treppenhausfenster",
      "Sehr geehrte Frau Ostermeier,\n\nfür die Objekte Wohnanlage Ostend, Wohnpark Steinberg und das Ärztehaus "
      "Kardinal-Bertram-Straße beauftragen wir die Glasreinigung der Treppenhausfenster gemäß Ihrem Angebot vom 18.09. "
      "zum Pauschalpreis von 1.480,00 € netto. Ausführung bitte in KW 42.\n\nBitte eine Rechnung für alle drei Objekte "
      "an uns.\n\nMit freundlichen Grüßen\nMelanie Kröger\nKröger & Partner Immobilienverwaltung GmbH\n")
    M("2026-09-29T15:02:00", f"Doppelte Zahlung Rechnung {a103['no']}.eml", "Tobias Lenz <buero@lenz-architektur.de>", OWN_INFO,
      f"Doppelte Zahlung Rechnung {a103['no']}",
      f"Hallo Frau Ostermeier,\n\nunsere Buchhaltung hat Ihre Rechnung {a103['no']} versehentlich zweimal überwiesen "
      f"(03.09. und 08.09., je {de(a103['gross'])} €). Bitte erstatten Sie uns den doppelten Betrag auf unser Konto "
      f"{fmt_iban(CUSTOMERS['10003']['iban'])}.\n\nDanke und viele Grüße\nTobias Lenz\n", mid="<dbl-0929@lenz-architektur.de>")
    M("2026-09-30T09:12:00", f"AW Doppelte Zahlung Rechnung {a103['no']}.eml", OWN, "Tobias Lenz <buero@lenz-architektur.de>",
      f"AW: Doppelte Zahlung Rechnung {a103['no']}",
      f"Hallo Herr Lenz,\n\nstimmt, danke für den Hinweis. Die Erstattung über {de(a103['gross'])} € ist heute "
      f"rausgegangen." + SIG, reply_to_id="<dbl-0929@lenz-architektur.de>")
    M("2026-10-06T11:26:00", "Kündigung Reinigungsvertrag Daimlerring 5 zum 31.12.2026.eml",
      "Sandra Petersen <office@neuland-it.de>", OWN_INFO, "Kündigung Reinigungsvertrag Daimlerring 5 zum 31.12.2026",
      "Sehr geehrte Damen und Herren,\n\naufgrund unseres Umzugs in den Neubau in Hannover kündigen wir den "
      "Reinigungsvertrag für den Standort Daimlerring 5, Hildesheim, fristgerecht zum 31.12.2026.\n\nBitte bestätigen Sie "
      "uns die Kündigung schriftlich und nennen Sie uns einen Termin für die Schlüsselrückgabe.\n\nMit freundlichen "
      "Grüßen\nSandra Petersen\nOffice Management\nIT-Systemhaus Neuland GmbH\n")
    r129 = inv_of("OB-129", 9)
    sep = [inv_of(ob, 9) for ob in ("OB-127", "OB-128", "OB-130")]
    M("2026-10-08T08:55:00", "Reklamation Haus Godehard - Treppenhaus.eml", "Melanie Kröger <buchhaltung@kroeger-partner.de>", OWN_INFO,
      "Reklamation Haus Godehard – Treppenhaus",
      f"Sehr geehrte Frau Ostermeier,\n\nim Haus Godehard (Godehardsplatz 9) beschweren sich die Mieter seit Wochen, dass "
      f"die Treppen nur oberflächlich gereinigt werden; der Müllplatz wurde im September zweimal gar nicht gemacht.\n\n"
      f"Bis zur Klärung behalten wir die Septemberrechnung für dieses Objekt ({r129['no']}) ein. Bitte melden Sie sich "
      f"kurzfristig für einen gemeinsamen Termin vor Ort.\n\nMit freundlichen Grüßen\nMelanie Kröger\n")
    M("2026-10-09T10:20:00", "Zahlungsavis 09.10.2026.eml", "Buchhaltung Kröger & Partner <buchhaltung@kroeger-partner.de>",
      "buchhaltung@ostermeier-gd.de", "Zahlungsavis 09.10.2026",
      "Sehr geehrte Damen und Herren,\n\nmit Valuta 09.10.2026 haben wir folgende Rechnungen beglichen:\n\n" +
      "".join(f"  {x['no']}   {OBJ[x['ob']]['name']:<42} {de(x['gross']):>10} €\n" for x in sep) +
      f"\n  Summe {de(sum(x['gross'] for x in sep))} €\n\nDie Rechnung {r129['no']} (Haus Godehard) behalten wir wegen "
      f"der Reklamation vom 08.10. vorerst ein.\n\nMit freundlichen Grüßen\nBuchhaltung\nKröger & Partner "
      f"Immobilienverwaltung GmbH\n")
    M("2026-10-14T16:05:00", "Lastschrift September - Widerspruch.eml", "Büro Notar Dr. Rehberg <kanzlei@notar-rehberg.de>", OWN_INFO,
      "Lastschrift September – Widerspruch",
      "Sehr geehrte Frau Ostermeier,\n\nwir haben der Lastschrift für September widersprochen. Der Preiserhöhung ab Juli "
      "haben wir nicht zugestimmt; laut unserem Vertrag ist eine Anpassung nur mit unserem Einverständnis möglich. Die "
      "Erhöhung ist uns erst jetzt bei der Kontrolle der Kontoauszüge aufgefallen.\n\nBitte rufen Sie Herrn Dr. Rehberg "
      "an.\n\nMit freundlichen Grüßen\nKaiser\nBüro Notar Dr. Rehberg\n")
    M("2026-10-16T18:02:00", "Rechnung 131-2026.eml", "Dragan Petrovic <petrovic-glas@t-online.de>",
      "Ostermeier Buchhaltung <buchhaltung@ostermeier-gd.de>", "Rechnung 131/2026",
      "Hallo Frau Fiedler,\n\nanbei die Rechnung für die drei Tage Treppenhausfenster bei Kröger.\n\nGruß\nDragan Petrovic\n",
      attachments=[("Petrovic_131-2026.pdf", pdfs["Petrovic_131-2026.pdf"])])
    M("2026-10-19T09:41:00", "Danke.eml", "Lars Meyer <meyer@hoerakustik-meyer.de>", "Mehmet Arslan <m.arslan@ostermeier-gd.de>",
      "Danke!", "Hallo Herr Arslan,\n\nder Teppich im Laden sieht nach der Grundreinigung am Donnerstag aus wie neu. Danke an "
      "Ihr Team – die Kunden haben es sofort bemerkt.\n\nViele Grüße\nLars Meyer\nHörakustik Meyer\n")
    M("2026-10-21T12:30:00", "Grundreinigung PVC Behandlungsräume.eml", "Dr. Martin Schäfer <info@zahnarzt-schaefer-hildesheim.de>",
      OWN_INFO, "Grundreinigung PVC Behandlungsräume",
      "Sehr geehrte Frau Ostermeier,\n\nbitte führen Sie am Samstag, 07.11.2026, die Grundreinigung der PVC-Böden in "
      "unseren vier Behandlungsräumen inkl. Neueinpflege durch – zum Preis aus Ihrem Angebot A-26-024 vom 14.10. "
      "(620,00 € netto). Den Schlüssel holen Sie bitte am Freitag bis 16 Uhr an der Anmeldung ab.\n\nMit freundlichen "
      "Grüßen\nDr. Martin Schäfer\nZahnarztpraxis Dr. Schäfer, Almsstraße 15\n")
    M("2026-10-22T07:58:00", "Ihre Rechnung 2026-34102.eml", "Nordhaus Hygiene-Großhandel <rechnung@nordhaus-hygiene.de>",
      "buchhaltung@ostermeier-gd.de", "Ihre Rechnung 2026-34102",
      "Sehr geehrte Damen und Herren,\n\nanbei erhalten Sie Ihre Rechnung 2026-34102 vom 21.10.2026 als PDF.\n\nMit "
      "freundlichen Grüßen\nIhr Nordhaus-Team\n\nNordhaus Hygiene-Großhandel GmbH · Lister Damm 112 · 30163 Hannover\n",
      attachments=[("Nordhaus_2026-34102.pdf", pdfs["Nordhaus_2026-34102.pdf"])])
    M("2026-10-26T07:41:00", "WICHTIG Neue Bankverbindung - Rechnung 2026-34102.eml",
      "Nordhaus Hygiene-Großhandel Buchhaltung <buchhaltung@nordhaus-hygiene.co>", "buchhaltung@ostermeier-gd.de",
      "WICHTIG: Neue Bankverbindung – Rechnung 2026-34102",
      "Sehr geehrte Kundin, sehr geehrter Kunde,\n\naufgrund einer Umstellung unseres Bankinstituts ändert sich unsere "
      "Bankverbindung mit sofortiger Wirkung. Bitte überweisen Sie den Betrag der Rechnung 2026-34102 sowie alle "
      f"künftigen Zahlungen ausschließlich auf unser neues Konto:\n\n  Revolut Bank UAB\n  IBAN {fmt_iban(FRAUD_IBAN)}\n"
      "  BIC REVOLT21XXX\n\nDie korrigierte Rechnung finden Sie im Anhang. Zahlungen auf die alte Bankverbindung können "
      "leider nicht mehr zugeordnet werden. Bitte bestätigen Sie die Änderung kurz per Antwort.\n\nMit freundlichen "
      "Grüßen\nBuchhaltung\nNordhaus Hygiene-Großhandel GmbH\n",
      attachments=[("Rechnung_2026-34102_korrigiert.pdf", pdfs["fraud"])])
    k24 = inv_sa("SA-26-024")
    M("2026-10-27T10:03:00", "AW Rechnung Grundreinigung Sommer.eml", "Heike Rust <kita.sonnenblume@evlka-hi.de>",
      "Renate Fiedler <buchhaltung@ostermeier-gd.de>", "AW: Rechnung Grundreinigung Sommer",
      f"Hallo Frau Fiedler,\n\nSie hatten nach der Rechnung {k24['no']} gefragt (Grundreinigung Sommer) – die haben wir am "
      f"20.10. überwiesen, {de(k24['gross'])} €. Bitte schauen Sie noch einmal nach.\n\nViele Grüße\nHeike Rust\n")
    M("2026-10-28T17:12:00", "Anfrage Fensterreinigung Gästezimmer.eml", "Familie Gerdes <gerdes@pension-domblick.de>", OWN_INFO,
      "Anfrage Fensterreinigung Gästezimmer",
      "Guten Tag,\n\nkönnen Sie uns ein Angebot für die Reinigung der Fenster in unseren 14 Gästezimmern machen? Am liebsten "
      "noch vor dem Weihnachtsgeschäft.\n\nViele Grüße\nGerdes\nPension Domblick\n")
    for when, fname, args, kw in mails:
        write_eml(folder / fname, *args[:2], when, *args[2:], **kw)
    return [m[1] for m in mails]


def write_delivery(root: Path, dv: dict) -> list[str]:
    out = root / dv["folder"]
    for sub in ("Bank", "Stunden", "Eingangsrechnungen", "Mails"):
        (out / sub).mkdir(parents=True, exist_ok=True)
    write_objektliste(out / "Objektliste_Vertraege.xlsx", dv)
    write_kunden(out / "Kunden_Export.csv", dv)
    write_rechnungsbuch(out / "Rechnungsausgangsbuch_2026.xlsx", dv)
    write_sonder(out / "Sonderauftraege_2026.xlsx", dv)
    write_angebote(out / "Angebote_2026.xlsx", dv)
    write_mitarbeiter(out / "Mitarbeiter.xlsx", dv)
    write_bank(out / "Bank" / "Sparkasse_Umsaetze_2026.csv", dv)
    for b in BATCHES:
        if b["date"] <= dv["cut"]:
            write_sepa(out / "Bank" / f"SEPA-LS_{b['date'].isoformat()}.xml", b)
    for m in range(6, dv["cut"].month + 1):
        write_stunden(out / "Stunden" / f"Stundennachweis_2026-{m:02d}.xlsx", 2026, m, dv["cut"])
    pdfs = {}
    tmp = root / "_pdf"
    tmp.mkdir(exist_ok=True)
    for x in SUPINV:
        p = tmp / x["file"]
        pdfs[x["file"]] = pdf_invoice(p, x)
        if x["date"] <= dv["cut"]:
            (out / "Eingangsrechnungen" / x["file"]).write_bytes(pdfs[x["file"]])
    x31877 = next(x for x in SUPINV if x["no"] == "2026-31877")
    (out / "Eingangsrechnungen" / "Nordhaus_2026-31877_Kopie.pdf").write_bytes(pdf_invoice(tmp / "copy.pdf", x31877, copy=True))
    pdfs["fraud"] = pdf_invoice(tmp / "fraud.pdf", next(x for x in SUPINV if x["no"] == "2026-34102"), fraud=True)
    write_mails(out / "Mails", dv, pdfs)
    if dv["n"] == 2:
        (out / "Stadt_XRechnung").mkdir(exist_ok=True)
        r = inv_of("OB-132", 8)
        write_xrechnung(out / "Stadt_XRechnung" / f"XRechnung_{r['no']}_Lindenhof_08-2026.xml", r)
    return sorted(str(p.relative_to(out)) for p in out.rglob("*") if p.is_file())


def main(outdir: str) -> None:
    root = Path(outdir)
    root.mkdir(parents=True, exist_ok=True)
    build_invoices()
    SUPINV.extend(supplier_invoices())
    gen_payments()
    gen_other_bank()
    truth = dict(firm="Ostermeier Gebäudedienste GmbH (Gebäudereinigung, Review 8)", deliveries=[])
    files = {}
    for dv in DELIV:
        files[dv["folder"]] = write_delivery(root, dv)
        truth["deliveries"].append(truth_for(dv))
    for p in (root / "_pdf").iterdir():
        p.unlink()
    (root / "_pdf").rmdir()
    (root / "truth.json").write_text(json.dumps(truth, ensure_ascii=False, indent=1), encoding="utf-8")
    key = dict(answers=ANSWERS,
               invoices={r["no"]: dict(kd=r["kd"], ob=r["ob"], date=r["date"].isoformat(), gross=eur(r["gross"]),
                                       due=r["due"].isoformat(), kind=r["kind"], zahlart=r["zahlart"], sa=r["sa"],
                                       period=r["period"]) for r in INV},
               money=[dict(date=e["date"].isoformat(), amount=eur(e["amount"]), vwz=e["vwz"], payer=e["payer"],
                           alloc=[(no, eur(c)) for no, c in e["alloc"]], deferred=[(no, eur(c)) for no, c in e["deferred"]],
                           note=e["note"], bank=e["bank"]) for e in EV if e["cust"] or e["note"]],
               files=files)
    (root / "answer_key.json").write_text(json.dumps(key, ensure_ascii=False, indent=1), encoding="utf-8")
    for d in truth["deliveries"]:
        print(d["folder"], d["today"], "offen:", len(d["open"]), d["open_total"], "überfällig:", len(d["overdue"]),
              "nicht berechnet:", d["unbilled"], "Geld ohne Rechnung:", d["receipts"])


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit("Aufruf: python3 gen_firm.py OUTDIR")
    main(sys.argv[1])
