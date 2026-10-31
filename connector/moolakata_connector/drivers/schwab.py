"""Schwab (requirements S18.9.2): the Trader API, signed in on Schwab's own page. The owner
opens the sign-in address the driver reports, signs in, and seals the address they land on
(with the app's secret) for the connector; the driver exchanges its code for tokens and
keeps the refresh token in the vault. That token lasts seven days, so the Connection asks for
a sign-in every week. Positions, transactions and balances are posted as OFX, one file per
account, which MoolaKata imports as a broker's download."""

import base64
import datetime as dt
import json
import re
import secrets
import time
import uuid
from decimal import Decimal
from urllib.parse import parse_qs, urlencode, urlsplit

from . import Account, Driver, File, Result

HOST = "api.schwabapi.com"
REDIRECT = "https://127.0.0.1"
TOKEN = f"https://{HOST}/v1/oauth/token"
TRADER = f"https://{HOST}/trader/v1"
REFRESH_DAYS = 7
# What each of Schwab's asset types is in OFX (protocol §6): its security's aggregate, its
# trades' and its position's. A money market fund (Schwab's cash equivalents among them) is a
# mutual fund there.
KINDS = {
    "EQUITY": ("STOCKINFO", "STOCK", "POSSTOCK"),
    "ETF": ("STOCKINFO", "STOCK", "POSSTOCK"),
    "COLLECTIVE_INVESTMENT": ("STOCKINFO", "STOCK", "POSSTOCK"),
    "MUTUAL_FUND": ("MFINFO", "MF", "POSMF"),
    "CASH_EQUIVALENT": ("MFINFO", "MF", "POSMF"),
    "FIXED_INCOME": ("DEBTINFO", "DEBT", "POSDEBT"),
    "OPTION": ("OPTINFO", "OPT", "POSOPT"),
}
# Cash in or out with nothing else: money from outside, or moved between the owner's accounts.
CASH_KINDS = {
    "ACH_RECEIPT": "CREDIT",
    "ACH_DISBURSEMENT": "DEBIT",
    "CASH_RECEIPT": "CREDIT",
    "CASH_DISBURSEMENT": "DEBIT",
    "WIRE_IN": "CREDIT",
    "WIRE_OUT": "DEBIT",
    "ELECTRONIC_FUND": "XFER",
    "JOURNAL": "XFER",
}
# Notes that move neither cash nor shares (a memorandum, a margin account's SMA): nothing to
# write while they move nothing.
NOTES = ("MEMORANDUM", "SMA_ADJUSTMENT", "MARGIN_CALL")
# An option's end, by what the transaction says of it (S3.4).
ENDS = (("EXPIR", "EXPIRE"), ("ASSIGN", "ASSIGN"), ("EXERC", "EXERCISE"))
OCC = re.compile(r"(\S{1,6})\s*(\d{6})([CP])(\d{8})")  # an option's symbol, in OCC's form
HEADER = (
    "OFXHEADER:100\r\nDATA:OFXSGML\r\nVERSION:102\r\nSECURITY:NONE\r\nENCODING:USASCII\r\n"
    "CHARSET:1252\r\nCOMPRESSION:NONE\r\nOLDFILEUID:NONE\r\nNEWFILEUID:NONE\r\n\r\n"
)


def _basic(settings: dict, credentials: dict) -> str:
    pair = f"{settings.get('appKey', '')}:{credentials.get('appSecret', '')}".encode()
    return "Basic " + base64.b64encode(pair).decode()


def _form(http, settings, credentials, fields: dict) -> dict:
    headers = {
        "Authorization": _basic(settings, credentials),
        "Content-Type": "application/x-www-form-urlencoded",
    }
    r = http.request("POST", TOKEN, headers, urlencode(fields).encode())
    if r.status != 200:
        raise PermissionError(f"Schwab refused the sign-in ({r.status})")
    return json.loads(r.body)


def _get(http, token: str, path: str) -> object:
    r = http.request("GET", TRADER + path, {"Authorization": f"Bearer {token}"}, b"")
    if r.status == 401:
        raise PermissionError("Schwab refused the token")
    if r.status != 200:
        raise OSError(f"Schwab answered {r.status} for {path.split('?')[0]}")
    return json.loads(r.body)


def _stamp(iso: str) -> str:
    return iso[:10].replace("-", "") + "120000"


def _num(v) -> Decimal:
    """A figure as Schwab wrote it, never through a binary float (R1.9)."""
    return Decimal(str(v)) if v not in (None, "") else Decimal(0)


