# S17.2. Server dependencies

2. **Server dependencies**, each a ruling, kept short because each runs with the database: fastapi, pydantic,
   hypercorn, sqlalchemy, alembic, argon2-cffi, cryptography (AES-GCM, Ed25519 for links),
   httpx, segno (two-step QR), **Pillow** and **pypdfium2** (thumbnails and receipt reading,
   S9.5, S9.8), **sqlcipher3** (the wheel that bundles SQLCipher, for the main database and the
   linked copies, S14.1, S11.9), **rapidocr** with **onnxruntime** (receipt reading, S9.8). rapidocr brings
   numpy, opencv-python-headless, shapely, pyclipper and pyyaml with it, about 100 MB in all;
   the image carries them, and they load only in the receipt worker. **ofxtools** reads OFX
   and QFX files (pure Python, GPL-3.0-only, compatible with MoolaKata's GPLv3). **pi-heif** reads iPhone photos
   (HEIC): it decodes only, so it is smaller than pillow-heif, which also encodes. **numpy** is a direct dependency for projections
   (S6) as well as RapidOCR's.
   Standard library for email (`smtplib`), config (`tomllib`), logging and the command line.
   Pinned exactly in `uv.lock`, Python 3.14 (S17.9.7.1).
   1. **The dependency register and the egress audit.** `docs/dependencies.md` lists every
      library the server, the browser app and the build run with: its version, what it is for,
      why it was chosen, what it could do that MoolaKata must not (a call out of the house
      above all), with the switch that stops it and where MoolaKata throws it, and when to look
      at it again. A library that can reach out is marked **egress**, one that sends telemetry
      **telemetry** as well. **Every change to `uv.lock` or the vendor manifest is followed by
      an audit** before it is committed: `web/dev.sh audit` scans the installed wheels and the
      vendored files for URLs and the words of telemetry and update checks, diffs the findings
      against the register, and runs the server and the receipt worker in a network namespace
      with no interfaces through a receipt read, a price refresh against the stubs, a backup
      and a pass of the tasks, failing on any socket opened to a non-loopback address. The
      hashes of the files it was audited against are kept beside the register, in
      `web/audit.json`, and `web/check` fails when they no longer match, which costs nothing on
      an ordinary run: the audit itself runs when a dependency changes, not on every test
      cycle.
