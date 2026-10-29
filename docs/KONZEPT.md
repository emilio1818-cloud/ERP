# Physarum — ein ERP, das aus den Daten einer Firma wächst

> Arbeitsstand des Konzepts. Abschnitt 8 hält fest, was die unabhängigen Reviews daran verändert haben.

## 1. Was eigentlich erreicht werden soll

Die Idee heißt „ERP“, aber kein Kleinbetrieb *will* ein ERP. Er will:

- **Überblick:** Was haben wir? (Kunden, Artikel, Bestände, offenes Geld)
- **Kontrolle:** Was muss heute passieren? Was hängt, was ist überfällig?
- **Zusammenhang:** Die E-Mail gehört zum Auftrag, der Auftrag zur Rechnung, die Rechnung zur Zahlung auf dem Kontoauszug. Das soll man sehen, ohne zu suchen.
- **Kein Projekt:** keine Berater, keine monatelange Einführung, und die Firma muss sich nicht an die Software anpassen.

Klassische ERPs zwingen die Firma in ein vorgefertigtes Modell (Customizing). Die Idee dreht das um: **Das Modell wird aus der Firma abgeleitet.**

Daraus folgt eine Umdeutung, die den ganzen Entwurf trägt:

> **Jede Firma hat schon ein ERP. Es liegt verstreut in Excel-Listen, Exporten, E-Mails, Kontoauszügen und Köpfen, nur ist es nicht verbunden.**
> Physarum baut kein ERP von außen. Es findet das vorhandene und verbindet es, so wie der Schleimpilz das Labyrinth nicht baut, sondern den Weg hindurch findet.

## 2. Die Grundidee, kritisch geprüft

### Wo die Metapher trägt

- **Erkunden, verstärken, verkümmern lassen:** Physarum plant nichts zentral. Es wächst überall hin, verstärkt Röhren mit viel Fluss und lässt die anderen verkümmern. So entsteht ein effizientes Netz. Genau das fehlt Software, die einmal konfiguriert wird und danach starr bleibt.
- **Das Netz ist das Gedächtnis:** Die Struktur ist der Rückstand der Nutzung, wie Trampelpfade.
- **Wandel ohne Migration:** Ändert die Firma ihren Ablauf, verkümmern die alten Röhren und neue wachsen. Niemand muss eine Datenbank umbauen.

### Wo sie bricht, und was daraus folgt

| Problem | Konsequenz im Entwurf |
|---|---|
| **Pruning ist im ERP gefährlich.** Inventur, Jahresabschluss und Mahnlauf sind selten, aber kritisch. Ein Schleimpilz würde sie abschneiden. | Verkümmern wirkt nur auf die **Sichtbarkeit**, nie auf die **Existenz**. Nichts wird gelöscht. Wichtigkeit setzt sich aus Fluss, Geldwert und Fristen zusammen, nicht nur aus Klicks. |
| **„Optimal abbilden“ widerspricht sich, wenn man nur abbildet.** Wer den Ist-Prozess perfekt kopiert, kopiert auch seine Umwege. Physarum kopiert das Labyrinth nicht, es *löst* es. | Das System bildet ab **und** zeigt die Abkürzungen: Engpässe, übliche Durchlaufzeiten, Ausreißer und Automatisierungsvorschläge („Trampelpfade pflastern“). |
| **„Egal in welcher Form“ heißt auch: Müll rein.** Dubletten, Tippfehler, Widersprüche. Wer daraus still Strukturen baut, baut die Fehler mit ein. | Sicher handeln, wo die Evidenz stark ist, und **fragen, wo sie schwach ist**, aber nur die wenigen Fragen mit der größten Wirkung. Wie eine neue Mitarbeiterin, nicht wie ein Einrichtungsassistent mit 200 Feldern. |
| **Ein ERP ist ein „System of Record“** (Belege, GoBD: Unveränderbarkeit, Nachvollziehbarkeit). Ein System, das sich selbst verändert, wirkt erst einmal verdächtig. | Es muss *mehr* Nachvollziehbarkeit bieten als üblich: Jede Zahl hat eine Herkunft (Datei, Zeile), jede Änderung ist ein neuer Eintrag (append-only), jede Annahme kann man erklären lassen und korrigieren. |
| **Eine „Belohnung“ braucht eine Messgröße**, sonst bleibt sie Marketing. | Siehe Abschnitt 3: Kompression als Zielfunktion. |
| **Physarum hat keine Menschen.** Eine Firma schon. | Menschliche Entscheidungen sind die stärksten Signale. Sie werden als Randbedingungen gespeichert und überleben jedes Neuwachsen. |

