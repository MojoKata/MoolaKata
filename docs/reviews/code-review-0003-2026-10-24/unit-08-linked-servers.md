# Code review 3, unit 08: linked-servers

**Session:** Oct 24, 09:43 PM to 10:02 PM (Chicago). **Commit read:** `6916954`. **Scope:** full.
**Checking:** quick (no §8 checker; every claim at 0 confirmations, status open).

## Brief (docs/REVIEW.md §7)

### 1. Sections, code and tests (map.md)

- **Sections:** S11 (S11.1 invite and join, keys and signing, TLS; S11.2 reachability and link
  addresses; S11.3 what a link carries, directories, S11.3.1 items worked out at the source;
  S11.4 how data moves, sealed changes, parts; S11.5 what crosses and never does; S11.6 ending;
  S11.7 Settings › Linked servers, progress, pause, the linked copy; S11.8 audit; S11.9 linked
  copies: folder, access key, unlocking, locking, staying in sync while locked, the streaming
  format, who opens what, lost words, backups, what it protects, the engine), with
  `docs/link-protocol.md` as its protocol, and the README's R1–R3 lines they rely on (R1.8,
  R1.18, R2.9, R2.10, R3.4).
- **Code (5,943 lines, 20 files):** `src/links/{__init__,changes,client,copies,copy,copydb,keys,
  manage,peers,receive,routes,sealed,serve,signing}.py`, `src/store/entities/links.py`,
  `src/store/tables/links.py`, `src/ui/{linked,links}.py`, `ui/components/links.js`,
  `ui/screens/linked.js`. The migrations of its tables (`mig/0010`, `0013`, `0016`) sit in unit
  06's list; read here only where a claim needs them.
- **Tests (1,430 lines):** `tests/linkpair.py`, `test_copies.py`, `test_links.py`,
  `test_sealed.py`.
- **Guides:** `linked-*.md` (14), `settings-links.md`, and the dialogs `dialog-{link-invite,
  link-join,link-pause,copy,copy-key,remove-copy,verify-key,share}.md` as far as links go.
- **Cites no section:** none listed for this unit; no untraced candidate given.

### 2. Delta since review 2 (`294792b`..`6916954`)

Content changed: 1,825 lines (30%), the highest share of the security units after 10 and 11.
New files: `links/changes.py` (390), `links/client.py` (220), `links/routes.py` (349), split
out of the old `manage.py`/`receive.py`/`serve.py` and rewritten in milestones 8–9 (TLS
verification and pinning, sealed changes, K3, K18, K22, B24–B26). Changed most:
`manage.py` (+222/−48), `serve.py` (+121/−7), `ui/links.py` (+108/−11), `ui/linked.py`
(+76/−7), `links.js` (+69/−31), `receive.py` (+68/−22), `signing.py` (+56/−10), `copies.py`
(+40), `linked.js` (+39/−9), `keys.py` (+28). Tests: `test_links.py` (+433/−17),
`test_copies.py` (+54/−5), `test_sealed.py` (+46/−17), `linkpair.py` (+21/−16). The rest is
the rename. All of it reached `main` in one squash (`38397b7`). Read first: `client.py`,
`routes.py`, `changes.py`, `signing.py`, then `manage.py` and `serve.py`.

### 3. Earlier reviews' findings in this area

Review 2 (§12.2 marks each done unless said):

| Finding | What | State per review 2 | To re-check |
|---|---|---|---|
| K2 | linked receipt served with the peer's type, no sandbox | done (m8 part 1) | `ui/linked.py` file route: type from the bytes, S13.7.7 headers |
| K3 | TLS verified, own certificate pinned, signed answers name caller and request; only `link-ended` ends; changes and receipts sealed end to end | done (m8 part 2) | `client.py`, `signing.py`, `routes.py`, `manage.py`, `serve.py` |
| K18 | link address checks (https, no query, no loopback/link-local/metadata, whoever names it); URL joining; DNS rebinding; chunked answers past 20 MB; `http://` | done (m8 part 2) | `client.py`, `peers.py`, `manage.py` (join) |
| K19 | a peer's `message` not copied into `lastError`, alerts or emails | done (m9 part 1) | `client.py`, `manage.py` |
| K22 | `/link` reads before any write; link key decrypted only to sign; unknown key over 1 MB refused on headers | m9 part 4 (12.5.3) | `routes.py` |
| K23 | Remove copy asks for the phrase too (S16.13); S11.9.10 point | m9 part 5 | unit 10's Settings route; `copies.py` here |
| K25 | copy key in the connection factory overwritten and refused after release; apply refuses a `seq` at or below the last applied | m9 parts 4–5 | `copy.py`, `copydb.py`, `changes.py` |
| P5, C20 | nothing crosses before approval; directories from the first exchange after | done | `manage.py` (join, approve), `receive.py` |
| P6 | budget recurring rows' account id and name; gift documents without Include receipts | m9 part 4 | `serve.py` (unit 05's U05-25 found it half holds in new code) |
| B24 | the pulling side's receipts travel in `deliver` | done (m8 part 2) | `client.py`, `routes.py`, `receive.py` |
| B25 | large changes oldest to newest, documents split by date, none over 20 MB | done (m8 part 9) | `serve.py` |
| B26 | a malformed change checked inside the guarded step, set aside, everything asked again | done (m8 part 9) | `changes.py` |
| B41 | a pull records who, which link, which shares; Pull now's actor; words checked when already unlocked; hash before the last chunk | m9 part 4 | `manage.py`, `copy.py`, `ui/linked.py` |
| N9 | `/link`'s 60 calls a minute | done (m8 part 7) | `routes.py` |
| N11 | what flows each way in Settings; the sweeper; view audit | m9 part 4 (the rest L6) | `ui/links.py`, `links.js`, `copy.py` |
| C10, C14 | the copy folder named at random | done | `copies.py`/`copy.py` |
| C17 | refusals' signed/unsigned and status | m9 part 4 | `routes.py` |
| C18 | removal "at the next exchange" | m9 part 4 | docs only |
| C33 | the eighth kind, `person`, crosses | m9 part 4 | `serve.py` |
| C23 | (connector side; the link side hashes `hello`'s key) | done | `manage.py` join |

Review 1: C1 (OCR text crosses with Include receipts, S9.8.5), C8, C10, C13 and F-items on
links: all superseded by review 2's K3 and C-rows above.

### 4. Phase 1 claims and decisions on S11

None is decided yet; each is judged against the code (and against both readings where open).

- **DC-1 = D2-1 + D3-1** (Med; needs the user): receipts over ~20 MB can't cross a link (the
  20 MB ceiling on `deliver` bodies and `file` answers). With **D3-5**, one oversize receipt may
  stall a link's exchange for good: check this in the code; if it does, the claim is **High**.
- **D2-2** (Med; needs the user): do a tax book's document files cross a link (S11.4, the Share
  dialog) or wait for L6 (S11.5.1)? Say what the code does and which reading it matches.
- **DC-3 = D2-4 + D3-6** (Low): a link's states (*requested*, *pending*, *active*, *paused*,
  *unreachable*, *broken*, *ended*), what each allows, and what leaves *broken*.
- **DC-11** (Low): `join` carries `t`, the joining side's certificate fingerprint, against
  S11.1.2's "nothing else".
- **D3-2** (Low): a received receipt's type found "when shown" (protocol) or "when it arrived"
  (S11.9.6.5); `files` carries a `type` anyway.
- **D3-3** (Low): the hash checked "before keeping the file" is sealed where a locked copy
  can't read it.
- **D3-4** (Low): a large change's remaining parts kept in memory (2 GB example).
- **D3-5** (Low): delivered receipts kept until their part arrives, with nothing for a part
  that never comes; the sweeper's rule.