def _x(text) -> str:
    """Text as SGML carries it (CR3-332): `&`, `<` and `>` escaped."""
    return str(text or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _kind(inst: dict) -> tuple[str, str, str] | None:
    return KINDS.get(str(inst.get("assetType") or ""))


def _key(inst: dict) -> str:
    """How the file names a security: an option by its symbol, which a position and a trade of
    it share, else by its CUSIP, else its symbol."""
    if inst.get("assetType") == "OPTION":
        return " ".join(str(inst.get("symbol") or "?").split())
    return inst.get("cusip") or inst.get("symbol", "?")


def _secid(inst: dict) -> str:
    kind = "CUSIP" if inst.get("assetType") != "OPTION" and inst.get("cusip") else "TICKER"
    return f"<SECID><UNIQUEID>{_x(_key(inst))}<UNIQUEIDTYPE>{kind}</SECID>"


def _multiplier(inst: dict) -> int:
    """Shares per contract: Schwab's multiplier, else the standard 100."""
    for k in ("optionPremiumMultiplier", "optionMultiplier", "multiplier"):
        if inst.get(k):
            return int(_num(inst[k]))
    return 100


def _terms(inst: dict) -> tuple[str, dt.date, Decimal] | None:
    """An option's right, expiry and strike: from the instrument, else from its symbol, which
    Schwab writes as OCC does (`AAPL  261120C00150000`)."""
    m = OCC.fullmatch(str(inst.get("symbol") or "").strip())
    right = {"CALL": "CALL", "PUT": "PUT"}.get(str(inst.get("putCall") or ""))
    if right is None and m:
        right = "CALL" if m.group(3) == "C" else "PUT"
    expiry = None
    if inst.get("expirationDate"):
        expiry = dt.date.fromisoformat(str(inst["expirationDate"])[:10])
    elif m:
        expiry = dt.datetime.strptime(m.group(2), "%y%m%d").date()
    strike = _num(inst.get("strikePrice")) if inst.get("strikePrice") is not None else None
    if strike is None and m:
        strike = Decimal(int(m.group(4))) / 1000
    if right is None or expiry is None or strike is None:
        return None
    return right, expiry, strike


def _invtran(fitid: str, when: str, memo: str) -> str:
    return f"<INVTRAN><FITID>{_x(fitid)}<DTTRADE>{when}<MEMO>{_x(memo[:60])}</INVTRAN>"


def _trade(t: dict, item: dict, fitid: str, when: str, total: Decimal, fees: Decimal) -> str | None:
    """One security's leg of a trade; None when it can't be written whole: an option trade that
    says neither opening nor closing, an asset type with no OFX form."""
    inst = item.get("instrument") or {}
    kind = _kind(inst)
    qty = _num(item.get("amount"))
    if kind is None or not qty:
        return None
    side = "BUY" if qty > 0 else "SELL"
    effect = item.get("positionEffect")
    agg = kind[1]
    if agg == "OPT":
        if effect not in ("OPENING", "CLOSING"):
            return None
        to = "OPEN" if effect == "OPENING" else "CLOSE"
        typ = f"<OPT{side}TYPE>{side}TO{to}<SHPERCTRCT>{_multiplier(inst)}"
    elif agg == "STOCK":
        what = side
        if side == "BUY" and effect == "CLOSING":
            what = "BUYTOCOVER"
        elif side == "SELL" and effect == "OPENING":
            what = "SELLSHORT"
        typ = f"<{side}TYPE>{what}"
    elif agg == "MF":
        typ = f"<{side}TYPE>{side}"
    else:  # a bond: its units are the face value, its price a percentage of it
        typ = "" if side == "BUY" else "<SELLREASON>SELL"
    return (
        f"<{side}{agg}><INV{side}>{_invtran(fitid, when, t.get('description', ''))}"
        f"{_secid(inst)}<UNITS>{qty}<UNITPRICE>{_num(item.get('price'))}<COMMISSION>{fees}"
        f"<TOTAL>{total}<SUBACCTSEC>CASH<SUBACCTFUND>CASH</INV{side}>{typ}</{side}{agg}>"
    )


def _closure(t: dict, item: dict, fitid: str, when: str) -> str | None:
    """An option's end, by what Schwab says of it (S3.4); None when it says none of them."""
    inst = item.get("instrument") or {}
    said = str(t.get("description") or "").upper()
    action = next((a for word, a in ENDS if word in said), None)
    qty = abs(_num(item.get("amount")))
    if action is None or not qty:
        return None
    return (
        f"<CLOSUREOPT>{_invtran(fitid, when, t.get('description', ''))}{_secid(inst)}"
        f"<OPTACTION>{action}<UNITS>{qty}<SHPERCTRCT>{_multiplier(inst)}<SUBACCTSEC>CASH"
        "</CLOSUREOPT>"
    )


def _transfer(t: dict, item: dict, fitid: str, when: str) -> str | None:
    """Shares moved in or out with no cash (from another broker, say)."""
    inst = item.get("instrument") or {}
    qty = _num(item.get("amount"))
    if _kind(inst) is None or not qty:
        return None
    action = "IN" if qty > 0 else "OUT"
    return (
        f"<TRANSFER>{_invtran(fitid, when, t.get('description', ''))}{_secid(inst)}"
        f"<SUBACCTSEC>CASH<UNITS>{abs(qty)}<TFERACTION>{action}<POSTYPE>LONG</TRANSFER>"
    )


def _income(t: dict, inst: dict, fitid: str, when: str) -> str:
    kind = "INTEREST" if inst.get("assetType") == "FIXED_INCOME" else "DIV"
    return (
        f"<INCOME>{_invtran(fitid, when, t.get('description', ''))}{_secid(inst)}"
        f"<INCOMETYPE>{kind}<TOTAL>{_num(t.get('netAmount'))}<SUBACCTSEC>CASH"
        "<SUBACCTFUND>CASH</INCOME>"
    )


def _bank(fitid: str, when: str, trn: str, net: Decimal, memo: str) -> str:
    return (
        f"<INVBANKTRAN><STMTTRN><TRNTYPE>{trn}<DTPOSTED>{when}<TRNAMT>{net}<FITID>{_x(fitid)}"
        f"<NAME>{_x(memo[:32])}</STMTTRN><SUBACCTFUND>CASH</INVBANKTRAN>"
    )


def _margin_interest(fitid: str, when: str, net: Decimal, memo: str) -> str:
    return (
        f"<MARGININTEREST>{_invtran(fitid, when, memo)}<TOTAL>{net}<SUBACCTFUND>CASH"
        "</MARGININTEREST>"
    )


def _position(p: dict, as_of: dt.datetime) -> str | None:
    inst = p.get("instrument") or {}
    kind = _kind(inst)
    if kind is None:
        return None
    units = _num(p.get("longQuantity")) - _num(p.get("shortQuantity"))
    side = "SHORT" if units < 0 else "LONG"
    value = _num(p.get("marketValue"))
    per = _multiplier(inst) if kind[1] == "OPT" else 1
    price = Decimal(0)
    if units:
        price = value / (units * per) * (100 if kind[1] == "DEBT" else 1)
        price = price.quantize(Decimal("0.000001")).normalize()
    return (
        f"<{kind[2]}><INVPOS>{_secid(inst)}<HELDINACCT>CASH<POSTYPE>{side}<UNITS>{units}"
        f"<UNITPRICE>{price}<MKTVAL>{value}<DTPRICEASOF>{as_of:%Y%m%d%H%M%S}</INVPOS>"
        f"</{kind[2]}>"
    )


def _secinfo(inst: dict) -> str:
    kind = _kind(inst)
    tag = kind[0] if kind else "OTHERINFO"
    name = _x((inst.get("description") or inst.get("symbol") or "")[:120])
    ticker = _x(" ".join(str(inst.get("symbol") or "").split())[:32])
    info = f"<SECINFO>{_secid(inst)}<SECNAME>{name}<TICKER>{ticker}</SECINFO>"
    if tag == "OPTINFO":
        right, expiry, strike = _terms(inst) or ("CALL", dt.date(1970, 1, 1), Decimal(0))
        info += (
            f"<OPTTYPE>{right}<STRIKEPRICE>{strike}<DTEXPIRE>{expiry:%Y%m%d}"
            f"<SHPERCTRCT>{_multiplier(inst)}"
        )
    elif tag == "DEBTINFO":
        info += "<PARVALUE>1000<DEBTTYPE>COUPON"
    return f"<{tag}>{info}</{tag}>"


def _legs(t: dict) -> list[dict]:
    return [
        i
        for i in (t.get("transferItems") or [])
        if (i.get("instrument") or {}).get("assetType") != "CURRENCY"
    ]


def _rows(t: dict, fitid: str, when: str) -> list[str] | None:
    """A transaction's OFX rows; None when it can't be written whole, so it is named."""
    kind = t.get("type")
    net = _num(t.get("netAmount"))
    legs = _legs(t)
    memo = str(t.get("description") or "")
    if kind in ("TRADE", "MONEY_MARKET") and legs:
        # Each security's leg on its own row (a spread's two options); the fees, and whatever
        # else the cash differs by, go with the first leg.
        fees = sum(
            (abs(_num(x.get("cost"))) for x in (t.get("transferItems") or []) if x.get("feeType")),
            Decimal(0),
        )
        totals = [_num(x.get("cost")) for x in legs]
        if len(legs) == 1:
            totals = [net]
        else:
            totals[0] += net - sum(totals, Decimal(0))
        out = []
        for n, (leg, total) in enumerate(zip(legs, totals, strict=True)):
            row = _trade(t, leg, fitid if n == 0 else f"{fitid}-{n + 1}", when, total,
                         fees if n == 0 else Decimal(0))  # fmt: skip
            if row is None:
                return None
            out.append(row)
        return out
    if kind == "RECEIVE_AND_DELIVER" and legs:
        leg = legs[0]
        if (leg.get("instrument") or {}).get("assetType") == "OPTION":
            row = _closure(t, leg, fitid, when)
        elif net:
            # Shares delivered for cash (an assignment's or exercise's stock leg): a trade.
            row = _trade(t, leg, fitid, when, net, Decimal(0))
        else:
            row = _transfer(t, leg, fitid, when)
        return [row] if row else None
    if kind == "DIVIDEND_OR_INTEREST" and legs:
        return [_income(t, legs[0].get("instrument") or {}, fitid, when)]
    if kind == "DIVIDEND_OR_INTEREST" and net < 0 and "MARGIN" in memo.upper():
        return [_margin_interest(fitid, when, net, memo)]
    if kind == "DIVIDEND_OR_INTEREST":
        return [_bank(fitid, when, "INT", net, memo)]
    if kind in CASH_KINDS and not legs:
        return [_bank(fitid, when, CASH_KINDS[kind], net, memo)]
    if kind in NOTES and not net and not legs:
        return []
    return None


def statement(acct: dict, transactions: list[dict], as_of: dt.datetime) -> tuple[bytes, list[str]]:
    """One account's positions, balances and transactions as an OFX investment statement, and
    the transactions it couldn't write whole, each named, never dropped unsaid (S18.9.2)."""
    positions = acct.get("positions") or []
    secs: dict[str, dict] = {}
    for p in positions:
        inst = p.get("instrument") or {}
        if _kind(inst):
            secs.setdefault(_key(inst), inst)
    rows, days, left = [], [], []
    for t in transactions:
        if t.get("status") in ("INVALID", "PENDING"):
            continue
        fitid = str(t.get("activityId") or uuid.uuid4())
        when = _stamp(t.get("tradeDate") or t.get("time") or "")
        made = _rows(t, fitid, when)
        if made is None:
            left.append(f"{when[:8]} {t.get('type')}: {str(t.get('description') or '')[:60]}")
            continue
        for leg in _legs(t):
            inst = leg.get("instrument") or {}
            if _kind(inst):
                secs.setdefault(_key(inst), inst)
        rows += made
        if made:
            days.append(when[:8])
    start = min(days) if days else f"{as_of:%Y%m%d}"
    stamp = f"{as_of:%Y%m%d%H%M%S}"
    balances = acct.get("currentBalances") or {}
    cash = _num(
        next(
            (balances[k] for k in ("cashBalance", "totalCash") if balances.get(k) is not None),
            0,
        )
    )
    held = "".join(x for x in (_position(p, as_of) for p in positions) if x)
    body = (
        HEADER + "<OFX><SIGNONMSGSRSV1><SONRS><STATUS><CODE>0<SEVERITY>INFO</STATUS>"
        f"<DTSERVER>{stamp}<LANGUAGE>ENG<FI><ORG>Schwab<FID>5104</FI></SONRS>"
        "</SIGNONMSGSRSV1><INVSTMTMSGSRSV1><INVSTMTTRNRS><TRNUID>1<STATUS><CODE>0<SEVERITY>INFO"
        f"</STATUS><INVSTMTRS><DTASOF>{stamp}<CURDEF>USD<INVACCTFROM><BROKERID>schwab.com"
        f"<ACCTID>{_x(acct.get('accountNumber', ''))}</INVACCTFROM><INVTRANLIST>"
        f"<DTSTART>{start}120000<DTEND>{stamp}{''.join(rows)}</INVTRANLIST><INVPOSLIST>{held}"
        f"</INVPOSLIST><INVBAL><AVAILCASH>{cash}<MARGINBALANCE>0<SHORTBALANCE>0</INVBAL>"
        "</INVSTMTRS></INVSTMTTRNRS></INVSTMTMSGSRSV1><SECLISTMSGSRSV1><SECLIST>"
        f"{''.join(_secinfo(i) for i in secs.values())}</SECLIST></SECLISTMSGSRSV1></OFX>"
    )
    return body.encode("cp1252", "replace"), left


def to_ofx(acct: dict, transactions: list[dict], as_of: dt.datetime) -> bytes:
    """One account's positions, balances and transactions as an OFX investment statement."""
    return statement(acct, transactions, as_of)[0]


class Schwab(Driver):
    name = "schwab"
    hosts = (HOST,)
    needs = ("appSecret",)
    interval = 24 * 3600

    def __init__(self) -> None:
        # A random state for each app's sign-in, checked in the address pasted back, so an
        # address from a sign-in this connector didn't start is refused (RFC 6749 §10.12).
        self._state: dict[str, str] = {}

    def sign_in(self, settings: dict) -> str | None:
        key = settings.get("appKey")
        if not key:
            return None
        state = self._state.setdefault(key, secrets.token_urlsafe(16))
        query = urlencode({"client_id": key, "redirect_uri": REDIRECT, "state": state})
        return f"https://{HOST}/v1/oauth/authorize?{query}"

    def _tokens(self, settings: dict, creds: dict, http) -> tuple[str, dict]:
        """A usable access token, refreshing or exchanging the sign-in as needed; the
        credentials to keep (a new refresh token) come back with it."""
        now = time.time()
        if creds.get("accessToken") and now < float(creds.get("accessUntil") or 0) - 60:
            return creds["accessToken"], creds
        if creds.get("refreshToken") and now < float(creds.get("refreshUntil") or 0):
            fields = {"grant_type": "refresh_token", "refresh_token": creds["refreshToken"]}
        elif creds.get("landed"):
            back = parse_qs(urlsplit(creds["landed"]).query)
            code = back.get("code", [""])[0]
            if not code:
                raise PermissionError("the address pasted carries no sign-in code")
            if back.get("state", [""])[0] != self._state.get(settings.get("appKey") or ""):
                raise PermissionError(
                    "the address pasted back isn't from the sign-in this connector started"
                )
            fields = {"grant_type": "authorization_code", "code": code, "redirect_uri": REDIRECT}
        else:
            raise PermissionError("the sign-in has expired")
        got = _form(http, settings, creds, fields)
        fresh = bool(got.get("refresh_token"))
        kept = {
            "appSecret": creds.get("appSecret"),
            "accessToken": got["access_token"],
            "accessUntil": now + float(got.get("expires_in") or 1800),
            "refreshToken": got.get("refresh_token") or creds.get("refreshToken"),
            "refreshUntil": now + REFRESH_DAYS * 86400 if fresh else creds.get("refreshUntil"),
        }
        return kept["accessToken"], kept

    def run(
        self, settings: dict, credentials: dict | None, accounts: list[Account], http
    ) -> Result:
        try:
            token, kept = self._tokens(settings, credentials or {}, http)
            numbers = _get(http, token, "/accounts/accountNumbers")
            details = _get(http, token, "/accounts?fields=positions")
        except PermissionError as e:
            return Result("needs-sign-in", str(e), sign_in=self.sign_in(settings))
        by_last4, found = {}, []
        for entry in details:
            acct = entry.get("securitiesAccount") or {}
            number = str(acct.get("accountNumber") or "")
            found.append({"name": str(acct.get("type") or "Account").title(), "last4": number[-4:]})
            by_last4[number[-4:]] = acct
        hashes = {str(n.get("accountNumber"))[-4:]: n.get("hashValue") for n in numbers}
        as_of = dt.datetime.now(dt.UTC)
        since = as_of - dt.timedelta(days=int(settings.get("days") or 45))
        window = urlencode(
            {
                "startDate": since.strftime("%Y-%m-%dT00:00:00.000Z"),
                "endDate": as_of.strftime("%Y-%m-%dT%H:%M:%S.000Z"),
            }
        )
        files, left = [], []
        for a in accounts:
            acct, h = by_last4.get(a.last4 or ""), hashes.get(a.last4 or "")
            if acct is None or not h:
                continue
            txns = _get(http, token, f"/accounts/{h}/transactions?{window}")
            name = f"schwab-{as_of:%Y-%m-%d}.ofx"
            data, skipped = statement(acct, txns, as_of)
            files.append(File(a.id, name, data, "ofx"))
            left += [f"••{a.last4} {x}" for x in skipped]
        message = f"{len(files)} statement{'s' if len(files) != 1 else ''}"
        if left:
            # What couldn't be written whole is named, never dropped unsaid (S18.9.2).
            n = len(left)
            message += f"; {n} transaction{'s' if n != 1 else ''} left out: " + "; ".join(left)
        return Result("ok", message[:200], found=found, files=files, credentials=kept)
