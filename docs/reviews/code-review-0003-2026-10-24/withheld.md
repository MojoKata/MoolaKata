# Withheld claims, code review 3 (git-ignored; docs/REVIEW.md §2)

## U03-3 (unit 03): a nested repeat inside a group passes the rule check, and one payee freezes the server

- **Kind:** security. **Severity:** Med. **Req:** S2.7.1 ("a nested repeat such as `(a+)+` is
  refused, as it can take a payee forever"), R3.1/S13 (one server for the household).
- **Code:** `web/server/src/moolakata/ledger/rules.py:143-145`:
  ```text
  # A repeat inside a repeated group, such as (a+)+ or (\w*)*: on a payee that nearly matches it
  # backtracks for ever.
  NESTED = re.compile(r"\((?:[^()\\]|\\.)*[+*}](?:[^()\\]|\\.)*\)\s*[+*{]")
  ```
  The group's body may hold no parenthesis, so a repeat one group deeper isn't seen:
  `re:((a+))+$`, `re:(?:(a+))+$`, `re:((ab)+)+$` all compile (`compile_pattern` returns a
  pattern). Alternation such as `re:(a|aa)+$` isn't looked for either.
- **What goes wrong:** any signed-in user saves the rule `re:((a+))+$` (Transactions › Rules).
  Python's `re` holds the GIL while it backtracks, and the time doubles with each character:
  22 a's and a `!` take 0.27 s, so 40 take about a day and the 500 the matcher reads
  (`rules.py:202`) never end. The rule runs on GET `/ui/api/rules` (`_list` counts what it
  could set), on *Apply to the uncategorised*, on every import (`store/repos/ledger.py:460`,
  a connector's fetch included) and on a receipt's merchant (`receipts/reading.py:303`). One
  payee such as "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA!" (a bank's text, or a transaction
  the user types) stops every request of the household's server until it is restarted, and it
  stops again at the next import or listing. Only the user who saved it can delete it, and
  only while the server answers.
- **Run:** yes, `tmp/u03/t/test_u03.py::test_nested_repeat_inside_a_group_passes`: the three
  patterns compile; 22 + 1 characters take 0.27 s (exponential growth).
- **Remedy:** refuse any repeat applied to a group that contains a repeat at any depth (parse
  the pattern with `re._parser` / `sre_parse` and walk the tree for MAX_REPEAT inside
  MAX_REPEAT, and for alternation whose branches overlap under a repeat), and run matching
  with a time limit: the `regex` module's `timeout=`, or a match on a bounded payee in a
  worker with a deadline.
- **Alternatives:** drop `re:` for a small glob syntax (`*`, `?`, `^`, `$`) that can't
  backtrack; or compile with Google's RE2 (`google-re2`), which has no backtracking.
- **Status:** open, 0 confirmations.


- **Check (unit 03 checker):** corrected. **Lines:** the code is in `ledger/rules.py:11-13` (`NESTED`, with its comment) and `:41` (the check in `compile_pattern`), and the 500-character cut is `ledger/rules.py:70` (`text = (payee or "")[:500]`); the file has 81 lines, so the cited 143-145 and 202 don't exist. Everything else holds, severity Med unchanged. Read `compile_pattern` (the regex `NESTED` allows no parenthesis inside the group, so `((a+))+`, `(?:(a+))+` and `((ab)+)+` pass), `ui/rules.py` `_check` (only `compile_pattern` guards a saved rule; any signed-in user may save one), the three callers (`ui/rules.py:119` `_list`, `store/repos/ledger.py:460` on import, `receipts/reading.py:303`). Ran: `re:((a+))+$` compiles and `search("a"*n + "!")` takes 0.016 s at 18, 0.064 s at 20, 0.259 s at 22 and 1.027 s at 24 characters (times four per two characters), so about a day at 40 and never at the 500 the matcher reads; Python's `re` holds the GIL while it backtracks. The stall runs where the owner's rules run on a payee: their listing, *Apply to the uncategorised*, their imports and receipts (a connector's fetch included), so the household's server stops while any of them runs. The claim's own scratch test asserts `> 0.5 s` at 22+1 characters and fails on its threshold (0.25 s measured, the claim says 0.27), not on the finding.

## U06-1 (unit 06): a receipt's dialog names every thing it is kept with, in accounts, gift plans and tax books the viewer can't see

- **Kind:** privacy. **Severity:** Med. **Req:** S9.6 ("Sharing follows what the receipt is
  attached to"), S9.3 ("its dialog names each thing it is kept with"), R3.4 (a share is never
  passed on), S10 (one user never sees what isn't theirs), S7.7 (gift plans kept from the
  person they're for).
- **Code:** `web/server/src/moolakata/ui/receipts.py:111-117, 181-197` (and the gift, donation,
  item, expense, statement and tax-document branches at `:118-179, 198-214`):
  ```text
  def _links(s, r: Receipt, user_id: str | None = None) -> list[LinkOut]:
      ...
      out = []
      for ln in receipts.links(s, r.id):
      ...
          t = s.get(Transaction, ln.itemId)
          if t is None or t.deleted:
              continue
          a = s.get(Account, t.accountId)
          out.append(
              LinkOut(
                  kind="transaction",
                  itemId=t.id,
                  transactionId=t.id,
                  accountId=a.id,
                  accountName=a.name,
                  date=t.date,
                  amount=t.amount,
                  payee=t.payee,
  ```
  `user_id` is used only for a gift's or donation's `canDetach`; nothing filters a link by
  whether the viewer can read what it points to. `row()` (`:234`) and so `GET /receipts`,
  `GET /receipts/{id}`, `GET /transactions/{id}/receipts` and every answer that carries a
  receipt's detail return every link.
- **What goes wrong:** Alice keeps a receipt on a transaction in her private account
  ("Alice private", *Secret Jeweller*, −42.18) and on one in the joint account she shares with
  Bob for reading. Bob opens the receipt from the joint account and its links list the private
  account's id and name and the transaction's id, date, amount and payee. The same holds for a
  gift (*The gift {description}* with its cost: a receipt for Bob's birthday present kept on
  the joint account's transaction and on the gift tells Bob what he is getting), a donation
  (organisation and amount), an item or 529 expense in an unshared account, a statement's
  account, and a tax document in a book Bob doesn't file (form, year, issuer).
- **Run:** yes, `tmp/u06/t/test_u06.py::test_links_of_an_unshared_account_reach_a_reader`:
  Bob's `GET /receipts/{id}` and `GET /transactions/{joint}/receipts` both list
  `('Alice private', 'Secret Jeweller', -42.18)` beside `('Joint', 'Blue Bottle', -42.18)`.
- **Remedy:** `_links` takes the viewer and keeps a link only when the viewer can read what it
  points to (the account's level, `_kept_level` for gifts and donations, the book's filers for
  a tax document); the owner sees all of them. Keep the count of the rest if the dialog wants to
  say "and 2 more things you can't see".
- **Alternatives:** show a hidden link as *something not shared with you*, with no id, name,
  date or amount (as S11.3.1 names *an account not shared*).
- **Status:** open, 0 confirmations.

- **Check (unit 06 checker):** confirmed. Read `ui/receipts.py:_links` (`:111-231`) and `row()` (`:234-258`): `user_id` reaches only a gift's or donation's `canDetach`, so every link kind (transaction with its account name, date, amount and payee; item and expense; statement; gift with its cost; donation; tax document with form, year and issuer) is returned to whoever can open the receipt, and `receipts.visible`/`level` let a reader of one linked account open it. Ran the claim's scratch test (copy of `test_u06.py`): Bob's `GET /receipts/{id}` lists `('Joint', 'Blue Bottle', -42.18)` and `('Alice private', 'Secret Jeweller', -42.18)`, and `GET /transactions/{joint}/receipts` lists both; Bob's `GET /accounts/{private}` is 403/404. Med stands: names, amounts and dates of an unshared account, and a gift plan's cost, cross the line S9.6, R3.4, S10 and S7.7 draw.

## U06-3 (unit 06): the reader's worker may still open Unix sockets, and the host commands' socket trusts whoever reaches it: a file that takes the worker can rotate the master key and delete the copies

- **Kind:** security. **Severity:** High. **Req:** S9.8.4.2 ("**The worker is a sandbox**, for a
  file that exploits the libraries that read it … a worker an exploit has taken can't run code
  in the server"; "a seccomp filter denies it network sockets; on a kernel with Landlock … it
  can't open the data directory"), S15.4.7 and S13.6 (host commands over the server's socket),
  S15.7.1 (rotation over the socket needs no old phrase), R1.17.
- **Code:** `web/server/src/moolakata/sandbox.py:85-90`:
  ```text
              ins(jeq, 1, 0, socket_nr),  # 6: socket: on to 8
              ins(ret, 0, 0, SECCOMP_RET_ALLOW),  # 7: anything else
              ins(ld, 0, 0, 16),  # 8: its first argument, the address family
              ins(jeq, 0, 1, AF_UNIX),  # 9: a local socket: allowed at 10
              ins(ret, 0, 0, SECCOMP_RET_ALLOW),  # 10
  ```
  `host.py:1-6`: the socket `/run/moolakata/sock` "is no network listener: only the server's own
  account (or root) inside the container can open it, so reaching it is the host access that
  authenticates these commands". The worker runs under that same account
  (`receipts/reading.py:75-82`: `Popen([sys.executable, "-I", "-m",
  "moolakata.receipts.worker", …], env={}, close_fds=True)`, no change of user). `host.py:67-90`:
  `POST /host/keys/rotate` takes `phrase` (the new one), no old phrase, and `copies` with
  `delete` for each copy, deleted at once. Landlock (`sandbox.read_only`, first-version rights
  only) governs opening files, not `connect()` to a Unix socket by path, and on a kernel
  without Landlock (this build host's, and the alert's case, S9.8.4.2.5) nothing does.
- **What goes wrong:** an emailed invoice PDF (or a statement the connector fetches, a HEIC
  photo, an OFX file) carries an exploit for pdfium, libheif or Pillow, and runs code in the
  worker as it is read. The worker opens `socket(AF_UNIX)`, connects to
  `/run/moolakata/sock` and posts `/host/keys/rotate` with a phrase only the attacker knows and
  every copy marked `delete`: the keyring is re-wrapped at once, the backups and `pre-upgrade/`
  copies on the host are deleted, and Activity shows a rotation "on the host". At the next
  restart the household's phrase no longer unlocks anything. The same reach gives `/host/backup`
  and `/host/unlock` (lockout counting), and the worker can also signal the server (same
  account) to stop it, which locks it until a person comes.
- **Run:** yes, `tmp/u06/s/unix_after_seccomp.py`: a process under `sandbox.no_network()` is
  refused `AF_INET` (EACCES) and still connects to a 0700-directory Unix listener of its
  account and sends `POST /host/keys/rotate`. Landlock is absent on this host (kernel 4.18), so
  that path rests on reading and Landlock's documented rights.
- **Remedy:** the filter refuses `socket()` for every family (the worker talks only over the
  pipes it inherited), and `socketpair`, `connect` and `bind` too for good measure; and the
  worker runs under an account of its own (a second uid in the image, or a user namespace),
  so neither the socket nor signals reach the server. Host routes that change keys also check
  `SO_PEERCRED` against the server's pid (refusing the worker's).
- **Alternatives:** keep AF_UNIX open only for what a library needs (none of the four do) and
  move the host socket into a directory the worker's Landlock rules leave out (not enough on
  hosts without Landlock); or have rotation over the socket ask the old phrase as well, which
  S15.7.1 says it needn't (that rule would then need changing).
- **Status:** open, 0 confirmations. **Fixed, Oct 28:** `05f523a`, its details written into the
  review (`e815b81`), merged and pushed in `4c7d7cc`: published, as no household uses a server yet.

- **Check (unit 06 checker):** confirmed, High stands. Read `sandbox._filter` (socket refused for every family but `AF_UNIX`; step 9-10 allow it), `host.py` (`/run/moolakata/sock`, 0700 directory of the server's account, no peer check; `POST /host/keys/rotate` takes the new phrase, `oldPhrase` optional, `copies` with `delete` acted on at once by `maintenance.rotate_running`, whose own docstring says no old phrase is needed), `Worker._start` (a plain `Popen`, no change of user) and the `Dockerfile` (`USER 10001`, the same account for server and worker; the TrueNAS compose's `user: "0:0"` is only the one-shot `permissions` service). Landlock v1 (`sandbox.read_only`, `FS_ALL_V1`) covers file opens and not `connect()` to a socket path, and the worker's roots don't include `/run`. Ran the claim's scratch script (copy): under `sandbox.no_network()` `AF_INET` is refused (EACCES) and a connect to a 0700-directory Unix listener of the same account succeeds and sends `POST /host/keys/rotate` (seccomp True, Landlock False on this 4.18 kernel). Needs an exploit in pdfium, libheif, Pillow or ofxtools to run code in the worker, which is the threat S9.8.4.2 names, and the result (the household's data key re-wrapped under a phrase only the attacker knows, every copy deleted) is not recoverable; High is right.

