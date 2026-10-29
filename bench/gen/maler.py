"""Realistic, slightly messy data dump of a fictional painting business in Kassel.

Malerfachbetrieb Krause GmbH (9 people). Files the office really has lying around:
  Kundenliste.xlsx              customer list with title rows, 'Stand', two different "Müller, Hans"
  Auftraege_2026.xlsx           job book (Auftragsbuch) with name variants of customers
  Rechnungsbuch_2026.csv        invoice book exported from Excel: cp1252, ';', decimal comma, title + sum row
  Umsaetze_Girokonto_...csv     bank export in Sparkasse CSV-CAMT layout (cp1252, dd.mm.yy)
  Mails/*.eml                   two customer e-mails (quote request, complaint about an invoice amount)

Planted situations (the "truth" the review checks against):
  * RE-2026-106 Autohaus Rehm 4.284,00 EUR due 07.10.2026, unpaid           -> overdue, needs reminder (task 7)
  * RE-2026-107 Restaurant Zur Fulda 1.071,00 EUR due 30.09.2026, unpaid    -> overdue
  * RE-2026-100 HV Fuldablick 3.570,00 EUR, 2.000 paid by bank             -> 1.570,00 open, overdue since 30.08.
  * RE-2026-111 Wagner, Peter 690,20 EUR due 04.11.2026, unpaid             -> he paid 200 EUR cash (task 6)
  * RE-2026-112 Schneider, Ulrike 2.558,50 EUR (2.150 net) wrong amount    -> e-mail complaint, correct (task 8)
  * A-2026-030 Zahnarztpraxis Dr. Bergmann finished 22.10.2026, no invoice -> write invoice (task 5)
  * A-2026-034 Neumann, Klaus (not in customer list) finished 27.10.2026  -> second uninvoiced job
  * Hausverwaltung Fuldablick: RE-2026-100 partly paid, RE-2026-109 and RE-2026-110 open,
    jobs in progress, quote-request e-mail                                  -> everything open for one customer (task 4)
  * "Fam. Fischer" (private family in Baunatal, NOT in the customer list) vs "Bäckerei Fischer" (K-1005)
    RE-2026-103 paid by "Fischer, Jan und Petra" without number             -> a wrong link/merge is a wrong guess to undo (task 11)
  * K-1007 and K-1008 are two different people both called "Müller, Hans"   -> must not be merged (task 11)
  * RE-2026-091..099 paid before the bank export window ('bezahlt am')     -> must not show as open
  * RE-2026-103/104/105/108 paid per bank but 'bezahlt am' empty in the book -> should be found as paid
  * Wohnbau Nordhessen pays 3.000 EUR Anzahlung without an invoice         -> "Geld ohne Rechnung"
  * Open total (truth): 100: 1.570,00 + 106: 4.284,00 + 107: 1.071,00 + 109: 2.856,00 + 110: 3.689,00
    + 111: 690,20 + 112: 2.558,50 = 16.718,70 EUR in 7 invoices; overdue: 100, 106, 107 = 6.925,00 EUR
"""
from __future__ import annotations

import csv
import io
import sys
from datetime import date, datetime, timedelta
from email.message import EmailMessage
from email.utils import format_datetime
from pathlib import Path

import openpyxl
from openpyxl.styles import Font


def iban(blz: str, konto: str) -> str:
    bban = blz + konto.zfill(10)
    num = int("".join(str(int(c, 36)) for c in bban + "DE00"))
    check = 98 - num % 97
    s = f"DE{check:02d}{bban}"
    return " ".join(s[i:i + 4] for i in range(0, len(s), 4))


def de(x: float) -> str:
    s = f"{x:,.2f}"
    return s.replace(",", "X").replace(".", ",").replace("X", ".")


def de_plain(x: float) -> str:
    return f"{x:.2f}".replace(".", ",")


OWN_IBAN = iban("52050353", "0001234567")

