"""Alerts (requirements S12.11): the screen's list, seen and dismissed, and the navigation's
counts, which the live stream asks for again when an alert opens."""

import datetime as dt

from fastapi import APIRouter, Depends, Request
from fastapi.responses import Response

from .. import alerts
from ..errors import Problem
from ..store.entities.users import User
from .conventions import ExactRoute, Model
from .deps import Caller, caller, server

router = APIRouter(prefix="/ui/api", route_class=ExactRoute, tags=["alerts"])


class AlertRow(Model):
    id: str
    kind: str
    title: str
    about: str
    link: str | None
    fix: str | None
    icon: str
    openedAt: dt.datetime
    resolvedAt: dt.datetime | None
    resolution: str | None
    forAdmins: bool
    seen: bool


class AlertList(Model):
    open: list[AlertRow]
    resolved: list[AlertRow]
    emails: str


@router.get("/alerts", response_model=AlertList)
def list_alerts(request: Request, c: Caller = Depends(caller)):
    """Open alerts first, newest first, then those resolved in the last 90 days; an alert
    the caller dismissed is left out."""
    with server(request).db.read(user=c.id) as s:
        rows = [
            AlertRow(
                id=a.id,
                kind=a.kind,
                title=a.title,
                about=a.about,
                link=a.link,
                fix=a.fix,
                icon=a.icon,
                openedAt=a.openedAt,
                resolvedAt=a.resolvedAt,
                resolution=a.resolution,
                forAdmins=a.userId is None,
                seen=st is not None and st.seenAt is not None,
            )
            for a, st in s.execute(alerts.visible(s, c.id, c.admin)).all()
            if st is None or st.dismissedAt is None or a.resolvedAt is not None
        ]
        emails = s.get(User, c.id).alertEmails
    return AlertList(
        open=[r for r in rows if r.resolvedAt is None],
        resolved=sorted(
            (r for r in rows if r.resolvedAt is not None),
            key=lambda r: r.resolvedAt,
            reverse=True,
        ),
        emails=emails,
    )


@router.post("/alerts/seen", status_code=204)
def seen(request: Request, c: Caller = Depends(caller)):
    """Opening the screen marks the caller's alerts as seen, which clears the badge."""
    srv = server(request)
    with srv.db.tx(user=c.id) as s:
        alerts.mark_seen(s, c.id, c.admin)
    srv.events.publish("badges", {}, users=[c.id])
    return Response(status_code=204)


@router.post("/alerts/{alert_id}/dismiss", status_code=204)
def dismiss(alert_id: str, request: Request, c: Caller = Depends(caller)):
    """Dismissed for the caller alone; it stays open for anyone else it is for."""
    srv = server(request)
    with srv.db.tx(user=c.id) as s:
        if not alerts.dismiss(s, c.id, c.admin, alert_id):
            raise Problem(404, "not-found", "That alert is not open for you.")
    srv.events.publish("badges", {}, users=[c.id])
    return Response(status_code=204)


@router.get("/badges", response_model=dict[str, int])
def badges(request: Request, c: Caller = Depends(caller)):
    return server(request).badges(c)
