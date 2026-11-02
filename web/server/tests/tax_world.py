"""Generated tax worlds (requirements S2.2, S2.3, S3.1, S3.8, S8.1, S8.3, S8.14): a household's
filers, accounts with their lot methods, and sale stories of every shape, drawn from a seed. A
world is a plain description first (`World`), so which data shapes the worlds reach is checked
without a server (`pairs`); `tax_reference` works out what each tax book's Form 8949 must say
from the description alone, and `test_tax_world` makes each world through the API and holds the
app's figures to it.

A **story** is one instrument's life in one account: buys before a sale (three lots, so the lot
method matters), the sale, and maybe a buy of the same instrument near the sale (a wash sale's
replacement, or a buy that must not be one) and a later sale of that buy. Each story has its own
instrument, so stories don't meet by chance; where they meet is the story's own doing.

The axes and their values are `AXES`. Coverage is pairwise: across the worlds of `SEEDS`, every
pair of values of two axes of a story meets at least once, but for the pairs that can't exist
(`_impossible`).
"""

import datetime as dt
import itertools
import random
from dataclasses import dataclass, field

TODAY = dt.date(2026, 12, 28)
YEARS = (2025, 2026)

# Per world.
FILERS = ("solo", "joint", "separate")  # Bob is Alice's spouse but in solo, where he's a stranger
METHODS = ("fifo", "lifo", "hifo", "average")

# Per story.
SELLERS = ("alice", "bob")
CLASSES = ("equity", "fund", "crypto")
PICKS = ("account", "specific", "specific-short")  # the account's method, or lots picked
TERMS = ("short", "long", "mixed", "anniversary", "old")
OUTCOMES = ("gain", "loss", "mixed")
SIZES = ("one-lot", "across", "most")
WHERE = ("none", "same", "other", "ira", "partner")
WHEN = ("none", "before", "after", "day-30", "day-31")
REPLACED = ("none", "whole", "part")
SOLD_IN = ("2025", "2026", "year-end")
FOLLOW = ("none", "resold")
# Between the buys and the sale: a 2-for-1 split, or a merger into two new shares a share and
# $3.00 cash (S2.4, IRC §356).
ACTION = ("none", "split", "merger")
OVERRIDE = ("none", "left-out")  # per world: Second left out of Alice's 2026 book

# Per option story (S3.2–S3.4): a contract opened long or short, ended closed, expired, or
# assigned (short) or exercised (long), its stock traded at the strike with the premium in it.
POSITIONS = ("long", "short")
RIGHTS = ("call", "put")
ENDS = ("close", "expire", "settle")
OPT_TERMS = ("short", "long")
OPT_UNDERLYINGS = ("SPY", "QQQ", "IWM", "DIA", "XLF", "XLE", "XLK", "GLD", "SMH", "XBI",
                   "EEM", "TLT", "HYG", "LQD", "ARKK", "SOXX")  # fmt: skip

# Per income record (S8.5): interest and dividends of each type, in each account, each year.
INCOME_KINDS = ("interest", "dividend", "reinvest", "capital-gain")
DIV_TYPES = ("qualified", "ordinary", "none")
INCOME_ACCOUNTS = ("Brokerage", "Second", "Bob's brokerage")
INCOME_YEARS = ("2025", "2026")
INCOME_SYMBOLS = ("SCHD", "VYM", "DGRO", "HDV", "NOBL", "SPYD", "DVY", "SDY")

AXES = {
    "story": {"filers": FILERS, "seller": SELLERS, "class": CLASSES, "method": METHODS,
              "picks": PICKS, "term": TERMS, "outcome": OUTCOMES, "size": SIZES,
              "where": WHERE, "when": WHEN, "replaced": REPLACED, "soldIn": SOLD_IN,
              "follow": FOLLOW, "action": ACTION, "override": OVERRIDE},
    "option": {"filers": FILERS, "override": OVERRIDE, "position": POSITIONS, "right": RIGHTS,
               "end": ENDS, "outcome": ("gain", "loss"), "term": OPT_TERMS,
               "year": INCOME_YEARS, "account": INCOME_ACCOUNTS},
    "income": {"filers": FILERS, "override": OVERRIDE, "kind": INCOME_KINDS,
               "type": DIV_TYPES, "account": INCOME_ACCOUNTS, "year": INCOME_YEARS},
}  # fmt: skip

