# S13. Architecture

1. One HTTPS address. `/` redirects to `/ui`. `/ui/*` serves the app and `/ui/api/*` its API.
   `/link/*` is the linked-server API (S11). `/connector/v1/*` is where the paired
   MoolaKata Connector posts its reports and files (S18.4.3). `/mcp` is the read-only
   endpoint for agents (S10.9). `/healthz` is the health check. `/demo` serves the clickable mockup (S12.9) to
   anyone, without signing in: it holds only sample data, runs in a sandbox with an opaque
   origin, and can reach neither the app's cookie nor its API.
2. **Authentication**: server-side sessions for `/ui/api` (a random token stored hashed, in an
   HttpOnly, Secure, SameSite=Strict cookie, with an `Origin` check on every change; idle and
   absolute lifetimes are Settings). Signed peer requests for `/link` (S11.1), and the paired
   connector's signed requests for `/connector` (S18.4.3). None is accepted on another's
   path; `/mcp` takes only its access tokens (S10.9).
3. **Port 37373**, on all of the container's interfaces; the host's port mapping and firewall
   decide what reaches it. **Two listener modes**, one switch in `moolakata.toml`: **`proxy`**,
   plain HTTP behind haproxy, Caddy or nginx, which ends TLS (forwarded headers are trusted
   only from the configured proxy addresses, each the proxy's own address and never a whole
   private range, since anything else in it could pose as the proxy); or **`tls`**, its own
   HTTPS listener with HTTP/2 (forwarded headers ignored). **`proxy`** is the expected setup.
   **`tls`** is for testing on a local network: given no certificate, the server makes a
   self-signed one on first start and keeps it in the data directory (`tls/`, the key mode
   0600). The pair is not encrypted: it protects the listener, not the data, and the listener
   must read it before any key is entered (S15.1.7). It names the server and `localhost`, and
   the names and addresses listed in `[tls] names`, which are how browsers on the network reach
   it; a change to the list makes it again. A certificate named in `[tls]` lives wherever the
   admin keeps it. From a trusted proxy, `X-Forwarded-For`, `X-Forwarded-Proto` and
   `X-Forwarded-Host` are believed, and the client is the right-most address in
   `X-Forwarded-For` that is not a trusted proxy. `[server] host` sets the listening address,
   all interfaces by default.
4. **Background tasks** in the server process: price refresh (S4.4), bitcoin wallet reads
   (S1.6), link pulls (S11.4), option expiry (S3.6), backups (S14.6), sending email (S16.2),
   alerts and their daily summary (S12.11), receipt and statement reading (S9.8, S1.3, in its
   own worker process), the linked copies' sweeper (S11.9.4), and the check for statements
   overdue (S1.11.7) and a silent connector (S18.5), the events host commands queue, taken
   every few minutes (S15.4.7), and an hourly prune that removes expired sessions and one-time
   tokens (`schema.md` §4.4.1). Recurring transactions are found when they are shown (S7.5).
   Each records its last run and error, which Settings shows. They run in a thread pool with
   per-provider rate limits and never block a request.
5. **Outbound calls** go through one httpx client with an **egress guard**: only the hosts of
   enabled price sources, the bitcoin explorer or node, the SMTP server, and links; never
   loopback, link-local or cloud metadata addresses unless an admin allows one by name, and the
   only hosts allowed by name are the Email and Bitcoin hosts an admin types in Settings: a
   link's address, which another server supplies, never is; with timeouts and response-size
   ceilings. Each call connects to the address the guard checked, never to a second lookup, so
   a name can't change its answer between the check and the connection. Email goes through the
   standard library's SMTP client, past the same guard; its host is one an admin named in
   Settings › Email, so it counts as allowed by name. The guard sees only the server's own
   clients, not a library's own client or native code, so every dependency is audited for what
   it could reach on its own, each time a dependency changes (S17.2.1), and any switch that
   turns such a call off is thrown before the library is first used. Each call connects within
   10 seconds and waits at most 20 seconds for each read, and every answer is cut off past 20
   MB, whether or not it announces its length. SMTP waits 20 seconds.