CUSTOMERS = [
    # kdnr, anrede, name, ansprechpartner, strasse, plz, ort, telefon, email, ziel, bemerkung
    ("K-1001", "Firma", "Hausverwaltung Fuldablick GmbH", "Frau Hartmann", "Friedrich-Ebert-Straße 88", "34119", "Kassel", "0561 73910", "info@hv-fuldablick.de", 30, "Rahmenvertrag Treppenhäuser"),
    ("K-1002", "Herr", "Wagner, Peter", "", "Am Weinberg 7", "34131", "Kassel", "0561 31277", "peter.wagner@kassel-mail.de", 14, ""),
    ("K-1003", "Frau", "Schneider, Ulrike", "", "Wilhelmshöher Allee 19", "34117", "Kassel", "0561 102030", "u.schneider@kassel-mail.de", 14, ""),
    ("K-1004", "Firma", "Autohaus Rehm GmbH", "Herr Rehm", "Leipziger Straße 201", "34123", "Kassel", "0561 95080", "buchhaltung@autohaus-rehm.de", 30, ""),
    ("K-1005", "Firma", "Bäckerei Fischer", "Herr Fischer", "Bettenhäuser Straße 12", "34123", "Kassel", "0561 571122", "baeckerei-fischer@kassel-mail.de", 14, "Filiale + Backstube"),
    ("K-1006", "Firma", "Zahnarztpraxis Dr. Bergmann", "Dr. Lena Bergmann", "Kölnische Straße 44", "34117", "Kassel", "0561 777888", "praxis@dr-bergmann-kassel.de", 14, ""),
    ("K-1007", "Herr", "Müller, Hans", "", "Wilhelmshöher Allee 210", "34119", "Kassel", "0561 401122", "", 14, ""),
    ("K-1008", "Herr", "Müller, Hans", "", "Kasseler Straße 5", "34246", "Vellmar", "0561 820933", "hans.mueller.vellmar@kassel-mail.de", 14, "nicht verwechseln mit K-1007!"),
    ("K-1009", "Firma", "Kita Sonnenschein e.V.", "Frau Yilmaz", "Am Rosengarten 3", "34130", "Kassel", "0561 600700", "leitung@kita-sonnenschein-ks.de", 30, ""),
    ("K-1010", "Firma", "Wohnbau Nordhessen eG", "Herr Brandt", "Ständeplatz 9", "34117", "Kassel", "0561 10920", "rechnungen@wohnbau-nordhessen.de", 30, "Anzahlung bei Großaufträgen"),
    ("K-1011", "Frau", "Becker, Monika", "", "Lindenstraße 22", "34225", "Baunatal", "05601 87654", "", 14, ""),
    ("K-1012", "Herr", "Dr. Weber, Thomas", "", "Rasenallee 61", "34128", "Kassel", "0561 881199", "t.weber@kassel-mail.de", 14, ""),
    ("K-1013", "Firma", "Restaurant Zur Fulda", "Herr Kaya", "Weserstraße 30", "34125", "Kassel", "0561 874455", "", 14, "zahlt oft spät"),
    ("K-1014", "Firma", "Physiotherapie Am Park", "Frau Klein", "Parkstraße 5", "34119", "Kassel", "0561 223344", "team@physio-am-park.de", 14, ""),
    ("K-1015", "Herr", "Hoffmann, Jürgen", "", "Ahnatalstraße 70", "34128", "Kassel", "0561 662211", "", 14, ""),
    ("K-1016", "Frau", "Schäfer, Andrea", "", "Heckershäuser Straße 3", "34277", "Fuldabrück", "0561 491717", "andrea.schaefer@kassel-mail.de", 14, ""),
    ("K-1017", "Firma", "Steuerkanzlei Lorenz & Partner", "Herr Lorenz", "Obere Königsstraße 15", "34117", "Kassel", "0561 705050", "kanzlei@lorenz-partner-ks.de", 14, ""),
    ("K-1018", "Frau", "Koch, Sabine", "", "Goethestraße 58", "34119", "Kassel", "0561 129900", "", 14, ""),
    ("K-1019", "Herr", "Schmidt, Wolfgang", "", "Mönchebergstraße 41", "34125", "Kassel", "0561 873301", "w.schmidt@kassel-mail.de", 14, ""),
    ("K-1020", "Firma", "Hotel Garni Bergpark", "Frau Engel", "Druseltalstraße 101", "34131", "Kassel", "0561 939390", "rezeption@hotel-bergpark-ks.de", 30, ""),
]