## 3. Die Zielfunktion: Kompression

„Prozesse vollständig und optimal abbilden“ lässt sich präzise fassen:

> **Das beste ERP ist die kürzeste Beschreibung der Firma, die alle ihre Daten erklärt.**
> (Minimum Description Length: L(Modell) + L(Daten | Modell) → min)

- **Vollständig** heißt, dass jede Zeile, jede Datei und jedes Dokument im Modell abgebildet ist. Nichts geht verloren.
- **Einfach** heißt, dass das Modell so wenige Begriffe, Felder und Schritte wie möglich hat.
- **Jede Strukturentscheidung muss sich bezahlt machen.** Ein neuer Datentyp, etwa „Kunde“ aus einer flachen Umsatzliste herausgelöst, entsteht nur, wenn er mehr Redundanz spart, als er an kognitiver Komplexität kostet. Das ist Datenbank-Normalisierung mit Preisschild.

Dasselbe Prinzip entscheidet überall:

| Entscheidung | Warum sie komprimiert |
|---|---|
| Kunde aus Auftragsliste herauslösen | Name und Adresse stehen nicht mehr 300-mal da, sondern einmal |
| Dubletten zusammenführen („Müller GmbH“ = „Mueller GmbH“) | ein Datensatz statt zwei |
| Formel entdecken (Brutto = Netto × 1,07) | Brutto muss nicht mehr gespeichert, nur noch berechnet werden |
| Verweis statt kopiertem Namen | der Name steht beim Kunden, nicht in jeder Rechnung |
| Auswahlliste statt Freitext (Status: offen/bezahlt) | 2 Bit statt eines Wortes |
| Datumsabstand als Regel (fällig = Datum + 14 Tage) | Vorschlagswert statt Eingabe |

Neben der Kompression wirkt eine zweite Kraft, wie beim Schleimpilz:

- **Struktur aus Kompression:** Was in den Daten steckt, wird zum Modell.
- **Relevanz aus Fluss:** Was benutzt wird und wo Geld und Fristen fließen, wird sichtbar.

## 4. Prinzipien

1. **Einwerfen statt Einrichten.** Es gibt eine Drop-Zone und keine Konfiguration.
2. **Nichts geht verloren.** Rohdaten bleiben unverändert erhalten (Substrat). Alles Abgeleitete lässt sich neu berechnen, jede Änderung ist ein neuer Eintrag mit Herkunft.
3. **Kompression als Bauplan.** Typen, Verweise, Formeln, Auswahllisten und Dubletten werden per MDL entschieden.
4. **Fluss als Relevanz.** Datenmenge und Nutzung sind die Nährstoffe. Eine Verbindung ist so dick wie das, was durch sie fließt; ungenutzte verblassen, verschwinden aber nie.
5. **Prozesse aus Zeitstempeln.** Jede Datumsspalte ist ein Meilenstein. Reihenfolge und typische Abstände ergeben den Prozess, auch ohne Event-Log. **Was vom Üblichen abweicht, ist Arbeit.** So entsteht die Liste „Heute zu tun“ ohne eine einzige konfigurierte Regel.
6. **Fragen statt Konfigurieren.** Gefragt wird nur, was die Inhaberin weiß und die Daten nicht sagen: ob zwei Einträge derselbe Kunde sind, ob eine Überweisung eine Rechnung bezahlt. Wenige Ja/Nein-Fragen, sortiert nach Wirkung (betroffene Datensätze × Unsicherheit). Wie die Dateien zu lesen sind (zwei Listen oder eine, eine Spalte als Text oder als Verknüpfung), entscheidet das System selbst. Die Entscheidung steht als Hinweis an der Liste, mit einem Knopf, der sie umkehrt.
7. **Trampelpfade pflastern.** Was Menschen oder Daten wiederholt tun, etwa „wenn ‚bezahlt am‘ gesetzt wird, wird Status = bezahlt“, wird als Automatisierung angeboten, nie heimlich eingeführt.
8. **Erklärbar.** Zu jeder Annahme gibt es ein „Warum?“ mit Evidenz und ein „Korrigieren“.

