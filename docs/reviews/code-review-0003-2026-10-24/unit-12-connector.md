# Code review 3, unit 12: connector

**Started:** Oct 24, 10:50 PM (Chicago). **Commit read:** `6916954`. **Scope:** full, quick
(no §8 checker; every claim at 0 confirmations). Work-pad ids `U12-<n>`.

## Brief (§7)

### 1. Sections, code and tests (map.md)

- **Sections:** S18 (`docs/requirements/S18-connector.md`, 407 lines), with
  `docs/connector-protocol.md` (343 lines) as its protocol, and the README's R1–R3 lines they
  rely on (R1 decisions on the connector, R2.21–R2.23 and R2.26, R3.1, R3.6).
- **Code** (5,355 lines in 30 files): the connector, `connector/` (`Dockerfile`, `.dockerignore`,
  `pyproject.toml`, `requirements.txt`, and `moolakata_connector/`: `__init__`, `client`, `core`,
  `drivers/__init__`, `drivers/ofx_direct`, `drivers/schwab`, `keys`, `main`, `page.py`,
  `page.css`, `sealed`, `signing`, `sock`, `vault`, `words`); MoolaKata's side,
  `web/server/src/moolakata/connector/` (`__init__`, `files`, `manage`, `routes`, `sealed`),
  `store/entities/connector.py`, `store/tables/connector.py`, `ui/connections.py`,
  `ui/connector.py`; the browser's `web/ui/components/connections.js` and `connector.js`.
  Migrations of its tables: 0011, 0012, 0020, 0027 (and 0013, 0014 where they touch it).
- **Tests** (2,313 lines): `connector/tests/` (`conftest`, `test_core`, `test_drivers`,
  `test_end_to_end`, `test_page`); `web/server/tests/test_connections.py`, `test_connector.py`.
- **Guides:** `settings-connector.md`, `account-settings.md` (connections), `dialog-connector-pair.md`,
  `dialog-pair.md`, `dialog-connection.md`, `dialog-add-source.md`.

### 2. Delta (delta.txt, unit 12)