- **D3-6** (Low): see DC-3; relinking with the same key.
- **D3-7** (Low): the approval reaching the joining side "at once".
- **D3-8** (Low): the kinds' wire names.
- **D3-9** (Low, security): `hello` names the version.
- **D3-22** (Low): S11.9.1 cites "schema.md §2.5"; the code side is the folder's random name.
- Also on S11: D2-5 (the copy's database and the eight kinds), D2-6 (hourly "by default"),
  D2-7 (where S11.8's records go), D2-8 (the mockup's "no secret"), DC-9 (the attempt
  counters, S11.9.3.3), DC-10 (remote user limits; unit 07 judged it), DC-16 (the hour as a
  setting), D2-25/DC-4 (the relay "not now").

### 5. Untraced candidates and uncited first-level items

The map gives this unit no untraced file and no uncited first-level item of S11.

## Claims

### U08-1: one receipt the pulling side can't fetch stops the link both ways for good, and nothing shows it

- **Kind:** bug. **Req:** S11.4 ("Pulls run whether or not anyone has unlocked the copy. When
  the source is unreachable, the copy stays, marked stale"), S11.2 ("each exchange carries both
  directions"), S11.5.1, S13.5 (20 MB answers), S12.11.1 (a failing link alerts); DC-1 (D2-1,
  D3-1) with D3-5; `link-protocol.md` §4.3, §4.4.
- **Code:**
  - `web/server/src/moolakata/links/receive.py:33-35` (`take`), before anything of the change is
    kept:
    ```text
        names = dict(delivered or {})
        missing = [f for f in change.get("fetch") or [] if f not in names]
        names |= fetch_files(srv, link_id, missing)
    ```
    and `fetch_files` (`:156-162`) re-raises whatever `client.iter_file` raises.
  - `web/server/src/moolakata/net.py:24` `MAX_RESPONSE = 20 * 1024 * 1024`, applied to every
    answer by `_Capped` (`:180-192`), so a `file` answer whose sealed bytes pass 20 MB raises
    `ResponseTooLarge`, which `client.iter_file` (`links/client.py:178-179`) turns into
    `LinkError("unreachable", …)`.
  - `web/server/src/moolakata/links/manage.py:482-498`: the exchange records success
    (`link.lastOkAt, link.lastError, link.failingSince = clock.now(), None, None`) before it
    takes the change, and `receive.take` (`:498`) runs outside the `try` that records
    failures; this side's own change (`:509-515`) is worked out only after it. `exchange_all`
    (`:666-667`) then swallows the `LinkError`: `with contextlib.suppress(LinkError):  #
    recorded on the link; alerts follow it`.
  - `web/server/src/moolakata/links/serve.py:354` `full = full or have != link.sentSeq`, with
    `sentSeq` and `LinkSent` committed when the change is worked out (`:400-405`), so the next
    exchange gets a full change, which names the same receipt again.
- **What goes wrong:** Alice shares *Checking* with Carol on her parents' server with
  **Include receipts**, and one of its receipts seals to more than 20 MB (a 21 MB scan: allowed,
  the limit is 25 MB by default and up to 100). Carol's server pulls hourly; the first part of
  the change names the receipt in `fetch`, its `file` answer is cut off, and `take` raises
  before the registry, the inbox or `gotSeq` is touched. Every later exchange asks again from
  the same `have`, gets a full change naming the same receipt, and fails at the same point.
  Nothing Alice shares ever arrives (not even the account's row), nothing Carol's household
  shares with Alice's ever leaves (this side's change is never sent), the link shows *active*
  with a fresh *last exchange* and no error, and no alert is raised. The same holds for any
  failure in fetching one receipt: its file missing at the source, a `not-shared` race, or the
  60-second answer check of U08-6. On the delivering side (`manage.py:510-515`), a receipt the
  peer refuses (sealed past the peer's own receipt limit, which the middleware applies to
  `deliver` bodies, `middleware.py:243-247`) stops that direction the same way, unrecorded.
  DC-1 asked whether one oversize receipt stalls a link's exchange for good: it does, both
  ways, silently, so this is High.
- **Run:** yes, `tmp/u08/t/test_u08.py::test_oversize_receipt_stalls_both_directions`: a
  `file` answer cut off as `net.Client` cuts one past 20 MB; four pulls later B's `gotSeq` is
  still 0, Carol is told nothing is shared with her, A has taken nothing of Bob's new share
  (`A.gotSeq 0`, `A.sentSeq 4`), `lastError` and `failingSince` stay empty, and no alert is
  open (`run2.txt`).
- **Remedy:** a receipt that can't be fetched or delivered never holds back its change: the
  change is kept with that receipt marked *not arrived* (shown as such in the linked window),
  and the receipt is tried again at the next exchange; any failure after the exchange's first
  call is recorded on the link (`lastError`, `failingSince`) so S12.11.1's alert follows; and
  the decision DC-1 asks for sets the ceiling for sealed receipt bodies (`file` answers read
  through a ceiling tied to S16.10's maximum plus the format's overhead, as `deliver` bodies
  already are). A test with a receipt over the ceiling, through the real `net.Client`.
- **Alternatives:** the source leaves out of `fetch` any receipt sealed past the ceiling and
  sends its record marked *too large to share* (DC-1's first alternative).
- **Needs the user:** the ceiling is DC-1's decision (stream to S16.10's maximum, cap at 20 MB
  and mark *too large to share*, or lower S16.10); the stall and its silence need fixing
  whichever is chosen.
- **Check:** confirmed. Read `receive.take`, `fetch_files`, `client.iter_file`, `net._Capped`,
  `manage.exchange` (success recorded before `take`, `LinkError` suppressed in `exchange_all`) and
  `serve.change_for` (`sentSeq` committed). Ran the scratch test on my copy: four pulls leave
  `gotSeq` 0, A takes nothing of Bob's share, no `lastError`, `failingSince` or alert. Receipts to
  25 MB are allowed (S16.10), so the cap is reachable.

### U08-2: two servers whose link ended can never link again: the join answers 500 on both sides

- **Kind:** bug. **Req:** S11.6 ("marks the link broken and alerts admins, who end it or link
  again"), S11.1.2; DC-3 (D3-6: "linking again with the same key is unspecified").
- **Code:**
  - `web/server/src/moolakata/store/tables/links.py:82` `unique_live(Link, "peerKey")`: unique
    among rows not deleted, and nothing ever soft-deletes a `Link` (an ended link "stays
    listed", `:18-20`).
  - `web/server/src/moolakata/links/manage.py:258-265` (join) and `:300-307` (`answer_join`)
    look for an existing link with `Link.state != "ended"`, so an ended one passes the
    `already-linked` check, and then `:271-284` adds a new row with the same `peerKey`, and
    `:314` sets it on the invitation.
- **What goes wrong:** A was restored from an older backup; B's link shows *broken*, and the
  alert says "end the link, or link again". The admins end it on both sides, A invites, B
  enters the code: A's `/link/v1/join` fails with `IntegrityError: UNIQUE constraint failed:
  Link.peerKey` (an unsigned 500), and B's `POST /ui/api/settings/links/join` answers 500 too
  (B's own ended row has the same key). The same happens to any two households that end a link
  and want it back. The only way out is a new link key on one server, which nothing offers.
- **Run:** yes, `tmp/u08/t/test_u08.py::test_relink_after_end` (`run1.txt`: 500 from
  `/link/v1/join` and from Settings' join, both `IntegrityError` on `Link.peerKey`).
- **Remedy:** a join from a key whose link here has ended (or is broken) is allowed: the ended
  row is soft-deleted (or its `peerKey` moved aside) in the same transaction, and a broken one
  ends first, as D3-6's remedy says; the unique index then holds for live links only. A test
  that ends a link and links the same two servers again.
- **Alternatives:** the index covers only links not ended (`NOT deleted AND state <>
  'ended'`).
- **Check:** corrected. Severity unchanged. Reproduced on my copy: A's `/link/v1/join` raises
  `IntegrityError: UNIQUE constraint failed: Link.peerKey` (`answer_join` sets the invitation's
  `peerKey` while A's ended row holds it; `unique_live` ignores only `deleted`, and no `Link` is
  ever soft-deleted). The "500 on both sides" is loose: `join` (`manage.py:296-323`) calls A
  before adding B's row, so B first gets A's unsigned 500 as a `LinkError` (the 500 shown in the
  scratch run is the in-process wire re-raising); B's own `IntegrityError` at `:271-284` comes
  only if A's answer ever succeeded. The remedy stands.

### U08-3: a peer's exchange or delivery is answered on the server's event loop, so the whole server waits for it

- **Kind:** bug. **Req:** S11.4 (pulls hourly and on demand), S13 (one server answers the
  household's browsers, the API and `/link`); no requirement names the event loop.
- **Code:** `web/server/src/moolakata/links/routes.py:183-196`:
  ```text
  @router.post("/exchange")
  async def exchange(request: Request):
      ...
      out = answer_exchange(
          srv, link, exactjson.loads(body or b"{}"), request.headers.get("mk-link-version")
      )
  ```
  `answer_exchange` (`manage.py:561-592`) is synchronous and runs `serve.change_for`, which
  works out every shared item for every viewer through the API's own routes (`serve.py:229-263`:
  every account's whole transaction history, series, holdings, every budget's month, trends and
  cash flow), hashes and seals it, all before it returns. The same holds for `deliver`
  (`routes.py:225-243` → `answer_deliver` → `receive.take`, which may call the peer back over
  the network through `fetch_files` with its 10 s and 20 s timeouts), `_deliver_file`
  (`:250-302`, writing and reading the body's file, `keep_delivered` with `fsync`), `join`,
  `ping` and `certificate`, all `async def` calling blocking database, file and network work.
  The server is one Hypercorn process on one asyncio loop (`listener.py:19, 122-125`).
- **What goes wrong:** while A answers B's hourly exchange, nothing else on A is answered: the
  household's browsers, `/healthz`, the connector's reports and other links' calls all wait
  until A has worked out B's change (seconds for a modest household, longer for a first full
  snapshot with years of transactions) and, in `deliver`, until any receipt it fetches back
  from B arrives or times out. Two links exchanging at the same time double it. A slow answer
  also blocks the 20 MB `deliver` body read and sealed-receipt streams of other peers, whose
  own 20-second read timeouts then fail (U08-4).
- **Run:** no; rests on reading (`async def` routes calling synchronous work, one loop).
- **Remedy:** the `/link` routes are plain `def` (FastAPI runs them in its thread pool), or
  each hands its synchronous work to `run_in_threadpool`; `_deliver_file` reads the stream on
  the loop and writes through a thread. A test that a slow `answer_exchange` doesn't hold up
  `/healthz`.
- **Alternatives:** none simpler.
- **Check:** confirmed. Read `routes.py`: `exchange`, `deliver`, `join`, `ping`, `certificate` and
  `file` are `async def` and call `answer_exchange`, `answer_deliver`/`receive.take` (which can
  call the peer back) and `serve.change_for` directly, with no thread hand-off; the UI routes are
  plain `def` and `run_in_threadpool`/`to_thread` appear nowhere in `links/`. Not run: it rests on
  reading, as the claim says.

### U08-4: the answer to an exchange is worked out whole before a byte goes, and a caller waits 20 seconds

- **Kind:** bug. **Req:** S11.4 (a first full snapshot fills the copy part by part), S13.5
  ("waits at most 20 seconds for each read"); D3-4 (the parts kept in memory).
- **Code:** `web/server/src/moolakata/links/manage.py:582-591` works out *every* part of the
  change (`serve.change_for`, which builds every document, splits, signs and seals them all,
  `serve.py:347-414`) inside the request, before answering with the first; `PENDING[link.id] =
  parts[1:]` keeps the rest in memory. `serve.py:400-405` commits `sentSeq` and `LinkSent` as
  it does. The caller's client gives up after 20 s without a byte (`net.py:23` `TIMEOUT =
  httpx.Timeout(20.0, connect=10.0)`).
- **What goes wrong:** a household whose change takes A more than 20 s to work out (a first
  full snapshot of a few accounts with decades of transactions, worked out once per viewer,
  each document dumped to JSON three times for its hash, size and date: `serve.py:342-344,
  467, 471-472`) is never pulled by B: B's read times out (*didn't answer (ReadTimeout)*), A has
  already moved `sentSeq` on, so B's next `have` differs and A works out a full change again,
  larger than the last, every hour. The whole change, every part sealed, is held in A's memory
  at once (D3-4's case: the protocol's 2 GB example is more than DEPLOY gives the server).
- **Run:** no; rests on reading. How large a household has to be for the 20 s to bite was not
  measured.
- **Remedy:** the answering side commits `sentSeq` only when the caller confirms (its next
  `have`), works out the first part first and answers with it, and works out each later part
  when `next` asks for it, from a cursor (D3-4's remedy), so neither the answer nor memory
  grows with the change; or the exchange answers at once with `more` and the change follows
  in `next` calls.
- **Alternatives:** a longer read timeout for `exchange` and `next` alone.
- **Check:** confirmed. Read `answer_exchange` and `serve.change_for`: every part is built, signed
  and sealed before the first goes out, `sentSeq` is committed there and the rest sits in
  `PENDING`; `net.TIMEOUT` reads 20 s, and the next `have` then differs so the change is rebuilt
  in full. Reading only; the threshold was not measured and nothing is run, so Low stands.

### U08-5: withheld

- **Kind:** security. **Severity:** Med. Withheld (`withheld.md`, REVIEW.md §2).
- **Check:** confirmed.

### U08-6: a receipt that takes over a minute to cross is refused as a clock problem

- **Kind:** bug. **Req:** S11.1.3 (a timestamp more than 60 seconds off is refused, "named as
  such on the link, since the fix is NTP"), S11.2 (receipts' bytes cross in the exchange),
  S16.10 (receipts up to 100 MB); `link-protocol.md` §3.2, §4.3.4.
- **Code:**
  - `web/server/src/moolakata/links/routes.py:269-278`: the delivered receipt's body is read to
    the end, then `signing.verify_request(request.headers, "POST", request.url.path, b"", fp,
    srv.link_nonces, digest=digest)` checks the call's `MK-Link-Time` against the clock *now*
    (`signing.py:239-240`, `abs(now - t) > SKEW`).
  - `web/server/src/moolakata/links/client.py:174-185`: the `file` answer's bytes are read to
    the end, then `signing.verify_answer(peer_key, 200, b"", asked, answer_headers,
    digest=digest)` checks the answer's `MK-Link-Time`, stamped when its headers were sent,
    against the clock now (`signing.py:181-182`).
- **What goes wrong:** a 25 MB receipt (the default limit) over a 3 Mbit/s home uplink takes
  about 70 seconds. Delivered, it is refused `clock-skew` by the receiver once it has arrived
  whole; fetched, the fetching side refuses the answer as `clock-skew` once it has read it
  whole. Either way the receipt never crosses, and by U08-1 the link stops both ways, with an
  error that, where it is shown, blames the clocks. At 100 MB (S16.10's maximum) a 15 Mbit/s
  uplink is enough to fail it.
- **Run:** no; rests on reading (both checks take the clock after the stream).
- **Remedy:** check the time (and the nonce) from the headers when the call or answer
  arrives, before its body is read, and check only the signature over the digest at the end;
  the signature still covers the time it was made.
- **Alternatives:** none needed.
- **Check:** confirmed. Read `signing.verify_request` and `verify_answer`: both take the clock
  when called, and `_deliver_file` and `iter_file` call them only after the whole body is read,
  against a time stamped when the headers were sent (`sign_answer` before `StreamingResponse`;
  `sign_request_digest` before the upload). Past 60 s of transfer it raises `clock-skew`; 25 MB
  over 3 Mbit/s is about 67 s. Reading only, as the claim says.

### U08-7: the minute's sweep deletes receipts that arrived while the copy was locked, if it runs while an unlock is opening the inbox

- **Kind:** bug. **Req:** S11.9.5.2 (receipts written straight into `receipts/`), S11.9.6.6
  ("A sweeper removes files that no row names, left behind after a crash"), S11.9.5.3.
- **Code:** `web/server/src/moolakata/links/copies.py:117-131` (`orphans`, run every minute
  for each open copy by `sweep`, `:135-143`):
  ```text
      with o.engine.connect() as conn:
          kept = set(conn.execute(select(copydb.File.c.fileName)).scalars())
      waiting = set(DELIVERED.get(link_id, {}).values())
      old = time.time() - ORPHAN_MINUTES * 60
      ...
          if f.stat().st_mtime > old or f.name in kept or f.name in waiting:
              continue
          if f.suffix in (".mkr", ".tmp"):
              f.unlink(missing_ok=True)
  ```
  A receipt fetched while the copy was locked is named only in its inbox entry's `local`
  (`receive.py:94`, `changes.py:121-124`) until `apply` commits its `File` row. `unlock` puts
  the copy in `open` (`copies.py:61`) and then `apply` (`:72-73`) opens and checks every
  inbox change (`changes.py:168-185`) before its transaction begins (`:210`).
- **What goes wrong:** the parents' copy stays locked for a week while pulls bring in Alice's
  receipts. Carol unlocks; while `apply` is still opening the week's changes, the minute's
  sweep runs: the copy is open, no `File` row names the receipts yet, and they are older than
  ten minutes, so it deletes them. `apply` then writes `File` rows that name missing files.
  The receipts are listed, and opening one answers 500 (`FileNotFoundError`); nothing
  repairs it but Reset copy, and nobody is told. The larger the inbox (a first full snapshot),
  the wider the window. The same happens to receipts a pull fetches while the copy is open,
  when fetching a part's receipts takes more than ten minutes.
- **Run:** yes,
  `tmp/u08/t/test_u08.py::test_sweep_during_apply_deletes_receipts_that_arrived_while_locked`:
  a receipt pulled while locked, its file's time set an hour back, `orphans` called from
  inside `apply`'s opening loop as the minute's tick would; the receipt is listed, its file is
  gone, and fetching it raises `FileNotFoundError` (`run4.txt`).
- **Remedy:** `orphans` keeps every file named by an inbox entry's `fileNames` and every file
  of a pull in progress, or runs under a per-link lock that `take` and `apply` also hold.
- **Alternatives:** receipts are written under `receipts/` only by `apply`, from a staging
  folder the sweeper leaves alone.
- **Check:** confirmed. Read `copies.orphans`/`sweep` (own task thread, `runtime.py:140-145`),
  `unlock` and `changes.apply`: `unlock` puts the copy in `open` and `apply` opens the inbox
  before any `File` row exists, while `orphans` spares only `File` rows and `DELIVERED`. Ran the
  scratch test on my copy: `orphans` called inside `apply` removed the old receipt (`SWEPT 1`),
  then it was listed with `ON DISK 0` and fetching it raised `FileNotFoundError`. The window is
  narrow, so Med is generous but stands.

### U08-8: withheld

- **Kind:** privacy. **Severity:** Med. Withheld (`withheld.md`, REVIEW.md §2).
- **Check:** confirmed.

### U08-9: a peer's directory is kept unchecked: an avatar that isn't an object breaks Settings › Linked servers and the Linked list

- **Kind:** bug. **Req:** S11.3 (the directory: "display name, username, email, sex and
  stable id", "household name and avatar (S16.1)"), `link-protocol.md` §4.2 (the receiver's
  limits on what it keeps); DC-10.
- **Code:** `web/server/src/moolakata/links/manage.py:327-331, 349-351, 363`:
  ```text
      h = payload.get("household") or {}
      link.peerName = h.get("serverName") or link.peerName
      link.householdName = h.get("name") or link.householdName
      if h.get("avatar") is not None:
          link.householdAvatar = json.dumps(h["avatar"])
  ...
                  username=str(r.get("username") or rid)[:64],
                  displayName=name,
                  email=r.get("email"),
  ...
          u.email = r.get("email")
  ```
  and `ui/links.py:214` / `ui/linked.py:83` give it back as `json.loads(link.householdAvatar)`
  into fields typed `dict | None`; `RemoteUser.email` is `str | None` (`ui/links.py:30`).
- **What goes wrong:** a peer (a newer release, a bug there, or a hostile peer) sends `"avatar":
  ["x"]` or an email that isn't a string: every admin's Settings › Linked servers answers 500
  (pydantic refuses the list), as does `/ui/api/linked` for everyone that household shares
  with, until the peer sends something else. Nothing bounds the server name, household name,
  remote id or avatar either: a 15 MB avatar is stored in the main database at each exchange
  and sent to every browser that lists links or linked households.
- **Run:** yes, `tmp/u08/t/test_u08.py::test_peer_avatar_not_a_dict_breaks_settings`
  (`householdAvatar = '["x"]'`: `GET /ui/api/settings/links` fails with `ValidationError:
  householdAvatar Input should be a valid dictionary`, `run3.txt`).
- **Remedy:** `apply_directory` keeps only what the protocol names, each checked: the avatar
  as S16.1 shapes it (an object of known keys, an image as a data URL of an image type under a
  size), names cut to §4.2's lengths, the email a string under 254 characters or none, the id
  a string under 64; anything else is dropped, never stored. A test with a malformed directory.
- **Check:** confirmed. Read `apply_directory` (avatar dumped as given, email unchecked, no length
  bounds on server or household name) and the two `json.loads(householdAvatar)` into `dict | None`
  fields (`ui/links.py:214`, `ui/linked.py:83`). Ran the scratch test on my copy: `householdAvatar
  = '["x"]'` makes `GET /ui/api/settings/links` raise `ValidationError ... valid dictionary`.

### U08-10: a paused link holds back a share's removal, which S11.4 says still crosses

- **Kind:** privacy. **Req:** S11.4 ("A Pause (S11.7.2) stops data, never a removal or an end,
  which still cross"), R3.4 ("Revoking it ends access … on a linked server at its next
  exchange"), `link-protocol.md` §4.3.5; review 2's C18.
- **Code:** a paused side neither calls nor answers an exchange: `manage.py:445-448`
  (`if link.state not in ("active", "pending"): return`), `exchange_all` (`:655-662`, active
  and pending only), and `routes.py:188` `verified(request, ("active", "pending"))`, which
  refuses `link-paused`. Removals travel only inside a change (`serve.py:371, 390`), which only
  an exchange carries. An end has its own call (`/link/v1/end`, allowed while paused), so ends
  do cross; removals don't.
- **What goes wrong:** Alice stops sharing her brokerage account with her parents. Their admin
  had paused the link for two weeks (or pauses it again each time it resumes): Alice's server
  is refused `link-paused` at every exchange, and the parents' copy keeps the account, shown to
  whoever it named whenever the copy is unlocked, until the pause ends. S11.4 promises the
  removal crosses anyway.
- **Run:** no; rests on reading.
- **Remedy:** a paused side still answers an exchange, and still makes one, carrying only the
  registry's `removed` (and taking the peer's), no data and no directory; or a `removed` call
  of its own, allowed while paused, as `end` is.
- **Alternatives:** S11.4 says a removal waits for the pause to end (and R3.4 with it).
- **Check:** confirmed. Read `exchange` (returns unless active or pending), `exchange_all`,
  `routes.exchange` (`verified(..., ("active", "pending"))`, refusing `link-paused`) and
  `serve.change_for` (removals only inside a change); only `end` and `certificate` accept a paused
  link. S11.4 and `link-protocol.md` §4.3.5 both say a removal still crosses a paused link, and
  none does.

### U08-11: a certificate change that a peer missed is never announced to it again

- **Kind:** bug. **Req:** S11.1.3 ("a server whose certificate's key changes announces the new
  one to its peers … before its next exchange"), `link-protocol.md` §4.5.
- **Code:** `web/server/src/moolakata/links/manage.py:180-189`:
  ```text
      if (key or None) == (told or None):
          return 0
      n = 0
      for link_id in ids_:
          with contextlib.suppress(LinkError):  # it learns at the next exchange instead
              call(srv, link_id, "/link/v1/certificate", {"fingerprint": key})
              n += 1
      with srv.db.tx() as s:
          settings.put(s, "linkCertificate", key, None)
  ```
  The new key is recorded as told whether or not each peer was reached, and nothing at the
  next exchange tells it (the comment says it learns then; no code does that).
- **What goes wrong:** B's own certificate key changes while A is offline for an hour (or A is
  only reached by B's calls, which come later). B marks the key told; A's next connection to B
  presents an unannounced key, is refused, and A's link waits for an admin to compare and
  accept it: the case §4.5's announcement exists to spare. In proxy mode the key is found by
  connecting to the server's own address (`certs.py:61-91`); when that fails (no hairpin route
  through the router), `own_key` answers None, which is announced as `{"fingerprint": None}`
  (ignored by the peer) and recorded, so the next successful probe announces again: harmless,
  but the same loop.
- **Run:** no; rests on reading.
- **Remedy:** keep, per link, the certificate key last told it, and announce to each link that
  hasn't been told, at every run of the task, until it has.
- **Check:** confirmed. Read `announce_certificate`: each peer's `LinkError` is suppressed, then
  `linkCertificate` is stored as told for all; nothing at the exchange (`manage.exchange`,
  `client.call`) carries the key, so a peer missed once is never told again. Reading only.

### U08-12: one link's malformed change stops the hourly exchange for every link after it, unrecorded

- **Kind:** bug. **Req:** S11.4 (each link pulled hourly), S11.9.5.3 (a change that fails "is set
  aside and reported").
- **Code:** `web/server/src/moolakata/links/manage.py:663-667`:
  ```text
      for link_id in wanted:
          ...
          with contextlib.suppress(LinkError):  # recorded on the link; alerts follow it
              exchange(srv, link_id)
  ```
  `exchange` can raise more than `LinkError` after the call: `receive.take` raises
  `ChangeError` for a change whose signature fails (`receive.py:26`, `changes.py:88-94`),
  `KeyError` for an item without `id` (`receive.py:49`), `ValueError` for a `seq` or `more`
  that isn't a number (`receive.py:27`, `manage.py:500`), and `serve.sealed_receipt` raises
  `ChangeError` (`serve.py:434-435`). None is recorded on the link (the success was recorded
  just before, `manage.py:486`).
- **What goes wrong:** a peer on a release with a bug (or a hostile one) answers with a change
  whose signature doesn't check: that exchange raises `ChangeError` out of `exchange_all`, the
  task stops, and every link after it in the list isn't exchanged that hour, or any hour while
  the peer keeps answering so. The failing link shows a fresh *last exchange* and no error.
- **Run:** no; rests on reading.
- **Remedy:** `exchange_all` catches every exception per link, records it on that link
  (`lastError`, `failingSince`) and goes on to the next; `exchange` records failures after its
  first call too (U08-1's remedy).
- **Check:** confirmed. Read `exchange_all` (suppresses only `LinkError`), `changes.verify` and
  `serve.sealed_receipt` (both raise `ChangeError`, which is not a `LinkError`) and
  `receive.take`; the task runner (`tasks.py:208-213`) logs the failure and ends the run, so later
  links wait for the next hour, and no alert covers a failed task. The one trace besides the log
  is the task's own last error; the link shows nothing, as the claim says.

### U08-13: a linked server's address is exempt from the loopback refusal when its host is named like the SMTP server or the node

- **Kind:** security. **Req:** S11.2 ("never a loopback, link-local or cloud metadata address,
  whoever names it"), S13.5; review 2's K18.
- **Code:** `web/server/src/moolakata/net.py:103-118`: the exemption is by host name:
  `allowed, named = host in self._hosts, host in self._named` … `for a in addrs if not named
  else ():`; `ui/prices.py:154-159` puts the SMTP host and an admin-named node in `named`, and
  the peers' hosts in `hosts`. A peer's host that is the same string as one of those is
  exempt.
- **What goes wrong:** the SMTP server is `127.0.0.1` (a relay on the host, a common setup). A
  code holder joins with address `https://127.0.0.1:2019`; A's admin approves the request (the
  address is shown, but small); from then on A sends its signed `exchange`, `deliver` and
  `end` POSTs to a service on its own loopback. Only `https` is used, so a plain service fails
  the handshake; one that speaks TLS gets the calls. Low: it needs an approval of a visible
  address, and the calls are fixed JSON.
- **Run:** no; rests on reading.
- **Remedy:** the guard keeps the exemption per use: `check` takes who asks (a link, the SMTP
  client, the node), and only an admin-named host asked for by its own client is exempt; or
  `join`/`answer_join` refuse a link address whose host resolves to a forbidden range,
  whatever is named.
- **Check:** confirmed. Read `net.Guard.check` (`named` skips the forbidden-range test) and
  `ui/prices.apply_egress` (`allowed_by_name` is the SMTP host plus the node's; peers only in
  dev), and `client.checked_address` (https, host, no query: no range test). A peer host equal to
  the SMTP host string passes. Low is right: an admin approves a visible address, TLS only, fixed
  JSON.

### U08-14: what crosses of documents differs from S11.5.1: a gift's or a donation's receipt files never cross, and a tax book's document list crosses without Include receipts (D2-2)

- **Kind:** differs. **Req:** S11.5.1 ("Receipts cross only when the owner ticks Include
  receipts … Without the tick, … a gift's documents (their file names, notes and links) stay
  home too. A tax book's document files come later (L6)"), S11.4; D2-2.
- **Code:** `web/server/src/moolakata/links/serve.py:256-262`:
  ```text
                  if it.kind == "gift-plan" and not it.includeReceipts:
                      doc = _without_documents(doc)
  ...
      for it in items.values():
          if it.kind == "account" and it.includeReceipts:
              for f in receipt_files(srv, it.id):
  ```
  and `allowed_file` (`:329-338`) allows only an account's receipts. A tax book's documents
  are its `/tax-books/{id}` document (`serve.py:170-174`, `ui/taxes.py:396-406`: each document's
  `receiptId` and `fileName`), sent as it is, tick or not.
- **What goes wrong:** with **Include receipts** on a gift plan, the gift's documents' names and
  notes cross but their files never do, so the linked Gifts screen lists receipts that can't be
  opened; the same for a giving plan's donation receipts. A tax book shared with the CPA's
  server *without* the tick sends each tax document's file name and receipt id. On D2-2: the
  code follows S11.5.1 and L6 (no tax book document file crosses); under the other reading
  (S11.4, the Share dialog's "a tax book's documents too", milestone 5) they are not built.
- **Run:** no; rests on reading.
- **Remedy:** with the tick, every receipt the shared item's screens name (gifts, donations,
  accounts) is a `file:` document and allowed by `allowed_file`; without it, the tax book's
  document list crosses without `fileName` and `receiptId`, as a gift's documents are
  stripped; D2-2's decision settles the tax book's files.
- **Needs the user:** D2-2 (whether a tax book's document files cross now or with L6).
- **Check:** confirmed. Read `serve.work_out` (`_without_documents` only for a gift plan without
  the tick; `file:` documents only for an account's receipts), `allowed_file` (accounts only) and
  `taxes._doc` (`receiptId`, `fileName` sent in the tax book's document, tick or not); the linked
  window's file list (`/linked/<id>/files`) holds only account receipts. S9.6 and S11.5.1 say
  receipts cross with the tick, so gift documents' files not crossing differs; the tax book half
  rests on D2-2, as the claim says.

### U08-15: S11.8's records: a restart's release isn't recorded, and the copy's and the link's events don't say which link

- **Kind:** differs. **Req:** S11.8 ("every unlock (who), failed unlock, release (unused, Lock
  now or restart), access key made, and reset of a linked copy"; "each pause and resume on the
  side that made it").
- **Code:** `web/server/src/moolakata/links/copies.py:48, 64, 67, 83-89, 100, 147-153` and
  `manage.py:148, 162, 230, 285, 319, 398, 425, 629` record `link.copy-*`, `link.paused`,
  `link.ended` and the rest with no `subject_kind`/`subject_id`, and `ui/activity.py:123-140`
  words them as "a linked copy", "a link" ("{actor} unlocked a linked copy"); only
  `link.pulled`, `link.served` and `link.viewed` name their link. Nothing records the release
  at a restart (the copies live in memory, `copy.py:94-103`; no `link.copy-locked` with
  `restart` is written at startup).
- **What goes wrong:** a server with links to the parents and to the CPA shows "Carol gave
  wrong words for a linked copy" and "Margaret unlocked a linked copy" with nothing to say
  which household's copy; an admin can't tell from Activity whose data was opened. A restart
  that locks both copies leaves no record.
- **Run:** no; rests on reading.
- **Remedy:** every `link.*` entry carries `subject_kind="link", subject_id=link_id`, and its
  wording names the server; the startup records one `link.copy-locked` (`restart`) for each
  link whose copy has a key.
- **Check:** corrected. Severity unchanged. Reading `copies.py`, `manage.py`, `ui/activity.py` and
  `runtime.py`: nothing records a release at restart (no `link.copy-locked` at start), which S11.8
  lists, so that part holds. The other half does not: S11.8 asks for who, not which link, and the
  unlock entries have the actor; no requirement says each names its link. Keep the claim to the
  restart release; naming the link is an improvement, not a difference.

### U08-16: the guides and a dialog say other than S11.1 and the code in three places

- **Kind:** differs. **Req:** S11.1.1, S11.1.2, S11.9.8.
- **Where:**
  1. `web/ui/guides/dialog-link-join.md:6-7`: "sends this server's address, key, household
     name and users"; S11.1.2 and the code (`manage.py:266-269`: `{code, address, t}`) send
     no household or users before approval.
  2. `web/ui/components/links.js:348-349`, the invitation dialog: "It holds this server's
     link address and key fingerprint." (the code also holds a one-time secret, S11.1.1; its
     own guide, `dialog-link-invite.md`, says so; the mockup's version is D2-8).
  3. `web/ui/guides/settings-links.md` (Linked copies) and `links.js:80` ("Copy reset: make
     its new access key"): Reset copy deletes the copy and its key, and the admin makes new
     words next; S11.9.8 says Reset copy "makes a new copy key with new words", and the code
     (`copies.py:92-100`) does what the guide says.
- **Run:** no; rests on reading.
- **Remedy:** the join guide says "sends this server's address and key, and its certificate's
  fingerprint when its certificate is its own; nothing else until they approve"; the dialog
  names the secret; S11.9.8 says what Reset copy does (or the code shows the words at once).
- **Check:** confirmed. Read all three places: `dialog-link-join.md` says the join sends
  "household name and users" while `manage.join` sends `{code, address, t}` (S11.1.2: nothing
  else); `links.js:348-349` leaves out the one-time secret that `dialog-link-invite.md` names;
  S11.9.8 says Reset copy "makes a new copy key with new words" while `copies.reset` and the guide
  leave the key to be made next. Item 3 differs from S11.9.8 only, not from the code, as the claim
  says.

### U08-17: Reset copy asks for no password when the server wants it again, so the click does nothing

- **Kind:** bug. **Req:** S13.7.2 ("resetting a linked copy" needs the password again after 10
  minutes), S11.9.8.
- **Code:** `web/ui/components/links.js:78-80, 467`: `copyAct` posts with `api.post(...)`
  (no `withReauth`, which `act` and `CopyKey` use), and Reset copy's call ends in
  `.then(() => setArmed(null), () => {})`, which drops the error; `ui/links.py:420` answers
  `reauth-required` when the password is older than 10 minutes.
- **What goes wrong:** an admin who signed in an hour ago presses **Reset copy**, then **Click
  again to reset**: the server refuses with `reauth-required`, the browser shows nothing and
  asks for nothing, and the button stays armed.
- **Run:** no; rests on reading.
- **Remedy:** `copyAct` calls through `withReauth`, and shows its error.
- **Check:** corrected. Severity unchanged. The click does fail for want of a password: `copies()`
  gets `copyAct` as its `act` (`links.js:271, 403`), whose `api.post` has no `withReauth`, and
  `reset_copy` calls `recent_auth`. But the error is not dropped: `links.js:488` renders
  `<FormError error=${act.error ...} />`, so the admin sees "Enter your password again to do
  this." with no field to do it in. Remedy stands: `copyAct` through `withReauth`.

### U08-18: `changes.orphans` is used nowhere

- **Kind:** untraced. **Req:** —.
- **Code:** `web/server/src/moolakata/links/changes.py:373-390` (`def orphans(srv, link_id)`):
  a second sweeper, which removes every `*.tmp` under the copy whatever its age; the sweep
  task uses `copies.orphans` (`copies.py:106-132`) and nothing calls this one.
- **Remedy:** delete it (it would remove a file being written if anyone called it).
- **Check:** confirmed. No caller of `changes.orphans` anywhere in `src` or `tests` (grep);
  `copies.orphans` is the one the sweep and the test use. It is also worse than the claim says: it
  removes every unnamed `*.mkr` whatever its age, as well as every `*.tmp`.

### U08-19: three refusals differ from the protocol's table

- **Kind:** differs. **Req:** `link-protocol.md` §7, S13.7.5.4.
- **Code:**
  1. the 60-calls-a-minute refusal is the app's problem+json with code `rate-limited`
     (`routes.py:27`, `ratelimit.py:71-76`); §7 names it `limit` (`client.py:129-133` reads the
     status, so its own peers cope).
  2. `routes.py:285-286`: a delivered receipt from a link that exists but isn't active is
     refused `not-linked` ("This server has no active link with yours"); §7 says
     `link-<state>`, and a `not-linked` answer marks the caller's link broken
     (`manage.py:121-128`; here it comes through `send_file`, which doesn't, so only the code
     differs).
  3. `routes.py:287-288`: `file-refused`, a code §7 doesn't list.
- **Run:** no; rests on reading.
- **Remedy:** the codes §7 names, or §7 lists `file-refused` and says `limit` is sent as
  problem+json.
- **Check:** confirmed. Read `ratelimit.too_many` (429, `rate-limited`), `routes._deliver_file`
  (`not-linked` for an existing link that is not active; `file-refused` for a bad id) and
  link-protocol.md §7 (`limit`, `link-<state>`, no `file-refused`); `client.call` treats any
  unsigned 429 as `limit`, so peers cope, as the claim says.

### U08-20: no link test goes through `net.Client`, so the ceiling, the timeouts and a long stream's checks are never run on a link

- **Kind:** test gap. **Req:** S13.5, `link-protocol.md` §1.4, §4.3.4; DC-1.
- **Code:** `web/server/tests/linkpair.py:47-76`: the `Wire` client hands each call to the peer's
  `TestClient`, so `test_links.py` and `test_copies.py` never pass through `net.Client`'s
  20 MB `_Capped` ceiling, its 10 s/20 s timeouts, or a stream long enough for U08-6's checks.
  `test_core.py:313-321` tests the client alone.
- **What goes wrong:** U08-1 (a receipt past the ceiling stops the link) and U08-6 (a
  minute-long stream refused) pass every test.
- **Remedy:** the `Wire` applies the same ceiling as `net.Client` (or wraps its answers in
  `net._Capped`), and tests send a receipt over it and one that takes over a minute (a clock
  moved between headers and end).
- **Check:** confirmed. `linkpair.Wire.client` replaces `net.Client` with a class that hands each
  call to the peer's `TestClient`; the `_Capped` ceiling and the timeouts are tested only in
  `test_core.py:313-321` on the client alone. This is why the scratch test for U08-1 had to cut
  the stream by hand.

### U08-21: the name a delivered receipt goes by is outside the signature

- **Kind:** security. **Req:** S11.1.3 (every call signed over method, path, body hash, time
  and nonce), S11.9.6.3 (a file renamed onto another receipt fails to open),
  `link-protocol.md` §1.2 ("not even a proxy in front of the peer reads it"), §4.3.4.
- **Code:** `web/server/src/moolakata/links/client.py:195-200` signs the `deliver` call over
  the path and the sealed bytes' digest, and sends the receipt's id in `MK-Link-File`, which
  the signed text doesn't name; `routes.py:258, 299` takes the id from that header.
- **What goes wrong:** a reverse proxy in front of the receiving server (which terminates TLS,
  and which §1.2 treats as untrusted) swaps the `MK-Link-File` headers of two delivered
  receipts: both are kept under each other's ids, and since the associated data names the
  receipt, neither opens (*can't be opened*, and their type is never found). It reads nothing
  and forges nothing; it can only spoil receipts, which the next full change sends again.
  Low.
- **Run:** no; rests on reading.
- **Remedy:** the signed text of a `deliver` carrying a file names it (the path's query,
  `/link/v1/deliver?file=<id>`, which the signature already covers).
- **Check:** confirmed. `signing.sign_request_digest` signs method, path, body digest, time, nonce
  and receiver; `client.send_file` puts the receipt's id in `MK-Link-File`, outside it, and
  `routes._deliver_file` only checks that it looks like an id. A proxy can rename a delivered
  receipt; as the claim says it spoils and forges nothing (a proxy can already drop a call), so
  Low stands.

## Phase 1 items judged against the code

| Item | What the code does | Reading it matches |
|---|---|---|
| DC-1 (D2-1, D3-1) | `deliver` bodies of sealed receipts are bounded by the *receiver's* receipt limit (`middleware.py:243-247`), not 20 MB; `file` answers by `net.Client`'s 20 MB (`net.py:24`). Past either, the link stops both ways, silently (**U08-1**, High) | neither: the protocol's 20 MB holds for `file` only; needs the user (which of DC-1's three) |
| D3-5 | delivered receipts wait in an in-memory map (`routes.py:246, 299`), popped whole by the link's next delivered change (`manage.py:616`); unnamed files are swept after 10 minutes only while the copy is open (`copies.py:106-132`), never while locked; a restart forgets the map | the protocol's "until the part that names it arrives", with D3-5's gap: nothing bounds them while locked (U08-7 for the sweep's own race) |
| D2-2 | no tax book document file crosses; only an account's receipts do (`serve.py:259-262`) | S11.5.1 and L6; under S11.4 and the Share dialog's reading, not built (**U08-14**); needs the user |
| DC-3 (D2-4, D3-6) | states `invited`, `requested`, `pending`, `active`, `paused`, `ended` (`tables/links.py:76-78`); *broken* is `brokenAt` on an active link, cleared by any exchange that works and left by End link; *unreachable since* is `failingSince`; *syncing* is `syncTotal`; the screen shows all of them (`links.js:31-38, 177-185`). `ping` is answered but never called. Linking again after an end fails (**U08-2**) | the protocol's table, with D3-6's gap; S11.7's list is narrower than the code |
| DC-11 | `join` sends `{code, address, t}` (`manage.py:266-269`) | the protocol (`t` is right; S11.1.2's "nothing else" is the document to change) |
| D3-2 | the type is found from the bytes when the copy applies the change (`changes.py:213, 264-275`) and again when shown (`ui/linked.py:367-370`); the change's `contentType` is sent (`serve.py:310`) and never used | both: "when it arrived" in the copy (first opened) and "when shown"; `files.type` is dead weight |
| D3-3 | the fetching side checks the answer's signature over the sealed bytes' hash before keeping the file (`client.py:180-186`); the plaintext hash when shown, before the last piece (`ui/linked.py:379-392`) | D3-3's remedy |
| D3-4 | every part is worked out, signed and sealed at once and kept in memory (`manage.py:582-591`) | the protocol as written; **U08-4** |
| D3-6 | see DC-3 | — |
| D3-7 | approving calls `exchange` at once (`manage.py:399-400`); a pending side doesn't poll sooner than hourly | the protocol plus D3-7's first half; T5.2's minute holds only when A can reach B |
| D3-8 | the wire names are `account`, `portfolio`, `budget`, `gift-plan`, `giving-plan`, `tax-book`, `projection`, `person` (`serve.py:25-34`, `links.js:18-27`) | what D3-8 asks §6 to list |
| D3-9 | `hello` answers `version` (`routes.py:137-142`) | the protocol as written |
| D3-22 | the folder's name is random (`copy.py:71-74, 160-171`), kept in `Link.copyFolder`, loaded at start (`runtime.py:293-304`); the code's comments cite "schema.md §2.5" too (`copy.py:62`, `tables/links.py:52`); a link with no name yet falls back to its id (`copy.py:68`), which no path writes to before a key is made | S11.9.1's rule; the citation is wrong in the code as in S11.9.1 |
| D2-5 | `shared.db` keeps every kind generically (`copydb.py`: Item, Doc, File) | the eight kinds all fit |
| D2-6 | hourly, fixed (`runtime.py:128-139`, `Every(3600)`) | "hourly, and on demand" |
| D2-7 | pulls and sends are recorded in Activity for admins, naming kinds, owners and people, never an item's name (`receive.py:82-115`, `manage.py:543-558`) | D2-7's remedy |
| D2-8 | the app's own invitation dialog also leaves the secret out (**U08-16**) | — |
| DC-9 | the copy's wrong-words counters are in memory (`copy.py:100-102`) | S13.7.5.5 |
| DC-10 | remote names are cut to 64 and 120 (`manage.py:341, 349, 358-359`), not refused (unit 07 judged the `User` side) | the protocol's limits, read as "cut" |
| DC-16 | **Release linked keys after** is a setting (`linkReleaseMinutes`, `copies.py:137`) | S16.9 |
| D2-25 / DC-4 | no relay code | — |

## Earlier findings re-checked

| Finding | State per review 2 | Found |
|---|---|---|
| K2 | done | holds: type from the bytes at apply and at show, refused unless it matches; `sandbox`, `Content-Disposition`, `no-store`, `nosniff` (`ui/linked.py:367-377`; tested, `test_links.py:440-451`) |
| K3 | done | holds: TLS always verified (`net.py:245-246` refuses `verify`), own certificates pinned by key (`net.py:151-161`), answers name caller and request (`signing.py:130-133`), only `link-ended` ends (`manage.py:119-128`), changes and receipts sealed to the copy (`serve.py:406-414, 417-447`). New beside it: U08-11 (announcements not retried), U08-21 (`MK-Link-File` unsigned) |
| K18 | done | holds but for one case: `https`, no query or fragment (`client.py:56-66`), URLs from the parsed base (`:69-72`), the guard connects to the address it checked (`net.py:174-177`), answers capped however sent (`:180-192`), peers' hosts never named outside dev (`ui/prices.py:154-159`); a peer's host that matches an admin-named host is exempt (**U08-13**) |
| K19 | done (m9) | holds where it reaches alerts (`client.py:142-147`); `send_file` still copies the peer's `code` and `message` into its `LinkError` (`client.py:218-220`), which today is never recorded (U08-1) |
| K22 | m9 (12.5.3) | holds: the key looked up in a read transaction, the link key opened only to sign, an unknown key's body over 1 MB refused on headers (`routes.py:44-68`) |
| K25 | m9 | holds: the database key in a `HeldKey` overwritten and refused after release (`store/db.py:43-59`, `copy.py:180-191`); apply refuses a `seq` at or below the last applied (`changes.py:174-181`; tested) |
| P5, C20 | done | holds: `join` carries no directory, a pending side sends none (`manage.py:266-269, 455-461`); the join guide says otherwise (U08-16) |
| P6 | m9 | judged in unit 05 (U05-25); the link sends what the routes give the remote viewer (`serve.py:240-258`) |
| B24 | done | holds: the caller's receipts go in `deliver` before their part (`manage.py:510-513`) |
| B25 | done | holds: long lists split into whole records by date (`serve.py:475-498`); U08-4 beside it |
| B26 | done | holds: shape checked before the transaction, set aside, everything asked for (`changes.py:168-208`; tested) |
| B41 | m9 | holds: a pull names its link and shares (`receive.py:82-93`), *Pull now* its actor (`ui/links.py:361-363`), words checked when already open (`copy.py:129-145`), the hash before the last piece (`ui/linked.py:379-392`); U08-15 for the copy's other entries |
| N9 | done | holds (60 a minute, `routes.py:15-30`) |
| N11 | m9 | holds: what flows each way (`ui/links.py:140-199`), the sweeper (`copies.py:106-132`), views recorded (`ui/linked.py:216-231`); U08-7 |
| C10, C14 | done | holds (random folder; D3-22 above) |
| C17 | m9 | half holds: unsigned `limit` and `locked` handled; three codes differ (**U08-19**) |
| C18 | m9 | the documents agree; the code doesn't send removals over a paused link (**U08-10**) |
| C23 | done | holds on the link side (`manage.py:244-249`) |
| C33 | m9 | holds: `person` crosses (`serve.py:183-188`) |

## The uncited first-level items and untraced code

The map gives this unit none. Read for it: `changes.orphans` serves nothing (**U08-18**); the
`/link/v1/ping` route serves the protocol's table though nothing here calls it (DC-3 above).

## Checked and sound

- **Signing** (`signing.py`): the request's signed lines (method, path with query, body hash,
  time, nonce, receiver's fingerprint) and the answer's (status, body hash, time, the call's
  nonce, caller's fingerprint and body hash) match `link-protocol.md` §3; 60 s skew, nonces kept
  120 s per key (enough for the skew window), checked after the signature so forged calls can't
  fill it; the receiver's own fingerprint is in the signed text, so a call can't be replayed to
  another server.
- **Joining** (`manage.py:235-321`): `hello`'s key is hashed against the code's fingerprint
  before anything is sent; the secret is 192 bits, kept as a hash, used once, 24 hours; the
  join's signature proves the key; `already-linked` for a live link; nothing crosses before
  approval.
- **The sealed format** (`sealed.py`): per-file X25519 and HKDF salt, AES-256-GCM per 64 KiB
  chunk, nonce of prefix, counter and last flag, associated data naming direction, file and
  chunk; truncation after a whole chunk, reordering, renaming and a 0-byte or exact-multiple
  file all handled (traced by hand, and `test_sealed.py:39-90`).
- **The direction in the associated data** (`keys.py:108-112`): a change sealed for one
  direction or link opens for no other.
- **Change signatures** (`changes.py:43-47, 84-94`): canonical JSON over the registry and the
  sealed part's hash; checked when taken and again when applied; sequence checked at both.
- **The copy key** (`copy.py`): 128-bit, 12 BIP39 words, HKDF to the database key and the X25519
  key, never stored; unlock checks the words even when open; five wrong in a row wait 15
  minutes, 20 an hour per copy; the release disposes the engine, overwrites the key and the
  `HeldKey`, and a connection after it fails.
- **The linked window's access** (`ui/linked.py`): every read requires the user to be named
  (registry and copy), documents are looked up by viewer, files by an item naming the viewer;
  the hash is checked before the last piece is sent.
- **TLS and the guard** (`net.py`): verification always on, pinning by the key after the
  handshake, the vetted address connected to with the name kept for SNI, answers capped
  however sent.
- **Who is shared**: only `read` shares to a link's own active remote users cross
  (`serve.py:84-118`), `write` to a linked user is refused at the share (`sharing.py:134-141`),
  gifts for a user of that server never cross, Include receipts is per link.

## Read lightly or not read

- `ui/screens/linked.js` was read for its header strip, the locked screen and the kinds
  (about a third of it); its per-kind screens were not read line by line.
- The linked window's guides other than `linked-locked.md` and `linked-receipts.md` were
  listed, not read.
- The migrations `0010`, `0013`, `0016` were not read (the tables were).
- U08-3, U08-4, U08-6 and U08-10 rest on reading; U08-4's size threshold was not measured.
- The tests were read by their names and the ones the claims lean on (`test_links.py`
  receipts, pinning, refusals; `linkpair.py` whole).

## Work pad: severity, confirmations, status

| Id | Kind | Req | Sev | Conf | Status | Description |
|---|---|---|---|---|---|---|
| U08-1 | bug | S11.4, S11.2, DC-1 | High | 0 | open | One receipt the pulling side can't fetch (past 20 MB, say) stops the link both ways for good, unrecorded and unalerted |
| U08-2 | bug | S11.6 | Med | 0 | open | Two servers whose link ended can never link again: the join answers 500 on both sides |
| U08-3 | bug | S11.4, S13 | Med | 0 | open | A peer's exchange or delivery is answered on the event loop: the whole server waits for it |
| U08-4 | bug | S11.4, S13.5 | Low | 0 | open | An exchange's answer is worked out whole before a byte goes; past the caller's 20 s it is never pulled |
| U08-5 | security | S13.7.5.4, S13.7.6 | Med | 0 | open | Withheld (`withheld.md`) |
| U08-6 | bug | S11.1.3, S11.2 | Med | 0 | open | A receipt that takes over a minute to cross is refused as a clock problem |
| U08-7 | bug | S11.9.6.6, S11.9.5 | Med | 0 | open | The minute's sweep deletes receipts that arrived while locked when it runs during an unlock's apply |
| U08-8 | privacy | S11.9.1, S11.9.10 | Med | 0 | open | Withheld (`withheld.md`) |
| U08-9 | bug | S11.3 | Low | 0 | open | A peer's directory is kept unchecked: a non-object avatar breaks Settings › Linked servers |
| U08-10 | privacy | S11.4, R3.4 | Low | 0 | open | A paused link holds back a share's removal, which S11.4 says still crosses |
| U08-11 | bug | S11.1.3 | Low | 0 | open | A certificate change a peer missed is never announced to it again |
| U08-12 | bug | S11.4, S11.9.5.3 | Low | 0 | open | One link's malformed change stops the hourly exchange for every link after it, unrecorded |
| U08-13 | security | S11.2, S13.5 | Low | 0 | open | A link address is exempt from the loopback refusal when its host is named like the SMTP host or node |
| U08-14 | differs | S11.5.1, D2-2 | Low | 0 | open | Gift and donation receipt files never cross; a tax book's document list crosses without Include receipts |
| U08-15 | differs | S11.8 | Low | 0 | open | A restart's release isn't recorded, and the copy's and link's events don't say which link |
| U08-16 | differs | S11.1.1, S11.1.2, S11.9.8 | Low | 0 | open | The join guide, the invitation dialog and Reset copy's text say other than S11 or the code |
| U08-17 | bug | S13.7.2, S11.9.8 | Low | 0 | open | Reset copy asks for no password when it is needed again, so the click does nothing |
| U08-18 | untraced | — | Low | 0 | open | `changes.orphans` is used nowhere |
| U08-19 | differs | link-protocol §7 | Low | 0 | open | Three refusals differ from the protocol's table |
| U08-20 | test gap | S13.5, DC-1 | Low | 0 | open | No link test goes through `net.Client`: the ceiling, timeouts and long streams are never run on a link |
| U08-21 | security | S11.1.3, S11.9.6.3 | Low | 0 | open | The name a delivered receipt goes by is outside the signature |

Scratch runs: `/home/dev/.claude/jobs/b8ac83ff/tmp/u08/` (`t/test_u08.py` and its outputs
`run1.txt`–`run4.txt`).

## Found while checking

Unverified: written by the checker, who read the code but ran nothing for it (REVIEW.md §8).

### U08-F1: a join call from any address is read whole, up to 20 MB, before its signature is looked at

- **Kind:** security. **Severity:** Low. **Req:** S13.7.5.4 (calls not yet signed by a known key,
  "checked before a body is read"; a body of an unknown key over 1 MB refused on its headers),
  S13.7.6; review 2's K22.
- **Code:** `web/server/src/moolakata/links/routes.py:162-165`:
  ```text
  async def join(request: Request):
      ...
      srv = request.app.state.server
      body = await request.body()
  ```
  every other `/link` route reads its body through `body_of` (`routes.py:55-62`), which refuses
  an unknown key's body over `UNKNOWN_BODY` (1 MB) on its headers; `join` is the one route a
  stranger's key may call, and it skips that. `middleware.py:38` `LINK_LIMIT` is 20 MB for
  every `/link` path, and `join`'s body is a few hundred bytes (`code`, `address`, `t`).
- **What goes wrong:** anyone who can reach `/link/` posts a 20 MB body to `/link/v1/join`; it
  is held in memory and hashed before `verify_request` refuses it, as often as the per-address
  limit allows (60 a minute), and from many addresses as often as they like.
- **Remedy:** `join` refuses a body over a few KB on its headers (a limit of its own, below
  `UNKNOWN_BODY`), before it is read.

