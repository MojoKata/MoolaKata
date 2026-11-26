# S1.6. Self-custody wallets

6. **Self-custody wallets** hold **bitcoin**. Other coins and chains come later ([F#570](https://github.com/MojoKata/MoolaKata/issues/570)).
   1. **What the account holds**: addresses, an **xpub/ypub/zpub**, or an **output
      descriptor**, from which addresses are derived (with a gap limit of 20 unused addresses
      by default). Where a choice isn't settled here, MoolaKata does as Sparrow does, so a
      wallet exported from Sparrow derives the same addresses.
      1. An xpub's addresses are legacy (1…), a ypub's nested segwit (3…) and a zpub's
         native segwit (bc1q…), on the receive chain (0/i) and the change chain (1/i).
         Addresses typed are checked: legacy, script (3…), native segwit and taproot (bc1p…).
         Mainnet only: a testnet key or address is refused.
      2. Each chain is derived until the gap limit (1 to 200) of addresses in a row past the
         last used one are unused; when the explorer or node finds one used, more are
         derived, at most ten rounds in one check, so a long-used wallet fills in over a few
         hourly checks. The account's Settings lists the addresses watched, by chain and
         index.
      3. Taking a key or address out of the list stops watching its addresses. Its recorded
         transactions stay as they are; they are no longer checked against the chain (S1.6.2.7)
         unless a key still in the list brought them too, and are checked again when it is
         typed in again.
      4. **Descriptors**, as Sparrow, Nunchuk and Bitcoin Core export them: single-key
         `pkh()`, `sh(wpkh())`, `wpkh()` and `tr()` (taproot, BIP 86), and multisig
         `wsh(sortedmulti(k, …))` and `wsh(multi(k, …))` of at most 15 keys, each key with
         its origin (`[fingerprint/path]xpub…`) and a `/0/*` and `/1/*` or `/<0;1>/*`
         ending. The descriptor's checksum is checked when it has one. A multisig wallet's
         addresses are derived from all its keys, and only its public keys are ever held.
         Other forms (`sh(wsh(…))`, a taproot descriptor with scripts) are refused, saying
         so. Miniscript policies beyond these come after the first release
         ([F#566](https://github.com/MojoKata/MoolaKata/issues/566)).
   2. **Where balances and history come from**, set by an admin in Settings › Bitcoin:
      1. a **public explorer** with the Esplora API (mempool.space suggested, or Blockstream).
         No wallet is read until an admin saves Settings › Bitcoin (R3.5), and until then a
         wallet says it waits for that;
      2. **the household's own node**: its own mempool or Esplora instance, an **Electrum
         server** (Fulcrum, electrs), or **Bitcoin Core** over RPC with a watch-only
         descriptor wallet. An own node keeps the household's addresses private, and is
         recommended. Its address is named by the admin, so the egress guard (S13.5) lets
         MoolaKata reach it on the LAN; its credentials are a secret (S14.4).
      3. **How each is read.** Esplora: each address's transactions over HTTPS, with every
         input's previous output, so each transaction's effect on the wallet is known. An
         Electrum server: each address's history by its script hash over TCP (TLS by default),
         and the raw transactions, read by MoolaKata; its certificate is trusted on first use
         (below). Bitcoin
         Core over JSON-RPC: a watch-only descriptor wallet for each wallet account, named
         `moolakata-` and a random name given with its first keys and kept with the account,
         never the account's id (schema.md §2); its keys imported as descriptors over the
         addresses derived, rescanned from the start the first time, then its transactions
         listed. The wallet is the node's own, watching the account's descriptors on the
         chain; MoolaKata keeps the account, its descriptors, its transactions and the
         wallet's name, and reads the same wallet again under that name. Only public keys and
         addresses are ever sent.
      4. **An Electrum server's certificate** is trusted on first use: **Test** in Settings ›
         Bitcoin shows its SHA-256 fingerprint, an admin confirms it, and it is kept. A server
         that later presents another certificate is refused, and admins alerted (*the node's
         certificate changed*), until an admin confirms the new one, as Sparrow does. Until
         one is confirmed, the server is only tested, never read.
      5. **When**: every hour, and at once with the wallet's **Check now**. **Test** in
         Settings › Bitcoin asks the saved explorer or node for the chain's height. A failure
         lasting past the alert threshold alerts admins and each wallet's owner (S12.11); its
         message never names an address or an amount.
      6. **What is recorded**: each transaction once, by its txid, once it has **6
         confirmations** (about an hour); until then it waits. A transaction its owner
         deleted is not recorded again. Bitcoin received is a **transfer in** of BTC
         without a basis, to be entered (Taxes lists it as missing) unless it is matched
         to a transfer out of another of the owner's accounts (S1.7.1);
         bitcoin sent is a **transfer out** of what left for others, and its network fee a
         sale of the fee's sats at that day's price beside a fee of the same amount, so the
         cash is unchanged (S8.19). In a transaction others put inputs into too (a coinjoin),
         the wallet's share of the fee is at most what it put in less what came back to it,
         never the whole transaction's, and the memo says it is a share; a fee recorded before bitcoin has a price is valued at the
         next check. A transfer out that was a sale or a payment is changed to one by its
         owner. The first
         coins held start a price refresh, so the wallet is valued at once.
      7. **A reorganised chain**: a recorded transaction that the explorer or node no longer
         has is never deleted silently. Once two reads in a row miss it, it is marked *no
         longer on the chain* and the owner alerted, to keep or delete it; a transaction kept
         stays kept.
   3. The form **refuses anything that looks like a private key or seed phrase** (WIF, 64
      hex digits, 12 or 24 BIP-39 words, an extended private key such as an xprv), says why,
      and never stores or logs it. The browser clears it from the form as it is typed, before
      anything is sent; the server checks again and its refusal never repeats it.
   4. **Amounts in sats.** Bitcoin is counted in whole **sats** (100,000,000 to the bitcoin),
      as bitcoin itself counts: never a fraction of a sat. A wallet's balance is sent as an
      integer of sats (S13.8.2), exact in every client since no amount of bitcoin reaches
      2^53 sats; a transaction's or a lot's quantity is kept as an exact decimal of bitcoin
      with 8 places (S14.3), the same whole number of sats. Each user chooses in Profile
      whether they are shown as **BTC** (`0.12345678 BTC`, the default) or **sats**
      (`12,345,678 sats`);
      a quantity of bitcoin is typed in the same unit, whole sats when sats are chosen (a
      trade's, its lots' and its picks'), and the conversion is only in how they are shown
      and typed. A price is per bitcoin, in dollars.
