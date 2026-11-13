"""The ui-kit's pages packed into one file (requirements S17.3.10.4), as a pull request's run
keeps it and the Pages site publishes it: it opens from the disk with nothing else, every page
drawn, no page or console error."""

import subprocess
import sys
from pathlib import Path

from conftest import PAGES_IN_ORDER

PACK = Path(__file__).resolve().parents[1] / "pages" / "pack.py"


def test_the_packed_pages_open_on_their_own(chromium, tmp_path):
    # The packer from this checkout, on a folder of the test's own.
    subprocess.run([sys.executable, str(PACK), str(tmp_path)], check=True, capture_output=True)  # noqa: S603
    packed = tmp_path / "kit.html"
    page = chromium.new_page()
    problems = []
    page.on("pageerror", lambda e: problems.append(f"page error: {e}"))
    page.on("console", lambda m: m.type == "error" and problems.append(f"console: {m.text}"))
    for name in PAGES_IN_ORDER:
        page.goto(f"{packed.as_uri()}#{name}")
        page.wait_for_selector(".kit-page h1")
    page.wait_for_selector(".glyph")
    page.close()
    assert problems == []
