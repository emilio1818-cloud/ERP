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

Für das Geld lässt sich der zweite Term direkt messen: Welcher Anteil des Kontogelds ist durch einen Vorgang erklärt (eine Rechnung, eine Sollstellung, eine Umbuchung)? Der Prüfstand zeigt ihn seit Runde 11 als „Geld erklärt“. Er braucht keine Wahrheit, also könnte jede Firma ihn für sich selbst sehen. Über die zwölf Prüffirmen liegt er bei einem Drittel: 57 % bei der Agentur, 15 % beim Verein. Was unerklärt bleibt, ist der nächste Hunger.

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
   Oberfläche: Heute (mit den Fragen) · Listen · Datensatz · Dateien · Ihre Firma · Wie Physarum Ihre Firma sieht
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
- **Forderungen aus dem Zahlungsbild.** Miete, Hausgeld und Beiträge schuldet ein Vertrag oder Beschluss, keine Rechnung, und oft liegt keins von beiden bei. Physarum leitet die Sollstellungen aus den Zahlungen ab. Zahlen die Mitglieder einer Liste immer wieder einen ihrer Beträge, ist das eine Forderung: im Rhythmus der Zahlungsabstände, ab der ersten Zahlung, bis zu dem Ende, das die Liste nennt. Offen ist, was danach nicht kam.
- **Formeln werden entdeckt, nicht programmiert.**
- **Fragen nach Informationswert.** Statt eines Einrichtungsassistenten kommen die drei Fragen, deren Antwort am meisten klärt.

## 7. Ehrliche Grenzen

- Ohne Sprachmodell werden Rechnungs-PDFs gelesen wie E-Rechnungen (Nummer, Beträge, Fristen, Skonto, IBAN), Mails nach ihrem Anliegen eingeordnet (Bestellung, Bitte, Reklamation, Kündigung, „schon bezahlt“, neue Bankverbindung) und über der Tabelle Stehendes („Auftrag: A26-028“) übernommen. Anderer Freitext wird **verknüpft und durchsuchbar gemacht**, aber nicht in Datensätze zerlegt. Gescannte PDFs ohne Textebene liest Physarum nicht (kein OCR). Ein optionaler LLM-Baustein ist als Erweiterung vorgesehen.
- Forderungen ohne Rechnung (Miete, Hausgeld, Beiträge) leitet Physarum aus den Zahlungen ab. Was es nicht zahlen sieht, kennt es nicht:
  - Wer noch nie gezahlt hat, schuldet in seinen Augen nichts.
  - Eine Erhöhung, die noch niemand gezahlt hat, bleibt unsichtbar.
  - Bei Jahreszahlern zeigen die Auszüge zu wenige Zahlungen für einen Rhythmus.
  - Bei einer Sammellastschrift zeigt die Bank eine Gutschrift je Lauf; die Einzelposten stehen nur in der pain.008-Datei. Beim Verein, wo die meisten per Lastschrift zahlen, findet Physarum so 4 von 57 offenen Posten, bei der Hausverwaltung 15 von 41.

  Umlagen, Kautionen und Nachzahlungen ohne Rechnung kennt es nicht. Unter fremden Spaltennamen stehen bei der Hausverwaltung in der zweiten Lieferung vier falsche Rückstände. Konten mit fremden Inhabern im selben Ordner (Treuhand, WEG-Konten) trennt Physarum nicht nach Mandant; Umbuchungen zwischen ihnen erkennt es.
