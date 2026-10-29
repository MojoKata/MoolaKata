"""Alerts (requirements S12.11)."""

import datetime as dt

import pytest
from conftest import make_user, sign_in
from edits import make

from moolakata import alerts, clock, ids, settings
from moolakata.store.entities.accounts import Account, Import
from moolakata.store.entities.core import TaskRun
from moolakata.store.entities.prices import PriceSource

T0 = dt.datetime(2026, 10, 13, 12, 0, tzinfo=dt.UTC)


@pytest.fixture
def frozen():
    clock.fix(T0)
    yield
    clock.fix(None)


def at(**kw) -> None:
    clock.fix(T0 + dt.timedelta(**kw))


def failing_source(server, ok_hours_ago: float, error="Tiingo refused the key (HTTP 401)"):
    with server.db.tx() as s:
        s.add(
            PriceSource(
                id=ids.new_id("Src"),
                name="tiingo",
                enabled=True,
                lastOkAt=clock.now() - dt.timedelta(hours=ok_hours_ago),
                lastError=error,
            )
        )


def set_source_error(server, error):
    from sqlalchemy import select

    with server.db.tx() as s:
        src = s.scalars(select(PriceSource)).one()
        src.lastError = error
        if error is None:
            src.lastOkAt = clock.now()


def listed(c) -> dict:
    r = c.get("/ui/api/alerts")
    assert r.status_code == 200, r.text
    return r.json()


def test_a_failing_source_alerts_admins_after_the_threshold(server, admin_client, frozen):
    with server.db.tx() as s:
        settings.put(s, "sessionIdleHours", 168, None)
    alice = make_user(server, "alice")
    failing_source(server, ok_hours_ago=10)
    assert alerts.evaluate(server) == []
    assert listed(admin_client)["open"] == [], "not before 48 hours"
    at(hours=39)
    opened = alerts.evaluate(server)
    assert [a.title for a in opened] == ["Tiingo failing for 2 days"]
    rows = listed(admin_client)["open"]
    assert rows[0]["forAdmins"] and rows[0]["link"] == "/ui/settings/prices"
    assert admin_client.get("/ui/api/badges").json() == {"alerts": 1}
    assert listed(sign_in(server, "alice"))["open"] == [], f"not for {alice.username}"
    # It stays one alert, however often the source fails again.
    at(hours=60)
    assert alerts.evaluate(server) == []
    assert len(listed(admin_client)["open"]) == 1
    # The source answers again: resolved by itself.
    set_source_error(server, None)
    alerts.evaluate(server)
    body = listed(admin_client)
    assert body["open"] == [] and body["resolved"][0]["resolution"] == "the cause cleared"
    assert admin_client.get("/ui/api/badges").json() == {}


def test_the_threshold_is_a_setting(server, admin_client, frozen):
    with server.db.tx() as s:
        settings.put(s, "alertSourceHours", 6, None)
    failing_source(server, ok_hours_ago=7)
    assert len(alerts.evaluate(server)) == 1


def test_a_failed_backup_alerts_at_once_and_resolves(server, admin_client, frozen):
    with server.db.tx() as s:
        s.add(TaskRun(name="backups", startedAt=T0, finishedAt=T0, error="disk full"))
    assert [a.title for a in alerts.evaluate(server)] == ["Backup failed"]
    with server.db.tx() as s:
        s.get(TaskRun, "backups").error = None
    alerts.evaluate(server)
    assert listed(admin_client)["open"] == []


def test_an_overdue_statement_alerts_the_accounts_owner(server, admin_client, frozen):
    alice = make_user(server, "alice")
    with server.db.tx() as s:
        a = Account(
            id=ids.new_id("Acct"),
            ownerId=alice.id,
            name="Joint Household",
            type="checking",
            keptBy='["file"]',
        )
        s.add(a)
        s.flush()
        s.add(
            Import(
                id=ids.new_id("Imprt"),
                accountId=a.id,
                userId=alice.id,
                format="ofx",
                fileName="aug.ofx",
                fileHash="x",
                coveredFrom=dt.date(2026, 7, 26),
                coveredTo=dt.date(2026, 8, 25),
            )
        )
    # Due Sep 25, overdue from Oct 10 after 15 days' grace; today is Oct 13.
    alerts.evaluate(server)
    c = sign_in(server, "alice")
    rows = listed(c)["open"]
    assert [r["title"] for r in rows] == ["Joint Household: the September statement is overdue"]
    assert rows[0]["about"] == "monthly statements · the last ended Aug 25 · overdue from Oct 10"
    assert not rows[0]["forAdmins"]
    assert listed(admin_client)["open"] == [], "an admin never sees someone's account"
    # A statement covering it clears it; one kept without reading counts.
    with server.db.tx() as s:
        s.add(
            Import(
                id=ids.new_id("Imprt"),
                accountId=a.id,
                userId=alice.id,
                format="kept",
                fileName="sep.pdf",
                fileHash="y",
                coveredFrom=dt.date(2026, 8, 26),
                coveredTo=dt.date(2026, 9, 25),
            )
        )
    alerts.evaluate(server)
    assert listed(c)["open"] == []


