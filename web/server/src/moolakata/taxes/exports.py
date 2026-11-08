"""The tax exports (requirements S8.2): Form 8949 as CSV, TXF for tax software, and a PDF
summary for a preparer. Each says what it covers and what it doesn't."""

import csv
import datetime as dt
import io
from decimal import Decimal

from .. import money
from ..money import grouped
from .panels import Row, ScheduleD

COVERS = (
    "Every sale and closed option in the tax book's taxable accounts and each physical asset "
    "sold, with wash sales found across the filers' accounts and a spouse's. Not covered: "
    "anything in accounts left out of the book. The TXF file has no field for a digital "
    "asset's box (G to L) or for the C and L codes, so it leaves those rows out: enter them "
    "from the CSV."
)
# TXF's codes for Form 8949, by box (format V042).
TXF_CODE = {"A": 321, "B": 711, "C": 712, "D": 323, "E": 713, "F": 714}


def _money(d: Decimal | None) -> str:
    return money.money_str(d) or ""


FEES = {
    "sale": "Bitcoin network fees are sales of their sats, the common reading (S8.19).",
    "not-taxed": "Bitcoin network fees on transfers between the owner's own accounts are not "
    "taxed, as the book's settings choose (S8.19).",
}


def covers(bitcoin_fees: str = "sale") -> str:
    return f"{COVERS} {FEES.get(bitcoin_fees, FEES['sale'])}"


def csv_8949(rows: list[Row], year: int, bitcoin_fees: str = "sale") -> str:
    out = io.StringIO()
    w = csv.writer(out)
    w.writerow([f"# Form 8949 for {year}, from MoolaKata. {covers(bitcoin_fees)}"])
    w.writerow(
        [
            "Box",
            "Term",
            "Description",
            "Date acquired",
            "Date sold",
            "Proceeds",
            "Cost basis",
            "Adjustment code",
            "Adjustment",
            "Gain or loss",
            "Account",
        ]
    )
    for r in sorted(rows, key=lambda r: (r.box, r.sold)):
        w.writerow(
            [
                r.box,
                "long" if r.longTerm else "short",
                r.description,
                # Blank when sold without a lot to match: no day to write (CR3-415).
                r.acquired.isoformat() if r.acquired else "" if r.lotMissing else "VARIOUS",
                r.sold.isoformat(),
                _money(r.proceeds),
                _money(r.basis),
                r.code,
                _money(r.adjustment) if r.adjustment else "",
                _money(r.gain),
                r.account,
            ]
        )
    return out.getvalue()


def _txf_date(d: dt.date | None) -> str:
    return d.strftime("%m/%d/%Y") if d else "VARIOUS"


def in_txf(r: Row) -> bool:
    """TXF (V042) carries boxes A to F and the wash-sale adjustment, nothing else, and only a
    row with its day bought and its basis: TXF has no way to say one is missing, and a basis
    written as 0 would tax the whole proceeds (CR3-415, CR3-416)."""
    return r.box in TXF_CODE and r.code in ("", "W") and not r.lotMissing and r.basis is not None


def txf_left_out(rows: list[Row]) -> dict[str, int]:
    """The rows TXF can't carry, counted by why (S8.2): a digital asset's box (G to L), a
    collectable's code C, a personal-use loss's code L, a sale without a lot to match (no day
    bought to write), a sale without its basis."""
    out = {"digital": 0, "collectable": 0, "personalUse": 0, "noLot": 0, "noBasis": 0}
    for r in rows:
        if in_txf(r):
            continue
        if r.lotMissing:
            out["noLot"] += 1
        elif r.box not in TXF_CODE:
            out["digital"] += 1
        elif r.code == "C":
            out["collectable"] += 1
        elif r.code == "L":
            out["personalUse"] += 1
        else:
            out["noBasis"] += 1
    return out


def txf(rows: list[Row], today: dt.date) -> str:
    lines = ["V042", "AMoolaKata", f"D{today:%m/%d/%Y}", "^"]
    for r in sorted((r for r in rows if in_txf(r)), key=lambda r: (r.box, r.sold)):
        lines += [
            "TD",
            f"N{TXF_CODE[r.box]}",
            "C1",
            "L1",
            f"P{r.description}",
            f"D{_txf_date(r.acquired)}",
            f"D{_txf_date(r.sold)}",
            f"${_money(r.basis)}",
            f"${_money(r.proceeds)}",
        ]
        if r.code == "W" and r.adjustment:
            lines.append(f"${_money(r.adjustment)}")
        lines.append("^")
    return "\r\n".join(lines) + "\r\n"