- Physarum ist die **operative** Schicht und keine Finanzbuchhaltung. Die Steuerberatung bekommt einen DATEV-Buchungsstapel der Ausgangsrechnungen, die Bücher und die Belege; Aufwandskonten und Voranmeldung bleiben bei ihr.
- Mehrbenutzerbetrieb und Rechte sind nur rudimentär vorhanden (Name im Änderungsprotokoll).
- Heuristiken irren. Deshalb ist alles erklärbar, korrigierbar und umkehrbar, und die Originaldaten bleiben unangetastet.
- Unter neutralen Dateinamen weiß Physarum nicht mehr, dass die Käufer im Shop-Export Kunden sind; sie bleiben eine eigene Liste neben den Kunden aus CRM und Kundenliste, und die Zusammenlegung steht als Hinweis an der Liste.
- Abrechnungen von Zahlungsanbietern (Klarna, PayPal, Stripe) zählen nicht als Zahlungsnachweis für die einzelne Bestellung; nur der Kontoauszug zählt. Bei einem Shop bleiben so Bestellungen offen, die der Anbieter längst ausgezahlt hat.
- Ein Kontoauszug, der nur Zahlungseingänge auf Rechnungen enthält und dessen Verwendungszweck nur die Rechnungsnummer nennt, sieht unter einem neutralen Dateinamen aus wie eine zweite Fassung des Rechnungsbuchs und wird mit ihm zu einer Liste. Echte Auszüge mit Miete, Löhnen und Lastschriften trennt Physarum richtig.
- Rechnungsnummern aus reinen Ziffern sucht Physarum in Verwendungszwecken und Mails ab fünf Stellen, wenn sie lückenlos hochzählen (31001, 31002, …). Vierstellige (1001 …) nicht: Sie sind von Jahreszahlen und Beträgen nicht zu unterscheiden.
- Steht ein Kunde doppelt in der Kartei (zwei Kundennummern, eine mit Skontovereinbarung), gilt die Vereinbarung für den anderen Datensatz erst, wenn der Inhaber die Dublettenfrage beantwortet; bis dahin steht der Abzug als „nicht vereinbart“ da.
- „Geld erhalten – wofür?“ zeigt die Eingänge der letzten zwei Monate; ältere unerklärte Eingänge stehen in der Kontoliste, nicht auf „Heute“.
- Ein Dauerauftrag, der nach einer Preiserhöhung beim alten Betrag bleibt, bezahlt die Rechnung in Physarums Augen nicht: Hakt das Buch sie ab, gilt sie als bezahlt, sonst als offen. Die Differenz je Monat sieht nur, wer die Rechnung öffnet.
- Eine Pause, die nur eine Mengenliste zeigt (eine Schule ohne Essen in den Sommerferien, in einer Liste mit einer Spalte je Einrichtung), meldet Physarum als Vertragsmonat ohne Rechnung.
- Ein vergangener Leistungstag (eine Veranstaltung) gilt nicht als „erledigt“: Fertige, nicht berechnete Veranstaltungen ohne Erledigt-Datum oder -Status meldet Physarum nicht.
- Ein Entwurf ohne Nummer im Rechnungsexport eines anderen Programms zählt als offener Posten, und eine Teilzahlung, die nur das Buch kennt (aufs alte Konto, „teilbezahlt“ mit offenem Rest), zählt als ganz bezahlt.
- Eine Anzahlung ohne eigene Rechnung, die die Schlussrechnung abzieht, verbindet Physarum nicht mit ihr; nach zwei Monaten steht sie nicht mehr unter „Geld erhalten – wofür?“.
- Eigene Mails und solche, die schon beantwortet sind, stehen noch als Anliegen unter den Mails (Physarum liest den Mail-Faden nicht). Mängel, Zahlungszusagen und Ratenbitten ordnet es nicht ein. Eine Kündigung ohne Vertragsnummer gehört zum einen laufenden Vertrag des Kunden; hat er mehrere, bleibt die Mail still.
- Ein Vertrag ohne Ende und ohne Status, dessen letzte zwei Zeiträume fehlen, gilt als beendet; einen Monat lang steht er vorher als vergessener Zeitraum da. Ein Vertrag, für den noch nie eine Rechnung geschrieben wurde, steht nicht unter „nicht berechnet“.
- Zwei Listen, die dieselbe Nummer führen, aber Verschiedenes meinen (Sollmieten und Betriebskostenergebnisse je Mieternummer), werden eine Liste; eine Spalte gleichen Namens mit verschiedener Bedeutung (Vorauszahlung im Monat oder im Jahr) gilt dann aus der neueren Datei.
- Eine Kundendublette mit stark abweichendem Namen („Physiotherapie am Markt GbR“ / „Physio am Markt Brinkmann & Vogel GbR“), die nur das gleiche Konto, die gleiche Adresse und Telefonnummer verraten, fragt Physarum nicht ab. Ähnliche Namen fragt es ab.
- Zahlt ein Kunde eine Rechnung doppelt, steht sie als „zu viel gezahlt“ bei der Rechnung, nicht unter „Geld erhalten – wofür?“.
- Unter neutralen Dateinamen („export (3).csv“) ordnet Physarum die erste Lieferung eines Handwerksbetriebs schlechter (Stundenzettel je Monteur als eigene Listen); mit der zweiten Lieferung stimmt es wieder.

## 8. Was die unabhängigen Reviews verändert haben

### 8.1 Vor dem Bau: drei Konzept-Memos

Drei Reviewer hatten nur die ursprüngliche Idee vor sich und kannten diesen Entwurf nicht: ein ERP-Praktiker mit 20 Jahren Mittelstand, ein Forscher für adaptive Systeme, Process Mining und MDL, und eine Inhaberin einer Kaffeerösterei. Daraus wurde übernommen:

| Einwand / Idee | Quelle | Was daraus wurde |
|---|---|---|
| **„Fester Kern, wachsende Hülle.“** Ein System, das seinen buchhaltungsrelevanten Kern selbst umbaut, ist in Deutschland nicht betreibbar. | Praktiker | Ausgestellte Rechnungen sind festgeschrieben, Korrektur nur per Storno mit Grund. Datensätze mit Verweisen sind nicht löschbar. Gelernte Regeln wirken erst nach Zustimmung („Trampelpfade“). |
| **Salienz beschneiden, nie Semantik**; μ > 1 macht das Netz zum Baum | Forscher | Physarum steuert nur Sichtbarkeit. Der erste Lauf mit μ = 1,6 hat tatsächlich den Belegfluss Rechnung → Auftrag weggeschnitten, deshalb galt danach μ = 0,85 (redundantes, robustes Netz); seit Runde 6 misst Physarum den Fluss direkt, ohne Tero-Löser. Navigation mit Hysterese, nichts springt. |
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
| Online-Shop (Shopify, PayPal, Klarna, Auszahlungen, Erstattungen, B2B-Rechnungen aus lexoffice) | Auszahlungen netto und Sammelzahlungen nach Betrag; die Steuerberatung bekommt nur eigene Rechnungen im DATEV-Stapel, eingelesene als Kopie mit Herkunft; versiegeltes, lückenlos geprüftes Protokoll; die Inhaberin sieht beim ersten Kontakt eine Kette „bis das Geld da ist“ |
| Kfz-Werkstatt (Runde 7): Rechnungsnummern als reine Zahl, bar und Karte bei Abholung, Versicherung zahlt den Rest, Gutschrift und Storno, eigene Rechnungs-PDFs, Fahrzeuge zweier gleichnamiger Kunden, Zahlungsavis. Erster Stand: 183 statt 16 offene Posten, 23 Betrugswarnungen über die eigenen Rechnungen | Nummern, die lückenlos hochzählen, werden auch kurz gefunden; was das Buch als erhalten führt, zählt neben der Bank; eine Überweisung, die das Kennzeichen nennt, findet ihre Rechnung; eine neue Bankverbindung ist nur bei Partnern ein Risiko, an die die Firma zahlt. Jetzt 16 von 16 und 18 von 18 offenen Posten, 8 von 8 überfälligen, 4 von 4 und 3 von 3 fertigen, nicht berechneten Aufträgen; der Rest hängt an einer Dublette, nach der Physarum fragt |

