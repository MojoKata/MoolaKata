# The manual test plan

What the build can't try by itself (requirements S17.9.7.8): each test names the environment
it needs, its steps and what passing looks like. The build proves the same code against mocks
(`web/dev.sh mocks`, the connector's fakes, the arm64 image under emulation); these runs prove
it against the real thing. A release says which of them were run, by whom and on what, and
which were not.

| Id | Test | Needs |
|---|---|---|
| T1 | Wallets against Fulcrum | an Electrum server (Fulcrum) on the LAN |
| T2 | Wallets against electrs | electrs |
| T3 | Wallets against Bitcoin Core | Bitcoin Core 27 or later with RPC on |
| T4 | Wallets against a self-hosted mempool | a mempool or Esplora instance |
| T5 | A link over an overlay network | two servers on Tailscale, WireGuard or ZeroTier |
| T6 | A link over a forwarded port | two networks, one with a forwarded port or a reverse proxy passing `/link/` |
| T7 | The arm64 image on real hardware | a Raspberry Pi 4 or 5, or an arm64 NAS, with Docker |
| T8 | The Schwab driver with a real account | a Schwab developer account with an app approved for the Trader API |
| T9 | OFX Direct Connect with a real institution | an institution still running an OFX server, and its ORG and FID |
| T10 | An install on Proxmox | a Proxmox host |
| T11 | An install on TrueNAS | a TrueNAS Community Edition box |
| T12 | A restore onto a new host | a second machine or a scratch VM, and the phrase from its offline copy |
| T13 | The connector on another machine | a laptop reaching the server's address |

Each test starts from a server at the release being tested, installed as `operations.md` says,
with the dev seed's figures where a figure is named.

## T1–T4: wallets against a live node

**Needs:** the node, reachable from the server's host, and a bitcoin wallet whose xpub (or
descriptor) and a few of whose transactions are known. Mainnet.

1. Settings › Bitcoin: choose the node's kind, enter its host, port and (for Core) its RPC user
   and password; **Test**. Passing: *answered: block N* with the current height; for an
   Electrum server with TLS, its certificate's SHA-256, which you confirm and Test again.
2. Make a `crypto-wallet` account with the xpub. Passing: Settings lists the derived addresses
   on both chains, 20 past the last used.
3. **Check now** on the wallet. Passing: every known transaction appears once, with its date
   and net amount; the balance matches the wallet's own software; the network fee of a send
   is a sale of that many sats beside a fee (S8.19); nothing under 6 confirmations is
   recorded.
4. Receive a small amount to a fresh address past the gap. Passing: within an hour (or at
   once with Check now) the transaction appears and more addresses are derived.
5. For Core (T3): the node shows a wallet `moolakata-<account id>` with the descriptors
   imported, watch-only, rescanned from the start.
6. Stop the node for longer than Settings › Alerts allows. Passing: one alert for admins and
   one for the wallet's owner, naming no address or amount; both resolve when it is back.
7. For an Electrum server (T1, T2): replace its certificate. Passing: reads stop, admins are
   alerted *the node's certificate changed*, and Test shows the new fingerprint to confirm.

## T5–T6: a link across two real networks

**Needs:** two servers at the same release on two networks, admins on both.

1. On A, Settings › General: the public URL as B reaches it (over the overlay, or through the
   forwarded port, or the proxy passing only `/link/`); on B likewise.
2. A: Settings › Linked servers › Invite a server; B: Enter a link code; A: compare the
   fingerprints by phone, Approve. Passing: both show *active* within a minute, with the
   other's household name, users and version.
3. On A, share an account, a budget and a tax book with a named user of B; tick Include
   receipts on the account. On B, Create the access key, open the linked window, enter the
   words. Passing: every shared screen shows as the owner sees it, read only; receipts open;
   nothing shared appears in B's own lists or totals.
4. Make the two servers reach each other one way only (close the forwarded port on one side).
   Passing: the link keeps syncing from the side that can reach, and Settings says so.
5. Pause on B for `1h`. Passing: both show paused until then; exchanges stop; Resume now
   ends it early.
6. End the link on A. Passing: B learns at its next call; B's copy is deleted; A keeps its
   data.
7. With the proxy setup (T6), from outside the proxy: `/ui` answers 404 and `/link/v1/hello`
   answers.

## T7: the arm64 image on real hardware

**Needs:** a Raspberry Pi 4 (4 GB) or 5, or an arm64 NAS, with Docker, and the images built
with `--platform linux/amd64,linux/arm64`.

