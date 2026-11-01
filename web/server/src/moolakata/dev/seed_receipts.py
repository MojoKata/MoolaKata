"""Dev mode's receipts (requirements S17.7): a few drawn here, so the screen, the inbox and
reading them have something to show. One is attached to its card transaction, one waits in
the inbox, and one is a PDF invoice."""

import io
from decimal import Decimal

from PIL import Image, ImageDraw, ImageFont
from sqlalchemy import select

from ..receipts import prepared, record
from ..store.entities.accounts import Account, Transaction
from ..store.entities.receipts import ReceiptLink


def _font(size: int):
    try:
        return ImageFont.load_default(size=size)
    except TypeError:  # an older Pillow without sizes
        return ImageFont.load_default()


def draw(lines: list[str], width: int = 420, line: int = 30) -> Image.Image:
    """A till receipt: dark text on white, one line of text per row."""
    img = Image.new("RGB", (width, 40 + line * len(lines)), "white")
    pen = ImageDraw.Draw(img)
    font = _font(20)
    for i, text in enumerate(lines):
        pen.text((24, 20 + i * line), text, fill=(20, 20, 20), font=font)
    return img


def _bytes(img: Image.Image, fmt: str) -> bytes:
    out = io.BytesIO()
    img.save(out, fmt, **({"quality": 90} if fmt == "JPEG" else {}))
    return out.getvalue()


def store(s, server, owner_id: str, name: str, data: bytes):
    """A receipt as an upload keeps it: prepared, then recorded in the seed's transaction."""
    with prepared(server, owner_id, name, data) as ready:
        return record(s, server, owner_id, ready)


def seed_receipts(server, s, people: dict) -> None:
    alice = people["alice"]
    card = s.scalars(select(Account).where(Account.name == "Travel Visa")).one()
    shop = s.scalars(
        select(Transaction)
        .where(Transaction.accountId == card.id, Transaction.payee == "Kroger")
        .order_by(Transaction.date.desc())
    ).first()
    amount = -shop.amount if shop else Decimal("62.40")
    grocery = (amount * Decimal("0.6")).quantize(Decimal("0.01"))
    when = shop.date if shop else None
    kroger = draw(
        [
            "KROGER #0421",
            "1200 MAIN ST",
            f"{when:%m/%d/%Y}  14:32" if when else "10/01/2026  14:32",
            "",
            "GROCERY            " + f"{grocery:.2f}",
            "PRODUCE            " + f"{amount - grocery:.2f}",
            "SUBTOTAL           " + f"{amount:.2f}",
            "TAX                0.00",
            "TOTAL              " + f"{amount:.2f}",
            "VISA ****1123",
        ]
    )
    r = store(s, server, alice.id, "IMG_2291.png", _bytes(kroger, "PNG")).receipt
    if shop is not None:
        r.date, r.amount, r.payee = shop.date, amount, "Kroger"
        s.add(
            ReceiptLink(
                receiptId=r.id,
                kind="transaction",
                itemId=shop.id,
                createdAt=r.createdAt,
                linkedById=alice.id,
            )
        )
    coffee = draw(
        ["BLUE BOTTLE COFFEE", "OCT 9, 2026", "", "LATTE              5.75", "TOTAL         $5.75"]
    )
    store(s, server, alice.id, "IMG_2310.jpg", _bytes(coffee, "JPEG"))
    invoice = draw(
        [
            "INVOICE 2026-117",
            "City Power & Water",
            "Service: Sep 1 - Sep 30, 2026",
            "",
            "Electricity        112.40",
            "Water               41.18",
            "AMOUNT DUE         153.58",
        ],
        width=620,
    )
    store(s, server, alice.id, "city-power-sept.pdf", _bytes(invoice, "PDF"))
    s.flush()
    read_now(s, server)


def read_now(s, server) -> None:
    """Read the seed's receipts before the server starts, here rather than in the worker, so
    every dev server (and the generated mockup) begins from the same readings."""
    from ..receipts import ocr, reading, whole
    from ..store.entities.receipts import Receipt

    for r in s.scalars(select(Receipt).where(Receipt.readStatus == "waiting")):
        try:
            got = ocr.read(whole(server, r), r.mediaType)
        except ocr.ReadError as e:
            r.readStatus, r.readError = "failed", str(e)
            continue
        reading.save_reading(s, r, got.lines, got.method, got.engine)