CUST_IBAN = {
    "K-1001": iban("52050353", "0007700110"), "K-1002": iban("52060410", "0003141592"),
    "K-1003": iban("52050353", "0004455667"), "K-1004": iban("52090000", "0009988776"),
    "K-1005": iban("52050353", "0001122334"), "K-1006": iban("50010517", "0005566778"),
    "K-1007": iban("52050353", "0002233445"), "K-1008": iban("52060410", "0007788990"),
    "K-1009": iban("52050353", "0003344556"), "K-1010": iban("52090000", "0001010101"),
    "K-1011": iban("52060410", "0006677889"), "K-1012": iban("50010517", "0002468024"),
    "K-1013": iban("52050353", "0001357913"), "K-1014": iban("52050353", "0009090909"),
    "K-1015": iban("52060410", "0008080808"), "K-1016": iban("52050353", "0007070707"),
    "K-1017": iban("50010517", "0006060606"), "K-1018": iban("52050353", "0005050505"),
    "K-1019": iban("52060410", "0004040404"), "K-1020": iban("52090000", "0003030303"),
    "FISCHER_PRIVAT": iban("52060410", "0001919191"),
}

# Job book. kunde = how the office actually wrote it (variants!)
# auftrag, datum, kunde, baustelle, leistung, angebot_netto, status, beginn, fertig, rechnung, kolonne
JOBS = [
    ("A-2026-001", "12.01.2026", "HV Fuldablick", "Goethestraße 22, Treppenhaus", "Treppenhaus streichen, 3 Etagen", 4200.00, "abgerechnet", "02.03.2026", "13.03.2026", "RE-2026-091", "Kolonne 1"),
    ("A-2026-004", "03.02.2026", "Dr. Weber", "Rasenallee 61", "Wohnzimmer, Esszimmer tapezieren + streichen", 2860.00, "abgerechnet", "16.03.2026", "20.03.2026", "RE-2026-092", "Kolonne 2"),
    ("A-2026-007", "24.02.2026", "Kita Sonnenschein", "Am Rosengarten 3", "Gruppenräume Latexanstrich", 3940.00, "abgerechnet", "30.03.2026", "08.04.2026", "RE-2026-093", "Kolonne 1"),
    ("A-2026-009", "10.03.2026", "Hoffmann, Jürgen", "Ahnatalstraße 70", "Fassade Rückseite, Fenster lackieren", 3150.00, "abgerechnet", "20.04.2026", "30.04.2026", "RE-2026-094", "Kolonne 2"),
    ("A-2026-012", "02.04.2026", "Physiotherapie Am Park", "Parkstraße 5", "Behandlungsräume streichen", 1980.00, "abgerechnet", "11.05.2026", "15.05.2026", "RE-2026-095", "Kolonne 1"),
    ("A-2026-014", "20.04.2026", "Becker, Monika", "Lindenstraße 22, Baunatal", "Schlafzimmer + Flur", 1240.00, "abgerechnet", "01.06.2026", "03.06.2026", "RE-2026-096", "Kolonne 2"),
    ("A-2026-015", "05.05.2026", "Steuerkanzlei Lorenz", "Obere Königsstraße 15", "Büroetage streichen", 5480.00, "abgerechnet", "15.06.2026", "26.06.2026", "RE-2026-097", "Kolonne 1"),
    ("A-2026-016", "12.05.2026", "Müller, Hans (W.-Allee)", "Wilhelmshöher Allee 210", "Küche + Bad Decke", 780.00, "abgerechnet", "29.06.2026", "30.06.2026", "RE-2026-098", "Kolonne 2"),
    ("A-2026-017", "26.05.2026", "Schmidt, Wolfgang", "Mönchebergstraße 41", "Treppengeländer lackieren", 640.00, "abgerechnet", "06.07.2026", "07.07.2026", "RE-2026-099", "Kolonne 2"),
    ("A-2026-018", "02.06.2026", "Hausverwaltung Fuldablick", "Goethestraße 14, Fassade", "Fassade Vorderhaus, Gerüst bauseits", 9800.00, "in Arbeit", "13.07.2026", "", "RE-2026-100", "Kolonne 1"),
    ("A-2026-019", "09.06.2026", "Hotel Garni Bergpark", "Druseltalstraße 101", "Zimmer 1-6 renovieren", 6120.00, "abgerechnet", "20.07.2026", "31.07.2026", "RE-2026-101", "Kolonne 1"),
    ("A-2026-020", "16.06.2026", "Koch, Sabine", "Goethestraße 58", "Wohnung komplett nach Auszug", 2310.00, "abgerechnet", "03.08.2026", "07.08.2026", "RE-2026-102", "Kolonne 2"),
    ("A-2026-021", "30.06.2026", "Fam. Fischer (Baunatal)", "Im Wiesengrund 4, Baunatal", "Kinderzimmer + Treppenhaus EFH", 1460.00, "abgerechnet", "10.08.2026", "12.08.2026", "RE-2026-103", "Kolonne 2"),
    ("A-2026-022", "07.07.2026", "Bäckerei Fischer", "Bettenhäuser Straße 12", "Verkaufsraum + Backstube (Lebensmittelfarbe)", 2790.00, "abgerechnet", "17.08.2026", "21.08.2026", "RE-2026-104", "Kolonne 1"),
    ("A-2026-023", "14.07.2026", "Autohaus Rehm", "Leipziger Straße 201", "Showroom Wände + Decken", 3600.00, "abgerechnet", "24.08.2026", "04.09.2026", "RE-2026-106", "Kolonne 1"),
    ("A-2026-024", "21.07.2026", "Schäfer, Andrea", "Heckershäuser Straße 3", "Bad + Gäste-WC", 1050.00, "abgerechnet", "31.08.2026", "02.09.2026", "RE-2026-105", "Kolonne 2"),
    ("A-2026-025", "28.07.2026", "Restaurant Zur Fulda", "Weserstraße 30", "Gastraum streichen nach Schließtag", 900.00, "abgerechnet", "14.09.2026", "15.09.2026", "RE-2026-107", "Kolonne 2"),
    ("A-2026-026", "04.08.2026", "H. Müller Vellmar", "Kasseler Straße 5, Vellmar", "Wohnzimmer streichen", 450.00, "abgerechnet", "21.09.2026", "22.09.2026", "RE-2026-108", "Kolonne 2"),
    ("A-2026-027", "11.08.2026", "Wohnbau Nordhessen", "Holländische Straße 40-44", "12 Wohnungen Leerstandsrenovierung", 18600.00, "in Arbeit", "05.10.2026", "", "", "Kolonne 1"),
    ("A-2026-028", "18.08.2026", "HV Fuldablick", "Friedrich-Ebert-Straße 88, Büro", "Büro Hausverwaltung streichen", 2400.00, "abgerechnet", "28.09.2026", "02.10.2026", "RE-2026-109", "Kolonne 2"),
    ("A-2026-029", "25.08.2026", "Wagner, Peter", "Am Weinberg 7", "Gartenzaun + Pergola lasieren", 580.00, "abgerechnet", "12.10.2026", "13.10.2026", "RE-2026-111", "Kolonne 2"),
    ("A-2026-030", "01.09.2026", "Praxis Dr. Bergmann", "Kölnische Straße 44", "Praxisräume + Wartezimmer streichen", 3280.00, "fertig", "19.10.2026", "22.10.2026", "", "Kolonne 1"),
    ("A-2026-031", "08.09.2026", "Hausverwaltung Fuldablick", "Goethestraße 14, Treppenhaus Hinterhaus", "Treppenhaus Hinterhaus", 3100.00, "abgerechnet", "05.10.2026", "09.10.2026", "RE-2026-110", "Kolonne 2"),
    ("A-2026-032", "15.09.2026", "Fr. Schneider", "Wilhelmshöher Allee 19", "Wohnzimmer + Flur tapezieren und streichen", 1850.00, "abgerechnet", "19.10.2026", "23.10.2026", "RE-2026-112", "Kolonne 2"),
    ("A-2026-033", "22.09.2026", "Hotel Garni Bergpark", "Druseltalstraße 101", "Frühstücksraum + Flure", 4300.00, "beauftragt", "09.11.2026", "", "", "Kolonne 1"),
    ("A-2026-034", "29.09.2026", "Neumann, Klaus", "Tischbeinstraße 12", "Altbauwohnung Stuckdecken ausbessern + streichen", 2950.00, "fertig", "20.10.2026", "27.10.2026", "", "Kolonne 2"),
    ("A-2026-035", "06.10.2026", "Kita Sonnenschein e.V.", "Am Rosengarten 3", "Waschräume Fliesenlack", 1720.00, "Angebot", "", "", "", ""),
    ("A-2026-036", "13.10.2026", "Dr. Weber", "Rasenallee 61", "Arbeitszimmer", 890.00, "beauftragt", "16.11.2026", "", "", "Kolonne 2"),
]