## 5. Architektur

```
 Dateien (xlsx, csv, txt, eml, pdf, docx, json, zip)
        │  Verdauung: Tabellen erkennen (Kopf-, Titel- und Summenzeilen), Werte verstehen
        ▼  (Dezimalkomma, Datumsformate, IBAN, PLZ …), Freitext als Dokument
 ┌──────────────┐
 │  Substrat    │  unveränderliche Rohdaten: Quellen, Rohtabellen, Rohzeilen, Dokumente
 └──────┬───────┘
        │  Wachstum (deterministisch, erklärbar):
        │   1. Spalten profilieren (Typ, Rolle, Muster, Entropie)
        │   2. Normalisieren: funktionale Abhängigkeiten + MDL → eingebettete Entitäten herauslösen
        │   3. Vereinigen: gleiche Dinge aus verschiedenen Dateien zu einem Typ zusammenführen
        │   4. Dubletten auflösen (Entity Resolution) – unsicher → Frage
        │   5. Verweise entdecken (Inklusionsabhängigkeiten, auch in Freitext: Verwendungszweck)
        ▼
 ┌──────────────┐   Randbedingungen (menschliche Antworten) fließen in jeden Lauf ein
 │  Organismus  │   Typen, Felder, Verweise, Formeln, Vorgaben, Nummernkreise, Prozesse
 └──────┬───────┘
        │  Materialisieren: Datensätze mit stabiler Identität + Änderungsprotokoll + Suchindex
        ▼
 ┌──────────────┐   Verhalten: Formeln, Vorgaben, Meilenstein-Prozesse, Aufgaben, Kennzahlen
 │  Datensätze  │   Zahlungsbuch: Kontoauszug ↔ Rechnungen ↔ Lieferantenrechnungen, eine Wahrheit für „offen“
 └──────┬───────┘   Physarum: Dicke der Verbindungen aus Daten- und Nutzungsfluss
        ▼
   Oberfläche: Heute · Listen · Datensatz · Formulare · Organismus · Prozesse · Fragen
```

**Technik:** Python 3, Starlette, Jinja2 und SQLite (WAL, FTS5), serverseitig gerendert mit wenig Vanilla-JS. Es gibt keinen Build-Schritt und keinen externen Dienst, alles läuft lokal und offline. Ein einzelner Ordner mit einer SQLite-Datei und den Originaldateien ist die komplette Firma; ein Backup heißt, diesen Ordner zu kopieren.

## 6. Was daran neu ist

