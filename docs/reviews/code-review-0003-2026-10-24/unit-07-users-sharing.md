# Code review 3, unit 07: users-sharing

**Session:** Oct 24, 09:28 PM to 09:43 PM (Chicago). **Commit read:** `6916954`. **Scope:** full.
**Checking:** quick (no §8 checker; every claim at 0 confirmations, status open).

## Brief (docs/REVIEW.md §7)

### 1. Sections, code and tests (map.md)

- **Sections:** S10 (users S10.1: the user and its limits S10.1.1, the first admin S10.1.2,
  invitations S10.1.3, sign-up S10.1.4, reset and email change S10.1.5, two-step and recovery
  codes S10.1.6, deactivation S10.1.7, admins S10.1.8, emails S10.1.9; what admins are trusted
  with S10.2; sharing S10.3 and its levels and linked users S10.3.3; the Share dialog S10.4;
  groups S10.5; shared marks and filters S10.6; Count in my totals S10.7; Activity S10.8; access
  tokens and MCP S10.9; people, relationships and the family tree S10.10), with the README's
  R1.6, R1.7, R1.8, R2.9, R3.4 and the S13 items this code cites (S13.7.1 sessions, S13.7.2
  re-authentication, S13.7.3 passwords, S13.7.4 Origin, S13.7.5 rate limits and lockouts,
  S13.7.9 logs).
- **Code (9,468 lines, 45 files):** `src/access.py`, `activity.py`, `auth/{__init__,passwords,
  sessions,signup,tokens,twostep,users}.py`, `mail.py`, `mcp.py`, `people/{__init__,tree}.py`,
  `ratelimit.py`, `sharing.py`, `tokens.py`, `store/entities/{sharing,users}.py`,
  `store/tables/{activity,people,sharing,users}.py`, `ui/{activity,people,profile,session,
  sharing,tokens,users,welcome}.py`; `ui/components/{auth,reauth,share,tokens}.js`,
  `ui/screens/{activity,confirm-email,new-server,profile,reset,setup,signin,signup-confirm,
  users,welcome}.js`, `ui/store/session.js`.
- **Tests (2,372 lines):** `test_mail.py`, `test_mcp.py`, `test_people.py`, `test_sharing.py`,
  `test_tokens.py`, `test_twostep.py`, `test_users.py`, `test_welcome.py`.
- **Guides:** `signin.md`, `signup*.md`, `reset.md`, `confirm-email.md`, `setup.md`,
  `welcome.md`, `new-server.md`, `users.md`, `profile.md`, `activity.md`,
  `settings-signup.md`, `settings-passwords.md`, `settings-sessions.md`, and the dialogs
  `dialog-{two-step,recovery-codes,new-user,edit-user,new-token,token-shown,share,person,
  relationship,group,written-email}.md`.
- **Cites no section** (judged when read): `ui/components/auth.js`.

### 2. Delta since review 2 (`294792b`..`6916954`)

Content changed: 1,235 lines (13%); 2 new files (`ui/welcome.py` 122, `ui/screens/new-server.js`
107) and `tests/test_welcome.py` (220). Changed most: `mail.py` (+192/−34, the email queue,
K15), `ui/session.py` (+109/−36, sign-in, two-step, K16/K17), `people/__init__.py` (+108/−15,
P5, C42 spouse confirmation), `auth/users.py` (+84/−51), `ui/activity.py` (+84/−8, P8),
`ui/people.py` (+72), `ratelimit.py` (+53/−5, /64 and the guard), `profile.js` (+48/−6),
`tokens.py` (+38/−2, K7), `mcp.py` (+33/−6, B32), `setup.js` (+26/−12), `ui/sharing.py`
(+23/−1, K14), `ui/profile.py` (+18/−9), `ui/users.py` (+17/−6, K14), `session.js` (+16/−2),
`sharing.py` (+13/−1), `store/tables/users.py` (+11), `auth/signup.py` (+9/−6, K17). Tests:
`test_mail.py` (+152), `test_users.py` (+117), `test_twostep.py` (+50), `test_people.py`
(+46), `test_tokens.py` (+37), `test_sharing.py` (+27). The rest is the rename. Read first:
the welcome (new), the email queue, the sign-in and two-step paths, the rate limiter, tokens.

### 3. Earlier reviews' findings in this area

Review 2 (§12.2 marks each done unless said):