VAT = 0.19

# Invoice book. nr, datum, kunde (as written), auftrag, leistung, netto, faellig, bezahlt_am, bemerkung
INVOICES = [
    ("RE-2026-091", "16.03.2026", "Hausverwaltung Fuldablick GmbH", "A-2026-001", "Treppenhaus Goethestraße 22", 4200.00, "15.04.2026", "09.04.2026", ""),
    ("RE-2026-092", "23.03.2026", "Dr. Thomas Weber", "A-2026-004", "Wohnzimmer, Esszimmer", 2860.00, "06.04.2026", "02.04.2026", ""),
    ("RE-2026-093", "10.04.2026", "Kita Sonnenschein e.V.", "A-2026-007", "Gruppenräume", 3940.00, "10.05.2026", "28.04.2026", ""),
    ("RE-2026-094", "04.05.2026", "Hoffmann, Jürgen", "A-2026-009", "Fassade Rückseite", 3150.00, "18.05.2026", "15.05.2026", ""),
    ("RE-2026-095", "18.05.2026", "Physiotherapie Am Park", "A-2026-012", "Behandlungsräume", 1980.00, "01.06.2026", "29.05.2026", ""),
    ("RE-2026-096", "05.06.2026", "Becker, Monika", "A-2026-014", "Schlafzimmer + Flur", 1240.00, "19.06.2026", "05.06.2026", "bar bei Abnahme"),
    ("RE-2026-097", "29.06.2026", "Steuerkanzlei Lorenz & Partner", "A-2026-015", "Büroetage", 5480.00, "13.07.2026", "10.07.2026", ""),
    ("RE-2026-098", "01.07.2026", "Müller, Hans", "A-2026-016", "Küche + Bad Decke", 780.00, "15.07.2026", "14.07.2026", ""),
    ("RE-2026-099", "08.07.2026", "Schmidt, Wolfgang", "A-2026-017", "Treppengeländer", 640.00, "22.07.2026", "20.07.2026", ""),
    ("RE-2026-100", "31.07.2026", "Hausverwaltung Fuldablick GmbH", "A-2026-018", "1. Abschlag Fassade Goethestraße 14", 3000.00, "30.08.2026", "", "Teilzahlung 2.000 am 28.08."),
    ("RE-2026-101", "03.08.2026", "Hotel Garni Bergpark", "A-2026-019", "Zimmer 1-6", 6120.00, "02.09.2026", "06.08.2026", ""),
    ("RE-2026-102", "10.08.2026", "Koch, Sabine", "A-2026-020", "Wohnung nach Auszug", 2310.00, "24.08.2026", "19.08.2026", ""),
    ("RE-2026-103", "14.08.2026", "Fam. Fischer", "A-2026-021", "Kinderzimmer + Treppenhaus", 1460.00, "28.08.2026", "", ""),
    ("RE-2026-104", "24.08.2026", "Bäckerei Fischer", "A-2026-022", "Verkaufsraum + Backstube", 2790.00, "07.09.2026", "", ""),
    ("RE-2026-105", "03.09.2026", "Schäfer, Andrea", "A-2026-024", "Bad + Gäste-WC", 1050.00, "17.09.2026", "", ""),
    ("RE-2026-106", "07.09.2026", "Autohaus Rehm GmbH", "A-2026-023", "Showroom", 3600.00, "07.10.2026", "", ""),
    ("RE-2026-107", "16.09.2026", "Restaurant Zur Fulda", "A-2026-025", "Gastraum", 900.00, "30.09.2026", "", "2x angerufen"),
    ("RE-2026-108", "23.09.2026", "Müller, Hans (Vellmar)", "A-2026-026", "Wohnzimmer", 450.00, "07.10.2026", "", ""),
    ("RE-2026-109", "05.10.2026", "Hausverwaltung Fuldablick GmbH", "A-2026-028", "Büro Hausverwaltung", 2400.00, "04.11.2026", "", ""),
    ("RE-2026-110", "12.10.2026", "Hausverwaltung Fuldablick GmbH", "A-2026-031", "Treppenhaus Hinterhaus", 3100.00, "11.11.2026", "", ""),
    ("RE-2026-111", "21.10.2026", "Wagner, Peter", "A-2026-029", "Gartenzaun + Pergola", 580.00, "04.11.2026", "", ""),
    ("RE-2026-112", "26.10.2026", "Schneider, Ulrike", "A-2026-032", "Wohnzimmer + Flur", 2150.00, "09.11.2026", "", ""),
]

