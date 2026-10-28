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

Dann `http://127.0.0.1:8000` öffnen und Dateien in das Fenster ziehen – oder **„Beispiel-Firma einwerfen“** klicken: eine erfundene Kaffeerösterei mit 16 typisch unordentlichen Dateien. Nach dem ersten Wachstum lässt sich mit „Nachträglich einwerfen“ ausprobieren, wie eine neue Liste (Wartungsverträge) organisch eingebaut wird.

Ohne Browser: `python -m physarum firma --einwerfen ~/Exporte` bzw. `python -m physarum firma --beispiel`.

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
| Abläufe ablesen | Jede Datumsspalte ist ein Meilenstein; Abweichung vom Üblichen ist Arbeit | Aufträge: *Datum → geliefert (Ø 3 Tage) → berechnet (Ø 1 Tag)*; 4 Aufträge warten auffällig lange auf ihre Rechnung |

Das Ergebnis ist die Seite **Heute**: überfällige Rechnungen, Lieferungen ohne Rechnung, knapper Bestand und Reichweite, Kunden, die ungewöhnlich lange nichts bestellt haben. Dazu kommen ein paar Fragen und Vorschläge („Trampelpfade“), etwa „15 Rechnungen sind laut Kontoauszug schon bezahlt, stehen aber noch auf offen – abgleichen?“.

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
  grow.py          Wachstum: Substrat → Modell → Datensätze (deterministisch, reihenfolgeunabhängig)
  behavior.py      Formeln, Vorgaben, Nummernkreise, Schwellen, Preis-Übernahmen
  process.py       Meilenstein-Abläufe, Aufgaben, Kennzahlen, Rhythmen, Reichweiten
  physarum.py      Tero-Modell + Layout + Salienz
  questions.py     Fragen und Antworten (als Randbedingungen)
  ops.py           Schreiben mit Regeln (Festschreibung, Storno, Protokoll)
  store.py         SQLite: Substrat, Modellversionen, Datensätze, Protokoll, Suche (FTS5)
  web/             Starlette + Jinja2, serverseitig gerendert, wenig Vanilla-JS
  demo/generate.py Beispiel-Firma (16 unordentliche Dateien)
tests/             unittest: Werte, Einlesen, Inferenz, Physarum, Ende-zu-Ende, Webseiten
e2e/screens.cjs    Playwright-Rundgang mit Screenshots
```

## Tests

```bash
python -m unittest discover -s tests -t .
node e2e/screens.cjs http://127.0.0.1:8000 docs/screenshots   # bei laufendem Server
```

## Grenzen (ehrlich)

- Freitext, PDFs und E-Mails werden **verknüpft und durchsuchbar**, aber nicht inhaltlich in Datensätze zerlegt; dafür wäre ein optionaler Sprachmodell-Baustein der nächste Schritt (Vorschlag → Prüfung durch Invarianten → Mensch).
- Keine Finanzbuchhaltung, kein DATEV-Export und keine E-Rechnung (XRechnung/ZUGFeRD), noch keine Benutzerrechte. Das steht auf der Liste in [docs/KONZEPT.md](docs/KONZEPT.md).
- Heuristiken können irren. Deshalb ist alles erklärt („Wie Physarum Ihre Firma sieht“), korrigierbar und umkehrbar, und die Originale bleiben unangetastet.
