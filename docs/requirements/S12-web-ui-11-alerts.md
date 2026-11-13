# S12.11. Alerts

11. **Alerts** tell someone that something needs them. Activity records what happened; an
    alert asks for an action.
    1. **What raises one**:
       1. **for admins**: a source that has failed for longer than the threshold in Settings ›
          Alerts (48 hours by default): the bitcoin explorer or node, a price source, email
          that can't be sent, or a linked server's pulls (a pull refused for a clock more than
          a minute off says *the clocks disagree*, which NTP on one host fixes); a backup that
          failed; the bitcoin node presenting a certificate other than the one trusted
          (S1.6.2.4); a link's first share waiting for its access key (S11.9.2), and a link
          marked broken (S11.6); the MoolaKata Connector locked, not heard from for 15 minutes,
          or reporting from an address other than the one admins know, until one accepts it or
          unpairs (S18.5), and a Connection needing a sign-in or failing; the yearly check of
          the master key's recovery phrase (S15.6.5), due a year after the phrase last opened
          the keyring, by an unlock, **Verify key** or `keys verify`, or after the key was made,
          which opens Settings › Key storage's **Verify key**; the master
          key's rotation, due after the period Settings › Key storage sets (S15.8.4), which
          opens Key storage's **Rotate**; a break-glass code asked for on the host, for two
          days, so one nobody here asked for is noticed (S15.5.2); and the
          receipt reader running without its file sandbox, on a host that doesn't offer
          Landlock (S9.8.4.2). An admin's alert about someone else's account names its owner and source, never the
          account's name or figures (S10.2);
       2. **for an account's owner**: their wallet's explorer or node failing for longer than
          the threshold, an account whose next statement or import is overdue for its interval
          (S1.11.7), naming the statement missing, a reconciliation mismatch left open for 7
          days (S1.11), a Connection that keeps one of their accounts current needing a sign-in
          or failing (S18.5), a recorded wallet transaction the chain has dropped (S1.6.2.7),
          an option past its expiry that wasn't settled on its own (S3.6), asking what
          happened, and a holding still valued from a stale statement (S4.3) while the account's
          next statement isn't overdue;
       3. **for each user**: a request to share a private person they created, which goes to
          its creator and to the admins (S10.10.3), an occasion entering its lead time
          (S7.7.3), an option expiring within a week, a pledge due (S7.9), an active projection
          falling behind (S6.7.5), and the active budget's cash before payday (S7.6).
    2. **One alert per cause.** The alerts task looks at every cause every 15 minutes, and at
       once after any other background task ends but the linked copies' sweeper, reading in one
       transaction and writing only what changed. A failing source raises one alert, not one
       per attempt, and a check that fails leaves its alerts as they were. It stays **open**
       while the cause lasts and is **resolved** by itself when the cause clears (the source
       answers again). A cause raised for admins and for the owner of what failed (a
       Connection, the wallets' explorer or node) reaches an admin who is that owner once, as
       the owner's alert, on screen and by email. A user can **dismiss** an open alert for
       themselves. Resolved alerts stay listed for 90 days.
    3. **The Alerts screen** lists open alerts first, newest first, then resolved ones. Each
       shows what it is about, since when, a link to the place to fix it, and **Dismiss**.
       Opening the screen marks the user's alerts as seen.
    4. **The badge** on the Alerts entry counts the open alerts the user has not seen. A new
       alert reaches the badge through the live stream (S12.6) without a reload, with a toast.
    5. **Emails**: each user chooses in Profile how alerts reach them by email:
       1. **each alert**: one email when an alert opens (not when it repeats or resolves);
       2. **daily summary**: one email a day at the time set in Settings › Alerts (07:00 by
          default, in each user's time zone, S14.9) listing the alerts opened since the last one, and none on a day without
          any;
       3. **none**: on screen only.

       Admins start on *each alert*, other users on *daily summary*. Without SMTP set up, the
       choice is shown but nothing is sent. Alert emails name the kind and the thing it is
       about, never amounts.
