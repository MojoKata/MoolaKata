"""The server's own zone, read from the host (requirements S14.9.2)."""

from pathlib import Path
from zoneinfo import TZPATH

from moolakata.timezones import zone_from, zone_of


def test_a_mounted_localtime_is_known_by_its_content():
    # compose.yaml mounts the host's /etc/localtime as a file, not a link to a named zone.
    denver = next(Path(p) / "America/Denver" for p in TZPATH if (Path(p) / "America").is_dir())
    assert zone_of(denver.read_bytes()) == "America/Denver"
    assert zone_of(b"not a zone") == ""


def zone_file(name: str) -> Path:
    return next(Path(p) / name for p in TZPATH if (Path(p) / name).is_file())


def test_a_hosts_file_mounted_over_the_images_link_is_known_by_its_data(tmp_path):
    """The image's /etc/localtime links to Etc/UTC, and the host's file mounted there (the VM's
    compose file, TrueNAS's YAML) lands on the link's target: its data is the host's zone, its
    name the image's. Found on TrueNAS, where the server took itself to be in UTC."""
    target = tmp_path / "zoneinfo" / "Etc" / "UTC"
    target.parent.mkdir(parents=True)
    target.write_bytes(zone_file("America/Los_Angeles").read_bytes())
    link = tmp_path / "localtime"
    link.symlink_to(target)
    none = tmp_path / "no-timezone"
    assert zone_from({}, none, link) == "America/Los_Angeles"  # not its alias US/Pacific
    target.write_bytes(zone_file("Etc/UTC").read_bytes())
    assert zone_from({}, none, link) == "Etc/UTC"  # a host in UTC stays there
    chicago = tmp_path / "chicago"
    chicago.symlink_to(zone_file("America/Chicago"))
    assert zone_from({}, none, chicago) == "America/Chicago"  # a link's own name, kept
    # The image's own /etc/timezone says Etc/UTC too: the data still decides.
    timezone = tmp_path / "timezone"
    timezone.write_text("Etc/UTC\n")
    target.write_bytes(zone_file("Europe/London").read_bytes())
    assert zone_from({}, timezone, link) == "Europe/London"
    target.write_bytes(zone_file("Etc/UTC").read_bytes())
    assert zone_from({}, timezone, link) == "Etc/UTC"
    timezone.write_text("Europe/Berlin\n")
    berlin = tmp_path / "berlin"
    berlin.write_bytes(zone_file("Europe/Berlin").read_bytes())
    assert zone_from({}, timezone, berlin) == "Europe/Berlin"  # a file, named by /etc/timezone
    assert zone_from({"TZ": ":America/Denver"}, timezone, link) == "America/Denver"
    assert zone_from({}, none, tmp_path / "missing") == "UTC"


def _tzif(offset: int) -> bytes:
    """A compiled zone file (RFC 9636, version 1) keeping one fixed offset no named zone keeps."""
    import struct

    counts = struct.pack(">6l", 0, 0, 0, 0, 1, 4)  # isut, isstd, leap, transitions, types, chars
    return b"TZif" + b"\0" * 16 + counts + struct.pack(">lBB", offset, 0, 0) + b"ODD\0"


def test_a_zone_no_named_zone_keeps_falls_back_to_the_names_then_utc(tmp_path):
    """S14.9.2: a file whose time no named zone keeps (+00:17) is known by /etc/timezone's
    name, or else by the link's, or else is UTC; a link to a file outside zoneinfo names
    nothing."""
    odd = tmp_path / "odd"
    odd.write_bytes(_tzif(17 * 60))
    assert zone_of(odd.read_bytes()) == ""
    none = tmp_path / "no-timezone"
    timezone = tmp_path / "timezone"
    timezone.write_text("Europe/Berlin\n")
    assert zone_from({}, timezone, odd) == "Europe/Berlin"
    assert zone_from({}, none, odd) == "UTC"
    link = tmp_path / "localtime"
    link.symlink_to(odd)  # its target outside any zoneinfo folder: no name from the link
    assert zone_from({}, none, link) == "UTC"
    named = tmp_path / "zoneinfo" / "America" / "Chicago"
    named.parent.mkdir(parents=True)
    named.write_bytes(_tzif(17 * 60))
    named_link = tmp_path / "named"
    named_link.symlink_to(named)
    assert zone_from({}, none, named_link) == "America/Chicago", "the link's name, last"


def test_with_no_zone_table_the_first_name_found_is_the_zones(tmp_path, monkeypatch):
    """tzdata without zone1970.tab: of names for the same zone, the first found stands."""
    from moolakata import timezones

    monkeypatch.setattr(timezones, "TZPATH", (str(tmp_path),))
    timezones._listed.cache_clear()
    try:
        assert timezones.canonical(["US/Pacific", "America/Los_Angeles"]) == "US/Pacific"
        assert timezones.canonical([]) == ""
    finally:
        timezones._listed.cache_clear()