### 8.3 Raptor: erst viel bauen, dann wegnehmen

Nach sechs Runden fragte eine strategische Prüfung, ob das System noch das schlankeste ist, das den Auftrag erfüllt. Befund: Es wuchs nur noch, jede Runde fügte Regeln für die eine geprüfte Firma hinzu, und der Geldkern hing an den Wörtern „bezahlt“ und „fällig“. Seitdem gilt:

- **Der Prüfstand ist die Belohnung.** Zwölf Firmen, die Prüfer gebaut haben, mit ihren Lieferungen und dem, was an jedem Tag wahr ist (`bench/`). Jede läuft zusätzlich unter neutralen Dateinamen und anderen Spaltennamen. Jede Änderung wird daran gemessen.
- **Die Stopp-Regel:** Eine Regel kommt nur hinein, wenn sie auf mindestens zwei Firmen greift und keine schlechter macht Seit Runde 11 gilt das für jede Bedingung auf Zellinhalte, wie auch immer sie heißt (Abschnitt 8.4).
- **Erst löschen.** Weg sind der Abgleich-Ablauf (zwei Wahrheiten für „bezahlt“), die Fragen zum Datenmodell (jetzt umkehrbare Hinweise an der Liste), doppelte Hilfsfunktionen, tote Funktionen und der Tero-Löser.

| Kennzahl (Prüfstand) | vorher | nachher |
|---|---:|---:|
| Geld richtig (offene Posten, alle Firmen) | 0,471 | 0,848 |
| Heute-Aufgaben richtig (überfällig, nicht berechnet, über Budget, Geld ohne Rechnung) | 0,721 | 0,967 |
| gleiche offene Posten unter anderen Datei- und Spaltennamen | 0,48 | 1,0 |
| Listen gleich benannt unter anderen Namen | 0,43 | 0,53 |
| Fragen zum Datenmodell | 9 | 0 |
| Zeilen Code | 18.723 | 18.564 |
| Wort-Regeln / reguläre Ausdrücke | 739 / 162 | 746 / 164 |

Centgenau stimmen jetzt Agentur, Handwerk, Demo, Musikschule und Maler, die drei kleinen auch unter fremden Namen. Beim Shop bleiben 10 bzw. 12 Bestellungen zu viel offen: Sie sind über Klarna oder PayPal bezahlt, deren Abrechnungen Physarum noch nicht als Zahlungsnachweis liest (nur der Kontoauszug zählt), über eine B2B-Rechnung abgerechnet oder nur autorisiert. Nicht erreicht ist das Ziel, die Wort-Regeln zu halbieren. Die Runde hat Wörter durch Struktur ersetzt, wo der Geldkern daran hing. Neue Regeln brauchte es für Erstattungen, Namen und neutrale Dateinamen; die alten Wortlisten der Erkennung stehen noch.

**Runde 7** prüfte das gleichzeitig von zwei Seiten: eine Kfz-Werkstatt, die niemand kannte, und eine Code-Prüfung der Raptor-Runde. Die Werkstatt kam in den Prüfstand, und alle Firmen laufen seitdem auch unter fremden Namen. Erst dort wurden ein Absturz der Haustechnik, Heute mit über 900 Einträgen bei der Agentur und eine vermischte Kontaktliste beim Shop sichtbar. Ersetzt wurde wieder Wort durch Struktur: Rücklastschrift an der Gläubiger-ID, Skonto nach Kondition, Brutto als der größte Betrag, Netto über den Steuersatz, ein Buchdatum, das der Bank folgt, Stammdaten neben Geschäftsvorfällen an Datum und Betrag. Ein Datum, das nie nach dem Start liegt, ist Herkunft und kein Schritt.

| Kennzahl (Prüfstand mit Werkstatt, alle Firmen auch unter fremden Namen) | vorher | nachher |
|---|---:|---:|
| Geld richtig | 0,269 | 0,882 |
| Heute-Aufgaben richtig | 0,614 | 0,934 |
| gleiche offene Posten unter anderen Namen | 0,954 | 1,0 |
| Listen gleich benannt | 0,622 | 0,671 |
| Abstürze | 1 | 0 |
| Zeilen Code | 18.564 | 18.867 |
| Wort-Regeln / reguläre Ausdrücke | 696 / 164 | 708 / 174 |

