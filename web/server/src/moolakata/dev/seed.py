"""Dev mode's seed data (requirements S17.7): the users admin, jane and john, a Household
group, and a year of their accounts; each part of the app adds its own."""

import datetime as dt
import logging

from sqlalchemy import select

from .. import clock, ids, settings
from ..auth import passwords
from ..auth import users as accounts
from ..store.entities.alerts import Alert
from ..store.entities.education import Person, Relationship
from ..store.entities.users import Group, User, UserGroup
from .seed_accounts import seed_accounts, seed_rules
from .seed_assets import seed_assets
from .seed_budgets import seed_budgets
from .seed_connector import seed_connector
from .seed_education import seed_education
from .seed_gifts import seed_gifts
from .seed_giving import seed_giving
from .seed_links import seed_links
from .seed_loans import seed_loans
from .seed_options import seed_options
from .seed_projections import seed_projections
from .seed_receipts import seed_receipts
from .seed_sharing import seed_sharing
from .seed_taxes import seed_taxes
from .seed_wallets import seed_wallets

log = logging.getLogger("moolakata.dev")
PASSWORD = "moolakata-dev"  # noqa: S105 - dev mode's seed users only


def seed(server) -> None:
    with server.db.tx(unscoped="dev mode: the seed") as s:
        if s.scalars(select(User).where(User.username == "jane")).first():
            log.info("dev: already seeded")
            return
        people = seed_users(s)
        # An address of its own, so what builds links and codes from it works (S16.1): the dev
        # default's, whatever port this run has, so the generated mockup records the same.
        settings.put(s, "publicUrl", "https://localhost:37373", None)
        seed_accounts(s, people)
        seed_rules(s, people)
        seed_loans(s, people)
        seed_assets(s, people)
        seed_education(s, people)
        seed_gifts(s, people)
        seed_giving(s, people)
        seed_taxes(s, people)
        seed_options(s, people)
        seed_wallets(s, people)
        if server.config.stubs:
            # Settings › Bitcoin saved, so the wallets are read (S16.7, S17.7).
            settings.put(s, "bitcoinSource", "stub", None)
        seed_links(server, s, people)
        seed_connector(s, people)
        seed_sharing(s, people)
        seed_budgets(s, people)
        seed_receipts(server, s, people)
        seed_projections(s, people)
        seed_alerts(s)
    log.info("dev: seeded; sign in as admin, jane or john with %r", PASSWORD)
    from .seed_links import words

    log.info("dev: doe-parents' linked copy opens with: %s", words())


def seed_users(s) -> dict[str, User]:
    settings.put(s, "householdName", "John & Jane", None)
    settings.put(
        s, "householdAvatar", {"kind": "initials", "initials": "JJ", "color": "#3b7a57"}, None
    )
    # The first admin, as the welcome makes it (S10.1.2), with the seed users' password.
    admin = s.scalars(select(User).where(User.username == "admin")).one_or_none()
    if admin is None:
        admin = accounts.make_first_admin(s, "Admin", "male", "admin@doe.home", PASSWORD)
    people = {"admin": admin}
    for username, name, sex, born in (
        ("jane", "Jane Doe", "female", dt.date(1979, 4, 12)),
        ("john", "John Doe", "male", dt.date(1977, 4, 2)),
    ):
        p = Person(
            id=ids.new_id("Persn"),
            name=name,
            sex=sex,
            birthMonth=born.month,
            birthDay=born.day,
            birthYear=born.year,
        )
        s.add(p)
        s.flush()
        u = User(
            id=ids.new_id("User"),
            personId=p.id,
            username=username,
            displayName=name,
            email=f"{username}@doe.home",
            passwordHash=passwords.hash_password(PASSWORD),
        )
        s.add(u)
        people[username] = u
    s.flush()
    # An admin starts on an email for each alert (S12.11.5).
    people["jane"].alertEmails = "each"
    seed_family(s, people)
    s.add(
        UserGroup(
            userId=people["jane"].id, groupId=accounts.admins_group(s).id, createdAt=accounts.now()
        )
    )
    household = Group(id=ids.new_id("Group"), name="Household")
    s.add(household)
    s.flush()
    for u in ("jane", "john"):
        s.add(UserGroup(userId=people[u].id, groupId=household.id, createdAt=accounts.now()))
    return people


def seed_family(s, people: dict[str, User]) -> None:
    """The household's people and how they are related (S10.10): Jane and John married since
    2009, their daughter Lisa and son Bart, John's parents Candace and Jeremy (users of the linked
    doe-parents), and Jane's friend John Smith, whom Jane keeps private."""
    jane, john = people["jane"], people["john"]

    def person(name, sex, month=None, day=None, year=None, private=False):
        p = Person(
            id=ids.new_id("Persn"),
            ownerId=jane.id,
            name=name,
            sex=sex,
            birthMonth=month,
            birthDay=day,
            birthYear=year,
            private=private,
        )
        s.add(p)
        return p

    lisa = person("Lisa Doe", "female", 10, 20, 2018)
    bart = person("Bart Doe", "male", 3, 3, 2012)
    candace = person("Candace Doe", "female", 3, 14, 1952)
    jeremy = person("Jeremy Doe", "male", 8, 30, 1950)
    jsmith = person("John Smith", "male", 2, 9, private=True)
    s.flush()

    def relate(a, b, relation, since=None):
        x, y = (
            a.personId if isinstance(a, User) else a.id,
            b.personId if isinstance(b, User) else b.id,
        )
        x, y = (x, y) if relation == "child" or x < y else (y, x)
        # The household's marriages, confirmed by both (S10.10.4).
        both = clock.now() if relation == "spouse" else None
        s.add(
            Relationship(
                id=ids.new_id("Rltn"),
                person1Id=x,
                person2Id=y,
                relation=relation,
                fromDate=since,
                confirmed1At=both,
                confirmed2At=both,
            )
        )

    relate(jane, john, "spouse", dt.date(2009, 6, 14))
    relate(candace, jeremy, "spouse", dt.date(1981, 11, 2))
    for parent in (jane, john):
        relate(parent, lisa, "child")
        relate(parent, bart, "child")
    for parent in (candace, jeremy):
        relate(parent, john, "child")
    relate(jane, jsmith, "friend", dt.date(2015, 5, 1))
    s.flush()


def seed_alerts(s) -> None:
    """A resolved alert for the admins; open ones come from the seed's own causes."""

    now = clock.now()
    s.add(
        Alert(
            id=ids.new_id("Alert"),
            kind="backup-failed",
            causeKey="backups",
            title="Backup failed",
            about="the backup directory was full",
            link="/ui/settings/backups",
            fix="Backups",
            seenSince=now - dt.timedelta(days=6),
            openedAt=now - dt.timedelta(days=6),
            resolvedAt=now - dt.timedelta(days=5),
            resolution="the next backup succeeded",
        )
    )