SEEDS = range(24)

# Accounts: name -> (owner, type). Alice's two brokerages and her two crypto accounts carry the
# world's lot methods; Bob has one brokerage.
ACCOUNTS = {
    "Brokerage": ("alice", "brokerage"),
    "Second": ("alice", "brokerage"),
    "IRA": ("alice", "ira"),
    "Exchange": ("alice", "crypto-exchange"),
    "Wallet": ("alice", "crypto-wallet"),
    "Bob's brokerage": ("bob", "brokerage"),
}
TAXABLE = ("brokerage", "crypto-exchange", "crypto-wallet")

EQUITIES = ("AAPL", "MSFT", "NVDA", "AMZN", "GOOG", "META", "TSLA", "JPM", "V", "MA", "UNH",
            "HD", "PG", "KO", "PEP", "COST", "WMT", "DIS", "NFLX", "ADBE", "CRM", "ORCL",
            "INTC", "AMD", "QCOM", "TXN", "IBM", "CSCO", "NKE", "MCD", "SBUX", "BA", "CAT",
            "DE", "GE", "MMM", "HON", "LMT", "XOM", "CVX")  # fmt: skip
FUNDS = ("VTSAX", "FXAIX", "VFIAX", "SWPPX", "VTIAX", "VBTLX", "FSKAX", "VGSLX", "VIMAX",
         "VSMAX", "FZROX", "FTIHX")  # fmt: skip
COINS = ("BTC", "ETH", "SOL", "ADA", "DOGE", "LTC", "XRP", "DOT", "AVAX", "LINK")


def _impossible(a: tuple[str, str], b: tuple[str, str], kind: str = "story") -> bool:
    """Pairs no record can hold."""
    k = {a[0]: a[1], b[0]: b[1]}
    get = k.get
    if kind == "income":
        # Interest and gain distributions have no dividend type.
        return get("kind") in ("interest", "capital-gain") and get("type") not in (None, "none")
    if kind == "option":
        # A written contract is short term however long it was open (S3.3); expiring, a long
        # one loses what it cost and a short one keeps its credit.
        if get("position") == "short" and get("term") == "long":
            return True
        if get("end") == "expire" and "position" in k and "outcome" in k:
            return (get("position") == "long") == (get("outcome") == "gain")
        return False
    # A coin neither splits nor merges.
    if get("class") == "crypto" and get("action") in ("split", "merger"):
        return True
    # A merger's story sells the new shares, nothing near the sale, no lots picked.
    if get("action") == "merger" and (
        get("where") not in (None, "none")
        or get("when") not in (None, "none")
        or get("replaced") not in (None, "none")
        or get("picks") not in (None, "account")
        or get("follow") == "resold"
    ):
        return True
    crypto = get("class") == "crypto"
    # Coins are Alice's, in her exchange and wallet: none in an IRA, none bought before 2011.
    if crypto and (get("where") in ("ira", "partner") or get("term") == "old"):
        return True
    if crypto and get("seller") == "bob":
        return True
    # In solo, Bob files no book: his sales are on no 8949.
    if get("seller") == "bob" and get("filers") == "solo":
        return True
    # Bob has one account.
    if get("seller") == "bob" and get("where") in ("other", "ira"):
        return True
    # No buy near the sale, or one: the three axes go together.
    near = [x for x in ("where", "when", "replaced") if x in k]
    if len(near) == 2 and (k[near[0]] == "none") != (k[near[1]] == "none"):
        return True
    # A later sale is of the buy near the sale, held where it can be sold on a return.
    if get("follow") == "resold" and get("where") in ("none", "ira"):
        return True
    if get("follow") == "resold" and "when" in k and get("when") == "none":
        return True
    return get("follow") == "resold" and "replaced" in k and get("replaced") == "none"


