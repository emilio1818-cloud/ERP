from datetime import date, timedelta
from pathlib import Path

TODAY = date.today()  # the scenarios move with the day the tests run


def de(d: date) -> str:
    return d.strftime("%d.%m.%Y")


def eur(x: float) -> str:
    return f"{x:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def write(folder: Path, files: dict):
    folder.mkdir(parents=True, exist_ok=True)
    for old in folder.iterdir():
        if old.is_file():
            old.unlink()
    for n, rows in files.items():
        (folder / n).write_text("\n".join(rows) + "\n", encoding="utf-8")


def eml(frm: str, to: str, subject: str, when, body: str) -> bytes:
    from email.message import EmailMessage
    from email.utils import format_datetime
    from datetime import datetime
    m = EmailMessage()
    m["From"], m["To"], m["Subject"] = frm, to, subject
    m["Date"] = format_datetime(datetime(when.year, when.month, when.day, 10, 15))
    m["Message-ID"] = f"<{abs(hash((frm, subject, str(when))))}@example.de>"
    m.set_content(body)
    return bytes(m)


def write_files(folder: Path, files: dict):
    """files: name -> list of lines (text) or bytes."""
    folder.mkdir(parents=True, exist_ok=True)
    import shutil
    for old in folder.iterdir():
        if old.is_file():
            old.unlink()
        else:
            shutil.rmtree(old)
    for n, rows in files.items():
        p = folder / n
        p.parent.mkdir(parents=True, exist_ok=True)
        if isinstance(rows, bytes):
            p.write_bytes(rows)
        else:
            p.write_text("\n".join(rows) + "\n", encoding="utf-8")