- **MDL als einziges Entscheidungsprinzip für die ERP-Struktur.** Ob etwas ein eigener Typ, ein Verweis, eine Formel oder eine Auswahlliste wird, entscheidet die Frage, ob es die Beschreibung der Firma kürzer macht.
- **Prozesse und Aufgaben aus Momentaufnahmen.** Process Mining braucht normalerweise Event-Logs, die Kleinbetriebe nicht haben. Physarum liest den Prozess aus der Ordnung der Datumsspalten über Tabellen hinweg ab (Auftrag → Lieferung → Rechnung → Zahlung).
- **Abweichung vom Üblichen ist Arbeit.** Die Aufgabenliste wird nicht programmiert, sie entsteht aus den gelernten Durchlaufzeiten.
- **Bis das Geld da ist.** Die Abläufe einzelner Listen werden verkettet, wo der Schritt der einen ein Datensatz der anderen ist (der Auftrag ist „berechnet“, sobald seine Rechnung existiert, die dann „bezahlt“ wird). So entsteht ohne Konfiguration die Kette vom Auftrag bis zum Geld mit ihrer üblichen Dauer und dem Abschnitt, in dem am längsten gewartet wird.
- **Physarum als Bauprinzip, nicht als Gleichung.** Alles wird aufgenommen, nichts gelöscht, Ungenutztes verblasst; eine Verbindung ist so dick wie das, was durch sie fließt (verknüpfte Datensätze und Nutzung). Bis Runde 6 rechnete ein Tero-Löser (Kirchhoff-Fluss mit Anpassung der Leitfähigkeit, 348 Zeilen) diese Dicke aus. Er ordnete nur die Liste im Menü und auf keiner der sieben Prüffirmen gab es zwischen Auftrag und Geld mehr als einen Weg, also kein Labyrinth, in dem er etwas hätte finden können. Er wurde durch die direkte Messung ersetzt. Das Labyrinth-Bild des Auftrags („der optimale Weg zum Futter“) ist die Kette „bis das Geld da ist“: vom ersten Schritt eines Falls bis zum Geld auf dem Konto, mit dem Abschnitt, in dem am längsten gewartet wird.
- **Der Kontoauszug schließt Rechnungen von selbst.** Verweise werden auch in Freitext gefunden, etwa „RE-2026-0412“ im Verwendungszweck.
- **Bezahlt ist, was das Geld sagt, nicht wie die Spalte heißt.** Der Kontoauszug wird an seinen Spalten erkannt (IBAN oder Verwendungszweck, Betrag, Buchungstag), nicht am Dateinamen. Ein Schritt, den Kontobuchungen belegen, ist „bezahlt“. Eine eigene Datumsspalte, die mit diesen Buchungen übereinstimmt, ist das Zahldatum, ob sie „Bezahlt am“ heißt oder „Ausgeglichen am“. Eine Liste, die der Kontoauszug bezahlt, ist eine Rechnung, und was auf sie verweist, ist „berechnet“. Sagt der Dateiname nichts („export (5).csv“), heißt die Liste nach ihrer Nummernspalte („Beleg-Nr“ – Belege) oder nach dem, was das Geld mit ihr macht (Rechnungen, Kontobewegungen), und ist dann in jeder Hinsicht eine Rechnung: Nummernkreis, Druck, E-Rechnung, Steuerberater-Export. Der Prüfstand rechnet dieselben Firmen unter anderen Datei- und Spaltennamen; die offenen Posten bleiben gleich.
- **Geld, das zurückgeht, folgt dem Erhaltungssatz.** Eine Rücklastschrift macht eine Zahlung ganz rückgängig (oft mit der Gebühr der Bank obendrauf), die Rechnung ist wieder offen – auch wenn die Einziehung in einer Sammellastschrift steckte, die die Rechnung nicht nennt. Weniger als eine Zahlung zurück ist eine Erstattung: Das Erstattete ist nicht mehr geschuldet. Ein Skonto-Abzug, den das eigene Buch als bezahlt führt, ist angenommenes Skonto.
- **Formeln werden entdeckt, nicht programmiert.**
- **Fragen nach Informationswert.** Statt eines Einrichtungsassistenten kommen die drei Fragen, deren Antwort am meisten klärt.

## 7. Ehrliche Grenzen

- Ohne Sprachmodell werden Rechnungs-PDFs gelesen wie E-Rechnungen (Nummer, Beträge, Fristen, Skonto, IBAN), Mails nach ihrem Anliegen eingeordnet (Bestellung, Bitte, Reklamation, Kündigung, „schon bezahlt“, neue Bankverbindung) und über der Tabelle Stehendes („Auftrag: A26-028“) übernommen. Anderer Freitext wird **verknüpft und durchsuchbar gemacht**, aber nicht in Datensätze zerlegt. Gescannte PDFs ohne Textebene liest Physarum nicht (kein OCR). Ein optionaler LLM-Baustein ist als Erweiterung vorgesehen.
- Physarum ist die **operative** Schicht und keine Finanzbuchhaltung. Die Steuerberatung bekommt einen DATEV-Buchungsstapel der Ausgangsrechnungen, die Bücher und die Belege; Aufwandskonten und Voranmeldung bleiben bei ihr.
- Mehrbenutzerbetrieb und Rechte sind nur rudimentär vorhanden (Name im Änderungsprotokoll).
- Heuristiken irren. Deshalb ist alles erklärbar, korrigierbar und umkehrbar, und die Originaldaten bleiben unangetastet.
- Unter neutralen Dateinamen weiß Physarum nicht mehr, dass die Käufer im Shop-Export Kunden sind; sie bleiben eine eigene Liste neben den Kunden aus CRM und Kundenliste, und die Zusammenlegung steht als Hinweis an der Liste.
- Ein Kontoauszug, der nur Zahlungseingänge auf Rechnungen enthält und dessen Verwendungszweck nur die Rechnungsnummer nennt, sieht unter einem neutralen Dateinamen aus wie eine zweite Fassung des Rechnungsbuchs und wird mit ihm zu einer Liste. Echte Auszüge mit Miete, Löhnen und Lastschriften trennt Physarum richtig.

