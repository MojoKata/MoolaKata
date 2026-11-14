"""The vendored browser libraries' gate (requirements S17.3.1): the cooldown and the hash check."""

import importlib.util
import shutil
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

VENDOR = Path(__file__).resolve().parents[2] / "ui" / "vendor"


def load(directory: Path):
    spec = importlib.util.spec_from_file_location("vendor", directory / "vendor.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


vendor = load(VENDOR)
NOW = datetime(2026, 10, 14, tzinfo=UTC)


def test_a_release_inside_the_cooldown_is_refused():
    with pytest.raises(SystemExit, match="under the 14-day cooldown; adopt it from 2026-10-22"):
        vendor.cooldown(NOW - timedelta(days=6), NOW, None)


def test_the_cooldown_passes_with_age_or_a_reason(capsys):
    vendor.cooldown(NOW - timedelta(days=14), NOW, None)
    vendor.cooldown(NOW - timedelta(days=1), NOW, "fixes a published XSS")
    assert "cooldown waived: fixes a published XSS" in capsys.readouterr().out


@pytest.mark.parametrize(
    "repository",
    [
        "git+https://github.com/preactjs/preact.git",
        {"type": "git", "url": "git://github.com/preactjs/preact.git"},
        {"type": "git", "url": "https://github.com/preactjs/preact"},
    ],
)
def test_repository_url_is_the_one_a_provenance_certificate_names(repository):
    assert vendor.repository_url({"repository": repository}) == "https://github.com/preactjs/preact"


def test_every_pin_has_its_source_recorded():
    for name, pkg in vendor.load()["packages"].items():
        # Any forge for a package without provenance (ProseMirror's own); a provenance
        # certificate names the GitHub repository it was built from.
        assert pkg["repository"].startswith("https://"), name
        if pkg["provenance"]:
            assert pkg["repository"].startswith("https://github.com/"), name
        assert isinstance(pkg["provenance"], bool), name
        assert not vendor.verify({"packages": {name: pkg}}), name


def test_a_changed_tarball_is_refused(tmp_path):
    copy = tmp_path / "vendor"
    shutil.copytree(VENDOR, copy, ignore=shutil.ignore_patterns("*.tgz", "__pycache__"))
    for tgz in VENDOR.glob("*.tgz"):
        shutil.copy(tgz, copy)
    tgz = copy / "htm-3.1.1.tgz"
    tgz.write_bytes(tgz.read_bytes() + b"\0")
    moved = load(copy)
    assert moved.main(["vendor.py", "verify"]) == 1
