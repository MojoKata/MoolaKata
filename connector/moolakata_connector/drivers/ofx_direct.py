"""OFX Direct Connect (requirements S18.9.2): institutions that still run an OFX server.
A statement request signed in with the owner's username and password, answered with an OFX
statement that MoolaKata imports as it is. The server's address is in the Connection's
settings, so the host the driver reaches is the one its owner named, and the credentials are
bound to it when they are filed (S18.7.3): a changed address asks for them again."""

import datetime as dt
import re
import uuid
from urllib.parse import urlsplit

from . import Account, Driver, File, Result

BANK_TYPES = ("CHECKING", "SAVINGS", "MONEYMRKT", "CREDITLINE")
HEADER = (
    "OFXHEADER:100\r\nDATA:OFXSGML\r\nVERSION:102\r\nSECURITY:NONE\r\nENCODING:USASCII\r\n"
    "CHARSET:1252\r\nCOMPRESSION:NONE\r\nOLDFILEUID:NONE\r\nNEWFILEUID:{uid}\r\n\r\n"
)
SIGNON_CODE = re.compile(r"<SONRS>.*?<CODE>(\d+)", re.S)
ACCTID = re.compile(r"<ACCTID>([^<\r\n]+)")
STATEMENTS = re.compile(r"<(STMTTRNRS|CCSTMTTRNRS|INVSTMTTRNRS)>.*?</\1>", re.S)
STATUS_CODE = re.compile(r"<STATUS>\s*<CODE>(\d+)", re.S)
# Sign-on codes (OFX 1.0.2 §2.5.1.6, §2.5.1.5) that ask the owner, not the connector.
SIGN_IN_AGAIN = {
    "15500": "the institution refused the sign-in",
    "15501": "the institution refused the sign-in",
    "15502": "the institution locked the sign-in: unlock it there, then sign in again",
    "15503": "the institution refused the sign-in",
    "15000": "the institution asks for a new password: change it there, then sign in again",
}


def _stamp(d: dt.datetime) -> str:
    return d.strftime("%Y%m%d%H%M%S")


class Unsendable(ValueError):
    """A value the request can't carry as typed: never altered to fit."""


def _v(value, what: str) -> str:
    """A value written into the SGML request: `&`, `<` and `>` escaped (OFX 1.0.2 §2.3), and
    only characters its charset (Windows-1252, as the header says) holds."""
    text = str(value or "")
    try:
        text.encode("cp1252")
    except UnicodeEncodeError:
        raise Unsendable(
            f"the {what} holds a character an OFX request can't carry: nothing was sent"
        ) from None
    if any(ch in text for ch in "\r\n"):
        raise Unsendable(f"the {what} holds a line break: nothing was sent")
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def request(settings: dict, credentials: dict, since: dt.date) -> bytes:
    """The OFX 1.0.2 request for one account's statement since a date."""
    now = dt.datetime.now(dt.UTC)
    kind = str(settings.get("accountType") or "CHECKING").upper()
    acct = _v(settings.get("accountId"), "account number")
    uid = str(uuid.uuid4())
    user = _v(credentials.get("username"), "username")
    password = _v(credentials.get("password"), "password")
    org, fid = _v(settings.get("org"), "ORG"), _v(settings.get("fid"), "FID")
    bank = _v(settings.get("bankId"), "routing number")
    signon = (
        f"<SIGNONMSGSRQV1><SONRQ><DTCLIENT>{_stamp(now)}<USERID>{user}<USERPASS>{password}"
        f"<LANGUAGE>ENG<FI><ORG>{org}<FID>{fid}</FI><APPID>QWIN<APPVER>2700</SONRQ>"
        "</SIGNONMSGSRQV1>"
    )
    inctran = f"<INCTRAN><DTSTART>{since:%Y%m%d}<INCLUDE>Y</INCTRAN>"
    if kind == "CREDITCARD":
        body = (
            f"<CREDITCARDMSGSRQV1><CCSTMTTRNRQ><TRNUID>{uid}<CCSTMTRQ><CCACCTFROM><ACCTID>{acct}"
            f"</CCACCTFROM>{inctran}</CCSTMTRQ></CCSTMTTRNRQ></CREDITCARDMSGSRQV1>"
        )
    elif kind == "INVESTMENT":
        body = (
            f"<INVSTMTMSGSRQV1><INVSTMTTRNRQ><TRNUID>{uid}<INVSTMTRQ><INVACCTFROM><BROKERID>"
            f"{bank or org}<ACCTID>{acct}</INVACCTFROM>"
            f"{inctran}<INCOO>N<INCPOS><DTASOF>{_stamp(now)}<INCLUDE>Y</INCPOS><INCBAL>Y"
            f"</INVSTMTRQ></INVSTMTTRNRQ></INVSTMTMSGSRQV1>"
        )
    else:
        body = (
            f"<BANKMSGSRQV1><STMTTRNRQ><TRNUID>{uid}<STMTRQ><BANKACCTFROM><BANKID>"
            f"{bank}<ACCTID>{acct}<ACCTTYPE>{_v(kind, 'account type')}</BANKACCTFROM>"
            f"{inctran}</STMTRQ></STMTTRNRQ></BANKMSGSRQV1>"
        )
    return (HEADER.format(uid=uid) + f"<OFX>{signon}{body}</OFX>").encode("cp1252")