# Bank lines (Aug 1 - Oct 28). (buchungstag, text, zweck, name, cust-key or iban, amount)
BANK = [
    ("03.08.26", "LOHN / GEHALT", "Lohn Juli 2026", "Lohnabrechnung Sammel", None, -21480.00),
    ("04.08.26", "DAUERAUFTRAG", "Miete Werkstatt Lager August", "Immobilien Kuhn GbR", iban("52050353", "0008000800"), -1450.00),
    ("06.08.26", "GUTSCHR. UEBERWEISUNG", "RE-2026-101 Zimmer 1-6", "Hotel Garni Bergpark", "K-1020", 7282.80),
    ("10.08.26", "FOLGELASTSCHRIFT", "Kd-Nr 448812 Rechnung 08/2026", "Farbenhaus Nordhessen GmbH", iban("52090000", "0004488120"), -2314.66),
    ("12.08.26", "KARTENZAHLUNG", "Tankstelle Kassel-Nord 2026-08-11", "Tankstelle Nord", None, -146.30),
    ("19.08.26", "GUTSCHR. UEBERWEISUNG", "Rechnung 2026-102 Wohnung Goethestr", "Sabine Koch", "K-1018", 2748.90),
    ("28.08.26", "GUTSCHR. UEBERWEISUNG", "Abschlag RE-2026-100 Fassade", "Hausverwaltung Fuldablick GmbH", "K-1001", 2000.00),
    ("31.08.26", "GUTSCHR. UEBERWEISUNG", "Malerarbeiten Kinderzimmer Danke", "Fischer, Jan und Petra", "FISCHER_PRIVAT", 1737.40),
    ("01.09.26", "LOHN / GEHALT", "Lohn August 2026", "Lohnabrechnung Sammel", None, -21480.00),
    ("02.09.26", "DAUERAUFTRAG", "Miete Werkstatt Lager September", "Immobilien Kuhn GbR", iban("52050353", "0008000800"), -1450.00),
    ("05.09.26", "GUTSCHR. UEBERWEISUNG", "RE 2026 104", "Baeckerei Fischer", "K-1005", 3320.10),
    ("10.09.26", "FOLGELASTSCHRIFT", "Kd-Nr 448812 Rechnung 09/2026", "Farbenhaus Nordhessen GmbH", iban("52090000", "0004488120"), -3108.42),
    ("10.09.26", "LASTSCHRIFT", "USt-VZ 07/2026 StNr 026 123 45678", "Finanzamt", iban("52000000", "0052001500"), -4210.00),
    ("15.09.26", "GUTSCHR. UEBERWEISUNG", "Malerarbeiten Bad", "Andrea Schaefer", "K-1016", 1249.50),
    ("22.09.26", "KARTENZAHLUNG", "Baumarkt Kassel Abdeckfolie", "Baumarkt", None, -89.97),
    ("01.10.26", "LOHN / GEHALT", "Lohn September 2026", "Lohnabrechnung Sammel", None, -21480.00),
    ("02.10.26", "DAUERAUFTRAG", "Miete Werkstatt Lager Oktober", "Immobilien Kuhn GbR", iban("52050353", "0008000800"), -1450.00),
    ("06.10.26", "GUTSCHR. UEBERWEISUNG", "Malerarbeiten Wohnzimmer", "Hans Mueller", "K-1008", 535.50),
    ("09.10.26", "FOLGELASTSCHRIFT", "Kd-Nr 448812 Rechnung 10/2026", "Farbenhaus Nordhessen GmbH", iban("52090000", "0004488120"), -1876.20),
    ("12.10.26", "LASTSCHRIFT", "USt-VZ 08/2026 StNr 026 123 45678", "Finanzamt", iban("52000000", "0052001500"), -3890.00),
    ("16.10.26", "GUTSCHR. UEBERWEISUNG", "Anzahlung Auftrag A-2026-027 Holl. Str. 40-44", "Wohnbau Nordhessen eG", "K-1010", 3000.00),
    ("21.10.26", "KARTENZAHLUNG", "Tankstelle Kassel-Nord 2026-10-20", "Tankstelle Nord", None, -151.84),
]


