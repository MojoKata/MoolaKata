# S12. Web UI

1. **Frame**: drawn once around every signed-in screen, from one list of navigation entries;
   no screen draws or changes it.
   1. A **sidebar** pinned to the viewport: the household's avatar and name with the version
      (and a red **DEV** pill in dev mode), the navigation with count badges, and at its
      foot the signed-in user's
      tile with the **theme** button (crescent moon for dark, lightbulb for light, palette
      for the system's; a click moves to the next). A round button on its edge collapses it
      to icons and opens it again; the browser remembers which.
   2. The **help pane** on the right (S12.7), and a **toast** area for confirmations.
   3. Shared components: one popup menu (closes on choosing, Escape, or a click or focus
      outside), dialogs, styled tooltips that also show on keyboard focus and reach screen
      readers, and a **pager** for long lists (Transactions, Activity): a page size of 100,
      500 or 1000 kept per browser, the rows shown out of the list's total ("1–500 of 2,624")
      with a jump to its pages (S13.8.5), and rows that arrive while reading counted on an
      orange **+N new** pill instead of shifting the page. Every password field (a password,
      an API key, the SMTP or node password) carries an **eye** button at its right end that
      shows what was typed and hides it again (the eye struck through while shown), labelled
      for screen readers. A **dialog** masks the content, not the guide: the sidebar and the
      page are dimmed and out of reach, for the pointer, the keyboard and screen readers,
      while the help pane beside it shows the dialog's guide and stays in reach, its links and
      terms working. The dialog is centred over the content; Tab goes round its fields and
      then the guide's, Escape or a click on the dimmed content closes it (unless it holds
      changes not saved, S12.15.6), and focus returns to where it was.
   4. An orange **update** pill under the brand when the server was upgraded since the page
      loaded; a click reloads.
