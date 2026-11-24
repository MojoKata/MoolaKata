"""Alerts (requirements S12.11)."""

import contextlib
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
    with server.db.tx(unscoped="test") as s:
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

    with server.db.tx(unscoped="test") as s:
        src = s.scalars(select(PriceSource)).one()
        src.lastError = error
        if error is None:
            src.lastOkAt = clock.now()


def listed(c) -> dict:
    r = c.get("/ui/api/alerts")
    assert r.status_code == 200, r.text
    return r.json()


def test_a_failing_source_alerts_admins_after_the_threshold(server, admin_client, frozen):
    with server.db.tx(unscoped="test") as s:
        settings.put(s, "sessionIdleHours", 168, None)
    jane = make_user(server, "jane")
    failing_source(server, ok_hours_ago=10)
    assert alerts.evaluate(server) == []
    assert listed(admin_client)["open"] == [], "not before 48 hours"
    at(hours=39)
    opened = alerts.evaluate(server)
    assert [a.title for a in opened] == ["Tiingo failing for 2 days"]
    rows = listed(admin_client)["open"]
    assert rows[0]["forAdmins"] and rows[0]["link"] == "/ui/settings/prices"
    assert admin_client.get("/ui/api/badges").json() == {"alerts": 1}
    assert listed(sign_in(server, "jane"))["open"] == [], f"not for {jane.username}"
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
    with server.db.tx(unscoped="test") as s:
        settings.put(s, "alertSourceHours", 6, None)
    failing_source(server, ok_hours_ago=7)
    assert len(alerts.evaluate(server)) == 1


def test_a_failed_backup_alerts_at_once_and_resolves(server, admin_client, frozen):
    with server.db.tx(unscoped="test") as s:
        s.add(TaskRun(name="backups", startedAt=T0, finishedAt=T0, error="disk full"))
    assert [a.title for a in alerts.evaluate(server)] == ["Backup failed"]
    with server.db.tx(unscoped="test") as s:
        s.get(TaskRun, "backups").error = None
    alerts.evaluate(server)
    assert listed(admin_client)["open"] == []