def _only(body: bytes, last4: str) -> tuple[bytes, str | None]:
    """The answer kept to the Connection's own account's statement, when a server answers with
    several (the import takes one account a file, S1.3.2); and the statement's own status
    code, when it isn't 0."""
    text = body.decode("latin-1")
    blocks = list(STATEMENTS.finditer(text))
    mine = [
        b for b in blocks if (m := ACCTID.search(b.group(0))) and m.group(1).strip()[-4:] == last4
    ] or blocks[:1]
    for b in mine:
        status = STATUS_CODE.search(b.group(0))
        if status and status.group(1) != "0":
            return body, status.group(1)
    if len(blocks) < 2:
        return body, None
    for b in reversed(blocks):
        if b not in mine:
            text = text[: b.start()] + text[b.end() :]
    return text.encode("latin-1"), None


class OfxDirect(Driver):
    name = "ofx-direct"
    hosts = ()  # the server named in each Connection's settings (hosts_for)
    needs = ("username", "password")
    interval = 24 * 3600

    def hosts_for(self, settings: dict) -> tuple[str, ...]:
        host = urlsplit(str(settings.get("url") or "")).hostname
        return (host,) if host else ()

    def binds(self, settings: dict) -> str | None:
        return (urlsplit(str(settings.get("url") or "")).hostname or "").lower() or None

    def run(
        self, settings: dict, credentials: dict | None, accounts: list[Account], http
    ) -> Result:
        url = str(settings.get("url") or "")
        if not url.startswith("https://"):
            return Result("failing", "the OFX server's address must be https")
        since = dt.date.today() - dt.timedelta(days=90)
        for a in accounts:
            if a.last4 and a.last4 == str(settings.get("accountId", ""))[-4:]:
                days = settings.get("days")
                days = days if isinstance(days, int) and 1 <= days <= 90 else 45
                since = dt.date.today() - dt.timedelta(days=days)
        try:
            body = request(settings, credentials or {}, since)
        except Unsendable as e:
            return Result("failing", str(e))
        headers = {"Content-Type": "application/x-ofx", "Accept": "*/*, application/x-ofx"}
        r = http.request("POST", url, headers, body)
        text = r.body.decode("latin-1", "replace")
        code = SIGNON_CODE.search(text)
        if r.status != 200 or not code:
            return Result("failing", f"the OFX server answered {r.status}")
        if code.group(1) != "0":
            if code.group(1) in SIGN_IN_AGAIN:
                return Result("needs-sign-in", SIGN_IN_AGAIN[code.group(1)])
            if code.group(1) == "3000":
                return Result(
                    "failing",
                    "the institution asks for a second factor, which OFX Direct Connect can't "
                    "give: download its files and upload them instead",
                )
            return Result("failing", f"the OFX server refused (code {code.group(1)})")
        last4 = str(settings.get("accountId", ""))[-4:]
        found = [
            {"name": settings.get("accountType", "").title(), "last4": m.strip()[-4:]}
            for m in ACCTID.findall(text)
        ]
        body, refused = _only(r.body, last4)
        if refused:
            return Result("failing", f"the OFX server refused the statement (code {refused})")
        files = [
            File(a.id, f"ofx-{dt.date.today():%Y-%m-%d}.ofx", body, "ofx")
            for a in accounts
            if a.last4 == last4
        ]
        message = f"{len(files)} statement{'s' if len(files) != 1 else ''}"
        if not files:
            message = "no account here names this institution account"
        return Result("ok", message, found=found, files=files)
