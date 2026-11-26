"""Reading a receipt (requirements S9.8.2): what runs in the worker process.

1. A PDF is read page by page: a page with a text layer (at least 20 characters) with
   pypdfium2, no OCR; any other page by OCR. A receipt's total read from a text layer is
   checked against the OCR of its page.
2. Images and scanned pages are prepared: Pillow applies the EXIF orientation, reads HEIC,
   turns them grey and scales the long side to 2,000 pixels; pypdfium2 renders at most 3
   scanned pages at 300 DPI.
3. RapidOCR on ONNX Runtime (CPU, 2 threads) runs the PP-OCR models: text detection,
   orientation, recognition. The models are the ones in the pinned rapidocr wheel, loaded by
   their paths and checked against their SHA-256 first, so nothing is ever downloaded.
4. Lines are put in reading order from their boxes, and the field parser takes over.
"""

import hashlib
import io
from dataclasses import dataclass
from pathlib import Path

TEXT_LAYER_CHARS = 20
MAX_PAGES = 3  # a receipt's
STATEMENT_PAGES = 30  # a scanned statement's, each page read in turn within its time limit
LONG_SIDE = 2000
DPI = 300
# Pixels an image may have, or a PDF page be drawn at, before it is refused or drawn smaller
# (S9.8.4.3).
MAX_PIXELS = 40_000_000
THREADS = 2

MODELS = {
    "det": (
        "PP-OCRv6_det_small.onnx",
        "090f04abcd9d9a7498bc4ebf677e4cb9bdce1fe4197ddb7e529f1ef44e1ff94f",
    ),
    "cls": (
        "ch_ppocr_mobile_v2.0_cls_mobile.onnx",
        "e47acedf663230f8863ff1ab0e64dd2d82b838fceb5957146dab185a89d6215c",
    ),
    "rec": (
        "PP-OCRv6_rec_small.onnx",
        "6f327246b50388f3c176ae304bd95767ea6dc0c9ae92153ef8cbe210b3c14884",
    ),
}


class ReadError(Exception):
    """A receipt that couldn't be read, with the reason a person is shown."""


@dataclass
class Read:
    lines: list[str]
    method: str  # "text", "ocr", or "both" for a PDF with pages of each
    engine: str
    # The total against the scan of its page (S9.8.2.1.1): {"text", "scan", "agrees"}
    check: dict | None = None


def models_dir() -> Path:
    import rapidocr

    return Path(rapidocr.__file__).parent / "models"


def check_models() -> dict[str, Path]:
    out = {}
    folder = models_dir()
    for key, (name, digest) in MODELS.items():
        path = folder / name
        if not path.exists():
            raise ReadError(f"the OCR model {name} is missing")
        if hashlib.sha256(path.read_bytes()).hexdigest() != digest:
            raise ReadError(f"the OCR model {name} is not the one MoolaKata was built with")
        out[key] = path
    return out


_engine = None


def engine():
    global _engine
    if _engine is None:
        import onnxruntime
        from rapidocr import RapidOCR

        # ONNX Runtime ships a telemetry client that would upload to Microsoft (its 1DS
        # collector). Nothing leaves the server but the calls of R3.1, so it is switched off
        # before the first session is made, whatever the wheel's default.
        onnxruntime.disable_telemetry_events()
        paths = check_models()
        _engine = RapidOCR(
            params={
                "Global.log_level": "error",
                "Det.model_path": str(paths["det"]),
                "Cls.model_path": str(paths["cls"]),
                "Rec.model_path": str(paths["rec"]),
                "EngineConfig.onnxruntime.intra_op_num_threads": THREADS,
                "EngineConfig.onnxruntime.inter_op_num_threads": 1,
            }
        )
    return _engine


def engine_name() -> str:
    from importlib.metadata import version

    return f"rapidocr {version('rapidocr')}, onnxruntime {version('onnxruntime')}, PP-OCRv6 small"


def _prepare(img):
    from PIL import Image, ImageOps

    img = ImageOps.exif_transpose(img).convert("L")
    w, h = img.size
    scale = LONG_SIDE / max(w, h)
    if scale < 1:
        img = img.resize((round(w * scale), round(h * scale)), Image.Resampling.LANCZOS)
    return img


def in_order(boxes, texts) -> list[str]:
    """Words into lines: boxes whose vertical middles are close make one line, read left to
    right; lines top to bottom."""
    items = []
    for box, text in zip(boxes, texts, strict=False):
        ys = [p[1] for p in box]
        xs = [p[0] for p in box]
        items.append((sum(ys) / len(ys), max(ys) - min(ys), min(xs), text))
    items.sort(key=lambda x: x[0])
    lines: list[list] = []
    for mid, height, x, text in items:
        if lines and abs(mid - lines[-1][0]) <= max(height, lines[-1][1]) * 0.5:
            line = lines[-1]
            line[2].append((x, text))
        else:
            lines.append([mid, height, [(x, text)]])
    return [" ".join(t for _, t in sorted(words)) for _, _, words in lines]


