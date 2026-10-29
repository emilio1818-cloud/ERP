# Physarum – ein ERP, das aus Ihren Daten wächst

**Kippen Sie alles rein, was Ihre Firma hat** – Excel-Listen, CSV-Exporte aus Shop und Buchhaltung, Kontoauszüge, E-Mails, PDFs, ZIP-Ordner. Physarum findet darin, welche Dinge es in Ihrer Firma gibt (Kunden, Artikel, Aufträge, Rechnungen …), wie sie zusammenhängen und wie Ihre Abläufe laufen. Daraus entsteht Ihr ERP – ohne Einrichtung, ohne Berater, ohne Cloud.

Vorbild ist der Schleimpilz *Physarum polycephalum*: Er wächst überall hin, verstärkt die Röhren, durch die viel fließt, und lässt die anderen verkümmern. Physarum macht dasselbe mit Ihrem Datenmodell: Verbindungen, die viel tragen (viele Verknüpfungen, viel Geld, viel Nutzung), werden prominent; Ungenutztes tritt in den Hintergrund – gelöscht wird nie etwas.

![Heute](docs/screenshots/03-heute.png)

## Starten

```bash
pip install -e .            # starlette, uvicorn, jinja2, python-multipart, openpyxl
pip install -e ".[dokumente]"  # optional: PDF, Word, HTML (pdfplumber, python-docx, beautifulsoup4)
python -m physarum firma    # Ordner "firma" = Datenbank + Originaldateien
```

Dann `http://127.0.0.1:8000` öffnen und Dateien in das Fenster ziehen – oder **„Beispiel-Firma einwerfen“** klicken: eine erfundene Kaffeerösterei mit 21 typisch unordentlichen Dateien (Listen, Exporte, Kontoauszug, Mails, eine PDF-Rechnung und E-Rechnungen). Nach dem ersten Wachstum lässt sich mit „Nachträglich einwerfen“ ausprobieren, wie eine neue Liste (Wartungsverträge) organisch eingebaut wird.

Ohne Browser einwerfen und wachsen lassen: `python -m physarum firma --einwerfen ~/Exporte`. `python -m physarum firma --beispiel` erzeugt die Beispiel-Firma, lässt sie wachsen und startet dann den Server.

## Was beim Einwerfen passiert

| Schritt | Was Physarum tut | Beispiel aus der Beispiel-Firma |
|---|---|---|
| Verdauen | Tabellen finden – auch mit Titelzeilen, Abschnittszeilen, Summenzeilen, cp1252, Dezimalkomma; Schlüssel-Wert-Texte; E-Mails mit Anhängen; PDFs | „Summe“-Zeile im Rechnungsbuch wird erkannt und weggelassen; „ESPRESSO“-Zwischenzeilen der Preisliste werden zur Spalte *Gruppe* |
| Verstehen | Werte deuten: Beträge, Datumsformate, IBAN (mit Prüfziffer), PLZ, E-Mail, Kennungen, Status | „#1001“ in einer Spalte namens *Name* ist eine Bestellnummer |
| Herauslösen | Eingebettete Dinge aus flachen Exporten lösen – nur wenn es sich lohnt (MDL, s. u.) | Aus dem Shop-Export entstehen Bestellungen, Positionen, Kunden, Artikel |
| Vereinen | Gleiches aus verschiedenen Dateien zusammenführen | Kundenliste + CRM-Export + Shop-Käufer + Kunden aus Aufträgen = *Kunden* |
| Dubletten | Sicher Gleiches zusammenführen, Unsicheres fragen | „Feinkost Tidenhub“ (K-1005) und „Feinkost Tidenhub GmbH“ (K-1099): gleiche Adresse und Telefonnummer, aber verschiedene Kundennummern → Frage |
| Verbinden | Verweise über Werte finden, auch im Freitext | Der Kontoauszug „bezahlt“ Rechnungen, weil ihre Nummer im Verwendungszweck steht |
| Verhalten lernen | Formeln, Vorgaben, Nummernkreise, Mindestbestände | *Brutto = Netto + MwSt*, *MwSt = Netto × 0,07*, *kg = Säcke × 60*, nächste Nummer *RE-2026-0189* |
| Abläufe ablesen | Jede Datumsspalte ist ein Meilenstein; Abweichung vom Üblichen ist Arbeit; über Dateien hinweg verkettet bis zum Geld | Aufträge: *Datum → geliefert (Ø 3 Tage) → berechnet (Ø 1 Tag) → bezahlt (Ø 13 Tage)*: üblich 18 Tage, bis das Geld da ist; am längsten dauert das Warten auf die Zahlung |

