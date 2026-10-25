# Code review 3, unit 09: web-ui-architecture

**Session:** Oct 24, 10:02 PM to Oct 24, 10:17 PM (Chicago). **Commit read:** `6916954`. **Scope:** full.
**Checking:** quick (no §8 checker; every claim at 0 confirmations, status open).

## Brief (docs/REVIEW.md §7)

### 1. Sections, code and tests (map.md)

- **Sections:** S12 (the web UI: S12.1 the frame, pager, update pill; S12.2 navigation and the
  screens; S12.3 privacy mode; S12.4 numbers; S12.5 price age; S12.6 the live stream; S12.7 the
  help pane and guides; S12.8 keyboard, accessibility, themes, desktop; S12.9 the mockups;
  S12.10 linked households' window as far as the frame goes; S12.11 alerts; S12.12 `Dec`;
  S12.13 durations; S12.14 the welcome and the locked screen) and S13 (architecture: S13.1 the
  address and its paths; S13.2 who is accepted where; S13.3 the listener, `proxy` and `tls`
  modes, the certificate, forwarded headers; S13.4 background tasks; S13.5 the egress guard;
  S13.6 start, stop, the states, host commands; S13.7 security: sessions, the password again,
  passwords, CSRF, rate limits, request limits, headers, errors, logs, TLS, supply chain;
  S13.8 the API's conventions), with the README's R1–R3 lines they rely on (R1.9 exact
  numbers, R3 principles).
- **Code (10,077 lines, 59 files):** `src/{__init__,alerts,app,certs,config,contract,duration,
  errors,events,jobs,listener,main,middleware,net,tasks}.py`, `src/store/{entities,tables}/
  alerts.py`, `src/ui/{__init__,alerts,conventions,dashboard,deps,stream}.py`;
  `ui/api/client.js`, `ui/app/{config,dec,duration,format,hooks,html,main,router,sealed,
  stream}.js`, `ui/assets/{favicon,icons}.svg`, `ui/charts/{chart.js,echarts.d.ts}`,
  `ui/components/{amount,bits,dialog,fields,frame,help,icon,markdown,menu,pager,term,toast,
  tooltip}.js`, `ui/index.html`, `ui/screens/{alerts,dashboard,notfound}.js`,
  `ui/store/prefs.js`, `ui/styles/{base,components,tokens}.css`. The generated
  `ui/api/openapi.json` and `types.js` are not read; `contract.py`, which writes them, is.
  `alerts.py`'s cash-before-payday logic was judged in unit 05 (U05-22) and is not re-judged.
- **Tests (2,619 lines):** `tests/test_{alerts,app,browser_smoke,config,conventions,core,
  duration,guides,middleware,no_network}.py`.
- **Guides:** `ui/guides/dashboard.md`, `alerts.md`, `settings-alerts.md`, `terms.md`; the
  guides as a set (every screen has one, the help pane renders them); a sample of the others
  for how the pane renders them.
- **Cites no section:** `ui/app/html.js`, `ui/charts/echarts.d.ts`, `ui/components/bits.js`,
  `ui/index.html`, `ui/screens/notfound.js`.

### 2. Delta since review 2 (`294792b`..`6916954`)

Content changed: 1,793 lines (17%), 4 new files. New: `certs.py` (112), `net.py` (267, split
out of an older module), `ui/components/term.js` (95), `tests/test_guides.py` (127). Changed
most: `alerts.py` (+398/−43: new causes N15, C45, C11, the Landlock alert, the owner's one
alert, B27's read-then-write evaluation, K25's count-only event), `middleware.py` (+164/−11:
K1's peer address, request and header limits, headers), `contract.py` (+107/−8: N16's problem
codes, B38's release), `markdown.js` (+100/−13), `config.py` (+49/−8: B40's unknown keys),
`app.py` (+47/−10), `ui/dashboard.py` (+43/−5), `dialog.js` (+41/−16), `sealed.js` (+34/−4),
`jobs.py` (+34), `main.py` (+31/−14: K25's dev mode), `help.js` (+29/−5),
`ui/conventions.py` (+26), `format.js` (+21), `listener.py` (+14/−4), `errors.py` (+13/−5: K19),
`tasks.py` (+13/−3). Tests: `test_app.py` (+254/−11), `test_alerts.py` (+137/−14),
`test_conventions.py` (+132/−10), `test_guides.py` (new), `test_core.py` (+102/−7),
`test_config.py` (+67/−14), `test_browser_smoke.py` (+59/−12), `test_middleware.py`
(+44/−10). The rest is the rename. Read first: `middleware.py`, `net.py`, `certs.py`,
`config.py`, `alerts.py`, `contract.py`, `markdown.js`.

### 3. Earlier reviews' findings in this area

Review 2 (§12.2 marks each done unless said; m8/m9 = milestone 8/9):

| Finding | What | State per review 2 | To re-check |
|---|---|---|---|
| K1 | host key routes trusted a forgeable loopback (`ClientAddress` rewrote the peer) | done (m8 part 1: host commands over a socket) | `middleware.py` client address, trusted proxies; no key route on the listener |
| K2 | linked receipt served without sandbox (the headers half: S13.7.7 on every file route) | done | `middleware.py`'s headers (unit 08 checked the route) |
| K3, K18 | TLS verified and pinned; guard's holes (rebinding, chunked past 20 MB, URL joining) | done (m8 part 2) | `net.py` (unit 08 found U08-13 beside it) |
| K19 | `hide_parameters`; refusals logged with their id; no host path in `detail` | m9 part 1 | `errors.py`, `middleware.py` |
| K23 | Settings › Network while locked (A14) | m9 part 5 (text) | `app.py`'s locked app |
| K25 | uploads spooled to disk; `/tmp` tmpfs; the alert event's titles; dev mode in the image | m9 parts 4–5 | `middleware.py`/`app.py` uploads, `alerts.py` event, `main.py` dev |
| B27 | alerts every minute in one write transaction; a failing check resolves and reopens | done (m8 part 9) | `alerts.py`, `tasks.py` |
| B38 | `Location` on every 201, job on every 202, OpenAPI names the release | m9 (12.5.4) | `contract.py`, `ui/conventions.py` |
| B40 | unknown config key ignored | done | `config.py` |
| N15 | alerts for an option expiring within a week, a pledge due, the rotation reminder | done (m8 part 7) | `alerts.py` |
| N16 | OpenAPI's problem codes and problem+json 422s | m9 part 7 | `contract.py` |
| C11 | an unlock counts as a phrase check | m9 part 5 | `alerts.py` |
| C45 | a statement value older than 90 days raises an alert | m9 part 7 | `alerts.py` (unit 03 found U03-11: never marked stale) |
| C52 | share request alerts the creator and admins | done | `alerts.py` |
| A7, A9–A11, A14, A16 | written from the code (forwarded headers, net timeouts, healthz states, link body 20 MB, ranges while locked, node certificate and chain alerts) | confirmed | as they stand |

Review 1's F8, F10, C7, C11, C12 (re-authentication list, the TLS key's storage, the egress
list) were requirements-level and superseded by review 2.

### 4. Phase 1 claims and decisions on S12, S13

None is decided yet; each is judged against the code (and both readings where open).

- **DC-1 = D2-1 + D3-1** (Med; needs the user): the 20 MB ceiling (S13.5) against receipts up to
  100 MB. Unit 08 found one oversize receipt stops a link (U08-1). Here: what `net.py` and the
  middleware's body limit actually bound.
- **DC-2 = D2-3** (Med; needs the user): `tls` mode "for testing" against the TrueNAS install.
  Here: what `tls` mode does (certificate, HSTS, TLS versions, HTTP/2) and whether it is fit for
  either reading.
- **DC-8** (Low): a newer database refused at start or at the unlock. Here: where the code
  refuses it.
- **DC-15** (Low): daily emails in the host's zone or each user's. Here: `alerts.py`'s summary.
- **DC-16** (Low): the linked-key hour and the 48-hour threshold, fixed or settings. Here:
  whether `alerts.py` reads the threshold from Settings.
- **DC-19** (Low): the config file's keys. Here: what `config.py` accepts and refuses.
- **D2-1**: see DC-1.
- Also on S12/S13: D2-10 (navigation order), D2-11 (Profile), D2-14 (the password-again list,
  unit 07 judged), D2-16 (100 MB in flight), D2-17 (the unlock's lockout figures, unit 07
  judged), DC-9 (counters in memory), DC-13 (two upload sizes), DC-18 (secrets' version),
  DC-22 (unit 07 judged), D3-9 (`/healthz` names the version), D3-16 (health states),
  D3-23 (unit 07 judged).

### 5. Untraced candidates and uncited first-level items

- Cites no section: `ui/app/html.js`, `ui/charts/echarts.d.ts`, `ui/components/bits.js`,
  `ui/index.html`, `ui/screens/notfound.js`.
- Uncited first-level items: **S12.14** (the welcome and the locked screen) and **S13.1** (the
  one address and its paths).

## Claims

### U09-1: withheld

- **Kind:** security. **Severity:** Med. Withheld (`withheld.md`, REVIEW.md §2).

### U09-2: with an upload limit of 19 MB, uploads are never counted against the 100 MB in flight

- **Kind:** bug. **Req:** S13.7.6 ("at most 100 MB of uploads in flight per user"), S16.8,
  S16.10.
- **Code:** `web/server/src/moolakata/middleware.py:242-258`:
  ```text
          limit = (
              self.upload_limit()
              ...
              else LINK_LIMIT
              if to_link
              else JSON_LIMIT
          )
          ...
          upload = limit != JSON_LIMIT and limit != LINK_LIMIT
  ```
  and `app.py:117-119` (`upload_cap`): `mb = max(settings.get(s, "importMaxMb"),
  settings.get(s, "receiptMaxMb"))` … `return (mb + 1) * 1024 * 1024`. `LINK_LIMIT` is
  `20 * 1024 * 1024` (`middleware.py:38`).
- **What goes wrong:** whether a request is an upload is told from the size of its limit, not
  from its kind. An admin who sets both size limits so the larger is 19 MB (Settings › Imports
  and › Receipts accept 1–200 and 1–100) makes `upload_cap()` exactly `LINK_LIMIT`, so every
  multipart upload, and every sealed receipt a linked server delivers, is treated as a JSON body:
  nothing is added to `in_flight`, and one user's uploads in flight are unbounded (each still
  at most 20 MB). Any other value works.
- **Run:** no; rests on reading (the arithmetic is exact).
- **Remedy:** keep the kind apart from the limit (`upload = ctype.startswith("multipart/") or
  (to_link and ctype.startswith("application/octet-stream"))`).
- **Alternatives:** none needed.

### U09-3: a refusal for an address outside Settings › Network carries none of S13.7.7's headers and isn't logged

- **Kind:** differs. **Req:** S13.7.7 ("Response headers on every response, refusals
  included"), S13.7.9 (failures logged), S16.14.
- **Code:** `web/server/src/moolakata/app.py:283-296`, the order of the middleware (the last
  added runs first):
  ```text
      app.add_middleware(middleware.SecurityHeaders, tls=server.config.mode == "tls")
      app.add_middleware(middleware.AccessLog)
      app.add_middleware(middleware.AddressRanges, ranges=server.network_ranges)
      app.add_middleware(
          middleware.ClientAddress, mode=server.config.mode, trusted=server.config.trusted_proxies
      )
  ```
  `AddressRanges` (`middleware.py:166-175`) answers `_send_problem(404, …)(send)` with the
  `send` it was given, which is outside `AccessLog` and `SecurityHeaders`; `_send_problem`
  (`:56-68`) writes only `content-type` and `content-length`. The comment above the list
  (`app.py:283-284`: "the client's address, then the log, the headers, the Origin check …")
  names an order the code doesn't have: the ranges come before the log and the headers.
- **What goes wrong:** a browser outside the allowed ranges (a phone on mobile data, say, with
  `/ui` limited to the home network) gets a 404 with no CSP, `nosniff`, `frame-ancestors`,
  COOP, CORP, `Referrer-Policy` or, in `tls` mode, HSTS; and no access-log line is written for
  it, so an admin looking for why someone is refused finds nothing. The body is fixed JSON, so
  the missing headers expose nothing today; the missing log line is the practical loss.
- **Run:** yes, `/home/dev/.claude/jobs/b8ac83ff/tmp/u09/mw.py` (output `mw.txt`): with `/ui`
  limited to `10.0.0.0/8`, `GET /ui/api/session` answered 404 with no `content-security-policy`
  and no `x-content-type-options`, and no `moolakata.access` line was written for it.
- **Remedy:** add `AddressRanges` before `AccessLog` and `SecurityHeaders` (so it runs inside
  them), keeping `ClientAddress` outermost; a test that a refused address's 404 carries the
  headers.
- **Alternatives:** `_send_problem` adds the common headers itself, as every early refusal would
  then need.

### U09-4: withheld

- **Kind:** security. **Severity:** Med. Withheld (`withheld.md`, REVIEW.md §2).

### U09-5: `trusted_proxies` takes whole networks, which S13.3 rules out

- **Kind:** security. **Req:** S13.3 ("forwarded headers are trusted only from the configured
  proxy addresses, each the proxy's own address and never a whole private range, since anything
  else in it could pose as the proxy"); review 2's K1 remedy ("the example must trust only the
  proxy's exact address").
- **Code:** `web/server/src/moolakata/config.py:149-156`:
  ```text
      for entry in server.get("trusted_proxies", []):
          try:
              proxies.append(ipaddress.ip_network(entry, strict=False))
  ```
  and `middleware.py:82-87` (`_is_trusted`: `any(addr in net for net in self.trusted)`).
- **What goes wrong:** an operator who writes `trusted_proxies = ["172.16.0.0/12"]` (the
  pattern review 2's K1 found in the example, and what many proxy guides suggest for Docker)
  starts without a word; every container on any Docker bridge can then send
  `X-Forwarded-For: <any address>` and be believed: it escapes the address lockout of
  S13.7.5.1 (a new "address" per attempt) and passes Settings › Network's ranges by naming an
  allowed address. The example file and operations.md say the exact address (`moolakata.toml:16`,
  `operations.md:83`), so only a misconfiguration is exposed, which is what S13.3's "never"
  is there to refuse. Host commands no longer depend on it (they use the socket), so the
  damage stops at the lockout and the ranges. Low.
- **Run:** no; rests on reading.
- **Remedy:** accept only single addresses (`ip_address`, or a network whose prefix is the full
  length) and refuse the start otherwise, naming S13.3; a test.
- **Alternatives:** accept a range but log a warning at every start; weaker than S13.3 says.

### U09-6: the self-signed certificate is never made again when it expires, and a pair half written is kept for good

- **Kind:** bug. **Req:** S13.3 ("given no certificate, the server makes a self-signed one on
  first start … a change to the list makes it again"), S13.6 (a certificate it can't load
  refuses the start), S11.1.3 (peers pin its key).
- **Code:** `web/server/src/moolakata/listener.py:33-35, 53, 58-67`:
  ```text
      if cert_path.exists() and key_path.exists() and set(names) <= _covers(cert_path):
          return cert_path, key_path
      ...
          .not_valid_after(now + dt.timedelta(days=825))
      ...
      fd = os.open(key_path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
      ...
      cert_path.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
  ```
- **What goes wrong:** (1) the pair is kept as long as it covers the names, whatever its dates:
  825 days after the first start of a `tls`-mode server (every TrueNAS install, DC-2), it
  serves an expired certificate. Browsers that had accepted it refuse it again; the connector
  and linked servers pin the key and may go on, but anything that checks dates fails, and
  nothing alerts an admin beforehand. (2) The key is written over first and the certificate
  after, neither through a temporary file: a stop between the two (a full disk, a kill) leaves
  a new key beside the old certificate, which still "covers" the names, so every later start
  keeps the mismatched pair and refuses with "the TLS certificate or key cannot be loaded" until
  an operator deletes `tls/` by hand.
- **Run:** no; rests on reading.
- **Remedy:** remake the pair when it is within, say, 30 days of `not_valid_after` (keeping the
  key, so pins hold, and only re-signing the certificate), and write each file to a temporary
  name and rename both; S13.3 says the certificate is renewed before it expires.
- **Alternatives:** a much longer validity (browsers ignore it for a self-signed one, and the
  pins are on the key), saying so in S13.3.

### U09-7: this server's own certificate is read over a raw socket, outside the egress guard

- **Kind:** differs. **Req:** S13.5 ("Outbound calls go through one httpx client with an egress
  guard … Each call connects to the address the guard checked").
- **Code:** `web/server/src/moolakata/certs.py:61-91` (`_probe`):
  ```text
          with (
              socket.create_connection((host, port), timeout=5) as raw,
              ssl.create_default_context().wrap_socket(raw, server_hostname=host),
          ):
  ```
  and again without verification (`:81-88`), to the host of `own_address(s)`, the link
  address an admin typed in Settings › Linked servers; called by `own_key` from link and
  connector routes (`ui/links.py:253`, `links/manage.py:172, 209, 267`,
  `connector/routes.py:144`, `connector/manage.py:81`), cached ten minutes.
- **What goes wrong:** the probe resolves the name itself and connects to whatever it resolves
  to, loopback, link-local and metadata addresses included, with up to two 5-second connects
  in the request that asked. The address is an admin's, so nothing is reached that an admin
  couldn't name; but it is a second outbound path that S13.5 says doesn't exist, and a link
  address on a loopback or metadata address, which the guard refuses for every other call
  (S13.5: "a link's address … never is" allowed by name), is reached here.
- **Run:** no; rests on reading.
- **Remedy:** make the probe through `net.Guard.check` (its address) or a `net.Client` with no
  pins whose TLS failure says "not public", then a second, pinned-to-anything handshake through
  the same backend; or S13.5 names this one exception.
- **Alternatives:** in `proxy` mode, take the certificate from the admin (paste the
  fingerprint), as it is the proxy's, not a call to make.

### U09-8: the middleware's refusals carry an error id that is never logged

- **Kind:** differs. **Req:** S13.7.8 ("Each error carries an id that is also in the log, with
  its status and code, refusals included"); review 2's K19 ("every problem logged with its id,
  status and code"), marked done in milestone 9 part 1.
- **Code:** `web/server/src/moolakata/middleware.py:41-53`:
  ```text
  def _send_problem(status: int, code: str, detail: str, headers=()):
      body = json.dumps(
          {
              ...
              "errorId": new_error_id(),
  ```
  It writes no log line; `errors.problem_response` (`errors.py:75-83`) is the one that logs
  `problem <id> <status> <code>`, and the middleware doesn't use it. `_send_problem` answers the
  Origin refusal (403 `origin-refused`), the body limits (413 `too-large`, 429
  `uploads-in-flight`), Settings › Network's 404, and the locked server's 503 `locked`.
- **What goes wrong:** a user behind a proxy that drops `X-Forwarded-Proto` has every change
  refused with *This request did not come from MoolaKata's own page* and error id
  `err_3f2a…`; the admin searches the log for that id and finds nothing (and, for the 404 of
  U09-3, not even an access line). K19's half about refusals holds for route refusals only.
- **Run:** yes, `tmp/u09/mw.py` (output `mw.txt`): a `POST /ui/api/session` with a foreign
  `Origin` answered 403 `origin-refused`; its `errorId` was in no log record (nor the ranges'
  404's). `test_middleware.py:118` checks a route's 404 only.
- **Remedy:** `_send_problem` logs `problem <id> <status> <code>` as `problem_response` does
  (or calls a shared helper); a test that a 403 `origin-refused`'s id is in the log.
- **Alternatives:** none.

### U09-9: between the unlock and readiness the API is served, not answered 503

- **Kind:** differs. **Req:** S13.8.4 ("503 while the server is starting"), S13.6 (`starting`
  between the unlock and readiness).
- **Code:** `web/server/src/moolakata/app.py:287`:
  ```text
      app.add_middleware(middleware.Locked, locked=lambda: server.store is None and not server.ready)
  ```
  `runtime.build` sets `server.store = store` (`runtime.py:186`) before it ensures the
  categories and benchmarks, registers the tasks, applies the egress guard, takes the host
  events, records the unlock, starts the tasks and the reader, and only then
  `server.ready = True` (`:393`). Nothing else checks `ready` for `/ui/api`, `/link`,
  `/connector` or `/mcp` (`grep -rn "\.ready" src`: `app.py`, `runtime.py` only).
- **What goes wrong:** for the seconds of that window (longer in dev with `--seed`), `/healthz`
  says `starting` while the API, `/link` and `/connector` answer as if ready: a linked
  server's exchange or the connector's report can arrive before `apply_egress` has set the
  guard's hosts or before the categories exist, and a page open on the locked screen that
  polls `/ui/api/unlock` may move on to sign-in and get answers from a half-built server. The
  window is short in production, so Low.
- **Run:** no; rests on reading.
- **Remedy:** the gate is `not server.ready` for everything but the open paths, with a 503
  `starting` and `Retry-After` while `server.store is not None`.
- **Alternatives:** set `server.store` last in `build`, after the rest is done on a local.

### U09-10: each price refresh starts its provider's rate limits afresh, so two refreshes in an hour can make twice Tiingo's calls

- **Kind:** bug. **Req:** S13.4 ("They run in a thread pool with per-provider rate limits"),
  S4.4.
- **Code:** `web/server/src/moolakata/tasks.py:102-104`:
  ```text
      def set(self, provider: str, limits: Sequence[tuple[int, float]]) -> None:
          with self._lock:
              self._windows[provider] = [Window(n, s) for n, s in limits]
  ```
  called at every refresh (`prices/refresh.py:297-299`: `ctx.limits.set(src.name,
  cls.limits)` in `build`), with Tiingo's `((50, 3600), (1000, 86400))`
  (`prices/tiingo.py:20`). Each `Window` starts with an empty `seen`.
- **What goes wrong:** the daily refresh makes 50 calls to Tiingo; an admin presses **Refresh
  prices** ten minutes later (`run_now`), and the new run's windows are empty, so it makes 50
  more within the same hour: Tiingo answers 429 and the run records failures (and, past the
  threshold, an alert) for a limit MoolaKata was meant to keep. The same for the 1,000 a day,
  Massive's 5 a minute and Cboe's 30 a minute. And a refresh waiting for Tiingo's hourly
  window holds one of the pool's four workers (`tasks.py:130`, `workers: int = 4`) for as
  long as it waits, so with backups and link pulls running, mail and alerts queue behind it.
- **Run:** no; rests on reading.
- **Remedy:** `set` keeps the existing windows (and their `seen`) when the limits are
  unchanged; only a changed limit replaces them. A test that two runs within the hour share
  one window.
- **Alternatives:** register each source's limits once at start.

### U09-11: the OpenAPI document lists only the codes written as literals; the link, copy, wallet and connector refusals, and any code a peer sends, are left out

- **Kind:** differs. **Req:** S13.8.3 ("Codes are stable strings … listed in the OpenAPI
  document"); review 2's N16, marked done in milestone 9 part 7.
- **Code:** `web/server/src/moolakata/contract.py:53-74` (`problem_codes`) collects the second
  argument of `Problem()`, `refuse()`, `FieldError()`, `_send_problem()`,
  `problem_response()` only when it is a string constant:
  ```text
              if (
                  name in PROBLEM_CALLS
                  and isinstance(arg, ast.Constant)
                  and isinstance(arg.value, str)
              ):
  ```
  Codes passed through a variable are skipped. Among them: `ui/links.py:243-245`
  (`refuse(…, e.code, e.message, status)` for every `LinkError`), `:371-373`
  (`Problem(status, e.code, …)` for copy errors), `ui/linked.py:150`, `ui/wallets.py:151`,
  `ui/connector.py:195`. `LinkError`'s codes (`links/*.py`: `already-linked`, `code-invalid`,
  `file-refused`, `no-certificate`, `not-moolakata`, `not-requested`, `state-invalid`,
  `unreachable`, and `certificate-changed` from `links/client.py:80-86`) and, through
  `links/client.py:143-147`, *any* code the peer answers with that matches `_CODE`, become
  this server's own API codes:
  ```text
          code = out.get("code")
          code = code if isinstance(code, str) and _CODE.match(code) else "refused"
          ...
          raise LinkError(code, refusal(code, r.status_code, out.get("protocols")))
  ```
- **What goes wrong:** `grep -c '"not-moolakata"\|"unreachable"\|"certificate-changed"\|"not-linked"'
  web/ui/api/openapi.json` finds none of them, though Settings › Linked servers answers each
  (the join answers `unreachable` with 502, a status S13.8.4 doesn't list). A client written
  against the document's enum meets codes it was told can't happen, and a linked server
  decides some of this server's codes. `/home/dev/.claude/jobs/b8ac83ff/tmp/u09/codes.txt`
  lists the 49 calls whose code isn't a literal; most pass a code that is a literal elsewhere,
  the link, copy, wallet and connector ones don't.
- **Run:** yes: `tmp/u09/codes.py` (an AST walk of `src/moolakata`, output `codes.txt`), and
  the grep above on the generated document.
- **Remedy:** each error class declares its codes (`LinkError.CODES`, …) and `problem_codes`
  adds them; a peer's code is mapped to one of this server's own (`refused` with the peer's
  in the log), never passed through; S13.8.4 lists 502 or the join answers 422.
- **Alternatives:** a test that walks the routes' refusals by calling them is heavier; the
  AST walk could follow a variable to its class's literal codes instead.

### U09-12: the Dashboard has no upcoming recurring transactions and no giving against its target

- **Kind:** not built. **Req:** S12.2.1 ("upcoming recurring transactions, occasions inside
  their reminder time (S7.7.3), giving against its target, the **Plans** card …, and stale
  prices, stale valuations, or sources and imports that need attention").
- **Code:** `web/server/src/moolakata/ui/dashboard.py:55-65` (the `Dashboard` model: net worth,
  change, investments, cash, groups, attention, budget) and `web/ui/screens/dashboard.js`
  (KPI tiles, the net-worth chart, Accounts by group, `Plans`, Needs attention). Neither has a
  recurring-transactions card or a giving card; `_attention` (`dashboard.py:151-270`) adds
  occasions, filings, mismatches, overdue statements, lots without basis, uncategorised rows
  and stale prices, but no stale statement valuation (S4.3) and no failing source or import.
  Allocation is later work (L5), so it is not counted here.
- **What goes wrong:** a household with a pledge of $500 a year and a mortgage payment due on
  the 1st sees neither on the Dashboard; they are on Giving and on a budget's Recurring tab
  only. No milestone, gap or later item schedules them (`S17-implementation-09-milestones.md`
  names "Dashboard (net worth, accounts, needs attention)" and the Plans and budget cards).
- **Run:** no; rests on reading.
- **Remedy:** a card of the next recurring transactions (from `budgets.recurring.detect` over
  the user's accounts, as `cash_short` does) and a giving card (the year's target and given,
  as the Giving screen's header); `_attention` adds a holding valued from a statement over 90
  days (as the alert does). Or S12.2.1 drops what the Dashboard won't show, with the mockup.
- **Alternatives:** schedule them as a later item.

### U09-13: one failing check keeps every other check's *source failing* alerts from resolving

- **Kind:** bug. **Req:** S12.11.2 ("a check that fails leaves its alerts as they were … it is
  resolved by itself when the cause clears").
- **Code:** `web/server/src/moolakata/alerts.py:844-858` and `:908-912`:
  ```text
              except Exception:
                  ...
                  failed |= _KINDS[fn.__name__]
      ...
          if cause is None:
              if kind not in failed:
                  resolve.append(alert_id)
  ```
  ```text
  _KINDS = {
      "price_sources": {"source-failing"},
      "email": {"source-failing"},
      "bitcoin_source": {"source-failing"},
      "linked_servers": {"source-failing", "link-broken", "link-certificate", "link-key-waiting"},
  ```
- **What goes wrong:** what is held back is a *kind*, and four checks share `source-failing`.
  While `linked_servers` raises (an error reading any one link's row, say), Tiingo's alert, the email alert and the bitcoin alert stay open after their
  sources answer again, and their emails don't stop being true until the link check is fixed;
  the same the other way. The alert's `causeKey` (`prices:…`, `mail`, `bitcoin…`, `link:…`)
  already says which check raised it.
- **Run:** no; rests on reading.
- **Remedy:** hold back by the failed check's key prefixes (`prices:`, `mail`, `bitcoin`,
  `link…:`) rather than by kind, or give each check its own kind.
- **Alternatives:** none simpler.

### U09-14: the reconciliation-mismatch alert is raised for loans and always links to a Reconcile tab

- **Kind:** differs. **Req:** S12.11.1.2 (a reconciliation mismatch "left open for 7 days
  (S1.11)"), S1.11 and S1.9.4 (a loan is checked on its Overview against its servicer's
  balance; review 2 §12.5.1, B33's decision).
- **Code:** `web/server/src/moolakata/alerts.py:446-486`: `where` is worked out for the overdue
  statement (`"/reconcile" if atypes.reconcilable(a.type) else ""`), but the mismatch alert
  ignores it:
  ```text
          if checks and not checks[-1].ok:
              yield Cause(
                  key=f"mismatch:{a.id}",
                  ...
                  link=f"/ui/accounts/{a.id}/reconcile",
  ```
  and runs for every active account with imports, loans included; the Dashboard's same check
  skips what isn't `reconcilable` (`ui/dashboard.py:193-195`).
- **What goes wrong:** a mortgage whose imported statements disagree with its ledger raises an
  alert (none on the Dashboard) whose *Reconcile* button goes to `/ui/accounts/<id>/reconcile`,
  a tab a loan doesn't have, landing on the Overview only by the router's fallback (as review
  2's B33 found for the overdue alert before it was fixed).
- **Run:** no; rests on reading.
- **Remedy:** `link=where` and `fix` "Reconcile" or "See the balance" by the same test; the
  Dashboard and the alert apply one rule for which accounts are checked.
- **Alternatives:** leave loans out of the mismatch alert, as the Dashboard does, if S1.9.4's
  check is meant to be the loan's only one.

### U09-15: an admin's alert about a Connection that keeps someone's accounts doesn't name the owner

- **Kind:** differs. **Req:** S12.11.1.1 ("An admin's alert about someone else's account names
  its owner and source, never the account's name or figures (S10.2)").
- **Code:** `web/server/src/moolakata/alerts.py:292-324`:
  ```text
          title = f"{c.label} {'needs a sign-in' if needs else 'is failing'}"
          about = f"Connection · {c.message or c.driver}"
          ...
          yield Cause(
              key=f"connection:{c.id}:{c.state}",
              kind="connection-failing",
              title=title,
              about=about,
              link="/ui/settings/connector",
  ```
- **What goes wrong:** the admins' copy says *Schwab is failing · Connection · …* with no word
  of whose it is, so with two people's Schwab Connections an admin can't tell which person to
  ask to sign in again without opening Settings › Connector. (The admin who is the owner sees
  the owner's copy only, which is right.) The bitcoin source alert concerns the household's
  explorer, so it is not an account alert.
- **Run:** no; rests on reading.
- **Remedy:** the admins' `about` names the Connection's owner's display name (`Connection ·
  Alice's · <driver>`).
- **Alternatives:** none.

### U09-16: a long duration answers 500: `parse` has no ceiling and the overflow isn't a refusal

- **Kind:** bug. **Req:** S12.13 ("read by one helper on each side …, which refuses anything
  else and says why"), R3.7 (refusals at the field).
- **Code:** `web/server/src/moolakata/duration.py:44`: `total += int(m.group(1)) *
  UNITS[unit]`, unbounded; `ui/links.py:337-341`:
  ```text
      try:
          span = duration.parse(body.for_ if body else "1d")
      except duration.DurationError as e:
          raise refuse("for", "duration-invalid", str(e)) from None
      until = clock.now() + span
  ```
- **What goes wrong:** an admin pausing a link "for good" types `1000000w`: the browser's
  `parseDuration` accepts it, `parse` returns 7 million days, and `clock.now() + span` raises
  `OverflowError` (past year 9999): 500 *Something went wrong*. `999999999w` overflows inside
  `parse` itself (`OverflowError`, not a `DurationError`). Run: `duration.parse("999999999w")`
  and `duration.parse("99999999999999999999m")` both raise `OverflowError` (`isinstance(e,
  ValueError)` is False).
- **Run:** yes, the two calls above in `uv run python -I -c …`.
- **Remedy:** a ceiling in both helpers (a year, say, or what each field allows), refused with a
  sentence ("A duration is at most 52w."); `parse` turns any arithmetic error into a
  `DurationError`.
- **Alternatives:** the pause route clamps `until`.

### U09-17: the Watchlist is not built, and nothing schedules it

- **Kind:** not built. **Req:** S12.2.12 ("**Watchlist** *(small)*: instruments the user
  follows without holding them"), S12.10.3.4 (the linked window has no Watchlist, which
  assumes there is one).
- **Code:** `web/ui/components/frame.js:36-51` (`NAV`, "only the screens this release has":
  no Watchlist); `web/ui/app/router.js:26-55` (no `/ui/watchlist` route); no server route,
  table or entity (`grep -rni watchlist web/server/src web/ui/screens web/ui/components`
  finds nothing). No item in `later.md`, `gaps.md` or the milestones names it, and no other
  section specifies it (`grep -rni watchlist docs/requirements` finds only S12.2.12 and
  S12.10.3.4). The mockup has one (D2-26 is about its prices).
- **What goes wrong:** a user who wants VIX or a stock they don't hold followed has nowhere to
  put it; the price refresh (S4.4: "only what is held or watched") has nothing "watched" to
  price.
- **Run:** no; rests on reading and the greps above.
- **Remedy:** build it (a per-user list of instruments, priced by the refresh, with last
  close and change), or move it to later work with an L id and say so in S12.2.12 and the
  mockup.
- **Alternatives:** none.

### U09-18: privacy mode blurs only what is marked `.amt`; projections, taxes, giving and rules show amounts in plain text

- **Kind:** differs. **Req:** S12.3 ("a button in the header (an eye) blurs every amount on the
  page").
- **Code:** `web/ui/styles/base.css:59` (`body.privacy .amt { … }`) is the whole mechanism
  (`frame.js:117-119` toggles the class); amounts formatted with `money()` into running text
  carry no `.amt`: `web/ui/screens/projections.js:44, 180-237` (`dollars(r.start)`: "Starts from
  $…", "median at retirement …", "Chance of $… by …", "saving $… a month"),
  `components/taxpanels.js:402` ("paid in 2026 so far: ${money(total, …)}"), `:532`,
  `screens/giving.js:525` (a lot's "basis $…"), `components/rules.js:42-45` (a rule's amount
  range), `screens/import.js:474, 509`, `screens/transaction-dialog.js:327`.
- **What goes wrong:** with privacy mode on, the Projections screen still reads "A model, not a
  forecast. Starts from $1,284,000" and "median at retirement (2041) $2,310,000" in the clear,
  and the Income panel the tax paid so far, to whoever looks over the shoulder; the person
  trusted the eye to hide them.
- **Run:** no; rests on reading.
- **Remedy:** `money()` (in `app/format.js`) returns its text wrapped in a `.amt` span (or a
  `Money` component used everywhere), so nothing formatted as money escapes; a test in the
  browser smoke that, in privacy mode, no visible text node matches `\$\d`.
- **Alternatives:** blur by a CSS rule on every `.num` and the KPI values, plus the call sites
  above; easier to miss one.

### U09-19: tooltips never reach screen readers, so the collapsed sidebar's links and several marks have no name

- **Kind:** differs. **Req:** S12.1.3 ("styled tooltips that also show on keyboard focus and
  reach screen readers"), S12.8 ("every control is labelled").
- **Code:** `web/ui/components/tooltip.js:1-2` says "the text is also its aria-label when it
  has no text of its own", but nothing sets one: `show` (`:8-13`) only fills the `tip` signal,
  and `TooltipHost` (`:26-34`) draws `<div class="tooltip" role="tooltip">` that no element
  points to (`grep -rn "aria-describedby" web/ui/components web/ui/app web/ui/screens`: only
  `fields.js:24` and `term.js:81`). In `frame.js:180-187` a collapsed sidebar's link is an
  `aria-hidden` icon and a `.nav-label` set to `display: none` (`components.css:57-62`), named
  only by `data-tip`. Likewise `screens/accounts.js:40, 43` (the "Shared by me" / "Shared with
  me by …" marks are an icon and a number).
- **What goes wrong:** with the sidebar collapsed, a screen reader announces thirteen links as
  "link" with no name; the sharing marks on Accounts read as a bare number.
- **Run:** no; rests on reading.
- **Remedy:** `installTooltips` (or the components) set `aria-label` from `data-tip` on an
  element without text, and `aria-describedby` to the tooltip's id while it shows for one
  with text; the collapsed nav keeps `.nav-label` in the accessibility tree (`sr-only`
  instead of `display: none`).
- **Alternatives:** an `aria-label` written beside every `data-tip` by hand.

### U09-20: no test checks a guide's screenshot, and about forty screen guides have none

- **Kind:** test gap. **Req:** S12.7.4 ("What a guide holds: a short paragraph on what the
  screen is for, a screenshot, and a heading for every field"), S12.7.6 ("a test fails when a
  screen has no guide, **a guide's screenshot is missing**, a field's label finds no heading,
  the next field down the page sends the guide up …").
- **Code:** `web/server/tests/test_app.py:131-160` (`GUIDE_CHECK`, `check_guide`) checks that the
  guide loads, that each field finds a heading, and the order; `test_guides.py` checks the
  terms and forms. Nothing looks for an image (`grep -rn "shots/" web/server/tests` finds
  none). Screen guides with no `![` (from `for f in web/ui/guides/*.md; do grep -q '!\[' $f
  || echo $f; done`, leaving out the account-type, price-source and dialog parts):
  `budgets-cash-flow`, `budgets-compare`, `budgets-list`, `budgets-recurring`,
  `budgets-reimbursements`, `budgets-review`, `budgets-trends`, `budgets-where`, the fourteen
  `linked-*`, `portfolio-projections`, `settings-alerts`, `settings-email`,
  `settings-receipts`, `settings-signup`, `settings-tax-tables`, `locked`, `welcome`,
  `new-server`, `signin`, `signup`, `setup`, `reset`, `confirm-email`, `signup-confirm`. Every
  image the guides do name exists (checked with the same loop over `shots/…png`).
- **What goes wrong:** the help pane for Budgets' Compare, every linked-household screen, or
  Settings › Alerts shows text with no picture of the screen, which S12.7.4 says each has, and
  the check S12.7.6 promises would have said so.
- **Run:** yes, the shell loop above.
- **Remedy:** a test that every screen guide (not a part or dialog, if S12.7.4 means screens)
  has an image and that its file exists; then `web/dev.sh help-shots` for the missing ones, or
  S12.7.4 says which guides carry none.
- **Alternatives:** S12.7.4 exempts tabs whose screen guide already has one.

### U09-21: the Alerts, Settings › Alerts and Dashboard guides say less than the code does

- **Kind:** differs. **Req:** S12.11.1, S16.16, S12.2.1, S12.7.4.
- **Code and guides:**
  - `web/ui/guides/alerts.md:16-20`: "Admins are alerted about a price source or email failing
    …, a failed backup, the yearly check …, and the receipt reader running without its file
    sandbox …. An account's owner is alerted when its next statement or import is overdue, when
    its balance has disagreed …, and when a holding …". The code (`alerts.py` `CHECKS`) also
    alerts admins of the bitcoin explorer or node, a linked server not reached, broken, its
    certificate changed or its share waiting for a key, the connector silent, locked or
    moved, a Connection failing, the node's certificate and the key's rotation; owners of
    their wallets' source, a Connection, a transaction off the chain and an option past
    expiry; and every user of a share request, an occasion, an option expiring, a pledge, a
    projection behind and cash before payday. None of these is in the guide.
  - `web/ui/guides/settings-alerts.md:7-9`: "How long a price source, or email, may keep
    failing before admins are alerted." The same setting (`alertSourceHours`) also delays the
    bitcoin explorer or node (`alerts.py:168`) and a linked server's alert (`:178, 218`).
  - `web/ui/guides/dashboard.md:16-18`: "Investments: Brokerage and retirement accounts"; the
    code counts every account `atypes.investing` names (`ui/dashboard.py:104`,
    `ledger/types.py:109-111`: investing, retirement, education, giving and crypto groups),
    so a 529, a DAF and a bitcoin wallet are in it.
- **What goes wrong:** a user reading the Alerts guide to learn why a "pledge due" alert came
  finds nothing about it; an admin sets 6 hours believing it touches prices and email only and
  gets link alerts after 6 hours too.
- **Run:** no; rests on reading.
- **Remedy:** the alerts guide lists the causes by audience as S12.11.1 does (or says "for
  example"); settings-alerts names the explorer, node and linked servers; dashboard.md says
  which groups Investments sums.
- **Alternatives:** none.

### U09-22: the image's health check asks 127.0.0.1 whatever `[server] host` says

- **Kind:** bug. **Req:** S13.3 ("`[server] host` sets the listening address, all interfaces by
  default"), S13.6 ("The image's own health check asks only whether the server answers").
- **Code:** `web/server/src/moolakata/main.py:107-111`:
  ```text
      config = configured(args.config)
      scheme = "https" if config.mode == "tls" else "http"
      try:
          # Loopback to this container's own listener; its certificate may be self-signed.
          r = httpx.get(f"{scheme}://127.0.0.1:{config.port}/healthz", verify=False, timeout=4)
  ```
  while the listener binds `config.host` (`listener.py:82-84`).
- **What goes wrong:** an operator who sets `host = "192.168.1.20"` (one interface of a host-
  networked container, or a bare install with several) gets a server that answers on that
  address and a health check that finds nothing on loopback: `unhealthy`, so an orchestrator
  that waits for healthy containers (TrueNAS's, S13.6) never lets it come up. Also with
  `host = "::1"`-style IPv6-only binds.
- **Run:** no; rests on reading.
- **Remedy:** ask `config.host` (loopback when it is `0.0.0.0` or `::`), bracketing an IPv6
  address.
- **Alternatives:** the health check reads the host commands' socket (`/run/moolakata/sock`),
  which is always there and needs no address.

### U09-23: a statement over 100 MB, which Settings › Imports allows, is refused as "uploads arriving at once: wait"

- **Kind:** differs. **Req:** S13.7.6 (100 MB of uploads in flight), S16.8 (statements up to
  200 MB); D2-16 (Phase 1: the two limits disagree), judged here on the code.
- **Code:** `web/server/src/moolakata/middleware.py:262-270`:
  ```text
          declared = int(length) if upload and length and length.isdigit() else 0
          if upload and self.in_flight.get(who, 0) + declared > IN_FLIGHT:
              await _send_problem(
                  429,
                  "uploads-in-flight",
                  "More than 100 MB of uploads are arriving at once. Wait for them to finish.",
                  [(b"retry-after", b"10")],
  ```
  with `upload_cap` up to 201 MiB (`app.py:117-119`, `importMaxMb` 1–200, `settings.py:255`).
- **What goes wrong:** an admin sets the statement limit to 150 MB; a member uploads a 120 MB
  PDF statement with nothing else in flight. It passes the size check and is refused 429 with
  *Wait for them to finish* and `Retry-After: 10`; the browser (or the connector, which
  counts its files the same way) waits and tries again, and is refused again for ever. The
  route's own 413 (*Statements are up to 150 MB*) is never reached. Whichever way D2-16 is
  decided, the refusal names the wrong cause.
- **Run:** no; rests on reading.
- **Remedy:** with D2-16's decision: either S16.8's range stops at 100 (and the setting's
  validator with it), or a single upload larger than `IN_FLIGHT` is refused 413 naming the
  100 MB ceiling rather than 429.
- **Alternatives:** `IN_FLIGHT` is the larger of 100 MB and the largest size limit.

## Phase 1 claims judged against the code

None is decided yet; where a question is open, the code is set against both readings.

| Id | What the code does | Which reading it matches |
|---|---|---|
| DC-1 (D2-1) | Outbound, every answer is cut at 20 MB (`net.py:24, 220-230`; links use the default ceiling, `links/client.py:75-76`), so a peer's `file` answer over 20 MB fails. Inbound, a sealed receipt `deliver`ed as `application/octet-stream` to `/link/` is bounded by `upload_cap` (the larger size limit + 1 MB, up to 201 MiB, `middleware.py:242-250`), a link's JSON by 20 MB. | Neither fully: the receiving side already takes S16.10's sizes (the first remedy's reading), the fetching side keeps 20 MB (the protocol's). Unit 08's U08-1 is what follows. Note U09-4: the 20 MB counts compressed bytes. |
| DC-2 (D2-3) | `tls` mode: a self-signed P-256 certificate for 825 days naming `[tls] names`, `[server] name` and `localhost`, its key plain 0600 in `tls/` (`listener.py:30-68`); TLS 1.2+ (Hypercorn's default context), ALPN h2; HSTS a year (`middleware.py:33, 134-135`); forwarded headers ignored. Nothing marks it as testing-only. | Fit for "a supported mode" but for renewal (U09-6); nothing in the code depends on the "testing" reading. |
| DC-8 | A newer database raises `RefuseStart` in `store/migrate.py:78-82` during `runtime.build` at the unlock; `ui/unlock.py:117-123` logs `refusing to unlock: …`, answers 503 `cannot-unlock`, and the server stays up, locked. | S13.6 and `operations.md` §5.1 (at the unlock). `store/migrate.py:3`'s docstring ("refuses the start") is stale (unit 06's file). |
| DC-15 | `daily_summaries` (`alerts.py:1050-1100`) sends at Settings › Alerts' time in each user's zone (`timezones.zone_for(u.timeZone)`), Auto being the server's. | S12.11.5 (each user's zone); `operations.md` §2.3 is true for Auto users only. |
| DC-16 | The alert threshold is read from Settings each run (`settings.get(s, "alertSourceHours")`, `alerts.py:72, 168, 178, 383`). (The linked-key hour is unit 08's and 10's.) | S16.16 (a setting); R1.25's "48 hours" is its default. |
| DC-19 | `config.KEYS` accepts `[server] name, mode, host, port, trusted_proxies`, `[paths] data, backups, socket`, `[tls] cert, key, names`; any other key or section refuses the start, `[keys]` with its own reason (`config.py:72-134`). `name` goes into the self-signed certificate (CN and a SAN) and nothing else; `paths.socket` is named by no requirement either. `trusted_proxies` takes networks (U09-5); the health check ignores `host` (U09-22). | DC-19's remedy (list the keys in S13.3) would describe exactly these eleven. |
| D2-10 | `frame.js:36-51`: Alerts after Activity, then Users and Groups and Settings for admins. | The mockup's order, not S12.2's (which puts Alerts last). |
| D2-16 | A single upload over 100 MB is refused 429 *wait* (U09-23). | Neither: the refusal names the wrong cause. |
| DC-13 | The body limit is the larger of the import and receipt limits (`app.py:111-119`); each route then checks its own (`ui/receipts.py:319-323`). | DC-13's remedy's reading (two limits). |
| D3-9 | `/healthz` answers `{"status", "version"}` to any address (`app.py:169-189`; `AddressRanges` exempts it). | As the documents state; the question stays open. |
| D3-16 | `/healthz`: `ok`, `re-encrypting`, `starting`, `locked`, `uninitialised`; `moolakata health` prints the status and exits 0 for any answer. | S13.6. |
| DC-9 | Counters are in memory (`ratelimit.py`, unit 07's), as S13.7.5.5 says. | S13.7.5.5. |

## Earlier reviews' findings, re-checked

| Finding | State given | Found |
|---|---|---|
| K1 | done | holds: `ClientAddress` believes forwarded headers only from a trusted peer, walking right to left (`middleware.py:89-111`); host commands are on the socket, never the listener (S13.6). Ranges still accepted in `trusted_proxies` (**U09-5**). |
| K2 (headers) | done | holds: a route's own CSP is kept (`middleware.py:131-133`); unit 08 checked the linked file route. |
| K3, K18 (net) | done | hold: one guarded client, vetted address connected to with the name for SNI (`net.py:169-177`), pins checked after the handshake (`:151-161`), `verify` refused, no redirects, chunked answers capped. |
| K19 | m9 part 1 | half holds: `hide_parameters=True` (`store/db.py:78`); route problems logged by id, status and code (`errors.py:75-83`, tested); the middleware's refusals are not (**U09-8**). |
| K23 | m9 part 5 | as A14 says: while locked the ranges can't be read, so every address reaches the locked screen (`app.py:121-124`). |
| K25 | m9 parts 4–5 | holds: uploads parsed in memory (`app.py:154-158`, `spool_max_size` 128 MiB, above every limit that passes the 100 MB in flight); the alert event carries `{"count": 1}` (`alerts.py:901-903`); dev mode refuses outside a checkout or on `/var/lib/moolakata` (`main.py:53-64`). |
| B27 | done | holds: checks read in one transaction, only changes written (`alerts.py:832-904`); the sweeper doesn't trigger a run (`runtime.py:40-44`); a failing check leaves its kinds as they were, too broadly (**U09-13**). |
| B38 | m9 | holds: `Created` gives a 201 a `Location` that a GET route reads, or none (`middleware.py:439-509`); OpenAPI's version is `web/VERSION` (`app.py:159-161`, `paths.py:14-15`); tested (`test_conventions.py:134-177`). |
| B40 | done | holds: an unknown key or section refuses the start (`config.py:125-134`); tested. |
| N15 | done | holds: `options_expiring`, `pledges_due`, `key_rotation` (`alerts.py:387-406, 656-733`); tested. |
| N16 | m9 part 7 | half holds: codes written as literals and the handlers' are listed, 422s are problem documents; codes passed through a variable (links, copies, wallets, connector) and a peer's own codes are not (**U09-11**). |
| C11 | m9 part 5 | holds: `key.unlocked` counts as a check (`alerts.py:414-420`, `runtime.py` records it at every unlock). |
| C45 | m9 part 7 | holds as an alert (`alerts.py:489-525`; tested); unit 03's U03-11 (never marked stale on screen) stands beside it. |
| C52 | done | holds: a share request alerts the creator and the admins (`alerts.py:778-789`). |
| A7, A9–A11, A14, A16 | confirmed | hold as written. |

## The uncited first-level items and untraced code

- **S12.14** (the welcome and the locked screen) is built under S15's citations:
  `web/ui/screens/new-server.js` (Show my recovery phrase, I've written them down, three words
  asked, "check your sheet", Back), `screens/locked.js` (a masked field with the eye,
  `autocomplete="off" autocapitalize="none" autocorrect="off" spellcheck=false`, the host
  command line, re-encryption progress), `ui/welcome.py` (refuses once a keyring exists, also
  after the words are checked), `Locked` (`middleware.py:395-436`) serving only those routes.
- **S13.1** (one address and its paths) is built: `/` and `/ui` redirect to `/ui/`, `/demo`
  with its own CSP, `/ui/api`, `/link/v1`, `/connector/v1`, `/mcp`, `/healthz`
  (`static.py:139-161`, `app.py:169-281`).
- **Cites no section**: `ui/app/html.js` (HTM bound to Preact, S17.3), `ui/index.html` (the app's
  page and import map, S17.3), `ui/components/bits.js` (tabs, chips, avatars, tiles, loading,
  S12.1.3's shared components), `ui/screens/notfound.js` (the router's default, S12.1),
  `ui/charts/echarts.d.ts` (types for the chart wrapper, S17.4): each serves a requirement
  under other words; none is untraced.

## Checked and sound

- **Forwarded headers** (`middleware.py:73-111`): only from a trusted peer, the right-most
  untrusted hop, `-Proto` limited to http/https, `-Host` replacing `Host`; ignored in `tls`
  mode.
- **The Origin check** (`middleware.py:178-200`): every non-safe method under `/ui/`, a missing
  or foreign `Origin` refused 403, compared with the scheme and host the forwarded headers
  set; `/link`, `/connector` and `/mcp` don't take the cookie.
- **The session cookie** (`middleware.py:360-392`, `ui/deps.py`): `HttpOnly; Secure;
  SameSite=Strict; Path=/ui`, `Max-Age` the absolute lifetime, rotated at a change of
  privilege, the stream never touching the idle time.
- **The locked gate** (`middleware.py:395-436`): only the page, its files, `/healthz`, `/demo`,
  the unlock and the welcome's two routes; everything else 503 `locked` with `Retry-After`
  and `no-store`.
- **The egress guard** (`net.py`): host allow-list, every resolved address checked, loopback,
  link-local, metadata, unspecified, multicast and reserved refused unless named, IPv4-mapped
  IPv6 unwrapped, the vetted address connected to, TLS always verified or pinned by key
  after the handshake, no redirects, no environment proxies (a `transport` is given).
- **Errors** (`errors.py`): no traceback or SQL in a body; 500s logged with their id; field
  refusals mapped to `invalid-<type>`; malformed JSON 400.
- **Exact numbers** (`ui/conventions.py`, `app/dec.js`, `app/format.js`): floats refused in
  money, quantity and rate fields, places checked on what a request sends, `parseJson` reads
  every decimal as a `Dec`, `Dec` rounds half-even and throws on coercion, `money()` formats
  from digits.
- **The live stream** (`events.py`, `ui/stream.py`, `app/stream.js`): per-user and per-session
  delivery from any thread, a full queue ends the stream, four minutes and reconnect, session
  end checked off the loop, the alert event a count only, the update pill from `hello`'s
  version.
- **Alerts** (`alerts.py`): every cause S12.11.1 lists is built; one alert per cause key, its
  delay from when the cause began, an admin who owns what failed sees the owner's copy only
  (`recipients`, `visible`/`_owned`), dismiss per user, 90 days of resolved, emails once at
  opening, the summary once a day after its time in each user's zone, nothing sent without
  SMTP.
- **Jobs** (`jobs.py`): visible only to the user who started them, errors by type only.
- **The help pane and guides' Markdown** (`help.js`, `markdown.js`, `term.js`): everything built
  as elements from text (raw HTML shown as text), external links `noopener noreferrer`, terms'
  first use per heading a tab stop with its meaning as the description, Escape closes a card
  without closing a dialog; the focus follows to `f-<slug>` or `data-help` headings; every
  guide a test walks loads (`test_app.py:194-262`), and every image a guide names exists.
- **Dialogs** (`dialog.js`): the sidebar and page made `inert`, the help pane kept in reach,
  Tab round the dialog and the guide, Escape and a click on the scrim close, focus returned.
- **Config** (`config.py`): every unknown key or section refused, paths absolute, backups
  outside the data directory, `[keys]` refused with its reason, `MOOLAKATA_CONFIG` as TOML.
- **Durations** (`duration.py`, `duration.js`): the same grammar both sides, largest first,
  each unit once, refusals worded for the field (but U09-16).

## Read lightly or not read

- `web/ui/styles/components.css` (1,836 lines), `base.css`, `tokens.css`: searched for what
  the claims needed (privacy, reduced motion, the collapsed sidebar), not read line by line.
- `web/ui/charts/chart.js`: the `TimeChart` and the table view read; `BarChart`, `FlowChart`,
  `FanChart`, `ModelsChart` only for reduced motion, the table view and privacy.
- `web/ui/assets/*.svg`, `ui/charts/echarts.d.ts`: not read (data and types).
- `alerts.py`'s `cash_short` (U05-22's, unit 05) not judged again.
- The tests were read by their names and the ones claims lean on (`test_middleware.py`,
  `test_app.py`'s guide walk, `test_guides.py`, `test_conventions.py:162-176`).
- Help guides: `dashboard.md`, `alerts.md`, `settings-alerts.md` read whole; `terms.md` and
  `forms.md` by their tests; the others only listed for screenshots (U09-20).
- U09-1 in part, U09-6, U09-9, U09-10, U09-13, U09-14, U09-22 and U09-23 rest on
  reading.

## Work pad: severity, confirmations, status

| Id | Kind | Req | Sev | Conf | Status | Description |
|---|---|---|---|---|---|---|
| U09-1 | security | S13.7.6, S13.7.5.3 | Med | 0 | open | Withheld (`withheld.md`) |
| U09-2 | bug | S13.7.6 | Low | 0 | open | With the larger upload limit at 19 MB, uploads are never counted against the 100 MB in flight |
| U09-3 | differs | S13.7.7, S13.7.9 | Low | 0 | open | A refusal for an address outside Settings › Network carries no S13.7.7 headers and isn't logged |
| U09-4 | security | S13.5 | Med | 0 | open | Withheld (`withheld.md`) |
| U09-5 | security | S13.3 | Low | 0 | open | `trusted_proxies` takes whole networks, which S13.3 rules out |
| U09-6 | bug | S13.3, S13.6 | Low | 0 | open | The self-signed certificate is never remade at expiry, and a half-written pair is kept for good |
| U09-7 | differs | S13.5 | Low | 0 | open | This server's own certificate is probed over a raw socket, outside the egress guard |
| U09-8 | differs | S13.7.8 | Low | 0 | open | The middleware's refusals carry an error id that is never logged (K19 half holds) |
| U09-9 | differs | S13.8.4, S13.6 | Low | 0 | open | Between the unlock and readiness the API, `/link` and `/connector` are served, not 503 |
| U09-10 | bug | S13.4 | Low | 0 | open | Each price refresh starts its provider's rate limits afresh: two refreshes an hour double Tiingo's calls |
| U09-11 | differs | S13.8.3 | Low | 0 | open | The OpenAPI document omits codes passed through variables (links, copies, wallets, connector) and passes a peer's codes on (N16 half holds) |
| U09-12 | not built | S12.2.1 | Low | 0 | open | The Dashboard has no upcoming recurring transactions and no giving against its target |
| U09-13 | bug | S12.11.2 | Low | 0 | open | One failing check keeps every other check's *source failing* alerts from resolving |
| U09-14 | differs | S12.11.1.2, S1.9.4 | Low | 0 | open | The mismatch alert is raised for loans and always links to a Reconcile tab |
| U09-15 | differs | S12.11.1.1 | Low | 0 | open | An admin's alert about a Connection doesn't name its owner |
| U09-16 | bug | S12.13 | Low | 0 | open | A long duration (pausing a link for `1000000w`) answers 500 |
| U09-17 | not built | S12.2.12 | Low | 0 | open | The Watchlist is not built, and nothing schedules it |
| U09-18 | differs | S12.3 | Low | 0 | open | Privacy mode blurs only `.amt`; Projections, Taxes, Giving and rules show amounts in plain text |
| U09-19 | differs | S12.1.3, S12.8 | Low | 0 | open | Tooltips never reach screen readers: the collapsed sidebar's links have no name |
| U09-20 | test gap | S12.7.6, S12.7.4 | Low | 0 | open | No test checks a guide's screenshot; about forty screen guides have none |
| U09-21 | differs | S12.11.1, S16.16, S12.2.1 | Low | 0 | open | The Alerts, Settings › Alerts and Dashboard guides say less than the code |
| U09-22 | bug | S13.3, S13.6 | Low | 0 | open | The health check asks 127.0.0.1 whatever `[server] host` says |
| U09-23 | differs | S13.7.6, S16.8, D2-16 | Low | 0 | open | A statement over 100 MB is refused 429 *wait*, which can never succeed |

Scratch runs: `/home/dev/.claude/jobs/b8ac83ff/tmp/u09/` (`bomb.py`/`bomb.txt`, `upload.py`/
`upload.txt`, `mw.py`/`mw.txt`, `codes.py`/`codes.txt`).
