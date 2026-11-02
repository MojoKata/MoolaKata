"""Dev mode's gifts (requirements S17.7): Alice's gift plans for Emma, Carol, Margaret, Bob and
her friend Priya, with their holidays; gifts from idea to given across this year and last, one
received with its thank-you; and her plan for Emma shared with Bob so they plan her gifts
together."""

from decimal import Decimal as D

from sqlalchemy import select

from .. import clock, ids, sharing
from ..store.entities.education import Gift, GiftPerson, GiftPlan, Occasion, Person


def seed_gifts(s, people: dict) -> None:
    alice, bob = people["alice"], people["bob"]
    year = clock.today().year
    now = clock.now()

    def named(name: str) -> Person:
        return s.scalars(select(Person).where(Person.name == name)).one()

    emma, carol = named("Emma Griffin"), named("Carol Griffin")
    margaret, priya = named("Margaret Griffin"), named("Priya Shah")
    him = s.get(Person, bob.personId)

    def plan(p, budget=None, notes=None):
        gp = GiftPlan(
            id=ids.new_id("GfPln"),
            ownerId=alice.id,
            personId=p.id,
            giftBudget=D(budget) if budget else None,
            notes=notes,
        )
        s.add(gp)
        s.flush()
        return gp

    emma_plan = plan(emma, 600, "Loves drawing and horses. Shoe size 1.")
    carol_plan = plan(carol, 600)
    margaret_plan = plan(margaret, 300)
    priya_plan = plan(priya, 150)
    bob_plan = plan(him, 800, "Size L. Wants a new watch strap.")

    def occasion(gp, kind, **kw):
        s.add(Occasion(id=ids.new_id("Occsn"), giftPlanId=gp.id, kind=kind, **kw))

    occasion(emma_plan, "holiday", holiday="christmas", budget=D(150))
    occasion(carol_plan, "holiday", holiday="christmas", budget=D(200))
    occasion(margaret_plan, "holiday", holiday="christmas", budget=D(80))
    occasion(margaret_plan, "holiday", holiday="mothers-day")
    occasion(priya_plan, "holiday", holiday="diwali", budget=D(50))
    occasion(bob_plan, "holiday", holiday="christmas")
    occasion(bob_plan, "holiday", holiday="valentines")

    def gift(whom, description, status, occ=None, y=None, cost=None, **kw):
        g = Gift(
            id=ids.new_id("Gift"),
            ownerId=alice.id,
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

    gift([emma], "Watercolour set", "idea", "birthday", year)
    gift([emma], "Riding lessons, a block of five", "planned", "birthday", year, "180")
    gift([emma], "Horse encyclopedia", "idea")
    gift([emma], "LEGO castle", "given", "birthday", year - 1, "89.99")
    gift([emma], "Art easel", "given", "holiday:christmas", year - 1, "64.00")
    gift([carol], "Noise-cancelling headphones", "idea", "holiday:christmas", year)
    gift([carol], "Concert tickets", "given", "birthday", year, "180.00")
    gift([priya], "Cookbook", "given", "birthday", year, "40.00")
    gift([margaret], "Framed photo of Emma", "given", "holiday:mothers-day", year, "45.00")
    gift([margaret], "Wool scarf", "received", "holiday:christmas", year - 1, thankYou=True)
    gift([him], "Watch strap, brown leather", "planned", "holiday:christmas", year, "120")
    gift([him], "Weekend away", "given", "wedding", year, "640.00")
    gift(
        [emma, him],
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
            emma_plan.id,
            "write",
            user_id=bob.id,
            by=alice.id,
        )
    )