2. **Navigation** (in this order):
   1. **Dashboard**: net worth and its change (day, month, year), the net-worth chart,
      allocation, accounts by group with balances, the active budget's month (S7.12), upcoming recurring
      transactions, occasions inside their reminder time (S7.7.3), giving against its
      target, the **Plans** card of active projections (S6.8), and stale prices, stale
      valuations, or sources and imports that need attention;
   2. **Accounts**: every account the user owns or holds a share of, grouped (Banking,
      Investing, Retirement, Education, Crypto, Giving, Liabilities, Physical assets), each with its type icon,
      institution, balance, change, when it was last updated, and sharing marks. **New account** offers a
      type picker, then the account form. An **account page** has the tabs *Overview*
      (balance chart), *Holdings* (investing only), *Transactions*, *Positions* (investing
      only), *Receipts*, *Reconcile* (banking, card, brokerage and loan accounts, S1.11),
      *Sharing* and *Settings* (how it is kept current, lot method, import mappings).
      Some types add tabs: a loan *Schedule* and *Payoff* (S1.9, S6.10); a 529
      *Contributions*, *Withdrawals* and *Goal* (S1.8); a physical-asset account *Items*
      (S1.10);
   3. **Transactions**, with the tabs *Transactions* and *Rules*:
      1. *Transactions* (`/ui/transactions`): every account's transactions together, filtered
         by account, category, date, amount, payee and tag, with bulk categorise, split,
         attach receipt, and **Import**; `?category=<id>` opens it filtered to a category. The
         amount's **At least** and **At most** bound its size, whichever way the money went:
         each is an amount, zero or more, *any* while blank, and *At most* under *At least* is
         marked (S12.18.3) and leaves the list as it was. A
         transaction's dialog marks it reimbursable (S2.9), and its **In budgets** line names
         each budget counting it, what it counts as there, and that budget's **Leave out**
         switch (S7.3.5).
      2. *Rules* (`/ui/transactions/rules`): the user's categorisation rules (S2.7), in two
         parts. On the left, **Add rule**, and beside it, while any transaction in the
         accounts the user can change is uncategorised, **Apply to N uncategorised**, which
         runs the saved rules (S2.7.4); under them the rules in order, each with its number,
         its conditions, what it sets, and **↑** and **↓**. On the right, the rule chosen
         (`/ui/transactions/rules/<id>`): its fields, which edit a draft (S12.15), and
         **Delete**; with none chosen, a line saying to choose a rule or add one.
         1. **Discard** and **Save** show while the rule holds changes, and go when it is put
            back as it was (S12.15.1). **Discard** puts it back; **Save** saves it.
         2. **Add rule** puts a new rule at the end of the list, chosen, its fields as a new
            rule has them, with **Discard** and **Save** showing; **Discard** takes it out of
            the list. Saved, it takes its own address.
         3. **Leaving a rule with changes**: choosing another rule, **Add rule**, the other
            tab, moving elsewhere in the app or the browser's Back asks first (S12.15.6).
         4. While the rule chosen holds changes, what acts on the saved rules (**↑**, **↓**,
            **Apply to N uncategorised**) is disabled, its tooltip saying *Save changes
            first*;
   4. **Portfolios**: the user's portfolios and those shared with them; a portfolio page with
      the charts of S5.2, its holdings, and its *Projections*;
   5. **Positions**: open and closed positions across accounts, with stocks, options and
      crypto as filters, and P/L per S3.9. **Record trade** opens the trade dialog, which has
      an option leg builder;
   6. **Budgets**: the list of budgets, the active one first and then the scenarios, with
      **New budget** (its method and options, and **Estimate from history**, S7.1); for one
      budget, the month view with its reserves and moves (`?month=YYYY-MM` in its address
      opens a month), **Where the money is**, the
      month's review, **Compare**, cash flow, trends, **Awaiting reimbursement**, recurring
      transactions and rules (S7.4). Beside the list, **Categories**: the household's tree,
      each with its kind, tax tag and who added it, with **Add a category**, and for each
      **Edit** (its name, parent, kind and tax tag; what the reader may not change shown
      locked, with why), **Delete** and **Merge** as S7.2.3 and S7.2.4 allow. A category
      in use says in its dialog how many of its uses the reader can see and how many they
      can't (*47 uses you can see, and 22 you can't*; a transaction counts once, whatever
      its parts), and the refused delete says the same; **Find them**, while there are any
      the reader can see, closes the dialog (asking first if it holds changes, S12.15.6)
      and starts the *Find uses* tour (S12.17.6). Every list
      of categories to choose from (a transaction's and its parts', bulk categorise, a
      rule's, a plan line's, a loan's) ends with **New category…**, which opens **New
      category** over the dialog (S12.15.7) and chooses the one it makes;
   7. **Projections**: active projections first, with their tracking, then the scenarios;
      each with its inputs and the fan chart (S6);
   8. **Gifts**: *Upcoming* occasions, *People*, *Gifts* (ideas to given, and received), and
      *Spending* by person, occasion and year (S7.7, S7.8);
   9. **Giving**: the year's target and progress, donations, organisations and the DAF
      (S7.9);
   10. **Taxes**: the tax-book picker (year and filers), **New tax book** and **Share**, then
       the panels of S8, with *Filings* and *Documents* (received and filed, S8.14–S8.17);
   11. **Receipts**: the inbox and every receipt, with a grid or list view and upload;
   12. **Watchlist** *(small)*: instruments the user follows without holding them;
   13. **Activity**: the changes of S10.8, newest first, filtered by account and person;
   14. **Users and Groups**, **Settings** (admins);
   15. **Alerts**: what needs the user's attention, with a live count on its badge (S12.11);
   16. the user tile opens **Profile** (name, sex, birthday, relationships (S10.10), email,
       avatar, password, two-step, alert emails, time zone (S14.9), assumptions for
       projections (S6.3), access tokens) and **Sign out**.
3. **Privacy mode**: a button in the header (an eye) blurs every amount on the page until
   clicked again, for using the app with someone looking over your shoulder. The browser
   remembers it.
4. **Numbers**: tabular figures, right-aligned, with the dollar sign. Gains are green and
   losses red, *and* signed with + or −, so colour is never the only cue. Large values are
   abbreviated in charts only ($1.2M), never in tables.
5. **Every value derived from a price** shows its age on hover, and the header shows the last
   price refresh with a dot that turns amber when prices are stale (S4.7).
6. **Live updates**: the frame keeps one Server-Sent Events stream open (`GET /ui/api/events`).
   It carries fingerprints and counts, never data: prices refreshed, an import finished, a
   statement read, a share received or removed, the categories changed, a linked pull done, a
   background task finished (a backup, a re-encryption), a sign-up request (for admins), a new
   alert (its count, never its title), the badges' counts (Alerts among them), a save, bulk
   categorise or rules applied (to the user who made it, so their other pages read again), and
   the server's version. A screen whose data changed reloads it through its usual routes. The stream never
   extends the session, ends after a few minutes (the browser reconnects), and takes the page
   to sign-in or *account is disabled* when the session ends.
7. **Help pane**, on every screen:
   1. **F1** toggles it. While it is closed, a dim quarter-circle with a question mark sits in
      the page's top right corner, and grows into a green circle on hover ("Show help (F1)").
      The pane sits at the right edge; the split drags (up to half the window) and moves with
      the arrow keys. The browser remembers whether it is open and how wide.
   2. **The guides** are Markdown files shipped with the app: `web/ui/guides/<screen>.md`, and
      `<screen>-<panel>.md` for a screen's tabs or sections. **Per-account-type** parts
      (`guides/account-<type>.md`) are placed into the account page's guides by marker lines
      (`{{account-type settings}}`), and each price source has its own part for Settings ›
      Prices.
   3. **It follows the page.** As focus moves to a field, the pane scrolls smoothly to that
      field's heading and highlights it for a moment. That heading stays marked as the
      **active topic** (extra bold, underlined, with a solid ▶ to its left) until focus moves
      to another field with a heading of its own. A field is matched to a `##` heading by
      its label turned into an id ("Lot method" → `lot-method`), or to an id the heading lists
      (`## Lot method {#lots}`). Guides keep the page's order, so moving down the page never
      moves the guide up.
   4. **What a guide holds**: a short paragraph on what the screen is for, a screenshot, and a
      heading for every field, switch and button (what it is for, what to enter, its default),
      with examples for anything typed in a language of its own (rules, patterns, mappings).
      Finance terms (cost basis, wash sale, RMD, TWR and IRR) get a short plain-language
      explanation in the guide of the screen where they appear. The Markdown is a subset:
      headings, paragraphs, lists, tables, code, quotes (shown as notes), images, links, bold,
      italic; raw HTML is shown as text.
   5. **Screenshots** come from the clickable mockup (`web/dev.sh help-shots`, dark theme,
      1280 px, PNG quantized to 256 colours) and are committed.
   6. **Checks**: a test fails when a screen has no guide, a guide's screenshot is missing,
      a field's label finds no heading, the next field down the page sends the guide up, a
      guide uses an acronym the terms (S12.7.7) don't explain, or it names a form the forms
      (S12.7.8) don't list. Tickers and banks in examples and words everyone knows (PDF, URL)
      are listed as plain; a listed form's name (1099-DIV) is no acronym.
   7. **Terms**: an acronym in a guide (AGI, OFX, HELOC), or its plural, never in code or a
      link. Its first use under each heading has a dashed underline and is a tab stop; later
      uses under the same heading look like the text around them until hovered, when they show
      the same underline. On hover, or keyboard focus of a first use, a card shows the acronym,
      what it stands for, and a sentence or two on what it means. Where an official document
      defines it (an IRS publication, a CFPB answer, an RFC), an external-link icon at the
      right of the card's title row links to it: a plain link, opened in a new tab, that can be
      right-clicked or opened in a tab of one's choosing, and named for screen readers by the
      document. The card shows below the term, or above it when there's no room below, and
      stays open while the pointer or focus is on the term or the card, so the pointer and Tab
      both reach the link; leaving both or Escape closes it. It moves with the term as the
      guide scrolls, and closes when the term scrolls out of sight. Screen readers read what a
      first use stands for after it, and its explanation as its description. The terms are one
      Markdown file, `guides/terms.md`: a heading per acronym and what it stands for
      (`## AGI: Adjusted Gross Income`), the explanation under it, and the document as a last
      line that is only a link, in alphabetical order. The hand-written mockup carries the same
      terms, and a test keeps the two alike.
   8. **Forms**: an IRS form a guide names, never in code or a link, is marked as a term is
      (S12.7.7): "Form 8949" and "Schedule D" in full, and "1099-DIV" or "W-2" alone too,
      since they can be nothing else; a bare number ("8949") is never taken for a form. Its
      card shows the form, its title, a sentence or two on what it is for, and the
      external-link icon to the form's page on irs.gov ("About Form 1099-DIV"). The forms are
      one Markdown file, `guides/forms.md`, laid out as the terms are
      (`## Form 8949: Sales and Other Dispositions of Capital Assets`), in alphabetical order.
      The hand-written mockup carries the same forms, and a test keeps the two alike.
8. **Accessibility**: everything works by keyboard, every control is labelled, contrast
   meets WCAG AA, and `prefers-reduced-motion` turns transitions off. Dark theme first, with
   light and system. **Desktop browsers only**: phone layouts are not built or tested, since
   phones will get a separate PWA with a narrower, focused set of features. English only,
   no i18n layer. Charts have a **table view** toggle (a screen reader reads the numbers) and
   honour `prefers-reduced-motion`.
9. **The clickable mockup**: one HTML file that opens from disk and sends nothing anywhere,
   showing every screen and dialog on sample data. Its purple **MOCK** pill (where the DEV
   pill goes) jumps to any screen, switches users, opens dialogs and changes state (prices
   stale, privacy mode). There are two files while the app is being built:
   1. **`docs/mockups/MoolaKata-mock.html`**, hand-written: the design reference for every
      screen. A change to what users see updates it in the same change.
   2. **`docs/mockups/MoolaKata-app.html`**, generated: `web/ui/mockup/build.py` inlines the
      app and an in-page fake backend, for the screens built so far, the linked household
      window among them (recorded from a seeded peer with its copy unlocked), and `web/check`
      fails while it is out of date. It records each sample user in turn, as each signs in
      (what one sees can show who has signed in so far): several browsers in that user's
      session open the screens, tabs, ranges and dialogs at once, and each answer is asked of
      the server once and kept as one browser opening them all in order would keep it.

   When the generated file covers every screen, it replaces the hand-written one and takes
   its name. `docs/mockups/check.py` opens every screen, tab, Settings section and dialog of
   the hand-written mockup in headless Chromium and fails on any page or console error.
10. **Linked households.** What another household shares is a world of its own, so it is
    never shown together with this household's data. It opens in a **window of its own**.
    1. **Where to find them**: a click on the household's avatar at the top of the sidebar
       opens a menu of the linked households, with no title. A **Linked households** card on
       Accounts lists them too. Each entry shows the household's avatar and name, how many
       items it shares with you, and when it last synced, and no names or amounts. A
       household that shares nothing with you is not listed. With none, the avatar opens no
       menu.
    2. **Opening one** follows a plain link to `/ui/linked/<link-id>/` with
       `target="mk-linked-<link-id>"`, so a pop-up blocker doesn't stop it, a second click
       goes to the window already open, and it can be bookmarked. Whether it opens as a
       window or a tab is the browser's choice. It uses the same sign-in, so signing out in
       either ends both.
    3. **The window** is the same frame, read only:
       1. the household's **avatar and name** in place of this household's, always as the
          source server sets them (S16.1);
       2. the sidebar tinted with **a colour each user chooses** for that household, from a
          fixed palette that reads well in dark and light themes. A new household gets the
          next unused colour. The name, avatar and a header strip always show as well, so
          colour is never the only sign;
       3. a **header strip**: *griffin-parents · read only · synced 41 min ago · unlocked by
          Alice at 14:05 · Lock now*;
       4. the screens for the kinds shared with you, **every screen and tab of each**, as its
          owner sees them but read only: Dashboard (only what is shared with you), Accounts,
          Portfolios, Positions (an account's holdings), Transactions, Projections (with their
          charts), Budgets (with cash flow and recurring payments), Gifts, Giving (with its
          months and organisations), Taxes and Receipts. The source sends what each screen
          needs (S11.3.1). A receipt still on its way (S11.4) is listed, *not arrived*, with
          what came with it (its date, amount and payee), and opens once it has. Positions with their gains and option trades, a loan's view and a
          physical-asset account's items come later ([later work](later.md), L6). The
          navigation lists only the kinds you have something from. There is no Settings,
          Profile, Watchlist, import, sharing or editing;
       5. the user tile shows you, the local user, *viewing griffin-parents*.
    4. **Locked**: the window shows only the household's name and avatar and the request for
       the access key (S11.9.3). If the copy locks while the window is open, the window
       returns to that request.
    5. **Never mixed**: nothing from a linked household appears in this household's lists,
       totals, charts, search, portfolios, budgets, taxes or Activity.
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
12. **Exact numbers in the browser.** Every amount, quantity, price and ratio the API sends
    arrives as an exact decimal (S13.8.2), a `Dec` (`app/dec.js`): a whole number of units at a
    scale, held in a BigInt. Adding, subtracting, comparing and rounding are exact, and the
    display functions format its digits as they are. It refuses to become a float by
    accident: arithmetic or a comparison with plain numbers throws, so a mistake fails loudly.
    What is only drawn (a chart's point, a bar's width) asks for a float by name. Sent back in a
    request, it is written as an exact number.
13. **Durations** are typed in one grammar wherever a length of time is asked for (pausing a
    link, S11.7.2): one or more parts, each a whole number and a unit, `w` (weeks), `d` (days),
    `h` (hours) or `m` (minutes), largest first, each unit at most once, with or without
    spaces between them: `1d`, `90m`, `2w 3d 4h`, `2w3d`. It is read by one helper on each side
    (`app/duration.js`, `moolakata/duration.py`), which refuses anything else and says why, and
    shown back the same way, so `2w 3d 4h` reads as typed.
14. **The welcome and the locked screen** (S13.6, S15.4). Both are outside the frame, in the
    card the sign-in screens use.
    1. **The welcome**, while the server has no keyring: every address under `/ui` shows it.
       **Welcome to MoolaKata** says the data will be kept under a master key that is a
       recovery phrase of 12 words, written down by the admin, asked for at every restart and
       recoverable by nobody; **Show my recovery phrase** shows a new phrase (S15.4.4): the 12
       words numbered, with the fingerprint, to write on paper. **I've written them down** asks
       for three of them by number; wrong ones are refused with "check your sheet", and
       **Back** shows the same words again. Right, the key is made and the server unlocked,
       and **Set up the admin account** follows (S10.1.2), then the Dashboard. A reload, or
       another browser, shows a new phrase; only the one confirmed is kept.
    2. **The locked screen**, while the server has a keyring but no key: every address under
       `/ui` shows it: the server has started and holds no key, with a field for the 12 words
       of the recovery phrase and **Unlock**, and a line naming the host command that does the
       same. The field is masked in every supported browser, with the eye button to show it
       (S12.1.3), and turns off the browser's autocorrect, autocapitalize, spellcheck and
       autocomplete, so nothing learns or keeps the words. While a re-encryption runs at the
       unlock (S15.7.2), the screen shows its progress, and gives way to sign-in when it is
       done. A wrong phrase is refused at the field; after the lockout of S13.7.5.1 the screen
       says how long to wait. Once unlocked, the screen gives way to sign-in, or to **Set up
       the admin account** while there are no users (S10.1.2). A page open when the server
       restarts lands on it at its next request, as it lands on sign-in when a session ends
       (S12.6). After **Rotate** or **Re-encrypt now** (S16.13), the page that asked shows
       **MoolaKata is restarting** until the server answers locked, then this screen; a
       server not back within a minute is said to need starting on the host.
15. **Editing and saving.** A form that changes records, in a dialog or on a screen
    (Settings, Profile), edits a **draft** of them (`app/draft.js`, S17.3.9), and nothing
    reaches the server until **Save**.
    1. **The draft** holds each record the form loaded, read from the route that reads it,
       never from a screen's figures, with the version it was read at (S13.8.6): its values as
       they stand and, for each field changed, the value it had. A field set back to that value
       is unchanged again, and a field, or the whole form, can be put back. An edit a rule
       makes because of another (a field cleared when it stops applying) is put back with
       the edit that caused it. Only what changed is sent, so a form saved without changes
       sends nothing.
    2. **Fields** take their type from the API's own description (S13.8.2): text, money, a
       quantity, a percentage, a whole number, yes or no, a date, a month, a choice from a list,
       a reference to another record, a list, or a structured value. Each type reads what is
       typed, shows a value back, and compares two values as values, so `42` and `42.00` are
       the same amount. Each is typed in its kind's input (S12.18). What is typed but doesn't
       read yet stays in its field, marked with the reason when the field is left; the draft
       keeps the last value that did, and Save refuses it at its field.
    3. **A new record** takes its id in the browser (`schema.md` §2), so another new record in
       the same draft can refer to it. Records with a stated order keep it: a field's
       (a category's path, a date), the order they were made in, or a position the person sets
       where a screen lets them arrange the order.
    4. **One save, all or nothing.** **Save** sends the whole draft in one request (S13.8.11),
       applied in one database transaction or not at all. A refusal changes nothing; each
       reason is shown at its field, or on its row for a record the dialog shows as a row, or
       above the buttons when it belongs to no field. A save that asks first (a transaction in
       a reconciled period, an edit to a year whose return is filed, a reserve that stops being
       kept while it holds money) lists every question together, and the dialog's button that
       goes ahead (**Save anyway**, **Change it anyway**) confirms exactly those; a question
       that arises after them is asked again.
    5. **Changed meanwhile.** When a record changed since the dialog read it (S13.8.6), nothing
       is saved: the dialog says so, with **Reload**, which opens it again from the records as
       they stand and loses the changes made in it, and **Cancel**.
    6. **Changes not saved.** While a draft holds changes, Escape, ✕, **Cancel** or the
       browser's Back asks **Save your changes?**, with **Keep editing**, focused and what
       Escape answers, **Discard**, in red, and **Save**; a click on the dimmed content does
       nothing; and on a screen's form, so does moving elsewhere in the app. **Save** saves
       and goes on; one refused, or one that asks first (S12.15.4), stays, with the reasons
       or questions shown. Typed text that doesn't read yet counts as a change.
       Leaving or reloading the page brings the browser's own question. A dialog without
       changes closes as S12.1.3 says. A
       session that ends, or a server that locks, while a dialog holds changes loses them, and
       the sign-in or locked screen says so.
    7. **A dialog opened from a dialog** opens over it, and the first, as it was, is back when
       it closes. One that makes a record on the way (a person for a gift, an organisation
       for a donation, a category with **New category…**, S12.2.6, a rule with **Make a
       rule**, S2.7.6) saves it with its own **Save**, and the first dialog then refers to it
       where it asked (the category chosen in the field that offered it); cancelling the
       first leaves it. One that fills in a record the first dialog's records own (a split, a
       plan line's reserve, a gift plan's occasion) edits the first dialog's draft: **Done**
       keeps its changes without saving them, **Cancel** puts back what it changed, and they
       are saved, or discarded, with the first dialog's.
16. **Deleting asks first.** Whatever deletes, removes, revokes, ends, resets, forgets, ungroups
    or unpairs something (a transaction, an account, a gift, a rule, a document, a token, a
    link, a linked copy, the connector's pairing) asks once, in a small box over the page or
    the dialog it comes from: what is about to happen (*Delete this transaction?*), a line on
    what follows where something does, **Yes**, named for what it does (**Yes, delete**,
    **Yes, revoke**), and **No**, focused. Enter, Escape and a click outside the box answer
    No, and leave the dialog it came from open. Yes goes ahead: in a dialog that edits a
    draft, the record is taken out of the draft and the draft saved at once (S12.15.4). An
    action that asks for more than a yes (a copy's removal, which asks for the recovery
    phrase) asks in its own dialog instead.
17. **Tours.** A tour leads someone through a task that spans screens: finding what uses a
    category is the first; setting things up across several screens (a household's
    accounts, a linked server) is what they are for as well.
    1. **The pane.** A tour opens in a pane at the right of the page, inside the content and
       left of the help pane, so a dialog dims it and holds it with the page. Its title is
       the tour's name, with ✕ at the top right, which closes it; it is never collapsed and
       brought back. Its width drags and moves with the arrow keys, as the help pane's does
       (S12.7.1), and the browser remembers it. One tour is open at a time: starting another
       closes the first.
    2. **It stays.** Its links go to screens, tabs and records by their addresses, and the
       pane stays as it was, scrolled where it was, while the person moves around the app.
       It is kept for the browser tab, through a reload, until it is closed or the session
       ends.
    3. **What it holds**: a short preamble (what the task is, and how the tour helps), then
       its steps in a list. A step is a line of text, with links where there are places to
       go, and a state read from the server: to do, or done (ticked). A step done while the
       tour is open stays where it is, ticked, so the list never jumps. The link to where the
       person is now is marked.
    4. **It follows the server.** When the live stream (S12.6) says its records changed, it
       reads its steps again: counts fall and steps tick themselves. When every step is done,
       it says so, and what comes next.
    5. **Its words** are Markdown shipped with the app, beside the guides
       (`web/ui/guides/tour-<tour>.md`); the steps and their counts come from the server.
    6. **Find uses** (S12.2.6), for a category. The preamble says what it is for: everything
       the reader can see that files money under the category, to give each another category
       (or merge it, S7.2.4), with the counts falling as they go; and how many uses they
       can't see, which only their owners or an admin's merge can clear. One step for each
       kind of use the reader can see, with its count:
       1. **Transactions and their parts**: a link to Transactions filtered to the category
          (`/ui/transactions?category=<id>`).
       2. **Rules**: a link to each (`/ui/transactions/rules/<id>`).
       3. **Plan lines**: each budget that plans it, linked to the budget's month where the
          line starts (`/ui/budgets/<id>/month?month=YYYY-MM`).
       4. **Moves**: each budget, with a link to each month that has one.
       5. **Loans**: each loan whose whole payment counts in it, linked to the loan's
          Settings tab (`/ui/accounts/<id>/settings`).
       6. **Categories under it**: each by name, linked to Budgets › Categories.
       Done, it says that nothing the reader can see uses the category: with nothing left,
       a link to the category's dialog, to delete it; with uses they can't see, how many,
       and that an admin can merge it.
18. **Typed inputs.** Each kind of value is typed in an input of its own, the same on every
    screen, so what it takes, when it is checked and how it is shown never vary (R3.11):
    1. **The kinds**, each with the characters it takes and the form it is checked against:
       an **amount** (digits and one `.`, at most two places), a **quantity** or ratio (digits
       and one `.`), a **percent** (digits, one `.`, and `%` at its end), a **count** (digits),
       a **duration** (digits, `w`, `d`, `h`, `m` and spaces, read as S12.13 says), a **date**
       (the browser's date picker), a **web address** (no spaces; `http://` or `https://`, then
       a host) and **text** (anything). An amount, quantity or count takes a `-` where the
       field takes a negative.
    2. **A key or a paste outside the kind's characters is not taken**, and the field is
       marked with what it takes (*Digits and . only*). A paste, or text put in whole (by
       autofill or dictation), is cleaned first: a dollar sign, spaces and non-breaking spaces
       are dropped, commas where they group thousands, a typographic minus becomes `-`, and an
       amount in parentheses becomes negative where the field takes one. Anything else left
       refuses the whole of it, never a part.
    3. **Checked when the field is left, and at Save**: its form, its bounds, and a bound
       another field sets (*At most* under *At least*). A value that fails is marked: a red
       border, and a tooltip saying why, which a screen reader reads with the field. Any
       change to the field clears its mark; it is checked again when next left. Save marks
       every field that fails and goes on, so each refusal shows under its field (S12.15.4).
    4. **Without a Save** (a filter, a preview), Enter or leaving the field is when its value
       is taken: one not yet checked, or marked, is left out, and what is shown stays as it
       was until the value passes.
    5. **What is shown and what is stored** are the input's own: an amount is shown at its two
       places (`1234.50`) and stored as an exact decimal (S12.12), a percent is shown with its
       `%` and stored as the number, a duration reads back as typed (S12.13), and a date shows
       in the browser's own format and is stored as `YYYY-MM-DD`.
    6. **The server checks every value again**, whatever the browser did (S13.8).
19. **Actions and the page's state.** What a person can't do is shown or hidden by why they
    can't, and what the page knows is shown briefly, its explanation in the guide (S12.7.4):
    1. **An action not open to them now**, by why:
       1. **Permission on this record** (it is shared with them to read; only its owner shares,
          deletes or changes its settings; another user's category) or **state they could
          change** (changes are to be saved first; a filing is needed first; the receipt is
          being read): the action stays where it is, unavailable. It looks off, reaches the
          keyboard, does nothing when pressed, and its tooltip says why (*Shared with you to
          read*, *Only its owner shares it*, *Save changes first*). It is never replaced by a
          line saying why.
       2. **Their role** (what only an admin does: Settings, Users and Groups): hidden. It is
          another level, never theirs to do.
       3. **A preference turned off** (a budget's moves): hidden, with no marker: they chose
          not to see it.
       4. What a person can only read is shown as read, not as a form of fields that are off. A
          list of tasks only a record's writer can do (the bank transactions offered to link
          to a loan, the transfers to pair) is the writer's alone.
    2. **Empty**: a short line where the content would be (*No saved plans*), beside the
       action that makes the first one when there is one.
    3. **A count or a status**: a pill on the card's header or the row (*3 uncategorised*,
       *Code out until 5:40 PM*), its one sentence of explanation its tooltip, reached by the
       keyboard.
    4. **Something needing attention**: a notice of one line naming it, with its actions as
       buttons (*Statement overdue · Import · Type today's balance*). A warning of what an
       action will do (*No backup is made first.*) is such a notice, beside the action.
    5. **One component each** draws them, the same on every screen. A test fails on an
       action left out because of a permission on its record, and on one shown unavailable
       without a reason.
    6. **What this doesn't cover**: the answer to an action just taken (a save's question or
       refusal, beside the buttons that took it), a tour's steps (S12.17), the screens outside
       the frame (sign-in, the welcome, the locked screen), which are one task each, results
       a screen works out (a plan's payoff, the money to move), and a security prompt that
       carries a value to compare (a certificate's fingerprint), which keeps it with it.