## 8. Was die unabhängigen Reviews verändert haben

### 8.1 Vor dem Bau: drei Konzept-Memos

Drei Reviewer hatten nur die ursprüngliche Idee vor sich und kannten diesen Entwurf nicht: ein ERP-Praktiker mit 20 Jahren Mittelstand, ein Forscher für adaptive Systeme, Process Mining und MDL, und eine Inhaberin einer Kaffeerösterei. Daraus wurde übernommen:

| Einwand / Idee | Quelle | Was daraus wurde |
|---|---|---|
| **„Fester Kern, wachsende Hülle.“** Ein System, das seinen buchhaltungsrelevanten Kern selbst umbaut, ist in Deutschland nicht betreibbar. | Praktiker | Ausgestellte Rechnungen sind festgeschrieben, Korrektur nur per Storno mit Grund. Datensätze mit Verweisen sind nicht löschbar. Gelernte Regeln wirken erst nach Zustimmung („Trampelpfade“). |
| **Salienz beschneiden, nie Semantik**; μ > 1 macht das Netz zum Baum | Forscher | Physarum steuert nur Sichtbarkeit. Der erste Lauf mit μ = 1,6 hat tatsächlich den Belegfluss Rechnung → Auftrag weggeschnitten, deshalb gilt jetzt μ = 0,85 (redundantes, robustes Netz). Navigation mit Hysterese, nichts springt. |
| **Erhaltungssätze als Hunger:** Wo Geld nicht aufgeht, fehlt ein Prozess oder eine Verknüpfung | Forscher | Bankabgleich auf zwei Wegen: über Nummern im Verwendungszweck und über den Betrag (centgenau, mit Skonto oder als Summe zweier Rechnungen). Ob bezahlt ist, sagt allein das Zahlungsbuch; die Status-Spalte der Datei heißt „laut Datei“. |
| **Eingegebene Bits pro Vorgang** als Nordstern; die Maske fragt nur, was nicht vorhersagbar ist | Forscher | Formulare belegen vor: Nummer, Datum, Status, Formeln, Preis aus dem Artikel, Fälligkeit aus dem Zahlungsziel des Kunden, „Wie beim letzten Mal“. |
| **Aha-Moment:** „Café Linde bestellt sonst alle zwei Wochen, seit sieben Wochen nichts“ | Inhaberin | Rhythmus-Analyse je Kunde und Lieferant; dazu die Reichweite der Bestände. |
| **Jede Zahl bis zur Quelle**, Geratenes sichtbar von Sicherem getrennt; Fragen mit Begründung, „Weiß nicht“, „Später“, nie zweimal | Inhaberin, Praktiker | Herkunft je Feld (Datei, Zeile), Markierungen „berechnet“, „abweichend“ und „nicht verknüpft“; Fragen nach Wirkung sortiert. |
| **Manipulierte Eingangsrechnung** (neue IBAN, ähnliche Domain) | Praktiker | Warnung „Bankverbindung, an die nie gezahlt wurde“ und „Absender ähnlich, aber nicht gleich“. |
| **Verfahrensdokumentation als Nebenprodukt** des Wachstums | Praktiker, Forscher | Seite „Verfahrensdokumentation“ aus Quellen, Regeln, Entscheidungen und Protokoll. |
| Mahnwesen, Datenstand („Inventur vom 31.12. ist nicht der aktuelle Bestand“), Lücken im Nummernkreis | Praktiker, Inhaberin | Zahlungserinnerung als Entwurf (nie, wenn eine passende Zahlung wartet), „Stand“ je Quelle, die aktuellere Quelle gewinnt, Lückenprüfung nach GoBD. |

