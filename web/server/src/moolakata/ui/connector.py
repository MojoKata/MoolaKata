"""Settings › Connector (requirements S16.18, S18.4): pairing with the MoolaKata Connector,
whether it is locked, its last report, and every Connection's state, owner and accounts, never
their credentials."""

import datetime as dt
import json

from fastapi import APIRouter, Depends, Request
from sqlalchemy import false, select

from ..connector import manage
from ..connector.manage import ConnectorError
from ..errors import Problem, refuse
from ..links import keys
from ..store.entities.accounts import Account
from ..store.entities.connector import Connection
from ..store.entities.users import User
from .conventions import ExactRoute, Model
from .deps import Caller, admin, recent_auth, server

router = APIRouter(prefix="/ui/api", route_class=ExactRoute, tags=["connector"])


class InstitutionAccount(Model):
    name: str
    last4: str | None


class SyncedAccount(Model):
    id: str
    name: str
    syncAccount: str | None


class ConnectionOut(Model):
    id: str
    ownerId: str
    ownerName: str
    driver: str
    label: str
    state: str  # new, ok, needs-sign-in, failing, removed
    message: str | None
    lastRunAt: dt.datetime | None
    lastRunAdded: int | None
    institutionAccounts: list[InstitutionAccount]
    accounts: list[SyncedAccount]
    credentialWaiting: bool  # sealed for the connector, not yet collected
    signInAddress: str | None
    signInHost: str | None = None  # shown on the button, so the page is known (S18.7.1)
    createdAt: dt.datetime
    version: int


class ConnectorOut(Model):
    state: str  # none, pairing, paired
    fingerprint: str | None  # the connector's, four groups of four
    serverFingerprint: str  # this server's link key's
    sealingKey: str | None  # base64url, for the browser to seal credentials to (S18.7.1)
    locked: bool
    pairedAt: dt.datetime | None
    pairedBy: str | None
    confirmedAt: dt.datetime | None  # an admin compared the fingerprints (S18.4.3)
    confirmedBy: str | None
    lastAddress: str | None  # where its reports come from (S18.2.4.4)
    knownAddress: str | None  # the address admins accepted; a difference is alerted
    newAddress: str | None  # one it reported from that no admin has accepted (S18.5.4)
    lastReportAt: dt.datetime | None
    page: str | None  # the connector's own page, from its reports (S18.11.1)
    silentForSeconds: int | None  # past the 15 minutes allowed
    connectorVersion: str | None
    codeExpiresAt: dt.datetime | None  # while a pairing code is out
    connections: list[ConnectionOut]


class PairingOut(Model):
    code: str  # shown once
    expiresAt: dt.datetime
    command: str  # what to run on the connector's host


def _host(address: str | None) -> str | None:
    from urllib.parse import urlsplit

    return urlsplit(address).hostname if address else None


def connection_out(s, c: Connection) -> ConnectionOut:
    owner = s.get(User, c.ownerId)
    return ConnectionOut(
        id=c.id,
        ownerId=c.ownerId,
        ownerName=owner.displayName if owner else "?",
        driver=c.driver,
        label=c.label,
        state=c.state,
        message=c.message,
        lastRunAt=c.lastRunAt,
        lastRunAdded=c.lastRunAdded,
        institutionAccounts=[
            InstitutionAccount(name=x.get("name", ""), last4=x.get("last4"))
            for x in json.loads(c.institutionAccounts or "[]")
        ],
        accounts=[
            SyncedAccount(id=a.id, name=a.name, syncAccount=a.syncAccount)
            for a in s.scalars(
                select(Account)
                .where(Account.connectionId == c.id, Account.deleted == false())
                .order_by(Account.name)
            )
        ],
        credentialWaiting=bool(c.sealedCredential),
        signInAddress=c.signInAddress,
        signInHost=_host(c.signInAddress),
        createdAt=c.createdAt,
        version=c.version,
    )


