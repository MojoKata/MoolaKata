"""Files parsed in the reader's worker, never in the server (requirements S9.8.4.2): a
receipt's thumbnail, a HEIC photo as JPEG for display, a PDF's text layer, and the OFX and CSV
files of an import. One worker is kept for these quick jobs, beside the reading queue's, and
started again after a crash; what it answers is checked field by field here."""

import base64
import threading

from .importers.parsed import Malformed, ParsedFile, ReadError, from_json

LIMIT = 60
_lock = threading.Lock()
_worker = None
_data_dir = None
# What the file sandbox is shown as, whatever this host offers: set for the generated mockup and
# the tests, so what they show doesn't depend on the kernel they run on. None everywhere else.
PINNED: bool | None = None


def _call(op: str, data: bytes, **params) -> dict:
    global _worker
    from .receipts.reading import Worker

    with _lock:
        if _worker is None:
            _worker = Worker(_data_dir)
        return _worker.call(op, data, LIMIT, **params)


def use_data_dir(path) -> None:
    """The directory the quick worker's sandbox keeps it out of (S9.8.4.2)."""
    global _data_dir, _worker
    with _lock:
        _data_dir = path
        if _worker is not None:
            _worker.stop()
            _worker = None


def stop() -> None:
    global _worker
    with _lock:
        if _worker is not None:
            _worker.stop()
            _worker = None


def sandbox() -> dict | None:
    """What the quick worker's sandbox holds: seccomp, landlock, core; None if it won't start."""
    out = _call("selftest", b"")
    if "error" in out:
        return None
    with _lock:
        return dict(_worker.state) if _worker is not None and _worker.state else None


def file_sandbox(start: bool = False) -> bool | None:
    """Whether reading keeps its worker out of the data directory (S9.8.4.2): what the quick
    worker found when it started, else whether this host offers Landlock at all. With `start`,
    the worker is started first; None when it won't start."""
    if PINNED is not None:
        return PINNED
    if start:
        state = sandbox()
        return state.get("landlock") if state else None
    with _lock:
        if _worker is not None and _worker.state:
            return _worker.state["landlock"]
    from .sandbox import landlock_abi

    return landlock_abi() >= 1


def _bytes(value, magic: tuple[bytes, ...], limit: int) -> bytes | None:
    if value is None:
        return None
    if not isinstance(value, str) or len(value) > limit * 4 // 3 + 8:
        raise Malformed("an image")
    data = base64.b64decode(value, validate=True)
    if not any(data.startswith(m) for m in magic):
        raise Malformed("an image")
    return data


def thumbnail(data: bytes, media: str) -> bytes | None:
    """A small WebP of an image or a PDF's first page; None when it can't be drawn."""
    out = _call("thumbnail", data, media=media)
    if "error" in out:
        return None
    try:
        webp = _bytes(out.get("webp"), (b"RIFF",), 2 * 1024 * 1024)
    except Malformed, ValueError:
        return None
    return webp if webp is None or webp[8:12] == b"WEBP" else None


def as_jpeg(data: bytes) -> bytes:
    """A HEIC photo as JPEG for the browser; ReadError when it can't be."""
    out = _call("jpeg", data)
    if "error" in out:
        raise ReadError(out["error"])
    try:
        jpeg = _bytes(out.get("jpeg"), (b"\xff\xd8\xff",), 64 * 1024 * 1024)
    except Malformed, ValueError:
        raise ReadError("the photo can't be shown") from None
    if jpeg is None:
        raise ReadError("the photo can't be shown")
    return jpeg


def text_layer(data: bytes) -> list[str] | None:
    """A PDF's text layer as lines, or None when it has none worth reading."""
    out = _call("text", data)
    if "error" in out:
        raise ReadError(out["error"])
    lines = out.get("lines")
    if lines is None:
        return None
    if not isinstance(lines, list) or not all(isinstance(x, str) and len(x) <= 2000 for x in lines):
        raise ReadError("the reader answered out of turn")
    return lines[:20_000]


def _parsed(out: dict) -> ParsedFile:
    if "error" in out:
        raise ReadError(out["error"])
    try:
        return from_json(out.get("parsed"))
    except Malformed:
        raise ReadError("the reader answered out of turn") from None


def read_ofx(data: bytes) -> ParsedFile:
    return _parsed(_call("ofx", data))


def read_csv(data: bytes, mapping: dict) -> ParsedFile:
    return _parsed(_call("csv", data, mapping=mapping))


MAPPING_KEYS = {
    "delimiter",
    "skipRows",
    "negateAmounts",
    "dateFormat",
}


def propose_csv(data: bytes, trades: bool = False) -> dict:
    """A CSV's headers, a sample and a guessed mapping, for the person to check; a trade
    history's columns too for an account that holds instruments."""
    out = _call("csv-propose", data, trades=trades)
    if "error" in out:
        raise ReadError(out["error"])
    p = out.get("proposal")
    ok = (
        isinstance(p, dict)
        and isinstance(p.get("headers"), list)
        and len(p["headers"]) <= 500
        and all(isinstance(h, str) and len(h) <= 200 for h in p["headers"])
        and isinstance(p.get("sample"), list)
        and len(p["sample"]) <= 8
        and all(
            isinstance(r, list)
            and len(r) <= 500
            and all(isinstance(c, str) and len(c) <= 500 for c in r)
            for r in p["sample"]
        )
        and isinstance(p.get("trailer", 0), int)
        and isinstance(p.get("mapping"), dict)
        and all(
            isinstance(k, str)
            and (v is None or isinstance(v, (str, int, bool)))
            and len(str(v)) <= 200
            for k, v in p["mapping"].items()
        )
    )
    if not ok:
        raise ReadError("the reader answered out of turn")
    return {
        "headers": p["headers"],
        "sample": p["sample"],
        "mapping": p["mapping"],
        "trailer": p.get("trailer", 0),
    }
