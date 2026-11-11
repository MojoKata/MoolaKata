@@ overview

> A self-custody bitcoin wallet, read from its extended public key or addresses. MoolaKata can
> see it, never spend from it.

@@ settings

## Keys and addresses

The wallet's extended public keys and addresses, and the addresses watched.

## Extended public keys or addresses {#wallet-keys}

An **xpub** (legacy addresses, 1…), **ypub** (nested segwit, 3…) or **zpub** (native segwit,
bc1q…), an **output descriptor** as Sparrow, Nunchuk or Bitcoin Core export it (`pkh`,
`sh(wpkh)`, `wpkh`, `tr` for taproot, or a `wsh` multisig, each key with its origin and a `/0/*`,
`/1/*` or `/<0;1>/*` ending, its checksum checked), or addresses, one a line. A multisig wallet's
addresses come from all its keys. Taking a key out stops watching its addresses; its recorded
transactions stay as they are.

> Never enter a seed phrase or a private key: the form clears anything that looks like one at
> once, and MoolaKata never stores or logs it.

## Gap limit

How many unused addresses past the last used one are watched on each chain. 20 suits most
wallets.

## Watched {#watched}

How many addresses are watched and how many have been used, and when the explorer or node in
Settings › Bitcoin last checked them. **Addresses** lists them: receive and change, by index.

## Check now

Reads the wallet from the explorer or node in Settings › Bitcoin now, rather than at the next
hourly check. Each confirmed transaction is recorded once: bitcoin received as a transfer in
(enter its cost basis from the Transactions tab, or Taxes shows it as missing), and bitcoin sent
as a transfer out, its network fee included. A transfer out that was a sale or a payment can be
changed to one.

## What is recorded

Each transaction once it has 6 confirmations, about an hour. Bitcoin received is a transfer in,
its basis to be entered unless it is matched to a transfer out of another of your accounts; bitcoin
sent is a transfer out, and its network fee a sale of the fee's sats at that day's price, beside a
fee of the same amount. A transaction the explorer or node no longer has is marked _no longer on
the chain_, never deleted: keep it, or delete it.

## Transfers between your accounts

A transfer out of one of your accounts and in to another of the same amount, within 3 days, is
offered as a pair. **Match them**, and the coins arrive with the lots they left with: the basis and
the day each was acquired carry over, so nothing is taxed or missing a basis.