def view(s, srv) -> ConnectorOut:
    row = manage.current(s)
    own = keys.short(keys.fingerprint(keys.public_of(s, srv.keys.secrets)))
    if row is None:
        return ConnectorOut(
            state="none",
            fingerprint=None,
            serverFingerprint=own,
            sealingKey=None,
            locked=True,
            pairedAt=None,
            pairedBy=None,
            confirmedAt=None,
            confirmedBy=None,
            lastAddress=None,
            knownAddress=None,
            newAddress=None,
            lastReportAt=None,
            page=None,
            silentForSeconds=None,
            connectorVersion=None,
            codeExpiresAt=None,
            connections=[],
        )
    by = s.get(User, row.pairedById) if row.pairedById else None
    confirmed_by = s.get(User, row.confirmedById) if row.confirmedById else None
    silent = manage.silent_for(row)
    connections = s.scalars(
        select(Connection)
        .where(
            Connection.connectorId == row.id,
            Connection.deleted == false(),
            Connection.state != "removed",
        )
        .order_by(Connection.createdAt)
    ).all()
    return ConnectorOut(
        state=row.state,
        fingerprint=keys.short(keys.fingerprint(keys.unb64(row.actionKey)))
        if row.actionKey
        else None,
        serverFingerprint=own,
        sealingKey=row.sealingKey,
        locked=row.locked,
        pairedAt=row.pairedAt,
        pairedBy=by.displayName if by else None,
        confirmedAt=row.confirmedAt,
        confirmedBy=confirmed_by.displayName if confirmed_by else None,
        lastAddress=row.lastAddress,
        knownAddress=row.knownAddress,
        newAddress=row.newAddress,
        lastReportAt=row.lastReportAt,
        page=row.pageAddress,
        silentForSeconds=int(silent.total_seconds()) if silent else None,
        connectorVersion=row.connectorVersion,
        codeExpiresAt=row.codeExpiresAt if row.state == "pairing" else None,
        connections=[connection_out(s, c) for c in connections],
    )


@router.get("/settings/connector", response_model=ConnectorOut)
def get_connector(request: Request, c: Caller = Depends(admin)):
    srv = server(request)
    with srv.db.tx() as s:
        return view(s, srv)


@router.post("/settings/connector/pairings", response_model=PairingOut, status_code=201)
def pair(request: Request, c: Caller = Depends(admin)):
    """Pair (S18.4.1): a one-time code, valid 24 hours, shown once; the password again if given
    over 10 minutes ago (S13.7.2)."""
    recent_auth(c)
    srv = server(request)
    try:
        row, code = manage.pair_code(srv, c.id)
    except ConnectorError as e:
        raise refuse(None, e.code, e.message) from None
    return PairingOut(
        code=code,
        expiresAt=row.codeExpiresAt,
        command=f"docker compose exec connector moolakata-connector pair {code}",
    )


@router.post("/settings/connector/confirm", response_model=ConnectorOut)
def confirm(request: Request, c: Caller = Depends(admin)):
    """Confirm (S18.4.3): the admin compared the fingerprint both sides show. Until then the
    connector gets no sealed credential and posts no file. The password again (S13.7.2)."""
    recent_auth(c)
    srv = server(request)
    if not manage.confirm(srv, c.id):
        raise Problem(404, "not-found", "No connector is paired.")
    with srv.db.tx() as s:
        return view(s, srv)


@router.post("/settings/connector/accept-address", response_model=ConnectorOut)
def accept_address(request: Request, c: Caller = Depends(admin)):
    """Accept (S18.2.4.4): the address the connector now reports from is its own. The
    password again (S13.7.2)."""
    recent_auth(c)
    srv = server(request)
    if not manage.accept_address(srv, c.id):
        raise Problem(404, "not-found", "No connector is paired.")
    srv.tasks.run_now("alerts")
    with srv.db.tx() as s:
        return view(s, srv)


@router.post("/settings/connector/unpair", response_model=ConnectorOut)
def unpair(request: Request, c: Caller = Depends(admin)):
    """Unpair (S18.4.4): the connector's key is refused from then on, every Connection stops
    and every account's sync turns off."""
    recent_auth(c)
    srv = server(request)
    if not manage.unpair(srv, c.id):
        raise Problem(404, "not-found", "No connector is paired.")
    with srv.db.tx() as s:
        return view(s, srv)