def write_customers(out: Path):
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Kunden"
    ws["A1"] = "Kundenliste Malerfachbetrieb Krause GmbH"
    ws["A1"].font = Font(bold=True, size=14)
    ws["A2"] = "Stand: 15.09.2026"
    header = ["Kd-Nr.", "Anrede", "Name / Firma", "Ansprechpartner", "Straße", "PLZ", "Ort", "Telefon", "E-Mail", "Zahlungsziel (Tage)", "Bemerkung"]
    ws.append([])
    ws.append(header)
    for c in ws[4]:
        c.font = Font(bold=True)
    for row in CUSTOMERS:
        ws.append(list(row))
    for col, w in zip("ABCDEFGHIJK", [8, 7, 32, 18, 26, 7, 12, 14, 34, 10, 26]):
        ws.column_dimensions[col].width = w
    wb.save(out / "Kundenliste.xlsx")


def write_jobs(out: Path):
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Aufträge 2026"
    header = ["Auftrag", "Datum", "Kunde", "Baustelle", "Leistung", "Angebot netto", "Status", "Beginn", "Fertig am", "Rechnung", "Kolonne"]
    ws.append(header)
    for c in ws[1]:
        c.font = Font(bold=True)
    for j in JOBS:
        row = list(j)
        for i in (1, 7, 8):  # dates as real Excel dates where present
            if row[i]:
                row[i] = datetime.strptime(row[i], "%d.%m.%Y")
        ws.append(row)
    for r in ws.iter_rows(min_row=2):
        for c in (r[1], r[7], r[8]):
            c.number_format = "DD.MM.YYYY"
        r[5].number_format = '#,##0.00 "€"'
    for col, w in zip("ABCDEFGHIJK", [12, 11, 28, 36, 44, 13, 12, 11, 11, 12, 10]):
        ws.column_dimensions[col].width = w
    wb.save(out / "Auftraege_2026.xlsx")