| Finding | What | State per review 2 | To re-check |
|---|---|---|---|
| K7 | token making needs re-auth; a password change or reset revokes tokens; token creation emailed | done (m8 part 1) | `ui/tokens.py`, `tokens.py`, `auth/users.py` |
| K8 | admins trusted (decision 3); opening a written email recorded for its addressee | done, decided way | `ui/settings.py` open-email route (unit 10's file; the Activity entry here) |
| K14 | re-auth on making an admin (PATCH/POST users, approving), linked sharing, Include receipts | done | `ui/users.py`, `ui/sharing.py` |
| K15, A12 | emails queued in the database, removed when sent or expired; refused keeps recipient, subject, error | done (m9 part 2) | `mail.py` |
| K16 | pending two-step token voided after 5 wrong codes; /64; one guess per token at a time; slowdown before counting | done (m9 part 1) | `auth/twostep.py`, `ui/session.py`, `ratelimit.py` |
| K17 | reactivation, re-auth and current-password behind the sign-in guard; reactivation answers the same; sign-up hashes first | done (m9 part 1) | `auth/users.py`, `ui/session.py`, `auth/signup.py` |
| K19 | engines hide parameters; refusals logged with id; peer messages | done (m9 part 1) | this unit: what the sign-in paths log |
| P1, C42 | spouse needs both confirmations | done | `people/__init__.py`, `ui/people.py` |
| P5, C21 | a remote user gets its own person; joined only on a local confirmation; a person who is a user changed only by them and admins | done | `people/__init__.py` |
| P8 | Activity: every kind's receivers see entries; a removed receiver keeps its entry | done | `ui/activity.py` |
| B32 | MCP `limit` checked 1–500; inputs checked against schemas; instructions | done | `mcp.py` |
| N12 | recovery-code sign-in email; new-address email with two-step; Activity for opening a written email | done | `ui/session.py`, `mail.py` |
| C9 | an email's link life: a day, an invitation's a week | done | `mail.py`, `auth/users.py` |
| C35 | S10.1.1 refers to S13.7.3 for password rules | done | `auth/passwords.py` |
| C37 | reset requests counted, not failures; recovery-code email | done | `ui/session.py`, `ratelimit.py` |
| C52 | share request alerts the creator and the admins | done | `ui/people.py` |
| A1–A6 | usernames, link lifetimes, reactivation, sessions, password max, counters in memory | confirmed (Q19) | `auth/users.py`, `passwords.py`, `ratelimit.py` |

Review 1: F5 (default admin password, now the welcome), F6 (mail folder tokens), F8 (re-auth
list): done, and superseded by review 2's K8, K14, K15. Review 1's §"other" item 10 (S13.7.5.1
locks the username): now "only slowed, never locked".

### 4. Phase 1 claims and decisions on S10

- **DC-10** (Low): remote usernames ≤ 64 and display names ≤ 120 (`link-protocol.md` §4.2)
  against S10.1.1's 32 and 80 on the same `User` rows: judge what the `User` checks enforce.
- **DC-17** (Low): R1.7's **read/write** against R2.9 and S10's `write`: check the enum.
- **DC-22** (Low): S10.6's **From linked servers** filter against S12.10.5 and rejected idea 7:
  judge what the code offers.
- **D2-14** (Low): an admin's reset of another user's two-step, and accepting the connector's
  new address, against S13.7.2's list: judge whether the reset route asks for the password.
- **D2-17** (Low): the unlock's lockout figures while Settings can't be read: judge what
  the code uses.
- **D2-18** (Low): the welcome holds every phrase it shows with no bound: judge `ui/welcome.py`.
- **D2-11** (Low, unit 09's mainly): what Profile holds; noted where `profile.js` is read.
- **D3-23** (Low): `/mcp`'s snake_case arguments; noted where `mcp.py` is read.
- **D3-19** (Low): `schema.md`'s `Share` narrower than R2.9; noted where the sharing tables are read.
- **D1-25** (Med, needs the user; U04-14 judged it): S10.3's tax-book row; nothing new here.
- None is decided yet; open questions are judged against both readings.

### 5. Untraced candidates and uncited first-level items

- Untraced candidate: `ui/components/auth.js`.
- Uncited first-level item: **S10.5** (groups): built under other words, scheduled, or not
  built.

## Claims

### U07-1: withheld

- **Kind:** security. **Severity:** Med. Withheld (`withheld.md`, REVIEW.md §2).

### U07-2: a sign-in from a new address after a month with no sign-ins sends no notice

- **Kind:** security. **Req:** S10.1.9 ("a sign-in from an address the user hasn't signed in
  from in 30 days (once they have signed in from somewhere; the addresses seen are kept on the
  user for those 30 days …)").
- **Code:** `web/server/src/moolakata/ui/session.py:352-358` (`_note_address`):
  ```text
      seen = {
          k: v
          for k, v in seen.items()
          if t - dt.datetime.fromisoformat(v) < dt.timedelta(days=ADDRESS_DAYS)
      }
      new = bool(seen) and address not in seen
  ```
  "Once they have signed in from somewhere" is read as "from somewhere in the last 30 days":
  the addresses older than 30 days are dropped first, so after a quiet month `seen` is empty and
  no sign-in is new.
- **What goes wrong:** Gil signs in on Sep 1 and not again. On Oct 2 someone with his password
  signs in from 203.0.113.9: no email, and only an Activity entry of an ordinary sign-in (no
  `signin.new-address`). The users least likely to notice a stranger in their account, those
  who sign in rarely, are the ones the notice never reaches. The same holds the first time
  after an invitation is accepted, as `invitation_accept` records no address
  (`ui/session.py:504-514`), which matches the "first sign-in" reading.
- **Run:** yes, `tmp/u07/t/test_u07.py::test_new_address_after_a_quiet_month_is_not_emailed`
  (clock moved 31 days; the sign-in from 203.0.113.9 writes no email).
- **Remedy:** decide "has signed in before" from `lastSignInAt` (or any session ever), not from
  the pruned list: `new = (user.lastSignInAt is not None) and address not in seen`, taken before
  `lastSignInAt` is set in `_signed_in`; a test of the quiet month.
- **Alternatives:** keep the last address past the 30 days, so the list is never emptied.

### U07-3: password-reset requests never lock the address; the throttle allows 30, shared with six other routes

- **Kind:** differs. **Req:** S13.7.5.1 ("10 failures in 15 minutes lock **the address they
  came from** for 15 minutes, whoever they named, and so do 10 password-reset requests").
- **Code:** `web/server/src/moolakata/app.py:59-60`:
  ```text
      # Password resets, re-authentications, reactivations: 30 in 15 minutes per address.
      password_asks: ratelimit.Window = field(default_factory=lambda: ratelimit.Window(30, 15 * 60))
  ```
  and `ui/session.py:431-437`, `password_reset` calls only `_throttle(request)` (that window);
  nothing calls `srv.sign_in.failed` for a reset request. The same window is hit by re-auth,
  sign-up, sign-up confirm, invitation lookup and accept, email-change confirm, reactivation and
  the welcome's admin step (`ui/session.py:416, 444, 463, 480, 494, 507, 520, 531`,
  `ui/welcome.py:117`).
- **What goes wrong:** from one address, 12 reset requests in a row all answer 204, and a
  sign-in from that address right after succeeds: the address is neither locked for 15 minutes
  after the 10th nor kept from signing in. Up to 30 reset emails per address per 15 minutes can
  be sent at a user (each ending the one before, S10.1.5), and the window slides rather than
  locking for a fixed 15 minutes. Review 2's C37 said S13.7.5.1 counts reset requests, not
  failures; the figure and the lock are still not built.
- **Run:** yes, `tmp/u07/t/test_u07.py::test_ten_reset_requests_do_not_lock_the_address`.
- **Remedy:** count each reset request in `SignInGuard` as a failure of the address (with the
  Settings figures), so the 10th locks the address for sign-in and resets alike; keep the 30
  window for the other token routes or give them their own.
- **Alternatives:** S13.7.5.1 says what the code does (30 a quarter hour per address, shared,
  no lock), if the spam bound is thought enough.

### U07-4: withheld

- **Kind:** security. **Severity:** Med. Withheld (`withheld.md`, REVIEW.md §2).

### U07-5: *Share these accounts too* shares to each person of the moment: a group's members keep the accounts after leaving it, and a linked server's user gets them without the password again

- **Kind:** privacy. **Req:** S5.1.2 ("offers **Share these accounts too** (at read, and only
  for accounts the owner may share)"), S10.5 (a member holds a group's shares "while they are in
  the group"), S13.7.2 (sharing with a linked server needs the password again).
- **Code:** `web/server/src/moolakata/sharing.py:235-243`:
  ```text
  def _share_accounts_too(s: Session, by: User, p: Portfolio) -> int:
      """Share these accounts too (S5.1.2): at read, only accounts the owner may share."""
      n = 0
      people = [u for u in access.holders(s, "portfolio", p.id, p.ownerId) if u != p.ownerId]
      for uid, missing in hidden_accounts(s, p, people).items():
  ```
  `holders` expands a group share into its current members, and each missing account is shared
  with `userId=uid` (`:244-253`), never with the group. The re-auth check
  (`ui/sharing.py:215-219`) looks only at linked users newly in `body.users` and at Include
  receipts:
  ```text
      for uid, lvl in body.users.items():
          if uid in linked and lvl != "none" and uid not in current:
              return True
  ```
  so a linked user who already held the portfolio gets the accounts with no password asked.
  The dialog names such a person from `view.users` only (`ui/components/share.js:62-63`), which
  holds no linked users, so the warning reads "can't see …" with no name.
- **What goes wrong:** (1) Alice shares her portfolio *Family* with the group Family at read and
  presses **Share these accounts too**: Carol, Dan and Eve each get a direct read share of
  Alice's brokerage account. When Carol leaves the group, she loses the portfolio but keeps
  the account, and Frank, who joins later, sees the portfolio without it. (2) Alice shared the
  portfolio with Bob on a linked server an hour ago; now she presses the button: her accounts
  cross to Bob's server at the next exchange, with no password asked, under a warning that
  names nobody.
- **Run:** no, reading alone.
- **Remedy:** share each missing account with the same grantee the portfolio has (the group, or
  the user), and run `_reaches_a_link`'s check on the accounts the button would add (linked
  holders among the people); name linked people in the warning from `view.links`.
- **Alternatives:** leave group shares out of the button and say so in the dialog.

### U07-6: the family tree drops in-laws, step-parents and stepchildren when a spouse dies

- **Kind:** differs. **Req:** S10.10.5 (the table: in-laws "through a spouse, or a child's
  spouse"; "ex-wife, ex-husband | a marriage ended by divorce; the in-laws through it end with
  it"; "wife, husband, widow, widower | *spouse*, ended by death for the last two").
- **Code:** `web/server/src/moolakata/people/tree.py:83-92` puts a marriage ended by death into
  `widowed`, not `spouses`, and every step and in-law relation reads `spouses` only
  (`:167-190`):
  ```text
          for sp in self._sp(ego):
              for p in self._p(sp):
                  put(p, 5, "parent-in-law")
  ```
  `_joined` (`:227-236`) walks `spouses` too, so the dead spouse's family isn't even a
  *relative*.
- **What goes wrong:** Ann married Bob in 2000; Bob died in 2020; Mae is Bob's mother and Kid
  Bob's son by an earlier marriage. On 2019-01-01 Ann's relations are Bob (husband), Kid
  (stepson), Mae (mother-in-law). On 2021-01-01 they are Bob (husband) alone: Mae and Kid are
  gone, and Kid's stepmother Ann is gone from his. The table ends in-laws only for a divorce;
  a widow keeps her mother-in-law. Gift plans show the relation (S10.10.6), so Mae's plan
  stops saying who she is to Ann.
- **Run:** yes, `tmp/u07/s/tree_widow.py` (output in `run2.txt`).
- **Remedy:** treat `widowed` like `spouses` for step and in-law relations (and in `_joined`),
  keeping `exes` out, as the table says.
- **Alternatives:** if a death is meant to end them too, the table says so beside the divorce
  row.

### U07-7: an admin's rename in Users leaves the user's person, and so gifts and the family tree, under the old name

- **Kind:** differs. **Req:** S10.10.1 ("a user's display name and birthday are their
  person's").
- **Code:** `web/server/src/moolakata/auth/users.py:672-675` (`update_user`, for PATCH
  `/users/{id}`):
  ```text
      if display_name is not None and display_name.strip() != user.displayName:
          _raise(_name_problems(display_name))
          user.displayName = display_name.strip()
          fields.append("displayName")
  ```
  The person is not touched, unlike Profile and setup, which go through `people.change`
  (`ui/profile.py:193`, `auth/users.py:219-221`). Nor is the new name checked against the other
  people (S10.10.3).
- **What goes wrong:** an admin corrects "Eve Shaw" to "Eve Wong" in Edit user. Users, the
  Share dialog and Activity say Eve Wong; the household's people, gift plans and the family
  tree still say Eve Shaw, and a new person "Eve Wong" can be added beside her. The two only
  meet again if Eve saves her Profile.
- **Run:** no, reading alone.
- **Remedy:** rename through `people.change(s, people.of_user(s, user.id), {"name": …})`, with
  the one-person check.

### U07-8: an admin, or a person's own user, opens the Share dialog of a private person and is refused at Save

- **Kind:** bug. **Req:** S10.10.2 ("Its creator may make it **private**, and then share it as
  any item").
- **Code:** `web/server/src/moolakata/ui/sharing.py:190-193` lets whoever may change a person
  open and save its sharing:
  ```text
      if kind == "person":  # a private person: whoever may change them shares them (S10.10.2)
          from .. import people

          lvl = people.level(s, c.id, obj)
  ```
  (`people.level` is `owner` for every admin and for the person's own user,
  `people/__init__.py:143-150`), while `sharing.save` lets only the creator
  (`sharing.py:105-111`):
  ```text
      if obj.ownerId == by.id:
          return True
      if kind == "tax-book":
  ```
- **What goes wrong:** an admin opens Share on Alice's private person *Ruth*: the dialog lists
  everyone; **Save** answers 403 "Only the owner changes who this is shared with." The two
  routes disagree on who may share a person.
- **Run:** no, reading alone.
- **Remedy:** one rule in both places; S10.10.2 names the creator, so `_owner_only` asks
  `obj.ownerId == c.id` for a person.

### U07-9: re-authentication as the first request after a change of privilege answers 500

- **Kind:** bug. **Req:** S13.7.1 (a new token at every change of privilege), S13.7.2.
- **Code:** `web/server/src/moolakata/ui/session.py:418-423` (`reauth`) reads the session again
  by the cookie the request came with:
  ```text
      with srv.db.tx() as s:
          user = s.get(User, c.id)
          right = passwords.verify(user.passwordHash, body.password)
          if right:
              row = sessions.find(s, request.cookies.get(sessions.COOKIE)).session
              row.authAt = sessions.now()
  ```
  but `_resolve` (`ui/deps.py:62-67`) has just rotated that token when the user's admin flag or
  setup state changed, deleting the old row and giving the caller the new one (`c.session`).
- **What goes wrong:** an admin adds Bob to Admins. Bob's open tab, idle past 10 minutes, asks
  for his password before making a token (the dialog posts `/session/reauth` first when it
  already knows it must, as Edit user's two-step reset does, `screens/users.js:295`). That
  request rotates his token, then `sessions.find(old)` is `None` and `.session` raises
  `AttributeError`: a 500, his password right. The next try works.
- **Run:** no, reading alone.
- **Remedy:** `row = s.get(Session, c.session.tokenHash)` (the rotated row).

### U07-10: sign-up tells anyone whether a username exists

- **Kind:** security. **Req:** S10.1.4.1 (sign-up's answer "is the same … whether or not the
  address already has an account"), S13.7.5.1 (sign-in and reset hide whether a user exists).
- **Code:** `web/server/src/moolakata/auth/signup.py:75-77`:
  ```text
      errors = _name_problems(display_name) + _username_problems(s, username)
      if not username_errors(errors) and _waiting_for(s, SignupRequest.username, username):
          errors.append(FieldError("username", "username-taken", "That username is taken."))
  ```
  with `_username_problems` answering `username-taken` for any existing user
  (`auth/users.py:263-264`).
- **What goes wrong:** with sign-up on, anyone posts `/ui/api/signup` with `username: "dad"` and
  a bad email: a 422 `username-taken` says the account exists, `email-invalid` alone says it
  doesn't. Usernames are what sign-in and reset take, and the sign-in screen and the reset
  answer are built to keep this unsaid. Low: usernames are not secrets in S10.1.1, and
  `admin` is fixed; sign-up is off by default.
- **Run:** no, reading alone.
- **Remedy:** check the username's uniqueness at approval only (it already does,
  `signup.py:177-185`) and answer a taken one like a taken email; or require the email to be
  confirmed before the username is checked.
- **Alternatives:** S10.1.4.1 says usernames are not hidden.

### U07-11: a sign-up request keeps the person's password hash for good

- **Kind:** security. **Req:** S10.1.4.2 ("The request stays as the record of it"), R1.13 /
  S14.4 (what is kept), S13.7.3.
- **Code:** `web/server/src/moolakata/store/tables/users.py:168`
  (`Column("passwordHash", Text, nullable=False)` on `SignupRequest`); `auth/signup.py:209`
  sets the decision and copies the hash to the user (`:200`) but never clears the request's,
  and `reject` (`:234-236`) keeps it too.
- **What goes wrong:** a rejected person's argon2 hash stays in the database (and every backup)
  for ever; an approved user's first password stays beside their later ones after they change
  it. A stolen backup gives an offline guess at passwords people reuse elsewhere, for people
  who may never have been let in.
- **Run:** no, reading alone.
- **Remedy:** make the column nullable (a revision) and clear it when the request is decided
  or its confirmation lapses.

### U07-12: the sign-in guard keeps every username ever tried, at any length, until a restart

- **Kind:** bug. **Req:** S13.7.5.1, S13.7.5.5 (counters in memory).
- **Code:** `web/server/src/moolakata/ratelimit.py:127-131`:
  ```text
          with self._lock:
              now = self._clock()
              u = self._by_user[username.lower()]
              self._trim(u, now)
              u.append(now)
  ```
  `_trim` empties a deque but no key is ever removed (`_failures` likewise, by address); the
  login is the body's `login` with no length limit but the 1 MB body (`ui/session.py:54-56`).
  `_codes` keeps a pending sign-in's count when it expires with fewer than five wrong codes.
- **What goes wrong:** each failed sign-in with a new login string adds an entry kept until the
  process restarts; at up to 1 MB a login, ten per address per quarter hour, a scan from many
  addresses grows the server's memory without bound. Low on its own (the lockout and argon2's
  cost slow it), but it grows on the documented 1–2 GB hosts.
- **Run:** no, reading alone.
- **Remedy:** cap `login` (254 characters, an email's limit) in `SignIn`, and drop empty deques
  and lapsed entries in `_trim`'s callers (or sweep them with the hourly prune).

### U07-13: the password hints say "At least 12 characters" whatever the minimum is set to

- **Kind:** differs. **Req:** S10.1.1, S16.5 (the minimum, 12 by default, 8 to 128).
- **Code:** `web/ui/screens/signin.js:156`, `reset.js:30`, `welcome.js:125`:
  ```js
                          hint="At least 12 characters; not a common password.">
  ```
  and `setup.js:63` ("At least 12 characters, and not a common password."). No route the
  signed-out screens use gives the minimum (`GET /signup` answers `open` and `domains` only).
- **What goes wrong:** an admin sets the minimum to 16; an invited user types 13 characters as
  the hint says and is refused "Use at least 16 characters." Set to 8, the hint asks for more
  than the server does. The guides say "At least the minimum length" (`welcome.md`,
  `signup.md`), so only the screens are wrong.
- **Run:** no, reading alone.
- **Remedy:** say "At least the minimum length …" as the guides do, or have `invitations/lookup`,
  `GET /signup` and the reset screen carry `passwordMinLength`.

### U07-14: a display name with a line break makes every invitation its holder sends fail with 500

- **Kind:** bug. **Req:** S10.1.1 (a display name of at most 80 characters), S10.1.3.
- **Code:** `web/server/src/moolakata/auth/users.py:268-272` checks only length after
  `strip()`:
  ```text
  def _name_problems(name: str, field: str = "displayName") -> list[FieldError]:
      name = (name or "").strip()
      if not name or len(name) > 80:
  ```
  (Profile's check is the same, `ui/profile.py:190-192`), and the inviter's name goes into the
  subject, `auth/users.py:385`: `f"{by.displayName} invited you to MoolaKata"`.
  `EmailMessage` refuses a header with a line feed (`ValueError: Header values may not contain
  linefeed or carriage return characters`, tried in this session's Python).
- **What goes wrong:** an admin whose display name was saved as "Ada\nAdmin" through the API
  invites anyone: `ValueError` inside `Mailer.send`, a 500, and no invitation. Other control
  characters pass into names shown everywhere.
- **Run:** partly: the header refusal was run on its own; the invite route was not.
- **Remedy:** refuse control characters (`\x00-\x1f\x7f`) in names, users' and people's.

### U07-15: PATCH `/persons/{id}` lets an admin, or a user their own person, make a person private

- **Kind:** differs. **Req:** S10.10.2 ("Its creator may make it **private**"; people are the
  household's, and every user is a person, S10.10.1).
- **Code:** `web/server/src/moolakata/ui/people.py:132, 141`: whoever holds `owner` on the person
  (`people.level`: its own user, an admin, its creator until it is a user) saves
  `values["private"] = body.private`. The gift plan's route (`/people`, unit 05) holds the rule
  (`canMakePrivate`), this one doesn't.
- **What goes wrong:** Bob, a user, PATCHes his own person with `"private": true`: he vanishes
  from every other user's people, gift lists and family tree, though every user is a person
  seen by all; an admin can do the same to anyone's. Reached through the API only (no screen
  sends `private` here).
- **Run:** no, reading alone.
- **Remedy:** take `private` only from the creator of a person who isn't a user, as `/people`
  does; ignore it otherwise.

### U07-16: a marriage an admin confirmed for someone who wasn't a user stays confirmed when that person becomes one

- **Kind:** privacy. **Req:** S10.10.4 ("A spouse needs both people's confirmation, the other's
  from their own Profile (an admin confirms for a person who isn't a user)"), S10.10.1 (a new
  user "becomes that person"), S3.8, S8.14.1.
- **Code:** `web/server/src/moolakata/people/__init__.py:42-50`:
  ```text
      taken = set(s.scalars(select(User.personId).where(User.deleted == false())))
      free = [p for p in same_name(s, name) if p.id not in taken]
      if len(free) == 1:
          p = free[0]
          p.sex, p.private = sex, False
          return p
  ```
  The person's relationships come with it, their `confirmed1At`/`confirmed2At` as they were;
  `may_confirm` (`:274-281`) let an admin confirm that side only because the person wasn't a
  user.
- **What goes wrong:** Mallory adds *Bob Smith* (not a user) as her spouse; an admin, asked to
  confirm it for gifts, confirms Bob's side. Months later Bob is invited and becomes that
  person: from his first sign-in the marriage counts, confirmed, for wash sales between his
  trades and Mallory's (`washes.recompute`, `spouse_user_on`) and for a joint tax book, though
  Bob never confirmed it. He sees it in Profile and can remove it, but nothing asks him.
- **Run:** no, reading alone.
- **Remedy:** when a person becomes a user (`for_new_user`, and a remote `join`), clear the
  confirmation of that person's side in each of their marriages, so it waits for them; tell
  them in Profile.

### U07-17: the guides say other than the sections and the code in four places

- **Kind:** differs. **Req:** S13.7.5.1, S16.2, S18.9 (rejected idea 21), S10.3.
- **Where:**
  1. `web/ui/guides/signin.md:9`: "Ten wrong passwords in 15 minutes lock the username for a
     while." S13.7.5.1, Settings › Sign-in's own guide (`settings-sessions.md:17-19`) and
     `ratelimit.py:80-85` lock the **address** and only slow the username.
  2. `web/ui/guides/dialog-written-email.md:5`: "it works once, for a day at most". An
     invitation's link works a week, and its written email is kept that long (S10.1.3, S16.2,
     `auth/users.py:393`).
  3. `web/ui/guides/profile.md:79` (Connections): "each with its driver (Schwab, OFX Direct Connect
     or a folder of downloads)". The Folder driver is gone (rejected idea 21; `connections.js`
     offers none).
  4. `web/ui/guides/users.md:47` (New group): "A named set of users that accounts and portfolios
     can be shared with." Any of the eight kinds can be (S10.3).
- **Run:** no, reading alone.
- **Remedy:** correct the four lines.

### U07-18: `/mcp` answers 500, not a JSON-RPC error, when `params` or `arguments` isn't an object

- **Kind:** bug. **Req:** S10.9.6 (JSON-RPC 2.0), S10.9.5 (each tool's input checked against
  its schema, review 2's B32), S13.7.8.
- **Code:** `web/server/src/moolakata/mcp.py:404` and `:321-327`:
  ```text
      method, id_, params = msg["method"], msg.get("id"), msg.get("params") or {}
  ...
      name = params.get("name")
      args = params.get("arguments") or {}
      ...
      unknown = set(args) - set(t.params)
      if unknown or not isinstance(args, dict):
  ```
  `params` is used as a dict without a check (`initialize` at `:408` too), and `args` is put in
  a `set` before its type is checked.
- **What goes wrong:** a token holder's client sends `"params": [1]` to `initialize` or
  `tools/call` (`AttributeError`), or `"arguments": [{"a": 1}]` (`TypeError: unhashable`): each
  is a 500 with an error id, where JSON-RPC asks for -32602 *Invalid params*. Only a token's
  holder can reach it; nothing leaks.
- **Run:** yes, `tmp/u07/t/test_u07_mcp.py` (the three bodies raise `AttributeError`,
  `AttributeError`, `TypeError`; `run4.txt`).
- **Remedy:** refuse a non-object `params` with -32602 before the method is read, and test
  `isinstance(args, dict)` before anything else; a test of each.

## Phase 1 items judged against the code

- **DC-10** (remote usernames ≤ 64, names ≤ 120, against S10.1.1's 32 and 80): the `User` table
  has no length `CHECK` (`store/tables/users.py:18-77`); S10.1.1's rules are applied to local
  users only (`auth/users.py:253-272`), and the link cuts a remote user's fields to 64 and 120
  (`links/manage.py:341-359`). The code follows DC-10's proposed reading (a remote user's
  fields follow `link-protocol.md` §4.2, a longer value cut); only the documents are missing it.
- **DC-17** (`read/write` or `write`): the enum is `read`, `write` (`sharing.py:19`,
  `store/tables/sharing.py` `CHECK level IN ('read', 'write')`), the dialog's switch
  None · Read · Write: R2.9 and S10's name; R1.7's "read/write" is the document's.
- **DC-22** (a *From linked servers* filter): the account list's filters end at *Shared by me*
  (`web/ui/screens/accounts.js:20-23`), and nothing from a link enters local lists: the code
  matches DC-22's remedy (S12.10.5, rejected idea 7), not S10.6's last filter.
- **D2-14** (an admin's two-step reset under S13.7.2): `DELETE /users/{id}/two-step` asks for
  the password again (`ui/users.py:201`): the code takes the generous reading. Accepting the
  connector's address is unit 10 and 12's.
- **D2-17** (the unlock's lockout figures): `ui/unlock.py:104, 112` call `guard.failed` with no
  figures, so the unlock uses the defaults (10 failures, 15 minutes) whatever Settings say:
  D2-17's proposed reading.
- **D2-18** (how many welcome phrases): `keys/welcome.py:13-14` keeps 20 at most, an hour each,
  as the connector's: D2-18's proposed reading.
- **D3-23** (`/mcp` arguments): snake_case arguments (`mcp.py:123-127`), camelCase answers (the
  screens' models): D3-23's proposed reading.
- **D3-19**, **D2-11**: documents (and unit 09's Profile layout); nothing here contradicts them.
  `Share` holds kind, item, level, user or group, `includeReceipts`.

## Earlier findings re-checked

| Finding | State (review 2) | Holds? |
|---|---|---|
| K7 (tokens: re-auth, revoked by a password change or reset, emailed) | done | yes: `ui/tokens.py:194`, `auth/users.py:494-496`, `tokens.py:59-78`; tested (`test_tokens.py:100, 118`) |
| K8 (admins trusted; opening a written email in Activity for its addressee) | done, decided | yes for this unit's part: `email.opened` is rendered (`ui/activity.py:122`) and seen by its owner, the addressee (`_visible`, `:268`); the route that records it is unit 10's |
| K14 (re-auth to make an admin, to share with a linked server, Include receipts) | done | yes: `ui/users.py:130-137, 144, 174, 249, 295-297`, `ui/sharing.py:206-219, 247-248`; a way round it for accounts: U07-5 |
| K15, A12 (the email queue in the database) | done | yes: `mail.py:253-280, 346-400, 402-431`; a refused email keeps recipient, subject and error (`:415-421`) |
| K16 (two-step brute force) | done | yes: five wrong codes end the token (`ratelimit.py:155-163`, `ui/session.py:242-244`), one code at a time (`:226-227`), slowed before the check (`:231-233`), /64 (`ratelimit.py:57-68`). New beside it: U07-4 (concurrent attempts at the password step) |
| K17 (oracles outside the guard) | done | yes: reactivation answers the same (`ui/session.py:526-537`, `auth/users.py:641-663`); re-auth and the current password behind the guard (`guarded`, `ui/session.py:284-297`, `ui/profile.py:263-273`); sign-up hashes first (`auth/signup.py:94-98`). New beside it: U07-10 (usernames) |
| K19 (logs) | done | this unit's part: no sign-in path logs a password, token or code; the access log has route, status and user id only (`middleware.py:348-357`) |
| P1, C42 (a spouse needs both) | done | yes: `people/__init__.py:269-316`, `ui/people.py:373-446`; a hole when a person becomes a user: U07-16 |
| P5, C21 (remote users' persons; a user's person theirs) | done | yes for this unit's part: `may_join`/`join` (`people/__init__.py:73-101`), `level` (`:133-166`); the link side is unit 08's |
| P8 (Activity for every kind's receivers; a removed receiver keeps the entry) | done | yes: `ui/activity.py:252-295`; tested (`test_sharing.py:205`) |
| B32 (MCP `limit` and inputs checked) | done | yes: `mcp.py:357-378`; malformed `params` still 500: U07-18 |
| N12 (recovery-code email; new-address email with two-step) | done | yes: `ui/session.py:249-273`; the notice skips a quiet month: U07-2 |
| C9 (a written invitation kept a week) | done | yes: `auth/users.py:393`, `mail.py:42-53`; one guide still says a day: U07-17 |
| C35 (S10.1.1 refers to S13.7.3) | done | yes: `auth/passwords.py:29-39` |
| C37 (reset requests counted) | done | half: counted in a 30-a-quarter-hour window, never locking the address: U07-3 |
| C52 (share requests alert the creator and the admins) | done | yes: `alerts.py:770-781` (found by search) |
| A1–A6 (usernames, link lifetimes, reactivation, sessions, 1,024 maximum, counters in memory) | confirmed (Q19) | yes: `auth/users.py:27-31`, `auth/sessions.py:84-135`, `passwords.py:33`, `ratelimit.py:1-2` |
| F5 (review 1: the published default password) | done | yes: the welcome makes the first admin (`ui/welcome.py:113-122`); a legacy admin reaches only setup, and the published password is refused (`auth/users.py:191-196`) |

## The uncited first-level item and the untraced candidate

- **S10.5** (through a group): built under other words in `access.py:37-69` (only active groups,
  a direct and a group share give the higher level, `higher`) and `access.holders`
  (`:177-203`); tested (`test_sharing.py:50`). Not a claim.
- `ui/components/auth.js`: the card of the signed-out screens and the token from a link's
  fragment (S10.1.3, S10.1.5, S12); traced.

## Checked and sound

- Passwords: argon2id at 64 MiB, 3 passes; the 1,024 maximum; the common list, case folded
  (`auth/passwords.py`); a missing user costs a hash too (`verify`), so sign-in's timing doesn't
  tell.
- Sessions: 256-bit tokens kept as SHA-256 (`auth/tokens.py`), idle and absolute lifetimes,
  expired rows removed before the refusal, rotation at a change of admin or setup state with
  `authAt` carried and a fresh absolute lifetime (`auth/sessions.py`, `ui/deps.py:37-79`);
  admin rights read live on each request, never from the session row; sign-out, a password
  change and deactivation end every session; a password change gives this browser a new one.
- One-time tokens: one per purpose per user, issuing a new one ends the last (`_issue`); used
  once, checked for purpose and expiry; reset and invitation refuse an inactive user; links
  carry the token in the fragment.
- Two-step: RFC 6238 with ±1 step and no step twice (`totpLastStep`); the pending seed sealed
  apart; recovery codes 16 of 31 letters, hashed, used once; turning off and the admin's reset
  remove seed and codes, the reset ending sessions; every change emailed and in Activity.
- Re-authentication on every S13.7.2 route of this unit: email change, two-step on, off and new
  codes, tokens, admin membership on all three routes, the admin's two-step reset, linked
  shares and Include receipts.
- Sharing: only the owner (or a tax book's filers) saves; remote users only at read and only on
  a live link; inactive users and groups refused; removal drops the receiver's tags; an
  inactive user's `reach` is empty; every read goes through `access` and answers 404.
- Access tokens and MCP: hash of a 256-bit secret compared in constant time; dead when revoked,
  expired or the user inactive; a chosen-items token filtered in every account and portfolio
  tool, the household tools refused it; a token caller is never an admin; 60 calls a minute;
  every call in Activity; foreign `Origin` refused.
- Sign-up: off unless SMTP and the public URL are set; a known address answered alike, after
  the same hash; approval rechecks username and email.
- The welcome: phrases in memory, 20 for an hour, the key written only after three words come
  back; the first admin only while no user exists.
- The email queue: the database holds queued emails, removed when sent or expired; written
  files 0600 in a 0700 folder; SMTP to the address the guard vetted, TLS verifying the host.
- People: one person once, private persons seen only through a share, a user's person changed
  by them and admins; one spouse at a time and no one their own ancestor; a marriage changed is
  confirmed again; wash sales and joint books read confirmed marriages only.

## Read lightly or not read

- `web/ui/screens/profile.js` past line 330 (the relationship dialog's form, two-step and
  password cards, assumptions) and `screens/users.js` past line 130 (dialogs) were skimmed for
  the routes they call; `screens/activity.js` (93 lines) not read.
- `store/entities/{users,sharing}.py` and `store/tables/{people,activity}.py` read for their
  columns only.
- The tests were read by their names and the parts the claims lean on; none was read whole.
- `ui/settings.py`'s written-email route (unit 10) and `alerts.py`'s share-asked alert were
  found by search, not read.
- U07-4 was not run against a live server (it would take this machine's memory); the scaling
  was measured with 16 threads.

## Work pad: severity, confirmations, status

| Id | Kind | Req | Sev | Conf | Status | Description |
|---|---|---|---|---|---|---|
| U07-1 | security | S10.1.3, S10.1.5 | Med | 0 | open | Withheld (`withheld.md`) |
| U07-2 | security | S10.1.9 | Low | 0 | open | A sign-in from a new address after a month with no sign-ins sends no notice |
| U07-3 | differs | S13.7.5.1 | Low | 0 | open | Reset requests never lock the address; the throttle allows 30 a quarter hour, shared with other routes |
| U07-4 | security | S13.7.5.1, S13.7.3 | Med | 0 | open | Withheld (`withheld.md`) |
| U07-5 | privacy | S5.1.2, S10.5, S13.7.2 | Low | 0 | open | *Share these accounts too* shares to each person of the moment: group leavers keep the accounts, linked users get them without re-auth |
| U07-6 | differs | S10.10.5 | Low | 0 | open | The family tree drops in-laws, step-parents and stepchildren when a spouse dies |
| U07-7 | differs | S10.10.1 | Low | 0 | open | An admin's rename in Users leaves the user's person under the old name |
| U07-8 | bug | S10.10.2 | Low | 0 | open | An admin or a person's own user opens a private person's Share dialog and is refused at Save |
| U07-9 | bug | S13.7.1, S13.7.2 | Low | 0 | open | Re-authentication as the first request after a change of privilege answers 500 |
| U07-10 | security | S10.1.4.1 | Low | 0 | open | Sign-up tells anyone whether a username exists |
| U07-11 | security | S10.1.4.2, S13.7.3 | Low | 0 | open | A sign-up request keeps the person's password hash for good |
| U07-12 | bug | S13.7.5.1, S13.7.5.5 | Low | 0 | open | The sign-in guard keeps every username ever tried, at any length, until a restart |
| U07-13 | differs | S10.1.1, S16.5 | Low | 0 | open | Password hints say "At least 12 characters" whatever the minimum is |
| U07-14 | bug | S10.1.1, S10.1.3 | Low | 0 | open | A display name with a line break makes its holder's invitations fail with 500 |
| U07-15 | differs | S10.10.2 | Low | 0 | open | PATCH `/persons/{id}` lets an admin, or a user their own person, make a person private |
| U07-16 | privacy | S10.10.4, S10.10.1 | Low | 0 | open | A marriage an admin confirmed for a non-user stays confirmed when that person becomes a user |
| U07-17 | differs | S13.7.5.1, S16.2, S10.3 | Low | 0 | open | Four guide lines say other than the sections and the code |
| U07-18 | bug | S10.9.6, S10.9.5 | Low | 0 | open | `/mcp` answers 500 when `params` or `arguments` isn't an object |

Scratch runs: `/home/dev/.claude/jobs/b8ac83ff/tmp/u07/` (`t/test_u07.py`, `t/test_u07_mcp.py`,
`s/tree_widow.py`, `s/argon_parallel.py`, and their outputs `run1.txt`–`run4.txt`).