**Runde 8** prüfte wieder von zwei Seiten. Eine Gebäudereinigung, die niemand kannte (zwei Lieferungen, 40 Fallen), zeigte, wie wenig ein Prüfstand mit einer Firma je Art beweist: Ihr Sparkassen-Export hat vor der Betragsspalte eine „Lastschrift Ursprungsbetrag“, die nur bei Rücklastschriften gefüllt ist, und Physarum nahm die erste Geldspalte – kein Bankeingang schloss eine Rechnung, 29 von 40 offenen Posten waren falsch. Behoben wurde auch hier mit Struktur statt Wörtern: Der Betrag ist die Geldspalte, die jede Zeile füllt. Geld ohne Nummer tilgt die älteste offene Rechnung des Zahlers zuerst, wie § 366 Abs. 2 BGB es vorsieht; den Zahler erkennt Physarum auch an der IBAN seiner Kundenliste. Ein Avis zählt mit der Summe, die auf den Cent passt (auch wenn eine Rechnung einbehalten wird), eine SEPA-Einzugsdatei ist ein Avis, ein nach 140 Zeichen abgeschnittener Sammelzweck bezahlt mit seinem Rest die passende nächste Rechnung. Bestimmt die Objektnummer den Kunden und der Kunde seinen Namen, gehört der Name zum Kunden (dritte Normalform). Der Schlüssel einer Liste ist auch eine Spalte mit Nummern als Werten, nicht nur eine, die „Nr.“ heißt. Lieferanten-PDFs im üblichen Briefbogen werden gelesen, die eigene E-Rechnung ist keine Eingangsrechnung und füllt „Ihre Firma“.

Die Code-Prüfung derselben Runde schaltete jede Regel der Runde 7 einzeln aus und maß den ganzen Prüfstand: 15 von 34 Stellen wirkten nur auf die Werkstatt – die Stopp-Regel war verletzt, weil der Prüfstand nur eine Firma dieser Art hatte. Sie fand zwölf Fehler, sechs davon Rückschritte (die Auftragssumme als Brutto, übliche Skonto-Schreibweisen, Umnummerierung 1001 → 10001, ein Avis mit fremdem Geld), und Regeln ohne jede Wirkung: Der Postleitzahl-Schutz griff nie, nahm aber Rechnungsnummern aus der Suche, die irgendwo als PLZ stehen. Behoben und gestrichen, ohne dass sich eine Kennzahl änderte. Der Prüfstand vergleicht fremde Namen jetzt in jeder Lieferung, nicht nur in der letzten; das deckte eine Abweichung beim Handwerk unter neutralen Dateinamen auf.

Eine Regel ist bewusst wieder herausgekommen: „Die Bank zeigt weniger, als das Buch abhakt“ hätte beim Shop fünf bezahlte Rechnungen teilweise offen gemacht. Der Dauerauftrag, der nach einer Preiserhöhung beim alten Betrag bleibt, ist damit eine Grenze.

| Kennzahl (Prüfstand mit Gebäudereinigung, alle Lieferungen unter fremden Namen) | vorher | nachher |
|---|---:|---:|
| Geld richtig | 0,664 | 0,877 |
| Heute-Aufgaben richtig | 0,632 | 0,859 |
| Gebäudereinigung allein: Geld / Heute | 0,218 / 0,163 | 0,846 / 0,575 |
| gleiche offene Posten unter anderen Namen | 0,989 | 0,989 |
| Listen gleich benannt | 0,694 | 0,707 |
| Abstürze | 0 | 0 |
| Zeilen Code | 18.970 | 19.198 |
| Wort-Regeln / reguläre Ausdrücke | 709 / 174 | 716 / 176 |

Wort-Regeln zählen seit Runde 7 nur echte Wortlisten (vorher auch Konstanten wie `EPS`: 746). Die Runde hat 300 Zeilen gekostet. Wieder gestrichen wurden toter Code, ungenutzte Importe und doppelte Mechanismen.

Ein zweiter Durchgang nahm sich die übrigen Befunde der Gebäudereinigung vor, jeden nur, wenn er die Stopp-Regel besteht. Geld, das einen Auftrag oder ein Angebot nennt („Anzahlung Angebot A-26-019“), zahlt die eine Rechnung, die dieser Fall hat – so, wie die Abläufe „berechnet“ gelernt haben, beim Angebot über den Auftrag, der es angenommen hat –, auch wenn die Rechnung erst Wochen später geschrieben wird. Ein berechneter Auftrag ist keine eigene Forderung mehr; sein Geld gehört der Rechnung. Das greift bei der Gebäudereinigung und bei einer Handwerksfirma des Code-Prüfers, die Anzahlungen auf Aufträge nimmt (16 falsche „überfällig“ fallen weg), und nimmt beim Shop eine falsch offene Bestellung heraus. Eine Bankzeile, die das Hauptbuch schon einer Rechnung gegeben hat, schlägt der Abgleich nicht noch einmal vor. Bisher zählte sie dann zweimal, und das verdeckte drei alte Fehler: Eine Doppelzahlung bezahlte als „Rest einer Sammelzahlung“ eine fremde Rechnung, eine Erstattung nahm das zu viel Gezahlte nicht zurück, und ein Stornobeleg blieb unerkannt, wenn sein Betreff unter fremden Spaltennamen zum Verweis geworden war. Beim Brenner steht so wieder offen, was das Buch „gemahnt“ nennt: Die Zahlung „Re 73/2026“ gehört zur Rechnung 73. Eine neue Bankverbindung im Stammsatz ist nur bei Zahlungsempfängern ein Risiko, nicht beim Kunden, der für die Lastschrift die Bank wechselt; die eigene Lastschriftdatei und das eigene Konto in einem Lieferantenbrief sind kein Betrugsversuch.