def test_seen_and_dismissed_are_each_persons_own(server, admin_client, frozen):
    make_user(server, "root2", admin=True)
    other = sign_in(server, "root2")
    with server.db.tx() as s:
        s.add(TaskRun(name="backups", startedAt=T0, finishedAt=T0, error="disk full"))
    alerts.evaluate(server)
    assert admin_client.post("/ui/api/alerts/seen").status_code == 204
    assert admin_client.get("/ui/api/badges").json() == {}
    assert other.get("/ui/api/badges").json() == {"alerts": 1}
    aid = listed(other)["open"][0]["id"]
    assert other.post(f"/ui/api/alerts/{aid}/dismiss").status_code == 204
    assert listed(other)["open"] == []
    assert len(listed(admin_client)["open"]) == 1
    assert other.post(f"/ui/api/alerts/{aid}/dismiss").status_code == 404


def test_the_phrase_check_comes_due_after_a_year(server, admin_client, frozen):
    created = server.store.keys.ring.master_created
    clock.fix(created + dt.timedelta(days=364))
    assert alerts.evaluate(server) == []
    clock.fix(created + dt.timedelta(days=366))
    assert sorted(a.kind for a in alerts.evaluate(server)) == ["key-rotation", "phrase-check"]
    # S15.6.5: every unlock is a check as well, so one resolves it.
    from moolakata import activity

    with server.db.tx() as s:
        activity.record(s, "key.unlocked", actor=None, for_admins=True)
    alerts.evaluate(server)
    from moolakata.store.entities.alerts import Alert

    with server.db.read() as s:
        still = {a.kind for a in s.query(Alert).filter(Alert.resolvedAt.is_(None))}
    assert still == {"key-rotation"}


def test_the_rotation_reminder_follows_its_setting(server, admin_client, frozen):
    # N15: due after the period Settings › Key storage sets (S15.8.4); off, never.
    created = server.store.keys.ring.master_created
    with server.db.tx() as s:
        settings.put(s, "keyReminderMonths", 6, None)
    clock.fix(created + dt.timedelta(days=190))
    assert [a.kind for a in alerts.evaluate(server)] == ["key-rotation"]
    with server.db.tx() as s:
        settings.put(s, "keyReminderMonths", 0, None)
    assert alerts.evaluate(server) == []


def test_an_option_expiring_within_a_week_and_a_pledge_due(server, frozen):
    # N15: to the account's owner, and to the organisation's (S12.11.1.3, S7.9.5).
    from test_accounts import new_account
    from test_options import opt

    make_user(server, "alice")
    c = sign_in(server, "alice")
    brk = new_account(c, name="Brokerage", type="brokerage")
    opt(c, brk["id"], "sell-to-open", "2026-10-01", "1.00", expiry="2026-10-16", fees="0")
    org = make(c, "Orgzn", name="Food Bank", deductible=True, pledge="50.00", pledgeEvery="month")
    assert org.status_code == 200, org.text
    titles = sorted(a.title for a in alerts.evaluate(server))
    assert titles == ["MSFT 16OCT26 480 P expires in 3 days"], titles
    at(days=13)  # Oct 26: the month's pledge is due; the option has expired
    assert "pledge-due" in [a.kind for a in alerts.evaluate(server)]
    from moolakata.store.entities.alerts import Alert

    with server.db.read() as s:
        open_ = {a.kind for a in s.query(Alert).filter(Alert.resolvedAt.is_(None))}
    assert "option-expiring" not in open_ and "pledge-due" in open_


def _outbox_subjects(server) -> list[str]:
    return [w.subject for w in server.services.mailer.waiting()]


def test_each_alert_is_emailed_once_when_smtp_is_set(server, admin_client, frozen):
    with server.db.tx() as s:
        s.add(TaskRun(name="backups", startedAt=T0, finishedAt=T0, error="disk full"))
    alerts.evaluate(server)
    assert _outbox_subjects(server) == [], "no SMTP: nothing is sent"
    with server.db.tx() as s:
        s.get(TaskRun, "backups").error = None
    alerts.evaluate(server)
    with server.db.tx() as s:
        settings.put(s, "smtpHost", "smtp.home.lan", None)
        s.get(TaskRun, "backups").error = "disk full again"
    alerts.evaluate(server)
    alerts.evaluate(server)
    assert _outbox_subjects(server) == ["MoolaKata alert: Backup failed"]