Das Ergebnis ist die Seite **Heute**:

- überfällige Rechnungen;
- Fertiges, das noch nicht berechnet ist;
- Lieferantenrechnungen, die zu bezahlen sind (mit Skonto-Frist), und solche, die nach Betrug aussehen;
- Angebote, deren Nachfass-Tag gekommen ist;
- fällige Wartungen, HU und Prüfungen;
- Mails, die auf eine Antwort warten;
- Geld, das keine Rechnung bezahlt;
- knapper Bestand und Reichweite;
- Kunden, die ungewöhnlich lange nichts bestellt haben.

Dazu kommen ein paar Fragen und Vorschläge („Trampelpfade“), etwa „15 Rechnungen sind laut Kontoauszug schon bezahlt, stehen aber noch auf offen – abgleichen?“. Gefragt wird nur, was die Inhaberin entscheiden muss.

## Prinzipien

1. **Einwerfen statt einrichten.**
2. **Nichts geht verloren:** Originale bleiben unverändert, jede Zahl führt zurück zur Quelldatei und Zeile, jede Änderung ist ein neuer Protokolleintrag.
3. **Kompression als Bauplan (MDL):** Ein neuer Begriff entsteht nur, wenn er mehr Wiederholung spart, als er Komplexität kostet.
4. **Fluss als Relevanz (Physarum nach Tero et al. 2010):** Kirchhoff-Fluss auf dem Typen-Graphen und Anpassung der Leitfähigkeit; Nutzung fließt mit ein. Navigation, Spalten und Reihenfolgen folgen der Leitfähigkeit, mit Hysterese, damit nichts herumspringt.
5. **Prozesse aus Zeitstempeln, Arbeit aus Abweichungen.**
6. **Fragen statt Konfigurieren:** wenige Fragen mit Begründung, sortiert nach Wirkung.
7. **Fester Kern:** Ausgestellte Rechnungen sind festgeschrieben (nur Storno), Datensätze mit Verweisen sind nicht löschbar, Regeln wirken nur nach Zustimmung.

Der vollständige Gedankengang mit der kritischen Prüfung der Grundidee und den Einwänden der unabhängigen Reviews steht in [docs/KONZEPT.md](docs/KONZEPT.md).

## Aufbau

```
physarum/
  ingest.py        Dateien → Tabellen/Dokumente (Tabellenerkennung)
  values.py        Werte verstehen, Spalten profilieren
  lexicon.py       kleines „Genom“: kaufmännische Begriffe DE/EN
  infer/           observe · normalize (MDL) · unify · identity · relations
  pdfinvoice.py    Rechnungs-PDFs lesen wie E-Rechnungen; einvoice.py: XRechnung/ZUGFeRD
  grow.py          Wachstum: Substrat → Modell → Datensätze (deterministisch, reihenfolgeunabhängig)
  behavior.py      Formeln, Vorgaben, Nummernkreise, Schwellen, Preis-Übernahmen
  payments.py      Zahlungsbuch: Kontoauszug ↔ Rechnungen, eine Wahrheit für „offen“
  reconcile.py     Lieferantenrechnungen prüfen (Betrug, doppelt), Geld ohne Rechnung
  process.py       Meilenstein-Abläufe, Aufgaben für „Heute“, Kennzahlen, Rhythmen, Reichweiten
  billing.py       Rechnung aus dem Auftrag, Ausstellen, Storno; dunning.py: Zahlungserinnerung
  taxexport.py     Paket für die Steuerberatung (DATEV); procedure.py: Verfahrensdokumentation
  coverage.py      Abdeckung: wie vollständig die Firma abgebildet ist
  physarum.py      Tero-Modell + Layout + Salienz
  questions.py     Fragen und Antworten (als Randbedingungen)
  ops.py           Schreiben mit Regeln (Festschreibung, Storno, Zahlungen, Protokoll)
  store.py         SQLite: Substrat, Modellversionen, Datensätze, Protokoll, Suche (FTS5)
  web/             Starlette + Jinja2, serverseitig gerendert, wenig Vanilla-JS
  demo/generate.py Beispiel-Firma (21 unordentliche Dateien)
tests/             unittest: Werte, Einlesen, Inferenz, Physarum, Ende-zu-Ende, Webseiten
e2e/screens.cjs    Playwright-Rundgang mit Screenshots
```