| Kennzahl (Prüfstand, zweiter Durchgang der Runde 8) | vorher | nachher |
|---|---:|---:|
| Geld richtig | 0,877 | 0,891 |
| Heute-Aufgaben richtig | 0,859 | 0,868 |
| Gebäudereinigung allein: Geld / Heute | 0,846 / 0,575 | 0,880 / 0,605 |
| gleiche offene Posten unter anderen Namen | 0,989 | 0,989 |
| Zeilen Code | 19.198 | 19.272 |
| Wort-Regeln / reguläre Ausdrücke | 716 / 176 | 724 / 176 |

Vier Befunde blieben nach der Stopp-Regel draußen, weil sie nur bei der Gebäudereinigung vorkommen (siehe Abschnitt 7): eine Kundendublette, die nur das gleiche Konto verrät, die Betrugs-Mail eines Lieferanten, den keine Liste führt, Vertragsmonate ohne Rechnung und die Doppelzahlung als „Geld erhalten“.

**Runde 9** prüfte zum ersten Mal den Alltag selbst. Eine Inhaberin arbeitete zwei Lieferungen lang mit den Daten der Gebäudereinigung (131 Bildschirmfotos). Ihr Urteil: Verstehen stark, Handeln schwach. Der Ordner ließ sich nicht hineinziehen. „+ Rechnung“ am fertigen Auftrag öffnete ein leeres Formular, und die eigene Nummer lief in den Nummernkreis des alten Programms. Betrugsmail und Skonto-Frist von morgen standen eingeklappt. Nach „versendet“ zeigte die Briefseite sofort die 1. Mahnung. Eine Handzahlung und derselbe Betrag im späteren Kontoauszug ergaben „doppelt überwiesen“, und „Rückgängig“ sperrte das Feld gegen die nächste Datei. Die eigene XRechnung galt als verdächtige Eingangsrechnung, und eine gelernte „Formel“ überschrieb einen vereinbarten Termin. Das sind Bedienfehler, keine Erkennungsregeln; sie sind allgemein behoben.

- Heute nennt den Datenstand der Bank.
- Eine Mail über eine neue Bankverbindung setzt die Rechnungen, die sie nennt, oben unter „Vorsicht“, bis jemand nachgefragt hat.
- Ein Brief wartet nach dem Versand seine Frist ab. Wer reklamiert, widerspricht oder „schon bezahlt“ schreibt, wird erst gefragt.
- Eine vorab eingetragene Überweisung bestätigt der spätere Kontoauszug, statt sie doppelt zu zählen.
- „Rückgängig“ gibt das Feld seiner Datei zurück.
- Ein gelernter Datumsabstand füllt nur Lücken.

Aus ihrer Streichliste ist gestrichen, was die Inhaberin nur störte: die wandernde Seitenleiste mit Fluss-Balken, der Organismus im Menü (jetzt „für Neugierige“ bei den Dateien), technische Filter und Lesart-Hinweise auf jeder Liste, die Halbmonats-Kachel und zwei von drei Wegen zu „bezahlt“.

Die zweite Prüfung brachte eine Firma neuer Art: einen Caterer mit Veranstaltungen, Kita-Essen nach Essenszahlen und Rahmenverträgen. Seine Bank kam nur als camt.053, ein XML je Buchungstag. Physarum las das nicht und sagte es auch nicht – ohne Bank mahnte Heute bezahlte Rechnungen über 34.000 € an. Mit dem Leser für das Standardformat stimmen die offenen Posten fast. Dazu kam ein Zählfehler beim eigenen Firmennamen („& Events GmbH“), der alle Eingangsrechnungen verwarf.

Die Lücke, die beide Prüfungen teilen, besteht die Stopp-Regel: Vertragszeiträume ohne Rechnung (Gebäudereinigung OB-107 und OB-132, Caterer MV-06 und das Quartal von RV-02). Physarum liest den Leistungszeitraum der Rechnungen (§ 14 UStG verlangt ihn) und lernt je Vertrag Takt und üblichen Tag. Ein fälliger Zeitraum ohne Rechnung steht unter „nicht berechnet“; rechnet er Lieferscheine ab, stehen diese dort. Damit der Caterer seine Verträge überhaupt findet, verweist eine Spalte „Referenz“ mit Nummern mehrerer Listen je Zeile auf den Datensatz, dessen ganze Nummer sie ist. Beim Brenner zeigt dieselbe Spalte, dass Termine Wartungsverträge betreffen. (Dass dadurch seit Monaten fällige Wartungen auf Heute kamen, stimmte nicht: Runde 10 fand, dass sie dort schon standen – es waren Doppelungen.)

Fünf Befunde des Caterers blieben nach der Stopp-Regel draußen (Abschnitt 7): der Entwurf im fremden Export, die Teilzahlung, die nur das Buch kennt, die Veranstaltung ohne Erledigt-Datum, die Anzahlung, die die Schlussrechnung abzieht, und eigene oder beantwortete Mails. Ein Fehlalarm ist neu und bewusst stehen geblieben: Die Schulferien des Caterers zeigt nur seine Essensliste, also meldet Physarum den August der Schule als Monat ohne Rechnung.