Content changed 2,052 of 5,355 lines (38%); 5 new files. New since review 2's `294792b`:
`client.py` (205), `main.py` (251), `page.py` (719), `page.css` (244), `__init__.py` (7) and
`test_page.py` (288): the connector's own HTTPS page (S18.11) and its client were written whole
after review 2. Large changes: `core.py` +220/−76, `manage.py` +101/−16, `routes.py` +40/−21,
`keys.py` +29/−10, `vault.py` +29/−13, `signing.py` +16/−5, `schwab.py` +16/−4, `test_core.py`
+339/−28, `test_end_to_end.py` +121/−34, `test_connector.py` +160/−28. Commits: `38397b7` (the
connector's page, the rename), milestone 9 part 3 `42a225b` (C23, K12) inside `e0db4e2`'s
history, `b14b5cb` milestone 8 part 8 (K12 in part, K20, K21, K24, B30, B31, 11b).

### 3. Earlier reviews' findings in this area, and their state (review 2 §12.2)

| Id | What | State given | To re-check |
|---|---|---|---|
| R1 F2 | sealing key beside the vault | done: private half in the vault, box only while unlocked | vault holds it; box withheld while locked |
| R1 F3 | MoolaKata steers hosts and the folder | done: credential bound to host; Folder driver gone | binding before every run |
| R1 F7 | pairing live before fingerprints compared | done: confirmed state | no box, file or sign-in before confirmed |
| R1 C4–C6 | threat-model statements | done (S18.2.4 rewritten) | S18.2.4 against the code |
| K3 | TLS off; `hello`'s key not hashed | done (part 2), C23 in m9 part 3 | TLS verified/pinned in `client.py`; key hashed |
| K12 | credential bound to whatever host MoolaKata names | m9 part 3 | box carries host; `connect` shows and confirms host |
| K20 | Unpair, address alert, `not-paired`, `reset` | done | each of the four points |
| K21, P4 | Folder driver | dropped (rejected idea 21) | no Folder driver left |
| K24 | sealing key unsigned; sign-in URL; box time; `taken` deletes newer; allowlist and answer ceiling; Schwab `state` | done | each of the six points |
| B30 | crash loop before socket | done | socket first, retry with growing wait |
| B31 | failed `pair` overwrites pairing | done | temp file and rename |
| B42 | report after each run, admin alert | done but its first part (dropped) | report after each run |
| N17 | per-driver allowlist test | done | test exists |
| C22, C23, C24–C27, C30 | protocol wording; key hash; `removed`; R3.1 | done | spot-check |
| 11b | report every 15 s while a sign-in waits | done | S18.5 |

### 4. Phase 1 claims on these sections

- **D3-10** (pair fields `sealingSig` vs `sealingSignature`; `certificate`/`confirmed` in the answer),
  **D3-11** (which refusals are unsigned), **D3-12** (a restore older than the pairing makes the
  connector delete every credential), **D3-13** (`days` missing from `ofx-direct`'s settings),
  **D3-14** (which address the pairing code carries): judge the code against both readings.
- **DC-13** (the connector's file limit names one of two upload settings): unit 10 found
  `connector/files.py` uses `importMaxMb` (S16.8); confirm from this side.
- **D2-21** (Unpair "never a pairing code … which it withdraws as well"): judge which the code does.
- **D2-14** (accepting the connector's address not in S13.7.2's list): judged in unit 07 as far
  as S13.7.2; check the route here.
- **D2-18** (the connector's welcome keeps 20 for an hour): check `page.py`.
- **D2-11** (Profile › Connections): only as far as the guide.
- **D3-15** ("Allowed to connect"): naming only; no code bearing expected.
- Q30 (how the connector stores its secrets) is open, and the identity key beside the vault is
  a stated choice: neither raised again without a new reason.

### 5. Untraced candidates and uncited first-level items

- Cite no section: `connector/moolakata_connector/sealed.py`, `signing.py`,
  `web/server/src/moolakata/connector/__init__.py`.
- Uncited first-level item: **S18.2** (built under other words, or not built).
- Earlier units' claims near this one, not to be repeated: U06-14 (statements through the
  receipt reader), U09-6 (MoolaKata's own certificate), U09-11 (OpenAPI codes), U09-15 (alert
  naming the owner), U09-1 and U09-4 (withheld: uploads before sign-in; gzip bombs through
  `net.Client`), U10-13 (Settings order), U11 (packaging).

## Claims

### U12-1: withheld

- **Kind:** security. **Severity:** Med. Withheld (`withheld.md`, docs/REVIEW.md §2).

### U12-2: withheld

- **Kind:** security. **Severity:** Med. Withheld (`withheld.md`, docs/REVIEW.md §2).

### U12-3: one option trade in the Schwab window makes the driver's whole OFX file unreadable

- **Kind:** bug. **Severity:** Med. **Req:** S18.9.2 ("positions, transactions and balances,
  posted as OFX"), S18.8, S3 (options).
- **Code:** `connector/moolakata_connector/drivers/schwab.py:93-110`, `_trade`, writes an
  option trade as `BUYOPT`/`SELLOPT` with no `SHPERCTRCT`:
  ```text
      tag = f"{side}OPT" if opt else f"{side}STOCK"
      ...
          f"<UNITS>{qty}<UNITPRICE>{_num(item.get('price'))}<COMMISSION>{fees}"
          f"<TOTAL>{_num(t.get('netAmount'))}<SUBACCTSEC>CASH<SUBACCTFUND>CASH</INV{side}>"
          f"{typ}</{tag}>"
  ```
  OFX 1.0.2 requires `SHPERCTRCT` in both aggregates, and the server's reader
  (`web/server/src/moolakata/importers/ofx.py:78-87`, ofxtools) refuses the file.
- **What goes wrong:** an owner who bought or wrote one option contract in the last 45 days:
  the driver's file for that account (all its trades, dividends, positions and cash) is
  refused as a whole, every day, for 45 days after each option trade. With U12-5 and U12-6 it
  also stops every other Connection's posts.
- **Run:** yes, `/home/dev/.claude/jobs/b8ac83ff/tmp/u12/schwab_ofx.py` and `schwab_opt.py`
  (outputs `.txt` beside them): `to_ofx` with a stock buy reads (rows `buy`), the same with an
  option bought or sold gives `OFXSpecError: Can't set BUYOPT.shperctrct to None` (and
  `SELLOPT`), `ReadError` from `importers.ofx.read`. A name with `&` (*AT&T INC*) reads.
- **Remedy:** write `<SHPERCTRCT>` (Schwab's `instrument.optionDeliverables` or 100) in
  `BUYOPT`/`SELLOPT`; a driver test that runs `to_ofx` with an option trade through the
  server's OFX reader, as `test_end_to_end` does for stocks.
- **Alternatives:** leave option trades out of the file, saying so in the Connection's
  message, until they are written whole.

### U12-4: the Schwab driver takes opening or closing from the sign, and writes every position as stock

- **Kind:** wrong figure. **Severity:** Med. **Req:** S18.9.2, S3.2 (the four option trades),
  R3.2 and S1.3.3.8.2 (positions in a file are a check).
- **Code:** `connector/moolakata_connector/drivers/schwab.py:100-104`:
  ```text
      typ = (
          f"<OPT{side}TYPE>{'BUYTOOPEN' if qty > 0 else 'SELLTOCLOSE'}"
          if opt
          else f"<{side}TYPE>{side}"
      )
  ```
  `:128-136`, `_position`, writes every position as `<POSSTOCK>`, options, funds and bonds
  too; `:174-177` drops every other transaction type (`else: continue`), Schwab's
  `RECEIVE_AND_DELIVER` (expiry, assignment, exercise, securities moved in) among them.
- **What goes wrong:** once U12-3 is fixed, a covered call written (sold to open, Schwab's
  `positionEffect: OPENING`) is imported as `SELLTOCLOSE`, closing a long call the owner never
  held; buying it back is `BUYTOOPEN`, a new long. The lots, the strategy and the gains are
  wrong, and an expiry or assignment never arrives, so the position check shows a difference
  that no transaction explains. The reader maps these exactly as written
  (`importers/ofx.py:233-241`).
- **Run:** no; rests on reading (the OFX reader's mapping read at `importers/ofx.py`).
- **Remedy:** take the trade type from `transferItems[].positionEffect` (OPENING, CLOSING):
  BUYTOOPEN, BUYTOCLOSE, SELLTOOPEN, SELLTOCLOSE, and SELLSHORT/BUYTOCOVER for stock; write
  `POSOPT`, `POSMF`, `POSDEBT` by asset type; map `RECEIVE_AND_DELIVER` expiries and
  assignments to `CLOSUREOPT`, or name what was left out in the Connection's message.
- **Alternatives:** none reasonable: the import has the four option trades (review 2's B5).

### U12-5: a file MoolaKata can't read is answered with an unsigned 500, not a signed refusal

- **Kind:** bug. **Severity:** Med. **Req:** S18.8 ("A file refused for any other reason is
  dropped, and its Connection shows the refusal"), `connector-protocol.md` §3.3 (every answer
  to a signed call is signed), §7 (`file-refused`).
- **Code:** `web/server/src/moolakata/connector/files.py:77-97` reads the file outside the
  `try` that turns a `ReadError` into a refusal (`:100-108`):
  ```text
      if ofx.looks_like_ofx(data):
          parsed = parsing.read_ofx(data)
      elif csvfile.looks_like_csv(data):
          ...
          parsed = parsing.read_csv(data, json.loads(saved.columns))
  ```
  `ReadError` is a `ValueError` the route doesn't catch (`connector/routes.py:232-237` catch
  `files.Limit` and `files.Refused` only), so the app's last handler answers 500
  `server-error` (`errors.py:124-130`), without the connector's signature.
- **What goes wrong:** an OFX server answers with a statement the reader can't parse (or the
  Schwab driver's file of U12-3): MoolaKata logs an unhandled error each time and answers 500
  unsigned; the connector can't tell it from a forged answer (U12-6), and the owner is never
  told why nothing arrives.
- **Run:** yes, `/home/dev/.claude/jobs/b8ac83ff/tmp/u12/test_u12_unreadable.py` (output
  `test_u12_unreadable.txt`): the Schwab driver's file with one option trade, posted by a
  paired, confirmed connector, got `500 application/problem+json`, no `MK-Conn-Signature`.
- **Remedy:** move both reads inside the `try` (or catch `ReadError` around them) and refuse
  `file-refused` with the reader's message, signed; a server test posting an unreadable OFX.
- **Alternatives:** the connector routes catch every exception and answer a signed
  `server-error`, so a fault there is never unsigned.

### U12-6: an unsigned answer, or a dropped connection, while posting files stops every later post and the after-run report, for good

- **Kind:** bug. **Severity:** Med. **Req:** S18.8 (a file refused for the limit is kept;
  any other refusal drops it), S18.5 (a report after each run), `connector-protocol.md` §7.
  Bears on D3-11.
- **Code:** `connector/moolakata_connector/core.py:449-463`:
  ```text
          for f in c.backlog:
              try:
                  out = self._post(c, f)
              except ServerError as e:
                  ...
                  continue
              ...
          c.backlog = kept
  ```
  An answer without `MK-Conn-Time` raises `signing.Refused("answer-unsigned")`
  (`signing.py:58-63`, via `client.py:171-174`), which isn't a `ServerError`; an `OSError`
  or `EgressRefused` from the transport isn't either. Either leaves `_post_backlogs` at once:
  `c.backlog = kept` never runs, the Connections after it are never posted, and the report
  after the runs (`core.py:320-322`) is skipped; `run_forever` waits and tries again
  (`:265-269`).
- **What goes wrong:** unsigned answers to a post come from MoolaKata itself: the 500 of U12-5,
  the body limit's 413 `too-large` and 429 `uploads-in-flight` (`middleware.py:251-270`, `:300-310`), and
  the 503 `locked` (S13.6). For a file that always gets one (U12-3 with U12-5), every round
  posts that file first, fails, and stops: the other Connections' files wait in memory until
  the connector restarts, and the restart's run fetches the same file again. Nothing reaches
  MoolaKata to say so (no report follows the run).
- **Run:** no; the connector side rests on reading; the unsigned 500 was run (U12-5).
- **Remedy:** catch every exception per file in `_post_backlogs`: keep the file for a later
  round on a transport error, `locked`, `limit` or `uploads-in-flight` (signed or not), drop it
  and set the Connection `failing` on anything else, and go on to the next file and
  Connection; always send the after-run report. A core test with an unsigned 500 on one file.
- **Alternatives:** the server never answers the connector unsigned except `locked` (the body
  limit signs too), as D3-11's remedy reads, and the connector drops any other unsigned
  answer per file.

### U12-7: new credentials for an existing OFX Connection are sealed with no host, so the connector refuses every one

- **Kind:** bug. **Severity:** Med. **Req:** S18.6.4 (**Sign in again**, **Change
  credentials**), S18.7.1 ("seals, with the credentials, the host the dialog shows the owner
  they go to"), S18.7.3 (after a changed address "the owner enters the credentials again,
  knowingly, for the new host"). Review 2's K12 (the browser seals the host the dialog
  showed), marked built in milestone 9.
- **Code:** `web/ui/components/connections.js:163`:
  ```js
      const host = f.driver === 'ofx-direct' ? hostOf(c.settings?.url || f.url) : null;
  ```
  For an existing Connection `c` is the row from `/profile/connections`, whose `ConnectionOut`
  has no `settings` (`web/server/src/moolakata/ui/connector.py:35-51`), and the dialog shows
  no address field for one (`connections.js:224`, `${existing ? null : html`…), so `f.url`
  stays `''` (`:113`) and `hostOf('')` is `null`. The connector then compares the box's host
  with the settings' (`connector/moolakata_connector/core.py:381-384`):
  ```text
          if host != self._binds(c):
              c.state, c.message = "failing", "the credentials were sealed for another server"
              return
  ```
- **What goes wrong:** Alice's credit union password changes; the run reports *needs a
  sign-in*; she clicks **Sign in again**, types the new password, **Seal and send**. The box
  says `host: null`, the connector refuses it as *sealed for another server*, the box is never
  taken (it stays in MoolaKata, offered at every report), and the Connection never works
  again. The same after S18.7.3's changed address. Only removing the Connection and making a
  new one (and setting each account's sync again) gets past it. Nor does the dialog show the
  owner the host the sign-in will go to, which S18.7.1 asks of it.
- **Run:** no; rests on reading (the chain above, end to end).
- **Remedy:** `ConnectionOut` carries the host a credential would be bound to (the settings'
  `url` host, for a driver with one), the dialog shows it ("sealed for ofx.example.com only")
  and seals that host; a browser test of **Change credentials** on an OFX Connection, and an
  end-to-end test that the connector takes it.
- **Alternatives:** the dialog for an existing OFX Connection shows the address field filled
  from the settings, so the owner sees and may change it (with the password again, as the
  PATCH already asks).

### U12-8: Settings › Connector doesn't show the host each Connection's credentials go to

- **Kind:** not built. **Severity:** Low. **Req:** S16.18 ("every Connection's state, owner,
  accounts and the host its credentials go to"), R3.1 ("each Connection's host shown in
  Settings › Connector").
- **Code:** `web/ui/components/connector.js:173-191`: the table's columns are Connection,
  Owner, Accounts and State; `ConnectionOut` (`ui/connector.py:35-51`) has no host or settings
  to show.
- **What goes wrong:** an admin can't see that an OFX Connection's address names an
  unexpected host (S18.2.4.1's changed settings), which is what R3.1 puts on this screen as
  the account of the connector's outbound calls.
- **Run:** no; rests on reading.
- **Remedy:** a Host column: the settings' `url` host for OFX Direct Connect, the driver's
  declared host (`api.schwabapi.com`) for Schwab; with U12-7, the same value the dialog shows.
- **Alternatives:** none needed.

### U12-9: `pair` shows the fingerprint MoolaKata's answer names, not the one it works out

- **Kind:** differs. **Severity:** Low. **Req:** S18.4.2 ("the connector shows its own,
  worked out from its identity key, never one an answer names"), `connector-protocol.md`
  §4.1.3. Review 2's K3 point 3, marked done.
- **Code:** `connector/moolakata_connector/core.py:138`:
  ```text
          return keys.short(out.get("connectorFingerprint", pairing.fingerprint))
  ```
  and MoolaKata's answer names one (`web/server/src/moolakata/connector/manage.py:204`,
  `"connectorFingerprint": keys.fingerprint(caller_public)`). Both the page
  (`page.py:659-668`) and `pair` on the host (`main.py:194-195`) show what comes back.
- **What goes wrong:** the comparison is meant to be two independent workings; here the
  connector's side shows the server's. Today the answer is signed by the paired key and names
  the caller's own, so the two agree; a server that answered otherwise (a bug, or a changed
  server) would have the connector show whatever it said.
- **Run:** no; rests on reading.
- **Remedy:** `return keys.short(pairing.fingerprint)`; refuse the pairing (or warn) when
  the answer names a different one.
- **Alternatives:** none needed.

### U12-10: the pairing code carries the link address before the public URL

- **Kind:** differs. **Severity:** Low. **Req:** S18.4.1 ("MoolaKata's address"),
  `connector-protocol.md` §1.1, §4.1; `operations.md` §8, `DEPLOY.md` §8.3. D3-14.
- **Code:** `web/server/src/moolakata/connector/manage.py:72-73`:
  ```text
  def own_address(s) -> str | None:
      return settings.get(s, "linkAddress") or settings.get(s, "publicUrl")
  ```
- **What goes wrong:** D3-14's case, in the code: a server with a link address set for a
  proxy that passes only `/link/*` (operations §1.1) puts that address in the pairing code;
  the connector's `hello` to `/connector/v1/hello` there is answered 404 and the pairing fails
  `not-moolakata`, though `DEPLOY.md` §8.3 told the admin the code carries the public URL.
  The code follows `operations.md` §8's "the public URL, or the link address", in the other
  order, and neither D3-14 reading (public URL alone; or an address of its own).
- **Run:** no; rests on reading.
- **Remedy:** with D3-14 decided: the public URL first (`publicUrl or linkAddress`), as DEPLOY
  says, and the screen's text says which address the code carries.
- **Alternatives:** an address of the connector's own in Settings › Connector, defaulting to
  the public URL (D3-14's alternative).

### U12-11: unpairing while the vault is locked forgets the pairing but keeps every credential and the sealing key

- **Kind:** differs. **Severity:** Low. **Req:** S18.4.4 ("at which the connector deletes the
  credentials it held for that server and its sealing key"), S18.11.4 (**Unpair** "forgets
  the pairing and the credentials"), `connector-protocol.md` §4.1.4.
- **Code:** `connector/moolakata_connector/core.py:150-160`:
  ```text
          keys.forget(self.data / "pairing.json")
          ...
          if not self.vault.locked:
              for cid in self.vault.ids():
                  self.vault.delete(cid)
              self.vault.keep_sealing_key(b"")
  ```
  reached from a signed `not-paired` (`:307-310`), which comes at any report, locked or not,
  and from `moolakata-connector unpair` (`main.py:227`, `sock.py:66-68`), which needs no
  words.
- **What goes wrong:** an admin unpairs a connector in MoolaKata after a restart that left it
  locked (or runs `unpair` on its host): the connector forgets the pairing at once and, having
  no pairing, never reports again, so nothing later deletes the credentials or the sealing
  key. They stay in the vault until the next `pair` (which deletes them) or `reset`. The page's
  Unpair unlocks first (`page.py:675`), so it is only these two ways.
- **Run:** no; rests on reading.
- **Remedy:** keep a "forget on unlock" mark beside the vault when it is locked, and delete at
  the next unlock; `unpair` on the host asks for the words, or says what it kept.
- **Alternatives:** S18.4.4 says the credentials go at the next unlock.

### U12-12: anyone on the network can keep the connector from being unlocked, the host's `unlock` included

- **Kind:** security. **Severity:** Low. **Req:** S18.3.3 ("Five wrong attempts in a row, on
  its page and at the command line alike, make the next wait 15 minutes"), S18.2.4.5 (someone
  on the network "can't unlock, lock, pair, unpair or reset it"), S18.3.2.
- **Code:** `connector/moolakata_connector/vault.py:87-89, 102-106`: one counter and one wait
  for the page and the socket, checked before the words:
  ```text
          if self.waiting():
              raise VaultError(f"wait {int(self.waiting() // 60) + 1} minutes: too many wrong words")
  ```
- **What goes wrong:** after a restart, a device on the LAN posts five wrong phrases to
  `/unlock` every 15 minutes (the form needs no session; `_form`'s origin check is a browser's
  rule, `curl` sets `Origin` itself). The household's correct words, on the page or with
  `docker compose exec connector moolakata-connector unlock`, are refused *wait 15 minutes*
  for as long as it goes on: the connector stays locked and fetches nothing. The wait protects
  nothing either: the key is 128 random bits (S18.3.1), which no guessing rate reaches. New
  reason against S18.3.3 as written: it hands the network the one thing S18.2.4.5 says it
  can't have, keeping the connector locked.
- **Run:** no; rests on reading.
- **Remedy:** count waits per address on the page; the host's socket (whose access is the
  authority, S18.3.4) is never made to wait. **Needs the user**: S18.3.3 states the shared
  wait.
- **Alternatives:** drop the wait (the key can't be guessed) and keep the logging of wrong
  attempts.

### U12-13: a mistyped word of the vault's phrase is written to the log

- **Kind:** security. **Severity:** Low. **Req:** S18.3.1 (the words are shown "never on
  standard output, so no log keeps them"), S18.3.3 (each wrong attempt logged with its
  address).
- **Code:** `connector/moolakata_connector/page.py:383-384`:
  ```text
          except VaultError as err:
              log.warning("wrong words on its page from %s: %s", self.client_address[0], err)
  ```
  and the error names the word (`words.py:46-47`, `f"word {n} ({token!r}) is not in the
  word list"`).
- **What goes wrong:** an admin types the 12 words with one slip (*abandn*): the container's
  log keeps `word 7 ('abandn') is not in the word list`, a word of the real phrase; each later
  slip adds another. The log goes wherever the host ships Docker's logs.
- **Run:** no; rests on reading.
- **Remedy:** log the address and the kind of refusal only ("not in the word list", "checksum",
  "another vault's"), never the token; the page may still show it to the person typing.
- **Alternatives:** none needed.

### U12-14: withheld

- **Kind:** security. **Severity:** Med. Withheld (`withheld.md`, docs/REVIEW.md §2).

### U12-15: `status`, the health check and its page wait for a whole round of reports, runs and posts

- **Kind:** bug. **Severity:** Low. **Req:** S18.3.2 ("The image's health check runs
  `status`, which answers whenever the connector runs … healthy means alive"), S18.11.3.
- **Code:** `connector/moolakata_connector/core.py:180-181` (`status` takes `self._lock`);
  `tick` holds the same lock through the report, every due driver run, every post and the
  second report (`:303-322`); the page's home and Unpair forms call `core.status()`
  (`page.py:425`, `:474`); `connector/Dockerfile:36-37` gives the check 5 seconds.
- **What goes wrong:** a Schwab Connection with four accounts, or an OFX server that is slow,
  makes a run of several calls of up to 60 seconds each (U12-16); a large post takes as long
  as the upload. For that whole time `moolakata-connector status` and the page hang. Three
  checks in a row past 5 seconds mark the container unhealthy, which an orchestrator that
  restarts unhealthy containers turns into a restart, and a restart locks the connector
  (S18.3.2). Someone opening its page to see what it does gets no answer.
- **Run:** no; rests on reading.
- **Remedy:** `status` reads a snapshot without the round's lock (the fields are set
  atomically, or copied under a short lock the round takes only to write them); the round
  holds the lock only around what it changes, not around network calls.
- **Alternatives:** the health check reads a heartbeat file the loop and the socket update,
  rather than asking the core.

### U12-16: "at most 60 seconds" is per socket operation, so an answer that trickles holds a call without end

- **Kind:** bug. **Severity:** Low. **Req:** S18.2.2 ("A call it makes … waits at most 60
  seconds, and reads at most 25 MB of an answer").
- **Code:** `connector/moolakata_connector/client.py:119-131`: `timeout=60` on the connection
  and the socket, then `r.read(MAX_ANSWER + 1)`. The timeout bounds each `recv`, not the call.
- **What goes wrong:** an institution's server (or anything an OFX Connection's `url` names)
  answers one byte every 50 seconds: the call never times out, reads up to 25 MB that way
  (weeks), and with U12-15 holds the whole loop: no report (MoolaKata alerts *not heard from*
  after 15 minutes, which is right), no other Connection runs.
- **Run:** no; rests on reading.
- **Remedy:** a deadline for the whole call (checked between reads, closing the socket past
  it), as the server's `net.Client` does for its 20 MB ceiling.
- **Alternatives:** none needed.

### U12-17: a box filed in the vault whose `credential/taken` failed is never acknowledged again, and marks the Connection failing at every report

- **Kind:** bug. **Severity:** Low. **Req:** S18.7.1 (the connector files the box and
  "confirms which box it took (by its time); MoolaKata then deletes that box"),
  `connector-protocol.md` §4.3.2.
- **Code:** `connector/moolakata_connector/core.py:385-391`:
  ```text
          if not isinstance(at, int | float) or at <= self.vault.sealed_at(c.id):
              c.state, c.message = "failing", "a box older than the credentials held was refused"
              return
          self.vault.put(c.id, opened.get("credentials") or {}, host, at)
          self.server.call(
              f"/connector/v1/connections/{c.id}/credential/taken", {"sealedAt": server_at}
          )
  ```
- **What goes wrong:** the `taken` call fails after the `put` (MoolaKata restarting and
  locked, a dropped connection): the exception also leaves `_apply` half done (the rest of the
  answer's Connections and its `removed` aren't applied that round). At the next report
  MoolaKata hands the same box again; its time equals the one filed, so it is refused as
  *older*, `taken` is never called, the box stays in MoolaKata for good, offered at every
  report, and every report says the Connection is *failing* until a run overwrites the state
  (once a day), then *failing* again at the next report. The owner sees "credentials sealed,
  waiting for the connector" (`connections.js:84-85`) for ever.
- **Run:** no; rests on reading.
- **Remedy:** a box whose time equals the credential's own is the one already filed: call
  `taken` for it again and change nothing else; catch a failed `taken` so the rest of the
  answer is applied.
- **Alternatives:** none needed.

### U12-18: OFX Direct Connect sends the username, password and settings unescaped, in Latin-1 with "?" for the rest

- **Kind:** bug. **Severity:** Low. **Req:** S18.9.1 (OFX 1.0.2 client, signing in with the
  username and password), R1.9 is not at stake (no amounts).
- **Code:** `connector/moolakata_connector/drivers/ofx_direct.py:106-110`:
  ```text
      user, password = credentials.get("username", ""), credentials.get("password", "")
      ...
          f"<SIGNONMSGSRQV1><SONRQ><DTCLIENT>{_stamp(now)}<USERID>{user}<USERPASS>{password}"
  ```
  and `:132`, `.encode("latin-1", "replace")`.
- **What goes wrong:** OFX 1.0.2 is SGML: `&`, `<` and `>` in an element's value must be
  written `&amp;`, `&lt;`, `&gt;`. A password `p<ss&word!` is cut at `<` by the server's
  parser; a password with a character outside Latin-1 (`€`) is sent with `?`. The server
  answers 15500, which the driver reports as *needs a sign-in: the institution refused the
  sign-in*, so the owner re-enters the same correct password and gets the same answer.
- **Run:** no; rests on reading.
- **Remedy:** escape every value written into the request (`&`, `<`, `>`); refuse a
  credential the request can't carry with a message that says so, rather than altering it.
- **Alternatives:** none needed.

### U12-19: a file over Settings › Imports' size is refused `file-refused`, not `too-large`

- **Kind:** differs. **Severity:** Low. **Req:** `connector-protocol.md` §7 (`too-large`,
  413, "a file over the upload size"), S16.8. DC-13.
- **Code:** `web/server/src/moolakata/connector/files.py:66-69`:
  ```text
      with srv.db.read() as s:
          limit = settings.get(s, "importMaxMb") * 1024 * 1024
      if len(data) > limit:
          raise Refused("file-refused", f"Files are up to {limit // (1024 * 1024)} MB.")
  ```
  after the owner's upload rate was spent on it (`:63-65`).
- **What goes wrong:** the connector drops the file either way (S18.8), but under the code
  the protocol reserves for content MoolaKata doesn't import; and a file above the body
  limit's cap gets the middleware's unsigned 413 instead (U12-6), so one case has two codes,
  signed and not. DC-13's reading holds: the limit is S16.8's (`importMaxMb`), not the
  receipts'.
- **Run:** no; rests on reading.
- **Remedy:** `too-large` (413), signed, for a file over `importMaxMb`, checked before the
  rate is spent; the protocol's §7 names S16.8 (DC-13's remedy).
- **Alternatives:** none needed.

### U12-20: Reset makes new words and forgets the pairing without telling MoolaKata

- **Kind:** differs. **Severity:** Low. **Req:** S18.3.4 ("deletes the vault, makes new
  words … and unpairs"), `connector-protocol.md` §4 (`unpaired`: "the connector was told to
  forget this server").
- **Code:** `connector/moolakata_connector/core.py:162-176`, `reset`, forgets `pairing.json`
  and replaces the vault, and makes no call; `unpair` (`:140-148`) calls
  `/connector/v1/unpaired` first.
- **What goes wrong:** after **Reset** on the page or `reset` on the host, MoolaKata still
  holds the pairing as live: Settings › Connector shows it paired and confirmed, owners can
  still seal credentials to its old sealing key (boxes the new vault can never open), and 15
  minutes later admins get *the connector hasn't been heard from*, which reads as an outage.
  The admin must Unpair in MoolaKata by hand before pairing again.
- **Run:** no; rests on reading.
- **Remedy:** `reset` calls `unpaired` (signed with the identity key it still has) before it
  forgets the pairing, as `unpair` does, and goes on if MoolaKata can't be reached.
- **Alternatives:** none needed.

### U12-21: the page's own certificate is written key first, neither through a temporary file

- **Kind:** bug. **Severity:** Low. **Req:** S18.11.1 (a certificate "made at its first start,
  kept in `tls/`"). The same pattern in MoolaKata's own certificate is U09-6 (2).
- **Code:** `connector/moolakata_connector/page.py:118-127`: the key is opened `O_TRUNC` and
  written, then `cert.write_bytes(...)`; `:95-101` keeps a pair whose certificate's names and
  dates still fit, without checking that the key matches it.
- **What goes wrong:** the connector is stopped (a `docker stop` past its grace, a full disk)
  between the two writes while remaking its certificate (names changed, or 30 days before the
  end): `key.pem` is new, `cert.pem` old. At every later start the old certificate still
  "fits", `load_cert_chain` fails, and `serve` refuses to start ("its page can't listen",
  exit 78), restarting for ever until someone deletes `tls/` by hand.
- **Run:** no; rests on reading.
- **Remedy:** write both to temporary files and rename the certificate last; at start, check
  that the key matches the certificate and make a new pair when it doesn't.
- **Alternatives:** none needed.

### U12-22: `init` writes the vault before its words are typed back

- **Kind:** differs. **Severity:** Low. **Req:** S18.3.1 ("the vault is made only once three
  of them, chosen at random, are typed back").
- **Code:** `connector/moolakata_connector/main.py:85-96`: `v.create()` writes `vault.json`
  first; the words are shown and checked after, and the file unlinked if they don't match.
- **What goes wrong:** the admin closes the terminal (or the `run --rm` container is stopped)
  while the words are on screen and before typing three back: a vault whose words may never
  have been written down stays, and the connector then starts asking for them; the only way
  on is `reset`. The page's welcome does it the stated way (the key held until the words come
  back, `page.py:601-635`).
- **Run:** no; rests on reading.
- **Remedy:** make the key in memory, show and check the words, then write the vault.
- **Alternatives:** none needed.

### U12-23: the connector's egress refuses 169.254.169.254 but not the IPv6 metadata address MoolaKata's guard refuses

- **Kind:** security. **Severity:** Low. **Req:** S18.2.2 ("It refuses loopback, link-local
  and cloud metadata addresses, as MoolaKata's egress guard does (S13.5)").
- **Code:** `connector/moolakata_connector/client.py:32-47` (`vetted`) refuses loopback,
  link-local, multicast and unspecified addresses; MoolaKata's guard also refuses
  `fd00:ec2::254` by name (`web/server/src/moolakata/net.py:25-28, 61-62`), which is a unique
  local address, not link-local.
- **What goes wrong:** a connector on an AWS host with IPv6 metadata enabled: an OFX
  Connection whose `url` names a host resolving to `fd00:ec2::254` (settings MoolaKata, or a
  compromised one, controls, S18.2.4.1) is reached; the credentials bound to that host are
  posted to the metadata service (which won't use them), and its answer is posted to
  MoolaKata as a file if it looks like OFX (it won't). Little to gain; the rule is stated
  as MoolaKata's and differs from it.
- **Run:** no; rests on reading.
- **Remedy:** the same `METADATA` set in `vetted`, and a test with each address.
- **Alternatives:** none needed.

### U12-24: `_check_settings`'s list branch serves only the Folder driver, which is gone

- **Kind:** untraced. **Severity:** Low. **Req:** — (rejected idea 21, S18.9).
- **Code:** `web/server/src/moolakata/ui/connections.py:116-122`:
  ```text
          if kind is list:
              ...
                  errors.append(FieldError(f"settings.{key}", "settings-invalid", "A list of rules."))
  ```
  No driver in `SETTINGS` (`:29-39`) has a list setting; the Folder driver's `rules` did. (The
  table's `driver IN ('folder', …)` check is kept on purpose, `:24-25`.)
- **What goes wrong:** nothing at run time; dead code that reads as if a driver took rules.
- **Run:** no; rests on reading.
- **Remedy:** remove the branch.
- **Alternatives:** none needed.

### U12-25: the connection and pairing guides say the account number is sealed and the keys are made only if missing

- **Kind:** differs. **Severity:** Low. **Req:** S12.7 (each screen's guide), S18.2.4.2 (the
  connector learns "an OFX server's address and account number"), S18.4.2 and
  `connector-protocol.md` §4.1.2 (a new identity key and a new sealing key at every pairing).
- **Code and what differs:**
  1. `web/ui/guides/dialog-connection.md`, *Account number*: "It is sealed with the
     credentials, never shown here." It is a setting (`accountId`), sent in the clear to
     MoolaKata (`connections.js:136-143`, `ui/connections.py:29-37`), stored there, and handed
     to the connector in every report's answer.
  2. `web/ui/guides/dialog-connector-pair.md`: the connector "makes its own keys if it has
     none"; `pair` makes both keys afresh every time (`core.py:114-115`).
  (`settings-connector.md:58`'s Folder driver is U10-17's.)
- **Run:** no; rests on reading.
- **Remedy:** correct both lines: the account number is a setting MoolaKata and the
  connector see; each pairing makes new keys.
- **Alternatives:** none needed.

## Judgements on Phase 1's claims and the earlier findings

### Phase 1

- **D3-10**: the code sends `sealingSignature` (§4.1.2's name, not the glance's `sealingSig`),
  with `version` but no `protocol` in the body (the header carries it, `client.py:161-165`);
  every report's answer carries `confirmed` (`manage.py:377`) and, for a server's own
  certificate, `certificate` (`routes.py:144-145`), which the connector reads
  (`client.py:175-180`). The code follows D3-10's remedy reading.
- **D3-11**: MoolaKata signs `limit` from the routes (`routes.py:71-73`, `:234-235`) and every
  refusal of a call with signing headers; the body limit's 413 and 429 and the 503 `locked` are
  unsigned. The connector acts on no unsigned answer and, while posting, stalls on one
  (U12-6). Neither reading is fully built.
- **D3-12**: a signed `not-paired` makes the connector delete everything (`core.py:307-310`),
  as the protocol's text says; D3-12's two codes are not built.
- **D3-13**: neither driver can get `days`: MoolaKata's settings for `ofx-direct` have no such
  field (`ui/connections.py:29-37`), so `settings.get("days") or 45` is always 45
  (`ofx_direct.py:157`, `schwab.py:263`). The code matches the "S18.9.1 drops `days`" reading;
  no separate claim.
- **D3-14**: the code puts the link address in the code before the public URL: U12-10.
- **DC-13**: the connector's files are held to `importMaxMb` (S16.8), DC-13's proposed
  reading, under the code `file-refused` rather than `too-large` (U12-19).
- **D2-21**: Unpair ends the paired connector and withdraws any code still out
  (`manage.py:242-259`): the safer reading.
- **D2-14**: Accept asks for the password again (`ui/connector.py:219`).
- **D2-18**: the page keeps 20 phrases on offer, an hour each (`page.py:33-34`, `:166-176`), as
  S18.11.2 says.
- **Q30**, and the identity key beside the vault: not raised again.

### Earlier reviews (re-checked against `6916954`)

| Id | Holds? | Where |
|---|---|---|
| R1 F2 | yes: sealing key in the vault (`vault.py:193-202`), box only to an unlocked, confirmed connector (`manage.py:369-373`) | |
| R1 F3 | yes: credential bound to its host, checked before every run (`core.py:414-424`); Folder driver gone | |
| R1 F7 | yes: no box, file or sealing before Confirm (`manage.py:371`, `routes.py:208-214`, `ui/connections.py:263-270`) | |
| K3 | TLS verified and pinned (`client.py:108-136`), `hello`'s key hashed (C23 below); point 3 (show its own fingerprint) half holds | U12-9 |
| C23 | yes: the key itself is hashed at pairing and at every attach (`core.py:83-85`, `:108-113`) | |
| K12 | half: the box carries the host, `connect` shows and confirms it (`main.py:203-208`, `core.py:247-252`), a changed address needs the password again (`ui/connections.py:228-232`); but an existing OFX Connection's new credentials are sealed with no host and never shown | U12-7 |
| K20 | Unpair ends the paired row and any code (yes); a new address stays alerted until accepted (yes, `manage.py:305-319`); `not-paired` deletes the credentials only when unlocked (half); `reset` unpairs on the connector's side but doesn't tell MoolaKata (half) | U12-11, U12-20 |
| K24 | sealing key signed and checked (yes); sign-in addresses (half holds: withheld, U12-1); box time (yes, `core.py:385`); `taken` names its box (yes, `manage.py:429`); allowlist refuses loopback and metadata, 25 MB ceiling (yes, but not the IPv6 metadata address); Schwab `state` (yes) | U12-1, U12-23 |
| B30 | yes: socket and page first (`main.py:136-138`), retry with a growing wait (`core.py:260-270`) | |
| B31 | yes: the pairing saved only after `pair` succeeds (`core.py:115-130`, `keys.py:82-107`) | |
| B42 | report after each run (yes, `core.py:320-322`), but skipped when a post fails unsigned | U12-6 |
| N17 | yes: `test_a_driver_run_reaches_its_own_hosts_and_no_other` | |
| 11b | yes: every 15 seconds for 10 minutes while a sign-in waits (`core.py:272-281`) | |
| K21, P4 | dropped with the Folder driver; only U12-24's dead branch is left | U12-24 |

### Uncited and untraced

- **S18.2** (no code cites it) is built under other words: the image's uid 10002, volume and
  socket folder (`connector/Dockerfile:21-24`), `MOOLAKATA_CONNECTOR_DATA` and `_SOCKET`
  (`main.py:20-21`), `pairing.json` at 0600 (`keys.py:92`), one way out with no redirect, 60 s
  (U12-16), 25 MB, a per-run allowlist and the address rules (`client.py`, U12-23), TLS
  verified; S18.2.4 checked against U12-1, U12-2, U12-14.
- `connector/moolakata_connector/sealed.py` serves S18.7.1 and protocol §4.3;
  `connector/moolakata_connector/signing.py` serves S18.4.3 and protocol §3;
  `web/server/src/moolakata/connector/__init__.py` serves protocol §5 (the versions spoken).
  None untraced.

## Checked and sound

1. The vault (S18.3.1): AES-256-GCM under HKDF-SHA256 of the 128-bit key with the stated
   label, the fingerprint as associated data, a fresh nonce per write, written through a
   temporary file, `fsync` and rename at 0600; the fingerprint as stated; wrong words counted
   across the page and the socket.
2. The 12 words: BIP-39 with its checksum, the list's hash checked, four-letter prefixes; `init`
   and `reset` show them on the terminal only (`main.py:53-79`), `unlock` reads without echo.
3. Signed calls and answers (protocol §3): the connector signs method, path, body hash, time,
   nonce and the server's fingerprint; it checks the answer's signature over status, body
   hash, time, its own nonce, its own fingerprint and its call's body hash, and the time.
4. TLS from the connector: system roots and the host name for public certificates; for
   MoolaKata's own, the SPKI hash pinned from the code, the next one announced only in a
   signed answer (`client.py:93-136`, `:175-180`, `core.py:88-96`); the address resolved once
   and the connection made to the address checked.
5. The sealed box: X25519, HKDF salted with the Connection's id (so a box can't be replayed to
   another Connection), AES-GCM; the connector refuses a host other than the settings' and a
   box not newer than the credential held.
6. The bound host before every run and the per-run allowlist (`core.py:414-430`); OFX Direct
   `https` only; a 3xx is a failure (no redirect followed by `http.client`); no
   `Content-Encoding` decoding in the connector's client, so no decompression bomb.
7. Pairing on the server: the secret kept as a hash, 24 hours, once; the sealing key's
   signature verified before anything is stored; a pairing replaces the paired one and ends
   its Connections; Unpair, Confirm, Accept and Pair each ask for the password again.
8. File posts: only to an account whose sync names this Connection and whose owner is the
   Connection's (`routes.py:225-231`); the owner's upload rate; the meta's hash checked;
   Activity *by MoolaKata Connector, <label>* (S18.8); account sync set only by the account's
   owner, to one of their own Connections (`ui/accounts.py:491-554`).
9. Reports: never more than a name and last four digits kept (`manage.py:340-348`), messages
   cut to 200 characters; Connections removed are listed in every answer, so a connector
   locked at the time deletes them at its first unlocked report; the page address held to
   `https://host:port` (but see U12-2).
10. Its page (S18.11.5): CSP `default-src 'none'; style-src 'self'; form-action 'self';
    frame-ancestors 'none'`, `no-store`, `DENY`, `nosniff`; forms only from the same origin
    (`Sec-Fetch-Site`, else `Origin` against `Host`); bodies at most 16 KB; every action takes
    the words; the status shows no institution, Connection name, account or credential; the
    handshake in the request's own thread with a 20-second timeout; the welcome's keys in
    memory, 20 for an hour, all dropped once one is taken; Reset needs the words and RESET.
11. The connector's tests: `test_core` 19, `test_drivers` 5, `test_page` 8, `test_end_to_end` 4,
    all passed (run one file at a time, outputs in the job's `tmp/u12/`).

## Read lightly or not read

- `connector/moolakata_connector/page.css` (244 lines): skimmed; its token test
  (`test_its_stylesheet_keeps_moolakatas_colours_and_type`) passed.
- `web/ui/app/sealed.js` (the browser's sealing, unit 09's file): not read; taken as
  `connections.js` calls it.
- `connector/requirements.txt`: the hashes not checked against the wheels.
- The migrations of the connector's tables (0011, 0012, 0020, 0027): 0027 read; the others
  only searched for the Folder driver's name.
- Schwab's API shapes (`positionEffect`, refresh answers) from memory and
  `docs/external/schwab-py-auth.rst`'s headings, not from Schwab's reference.

## Summary

| Id | Kind | Req | Sev | Conf | Status | What |
|---|---|---|---|---|---|---|
| U12-1 | security | S18.7.1 | Med | 0 | open | Withheld |
| U12-2 | security | S18.2.4.4 | Med | 0 | open | Withheld |
| U12-3 | bug | S18.9.2 | Med | 0 | open | One option trade makes the Schwab driver's whole OFX file unreadable (no `SHPERCTRCT`) |
| U12-4 | wrong figure | S18.9.2 | Med | 0 | open | Schwab option trades take open or close from the sign; every position written as stock; expiries dropped |
| U12-5 | bug | S18.8 | Med | 0 | open | A file the reader can't read gets an unsigned 500, not a signed `file-refused` |
| U12-6 | bug | S18.8 | Med | 0 | open | An unsigned answer or a dropped connection while posting stalls every later post and the after-run report |
| U12-7 | bug | S18.7.1 | Med | 0 | open | New credentials for an existing OFX Connection are sealed with no host and always refused |
| U12-8 | not built | S16.18 | Low | 0 | open | Settings › Connector doesn't show each Connection's host |
| U12-9 | differs | S18.4.2 | Low | 0 | open | `pair` shows the fingerprint the answer names, not its own |
| U12-10 | differs | S18.4.1 | Low | 0 | open | The pairing code carries the link address before the public URL (D3-14) |
| U12-11 | differs | S18.4.4 | Low | 0 | open | Unpair while locked keeps every credential and the sealing key |
| U12-12 | security | S18.3.3 | Low | 0 | open, needs the user | The shared wrong-words wait lets anyone on the network keep the connector locked |
| U12-13 | security | S18.3.1 | Low | 0 | open | A mistyped word of the vault's phrase is logged |
| U12-14 | security | S13.7.6 | Med | 0 | open | Withheld |
| U12-15 | bug | S18.3.2 | Low | 0 | open | `status`, the health check and the page wait for a whole round |
| U12-16 | bug | S18.2.2 | Low | 0 | open | The 60 seconds bound each read, not the call |
| U12-17 | bug | S18.7.1 | Low | 0 | open | A box filed whose `taken` failed is never acknowledged and marks the Connection failing |
| U12-18 | bug | S18.9.1 | Low | 0 | open | OFX Direct sends credentials unescaped, non-Latin-1 replaced |
| U12-19 | differs | protocol §7 | Low | 0 | open | A file over the import size is `file-refused`, not `too-large` (DC-13) |
| U12-20 | differs | S18.3.4 | Low | 0 | open | Reset doesn't tell MoolaKata it unpaired |
| U12-21 | bug | S18.11.1 | Low | 0 | open | The page's certificate written key first, no temporary file |
| U12-22 | differs | S18.3.1 | Low | 0 | open | `init` writes the vault before the words are typed back |
| U12-23 | security | S18.2.2 | Low | 0 | open | The connector's egress lets the IPv6 metadata address through |
| U12-24 | untraced | — | Low | 0 | open | `_check_settings`'s list branch serves only the dropped Folder driver |
| U12-25 | differs | S12.7 | Low | 0 | open | Guides: the account number "sealed"; keys made "if it has none" |

**Counts:** 25 claims. High 0, Med 8 (U12-1, U12-2, U12-3, U12-4, U12-5, U12-6, U12-7,
U12-14), Low 17. By kind: bug 9, differs 7, security 6 (U12-1, U12-2, U12-14 Med, withheld;
U12-12, U12-13, U12-23 Low), wrong figure 1, not built 1, untraced 1. Needing the user: U12-12.