## U07-1 (unit 07): correcting an invited user's email leaves the invitation sent to the wrong address working

- **Kind:** security. **Severity:** Med. **Req:** S10.1.3 (the invitation link; "sending a new
  one ends the one before"), S10.1.5 ("An admin corrects a user's email address only until the
  user has joined").
- **Code:** `web/server/src/moolakata/auth/users.py:676-686` (`update_user`):
  ```text
      if email is not None and email.strip().lower() != (user.email or ""):
          if user.passwordHash is not None:
              raise refuse(
                  ...
          _raise(_email_problems(s, email, user.id))
          user.email = email.strip().lower()
          fields.append("email")
  ```
  Nothing ends the `OneTimeToken` of purpose `invitation` (only `_issue` deletes one, when a new
  invitation is sent), and `ui/users.py:175` (`change_user`) sends nothing. The dialog promises
  the opposite: `web/ui/screens/users.js:354-355`:
  ```js
          hint=${user.invited
            ? 'Fix it before they join; the invitation then goes to the new address.'
  ```
- **What goes wrong:** an admin invites Eve as `eve@hme.lan` (a typo; or a typo-squatted
  domain), in the Admins group. The mistyped address's owner receives the link. The admin
  notices and corrects the address to `eve@home.lan` in Edit user; per the hint they believe
  the invitation now goes there. Nothing is sent to the new address, and the first link keeps
  working for its 7 days: whoever holds it opens it, chooses a password and is signed in as
  `eve`, with her groups (an admin's if she was invited into Admins). Eve's later Resend makes
  a new link and ends the first, but by then the account is taken.
- **Run:** yes, `tmp/u07/t/test_u07.py::test_corrected_invitation_old_link_still_works`: after
  the PATCH no email is written, and the old token's `invitations/accept` answers 200 as `eve`.
- **Remedy:** when an invited user's email changes, delete their pending invitation token and
  send a new invitation to the new address (`_send_invitation`), recorded as
  `user.invitation-resent`; a test that the old link answers 404 afterwards.
- **Alternatives:** end the old token and leave sending to **Resend invitation**, with the hint
  saying so.

**Check (unit 07 checker, Oct 25): confirmed.** Read `update_user` (`auth/users.py:668-695`), `change_user` (`ui/users.py:160-185`), `_issue`/`_take`/`accept_invitation` (`auth/users.py:289-330, 413-433`):
the invitation `OneTimeToken` is bound to the user id, never to the address, `update_user` neither deletes it nor sends a new one, and `users.js:354-355` promises the invitation
"then goes to the new address". Reran `test_u07.py::test_corrected_invitation_old_link_still_works`: passes (no mail after the PATCH; the old link's accept answers 200 as `eve`).
Severity Med stands: the holder of the first link takes the account with its groups; it needs the admin's typo to land on a real mailbox, which is why it is not High.

## U07-4 (unit 07): concurrent sign-ins from one address all hash past the lockout; forty at once exhaust a 2 GB server's memory

- **Kind:** security. **Severity:** Med (High if the release is meant to face the internet
  directly; the server comes back locked, waiting for the recovery phrase). **Req:** S13.7.5.1
  ("10 failures in 15 minutes lock the address"), S13.7.3 (argon2id at 64 MiB), DEPLOY.md §1
  ("2 GB of memory for MoolaKata (1 GB with receipt reading turned off)"), S15.4 (a restart
  waits for the phrase).
- **Code:** `web/server/src/moolakata/ui/session.py:178-191` (`sign_in`, a sync route run on
  the thread pool, 40 threads by default):
  ```text
      locked = guard.locked(address)
      if locked:
          raise too_many(locked, "failed sign-ins from this address")
      ...
      with srv.db.tx() as s:
          user = accounts.by_login(s, login)
          ok = passwords.verify(user.passwordHash if user else None, body.password)
          if not ok:
              count_failure(s, guard, login, address, user)
  ```
  The lock is read before the hash and the failure counted only after it
  (`ratelimit.py:102-107, 123-140`), and nothing bounds how many argon2 hashes run at once in
  the process (argon2-cffi releases the GIL; `passwords.py:14`, 64 MiB each). The `_throttle`
  routes count first (`Window.hit`), so they bound at 30 per address; sign-in doesn't.
- **What goes wrong:** one anonymous client, with no account, opens 40 connections and posts
  `{"login": "admin", "password": "x"}` on each at the same moment. All 40 pass `locked()`,
  all 40 hash at once: about 2.6 GiB on top of the server's own memory. On the documented 2 GB
  host (or the 1 GB one) the kernel or the container runtime kills the process; it restarts
  locked and stays down until an admin types the 12 words (S15.4). The address is locked
  afterwards, but a second address (or the next quarter hour) does it again. Below the memory
  limit, it still lets 40 guesses through per address per lockout window, not 10.
- **Run:** yes, `tmp/u07/s/argon_parallel.py`: 16 threads checking the guard and verifying at
  once: all 16 passed the lock check and hashed; peak RSS 1,070 MiB from 107 MiB (so 40 is
  about 2.6 GiB). Not run against the live server (it would take the machine's memory).
- **Remedy:** (1) a process-wide semaphore around every argon2 hash and verify (sign-in, setup,
  invitation, reset, sign-up, change, re-auth, reactivation), sized to the memory (2 at a time,
  64 MiB each), with a short wait and a 429/503 `Retry-After` beyond it; (2) the guard reserves
  an attempt before the hash (failures plus attempts in flight against the threshold), so the
  11th concurrent attempt is refused before it hashes.
- **Alternatives:** lower argon2's memory cost (S13.7.3 would change) — weaker against offline
  guessing; or a per-address in-flight cap of 1 for sign-in.

**Check (unit 07 checker, Oct 25): corrected, Severity now Low.** The claim's main consequence does not hold. `sign_in` (`ui/session.py:187-189`) runs `passwords.verify` *inside*
`with srv.db.tx()`, and `tx()` is `BEGIN IMMEDIATE` (`store/db.py:89-95, 105-114`), so SQLite's single writer lock serialises the hashes: only one argon2 runs at a time, not 40. The scratch
`argon_parallel.py` checks the guard and verifies outside any transaction, so it did not model this. My own run (`tmp/check/unit-07/test_c07b.py`, real argon2id 64 MiB x 3,
12 clients at once from one address): all 12 answered 401 one hash apart (0.21, 0.32, 0.47 ... 1.36 s), peak RSS 282 MiB from 214 MiB (one hash's
worth, not 12). So there is no memory exhaustion and no kill-and-lock-until-phrase.
What survives: the lockout is read before the hash and not again after waiting for the write lock, so a burst of up to the thread pool's 40 requests gets all of its guesses
through even though the threshold is 10 (all 12 of mine hashed, none refused with 429). That is a few times the allowed guesses per lockout window, once per window, behind argon2's
cost: Low. Remedy for what is left: re-check `guard.locked(address)` inside the transaction before verifying (or reserve the attempt before the hash). A second consequence of
the same line is recorded as U07-F2 in the unit file (hashing while holding the one write lock).

## U08-5 (unit 08): anyone who knows a linked server's public key can use up that link's call limit and upload budget, and stall the link

- **Kind:** security. **Severity:** Med. **Conf:** 0. **Status:** open.
- **Req:** S13.7.5.4 (`/link`'s 60 calls a minute, per link), S13.7.6 (100 MB of uploads in
  flight per caller, "a linked server's key"), S11.1.3 (only a signed call from a linked key
  counts as that link's); `link-protocol.md` §7 (`limit`).
- **Code:**
  - `web/server/src/moolakata/links/routes.py:15-30`, the router's dependency, run before any
    signature check:
    ```text
        key = request.headers.get("mk-link-key", "")
        link_id = None
        if key:
            with srv.db.read() as s:
                link_id = s.scalar(select(Link.id).where(Link.peerKey == key, Link.deleted == false()))
        if link_id:
            srv.link_limit.check(link_id, "calls from this linked server")
    ```
    The header is whatever the caller writes; `link_limit` is a `Window(60, 60)` (`app.py:68`).
  - `web/server/src/moolakata/middleware.py:229-231` (`BodyLimit._caller`): an upload is
    counted against `"key:" + headers[b"mk-link-key"]`, unchecked, toward `IN_FLIGHT` (100 MB).
  - `web/server/src/moolakata/links/client.py:129-133`: the genuine peer's call, answered 429
    unsigned, becomes `LinkError("limit")`, which `manage.exchange` records as a failure
    (`manage.py:477-480`).
  - The key is public: `GET /link/v1/hello` answers it to anyone (`routes.py:131-142`), and
    `/link/` is the part a household exposes (operations.md §1.1).
- **What goes wrong:** Mallory reads B's key from B's `hello`, guesses (or tries) that B links
  to A, and sends A 61 unsigned POSTs a minute to `/link/v1/ping` with `MK-Link-Key: <B's
  key>`. Each is refused (`unsigned` or `bad-signature`), but each counts against B's link
  first, so B's own exchanges get `429 limit` for as long as Mallory keeps it up: nothing of
  either household crosses, and after the threshold A's admins are alerted that B "isn't
  reached", though B is fine. With `Content-Type: application/octet-stream` and a declared
  length near 100 MB, a few held-open uploads with B's key also fill B's in-flight budget at A
  (`429 uploads-in-flight` for B's receipts). The probe also tells Mallory whether A links to
  B (the 429 comes only for a linked key). And a `deliver` with that header and an
  octet-stream body is written whole to `links-in/` before its signature is checked
  (`routes.py:259-278`: `known(request)` reads only the header), up to the receipt limit per
  call, so each held call also costs A that much disk until it ends.
- **Run:** no; rests on reading.
- **Remedy:** count calls against a link only once their signature verifies (the check is
  cheap and reads only headers and the body's hash); before that, count every call against
  its address, whatever key it names, as unknown keys are (`link_unknown`), with a limit
  generous enough for a peer's own calls behind a shared NAT; key the in-flight budget for
  `/link` by address until verified. A test that unsigned calls naming a linked key don't
  touch that link's limit.
- **Alternatives:** a separate, smaller per-address limit for calls that fail their
  signature, so a flood from one address is cut off without touching any link.

- **Check (unit 08 checker, Oct 25):** confirmed. Read `routes.limit` (the router's dependency
  looks up the header's key in `Link.peerKey` and counts the call against that link before any
  signature is read), `app.py:68-69` (`link_limit` and `link_unknown`, both `Window(60, 60)`),
  `ratelimit.too_many` (a 429 problem) and `middleware.BodyLimit._caller` (`"key:" + header`
  keys the in-flight budget on an unverified header), and `client.call`/`manage.exchange` (an
  unsigned 429 becomes `LinkError("limit")` and is recorded as a failure, which `alerts.py:208`
  turns into an alert). S13.7.5.4 says "calls not yet signed by a known key 60 a minute per
  address", which the code does not do for a call that names a known key. `GET /link/v1/hello`
  gives the key to anyone. Severity Med stands. Not run: it rests on reading.

## U08-8 (unit 08): every change waiting in a locked copy's inbox keeps its registry beside it in plain JSON: the other household's owners' names, what kinds they share, with whom and when

- **Kind:** privacy. **Severity:** Med. **Conf:** 0. **Status:** open.
- **Req:** S11.9.1 ("The main database holds only what is needed while the copy is locked …
  File and folder names are random, so the folder shows no names, payees or dates"), S11.9.10
  ("A stolen disk, a backup that leaves the house, and root reading files while the copy is
  locked reveal nothing of a linked copy beyond its size, its number of receipts and when
  changes arrived"), S11.9.9 (the host's backup carries the copies "encrypted under their
  access keys"), S11.9.5.1.
- **Code:** `web/server/src/moolakata/links/changes.py:121-124` (`enqueue`):
  ```text
      registry = {k: v for k, v in change.items() if k != "sealed"}
      entry = exactjson.dumps({"change": registry, "local": local or {}}, separators=(",", ":"))
      sealed.write(d / f"{name}.json", [entry.encode()])
      sealed.write(d / f"{name}.mks", [unb64(change["sealed"])])
  ```
  `sealed.write` (`sealed.py:112-124`) writes the bytes as given: the `.json` beside each
  sealed `.mks` in `links/<random>/inbox/` is plain. The registry (`changes.py:39`, protocol
  §4.4) holds each item's `id`, `kind`, `ownerName`, `sharedAt`, `viewers` (this server's user
  ids) and `includeReceipts`, the change's `asOf`, `progress.through` (the newest record's date
  reached) and the receipts' ids. The same facts in the main database are under SQLCipher
  (S15); here they are not. The files stay until the copy is unlocked and applies them, which
  by design may be days (S11.9.5).
- **What goes wrong:** the parents' server keeps the copy of their daughter's shares locked, as
  intended. A disk pulled from it, a host backup of the data directory taken off site, or root
  reading files while it is locked shows, in `inbox/0000000001.json` …, "Alice Griffin" sharing
  a `tax-book` and an `account` with receipts, with which local user ids, since when, and how
  far back her records reach: the who-shares-what-with-whom that S11.9.1 keeps out of the
  folder and S11.9.10 promises a locked copy doesn't reveal.
- **Run:** no; rests on reading.
- **Remedy:** the registry the copy needs to apply a change stays inside the sealed part (the
  source seals the whole change, and the receiver keeps its registry in the main database as
  it already does in `LinkedItem`), or the `.json` is sealed to the copy's public key like the
  change beside it; the `local` file names go into the main database (they are random) or into
  the same sealed entry.
- **Alternatives:** the `.json` holds only `seq` and the receipts' random names, and `apply`
  reads the rest from the opened change, which carries its registry under its signature.

- **Check (unit 08 checker, Oct 25):** confirmed. Read `changes.enqueue` and `sealed.write`: the
  `.json` entry is written as bytes as given, beside the sealed `.mks`; `seal_part` leaves the
  registry (`items` with `kind`, `ownerName`, `sharedAt`, `viewers`, `includeReceipts`, `asOf`,
  `progress`, `fetch`) in the open. S11.9.10 says a stolen disk, an off-site backup or root
  reading a locked copy reveal nothing beyond size, receipt count and when changes arrived.
  Nothing else seals that file. Severity Med stands. Not run: it rests on reading.

## U09-1 (unit 09): an upload is read whole into memory before anyone is signed in, and the in-flight cap is keyed by whatever cookie the request carries

- **Kind:** security. **Severity:** Med (High if the release is meant to face the internet
  directly). **Conf:** 0. **Status:** open.
- **Req:** S13.7.6 ("at most 100 MB of uploads in flight per user … an upload is held in
  memory"), S13.7.5.3 (60 uploads an hour per user), S16.14 (no ranges by default), DEPLOY.md
  §1 (2 GB for the server).
- **Code:**
  - `web/server/src/moolakata/middleware.py:216-233` (`BodyLimit._caller`): the caller an
    upload is counted against is the SHA-256 of the `mk_session` cookie's value, unchecked:
    ```text
            if COOKIE in cookie:
                return "session:" + hashlib.sha256(cookie[COOKIE].value.encode()).hexdigest()
    ```
  - `web/server/src/moolakata/app.py:154-158`: `MultiPartParser.spool_max_size = 128 * 1024 *
    1024`, so each part up to 128 MiB is held in memory; `upload_cap` lets a body be the larger
    size limit plus 1 MB (26 MiB by default, up to 201 MiB).
  - `web/server/src/moolakata/ui/receipts.py:313-318` (and `ui/imports.py:235-237, 1047-1049`):
    `async def upload(request: Request, file: UploadFile = File(...), c: Caller =
    Depends(caller))`. FastAPI 0.143 reads and parses a form body before it solves any
    dependency (`fastapi/routing.py`, `get_request_handler`: `body = await request.form()`, then
    `solve_dependencies`), so the session check, `upload_rate` and `api_limit` all come after
    the whole file is in memory.
  - `OriginCheck` only compares `Origin` with `Host`, which a non-browser client sets at will;
    `networkAppRanges` defaults to `[]`, every address (`settings.py:251`).
- **What goes wrong:** an anonymous client that reaches `/ui` sends, at once, 100 POSTs of a
  25 MB multipart file to `/ui/api/receipts`, each with `Origin` equal to its `Host` and a
  different random `Cookie: mk_session=<random>`. Each is a different "caller" to `BodyLimit`,
  so none hits the 100 MB cap; each body is parsed into memory (under `spool_max_size`); only
  then does `caller` answer 401. While they arrive the server holds about 2.5 GB, past the
  2 GB DEPLOY gives it: the process is killed, comes back locked (S15.4), and stays down until
  an admin types the phrase. Without a cookie the cap is per address (100 MB), which a few
  addresses defeat too.
- **Run:** yes, `/home/dev/.claude/jobs/b8ac83ff/tmp/u09/upload.py` (output `upload.txt`): an
  anonymous multipart POST of 5 MB to `/ui/api/receipts`, with a random `mk_session` and a
  matching `Origin`, through `create_app`'s whole middleware stack: all 5,242,988 bytes were
  read before the session check ran, then 401. The concurrency and memory figures rest on
  reading.
- **Remedy:** decide who the caller is before reading a body: `BodyLimit` (or a middleware
  before it) looks the session up (a read of `Session` by the token's hash) and counts an
  upload against the user only for a live session; any other upload to `/ui/api` is refused
  401 on its headers, before its body. Also a process-wide ceiling on uploads in flight from
  all callers (a few hundred MB), past which a 503 `Retry-After` answers.
- **Alternatives:** the upload routes take the body as a stream (`request.stream()`) after
  `Depends(caller)` has run, and parse the multipart themselves; or the in-flight cap for an
  unverified session counts by address, with one small shared budget for all of them.

- **Check (unit 09 checker, Oct 25):** confirmed. Severity Med stands (the Req reading: the
  100 MB per-user cap is S13.7.6's own limit, and an unauthenticated caller can pick its own
  key). Read `middleware.py:216-233` (`_caller` hashes the `mk_session` cookie value without
  looking it up) and `:262-270`. Read FastAPI 0.143's `routing.py:436-443`: for a form route
  `body = await request.form()` runs before `solve_dependencies` (`:499`), so `caller`,
  `upload_rate` and the rest run after the file is in memory. `app.py:154-158` sets
  `spool_max_size` to 128 MiB, so a part up to the body limit stays in memory.
  Ran a copy of `upload.py`: an anonymous 5 MB multipart POST with a random cookie was read
  whole (5,242,988 bytes) before the 401. The 100-concurrent-requests, 2.5 GB figure rests on
  reading (not run); DEPLOY.md:18 does give the server 2 GB. No pre-body rate limit or
  address cap by default (`networkAppRanges` defaults to `[]`).

## U09-4 (unit 09): the 20 MB ceiling counts compressed bytes, so a peer, an address in a link code or the explorer can answer with a gzip bomb that decompresses to gigabytes

- **Kind:** security. **Severity:** Med. **Conf:** 0. **Status:** open.
- **Req:** S13.5 ("every answer is cut off past 20 MB, whether or not it announces its
  length"), S11.1 (a link code names an address anyone can type), S15.4 (a restart waits for
  the phrase).
- **Code:** `web/server/src/moolakata/net.py:220-230` (`_Transport.handle_request`):
  ```text
          length = response.headers.get("content-length")
          if length and length.isdigit() and int(length) > self._max:
              ...
          response.stream = _Capped(response.stream, self._max, url.host)
  ```
  `response.stream` is the raw, still-encoded stream; httpx decodes `Content-Encoding` (gzip,
  deflate, and br/zstd when installed) after it, in `iter_bytes()`, with no limit, and its
  default headers ask for gzip. Only `Client.get_bytes` (`:258-267`) counts decoded bytes, and
  only the price sources use it. Everything else reads `.content`, `.json()` or `.text`, which
  decode the whole answer in memory: `links/client.py:102` (`hello`, unsigned, to whatever
  address a link code or a typed address names), `:136, :141, :215, :219` (`call`, decoded
  before the signature is checked), `bitcoin/sources.py:91-99, 323-331` (the explorer, the
  node).
- **What goes wrong:** someone hands a household a link code naming their own server, or a
  linked server turns hostile, or the explorer is compromised. It answers `hello` (or any call)
  with `Content-Encoding: gzip` and 20 MB of compressed zeros: under the ceiling on the wire,
  about 20 GB decoded. `r.json()` decodes it whole; the process is killed for memory and comes
  back locked (S15.4). For the explorer, the wallet read repeats it every few minutes.
- **Run:** yes, `/home/dev/.claude/jobs/b8ac83ff/tmp/u09/bomb.py` (output `bomb.txt`): a local
  server answering a POST with 203,860 bytes of gzip; `net.Client(...).post(...).content` was
  209,715,200 bytes (ceiling 20,971,520), peak RSS 456 MiB. 20 MB on the wire scales that by
  100.
- **Remedy:** `net.Client` sends `Accept-Encoding: identity` and `_Transport` refuses an
  answer with any `Content-Encoding` other than identity (none of the sources needs one); or
  `_Capped` wraps the decoded stream (count after decoding, e.g. by giving `httpx.Response` a
  decoded-size-checking `iter_bytes`), so `.content` raises at 20 MB of decoded bytes. A test
  with a gzip answer over the ceiling, through `.json()`.
- **Alternatives:** read every answer through `get_bytes` (and a POST equivalent), which
  already counts decoded bytes, and forbid `.content`/`.json()` on `net.Client` responses.

- **Check (unit 09 checker, Oct 25):** confirmed. Severity Med stands. Read `net.py:220-230`
  (the length test and `_Capped` wrap `response.stream`, the raw encoded stream) and
  `:258-267` (`get_bytes` counts decoded chunks, the only caller that does). Ran a copy of
  `bomb.py`: 203,860 gzip bytes on the wire came out as 209,715,200 bytes from `.content`
  (ceiling 20,971,520), peak RSS 536 MiB. `net.Client` sets no `Accept-Encoding` of its own, so
  httpx's default (gzip, deflate) is sent. The claim's call sites (`links/client.py`,
  `bitcoin/sources.py`) read `.content` or `.json()`. A reading that S13.5's "cut off past 20 MB"
  means bytes on the wire is possible but the ceiling's purpose is memory, so I did not rate
  it plausible.

## U10-3 (unit 10): copies made after a re-encryption's choices, the run's own first backup among them, are left under the old data key unasked; after a leak they open with the leaked phrase

- **Kind:** security. **Severity:** Med. **Conf:** 0. **Status:** open.
- **Req:** S15.7.2 ("for each the admin chooses **re-encrypt** (the default …), **delete**, or
  **leave**"; "A verified backup is made first, under the old key"), S15.7.1 ("**Then the
  copies on the host** … are each re-encrypted (the default), deleted or left"; "Re-wrapping
  alone would change only which phrase opens the keyring: an old phrase and any copy made
  before would still give the data key that opens every later copy, so a rotation always
  re-encrypts"), S15.8.2.2 ("so the leaked phrase opens nothing made from now on").
- **Code:** `web/server/src/moolakata/store/reencrypt.py:309-316`:
  ```text
      outcomes = dict(steps.get("copies") or {})
      found = copies.copies(config)
      progress.set("copies", 0, len(found))
      for i, c in enumerate(found):
          if c.name in outcomes:
              continue
          choice = j["copies"].get(c.name, "leave")
  ```
  The choices are the copies listed when the run was scheduled (`schedule`, `:89-105`; the
  rotation through the running server, `maintenance.rotate_running:521-531`; Settings,
  `ui/settings.py:841`). The run's own first backup (`:255-268`, `backup(config, st)` under
  the old data key, with the keyring as it then is) and every daily backup made between the
  scheduling and the next unlock (`runtime.py:67-74`, the server still serving under the old
  data key) are not among them, so they take `"leave"`. And `rotate_running:528-530` tells the
  admin `"re-encrypted at the next unlock"` for every copy chosen `reencrypt`, though a copy
  under the old phrase with an earlier data key ends `"left: needs the phrase of …"`
  (`reencrypt._copy:350-353`; `keys rotate` over the socket never sends `oldPhrase`,
  `keys/cli.py:382-385`).
- **What goes wrong:** the household's phrase A leaks (a lost sheet beside the bucket the
  backup directory syncs to, the case S15.8.1 opens with). The admin follows S15.8.2: rotates
  through the running server (`keys rotate`, choosing delete or re-encrypt for each copy,
  `--delete-old` for a script), and plans a restart for the weekend. Until then the daily task
  keeps making backups whose database is under the old data key D1 (keyring wrapped by the new
  phrase B, database keyed from D1); the restart's run then makes one more, its "verified
  backup first", also under D1. None of these was listed, so all are left, and the report says
  "left". The bucket now holds full copies, made *after* the rotation, that the leaked phrase
  A plus any older copy opens (A unwraps D1 from the older copy's keyring; D1 keys these
  databases directly). S15.8.2.3 tells the admin to delete the copies made *before* the
  rotation, so these are kept, and the host's snapshots carry them on.
- **Run:** no; rests on reading (`run` defaults any unlisted copy to `leave`, and the backup
  step runs before the copies step).
- **Remedy:** a copy not in the choices takes the default S15.7.1 and S15.7.2 give
  (re-encrypt) when it is under the data key being replaced, which covers the run's own backup
  and the daily ones; once the run has finished, the first backup is re-encrypted too (it was
  only the safety net). Report "re-encrypted at the next unlock" only for copies the run will
  be able to rewrite, and say "left unless you give the old phrase" for the rest.
- **Alternatives:** stop the daily backup while a rotation's re-encryption is pending (the
  host's own snapshots still capture the live database under D1, so the requirement should
  also say a leak rotation is followed by a restart at once); or delete the first backup once
  the run succeeded and say so.

- **Check (Oct 25, checker for unit 10):** confirmed. Read `reencrypt.run:309-317` and `_copy:335-355`: a copy not in the journal's `copies` takes `"leave"`, and the choices are the copies listed at `schedule` time (`rotate_running:521-531`; `ui/settings.py:841`). After `rotate_running` the server's `Store` holds the new keyring but the same data key, so `maintenance.backup` (daily task, `host.backup`) writes a database under D1 with the keyring wrapped by the new phrase, and the run's own first backup (`:255-268`) is also under D1. A leaked old phrase plus an older copy's keyring gives D1, so these open. S15.7.2 lists the copies "when it is scheduled" and requires the first backup "under the old key", so the first backup staying under D1 is by design; the claim's substance is the backups made between the schedule and the unlock, and S15.7.1's "an old phrase and any copy made before would still give the data key that opens every later copy" and S15.8.2.2 ("opens nothing made from now on") are what they break. The claim's remedy covers both; I keep it as written. `keys rotate` over the socket sends no `oldPhrase` (`keys/cli.py:382-385`), so a copy under the old phrase with an earlier data key ends `left: needs the phrase of ...` while `rotate_running` told the admin "re-encrypted at the next unlock", as written. Severity Med holds (needs the leak case and the window until the restart). Not run; reading only.

## U10-4 (unit 10): the re-encryption a rotation brought can be cancelled in Settings, with no password again, leaving a rotation that only re-wrapped

- **Kind:** security. **Severity:** Med. **Conf:** 0. **Status:** open.
- **Req:** S15.7.1 ("so a rotation always re-encrypts"), S16.13 ("**Re-encrypt at the next
  restart** … schedules the re-encryption for the next unlock …; **Cancel** withdraws one
  scheduled"), S13.7.2 (the password again for key actions), S15.8.2.2.
- **Code:** `web/server/src/moolakata/ui/settings.py:857-863`:
  ```text
  @router.delete("/settings/keys/reencrypt", response_model=KeyStorage)
  def key_reencrypt_cancel(request: Request, c: Caller = Depends(admin)):
      """A scheduled re-encryption not yet begun, cancelled."""
      from ..store import reencrypt

      srv = server(request)
      if not reencrypt.cancel(srv.config):
  ```
  `store/reencrypt.py:108-114` (`cancel` removes any journal whose `steps` are empty, whatever
  its `why`); `web/ui/screens/settings.js:1335-1350` shows **Cancel it** under "A
  re-encryption is scheduled for the next restart, brought by a rotation on the host" whenever
  it hasn't started. Also `ui/settings.py:841` (`reencrypt.schedule(... "settings")`) replaces
  a pending rotation's journal, choices and `why` included, since `schedule` refuses only a
  journal with steps (`reencrypt.py:94-96`).
- **What goes wrong:** after `keys rotate` through the running server, the keyring is wrapped
  under the new phrase B but still holds the old data key D1, and only the journal makes the
  next unlock re-encrypt. Any admin session (no password again: the route has no
  `recent_auth`) presses **Cancel it**, perhaps to avoid the re-encryption's downtime: the
  journal goes, the next unlock re-encrypts nothing, and the rotation has only re-wrapped. The
  old phrase A plus any copy made before (every host snapshot) then opens the live database
  and every copy made afterwards for good, the case S15.7.1 rules out. Activity records a
  `keys.reencrypt-cancelled` with no sign it undid a rotation's re-encryption. Scheduling a
  Settings re-encryption over a pending rotation's likewise drops the rotation's copy choices.
- **Run:** no; rests on reading.
- **Remedy:** `cancel` refuses a journal whose `why` is `rotation` (409, "a rotation's
  re-encryption can't be cancelled"), and the screen shows no Cancel for it; `schedule`
  refuses over any pending journal rather than replacing it; Cancel asks for the password
  again.
- **Alternatives:** keep Cancel for a rotation's journal but turn it into "rotate back"
  (re-wrap under the old phrase, which then needs it), so a cancelled rotation is a rotation
  undone, not half done.

- **Check (Oct 25, checker for unit 10):** confirmed. Read `ui/settings.py:857-863` (`key_reencrypt_cancel`: `Depends(admin)` only, no `recent_auth`; the POST beside it has it), `reencrypt.cancel:108-114` (unlinks any journal with empty `steps`, whatever its `why`) and `reencrypt.schedule:94-96` (replaces a journal that has no steps). `settings.js:1335-1350` shows **Cancel it** for a rotation's journal until it has begun. S16.13 says only "**Cancel** withdraws one scheduled", so the missing password again is a gap against S13.7.2's purpose, not a quoted rule; the loss of the rotation's re-encryption against S15.7.1 ("a rotation always re-encrypts") is plain. `recent_auth` asks for the password only when the last one is over 10 minutes old (`deps.py`), so the remedy's "asks for the password again" is that ordinary 10-minute rule. Severity Med holds (an admin's session, as with Remove's phrase). Not run; reading only.

## U10-21 (unit 10): an admin's session alone deletes every backup but one: *Copies kept* set to 1, then *Back up now*

- **Kind:** security. **Severity:** Med. **Conf:** 0. **Status:** open.
- **Req:** S16.13 ("**Remove**, which asks for the password and the phrase"), S13.7.2 (the
  password again), S16.12 ("the copies kept (14 by default, 1 to 365)"), S14.6 (backup
  pruning); review 2's K23 ("a stolen admin password deletes every backup one call at a time.
  **Remedy:** Remove asks for the phrase").
- **Code:** `web/server/src/moolakata/ui/settings.py:928-930` (Remove's own reason):
  ```text
      """Remove one copy (S15.8 step 4): the password again and the recovery phrase, so an
      admin's session alone deletes no backup (S13.7.2, S16.13). A wrong phrase counts toward
      the sign-in's lockout."""
  ```
  but `settings.py:266` (`_d("backupCopies", "backups", 14, _int(1, 365))`) is an ordinary
  setting: `ui/settings.py:94-103` asks for the password again only for `REAUTH` and `network*`
  keys; `POST /settings/backups/run` (`:1037-1046`) needs nothing more than an admin; and
  `store/maintenance.py:231-236` (`prune`) deletes every backup past `keep` at once, from the
  daily task and from Back up now (`runtime.py:67-74`, `host.py:118-122`).
- **What goes wrong:** whoever holds an admin's session (a browser left signed in, a stolen
  cookie) PATCHes `{"backupCopies": 1}` and posts `/settings/backups/run`: the new backup is
  made and the other thirteen are deleted, with no password and no phrase, the very thing
  Remove's phrase was added to stop. They can first change data (soft deletes are reversible,
  but edits to amounts, payees and tax books are not, without a backup) and then leave only a
  backup made after the change. Only the host's own snapshots, if any, still hold the earlier
  state.
- **Run:** no; rests on reading.
- **Remedy:** lowering `backupCopies` asks for the password again (add it to `REAUTH`) and
  takes effect only for backups made after the change (prune never deletes a backup older
  than the change's time by more than the old count's days), or pruning never deletes more
  than one backup per run.
- **Alternatives:** lowering *Copies kept* below the backups present asks for the phrase, as
  Remove does.

- **Check (Oct 25, checker for unit 10):** confirmed. Read `ui/settings.py:94-103` (`REAUTH` and `network*` only; `backupCopies` is not among them), `settings.py:266` (`_int(1, 365)`), `ui/settings.py:1037-1046` (`backup_now`: `admin` only), `maintenance.prune:231-236` (deletes every backup past `keep` at once) and `runtime.py:67-74`, which prunes at each run, Back up now's included. Remove asks for the phrase (`ui/settings.py:928-946`), the point of review 2's K23. `settings.js` offers both fields (`:1051-1079`). Nothing in S16.12 or S14.6 says lowering the count asks for anything. Severity Med holds (an admin's session; the new backup is made first, so one copy always stays). Not run; reading only.

## U12-1 (unit 12): a report's sign-in address skips the check the sign-in call makes, so a stolen or compromised connector shows owners any page as "Schwab's sign-in"

- **Kind:** security. **Severity:** Med. **Conf:** 0. **Status:** open.
- **Req:** S18.7.1 ("the connector reports the sign-in address, which MoolaKata takes only on
  the driver's own sign-in host and shows with that host"), `connector-protocol.md` §4.3.4
  (refusing another with `address-invalid`), S18.2.4.2 and S18.2.4.4 (what a compromised
  connector, or a stolen volume, can do: post files and read the answers; nothing about the
  owners' passwords). Review 2's K24 point 2, marked done.
- **Code:**
  - `web/server/src/moolakata/connector/manage.py:446-466`: the `sign-in` call checks the host
    and path (`sign_in_allowed`, `SIGN_IN_PAGES = {"schwab": ("api.schwabapi.com",
    "/v1/oauth/authorize")}`).
  - `manage.py:349-350`, in `apply_report`, for every Connection a report names:
    ```text
            address = rep.get("signInAddress")
            c.signInAddress = address if isinstance(address, str) and len(address) < 2000 else None
    ```
    no scheme, host or path check.
  - `web/server/src/moolakata/ui/connector.py:112-113` hands it out as `signInAddress` and
    `signInHost`; `web/ui/components/connections.js:303-305` renders it for a Schwab
    Connection as `<a href=${existing.signInAddress} target="_blank">Open Schwab's sign-in at
    ${existing.signInHost}</a>`, and Profile › Connections offers **Sign in again** whenever
    one is set (`connections.js:87`).
- **What goes wrong:** whoever holds the connector's identity key (a copied volume or backup,
  S18.2.4.4, or a compromised connector) sends a signed report naming every Connection with
  `"state": "needs-sign-in", "signInAddress": "https://api.schwabapi.com.example/v1/oauth/authorize?..."`.
  MoolaKata keeps it; each Schwab owner gets *needs a sign-in* (an alert to them and the
  admins) and a dialog whose link reads "Open Schwab's sign-in at api.schwabapi.com.example";
  the page there collects the owner's Schwab username and password. The `sign-in` call with
  the same address is refused `address-invalid`, so the check K24 added is bypassed by the
  report.
- **Run:** yes, `/home/dev/.claude/jobs/b8ac83ff/tmp/u12/test_u12_unreadable.py` (output
  `test_u12_unreadable.txt`), with the server's fixtures: a paired, confirmed connector's
  report naming `https://evil.example/schwab-login` was kept as the Connection's
  `signInAddress`; the `sign-in` call with the same address got 403 `address-invalid`.
- **Remedy:** `apply_report` runs the same `sign_in_allowed(c.driver, address)` and keeps
  nothing that fails it (or ignores `signInAddress` in reports altogether and takes it only
  from the `sign-in` call); a test that a report's address off the driver's page is dropped.
- **Alternatives:** the browser shows the sign-in link only when its host and path are the
  driver's own (a list in `connections.js`), as a second check.

- **Check (Oct 25, checker for unit 12):** confirmed. Read `manage.py:349-350` (`apply_report` keeps any string under 2,000 characters as `signInAddress`, with no scheme, host or path check) against `:446-466` (`sign_in_allowed` and `sign_in_address` refusing anything but `api.schwabapi.com/v1/oauth/authorize`), `ui/connector.py:100-113` (`signInAddress` and `signInHost` handed out) and `connections.js:87`, `:303-305` (Sign in again, and the link rendered from it). Ran `test_u12_unreadable.py` from a copy: a report naming `https://evil.example/schwab-login` was kept as the Connection's `signInAddress`, and the `sign-in` call with it got 403 `address-invalid`. MoolaKata's CSP (`script-src 'self'`, `middleware.py:20-24`) blocks a `javascript:` address from running as script, so the harm is the link's host, as the claim says. Severity Med holds.

## U12-2 (unit 12): the "Its page" link follows whatever any report says, even one from an address no admin accepted, so a stolen volume's holder can collect the vault's words

- **Kind:** security. **Severity:** Med. **Conf:** 0. **Status:** open.
- **Req:** S18.2.4.4 ("A stolen volume … yields the identity key and the pairing … The vault
  stays closed without the words"), S18.5.1 and S18.5.4 (the locked alert sends admins to
  its page; a report from a new address alerts until accepted), S18.11.1 ("Its address …
  goes in every report, and Settings › Connector links to it"), `connector-protocol.md` §4.2.3.
- **Code:**
  - `web/server/src/moolakata/connector/manage.py:301-304`, `apply_report`, before and
    regardless of the address check that follows at `:305-319`:
    ```text
        row.locked = bool(body.get("locked", True))
        ...
        row.pageAddress = _page(body.get("page"))
    ```
    `_page` (`:384-398`) accepts any `https://host:port`.
  - `web/ui/components/connector.js:77-81`: Settings › Connector shows it as "Its page …
    unlock, pair and lock it there", a link; the locked alert says "unlock it on its page"
    (`alerts.py:276-279`).
- **What goes wrong:** a thief has a copy of the connector's volume (`vault.json` and
  `pairing.json`, S18.2.4.4) and reports with its identity key from their own machine:
  `{"locked": true, "page": "https://connector.griffin-home.example:37374"}`. MoolaKata
  alerts *the connector is locked* and *reports from a new address*, and points Settings ›
  Connector's "Its page" at the thief's host. An admin who goes to unlock it, as the alert
  says, lands on a page that looks like the connector's and types the 12 words: the thief
  now opens the copied vault, every credential and the sealing key. The genuine connector's
  next report puts its own address back, so the link flips between the two and looks normal
  most of the time. S18.2.4.4's "stays closed without the words" holds only until the words
  are typed into a page MoolaKata linked to.
- **Run:** no; rests on reading.
- **Remedy:** take `page` only from a report that comes from the known (accepted) address,
  and keep the last good one otherwise; while a new address waits (`newAddress`), show the
  page link with that warning or not at all.
- **Alternatives:** the page's address is set by an admin in Settings › Connector (pre-filled
  from the first report) rather than taken from every report.

- **Check (Oct 25, checker for unit 12):** confirmed. Read `manage.py:296-352` (`apply_report`): `pageAddress` is taken from every verified report at `:305`, before the new-address branch at `:306-319`, and `_page` (`:384-398`) accepts any `https://host:port`. `ui/connector.py:171` hands it out and `connector.js:77-81` renders it as a link; `alerts.py:268-285` alerts *locked* and the new address, and tells the admin to unlock it on its page. So the link follows whichever address reported last, accepted or not, and an admin who follows the alert types the words into whatever page the link names. It needs the identity key (a copied volume, S18.2.4.4) and an admin who types the words, which the alert's own text invites. Severity Med holds. Not run; reading only.

## U12-14 (unit 12): any caller that reaches `/connector` has a whole upload read into memory before its signature is checked, and picks its own in-flight budget with the key header

- **Kind:** security. **Severity:** Med. **Conf:** 0. **Status:** open.
- **Req:** S13.7.6 (at most 100 MB of uploads in flight per caller, held in memory),
  S13.7.5.4 (`/connector` 60 calls a minute), S16.14 (`/connector` reachable from the private
  ranges by default), S15.4 (a restart waits for the phrase). The `/ui/api` case is U09-1
  (withheld); this is the same pattern on another path, keyed by another header, which
  U09-1's remedy (a session looked up before the body) doesn't reach.
- **Code:**
  - `web/server/src/moolakata/middleware.py:226-228` (`BodyLimit._caller`): a request with an
    `MK-Conn-Key` header is counted against `"key:" + headers[h]`, unverified.
  - `middleware.py:242-249`: any `multipart/` body, `/connector` included, may be the upload
    size (the larger of Settings' two, plus 1 MB).
  - `web/server/src/moolakata/connector/routes.py:61-73`: `_signed` reads the whole body
    (`body = await request.body()`) before `verify_request`, and the call limit
    (`srv.conn_limit.hit(...)`) applies only after a signature verified, to that key; an
    unknown key is answered `not-paired` after its body was read (`:77-85`).
- **What goes wrong:** a device on the LAN (or anywhere, where an admin widened Settings ›
  Network's connector ranges for a laptop away from home, `operations.md` §8) sends, at once,
  100 POSTs to `/connector/v1/report`, each `Content-Type: multipart/form-data` with a 25 MB
  body and its own random `MK-Conn-Key`. Each is a different caller under the 100 MB cap,
  each body is held whole, and only then refused: about 2.5 GB in flight against the 2 GB
  DEPLOY gives the server, which is killed and comes back locked until an admin types the
  phrase. Separately, any signed-in user can read the paired connector's identity key
  (`GET /ui/api/connector`, `ui/connections.py:87-95`) and send 100 MB under its header, so
  the genuine connector's posts get the unsigned 429 `uploads-in-flight`, which U12-6 turns
  into a stall of every post.
- **Run:** no; rests on reading (U09-1's run showed the body read before any check through
  the same middleware stack).
- **Remedy:** for `/connector`, refuse before the body: a call whose `MK-Conn-Key` isn't the
  paired connector's (one indexed read) is answered `not-paired` on its headers, unsigned, as
  the link protocol does for a large body from an unknown key; count the in-flight budget
  only for the paired key, and keep a process-wide ceiling on uploads in flight.
- **Alternatives:** `/connector` takes multipart only on `…/files` and refuses a body over
  1 MB on any other path on its headers.

- **Check (Oct 25, checker for unit 12):** confirmed. Read `middleware.py:211-231` (`_caller` keys an upload by the unverified `MK-Conn-Key` header), `:240-262` (any `multipart/` body may be the upload cap, the larger of the two limits plus 1 MB, `app.py:111-118`; a caller past 100 MB is answered 429 unsigned), and `connector/routes.py:59-85` (`_signed` awaits the whole body before `verify_request`, and `verified` answers an unknown key `not-paired` after that). `GET /ui/api/connector` is open to any signed-in user and returns `identityKey` (`ui/connections.py:75-95, 98`), so a user can send the genuine key as the header. The 100-callers case needs `/connector` reachable from the attacker's address (the private ranges by default, S16.14). Severity Med holds. Not run; reading only.

## U05-40 (unit 05, claim added after assembly): a budget keeps counting, and naming, an account whose share was removed

*From calibration run C's U05-1 (D52 in `model-experiment.md`), checked by the comparison and again
by the unit 05 checker.*

- **Kind:** privacy. **Severity:** Med. **Req:** R3.4 ("Revoking it ends access on the next
  request"), S7.1.1, S10.3.
- **Code:** `web/server/src/moolakata/budgets/__init__.py:55-65`, the owner's view takes every
  account the budget was given, with no check that the owner can still see it:
  ```text
  rows = s.scalars(
      select(Account)
      .join(BudgetAccount, BudgetAccount.accountId == Account.id)
      .where(
          BudgetAccount.budgetId == budget.id,
          BudgetAccount.deleted == false(),
          Account.type.not_in(TYPES),
      )
  ).all()
  if viewer is None or viewer == budget.ownerId:
      return [a.id for a in rows]
  ```
  Access is checked only when accounts are chosen (`ui/budgets.py:_check`, `:429-442`:
  `mine = {a.id for a, _ in access.visible_accounts(s, user_id)}`); a grep of `BudgetAccount`
  finds no writer that removes a row when an account's share ends (`ui/budgets.py:454-475` are the
  choose-accounts route, `seed_budgets.py` the dev seed). `budget_recurring` names every account for
  the owner (`ui/budgets.py:1644`: `reach = access.reach(s, c.id) if c.id != b.ownerId else None`),
  and `alerts.cash_short` (`alerts.py:546`) reads `account_ids(s, b, u.id)` the same way.
- **What goes wrong:** Bob shares *Bob Checking* with Alice; she adds it to her budget; Bob
  removes the share (Alice's `GET /accounts/{id}` is now 404). Bob's later spending still counts in
  Alice's month (Food actual $42), her recurring list shows *Secret Clinic, Bob Checking, −$42.00*,
  the budget lists the account's id, its balance feeds an envelope budget's To Budget and *Where the
  money is*, and the cash-before-payday alert names it and its dips to her. Her receivers see the
  same figures from the owner's own accounts. R3.4 says revoking ends access on the next request.
- **Run:** yes, calibration run C's `test_unshared_account_still_counted` (reran by the checker):
  `ACTUAL 42.00`, `RECURRING [('Secret Clinic', 'Bob Checking', -42.00)]`, `BUDGET ACCOUNTS`
  holding Bob's account id.
- **Remedy:** `account_ids` keeps, for every viewer the owner included, only accounts the owner
  can still see (`access.account_level(s, budget.ownerId, a)`), and the receiver rule on top; a
  test that removes a share.
- **Alternatives:** when a share ends, mark the account's `BudgetAccount` rows deleted in every
  budget of the user who lost it (and say so in Activity).

**Check (unit 05 checker, Sonnet 5.5, Oct 25):** confirmed. Read `account_ids` (`budgets/__init__.py:47-71`), `_check`, and
the places `BudgetAccount` is written: nothing follows a revoked share. Reran C's test: the account's
transactions, payee and name still reach Alice after the share is removed. It contradicts R3.4's
*revoking ends access on the next request*, with another user's payees and amounts, so Med stands
(an owner is a user the other person trusted once, which is why it is not High).

## U05-21 part 2 (unit 05, a published claim the checker rates Med): the checker's reasoning

The coordinator moves the claim's details here (docs/REVIEW.md §2); this is the checker's own
reasoning for the rating, kept beside it.

- **What was read:** `reserves.held_in` (`budgets/reserves.py:129-226`) takes the held-in account
  from the plan line's `heldInId` (`:143-148`) and reads it by id (`:152`), its transactions
  (`:157-164`) and balance (`:209`), with no check against the viewer's accounts (`accts` is the
  viewer-filtered list, but `by_account` is keyed by `ln.heldInId`); `where` (`ui/budgets.py:1090-1157`)
  labels it `an account not shared` and still sends `balance`, `withdrawals`, `unassigned` (each
  deposit's date, payee, amount) and `transfers`. `review` (`:1481-1489`) uses `held_in` the same way
  for *to move*.
- **Ran:** calibration run B's `test_e12.py` (reran): Carol shares her savings with Alice at read,
  Alice's budget counts it and holds a reserve there, and shares the budget with Bob; Bob's
  `GET /budgets/{id}/where` answers `accountName: "an account not shared"`, `balance: 12422.00`,
  `unassigned: [("Carol private payee", 77.00)]`; a scenario Bob copies shows the same.
- **Rating:** the arrangement is narrow (a third person's account, shared only with the owner, held
  in by a reserve of a budget shared on), as A and C said, but what leaks is the balance and the
  deposits' payees and amounts of an account whose owner never shared it with the viewer, across the
  line R3.4 and S7.1.1 draw, and the code's own `account_ids(viewer)` filter shows the line was meant
  to hold. So Med, and by §2 withheld. Parts 1 and 3 of U05-21 (the review's two figures, a card's
  name) stay Low and need no withholding.
- **Remedy:** as B's: `held_in` takes the viewer and leaves out, or reports only totals for, a
  held-in account the viewer can't see (`access.account_level`); U05-30 (the copy keeps `heldInId`)
  is the same fix's other end.


## U05-21 part 2: the published text before it was moved here (Oct 25)

### U05-21: a budget's receiver sees figures of an account shared with its owner but not with them, through the review and *Where the money is*

- **Kind:** privacy. **Req:** S7.1.1 ("Its receivers see the figures from the owner's own
  accounts, and from an account shared with the owner only if that account is shared with them
  too, so a budget never passes on an account someone else shared (R3.4)").
- **Code:**
  1. `web/server/src/moolakata/ui/budgets.py:1524` stores a review's figures as the reviewer
     sees them (`_figures(budgets.month_view(s, b, m, clock.today(), c.id))`), and `_reviewed`
     (`:1460-1466`) compares them with the viewer's own, writing both into the text:
     `f"{label}: spent {a[1]} then, {b[1]} now"` (`:1434`).
  2. `budgets/reserves.py:143-148, 157-164, 209` takes the held-in account from the plan line
     (`ln.heldInId`), whoever views, and reads all its transactions and its balance; `where`
     (`ui/budgets.py:1104-1137`) returns them, the account named *an account not shared* but its
     balance, transfers (payees, amounts) and landed money shown.
  3. `_moves_out` (`ui/budgets.py:888`) names a card move by any credit card on the server.
- **What goes wrong:** case: Carol shares her card with Alice (read); Alice's household budget
  counts it and is shared with Bob at write; the card is not shared with Bob. Alice marks
  October reviewed. Bob opens the review: *changed since reviewed: Dining: spent 812.40 then,
  355.10 now*, the $457.30 being Carol's card, which Bob can't see anywhere else; the flag also
  never clears for him, since his figures never match Alice's. Likewise, a reserve held in an
  account Carol shared with Alice shows Bob that account's balance and transfers.
- **Run:** no, reading alone. Low: one household's members, a narrow arrangement (an account
  shared to the owner by a third person, inside a shared budget).
- **Remedy:** keep a review's figures per viewer's reach, or store only the owner-view and
  compare each viewer against figures worked out from the accounts they share; leave out of
  *Where the money is* any held-in account the viewer can't see (its reserves listed with
  *held in an account not shared*); name cards from the viewer's accounts.
- **Alternatives:** S7.14 says a review compares figures per user, each marking it for
  themselves.

- **Check:** corrected. **Severity now:** Med (part 2 only; parts 1 and 3 stay Low). **Withhold:**
  yes (part 2). Split in two: (a) parts 1 and 3, the review's stored figures and a card's name,
  Low as written; (b) part 2, the *Where the money is* rows. Read `reserves.held_in` and `where`;
  my full reasoning for (b) is in `withheld.md`.



## U10-F1 (found while checking unit 10; moved here by the coordinator, Oct 25)

### U10-F1: `keys init` run with `docker compose run` shows the recovery sheet on `/dev/tty`, which Docker's log keeps for a container with a tty

- **Kind:** security. **Severity:** Low. **Req:** S15.4.4 ("shows the phrase on the terminal, never on
  standard output, so that no log keeps it"), S15.1.7 (the logs hold no secrets), review 2's K10;
  `docs/operations.md:101-103` ("never in Docker's logs").
- **Code:** `web/server/src/moolakata/keys/cli.py:41-62`:
  ```text
  class Terminal:
      """The controlling terminal, for a recovery sheet and the words typed back: never
      standard output, which Docker's logs keep (S15.4.4). A command that shows a sheet
      refuses to run without one."""
  ```
  with `say` and `ask` writing to the file `open_tty()` opened.
- **What goes wrong:** a container started with a tty (`docker compose run --rm moolakata keys
  init`, the documented way) has one pseudo-terminal, and the daemon's log driver reads
  everything written to it, `/dev/tty` included. A throwaway container run with `docker run -t`
  and `echo X > /dev/tty` showed `X` in `docker logs`. So the sheet and the three words typed
  back go to the container's log, kept past the command where the log driver is journald,
  syslog or a shipper (with the default driver and `--rm` the log goes with the container).
  `Terminal` keeps the sheet off standard output, which does not keep it out of the log.
  `keys rotate` is run with `compose exec` (`operations.md:280`), whose output the daemon does
  not log (not tested).
- **Run:** a throwaway container only (`docker run -t`, `/dev/tty` write, `docker logs`); the
  command itself was not run.
- **Remedy:** say in S15.4.4 and `operations.md` that `keys init` is run with `docker compose
  exec` against a started server, or with a log driver that keeps nothing; or write the sheet
  where no log reads it (the host's terminal, a file only the admin reads).
- **Alternatives:** none simpler that keeps `run --rm`.


- **Check (sweep, Oct 25):** confirmed. **Severity now:** Low, kept withheld (I am not sure
  that publishing it tells no one how to attack a server). Read `keys/cli.py:36-62` (`open_tty`
  opens `/dev/tty`; `Terminal.say` and `ask` write and read it) and `docs/operations.md:99-103,
  280-286`. Ran a throwaway container (`docker run -t --network none --entrypoint sh <local
  image> -c 'echo X > /dev/tty'`, then `docker logs`): `X` was in the log; without `-t` there is
  no `/dev/tty` at all (the command would refuse to run, `cli.py:51-56`). So the claim holds,
  and also covers `keys rotate` run against a stopped server (`operations.md:280-283`, which
  shows the new phrase on the same terminal) and the words typed back where the terminal echoes.
  What limits it: every shipped compose file pins `logging: driver: json-file`
  (`web/install/compose.yaml:34-35` and the others), which `docker compose run --rm` applies to
  its container too, and `--rm` deletes the container's log file when the command ends; so the
  sheet sits in a root-owned file for the command's length and is removed with the container
  (not scrubbed), unless a log shipper on the host reads those files (a common setup) or the
  command is run without `--rm`. `keys rotate` with `exec` is not logged by the daemon (not
  tested). Low stands: a stated property, "so that no log keeps it", is false under a shipper
  or another driver, and the fix is cheap (run with `exec`, or write the sheet where no log
  reads it).

## U08-F1 (found while checking unit 08; moved here by the sweep, Oct 25)

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

- **Check (sweep, Oct 25):** confirmed. **Severity now:** Med (checker's Low raised). The same
  class as U09-1 and U12-14 (both Med, above), on the link listener, which is the one meant to
  face the internet. Read `links/routes.py:35-81, 158-165`: `join` awaits `request.body()` and
  only then calls `signing.verify_request`; the per-address limit (`limit`, 60 a minute,
  `routes.py:19-30`) runs on the call's start, before the body is read, and `LINK_LIMIT` in
  `middleware.py:38, 243-247` makes 20 MB the ceiling for every `/link` path, with no
  in-flight budget (`upload` is false for `LINK_LIMIT`, `:258`). So one address can have 60
  bodies of up to 20 MB open at once (1.2 GB) by sending them slowly, and each is held whole.
  More than the item says: `body_of` (`routes.py:58-68`) reads `Content-Length` and treats an
  absent one as 0, so a **chunked** body to any route that uses it, from a key with no link,
  skips the 1 MB refusal and is read whole up to 20 MB before `verify_request`.
  Ran `tmp/check/sweep/test_f3.py` (through `create_app`'s whole stack, a spy on
  `signing.verify_request`): a 3 MB body to `/link/v1/join` reached `verify_request` whole; a
  3 MB body with a `Content-Length` to `/link/v1/deliver` from an unknown key was refused
  `not-linked` on its headers (no read); the same 3 MB sent chunked reached `verify_request`
  whole (answered `unsigned`). The 1.2 GB figure rests on reading.
  Remedy as the item's, and in `body_of` and `join` count the bytes as they arrive (refuse
  past 1 MB for a key with no link, whatever the headers say), with a process-wide ceiling on
  `/link` bodies in flight, as U09-1's remedy gives.