# ---------- a small PDF writer: text in Helvetica, pages as needed ----------


def _escape(text: str) -> bytes:
    raw = text.encode("cp1252", errors="replace")
    return raw.replace(b"\\", b"\\\\").replace(b"(", b"\\(").replace(b")", b"\\)")


def pdf(title: str, sections: list[tuple[str, list[str]]]) -> bytes:
    """A plain PDF: a title, then each section's heading and lines, on US Letter pages."""
    width, height, margin, leading = 612, 792, 54, 13
    pages: list[list[tuple[str, float, float, bytes]]] = [[]]
    y = height - margin

    def put(font: str, size: float, text: str) -> None:
        nonlocal y
        if y < margin:
            pages.append([])
            y = height - margin
        pages[-1].append((font, size, y, _escape(text)))
        y -= leading if size <= 10 else leading + 6

    put("F2", 16, title)
    for heading, lines in sections:
        y -= 6
        put("F2", 12, heading)
        for line in lines:
            # Long lines wrap at about 100 characters.
            while len(line) > 100:
                cut = line.rfind(" ", 0, 100)
                cut = cut if cut > 40 else 100
                put("F1", 9.5, line[:cut])
                line = "    " + line[cut:].lstrip()
            put("F1", 9.5, line)
    objects: list[bytes] = []

    def add(body: bytes) -> int:
        objects.append(body)
        return len(objects)

    catalog = add(b"")
    tree = add(b"")
    regular = add(
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding >>"
    )
    bold = add(
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica-Bold /Encoding /WinAnsiEncoding >>"
    )
    kids = []
    for i, page in enumerate(pages):
        ops = []
        for font, size, at, text in page:
            ops.append(
                b"BT /%s %.1f Tf %d %.1f Td (%s) Tj ET" % (font.encode(), size, margin, at, text)
            )
        ops.append(b"BT /F1 8 Tf %d 30 Td (Page %d of %d) Tj ET" % (margin, i + 1, len(pages)))
        stream = b"\n".join(ops)
        content = add(b"<< /Length %d >>\nstream\n%s\nendstream" % (len(stream), stream))
        kids.append(
            add(
                b"<< /Type /Page /Parent %d 0 R /MediaBox [0 0 %d %d] /Contents %d 0 R "
                b"/Resources << /Font << /F1 %d 0 R /F2 %d 0 R >> >> >>"
                % (tree, width, height, content, regular, bold)
            )
        )
    objects[catalog - 1] = b"<< /Type /Catalog /Pages %d 0 R >>" % tree
    objects[tree - 1] = b"<< /Type /Pages /Kids [%s] /Count %d >>" % (
        b" ".join(b"%d 0 R" % k for k in kids),
        len(kids),
    )
    out = io.BytesIO()
    out.write(b"%PDF-1.4\n")
    offsets = []
    for n, body in enumerate(objects, 1):
        offsets.append(out.tell())
        out.write(b"%d 0 obj\n%s\nendobj\n" % (n, body))
    xref = out.tell()
    out.write(b"xref\n0 %d\n0000000000 65535 f \n" % (len(objects) + 1))
    for off in offsets:
        out.write(b"%010d 00000 n \n" % off)
    out.write(
        b"trailer\n<< /Size %d /Root %d 0 R >>\nstartxref\n%d\n%%%%EOF\n"
        % (len(objects) + 1, catalog, xref)
    )
    return out.getvalue()


def schedule_d_lines(d: ScheduleD) -> list[str]:
    out = []
    for box, (proceeds, basis, adj, gain) in d.byBox.items():
        out.append(
            f"Box {box}: proceeds {grouped(proceeds)}, basis {grouped(basis)}, "
            f"adjustments {grouped(adj)}, gain or loss {grouped(gain)}"
        )
    out.append(f"Short term: {grouped(d.shortTerm)}. Long term: {grouped(d.longTerm)}.")
    if d.collectables:
        out.append(f"Of the long term, collectables (28% rate): {grouped(d.collectables)}.")
    if d.carryoverShort or d.carryoverLong:
        out.append(
            f"Capital-loss carryover from last year: short {grouped(d.carryoverShort)}, "
            f"long {grouped(d.carryoverLong)}."
        )
    return out