def all_pairs(kind: str = "story") -> set[frozenset]:
    out = set()
    axes = AXES[kind]
    for x, y in itertools.combinations(axes, 2):
        for vx in axes[x]:
            for vy in axes[y]:
                if not _impossible((x, vx), (y, vy), kind):
                    out.add(frozenset({(x, vx), (y, vy)}))
    return out


@dataclass
class Trade:
    """A buy or a sale as typed: quantity and price; the amount is what the cash moved."""

    account: str
    date: dt.date
    kind: str  # buy, sell
    symbol: str
    quantity: int
    price: str  # dollars and cents
    # A sale's specific lots: (the buy's index in the world's trades, quantity).
    picks: list[tuple[int, int]] = field(default_factory=list)
    ratio: int = 0  # a split's or a merger's new shares for each one held
    new_symbol: str = ""  # a merger's acquirer
    cash_cents: int = 0  # a merger's cash a share held
    new_price: str = "0"  # a new share's price that day, for the gain the cash recognizes
    # An option trade's contract (`symbol` the underlying, `quantity` the contracts, `price`
    # the premium a share) and fees; a stock trade made by an assignment or exercise names it.
    right: str = ""
    strike: int = 0
    expiry: dt.date | None = None
    fees: str = "0.00"
    leg_of: int | None = None

    @property
    def option(self) -> str:
        """The contract's symbol, as people read it: SPY 18DEC26 500 C."""
        assert self.expiry is not None
        return f"{self.symbol} {self.expiry:%d%b%y}".upper() + (
            f" {self.strike} {'C' if self.right == 'call' else 'P'}"
        )

    @property
    def cents(self) -> int:
        """The cash the trade comes to, fees taken off (an option's contract is 100 shares)."""
        gross = self.quantity * int(self.price.replace(".", ""))
        if self.right:
            gross *= 100
            fee = int(self.fees.replace(".", ""))
            return gross + fee if self.kind in ("buy-to-open", "buy-to-close") else gross - fee
        return gross

    @property
    def amount(self) -> str:
        if self.kind in ("expire", "assign", "exercise"):
            return "0.00"
        sells = ("sell", "sell-to-open", "sell-to-close")
        c = self.cents if self.kind in sells else -self.cents
        sign = "-" if c < 0 else ""
        return f"{sign}{abs(c) // 100}.{abs(c) % 100:02d}"


@dataclass
class Income:
    """Interest or a dividend, as typed (S8.5)."""

    axes: dict[str, str]
    account: str
    date: dt.date
    kind: str  # interest, dividend, reinvest, capital-gain
    dividend_type: str | None
    cents: int
    symbol: str | None = None

    @property
    def amount(self) -> str:
        c = -self.cents if self.kind == "reinvest" else self.cents
        sign = "-" if c < 0 else ""
        return f"{sign}{abs(c) // 100}.{abs(c) % 100:02d}"


@dataclass
class Story:
    axes: dict[str, str]
    symbol: str
    account: str = ""
    trades: list[int] = field(default_factory=list)  # indices into the world's trades


@dataclass
class World:
    seed: int
    filers: str
    methods: dict[str, str]  # account name -> lot method
    trades: list[Trade] = field(default_factory=list)
    stories: list[Story] = field(default_factory=list)
    incomes: list[Income] = field(default_factory=list)
    options: list[dict] = field(default_factory=list)  # each option story's axes
    left_out: bool = False  # Second left out of Alice's 2026 book

    @property
    def married(self) -> bool:
        return self.filers != "solo"

    def books(self) -> list[tuple[int, tuple[str, ...]]]:
        """The tax books: (year, filers)."""
        units = {"solo": [("alice",)], "joint": [("alice", "bob")],
                 "separate": [("alice",), ("bob",)]}[self.filers]  # fmt: skip
        return [(y, u) for y in YEARS for u in units]

    def records(self) -> dict[str, list[dict]]:
        world = {"filers": self.filers, "override": "left-out" if self.left_out else "none"}
        return {
            "story": [{**world, **s.axes} for s in self.stories],
            "income": [{**world, **i.axes} for i in self.incomes],
            "option": [{**world, **o} for o in self.options],
        }


