"""The reader's worker process (requirements S9.8.4): run as `python -I -m
moolakata.receipts.worker <data directory>`, with no environment and no file descriptor but
its two pipes. Every file a person or the connector brings is parsed here, never in the server:
receipts and statements read, thumbnails made, HEIC photos decoded for display, and OFX and CSV
files read for an import.

Before it reads anything it gives up what it doesn't need (S9.8.4.2): no network socket (a
seccomp filter), nothing beneath the data directory or outside the system's and Python's own
files (Landlock, where the kernel has it), and no core dump. It answers in one fixed shape,
length-prefixed JSON that the server checks field by field, never pickled objects, so a worker
that a hostile file has taken over can't run code in the server.

A request is a JSON frame (`op` and its parameters, `length`) and then a frame of the file's
bytes; the answer is one JSON frame: the result's fields, or `error`."""

import base64
import contextlib
import json
import os
import socket
import sys
from pathlib import Path

MAX_FILE = 110 * 1024 * 1024
MAX_HEAD = 1024 * 1024


def read_frame(f, limit: int) -> bytes | None:
    """One frame: 4 bytes of length, big-endian, then that many bytes. None at the end."""
    head = f.read(4)
    if len(head) < 4:
        return None
    n = int.from_bytes(head, "big")
    if n > limit:
        raise ValueError("a frame larger than allowed")
    data = f.read(n)
    if len(data) != n:
        raise ValueError("a frame cut short")
    return data


def write_frame(f, data: bytes) -> None:
    f.write(len(data).to_bytes(4, "big") + data)
    f.flush()


def _preload() -> None:
    """The libraries the jobs use, loaded while the files they need can still be opened."""
    from PIL import Image

    Image.init()
    import pi_heif
    import pypdfium2  # noqa: F401
    from ofxtools.Parser import OFXTree  # noqa: F401

    pi_heif.register_heif_opener()


def _lock_down(data_dir: Path | None) -> dict:
    from .. import sandbox

    dumpable = sandbox.not_dumpable()
    roots = {Path(p) for p in ("/usr", "/lib", "/lib64", "/bin", "/etc", "/proc", "/sys")}
    roots |= {Path(p) for p in (sys.prefix, sys.base_prefix, sys.exec_prefix)}
    roots |= {Path(p) for p in sys.path if p and Path(p).exists()}
    files = sandbox.read_only(sorted(roots), [Path("/dev")], refuse=data_dir)
    network = sandbox.no_network()
    return {"seccomp": network, "landlock": files, "core": dumpable}


def _b64(data: bytes | None) -> str | None:
    return base64.b64encode(data).decode() if data is not None else None


def handle(job: dict, data: bytes) -> dict:
    """One job; what it found, or why not, in words safe to show."""
    op = job.get("op")
    from .. import receipts
    from ..errors import Problem
    from ..importers import csvfile, ofx
    from ..importers.parsed import ReadError, to_json
    from . import ocr

    try:
        if op == "read":
            pages = job.get("pages")
            if type(pages) is not int or not 1 <= pages <= ocr.STATEMENT_PAGES:
                pages = ocr.MAX_PAGES
            r = ocr.read(data, str(job.get("media") or ""), pages)
            return {"lines": r.lines, "method": r.method, "engine": r.engine}
        if op == "text":
            return {"lines": ocr.text_layer(data)}
        if op == "thumbnail":
            return {"webp": _b64(receipts.thumbnail(data, str(job.get("media") or "")))}
        if op == "jpeg":
            return {"jpeg": _b64(receipts.as_jpeg(data))}
        if op == "ofx":
            return {"parsed": to_json(ofx.read(data))}
        if op == "csv-propose":
            return {"proposal": csvfile.propose(data)}
        if op == "csv":
            return {"parsed": to_json(csvfile.read(data, job.get("mapping") or {}))}
        if op == "selftest":
            return selftest(job)
    except (ocr.ReadError, ReadError) as e:
        return {"error": str(e)}
    except Problem as e:
        return {"error": e.detail}
    except MemoryError:
        return {"error": "it needed more memory than the reader may use"}
    except Exception as e:  # anything else a broken file sets off
        return {"error": f"the reader failed ({type(e).__name__})"}
    return {"error": f"no such job: {op!r}"}


def selftest(job: dict) -> dict:
    """What the sandbox allows, for the tests and Settings › Receipts: a network socket, a local
    one, and a signal to the server that started it (S9.8.4.2)."""

    def allowed(fn) -> bool:
        try:
            fn()
        except OSError:
            return False
        return True

    network = allowed(lambda: socket.socket(socket.AF_INET, socket.SOCK_STREAM).close())
    local = allowed(lambda: socket.socket(socket.AF_UNIX, socket.SOCK_STREAM).close())
    pair = allowed(lambda: [x.close() for x in socket.socketpair()])
    signal = allowed(lambda: os.kill(os.getppid(), 0))
    readable = False
    if job.get("path"):
        try:
            os.listdir(job["path"])
            readable = True
        except OSError:
            pass
    return {
        "network": network,
        "local": local or pair,
        "signal": signal,
        "path": readable,
        "environment": sorted(os.environ),
    }


def main(argv: list[str]) -> int:
    os.environ["OMP_NUM_THREADS"] = "2"
    data_dir = Path(argv[1]) if len(argv) > 1 and argv[1] else None
    _preload()
    state = _lock_down(data_dir)
    with os.fdopen(0, "rb") as inp, os.fdopen(1, "wb") as out:
        write_frame(out, json.dumps({"ready": True, **state}).encode())
        with contextlib.suppress(OSError):
            os.nice(10)
        while True:
            try:
                head = read_frame(inp, MAX_HEAD)
                if head is None:
                    return 0
                job = json.loads(head)
                data = read_frame(inp, MAX_FILE) or b""
            except ValueError:
                return 1
            write_frame(out, json.dumps(handle(job, data)).encode())


if __name__ == "__main__":
    sys.exit(main(sys.argv))