1. Load both images; install as `operations.md` §2; start; make the key in the welcome;
   restart and unlock with the phrase. Passing: `/healthz` says `locked` first, `docker compose ps` shows healthy within
   two minutes of the unlock, and the default admin's setup works.
2. Upload a receipt photo and a statement PDF. Passing: both are read; note the seconds each
   took (S9.8.4.5 expects 3–10 s a receipt on a Pi 5).
3. Run a day of use: imports, a backup at its time, a price refresh. Passing: no `unhealthy`,
   no restart, and memory stays under 2 GB with reading on (1 GB with it off).
4. Start the connector image, make its vault on its page and pair it there. Passing: it
   reports, and Settings › Connector shows it, linked to its page.

## T8: the Schwab driver with a real account

**Needs:** a Schwab developer account, an app approved for the Trader API with
`https://127.0.0.1` as its callback, and a brokerage account.

1. Profile › Connections › New connection: Schwab, the app key. Passing: within five minutes
   the connection says *needs a sign-in* with the sign-in address.
2. Open it, sign in at Schwab, paste the address you land on and the app secret; Seal and send.
   Passing: the sign-in address showed `api.schwabapi.com` as its host; the state turns *ok*
   within a minute (the landed address is exchanged within seconds, S18.5), listing the account
   by its last four digits.
3. On the brokerage account's Settings, turn on Sync using MoolaKata Connector, choose the
   connection and the account. Passing: within a day (or sooner after the connector's next
   run) positions, the last 45 days of trades and dividends, and the cash balance appear,
   matching Schwab's own pages; Activity shows each post as by the connector.
4. Wait eight days. Passing: the connection asks for a sign-in again, the owner is alerted,
   and Sign in again repeats step 2.

## T9: OFX Direct Connect with a real institution

**Needs:** an institution running OFX Direct Connect, its URL, ORG and FID (a directory such
as ofxhome.com lists them), a routing and account number, and a sign-in.

1. New connection: OFX Direct Connect with those settings, credentials sealed. Passing: *ok*
   within a day with the account's last four digits.
2. Sync a matching account. Passing: the OFX statement's transactions and balance arrive as
   an upload of the same file would; a second run adds nothing.
3. Change the password at the institution. Passing: the next run says *needs a sign-in* and
   the owner is alerted.

## T10–T11: Proxmox and TrueNAS

Follow `DEPLOY.md` §3 or §4 on the real host. Passing: the welcome makes the key and the
admin, and `/healthz` answers `ok`; a restart comes back locked and the phrase opens it with the data intact, a
snapshot of the host holds no key (search it for the keyring's fingerprint and the phrase's
words: neither is there), and the daily backup lands in `backups/`. Record what the page
didn't say and fix it.

## T12: a restore onto a new host

Follow `operations.md` §6.2 with the phrase read from its offline copy, the receipts directory
restored from the host's own backup. Passing: the restore refuses a changed backup, a wrong
phrase, and accepts the real one with the real phrase; the server starts locked and unlocks
with the phrase; every account is there, every receipt opens, Settings › Storage counts no
file no record names (or only those written after the backup), and linked copies pull
again. Record the time it took.

## T13: the connector on another machine

**Needs:** a laptop on the household's overlay, or whose address can be added to Settings ›
Network › Allowed to connect.

1. Run the connector image on the laptop with its own volume, its page's address in
   `MOOLAKATA_CONNECTOR_NAMES`; make its vault on its page; restart it and unlock it there;
   pair it there with a code from the server. Passing: both fingerprints match; the server shows
   it paired, linked to its page, and, until Confirm is pressed, no sign-in can be sealed for
   it, and its page says *not confirmed yet*; Pair with wrong words is refused, and logged with
   the address it came from.
2. Over a network you don't trust (a café's Wi-Fi), with MoolaKata behind a public certificate,
   let the connector report. Passing: the reports go through; with a relay in the path that
   presents another certificate, the connector sends nothing and says why; the laptop's address
   outside the allowed ranges is refused (404) until it is added.
3. Close the laptop for twenty minutes. Passing: admins are alerted *not heard from*; it
   resolves when the laptop is back and reports.
4. With an OFX Direct Connect Connection working, change its server address in Profile ›
   Connections. Passing: the next run sends nothing, the Connection reports *needs a
   sign-in: the server address changed*, and entering the sign-in again makes it run.
