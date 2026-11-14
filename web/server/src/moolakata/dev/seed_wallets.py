"""Dev mode's bitcoin wallet (requirements S17.7): Jane's cold storage, read from the public
BIP84 test key (the wallet of "abandon … about", which nobody can keep money in)."""

from .. import ids
from ..bitcoin import keys, wallet
from ..store.entities.accounts import Account

TEST_ZPUB = (
    "zpub6rFR7y4Q2AijBEqTUquhVz398htDFrtymD9xYYfG1m4wAcvPhXNfE3EfH1r1ADqtfSdVCToUG868Rv"
    "UUkgDKf31mGDtKsAYz2oz2AGutZYs"
)


def seed_wallets(s, people: dict) -> None:
    jane = people["jane"]
    a = Account(
        id=ids.new_id("Acct"),
        ownerId=jane.id,
        name="Cold storage",
        type="crypto-wallet",
        institution="Hardware wallet",
        keptBy='["bitcoin"]',
    )
    s.add(a)
    s.flush()
    wallet.replace(s, a.id, keys.parse(TEST_ZPUB), 20, jane.id)