def test_the_daily_summary_goes_once_a_day_after_its_time(server, frozen):
    alice = make_user(server, "alice")
    with server.db.tx() as s:
        settings.put(s, "smtpHost", "smtp.home.lan", None)
        a = Account(
            id=ids.new_id("Acct"),
            ownerId=alice.id,
            name="Savings",
            type="savings",
            keptBy='["file"]',
        )
        s.add(a)
        s.flush()
        s.add(
            Import(
                id=ids.new_id("Imprt"),
                accountId=a.id,
                userId=alice.id,
                format="csv",
                fileName="a.csv",
                fileHash="y",
                coveredTo=dt.date(2026, 8, 1),
            )
        )
    alerts.evaluate(server)
    # 12:00 UTC is 08:00 in New York, past the 07:00 default.
    with server.db.tx() as s:
        from moolakata.store.entities.users import User

        s.get(User, alice.id).timeZone = "America/New_York"
    assert alerts.daily_summaries(server) == 1
    assert alerts.daily_summaries(server) == 0, "once a day"
    assert _outbox_subjects(server)[-1] == "MoolaKata: 1 new alert"
    at(days=1)
    assert alerts.daily_summaries(server) == 0, "none on a day without new alerts"


def test_reading_without_its_file_sandbox_alerts_admins(server, admin_client, frozen):
    # S9.8.4.2: a host without Landlock keeps reading on, and admins are told while it lasts.
    from moolakata import parsing

    alerts.evaluate(server)
    assert listed(admin_client)["open"] == []
    parsing.PINNED = False
    alerts.evaluate(server)
    (a,) = listed(admin_client)["open"]
    assert a["title"] == "Reading runs without its file sandbox"
    assert a["link"] == "/ui/settings/receipts" and "Landlock" in a["about"]
    parsing.PINNED = True
    alerts.evaluate(server)
    assert listed(admin_client)["open"] == []


def test_every_check_names_the_kinds_it_keeps_when_it_fails():
    assert {fn.__name__ for fn in alerts.CHECKS} == set(alerts._KINDS)


def test_a_check_that_fails_leaves_its_alerts_open_and_unsent(server, admin_client, frozen):
    with server.db.tx() as s:
        s.add(TaskRun(name="backups", startedAt=T0, finishedAt=T0, error="disk full"))
    alerts.evaluate(server)
    before = [a["title"] for a in listed(admin_client)["open"]]
    assert before == ["Backup failed"]
    with server.db.tx() as s:
        s.get(TaskRun, "backups").error = None

    def broken(s, server):
        raise RuntimeError("a check that can't run")
        yield

    i = next(i for i, fn in enumerate(alerts.CHECKS) if fn.__name__ == "backups")
    keep = alerts.CHECKS[i]
    broken.__name__ = "backups"
    alerts.CHECKS[i] = broken
    try:
        assert alerts.evaluate(server) == []  # nothing reopened, so nothing sent again
    finally:
        alerts.CHECKS[i] = keep
    assert [a["title"] for a in listed(admin_client)["open"]] == before
    alerts.evaluate(server)  # the check runs again: the backup is fixed
    assert listed(admin_client)["open"] == []


def test_a_holding_valued_from_an_old_statement_alerts_its_owner(server, frozen):
    # S4.3, S12.11.1.2: a holding valued from a statement more than 90 days old.
    from test_accounts import new_account

    from moolakata.store.entities.accounts import Holding, Instrument

    with server.db.tx() as s:
        settings.put(s, "sessionIdleHours", 168, None)
    make_user(server, "alice")
    c = sign_in(server, "alice")
    acct = new_account(c, name="Plan", type="brokerage")
    with server.db.tx() as s:
        fund = Instrument(id=ids.new_id("Instr"), symbol="XFUNDZ", instrumentClass="mutual-fund")
        s.add(fund)
        s.flush()
        s.add(
            Holding(
                id=ids.new_id("Hold"),
                accountId=acct["id"],
                instrumentId=fund.id,
                asOf=(T0 - dt.timedelta(days=89)).date(),
                quantity=10,
                marketValue=1000,
            )
        )
    alerts.evaluate(server)
    assert [a["kind"] for a in listed(c)["open"]] == []
    at(days=2)
    alerts.evaluate(server)
    (a,) = [a for a in listed(c)["open"] if a["kind"] == "statement-value-old"]
    assert a["title"] == "Plan: a holding is valued from a statement over 90 days old"
    assert a["link"] == f"/ui/accounts/{acct['id']}/holdings"
