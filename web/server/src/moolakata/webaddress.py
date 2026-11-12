"""Web addresses people type (S7.8.1): checked in one place, so a field called a link holds a
link, and never a script's address (`javascript:`) that would run once it is clicked."""

from urllib.parse import urlsplit

MOST = 2000  # characters: what browsers and servers commonly take


def why_not(text: str, schemes: tuple[str, ...] = ("http", "https")) -> str | None:
    """Why `text` isn't a web address with one of `schemes` and a host, or None."""
    if len(text) > MOST:
        return f"At most {MOST:,} characters."
    refused = "A web address starting with https:// or http://."
    if any(c.isspace() for c in text):
        return refused
    try:
        u = urlsplit(text)
        host = u.hostname
    except ValueError:
        return refused
    if u.scheme.lower() not in schemes or not host:
        return refused
    return None
