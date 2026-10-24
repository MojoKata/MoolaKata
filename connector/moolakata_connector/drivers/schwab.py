"""Schwab (requirements S18.9.2): the Trader API, signed in on Schwab's own page. The owner
opens the sign-in address the driver reports, signs in, and seals the address they land on
(with the app's secret) for the connector; the driver exchanges its code for tokens and
keeps the refresh token in the vault. That token lasts seven days, so the Connection asks for
a sign-in every week. Positions, transactions and balances are posted as OFX, one file per
account, which MoolaKata imports as a broker's download."""

import base64
import datetime as dt
import json
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
SEC_KINDS = {
    "EQUITY": "STOCKINFO",
    "ETF": "STOCKINFO",
    "MUTUAL_FUND": "MFINFO",
    "OPTION": "OPTINFO",
    "FIXED_INCOME": "DEBTINFO",
}
CASH_KINDS = {
    "ELECTRONIC_FUND": "XFER",
    "JOURNAL": "XFER",
    "CASH_RECEIPT": "CREDIT",
    "CASH_DISBURSEMENT": "DEBIT",
    "WIRE_IN": "CREDIT",
    "WIRE_OUT": "DEBIT",
}
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


def _secid(inst: dict) -> str:
    cusip = inst.get("cusip")
    key, kind = (cusip, "CUSIP") if cusip else (inst.get("symbol", "?"), "TICKER")
    return f"<SECID><UNIQUEID>{key}<UNIQUEIDTYPE>{kind}</SECID>"


def _key(inst: dict) -> str:
    return inst.get("cusip") or inst.get("symbol", "?")


def _invtran(fitid: str, when: str, memo: str) -> str:
    return f"<INVTRAN><FITID>{fitid}<DTTRADE>{when}<MEMO>{memo[:60]}</INVTRAN>"


def _trade(t: dict, item: dict, fitid: str, when: str) -> str:
    inst = item.get("instrument") or {}
    qty = _num(item.get("amount"))
    fees = sum(abs(_num(x.get("cost"))) for x in (t.get("transferItems") or []) if x.get("feeType"))
    opt = inst.get("assetType") == "OPTION"
    side = "BUY" if qty > 0 else "SELL"
    tag = f"{side}OPT" if opt else f"{side}STOCK"
    typ = (
        f"<OPT{side}TYPE>{'BUYTOOPEN' if qty > 0 else 'SELLTOCLOSE'}"
        if opt
        else f"<{side}TYPE>{side}"
    )
    return (
        f"<{tag}><INV{side}>{_invtran(fitid, when, t.get('description', ''))}{_secid(inst)}"
        f"<UNITS>{qty}<UNITPRICE>{_num(item.get('price'))}<COMMISSION>{fees}"
        f"<TOTAL>{_num(t.get('netAmount'))}<SUBACCTSEC>CASH<SUBACCTFUND>CASH</INV{side}>"
        f"{typ}</{tag}>"
    )


def _income(t: dict, inst: dict, fitid: str, when: str) -> str:
    return (
        f"<INCOME>{_invtran(fitid, when, t.get('description', ''))}{_secid(inst)}"
        f"<INCOMETYPE>DIV<TOTAL>{_num(t.get('netAmount'))}<SUBACCTSEC>CASH<SUBACCTFUND>CASH"
        "</INCOME>"
    )


def _bank(fitid: str, when: str, trn: str, net: float, memo: str) -> str:
    return (
        f"<INVBANKTRAN><STMTTRN><TRNTYPE>{trn}<DTPOSTED>{when}<TRNAMT>{net}<FITID>{fitid}"
        f"<NAME>{memo[:32]}</STMTTRN><SUBACCTFUND>CASH</INVBANKTRAN>"
    )


def _position(p: dict, as_of: dt.datetime) -> str:
    inst = p.get("instrument") or {}
    units = _num(p.get("longQuantity")) - _num(p.get("shortQuantity"))
    side = "SHORT" if _num(p.get("shortQuantity")) else "LONG"
    return (
        f"<POSSTOCK><INVPOS>{_secid(inst)}<HELDINACCT>CASH<POSTYPE>{side}<UNITS>{units}"
        f"<UNITPRICE>{_num(p.get('averagePrice'))}<MKTVAL>{_num(p.get('marketValue'))}"
        f"<DTPRICEASOF>{as_of:%Y%m%d%H%M%S}</INVPOS></POSSTOCK>"
    )