def _ocr(images) -> list[str]:
    import numpy as np

    out: list[str] = []
    for img in images:
        result = engine()(np.array(_prepare(img).convert("RGB")))
        if result.boxes is None or result.txts is None:
            continue
        out += in_order(result.boxes, result.txts)
    return out


def text_layer(data: bytes) -> list[str] | None:
    """A PDF's text layer as lines, or None when it has none worth reading: what a statement
    kept without reading is named by (S1.3.3.6), with no OCR."""
    import pypdfium2 as pdfium

    try:
        pdf = pdfium.PdfDocument(data)
    except Exception:
        raise ReadError("the PDF can't be opened") from None
    try:
        texts = [pdf[i].get_textpage().get_text_range() for i in range(len(pdf))]
    finally:
        pdf.close()
    if not any(len(t.strip()) >= TEXT_LAYER_CHARS for t in texts):
        return None
    return [ln.strip() for t in texts for ln in t.splitlines() if ln.strip()]


def _rendered(page):
    """A page at the reading DPI, or smaller when that would pass the pixel cap: a page of
    any size is never drawn bigger than an image may be."""
    w, h = page.get_size()  # in points
    scale = DPI / 72
    if w * h * scale * scale > MAX_PIXELS:
        scale = (MAX_PIXELS / max(w * h, 1)) ** 0.5
    return page.render(scale=max(scale, 0.01)).to_pil()


def _page_text(page) -> list[str] | None:
    """A page's text layer as lines, or None when it gives fewer than 20 characters."""
    text = page.get_textpage().get_text_range()
    if len(text.strip()) < TEXT_LAYER_CHARS:
        return None
    return [ln.strip() for ln in text.splitlines() if ln.strip()]


def _checked(pdf, text_pages: list[tuple[int, list[str]]], lines: list[str]) -> dict | None:
    """The total against the scan (S9.8.2.1.1): the page whose text layer gives the total,
    read by OCR too; whether that finds the same amount there, and the total it reads."""
    from . import parser

    total = parser.find_total([parser.join_split_amounts(x) for x in lines])
    if total is None:
        return None
    page = next(
        (i for i, got in text_pages if (t := parser.find_total(got)) and t.value == total.value),
        None,
    )
    if page is None:
        page = next(
            (i for i, got in text_pages if any(total.value in parser.amounts(x) for x in got)),
            None,
        )
    if page is None:
        return None
    scanned = [parser.join_split_amounts(x) for x in _ocr([_rendered(pdf[page])])]
    found = {a for x in scanned for a in parser.amounts(x)}
    scan = parser.find_total(scanned)
    return {
        "text": str(total.value),
        "scan": str(scan.value) if scan else None,
        "agrees": total.value in found,
    }


def _read_pdf(data: bytes, pages: int, check: bool) -> Read:
    """Page by page (S9.8.2.1): a page's text layer when it has one, else OCR of the page, at
    most `pages` of them; the method says which, or both."""
    import pypdfium2 as pdfium

    try:
        pdf = pdfium.PdfDocument(data)
    except Exception:
        raise ReadError("the PDF can't be opened") from None
    lines: list[str] = []
    text_pages: list[tuple[int, list[str]]] = []
    ocred = 0
    try:
        for i in range(len(pdf)):
            got = _page_text(pdf[i])
            if got is not None:
                text_pages.append((i, got))
                lines += got
            elif ocred < pages:
                # Rendered one at a time, so a long statement holds one page in memory, each
                # within the images' pixel cap (S9.8.4.3).
                ocred += 1
                lines += _ocr([_rendered(pdf[i])])
        found = _checked(pdf, text_pages, lines) if check and text_pages else None
    finally:
        pdf.close()
    if text_pages and ocred:
        return Read(lines, "both", f"pypdfium2 text layer, {engine_name()}", found)
    if text_pages:
        return Read(lines, "text", "pypdfium2 text layer", found)
    return Read(lines, "ocr", engine_name())


def read(data: bytes, media_type: str, pages: int = MAX_PAGES, check: bool = False) -> Read:
    """A receipt or statement read. With `check` (a receipt's), a total read from a text
    layer is checked against the scan of its page."""
    from PIL import Image

    Image.MAX_IMAGE_PIXELS = MAX_PIXELS
    if media_type == "application/pdf":
        return _read_pdf(data, pages, check)
    try:
        import pi_heif

        pi_heif.register_heif_opener()
        img = Image.open(io.BytesIO(data))
        if img.size[0] * img.size[1] > MAX_PIXELS:
            raise ReadError("the image is larger than 40 million pixels")
        img.load()
    except ReadError:
        raise
    except Exception as e:
        raise ReadError(f"the image can't be opened ({type(e).__name__})") from None
    return Read(_ocr([img]), "ocr", engine_name())