| Kennzahl (Prüfstand mit Caterer, zehn Firmen) | vorher | nachher |
|---|---:|---:|
| Geld richtig | 0,816 | 0,884 |
| Heute-Aufgaben richtig | 0,734 | 0,844 |
| Caterer allein: Geld / Heute | 0,421 / 0,140 | 0,833 / 0,629 |
| Gebäudereinigung allein: Heute | 0,605 | 0,684 |
| gleiche offene Posten unter anderen Namen | 0,963 | 0,990 |
| Listen gleich benannt | 0,702 | 0,707 |
| Abstürze | 0 | 0 |
| Zeilen Code | 19.272 | 19.707 |
| Wort-Regeln / reguläre Ausdrücke | 724 / 176 | 767 / 179 |

Die Runde hat gut 400 Zeilen gekostet, fast alle für Dinge, die eine Inhaberin täglich anfasst (Mahnen, Zahlungen, Warnungen). Die neuen Wort-Regeln sind zum größten Teil Kennzeichen des Bankformats und die Mahnstufen-Wörter des Buchs. Gestrichen wurde, was nur Technik zeigte.

**Runde 10** prüfte wieder von zwei Seiten. Eine Code-Prüfung las die Runde 9 gegen den Strich und belegte 19 Fehler mit Tests, vier davon Rückschritte. Eine von Hand eingetragene Rate „bestätigte“ die ältere, gleich hohe Kontozeile, und die Rechnung blieb offen. Nach der Zahlungserinnerung schlug der nächste Brief die 2. Mahnung vor. Ein berechnetes Fälligkeitsdatum blieb beim alten Rechnungsdatum stehen, und fünfstellige Bestellnummern galten als Verweis auf Kundennummern. Dazu kamen drei weitere Fehler:

- Ein camt-Sammler ohne Einzelbeträge wurde n-fach gebucht.
- Die Mahnsperre aus Kundenmails galt nur für die ersten 50 überfälligen Rechnungen.
- Ein Leistungszeitraum im Jahr 9999 legte Heute lahm.

Alle sind behoben, jeder als Test. Eine Überweisung, die man vorab einträgt, zählt jetzt auch dann einmal, wenn der Auszug sie ohne Nummer zeigt.

Die Prüfung schaltete jede Regel der Runde 9 einzeln aus. Der Abgleich der Vertragszeiträume greift auf zwei Firmen, aber jede braucht einen eigenen Wegbereiter:

- **Caterer:** ganze Nummern einer Referenzspalte als Verweis, Zeitraum-Schreibweisen wie „01.07.–30.09.2026“, Lieferscheine als das, was wartet.
- **Gebäudereinigung:** „01/2026“ in „Unterhaltsreinigung lt. Vertrag 01/2026“ ist ein Teil der Wörter und kein Ding.

Drei davon sind Werteverständnis und Verweissuche, keine Erkennungsregeln im Sinn der Stopp-Regel; sie bleiben. Die Lieferscheine bleiben als Streichkandidat markiert. Der Brenner-Nutzen, den Runde 9 nannte, waren Doppelungen: Seine 42 Wartungsverträge standen zweimal auf Heute, einmal aus der Spalte „Nächste Wartung“ und einmal aus letzter Wartung plus Intervall. Jetzt stehen sie einmal da.

Die zweite Prüfung brachte eine Hausverwaltung: WEG- und Mietverwaltung, 14 Objekte, neun Bankkonten in drei Formaten, 40 Fallen. Für die Verwaltungsfirma selbst trägt Physarum nach vier Korrekturen:

- Eine Umbuchung zwischen zwei Konten des Ordners ist eine Zahlung und keine Rücklastschrift. Vorher standen 37 eigene Vergütungsrechnungen über 12.890 € als „zurückgebucht“ da, mit Erinnern-Knopf.
- Ein Guthaben ist keine Forderung. Vorher entstanden rund 91.000 € Scheinforderungen aus Betriebskostenabrechnungen.
- Die Gegen-IBAN eines Auszugs ist die Spalte mit den meisten verschiedenen Werten, nicht das eigene Konto.
- Eine Rechnung „c/o“ oder „vertreten durch“ geht an die Verwaltung. Vorher verwarf Physarum alle Handwerkerrechnungen.

Was eine Hausverwaltung ausmacht, bildet Physarum nicht ab. Miete, Hausgeld, Umlagen und Kautionen sind Forderungen ohne Rechnung, Monat für Monat aus Vertrag oder Beschluss, und sie machen 90 % des offenen Geldes dieser Firma aus. Ein Prototyp des Prüfers erkennt die Sollliste allein aus den Zahlungen und findet 16 von 26 Rückständen. Er bleibt nach der Stopp-Regel draußen, bis eine zweite Firma Forderungen ohne Rechnung kennt, etwa ein Verein, eine Kita oder ein privater Vermieter. Ebenso draußen bleiben der Vertrag, für den nie eine Rechnung geschrieben wurde, und der eigene Lastschriftlauf als Nicht-Frage. Die Hausverwaltung ist die elfte Firma des Prüfstands. Ihr „Geld richtig“ ist strukturell gedeckelt, und genau das soll der Prüfstand zeigen.