## Tests

```bash
python -m unittest discover -s tests -t .
node e2e/screens.cjs http://127.0.0.1:8000 docs/screenshots   # bei laufendem Server, leere Firma
node e2e/flow.cjs http://127.0.0.1:8000                       # Alltag: Rechnung, Zahlung, Mahnung
```

## Rechnungen, Geld und Steuerberatung

- **Ausgangsrechnungen** aus dem Auftrag: Entwurf, Ausstellen mit fortlaufender Nummer, Druck nach § 14 UStG und **XRechnung**; danach festgeschrieben, Korrektur nur per Storno-Beleg.
- **Abschlags- und Schlussrechnungen:** Offen ist der Zahlbetrag nach Abschlägen, ein Sicherheitseinbehalt wird nicht gemahnt, der Umsatz zählt keinen Abschlag doppelt. Die Schlussrechnung setzt ihren Auftrag auf „abgerechnet“ (im Wort der Firma).
- **Zahlungen** kommen aus dem Kontoauszug – über die Nummer im Verwendungszweck (auch „RE 2026 0089“), sonst über Betrag, Zahler und Tag (auch Skonto, Sammelzahlungen, Zahlendreher, Gutschriften, die Nummer eines anderen Kunden). Eindeutiges wird gebucht, Unsicheres gefragt, und solange die Frage offen ist, geht keine Mahnung raus. Bar, Scheck und Teilzahlungen trägt man an der Rechnung ein; eine Kontozeile ohne Nummer ordnet man mit einem Klick zu. Daraus folgen „offen“, „überfällig“ und die Zahlungserinnerung mit der richtigen Anrede.
- **Eingangsrechnungen** aus PDF oder E-Rechnung (XRechnung/ZUGFeRD) werden gelesen, nachgerechnet und vor dem Bezahlen geprüft: Rechenfehler, fehlende Pflichtangaben, falscher Empfänger, eine neue Bankverbindung, eine ähnliche, aber fremde Absender-Domain, eine Mail über „neue Kontodaten“, die erste Rechnung eines unbekannten Lieferanten, zweimal eingegangene Rechnungen. „Zu bezahlen“ nennt die Skonto-Frist; Verdächtiges steht nicht darauf.
- **Für die Steuerberatung** entsteht je Monat, Quartal oder Jahr ein ZIP: Ausgangsrechnungen als DATEV-Buchungsstapel (eine Buchung je Rechnung und Steuersatz, SKR03/SKR04), beide Rechnungsbücher, Umsatzsteuer je Satz (Soll oder Ist), offene Posten, Debitoren/Kreditoren, die Belege und ein Prüfprotokoll mit Prüfsummen.
- **Nachvollziehbarkeit:** Das Änderungsprotokoll ist versiegelt (jeder Eintrag trägt den SHA-256-Prüfwert aller vorherigen; Ändern und Löschen weist die Datenbank ab), archivierte Belege sind unveränderlich, und die **Verfahrensdokumentation** schreibt sich in den GoBD-Kapiteln aus Quellen, Regeln, Entscheidungen und Protokoll.

## Grenzen (ehrlich)

- Rechnungs-PDFs werden ausgelesen, Mails nach ihrem Anliegen eingeordnet (Bestellung, Anfrage, Bitte, Reklamation, Kündigung, „schon bezahlt“, neue Bankverbindung). Anderer Freitext wird **verknüpft und durchsuchbar**, aber nicht inhaltlich in Datensätze zerlegt; dafür wäre ein optionaler Sprachmodell-Baustein der nächste Schritt (Vorschlag → Prüfung durch Invarianten → Mensch). Scans ohne Textebene werden aufbewahrt, aber nicht gelesen.
- Keine Finanzbuchhaltung: Physarum liefert der Steuerberatung Buchungsstapel und Belege, bucht aber keine Aufwandskonten und erstellt keine Umsatzsteuer-Voranmeldung. Der DATEV-Export folgt dem veröffentlichten Format, ein Probe-Import bei der Steuerberatung gehört dazu.
- Noch keine Benutzerrechte (der Name steht im Protokoll); gedacht für einen Rechner im Büro.
- Heuristiken können irren. Deshalb ist alles erklärt („Wie Physarum Ihre Firma sieht“), korrigierbar und umkehrbar – auch Zusammenführungen auf Vermutung („Wieder trennen“) –, und die Originale bleiben unangetastet.