6. **Stopping**: on SIGTERM the server ends every event stream, lets requests in flight finish
   for up to 5 seconds, and stops; a second signal stops at once. **A refused start**: when it
   cannot start for a reason only an operator can fix (a config file it can't use or with a key
   it doesn't know, a keyring it can't read, a certificate it can't load, a data directory
   another server is using), it says why in one `refusing to start:` line and exits 78
   (`EX_CONFIG`). The example compose files restart it unless it was stopped
   (`unless-stopped`), so it comes back after every reboot, locked: a server stopped by a
   shutdown stopped cleanly, and a policy of restarting only on failure would leave it down. A
   refused start is retried with Docker's back-off, which reaches once a minute, each try
   saying why in its one line, until an operator fixes the cause or stops it. **An
   uninitialised start**: with no keyring, the server comes up **uninitialised**: `/healthz`
   answers 503 `uninitialised`, `/ui` serves only the welcome (S12.14.1) and the routes it
   calls, and every other path answers 503, until the key is made (S15.4.4). **A locked
   start**: with no key anywhere (S15.4), the server comes up **locked**: `/healthz` answers
   503 `locked`, `/ui` serves only the locked screen, and every other path, `/link`,
   `/connector` and `/mcp` included, answers 503 `locked` with `Retry-After`, until an admin
   enters the recovery phrase (S15.4.3). What the phrase then cannot open (a database from a
   newer release) is refused at the unlock, with the reason in the log, and the server stays
   locked. `/healthz` answers 503 `re-encrypting` while a re-encryption runs at the unlock
   (S15.7.2) and `starting` between the unlock and readiness, and `GET /ui/api/unlock` tells
   anyone who reaches `/ui` whether the server is uninitialised or locked, the fingerprint its
   keyring is wrapped under, the version, and, once unlocked, whether the first admin is still
   to be set up (S10.1.2). The image's own health check asks only whether the server answers:
   ready, starting, re-encrypting, locked or uninitialised, it is alive, so an orchestrator
   that waits for healthy containers (TrueNAS's catalog among them) lets it wait for its
   phrase; whether it is ready is `/healthz`'s answer, for an uptime monitor. **Host commands**
   (`keys unlock`, `keys rotate`, `db backup`, S15.4.7) reach the running server over its Unix
   socket, `/run/moolakata/sock`, in a 0700 directory of the server's account on a tmpfs
   (`web/.dev/` in dev mode), never over the listener.
7. **Security policies**. One place for the rules every request
   passes through; other sections refer here.
   1. **Sessions**: a 256-bit random token in a cookie named `mk_session`, `HttpOnly`,
      `Secure`, `SameSite=Strict`, `Path=/ui`, stored as its SHA-256. A new token at sign-in
      and at every change of privilege (two-step passed, made admin), so a token from before
      sign-in never works after it. Idle lifetime 8 hours and absolute 30 days by default
      (Settings › Sign-in and sessions). Signing out, a password change and deactivation end
      every session of that user at once. The cookie's `Max-Age` is the absolute lifetime, so
      a browser restart keeps the session. After a password change, the browser that made it
      gets a new session; accepting an invitation signs in, and a reset does not. The new
      token at a change of privilege starts its own absolute lifetime.
   2. **Re-authentication**: changing the password, the email address or two-step, making an
      access token, creating a linked copy's access key, resetting a linked copy, sharing with
      a linked server, pairing, confirming or unpairing the connector, sealing a Connection's
      credentials or changing its server's address, setting a secret in Settings (the SMTP
      password, the node's password, a price source's key), changing the SMTP host or the
      public URL, changing Settings › Network, changing who is in Admins, re-encrypting,
      removing a copy (which also asks for the phrase, S16.13) or forgetting a previous key,
      pruning files, removing orphan files, and opening a written email each need the password
      again if it was last given more than 10 minutes ago.
   3. **Passwords**: argon2id (64 MiB, 3 passes, parallelism 1), the minimum length of
      S16.5, at most 1,024 characters, and no other rules. Checked against a shipped list of
      the 100,000 most common passwords, which are refused.
   4. **Cross-site requests**: `SameSite=Strict` plus an `Origin` check on every request
      that changes something; a missing or foreign `Origin` is refused with 403. No CORS: the
      API answers only its own origin.
   5. **Rate limits**, per client address and per user, answered with 429 and a
      `Retry-After`:
      1. sign-in, two-step codes, re-authentication, the current-password check, a reactivation
         request and the unlock (S15.4.3): 10 failures in 15 minutes lock **the address they
         came from** for 15 minutes, whoever they named, and so do 10 password-reset requests;
         an IPv6 address counts by its /64; a username that keeps failing, from anywhere, is
         only slowed (half a second per failure past the third, up to five), never locked, so
         nobody can lock an admin out from afar (S10.1);
      2. linked copies' access keys: S11.9.3.3;
      3. the API: 600 requests a minute per session; uploads: 60 files an hour per user;
      4. `/mcp`: 60 calls a minute per token (S10.9.4); `/link`: 60 calls a minute per link,
         and calls not yet signed by a known key 60 a minute per address, checked before a body
         is read; `/connector`: 60 calls a minute, its files counted against the upload limit
         above.
      5. The counters are held in memory: a restart clears them.
   6. **Request limits**: JSON bodies up to 1 MB (a linked server's up to 20 MB,
      `docs/link-protocol.md` §1.4), uploads up to the size in Settings (25 MB by default), a
      receipt a linked server delivers up to the largest receipt Settings allows, sealed (link
      protocol §1.4), at most 100 MB of uploads in flight per user (never less than that
      largest sealed receipt), and request headers up to 16 KB. Each upload's
      type is checked from its content, never its name (S9.1), and an upload is held in memory,
      never spooled to a temporary file. An import waiting for its mapping or its check (S1.3)
      counts against its user's uploads in flight while it waits: past them, the user's
      oldest waiting upload is let go, and its dialog asks for the file again. Closing the
      dialog lets its upload go at once.
   7. **Response headers** on every response, refusals included: the CSP of S17.3.3,
      `X-Content-Type-Options: nosniff`, `Referrer-Policy: no-referrer`,
      `Cross-Origin-Opener-Policy: same-origin`, `Cross-Origin-Resource-Policy: same-origin`,
      `Permissions-Policy` denying camera, microphone, geolocation and payment, and
      `frame-ancestors 'none'`. In `tls` mode, `Strict-Transport-Security` for a year. Receipt
      and statement files, a linked household's among them, are served with
      `Content-Disposition`, their checked type, and a `sandbox` CSP, so a PDF can't run script
      in the app's origin. `/demo` has a CSP of its own: `sandbox allow-scripts allow-popups`,
      inline script and style allowed (the mockup is one file), and `connect-src 'none'`.
   8. **Errors** never include a stack trace, a SQL statement, a path on the host or a secret.
      Each error carries an id that is also in the log, with its status and code, refusals
      included, so an admin can find the detail.
   9. **Logging**: no amounts, names of accounts or payees, secrets, tokens or passwords; user
      ids, record ids, routes and outcomes only (R3.8). Sign-ins, failures, lockouts and every
      admin action are logged and recorded in Activity. Statement logging (SQLAlchemy's echo, a
      slow-query log) is never turned on: the database key travels in the `PRAGMA key`
      statement, and a logged statement would hold it. The engines hide statement parameters
      from their errors, so a failed write logs no value, and a linked server's own message is
      kept in the log, never copied into an alert or an email.
   10. **TLS** (in `tls` mode): TLS 1.2 and 1.3 only, with the server's default modern cipher
       suites; HTTP/2.
   11. **Supply chain**: Python dependencies pinned with hashes in `uv.lock`; the image built
       from a base pinned by digest, which moves with each release and between releases when
       Debian or Python publishes a fix for something the image uses (S17.8.5), since the
       same digest always gives the same packages. Browser libraries are vendored
       (S17.3.1) and adopted only through one gate, which is what stands against a
       compromised release upstream: a version is taken only after a 14-day cooldown (most
       malicious releases are found and pulled within days), its download must match the
       registry's integrity hash, its provenance must verify where the package publishes it
       (and a package that published it before may not stop), and the diff of the files the
       browser loads is reviewed before the commit. The hash kept in `manifest.json` records
       exactly what was adopted and refuses a tarball changed afterwards; it does not judge a
       release.