Neben den Prüfungen kamen dazu: Kündigungen ohne Vertragsnummer (Gebäudereinigung und Caterer), die Kontoliste mit Verwendungszweck und richtigem Stand, die Suche nach Beträgen, die Kundenliste mit „Offen“, das Einlesen in Alltagssprache und die Spaltenköpfe des Sparkassen-Exports.

| Kennzahl (Prüfstand) | vorher | nachher |
|---|---:|---:|
| zehn Firmen der Runde 9: Geld / Heute | 0,884 / 0,844 | 0,884 / 0,852 |
| mit Hausverwaltung, elf Firmen: Geld richtig | 0,372 | 0,499 |
| mit Hausverwaltung, elf Firmen: Heute-Aufgaben richtig | 0,450 | 0,573 |
| Hausverwaltung, Lieferung 1: offene Posten zu viel / überfällig zu viel | 129 / 37 | 57 / 0 |
| Hausverwaltung, Lieferung 1: Einträge auf Heute | 221 | 108 |
| Brenner: Einträge auf Heute | 280 | 238 |
| gleiche offene Posten unter anderen Namen | 0,961 | 0,991 |
| Listen gleich benannt | 0,696 | 0,698 |
| Abstürze | 0 | 0 |
| Zeilen Code | 19.707 | 20.036 |
| Wort-Regeln / reguläre Ausdrücke | 767 / 179 | 783 / 183 |

„Vorher“ bei elf Firmen ist der Stand der Runde 9 mit der neuen Firma. Heute steigt bei den zehn Firmen, weil eine Bareinzahlung auch dann eigenes Geld ist, wenn das Wort nur im Buchungstext steht (Caterer). Die Runde hat gut 300 Zeilen gekostet, zur Hälfte für die Fehler, die die Prüfung fand. Gestrichen wurden der Leser einer „bezahlt“-Markierung, die sich nicht mehr setzen ließ, die zweite Reklamationsprüfung über Dokumente (die Mails tun das schon) und die zweite Rechnung der Wartefrist nach einem Brief.

**Runde 11** brachte den zweiten Zeugen für die größte Lücke und eine strategische Prüfung.

Ein Sportverein, den niemand kannte, hat 562 Mitglieder in fünf Abteilungen. Sie zahlen per Lastschrift, Überweisung oder bar, und zum 1. Juli steigen die Beiträge. Im Jahr entstehen rund 1.800 Forderungen, nur 33 davon sind Rechnungen. Wie bei der Hausverwaltung sah Physarum fast nichts davon. Aus der Prüfung kamen ein Leser für MT940-Kontoauszüge (Standardformat, wie camt) und vier Fehlerbehebungen:

- Der Zahlername kam aus einer Spalte, die auf jeder Zeile gleich ist.
- Ein Zahlungsschritt unter anderem Namen wurde nicht erkannt.
- Ein Geburtsdatum galt als Beginn eines Ablaufs („576 Mitglieder seit März 1938“).
- Die Kachel „Offene Posten“ rechnet jetzt über alle Forderungslisten.

Die strategische Prüfung fragte, ob Physarum noch auf Kurs ist. Ihr Urteil: teilweise. „Alles reinkippen“ und „baut sich selbst“ gelingen für Firmen, die Rechnungen schreiben. Gewachsen ist aber vor allem der Code – seit Runde 7 rund 1.500 Zeilen und 90 Wort-Regeln –, nicht der Organismus:

- Von 19 einzeln ausgeschalteten Mechanismen wirken 9 nur auf die Firma, für die sie gebaut wurden, 2 auf keine.
- Der Prüfstand misst nur, ob offene Posten verstanden werden. Von Heute bewertet er gut ein Viertel, das Handeln gar nicht.
- Das Flussnetz, das dem System den Namen gibt, ändert keine einzige Zelle.
- Die Stopp-Regel hatte ein Schlupfloch: Was „Fehler“, „Leser“ oder „Wegbereiter“ hieß, kam mit einer Firma herein.

Daraus folgt dreierlei.

- **Forderungen ohne Rechnung** entstehen jetzt aus dem Zahlungsbild (`physarum/claims.py`). Eine Liste, deren Mitglieder einen ihrer Beträge immer wieder zahlen, ist eine Liste von Sollstellungen. Das Mitglied erkennt Physarum an seiner Nummer im Zweck, an seiner IBAN oder an seinem Namen. Den Rhythmus sagen die Abstände der Zahlungen: monatlich, vierteljährlich, halb- oder ganzjährlich. Geschuldet ist ab dem ersten gezahlten Zeitraum, solange die Auszüge reichen und das Mitglied nicht gegangen ist. Das Geld tilgt den genannten Zeitraum, sonst den ältesten (§ 366 BGB). Wechseln viele im selben Monat auf den Betrag der Liste, ist das eine Erhöhung: Ab dann gilt der neue Betrag, davor der alte. Wer danach noch den alten zahlt, schuldet die Differenz, aber nur, wenn die anderen vor der Erhöhung genau diesen Betrag zahlten. Nichts wird gefordert, wo keine Zahlung den Beginn belegt. Der Prototyp stammt vom Prüfer. Verallgemeinert auf Rhythmus und Erhöhung greift er bei beiden Firmen und verändert keine andere.
- **Der Prüfstand misst mehr:** „Geld richtig“ auch je Firma, damit eine Firma mit vielen Forderungen nicht allein entscheidet, und „Geld erklärt“ (Abschnitt 3).
- **Die Stopp-Regel gilt ohne Etikett**, mit Streichpflicht (Abschnitt 8.4). „Länger als üblich“ meldet nur noch, was auf einer Norm aus mindestens 20 Fällen beruht; beim Brenner standen 28 Aufträge an einer Norm aus 8.

