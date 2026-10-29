"""The same data under other names, as other firms' files call things: S1 neutral file names, S2 other
column headings, S3 both. A product that understands structure gives the same answers for all of them."""
from __future__ import annotations

import io
from pathlib import PurePosixPath

import openpyxl

# headings an office might use instead of the usual ones
HEADINGS = {
    "Rechnungsnr": "Beleg", "Rechnungsnr.": "Beleg", "Rechnungsnummer": "Beleg-Nr", "Re.-Nr.": "Beleg", "Re-Nr": "Beleg",
    "Belegnummer": "Beleg", "Rechnungsdatum": "Belegdatum", "Re-Datum": "Belegdatum", "Re.-Datum": "Belegdatum",
    "Datum": "Belegdatum", "Fällig am": "Zahlbar bis", "fällig am": "Zahlbar bis", "Fälligkeit": "Zahlbar bis",
    "Bezahlt am": "Ausgeglichen am", "bezahlt am": "Ausgeglichen am", "Zahlungseingang": "Ausgeglichen am",
    "Kunde": "Empfänger", "Kd-Nr": "Kundennr", "Kd-Nr.": "Kundennr", "Kd.-Nr.": "Kundennr", "Kundennummer": "Kundennr",
    "Status": "Stand", "Auftrag": "Vorgang", "Auftr.-Nr.": "Vorgang", "Auftragsnr": "Vorgang", "Einzelpreis": "EP",
    "Gesamt": "GP", "Bestand": "Ist", "Mindestbestand": "Soll", "Liefertermin": "Wunschtermin",
    "Geliefert am": "Ausgeliefert am", "fertig am": "abgeschlossen am", "Netto": "Nettobetrag", "Brutto": "Bruttobetrag",
    "Betreff": "Leistung", "Firma": "Kundenname", "Ansprechpartner": "z. Hd.",
}


def neutral_names(files: list[tuple[str, bytes]]) -> list[tuple[str, bytes]]:
    """S1: what comes out of a download folder – "export (3).csv" – keeping the folders."""
    out = []
    for i, (name, data) in enumerate(files, start=1):
        p = PurePosixPath(name)
        if p.suffix.lower() in (".eml", ".msg"):
            out.append((name, data))  # a mail's name carries nothing
            continue
        new = f"export ({i}){p.suffix}"
        out.append((str(p.with_name(new)) if str(p.parent) != "." else new, data))
    return out


def other_headings(files: list[tuple[str, bytes]]) -> list[tuple[str, bytes]]:
    """S2: the first line that looks like a heading gets the other words; xlsx sheets the same in their top rows."""
    out = []
    for name, data in files:
        suf = PurePosixPath(name).suffix.lower()
        try:
            if suf == ".csv":
                data = _csv(data)
            elif suf == ".xlsx":
                data = _xlsx(data)
        except Exception:  # noqa: BLE001 - a file the variant cannot rewrite stays as it is
            pass
        out.append((name, data))
    return out


def _csv(data: bytes) -> bytes:
    for enc in ("utf-8-sig", "cp1252"):
        try:
            text = data.decode(enc)
            break
        except UnicodeDecodeError:
            continue
    lines = text.split("\n")
    for i, line in enumerate(lines[:30]):
        sep = ";" if line.count(";") >= line.count(",") else ","
        cells = line.rstrip("\r").split(sep)
        if sum(1 for c in cells if c.strip().strip('"') in HEADINGS) >= 2:
            new = [HEADINGS.get(c.strip().strip('"'), c.strip().strip('"')) for c in cells]
            quoted = [f'"{n}"' if c.strip().startswith('"') else n for c, n in zip(cells, new)]
            lines[i] = sep.join(quoted) + ("\r" if line.endswith("\r") else "")
            break
    out = "\n".join(lines)
    return out.encode("utf-8-sig" if enc == "utf-8-sig" and data.startswith(b"\xef\xbb\xbf") else
                      "utf-8" if enc == "utf-8-sig" else enc)


def _xlsx(data: bytes) -> bytes:
    wb = openpyxl.load_workbook(io.BytesIO(data), data_only=True)  # the values Physarum reads, not formulas without them
    for ws in wb.worksheets:
        for row in ws.iter_rows(min_row=1, max_row=8):
            for c in row:
                if isinstance(c.value, str) and c.value.strip() in HEADINGS:
                    c.value = HEADINGS[c.value.strip()]
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def apply(variant: str, files: list[tuple[str, bytes]]) -> list[tuple[str, bytes]]:
    if variant in ("S2", "S3"):
        files = other_headings(files)
    if variant in ("S1", "S3"):
        files = neutral_names(files)
    return files
