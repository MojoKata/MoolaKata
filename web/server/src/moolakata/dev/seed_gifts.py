"""Dev mode's gifts (requirements S17.7): Jane's gift plans for Lisa, Bart, Candace, John and
her friend John Smith, with their holidays; gifts from idea to given across this year and last, one
received with its thank-you; and her plan for Lisa shared with John so they plan her gifts
together."""

from decimal import Decimal as D

from sqlalchemy import select

from .. import clock, ids, sharing
from ..store.entities.education import Gift, GiftPerson, GiftPlan, Occasion, Person


def seed_gifts(s, people: dict) -> None:
    jane, john = people["jane"], people["john"]
    year = clock.today().year
    now = clock.now()

    def named(name: str) -> Person:
        return s.scalars(select(Person).where(Person.name == name)).one()

    lisa, bart = named("Lisa Doe"), named("Bart Doe")
    candace, jsmith = named("Candace Doe"), named("John Smith")
    him = s.get(Person, john.personId)

    def plan(p, budget=None, notes=None):
        gp = GiftPlan(
            id=ids.new_id("GfPln"),
            ownerId=jane.id,
            personId=p.id,
            giftBudget=D(budget) if budget else None,
            notes=notes,
        )
        s.add(gp)
        s.flush()
        return gp

    lisa_plan = plan(lisa, 600, "Loves drawing and horses. Shoe size 1.")
    bart_plan = plan(bart, 600)
    candace_plan = plan(candace, 300)
    jsmith_plan = plan(jsmith, 150)
    john_plan = plan(him, 800, "Size L. Wants a new watch strap.")

    def occasion(gp, kind, **kw):
        s.add(Occasion(id=ids.new_id("Occsn"), giftPlanId=gp.id, kind=kind, **kw))

    occasion(lisa_plan, "holiday", holiday="christmas", budget=D(150))
    occasion(bart_plan, "holiday", holiday="christmas", budget=D(200))
    occasion(candace_plan, "holiday", holiday="christmas", budget=D(80))
    occasion(candace_plan, "holiday", holiday="mothers-day")
    occasion(jsmith_plan, "holiday", holiday="diwali", budget=D(50))
    occasion(john_plan, "holiday", holiday="christmas")
    occasion(john_plan, "holiday", holiday="valentines")

    def gift(whom, description, status, occ=None, y=None, cost=None, **kw):
        g = Gift(
            id=ids.new_id("Gift"),
            ownerId=jane.id,
            description=description,
            status=status,
            occasion=occ,
            occasionYear=y if occ else None,
            cost=D(cost) if cost else None,
            **kw,
        )
        s.add(g)
        s.flush()
        for p in whom:
            s.add(GiftPerson(giftId=g.id, personId=p.id, createdAt=now))

    gift([lisa], "Watercolour set", "idea", "birthday", year)
    gift([lisa], "Riding lessons, a block of five", "planned", "birthday", year, "180")
    gift([lisa], "Horse encyclopedia", "idea")
    gift([lisa], "LEGO castle", "given", "birthday", year - 1, "89.99")
    gift([lisa], "Art easel", "given", "holiday:christmas", year - 1, "64.00")
    gift([bart], "Noise-cancelling headphones", "idea", "holiday:christmas", year)
    gift([bart], "Concert tickets", "given", "birthday", year, "180.00")
    gift([jsmith], "Cookbook", "given", "birthday", year, "40.00")
    gift([candace], "Framed photo of Lisa", "given", "holiday:mothers-day", year, "45.00")
    gift([candace], "Wool scarf", "received", "holiday:christmas", year - 1, thankYou=True)
    gift([him], "Watch strap, brown leather", "planned", "holiday:christmas", year, "120")
    gift([him], "Weekend away", "given", "wedding", year, "640.00")
    gift(
        [lisa, him],
        "Board game for the family",
        "bought",
        "holiday:christmas",
        year,
        "39.99",
        store="Target",
    )
    s.add(
        sharing.new_share(
            "gift-plan",
            lisa_plan.id,
            "write",
            user_id=john.id,
            by=jane.id,
        )
    )