def test_an_overdue_statement_alerts_the_accounts_owner(server, admin_client, frozen):
    jane = make_user(server, "jane")
    with server.db.tx(unscoped="test") as s:
        a = Account(
            id=ids.new_id("Acct"),
            ownerId=jane.id,
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
                userId=jane.id,
                format="ofx",
                fileName="aug.ofx",
                fileHash="x",
                coveredFrom=dt.date(2026, 7, 26),
                coveredTo=dt.date(2026, 8, 25),
            )
        )
    # Due Sep 25, overdue from Oct 10 after 15 days' grace; today is Oct 13.
    alerts.evaluate(server)
    c = sign_in(server, "jane")
    rows = listed(c)["open"]
    assert [r["title"] for r in rows] == ["Joint Household: the September statement is overdue"]
    assert rows[0]["about"] == "monthly statements · the last ended Aug 25 · overdue from Oct 10"
    assert not rows[0]["forAdmins"]
    assert listed(admin_client)["open"] == [], "an admin never sees someone's account"
    # A statement covering it clears it; one kept without reading counts.
    with server.db.tx(unscoped="test") as s:
        s.add(
            Import(
                id=ids.new_id("Imprt"),
                accountId=a.id,
                userId=jane.id,
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
    with server.db.tx(unscoped="test") as s:
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

    with server.db.tx(unscoped="test") as s:
        activity.record(s, "key.unlocked", actor=None, for_admins=True)
    alerts.evaluate(server)
    from moolakata.store.entities.alerts import Alert

    with server.db.read(unscoped="test") as s:
        still = {a.kind for a in s.query(Alert).filter(Alert.resolvedAt.is_(None))}
    assert still == {"key-rotation"}


def test_the_rotation_reminder_follows_its_setting(server, admin_client, frozen):
    # Due after the period Settings › Key Storage sets (S15.8.4); off, never.
    created = server.store.keys.ring.master_created
    with server.db.tx(unscoped="test") as s:
        settings.put(s, "keyReminderMonths", 6, None)
    clock.fix(created + dt.timedelta(days=190))
    assert [a.kind for a in alerts.evaluate(server)] == ["key-rotation"]
    with server.db.tx(unscoped="test") as s:
        settings.put(s, "keyReminderMonths", 0, None)
    assert alerts.evaluate(server) == []


def test_an_option_expiring_within_a_week_and_a_pledge_due(server, frozen):
    # To the account's owner, and to the organisation's (S12.11.1.3, S7.9.5).
    from test_accounts import new_account
    from test_options import opt

    make_user(server, "jane")
    c = sign_in(server, "jane")
    brk = new_account(c, name="Brokerage", type="brokerage")
    opt(c, brk["id"], "sell-to-open", "2026-10-01", "1.00", expiry="2026-10-16", fees="0")
    org = make(c, "Orgzn", name="Food Bank", deductible=True, pledge="50.00", pledgeEvery="month")
    assert org.status_code == 200, org.text
    titles = sorted(a.title for a in alerts.evaluate(server))
    assert titles == ["MSFT 16OCT26 480 P expires in 3 days"], titles
    at(days=13)  # Oct 26: the month's pledge is due; the option has expired
    assert "pledge-due" in [a.kind for a in alerts.evaluate(server)]
    from moolakata.store.entities.alerts import Alert

    with server.db.read(unscoped="test") as s:
        open_ = {a.kind for a in s.query(Alert).filter(Alert.resolvedAt.is_(None))}
    assert "option-expiring" not in open_ and "pledge-due" in open_


def _outbox_subjects(server) -> list[str]:
    return [w.subject for w in server.services.mailer.waiting()]


def test_each_alert_is_emailed_once_when_smtp_is_set(server, admin_client, frozen):
    with server.db.tx(unscoped="test") as s:
        s.add(TaskRun(name="backups", startedAt=T0, finishedAt=T0, error="disk full"))
    alerts.evaluate(server)
    assert _outbox_subjects(server) == [], "no SMTP: nothing is sent"
    with server.db.tx(unscoped="test") as s:
        s.get(TaskRun, "backups").error = None
    alerts.evaluate(server)
    with server.db.tx(unscoped="test") as s:
        settings.put(s, "smtpHost", "smtp.home.lan", None)
        s.get(TaskRun, "backups").error = "disk full again"
    alerts.evaluate(server)
    alerts.evaluate(server)
    assert _outbox_subjects(server) == ["MoolaKata alert: Backup failed"]


def test_the_daily_summary_goes_once_a_day_after_its_time(server, frozen):
    jane = make_user(server, "jane")
    with server.db.tx(unscoped="test") as s:
        settings.put(s, "smtpHost", "smtp.home.lan", None)
        a = Account(
            id=ids.new_id("Acct"),
            ownerId=jane.id,
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
                userId=jane.id,
                format="csv",
                fileName="a.csv",
                fileHash="y",
                coveredTo=dt.date(2026, 8, 1),
            )
        )
    alerts.evaluate(server)
    # 12:00 UTC is 08:00 in New York, past the 07:00 default.
    with server.db.tx(unscoped="test") as s:
        from moolakata.store.entities.users import User

        s.get(User, jane.id).timeZone = "America/New_York"
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


def test_every_check_names_the_keys_it_keeps_when_it_fails():
    assert {fn.__name__ for fn in alerts.CHECKS} == set(alerts._KEYS)


def _key_heads(fn) -> list[str]:
    """The literal start of every cause key the check writes: `f"link:{link.id}"` → "link:"."""
    import ast
    import inspect
    import textwrap

    tree = ast.parse(textwrap.dedent(inspect.getsource(fn)))
    heads = []
    for node in ast.walk(tree):
        if isinstance(node, ast.keyword) and node.arg == "key":
            v = node.value
            while isinstance(v, ast.BinOp):  # "bitcoin" + (…)
                v = v.left
            if isinstance(v, ast.JoinedStr):
                v = v.values[0]
            assert isinstance(v, ast.Constant), ast.dump(node)
            heads.append(v.value)
    return heads


def test_a_failed_check_holds_back_its_own_keys_and_no_other_checks():
    """S12.11.2: each key a check writes has one of its stems, and no other check's."""
    for fn in alerts.CHECKS:
        heads = _key_heads(fn)
        assert heads, fn.__name__
        for head in heads:
            key = head + "x" if head.endswith(":") else head
            owners = [n for n, stems in alerts._KEYS.items() if alerts._held_back(key, stems)]
            assert owners == [fn.__name__], (key, owners)


@contextlib.contextmanager
def broken_check(name: str):
    """The check called `name` raises while the block runs."""

    def broken(s, server):
        raise RuntimeError("a check that can't run")
        yield

    i = next(i for i, fn in enumerate(alerts.CHECKS) if fn.__name__ == name)
    keep = alerts.CHECKS[i]
    broken.__name__ = name
    alerts.CHECKS[i] = broken
    try:
        yield
    finally:
        alerts.CHECKS[i] = keep


def test_a_check_that_fails_leaves_its_alerts_open_and_unsent(server, admin_client, frozen):
    with server.db.tx(unscoped="test") as s:
        s.add(TaskRun(name="backups", startedAt=T0, finishedAt=T0, error="disk full"))
    alerts.evaluate(server)
    before = [a["title"] for a in listed(admin_client)["open"]]
    assert before == ["Backup failed"]
    with server.db.tx(unscoped="test") as s:
        s.get(TaskRun, "backups").error = None
    with broken_check("backups"):
        assert alerts.evaluate(server) == []  # nothing reopened, so nothing sent again
    assert [a["title"] for a in listed(admin_client)["open"]] == before
    alerts.evaluate(server)  # the check runs again: the backup is fixed
    assert listed(admin_client)["open"] == []


def test_a_failing_check_holds_back_no_other_checks_source_alert(server, admin_client, frozen):
    """S12.11.2: while the linked servers' check fails, Tiingo's *source failing* alert, which
    the price sources' check raised, still resolves when Tiingo answers again."""
    failing_source(server, ok_hours_ago=50)
    assert [a.title for a in alerts.evaluate(server)] == ["Tiingo failing for 2 days"]
    set_source_error(server, None)
    with broken_check("linked_servers"):
        alerts.evaluate(server)
    body = listed(admin_client)
    assert body["open"] == [] and body["resolved"][0]["resolution"] == "the cause cleared"


def test_stale_values_with_no_import_alert_once_naming_the_oldest(server, frozen):
    """Holdings valued from statements an account has no import for (no next statement is
    due, so none is overdue) alert when stale: one alert for the account, naming the oldest."""
    from test_accounts import new_account

    from moolakata.store.entities.accounts import Holding, Instrument

    make_user(server, "jane")
    c = sign_in(server, "jane")
    acct = new_account(c, name="Old plan", type="brokerage")
    with server.db.tx(unscoped="test") as s:
        s.get(Account, acct["id"]).statementInterval = "monthly"
        for symbol, ended in (("XJULZ", dt.date(2026, 7, 31)), ("XAUGZ", dt.date(2026, 8, 31))):
            fund = Instrument(id=ids.new_id("Instr"), symbol=symbol, instrumentClass="mutual-fund")
            s.add(fund)
            s.flush()
            s.add(Holding(id=ids.new_id("Hold"), accountId=acct["id"], instrumentId=fund.id,
                          asOf=ended, quantity=10, marketValue=1000))  # fmt: skip
    at(days=2)  # Oct 15: Aug 31's next statement is due, and Jul 31's was a month ago
    alerts.evaluate(server)
    (a,) = [
        a for a in listed(sign_in(server, "jane"))["open"] if a["kind"] == "statement-value-old"
    ]
    assert a["about"].startswith("the statement of Jul 31, 2026")


def test_a_holding_valued_from_a_stale_statement_alerts_its_owner(server, frozen):
    # S4.3, S12.11.1.2: a statement's value is stale once the statement after it is
    # overdue (S1.11.7.3), and alerts only when that statement's own alert isn't already up: a
    # plan whose next statement is late gets the overdue alert alone, and a newer import that
    # doesn't value the holding leaves it stale and alerting. An account expecting no
    # statements counts as yearly.
    from test_accounts import new_account

    from moolakata.store.entities.accounts import Holding, Instrument

    jane = make_user(server, "jane")
    c = sign_in(server, "jane")
    plan = new_account(c, name="Plan", type="401k")
    kept = new_account(c, name="Kept", type="brokerage")

    def statement(acct, every, name, symbol, ended):
        with server.db.tx(unscoped="test") as s:
            s.get(Account, acct["id"]).statementInterval = every
            fund = Instrument(id=ids.new_id("Instr"), symbol=symbol, instrumentClass="mutual-fund")
            s.add(fund)
            s.flush()
            s.add(Import(id=ids.new_id("Imprt"), accountId=acct["id"], userId=jane.id,
                         format="statement", fileName=name, fileHash=name,
                         coveredFrom=ended.replace(day=1), coveredTo=ended))  # fmt: skip
            s.add(Holding(id=ids.new_id("Hold"), accountId=acct["id"], instrumentId=fund.id,
                          asOf=ended, quantity=10, marketValue=1000))  # fmt: skip

    def stale(acct) -> list[bool]:
        c = sign_in(server, "jane")  # a fresh session on the day the clock is at
        got = c.get(f"/ui/api/accounts/{acct['id']}/holdings").json()["holdings"]
        return [h["stale"] for h in got]

    def raised() -> dict[str, dict]:
        alerts.evaluate(server)
        open_ = listed(sign_in(server, "jane"))["open"]
        return {a["kind"] + " " + a["title"].split(":")[0]: a for a in open_}

    # Both stale from Oct 30: Jun 30, a quarter and 30 days on; Aug 31, 2025, a year and 60.
    statement(plan, "quarterly", "q2.pdf", "XPLANZ", dt.date(2026, 6, 30))
    statement(kept, "none", "aug.pdf", "XKEPTZ", dt.date(2025, 8, 31))
    at(days=16)
    assert raised() == {}
    assert stale(plan) == stale(kept) == [False]
    at(days=17)
    assert stale(plan) == stale(kept) == [True]
    got = raised()
    assert set(got) == {"statement-overdue Plan", "statement-value-old Kept"}
    a = got["statement-value-old Kept"]
    assert a["title"] == "Kept: a holding is still valued from an old statement"
    assert a["about"].startswith("the statement of Aug 31, 2025")
    assert a["link"] == f"/ui/accounts/{kept['id']}/holdings"

    # The plan's July–September download arrives without its positions: the holding's value
    # is still June's, stale, and now the value's own alert says so.
    with server.db.tx(unscoped="test") as s:
        s.add(Import(id=ids.new_id("Imprt"), accountId=plan["id"], userId=jane.id,
                     format="ofx", fileName="q3.ofx", fileHash="q3",
                     coveredFrom=dt.date(2026, 7, 1), coveredTo=dt.date(2026, 9, 30)))  # fmt: skip
    assert set(raised()) == {"statement-value-old Plan", "statement-value-old Kept"}
    assert stale(plan) == [True]


def _causes(server, check) -> list:
    with server.db.read(unscoped="test") as s:
        return list(check(s, server))


def test_bitcoin_wallets_not_checked_alert_admins_and_each_wallets_owner(server, frozen):
    """S1.6.2, S16.16: the explorer or node failing since its last good check tells admins
    and the owner of each wallet, after Settings › Alerts' hours; while it works, nothing."""
    jane = make_user(server, "jane")
    assert _causes(server, alerts.bitcoin_source) == []
    began = T0 - dt.timedelta(hours=50)
    with server.db.tx(unscoped="test") as s:
        s.add(TaskRun(name="bitcoin", startedAt=began, finishedAt=began, error=None))
    assert _causes(server, alerts.bitcoin_source) == [], "the last run worked"
    with server.db.tx(unscoped="test") as s:
        # No wallet address checked yet: failing since the run that failed began.
        s.get(TaskRun, "bitcoin").error = "the explorer answered 503"
        s.add(Account(id=ids.new_id("Acct"), ownerId=jane.id, name="Cold storage",
                      type="crypto-wallet"))  # fmt: skip
    causes = _causes(server, alerts.bitcoin_source)
    assert [(c.key, c.user_id, c.link) for c in causes] == [
        ("bitcoin", None, "/ui/settings/bitcoin"),
        (f"bitcoin:{jane.id}", jane.id, "/ui/accounts"),
    ]
    assert {c.title for c in causes} == {"Bitcoin wallets not checked for 2 days"}
    assert {c.about for c in causes} == {"explorer or node · the explorer answered 503"}
    assert {c.since for c in causes} == {began}
    assert {c.delay for c in causes} == {dt.timedelta(hours=48)}


def test_a_linked_servers_new_certificate_or_its_failing_alerts_admins(server, frozen):
    """S11.6, link-protocol.md §4.5: a peer's changed certificate alerts at once, before its
    failing would; a peer not reached since its last error alerts after the source hours."""
    from moolakata.store.entities.links import Link

    since = T0 - dt.timedelta(hours=30)
    with server.db.tx(unscoped="test") as s:
        changed = Link(id=ids.new_id("Link"), state="active", role="inviter", copyPublicKey="k",
                       peerName="Grandma", peerCertOffered="ab" * 32, failingSince=since,
                       lastError="certificate-changed")  # fmt: skip
        failing = Link(id=ids.new_id("Link"), state="active", role="joiner", copyPublicKey="k",
                       failingSince=since, lastError="unreachable")  # fmt: skip
        s.add_all([changed, failing])
    causes = {c.key: c for c in _causes(server, alerts.linked_servers)}
    assert set(causes) == {f"link-cert:{changed.id}", f"link:{failing.id}"}
    cert = causes[f"link-cert:{changed.id}"]
    assert (cert.kind, cert.title) == ("link-certificate", "Grandma's certificate changed")
    assert cert.about == "compare its new fingerprint with its admin, then accept it"
    down = causes[f"link:{failing.id}"]
    assert (down.kind, down.title) == ("source-failing", "A linked server not reached for 30 hours")
    assert (down.about, down.since, down.delay) == (
        "linked server · unreachable",
        since,
        dt.timedelta(hours=48),
    )


def test_email_that_cant_be_sent_alerts_admins_from_the_oldest_waiting(server, frozen, monkeypatch):
    """S16.2, S16.16: the mail task failing with emails waiting: since the oldest was queued,
    after the source hours; with none waiting, nothing."""
    from moolakata.mail import Waiting

    with server.db.tx(unscoped="test") as s:
        s.add(TaskRun(name="mail", startedAt=T0, finishedAt=T0, error="could not reach it"))
    assert _causes(server, alerts.email) == [], "nothing waiting"
    queued = T0 - dt.timedelta(hours=5)
    waiting = [Waiting("Email_1", "a@b.lan", "s", queued, None)] * 2
    monkeypatch.setattr(server.services.mailer, "waiting", lambda: waiting)
    [cause] = _causes(server, alerts.email)
    assert (cause.key, cause.title, cause.about) == (
        "mail",
        "Email can't be sent: 2 waiting",
        "SMTP · could not reach it",
    )
    assert (cause.since, cause.link, cause.user_id) == (queued, "/ui/settings/email", None)


def test_the_daily_summary_waits_for_its_time_in_the_users_zone(server, frozen):
    """S12.11.5: before the summary's time where the user is, nothing is sent and nothing is
    marked sent."""
    from moolakata.store.entities.users import User

    jane = make_user(server, "jane")
    with server.db.tx(unscoped="test") as s:
        settings.put(s, "smtpHost", "smtp.home.lan", None)
        u = s.get(User, jane.id)
        u.timeZone, u.alertEmails = "America/Los_Angeles", "daily"  # 05:00 there, before 07:00
    assert alerts.daily_summaries(server) == 0
    with server.db.read(unscoped="test") as s:
        assert s.get(User, jane.id).alertSummaryAt is None


def test_a_share_asked_of_a_person_since_gone_alerts_nobody(server, frozen):
    """S10.10.3: the alert lasts while the person is there to share; one deleted since (gone
    from the table, as a restore leaves them) ends it."""
    from moolakata import activity

    jane = make_user(server, "jane")
    with server.db.tx(unscoped="test") as s:
        activity.record(s, "person.share-asked", actor=jane.id, subject_kind="person",
                        subject_id="Prsn_gone", owner=jane.id)  # fmt: skip
    assert _causes(server, alerts.share_asked) == []
