"""Each setting's refusals (S16, R3.11): a value of the wrong type, blank where blank isn't
allowed, or out of its range is refused at its key, with its code and the words Settings shows
there; never read as a default."""

import pytest

from moolakata import settings
from moolakata.errors import Problem

LONG = "x" * 61


@pytest.mark.parametrize(
    ("key", "value", "words"),
    [
        # A whole number: never a bool, a float or text.
        ("smtpPort", True, "a whole number"),
        ("smtpPort", 25.0, "a whole number"),
        ("smtpPort", "25", "a whole number"),
        ("smtpPort", None, "a whole number"),
        ("smtpPort", 0, "between 1 and 65535"),
        ("smtpPort", 65536, "between 1 and 65535"),
        ("backupCopies", 2, "between 3 and 365"),
        ("keepStatementsYears", 0, "between 1 and 100"),
        ("keepStatementsYears", "ten", "a whole number"),
        ("signupEnabled", 1, "on or off"),
        ("signupEnabled", None, "on or off"),
        ("serverName", 7, "text"),
        ("serverName", "   ", "cannot be empty"),
        ("serverName", LONG, "at most 60 characters"),
        ("smtpUsername", "u" * 201, "at most 200 characters"),
        ("smtpUsername", 5, "text"),
        ("priceRefreshTime", "24:00", "a time of day as HH:MM"),
        ("priceRefreshTime", "6:00", "a time of day as HH:MM"),
        ("backupTime", 230, "a time of day as HH:MM"),
        ("priceRefreshZone", "Mars/Olympus", "a time zone name, such as America/New_York"),
        ("priceRefreshZone", "", "a time zone name, such as America/New_York"),
        ("priceRefreshZone", 5, "a time zone name, such as America/New_York"),
        ("priceRefreshZone", "../etc/passwd", "a time zone name, such as America/New_York"),
        (
            "linkAddress",
            "http://money.example.lan",
            "an https address with no query, such as https://money.example.lan",
        ),
        (
            "connectorAddress",
            "https://money.example.lan/?a=1",
            "an https address with no query, such as https://money.example.lan",
        ),
        (
            "linkAddress",
            "https://money.example.lan/#top",
            "an https address with no query, such as https://money.example.lan",
        ),
        ("publicUrl", "ftp://money.example.lan", "an address such as https://money.example.lan"),
        ("publicUrl", "https://money example", "an address such as https://money.example.lan"),
        ("signupDomains", "example.com", "a list of email domains"),
        ("signupDomains", ["example.com", 3], "a list of email domains"),
        ("signupDomains", ["localhost"], "'localhost' is not an email domain"),
        ("signupDomains", [" "], "'' is not an email domain"),
        ("networkAppRanges", "10.0.0.0/8", "a list of address ranges"),
        ("networkAppRanges", [None], "a list of address ranges"),
        (
            "networkLinkRanges",
            ["10.0.0.0/33"],
            "'10.0.0.0/33' is not an address or a range such as 192.168.1.0/24",
        ),
        ("smtpHost", "smtp example.com", "a host name or address, such as smtp.example.com"),
        ("bitcoinNodeHost", 7, "a host name or address, such as smtp.example.com"),
        ("smtpSecurity", "ssl", "one of starttls, tls, none"),
        ("smtpSecurity", None, "one of starttls, tls, none"),
        (
            "smtpFrom",
            "money@example",
            "an email address, such as MoolaKata <money@example.com>",
        ),
        ("smtpFrom", 5, "an email address, such as MoolaKata <money@example.com>"),
        ("householdAvatar", "MK", "initials or an image"),
        ("householdAvatar", {"kind": "emoji"}, "initials or an image"),
        ("householdAvatar", {"kind": "initials", "initials": " "}, "one to three letters"),
        ("householdAvatar", {"kind": "initials", "initials": "ABCD"}, "one to three letters"),
        (
            "householdAvatar",
            {"kind": "initials", "initials": "MK", "color": "green"},
            "a colour such as #3b7a57",
        ),
        ("householdAvatar", {"kind": "image"}, "an image"),
        ("householdAvatar", {"kind": "image", "image": "https://x/y.png"}, "an image"),
    ],
)
def test_a_value_out_of_its_setting_is_refused_at_its_key(key, value, words):
    with pytest.raises(Problem) as e:
        settings.coerce(key, value)
    p = e.value
    assert (p.status, p.code, p.detail) == (422, "invalid-setting", f"{key}: {words}")
    [error] = p.errors
    assert (error.field, error.code, error.message) == (key, "invalid-setting", f"Must be {words}.")


def test_a_key_that_is_no_setting_is_refused_at_itself():
    with pytest.raises(Problem) as e:
        settings.coerce("smtpPassword2", "x")
    p = e.value
    assert (p.status, p.code, p.detail) == (
        422,
        "unknown-setting",
        "There is no setting 'smtpPassword2'.",
    )
    [error] = p.errors
    assert (error.field, error.code, error.message) == (
        "smtpPassword2",
        "unknown-setting",
        "no such setting",
    )


@pytest.mark.parametrize(
    ("key", "value", "kept"),
    [
        ("priceRefreshZone", "Europe/Paris", "Europe/Paris"),
        ("priceRefreshTime", "23:59", "23:59"),
        ("serverName", "  home  ", "home"),
        ("smtpUsername", "", None),  # an optional text left blank is none
        ("keepStatementsYears", None, None),  # none: kept for ever (S16.17)
        ("keyReminderMonths", 0, 0),  # 0 is off (S15.8.2), its own range's low end
        ("smtpHost", "", None),
        ("smtpHost", " SMTP.Example.com ", "smtp.example.com"),
        ("smtpFrom", None, None),
        ("smtpFrom", "", None),
        ("smtpFrom", " MoolaKata <money@example.com> ", "MoolaKata <money@example.com>"),
        ("signupDomains", [" @Example.COM "], ["example.com"]),
        # An empty entry among the ranges is passed over; a single address is its own range.
        (
            "networkAppRanges",
            ["", " 10.1.2.3 ", "192.168.1.7/24"],
            ["10.1.2.3/32", "192.168.1.0/24"],
        ),
        ("linkAddress", None, None),
        ("linkAddress", "https://money.example.lan/", "https://money.example.lan"),
        (
            "householdAvatar",
            {"kind": "initials", "initials": " ab "},
            {"kind": "initials", "initials": "ab", "color": "#3b7a57"},
        ),
        (
            "householdAvatar",
            {"kind": "image", "image": "data:image/png;base64,AAAA"},
            {"kind": "image", "image": "data:image/png;base64,AAAA"},
        ),
    ],
)
def test_a_value_in_its_setting_is_kept_as_settings_shows_it(key, value, kept):
    assert settings.coerce(key, value) == kept