def write_invoices(out: Path):
    buf = io.StringIO()
    w = csv.writer(buf, delimiter=";", lineterminator="\r\n")
    w.writerow(["Rechnungsausgangsbuch 2026 – Malerfachbetrieb Krause GmbH"] + [""] * 10)
    w.writerow(["Re-Nr.", "Re-Datum", "Kunde", "Auftrag", "Leistung", "Netto", "MwSt 19%", "Brutto", "fällig am", "bezahlt am", "Bemerkung"])
    sn = sv = sb = 0.0
    for nr, d, kunde, auftrag, leistung, netto, faellig, bezahlt, bem in INVOICES:
        mwst = round(netto * VAT, 2)
        brutto = round(netto + mwst, 2)
        sn += netto; sv += mwst; sb += brutto
        w.writerow([nr, d, kunde, auftrag, leistung, de(netto), de(mwst), de(brutto), faellig, bezahlt, bem])
    w.writerow(["Summe", "", "", "", "", de(sn), de(sv), de(sb), "", "", ""])
    (out / "Rechnungsbuch_2026.csv").write_bytes(buf.getvalue().encode("cp1252"))


def write_bank(out: Path):
    cols = ["Auftragskonto", "Buchungstag", "Valutadatum", "Buchungstext", "Verwendungszweck", "Glaeubiger ID", "Mandatsreferenz",
            "Kundenreferenz (End-to-End)", "Sammlerreferenz", "Lastschrift Ursprungsbetrag", "Auslagenersatz Ruecklastschrift",
            "Beguenstigter/Zahlungspflichtiger", "Kontonummer/IBAN", "BIC (SWIFT-Code)", "Betrag", "Waehrung", "Info"]
    buf = io.StringIO()
    w = csv.writer(buf, delimiter=";", quoting=csv.QUOTE_ALL, lineterminator="\r\n")
    w.writerow(cols)
    own = OWN_IBAN.replace(" ", "")
    # Physio pays RE-2026-099 again? no: last line is a 0,00 placeholder we drop
    for bt, text, zweck, name, who, amount in sorted(BANK, key=lambda b: datetime.strptime(b[0], "%d.%m.%y")):
        if amount == 0.0:
            continue
        if who is None:
            ib = ""
        elif who in CUST_IBAN:
            ib = CUST_IBAN[who].replace(" ", "")
        else:
            ib = who.replace(" ", "")
        w.writerow([own, bt, bt, text, zweck, "", "", "NOTPROVIDED", "", "", "", name, ib, "", de_plain(amount), "EUR", "Umsatz gebucht"])
    (out / "Umsaetze_Girokonto_01.08.2026-28.10.2026.csv").write_bytes(buf.getvalue().encode("cp1252"))