def pairs(w: World) -> dict[str, set[frozenset]]:
    out: dict[str, set[frozenset]] = {}
    for kind, records in w.records().items():
        got = set()
        for r in records:
            for x, y in itertools.combinations(AXES[kind], 2):
                got.add(frozenset({(x, r[x]), (y, r[y])}))
        out[kind] = got
    return out


# ---------- drawing a world ----------


def world(seed: int) -> World:
    """A world drawn from a seed: its filers and methods cycle; each story's axes are dealt
    from shuffled decks, then made consistent (`_fit`)."""
    rnd = random.Random(seed)
    filers = FILERS[seed % 3]
    m = METHODS
    methods = {"Brokerage": m[seed % 4], "Second": m[(seed + 1) % 4], "IRA": "fifo",
               "Exchange": m[(seed + 2) % 4], "Wallet": m[(seed + 3) % 4],
               "Bob's brokerage": m[(seed // 3) % 4]}  # fmt: skip
    w = World(seed, filers, methods, left_out=seed % 4 in (1, 2))
    pools = {"equity": list(EQUITIES), "fund": list(FUNDS), "crypto": list(COINS)}
    for p in pools.values():
        rnd.shuffle(p)
    used: dict[str, set[dt.date]] = {}
    n = 22
    # Each axis's values dealt from a shuffled deck, so each world holds every value of an axis
    # about equally and the pairs fall differently in each world.
    decks = {}
    for name, values in AXES["story"].items():
        deck = [values[k % len(values)] for k in range(n)]
        rnd.shuffle(deck)
        decks[name] = deck
    for i in range(n):
        axes = {name: decks[name][i] for name in AXES["story"]
                if name not in ("filers", "override")}  # fmt: skip
        axes = _fit(axes, filers, rnd)
        cls = axes["class"]
        if not pools[cls]:
            cls = axes["class"] = "equity"
            axes = _fit(axes, filers, rnd)
        symbol = pools[cls].pop()
        story = Story(axes, symbol)
        story.account = _account(story, w)
        # The method is the selling account's: the dealt one where an account has it.
        axes["method"] = w.methods[story.account]
        _story(w, story, rnd, used.setdefault(symbol, set()))
        w.stories.append(story)
    _incomes(w, rnd)
    _options(w, rnd)
    return w


def _options(w: World, rnd: random.Random) -> None:
    """Ten option stories, dealt from shuffled decks, each on an underlying of its own."""
    n = 10
    names = [k for k in AXES["option"] if k not in ("filers", "override")]
    decks = {}
    for name in names:
        values = AXES["option"][name]
        deck = [values[k % len(values)] for k in range(n)]
        rnd.shuffle(deck)
        decks[name] = deck
    unders = list(OPT_UNDERLYINGS)
    rnd.shuffle(unders)
    for i in range(n):
        a = {name: decks[name][i] for name in names}
        if a["position"] == "short":
            a["term"] = "short"
        if a["end"] == "expire":
            a["outcome"] = "loss" if a["position"] == "long" else "gain"
        w.options.append(a)
        _option_story(w, a, unders[i], rnd)


def _option_story(w: World, a: dict, under: str, rnd: random.Random) -> None:
    year = int(a["year"])
    account = a["account"]
    n = rnd.randint(1, 3)
    fee = f"{65 * n // 100}.{65 * n % 100:02d}"
    long_ = a["position"] == "long"
    if a["term"] == "long":
        opened = dt.date(year - 1, rnd.randint(1, 3), rnd.randint(1, 28))
        expiry = dt.date(year, rnd.randint(9, 11), rnd.randint(1, 28))
        ends = opened + dt.timedelta(days=rnd.randint(380, 420))
    else:
        opened = dt.date(year, rnd.randint(1, 5), rnd.randint(1, 28))
        expiry = opened + dt.timedelta(days=rnd.randint(60, 150))
        ends = opened + dt.timedelta(days=rnd.randint(20, 55))
    strike = rnd.randint(50, 400)
    p1 = rnd.randint(100, 1500)  # the premium, cents a share
    gain = a["outcome"] == "gain"
    # Closing: a long contract gains sold dearer, a short one bought back cheaper.
    p2 = max(1, p1 + (1 if gain == long_ else -1) * rnd.randint(50, 90) * (p1 // 100 + 1))

    def opt(kind, day, cents=0, qty=n):
        return Trade(account, day, kind, under, qty, _dollars(cents), right=a["right"],
                     strike=strike, expiry=expiry, fees=fee if cents else "0.00")  # fmt: skip

    sells_shares = a["end"] == "settle" and (
        (long_ and a["right"] == "put") or (not long_ and a["right"] == "call")
    )
    if sells_shares:
        # The shares delivered are held first: bought well before, at a price the outcome sets.
        cost = strike * 100 + (-1 if gain else 1) * rnd.randint(500, 2000)
        w.trades.append(Trade(account, opened - dt.timedelta(days=40), "buy", under, 100 * n,
                              _dollars(cost)))  # fmt: skip
    w.trades.append(opt("buy-to-open" if long_ else "sell-to-open", opened, p1))
    if a["end"] == "close":
        w.trades.append(opt("sell-to-close" if long_ else "buy-to-close", ends, p2))
    elif a["end"] == "expire":
        w.trades.append(opt("expire", expiry))
    else:
        how = "exercise" if long_ else "assign"
        w.trades.append(opt(how, ends))
        end = len(w.trades) - 1
        buys = (long_ and a["right"] == "call") or (not long_ and a["right"] == "put")
        w.trades.append(Trade(account, ends, "buy" if buys else "sell", under, 100 * n,
                              _dollars(strike * 100), leg_of=end))  # fmt: skip
        if buys:
            # The shares sold again later, at a price the outcome sets about their cost.
            per = strike * 100 + (p1 if long_ else -p1)
            sold = max(100, per + (1 if gain else -1) * rnd.randint(300, 1500))
            on = min(ends + dt.timedelta(days=rnd.randint(40, 90)), dt.date(year, 12, 20))
            if on <= ends:
                on = ends + dt.timedelta(days=1)
            w.trades.append(Trade(account, on, "sell", under, 100 * n, _dollars(sold)))


def _incomes(w: World, rnd: random.Random) -> None:
    """Interest and dividends dealt from shuffled decks, each reinvested one in a fund of its
    own (never traded, so it washes nothing)."""
    n = 16
    decks = {}
    for name in ("kind", "type", "account", "year"):
        values = AXES["income"][name]
        deck = [values[k % len(values)] for k in range(n)]
        rnd.shuffle(deck)
        decks[name] = deck
    symbols = list(INCOME_SYMBOLS)
    for i in range(n):
        a = {name: decks[name][i] for name in decks}
        if a["kind"] in ("interest", "capital-gain"):
            a["type"] = "none"
        on = dt.date(int(a["year"]), rnd.randint(1, 12), rnd.randint(1, 28))
        typed = None if a["type"] == "none" else a["type"]
        symbol = symbols[i % len(symbols)] if a["kind"] != "interest" else None
        w.incomes.append(Income(a, a["account"], on, a["kind"], typed, rnd.randint(500, 90000),
                                symbol))  # fmt: skip


def _fit(axes: dict, filers: str, rnd: random.Random) -> dict:
    """The dealt values made possible, changing the fewest."""
    a = dict(axes)
    if a["class"] == "crypto":
        a["seller"] = "alice"
        if a["term"] == "old":
            a["term"] = "long"
        if a["where"] in ("ira", "partner"):
            a["where"] = rnd.choice(("same", "other"))
    if a["seller"] == "bob" and filers == "solo":
        a["seller"] = "alice"
    if a["seller"] == "bob" and a["where"] in ("other", "ira"):
        a["where"] = rnd.choice(("same", "partner"))
    near = [a["where"], a["when"], a["replaced"]]
    if "none" in near and near != ["none"] * 3:
        if a["where"] == "none":
            a["when"] = a["replaced"] = "none"
        else:
            if a["when"] == "none":
                a["when"] = rnd.choice(WHEN[1:])
            if a["replaced"] == "none":
                a["replaced"] = rnd.choice(REPLACED[1:])
    if a["follow"] == "resold" and a["where"] in ("none", "ira"):
        a["follow"] = "none"
    if a["class"] == "crypto":
        a["action"] = "none"
    if a["action"] == "merger":
        a["where"], a["when"], a["replaced"] = "none", "none", "none"
        a["picks"], a["follow"] = "account", "none"
    return a


def _account(story: Story, w: World) -> str:
    """The selling account: one with the dealt method where the seller has one, else by turn."""
    a = story.axes
    if a["seller"] == "bob":
        return "Bob's brokerage"
    names = ("Exchange", "Wallet") if a["class"] == "crypto" else ("Brokerage", "Second")
    for name in names:
        if w.methods[name] == a["method"]:
            return name
    return names[(w.seed + len(w.stories)) % 2]


def _other(story: Story, account: str) -> str:
    """The account the buy near the sale goes in."""
    where = story.axes["where"]
    if where == "same":
        return account
    if where == "ira":
        return "IRA"
    if where == "partner":
        return "Brokerage" if account == "Bob's brokerage" else "Bob's brokerage"
    return {"Brokerage": "Second", "Second": "Brokerage", "Exchange": "Wallet",
            "Wallet": "Exchange"}[account]  # fmt: skip


def _price(rnd, lo: int, hi: int) -> str:
    return f"{rnd.randint(lo, hi)}.{rnd.randint(0, 99):02d}"


def _dollars(cents: int) -> str:
    return f"{cents // 100}.{cents % 100:02d}"


def _day(used: set[dt.date], day: dt.date) -> dt.date:
    """The weekday nearest `day` the instrument has no trade on yet."""
    for k in range(60):
        d = day + dt.timedelta(days=(k + 1) // 2 * (1 if k % 2 else -1))
        if d not in used and d.weekday() < 5:
            used.add(d)
            return d
    raise AssertionError("no free day")


def _sale_day(rnd, sold_in: str) -> dt.date:
    if sold_in == "year-end":
        return dt.date(2025, 12, rnd.randint(8, 19))
    year = int(sold_in)
    return dt.date(year, rnd.randint(3, 9), rnd.randint(1, 28))


def _story(w: World, story: Story, rnd: random.Random, used: set[dt.date]) -> None:
    a = story.axes
    account = story.account
    sale_on = _sale_day(rnd, a["soldIn"])
    while sale_on.weekday() >= 5:
        sale_on += dt.timedelta(days=1)
    used.add(sale_on)
    year = dt.timedelta(days=365)
    # Three buys, each 10 shares (coins too), by the term asked for. Days before the sale stay
    # outside 30 days of it, so only the buy near the sale can replace.
    term = a["term"]
    if term == "short":
        offsets = sorted(rnd.sample(range(45, 330), 3), reverse=True)
        days = [sale_on - dt.timedelta(days=o) for o in offsets]
    elif term == "long":
        offsets = sorted(rnd.sample(range(380, 900), 3), reverse=True)
        days = [sale_on - dt.timedelta(days=o) for o in offsets]
    elif term == "mixed":
        days = [sale_on - dt.timedelta(days=rnd.randint(500, 800)),
                sale_on - dt.timedelta(days=rnd.randint(200, 330)),
                sale_on - dt.timedelta(days=rnd.randint(45, 150))]  # fmt: skip
    elif term == "anniversary":
        # Bought a year to the day before the sale (short: held exactly a year), and the day
        # before that (long).
        on = sale_on.replace(year=sale_on.year - 1)
        days = [on - dt.timedelta(days=1), on, on + dt.timedelta(days=60)]
    else:  # old: about when brokers began reporting basis (shares 2011, funds 2012)
        # The year before it, or the first year of it, so each side of the line is reached.
        start = 2011 if a["class"] == "equity" else 2012
        first = dt.date(start - rnd.randint(0, 1), rnd.randint(1, 12), rnd.randint(1, 28))
        days = [first, sale_on - year * 2, sale_on - dt.timedelta(days=rnd.randint(380, 600))]
    if term == "anniversary":
        used.update(days)  # the days themselves: weekends included, a year is a year
    else:
        days = [_day(used, d) for d in days]
    lo, hi = (20, 400) if a["class"] != "crypto" else (30, 900)
    prices = []
    while len(set(prices)) < 3:  # distinct prices, so the highest cost is one lot
        prices = [_price(rnd, lo, hi) for _ in range(3)]
    buys = []
    for d, p in zip(days, prices, strict=True):
        w.trades.append(Trade(account, d, "buy", story.symbol, 10, p))
        buys.append(len(w.trades) - 1)
    story.trades += buys
    sold_as = story.symbol
    if a["action"] in ("split", "merger"):
        # 35 days before the sale: after every buy, before any buy near the sale.
        on = sale_on - dt.timedelta(days=35)
        while on in used:
            on -= dt.timedelta(days=1)
        used.add(on)
        if a["action"] == "split":
            w.trades.append(Trade(account, on, "split", story.symbol, 0, "0", ratio=2))
        else:
            sold_as = story.symbol[:4] + "Q"
            mid = sorted(prices)[1].replace(".", "")
            w.trades.append(Trade(account, on, "merger", story.symbol, 0, "0", ratio=2,
                                  new_symbol=sold_as, cash_cents=300,
                                  new_price=_dollars(int(mid) // 2)))  # fmt: skip
        story.trades.append(len(w.trades) - 1)
    qty = {"one-lot": rnd.randint(2, 9), "across": rnd.randint(12, 19),
           "most": rnd.randint(22, 28)}[a["size"]]  # fmt: skip
    cents = [int(p.replace(".", "")) for p in prices]
    if a["outcome"] == "gain":
        sale_cents = max(cents) + rnd.randint(500, 5000)
    elif a["outcome"] == "loss":
        sale_cents = max(100, min(cents) - rnd.randint(500, 5000))
    else:
        s = sorted(cents)
        sale_cents = (s[0] + s[2]) // 2 if s[0] + 1 < s[2] else s[2] + 100
        if sale_cents in cents:
            sale_cents += 1
    if a["action"] == "merger":
        sale_cents //= 2  # two new shares a share
    sale = Trade(account, sale_on, "sell", sold_as, qty, _dollars(sale_cents))
    if a["picks"] != "account":
        # Lots picked: the latest first, then the first; short of the quantity, the rest goes
        # by the account's method.
        order = [buys[2], buys[0], buys[1]]
        left = qty if a["picks"] == "specific" else max(1, qty // 2)
        for b in order:
            take = min(10, left)
            if take <= 0:
                break
            sale.picks.append((b, take))
            left -= take
    # The buy near the sale.
    near = None
    if a["where"] != "none":
        when = a["when"]
        if when in ("day-30", "day-31"):
            on = sale_on + dt.timedelta(days=int(when[-2:]))  # the edge itself, any day
        else:
            step = 1 if when == "after" else -1
            start = rnd.randint(3, 27)
            tries = [sale_on + dt.timedelta(days=step * (1 + (start + j) % 29)) for j in range(29)]
            on = next(d for d in tries if d not in used and d.weekday() < 5)
        used.add(on)
        near_qty = qty if a["replaced"] == "whole" else max(1, qty // 2)
        near_cents = max(100, sale_cents + rnd.randint(-300, 300))
        near = Trade(
            _other(story, account), on, "buy", story.symbol, near_qty, _dollars(near_cents)
        )
    # In trade order: a buy before the sale is typed first.
    if near is not None and near.date < sale_on:
        w.trades.append(near)
        story.trades.append(len(w.trades) - 1)
        w.trades.append(sale)
        story.trades.append(len(w.trades) - 1)
    else:
        w.trades.append(sale)
        story.trades.append(len(w.trades) - 1)
        if near is not None:
            w.trades.append(near)
            story.trades.append(len(w.trades) - 1)
    if a["follow"] == "resold" and near is not None:
        on = min(near.date + dt.timedelta(days=rnd.randint(45, 200)), TODAY - dt.timedelta(days=5))
        on = _day(used, on)
        c = max(100, near_cents + rnd.choice((-1, 1)) * rnd.randint(200, 2000))
        w.trades.append(Trade(near.account, on, "sell", story.symbol, near.quantity, _dollars(c)))
        story.trades.append(len(w.trades) - 1)