| Kennzahl (Prüfstand, zwölf Firmen) | vorher | nachher |
|---|---:|---:|
| Geld richtig | 0,419 | 0,546 |
| Geld richtig je Firma (Mittel) | 0,761 | 0,780 |
| Geld erklärt (je Firma, neu) | – | 0,344 |
| Heute-Aufgaben richtig | 0,441 | 0,482 |
| zehn Firmen ohne Sollstellungen: Geld / Heute | 0,884 / 0,852 | 0,884 / 0,852 |
| Hausverwaltung, Lieferung 1: offene Posten richtig / zu viel / fehlend | 6 / 57 / 35 | 15 / 16 / 26 |
| Hausverwaltung, Lieferung 2: offene Posten richtig / zu viel / fehlend | 2 / 61 / 29 | 10 / 19 / 21 |
| Verein, Lieferung 1: offene Posten richtig / zu viel / fehlend | 3 / 1 / 54 | 4 / 1 / 53 |
| Brenner: Einträge auf Heute | 238 | 210 |
| gleiche offene Posten unter anderen Namen | 0,986 | 0,980 |
| Listen gleich benannt | 0,693 | 0,693 |
| Abstürze | 0 | 0 |
| Zeilen Code | 20.157 | 20.566 |
| Wort-Regeln / reguläre Ausdrücke | 786 / 190 | 800 / 195 |

„Vorher“ ist der Stand nach dem ersten Teil der Runde: der Verein im Prüfstand, MT940 und die Fehler aus seiner Prüfung, die die elf bisherigen Firmen in jeder Zelle gleich ließen. Unter anderen Namen sinkt der Wert, weil die Hausverwaltung unter fremden Spaltennamen in der zweiten Lieferung vier falsche Rückstände zeigt. Die Runde hat gut 500 Zeilen gekostet, 400 davon für die Sollstellungen.

Der Verein bleibt fast blind. Die meisten Mitglieder zahlen per Lastschrift, und deren Einzelposten stehen nur in der pain.008-Datei des Laufs. Physarum liest sie als Avis für Rechnungen, nicht als Zahlung eines Mitglieds. Das ist der nächste Schritt. Ebenfalls offen: „Geld als Futter“, also das Geld selbst als Nahrung – eine Grammatik, die jede Kontozeile durch einen Vorgang erklärt, und Heute als der Rest, den sie nicht erklärt. Sie wäre das, was das Flussnetz versprach, ist aber ein Umbau für eine eigene Runde.

### 8.4 Regeln auf Bewährung

Seit Runde 11 schaltet jede Runde die Regeln der letzten zwei Runden einzeln aus und misst den ganzen Prüfstand. Wirkt eine nur bei einer Firma, steht sie hier. Findet sich binnen zwei Runden kein zweiter Zeuge, wird sie gestrichen, und ihr Fall wird eine Grenze in Abschnitt 7. Den ersten Lauf machte der strategische Prüfer der Runde 11, über 19 Mechanismen aus allen Runden:

| Regel | wirkt bei | seit Runde | Frist bis Runde |
|---|---|---:|---:|
| Budget überschritten (`_budget_work`) | Agentur | 3 | 13 |
| Die PDF-Rechnung, die der Kunde bekam, sagt den Betrag, wenn das Buch etwas anderes sagt (`_documents`) | Handwerk | 4 | 13 |
| Zwei Rechnungen, die das Buch kurz nacheinander als bezahlt führt, teilen sich eine Überweisung (`_listed_together`) | Handwerk | 4 | 13 |
| Die Spalte „erhalten“ des Buchs zählt neben der Bank (`_received_attr`) | Werkstatt | 7 | 13 |
| An der Kasse bezahlt und Tage später noch einmal überwiesen: zweimal bezahlt | Shop | 8 | 13 |
| Ein abgeschnittener Sammelzweck bezahlt mit seinem Rest die nächste offene Rechnung (`_cut_off`) | Gebäudereinigung | 8 | 13 |
| Eine Anzahlung auf Auftrag oder Angebot zahlt dessen Rechnung | Gebäudereinigung | 8 | 13 |
| Die Umbuchung zwischen zwei Konten des Ordners ist eine Zahlung (`_transfer_twins`) | Hausverwaltung | 10 | 13 |
| „RE-… bis RE-…“ im Zweck zahlt die Rechnungen dazwischen (`_number_range`) | Hausverwaltung | 10 | 13 |

Ohne Wirkung im Prüfstand, nur durch einen Test belegt, sind der Sicherheitseinbehalt einer Schlussrechnung (`_retained`) und die eigene Kundennummer neben der Rechnungsnummer (ein Fehlerfall der Runde 8). Für beide gilt dieselbe Frist.

Vier weitere wirken nur auf Heute-Einträge, die der Prüfstand nicht bewertet: Mails, fällige Termine, Hinweise und „länger als üblich“. Über sie kann er erst urteilen, wenn er Heute ganz bewertet.