def write_mails(out: Path):
    md = out / "Mails"
    md.mkdir(exist_ok=True)
    m = EmailMessage()
    m["From"] = "Martina Hartmann <m.hartmann@hv-fuldablick.de>"
    m["To"] = "Malerfachbetrieb Krause <info@maler-krause-kassel.de>"
    m["Subject"] = "Anfrage Treppenhaus Goethestraße 14 – bitte um Angebot"
    m["Date"] = format_datetime(datetime(2026, 10, 26, 9, 14).astimezone())
    m["Message-ID"] = "<20261026091400.4711@hv-fuldablick.de>"
    m.set_content(
        "Sehr geehrte Frau Krause,\n\n"
        "für unser Objekt Goethestraße 14 (Vorderhaus) in Kassel benötigen wir ein Angebot für den Anstrich des "
        "Treppenhauses: 4 Etagen, ca. 380 m² Wandfläche, Holzgeländer schleifen und lackieren.\n"
        "Die Ausführung sollte möglichst bis Mitte Dezember erfolgen, die Mieter sind informiert.\n\n"
        "Könnten Sie uns bis zum 06.11.2026 ein Angebot schicken? Eine Besichtigung ist nach Absprache möglich.\n\n"
        "Übrigens: Die Rechnung RE-2026-100 (1. Abschlag Fassade) gleichen wir mit der nächsten Zahlung aus, "
        "der Rest kommt nach Abnahme.\n\n"
        "Mit freundlichen Grüßen\n"
        "Martina Hartmann\n"
        "Hausverwaltung Fuldablick GmbH\n"
        "Friedrich-Ebert-Straße 88, 34119 Kassel\n"
        "Tel. 0561 73910\n")
    (md / "2026-10-26_Anfrage_Treppenhaus_Goethestrasse.eml").write_bytes(bytes(m))

    m = EmailMessage()
    m["From"] = "Ulrike Schneider <u.schneider@kassel-mail.de>"
    m["To"] = "info@maler-krause-kassel.de"
    m["Subject"] = "AW: Ihre Rechnung RE-2026-112"
    m["Date"] = format_datetime(datetime(2026, 10, 27, 19, 40).astimezone())
    m["Message-ID"] = "<CAF27oct2026.schneider@kassel-mail.de>"
    m["In-Reply-To"] = "<re-2026-112@maler-krause-kassel.de>"
    m.set_content(
        "Hallo Frau Krause,\n\n"
        "vielen Dank für die schnelle Arbeit, Wohnzimmer und Flur sehen toll aus!\n\n"
        "Leider stimmt die Rechnung RE-2026-112 nicht: Vereinbart waren laut Angebot 1.850,00 € netto, "
        "auf der Rechnung stehen 2.150,00 € netto. Die Tapete hatten wir ja selbst gekauft, die ist "
        "vermutlich noch mit drin.\n\n"
        "Bitte schicken Sie mir eine korrigierte Rechnung, dann überweise ich sofort.\n\n"
        "Viele Grüße\n"
        "Ulrike Schneider\n"
        "Wilhelmshöher Allee 19, 34117 Kassel\n")
    (md / "2026-10-27_AW_Rechnung_RE-2026-112.eml").write_bytes(bytes(m))


def main(out: Path):
    out.mkdir(parents=True, exist_ok=True)
    write_customers(out)
    write_jobs(out)
    write_invoices(out)
    write_bank(out)
    write_mails(out)
    for p in sorted(out.rglob("*")):
        if p.is_file():
            print(p.relative_to(out), p.stat().st_size)


if __name__ == "__main__":
    main(Path(sys.argv[1]))