def _secinfo(inst: dict) -> str:
    tag = SEC_KINDS.get(inst.get("assetType"), "OTHERINFO")
    name = (inst.get("description") or inst.get("symbol") or "")[:120]
    return (
        f"<{tag}><SECINFO>{_secid(inst)}<SECNAME>{name}<TICKER>{inst.get('symbol', '')}"
        f"</SECINFO></{tag}>"
    )


def to_ofx(acct: dict, transactions: list[dict], as_of: dt.datetime) -> bytes:
    """One account's positions, balances and transactions as an OFX investment statement."""
    positions = acct.get("positions") or []
    secs: dict[str, dict] = {
        _key(p.get("instrument") or {}): p.get("instrument") or {} for p in positions
    }
    rows, days = [], []
    for t in transactions:
        kind = t.get("type")
        items = [
            i
            for i in (t.get("transferItems") or [])
            if (i.get("instrument") or {}).get("assetType") != "CURRENCY"
        ]
        fitid = str(t.get("activityId") or uuid.uuid4())
        when = _stamp(t.get("time") or t.get("tradeDate") or "")
        net = _num(t.get("netAmount"))
        inst = (items[0].get("instrument") or {}) if items else {}
        if kind == "TRADE" and items:
            secs.setdefault(_key(inst), inst)
            rows.append(_trade(t, items[0], fitid, when))
        elif kind == "DIVIDEND_OR_INTEREST" and inst:
            secs.setdefault(_key(inst), inst)
            rows.append(_income(t, inst, fitid, when))
        elif kind == "DIVIDEND_OR_INTEREST":
            rows.append(_bank(fitid, when, "INT", net, t.get("description", "")))
        elif kind in CASH_KINDS:
            rows.append(_bank(fitid, when, CASH_KINDS[kind], net, t.get("description", "")))
        else:
            continue
        days.append(when[:8])
    start = min(days) if days else f"{as_of:%Y%m%d}"
    stamp = f"{as_of:%Y%m%d%H%M%S}"
    cash = _num((acct.get("currentBalances") or {}).get("cashBalance"))
    return (
        HEADER + "<OFX><SIGNONMSGSRSV1><SONRS><STATUS><CODE>0<SEVERITY>INFO</STATUS>"
        f"<DTSERVER>{stamp}<LANGUAGE>ENG<FI><ORG>Schwab<FID>5104</FI></SONRS>"
        "</SIGNONMSGSRSV1><INVSTMTMSGSRSV1><INVSTMTTRNRS><TRNUID>1<STATUS><CODE>0<SEVERITY>INFO"
        f"</STATUS><INVSTMTRS><DTASOF>{stamp}<CURDEF>USD<INVACCTFROM><BROKERID>schwab.com"
        f"<ACCTID>{acct.get('accountNumber', '')}</INVACCTFROM><INVTRANLIST><DTSTART>{start}120000"
        f"<DTEND>{stamp}{''.join(rows)}</INVTRANLIST><INVPOSLIST>"
        f"{''.join(_position(p, as_of) for p in positions)}</INVPOSLIST><INVBAL><AVAILCASH>{cash}"
        "<MARGINBALANCE>0<SHORTBALANCE>0</INVBAL></INVSTMTRS></INVSTMTTRNRS></INVSTMTMSGSRSV1>"
        f"<SECLISTMSGSRSV1><SECLIST>{''.join(_secinfo(i) for i in secs.values())}</SECLIST>"
        "</SECLISTMSGSRSV1></OFX>"
    ).encode("latin-1", "replace")


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
        files = []
        for a in accounts:
            acct, h = by_last4.get(a.last4 or ""), hashes.get(a.last4 or "")
            if acct is None or not h:
                continue
            txns = _get(http, token, f"/accounts/{h}/transactions?{window}")
            name = f"schwab-{as_of:%Y-%m-%d}.ofx"
            files.append(File(a.id, name, to_ofx(acct, txns, as_of), "ofx"))
        message = f"{len(files)} statement{'s' if len(files) != 1 else ''}"
        return Result("ok", message, found=found, files=files, credentials=kept)