Bewusst **nicht** übernommen:

- Ein firmenübergreifender Struktur-Prior („Genom aus vielen Firmen“) passt nicht zum Versprechen „bleibt bei Ihnen“.
- E-Rechnung (XRechnung/ZUGFeRD) und DATEV-Export standen hier als nächste Schritte – beide sind inzwischen gebaut (siehe 8.2).
- Die LLM-Extraktion aus Freitext bleibt ein optionaler Baustein.
- Der Schattenbetrieb über 4–8 Wochen ist eine organisatorische Frage. Unterstützt wird er dadurch, dass sich Quellen jederzeit herausnehmen und wieder aufnehmen lassen.

### 8.2 Nach dem Bau: Prüfungen mit fremden Augen

Danach wurde in Runden geprüft, jedes Mal von Prüfern, die den Code nicht kannten und eine eigene „Wahrheit“ mitbrachten:

- eine Inhaberin, die mit der Beispiel-Firma ihren Alltag durchspielt;
- eine ihr unbekannte Webagentur mit zwei Lieferungen (CRM, zwei Zeiterfassungen, Ticketsystem, Rechnungsbuch, Kontoauszug, Freelancer-Stundenzettel, Mails), deren richtige Zahlen vorher feststanden;
- eine Sicherheitsprüfung mit präparierten Dateien;
- zuletzt ein Handwerksbetrieb (Haustechnik, 11 Leute) mit zwei Lieferungen aus gewachsener Ablage: Auftragsbuch mit einem Blatt je Jahr, Stundenzettel je Monteur, Aufmaße, Wartungsverträge, Fuhrpark, Kundenstamm aus einem alten Programm, zwei Banken, Lieferantenrechnungen nur als PDF, Mails und die Listen der Steuerberatung.