8. **API conventions**, for `/ui/api` and, where they apply, `/mcp`.
   The OpenAPI document is generated from the routes (R3.9); `docs/api.md` says how to use
   `/ui/api` and `/mcp`.
   1. **Resources and methods**: plural nouns (`/ui/api/accounts`, `/ui/api/accounts/{id}`).
      `GET` reads. Records are made, changed and deleted through one route, the save
      (S13.8.11): a kind of record it takes has only its reads and its actions, an action
      that is not a change of fields being a `POST` to a verb under the resource
      (`/ui/api/links/{id}/pull`). A `POST` makes something of its own only where no
      record's draft can: an upload (a receipt, a statement), signing in and the first
      start's steps, pairing a linked server or the connector. The app is the API's only
      caller.
      1. **`DELETE`** soft-deletes (`schema.md` §4) and answers 200 with
         `{deleted, parent}`: `deleted` is what went (its id, or a pair's two keys joined by
         a slash, its `deletedAt` and its version), and `parent` is what it belonged to as it
         now stands (an item, when one of its valuations goes), or `null` for a record that
         belongs to nothing. A client may ignore `parent`. Signing out (`DELETE
         /ui/api/session`) answers 204.
   2. **Names and values in JSON**: field names camelCase, as in the database (`schema.md`
      §1). Ids are the prefixed strings of `schema.md` §2. Dates are `YYYY-MM-DD`; timestamps
      are RFC 3339 in UTC (`2026-10-12T14:05:00Z`, S14.9). A field with no value is `null`,
      never left out.
      1. **Numbers are exact JSON numbers.** Money (`1234.50`, two places), quantities and
         prices (to their own scale, S14.3) and the ratios the server works out (a percentage,
         a rate, years) are number literals written with their own digits and always a
         decimal point, so `10` shares is `10.0`; a whole number with no decimal point (a
         count, a year, a version, an amount of bitcoin in sats, S1.6.4) is an integer. The
         server never writes a binary float.
      2. **Each is declared** in the OpenAPI document as `"type": "number"` with
         `"format": "money"` or `"decimal"`, and the browser's types (S17.3) mark it as an
         exact decimal.
      3. **One edge on each side.** The server writes and reads JSON only through its exact
         encoder (`moolakata/exactjson.py`): the API's responses, the live stream, MCP and
         `/link`. The browser reads it only through `parseJson`, which makes every number with a
         decimal point an exact decimal (S12.12).
      4. **Requests** send amounts the same way, as exact numbers. A decimal string, as a form
         field gives it, is accepted too; more places than a field allows is refused.
   3. **Errors** are `application/problem+json` (RFC 9457): `type`, `title`, `status`,
      `detail`, the error id of S13.7.8, and `errors`, a list of `{field, code, message}` so
      the UI shows each refusal at its field (R3.7); a save's errors also name the record
      (`id`, S13.8.11). Codes are stable strings
      (`key-too-short`, `share-not-allowed`), listed in the OpenAPI document.
   4. **Status codes**: 200, 201 with `Location` (where the record made is read: its own path
      where it has one, otherwise the list or the record that holds it; a 201 whose record
      nothing reads names none), 202 for work that continues (S13.8.7),
      204 for signing out and changes that answer nothing, 400 for a malformed request, 401
      when not signed in, 403 when not allowed, 404 for what doesn't exist *or* isn't visible
      to the caller (never revealing which), 409 for a conflict, 412 for a stale version, 413,
      415, 422 for a valid request that breaks a rule, 428 for a change sent without its
      version, 429, and 503 while the server is starting or a linked copy is locked.
   5. **Lists**: every list takes `?offset=` (0 by default) and `?limit=` (500 by default, at
      most 1000; the app's pages are 100, 500 or 1000 rows, S12.1.3) and answers
      `{items, total, offset, limit}`: the page's rows, how many the caller can see in all
      (so a pager shows "1–500 of 2,624" and jumps to a page), and where the page starts.
      Sorting with `?sort=field` or `-field` on the fields each list declares; filters as
      named query parameters. A list a screen never pages (a household's accounts) is read
      the same way, its `items` taken whole. Rows that arrive while someone reads a long list
      are counted on its "+N new" pill and added to the offset of later pages, so the pages
      don't shift (S12.1.3).
   6. **Versions**: each record has a `version` that goes up with every save. A change or a
      delete through the save names it with each op (S13.8.11); a `DELETE` of a record with
      a version sends the version it was made against in `If-Match`:
      1. without it, the change is refused with 428 `version-required`;
      2. with a stale one, it is refused with 412 `stale-version`, carrying the record as it is
         now (`current`) and its `version`, for a caller that starts again from it; the
         browser's dialogs reload (S12.15.5);
      3. with the current one, it is applied and the version goes up.

      Pure relations, two keys and nothing of their own (a user in a group), have no
      version. A secret (a password, a price source's key) is
      written with the record it belongs to, a setting's among them, and never read back. A
      test walks every route and fails when a change skips its version or a `DELETE` answers
      another shape.
   7. **Long work** (an import, a statement read, a projection run, a reset copy) answers
      202 with a job resource (`/ui/api/jobs/{id}`: state, progress, result), and the live
      stream announces its end (S12.6).
   8. **Idempotency**: the save (S13.8.11) may carry `Idempotency-Key`; a repeat within 24
      hours returns the first answer. Imports are idempotent by their content (S1.3).
   9. **Versioning**: `/ui/api` is served with the app and changes with it, so it carries no
      version; the OpenAPI document states the release. `/link` is versioned in its protocol
      (`docs/link-protocol.md`), `/connector` by its path (`/connector/v1/`), and `/mcp` by
      the protocol version the client and server agree on.
   10. **Visibility**: every read goes through the caller's shares (S10.3) and the soft-delete
       views (`schema.md` §4.2). A list never counts or hints at what the caller can't see.
   11. **The save** (`POST /ui/api/save`): a form's draft (S12.15) in one request,
       applied in one database transaction or not at all.
       1. **The request** is `{ops, confirm}`. Each op is `{op, entity, id, version, fields}`:
          `op` is `create`, `update` or `delete`; `entity` the record's prefix (`schema.md`
          §3); `version` the one the record was read at, for an update or a delete (S13.8.6);
          `fields`, for a create, every field, and for an update only those changed, put onto
          the record as it is before the whole record is checked. A set of pairs (a gift's
          people, a transaction's tags) is sent on the record that holds it as
          `{add, remove}`. A save holds at most 1000 ops, within the request limit of
          S13.7.6.
       2. **Ids.** A create names its record's id, made in the browser (`schema.md` §2). An
          id of the wrong prefix or form, one whose time is more than a day from the server's
          clock ("this computer's clock is off by more than a day"), or one already taken is
          refused at its field with 422. Every other id a save names is checked against the
          prefix of what it refers to, refused the same way.
       3. **Applying.** Creates come first, then updates, then deletes, with foreign keys
          checked at the commit, so the order of the ops can't break a reference. Each op is
          checked by its kind: shares (S10.3), rules, versions.
          Deleting a record deletes what is deleted with it (`schema.md` §4).
       4. **Refusals.** Every op is checked and every refusal gathered before the transaction
          rolls back, each error naming its record's `id` beside its `field`, `code` and
          `message` (S13.8.3). A stale version anywhere refuses the whole save with 412
          `stale-version`, listing each stale record as it stands.
       5. **Questions.** A change that asks first (`reconciled-period`, `closed-year`,
          `reserve-balance`, `occasion-gifts`) is gathered with the others; the save rolls
          back and answers 409 `confirm-needed`, listing each question's `code`, record `id`
          and message. Sent
          again with `confirm` (a list of `{code, id}`), it goes ahead only when every
          question it raises is in that list.
       6. **After the commit**, the live stream's events (S12.6), alerts and the work that
          follows a change run once for the whole save, and Activity records each change.
       7. **The answer** is 200 with each record the save touched: its id, its new version
          and the record as read, or, for a delete, what went (S13.8.1.1).