| Befund | Was daraus wurde |
|---|---|
| Beim zweiten Einwerfen verloren Rechnungen ihre Identität; überlappende Exporte doppelten Zeiteinträge | Versionen einer Liste werden je Schlüssel zusammengeführt, die neuere Datei gilt für ihren Zeitraum, gelöschte Zeilen werden als „fehlt in der neuesten Fassung“ markiert statt still entfernt |
| „Offen“ stimmte nicht: Soll/Haben-Spalten, Gutschriften, Storno, Zahlendreher, Zahlungen ohne Nummer | Eine Wahrheit für „offen“ aus dem Kontoauszug; bei der Agentur stimmen die offenen Posten beider Lieferungen centgenau (32 / 39.949,38 € und 13 / 49.390,91 €), 163 von 163 Zahlungen ohne Nummer richtig zugeordnet |
| Ticketsystem und Projektliste nennen Kunden „Wattwurm“ oder „Optik Schulz“ | Kurzformen gehören zum einzigen Kunden, dessen Name alle ihre Wörter enthält; mehrdeutige („Hafenkontor“) bleiben offen. Projekte mit Kunde von 76 auf 140 von 143, ohne Fehlzuordnung; jede Zusammenführung auf Vermutung lässt sich wieder trennen |
| Fehlalarme auf „Heute“ (Retainer „überfällig“, Projekte nie abgeschlossen, Daten älter als heute) | Kennzahlen zum Datenstand, geplante Termine als Norm, Vorgänge ohne Abschluss werden nicht angemahnt |
| Hänger bei einer 5-MB-Zelle, 2.500 Spalten, 300.000 Zeilen | Begrenzte Suche, linearer Versionsabgleich; 300.000 Zeilen in gut einer Minute |
| Eingangsrechnungen mit IBAN galten als Kontoauszug; ohne Lieferantenliste lief Geld falsch herum | Behoben; dazu Nachrechnen empfangener E-Rechnungen und Betrugsprüfung gegen frühere Rechnungen desselben Lieferanten |
| Die Inhaberin: zwei Status im Kopf, Mails mit Bestellungen gehen unter, englische Spaltennamen, kein Paket für die Steuerberatung | Ein Status aus dem Kontoauszug, Mails mit Bestellung/Anfrage/Reklamation auf „Heute“ bis zum Auftrag, deutsche Feldnamen, Steuerberater-Paket mit DATEV-Buchungsstapel, versiegeltes Protokoll |
| Sicherheit: Eine Zelle mit 200.000 Leerzeichen legte das Wachsen stundenlang lahm. Ein mitgeschickter „Zahlungsnachweis“ setzte Rechnungen auf bezahlt und unterdrückte die Mahnung. Physarum ließ sich in fremde Seiten einbetten. | Werte werden nur bis zu einer sinnvollen Länge gedeutet (6 MB in 0,9 s). Geld zählt nur aus eigenen Kontoauszügen, Listen aus Mails erst, wenn die Inhaberin sie anerkennt. Kein Einbetten, kein Inline-Skript. Entpack-Bomben werden vor dem Öffnen erkannt. Eine geänderte Lieferanten-IBAN ist Betrugsverdacht. |
| Handwerk, Geld: Rechnungen ohne Fälligkeit, Schlussrechnungen mit Abschlägen, Sicherheitseinbehalt, Zahlungen ohne Nummer oder mit der Nummer eines anderen Kunden, eine zweite Bank mit S/H-Spalte | Fälligkeit aus dem Zahlungsziel des Kunden, sonst 30 Tage (§ 286 BGB), sichtbar als berechnet. Offen ist der Zahlbetrag nach Abschlägen, ein Einbehalt wird nicht gemahnt. Eindeutige Zahlungen werden gebucht, unsichere gefragt, und solange die Frage offen ist, geht keine Mahnung raus. In beiden Lieferungen stimmt jeder offene Betrag centgenau (18.237,08 € und 39.348,27 € über 107 und 134 Rechnungen), und alle Zahlungseingänge sind richtig zugeordnet (63 und 105). |
| Handwerk, Namen: Kundenstamm mit NAME1/NAME2 und KDNR; die Bücher schreiben „Fam. Tepe“, „ZA-Praxis Lehmann“, „Müller, Hans-Peter“ oder den alten Namen einer umbenannten Firma; ein Kunde steht in keiner Liste | Personen bekommen ihren vollen Namen. Kürzel, Initialen, Titel, Abkürzungen, Wortreihenfolge, frühere Namen und die Nachbarn im Belegfluss entscheiden die Zuordnung. Ein Kunde, den nur die Bücher kennen, wird angelegt und sagt, woraus er erschlossen ist. 134 von 134 Rechnungen und 26 von 26 Wartungsverträgen hängen an ihrem Kunden, 133 von 134 Aufträgen, ohne falsche Zuordnung. |
| Handwerk, Struktur: ein Blatt je Jahr und je Monteur mit anders benannten Spalten; Aufmaße ohne Auftrag; sieben Rückfragen, von denen eine echt war | Blätter einer Datei und Listen derselben bekannten Art werden ohne Rückfrage eine Liste. Spalten werden über Nummernmuster, zusammengesetzte Wörter und gleiche Meilensteine verglichen. Was über einer Tabelle steht („Auftrag: A26-028“), wird zur Spalte jeder Zeile. Übrig bleibt die eine Frage, die der Chef entscheiden muss: zwei Müllers an derselben Straße. |
| Handwerk, Alltag: Was morgens zählt, fehlte auf „Heute“: Angebote zum Nachfassen, fertige, nicht berechnete Aufträge, fällige Wartungen und HU, Mails, die auf Antwort warten, Geld ohne Rechnung, Lieferantenrechnungen mit Skonto-Frist – und ein Betrugsversuch mit neuer IBAN und ähnlicher Domain | Nachfassen an dem Tag, den das Angebotsbuch nennt; verlaufene Angebote nicht (§ 147 BGB). Jeder fertige Auftrag ohne Rechnung. Wartung aus letzter Wartung plus Intervall, einen Monat voraus. Mails mit Bitte, Kündigung, „schon bezahlt“ oder neuer Bankverbindung. „Geld erhalten – wofür?“ mit Anzahlungsrechnung oder Zuordnung. PDF-Rechnungen werden wie E-Rechnungen gelesen, Betrugsverdacht steht ganz oben und nicht auf der Liste zum Bezahlen. Bar- und Teilzahlungen lassen sich eintragen, Kontozeilen von Hand zuordnen. |

