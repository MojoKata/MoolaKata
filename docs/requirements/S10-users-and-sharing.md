# S10. Users, groups and sharing

1. **Users, groups and sign-in**:
   1. A user has a unique username, a display name, a unique **email address**, an optional
      avatar, and a password stored as an argon2id hash. They sign in with username or email.
      The password's rules are S13.7.3's: a minimum length that admins set (12 by default), a
      maximum, and none of the most common passwords. A username is 2 to 32 lowercase letters,
      digits, dots, dashes or underscores, beginning with a letter or digit; usernames and
      email addresses match without regard to case. A display name is at most 80 characters, an
      email address at most 254.
   2. **The first admin** is made by the welcome (S12.14): once the key is made, **Set up the
      admin account** asks for the admin's name, sex (S10.10.1), email address and password,
      makes `admin` with them, and signs them in. No password is published, and nobody signs
      in before the admin exists. A server whose key was made on a terminal shows the same
      step at its first unlock, for as long as it has no users.
   3. **Invitations.** Admins never set passwords. Creating a user (name, sex, username,
      email, groups) emails an invitation link, and the user chooses their password from it.
      The link works once, for 7 days; sending a new one ends the one before.
   4. **Sign-up**, when an admin turns it on (it needs SMTP and the public URL, and can be
      limited to email domains): a person gives their name, sex and email, confirms the email,
      and waits on a *waiting for approval* screen until an admin approves or rejects the
      request.
      1. **Asking**: from **Sign up** on the sign-in screen, with a username and a password
         chosen then, so approval leaves nothing more to do. The answer is the same, and takes
         as long, whether or not the address already has an account; only a new address gets a
         link, which works once, for 24 hours.
      2. **Deciding**: confirmed requests show under **Requests** in Users and Groups, with a
         count on its badge. **Approve** makes the user, in a group if one is chosen;
         **Reject** turns it down. An email tells the person either way, and Activity records
         the request and the decision. The request stays as the record of it.
   5. **Password reset** by an emailed link from *Forgot password?*. A changed email address
      takes effect only when a link sent to the new address is opened. A reset link works
      once, for an hour, and a new request ends the one before; an email-change link works
      once, for 24 hours. An admin corrects a user's email address only until the user has
      joined; after that the user changes it in Profile.
   6. **Two-step sign-in**, optional for everyone: a TOTP code from an authenticator app after
      the password, set up with a QR code; ten recovery codes shown once; and an admin's
      reset as the last resort.
      1. **The code**: TOTP as authenticator apps read it (RFC 6238: SHA-1, six digits,
         30-second steps), with one step either side allowed for a phone's clock, and no step
         accepted twice. Its seed is a secret (S14.4).
      2. **Turning it on**, in Profile: a QR code and the same key as text, then a code from
         the app to confirm it, and only then is it on. The ten **recovery codes** follow,
         shown once, to copy or download: each 16 characters of a 31-letter alphabet (about
         79 bits, so a hash of one cannot be searched), written in four groups of four, and
         taken with any case or spacing; only their hashes are kept. Profile shows how many
         are left, warns at three, and **New recovery codes** replaces them all.
      3. **Signing in**: a right password leads to the code, through a token that lasts five
         minutes; no session exists until the code is right. A recovery code is taken in place
         of the code, once. Wrong codes count toward the same lockout of the address as wrong
         passwords (S13.7.5), and five wrong codes end the token, so the password is needed
         again.
      4. **Turning it off** in Profile, or an **admin's reset** in Users (for someone who
         has lost both the app and the codes), removes the seed and the codes; the reset also
         ends that user's sessions. Each, and turning it on, is emailed to the user and
         recorded in Activity, as is a sign-in with a recovery code. Each needs the password
         again under S13.7.2.
   7. **Active.** Each user has an **active** flag, which admins switch off and on. An inactive
      user cannot sign in, and cannot be added to a share, here or from a linked server; shares
      they already hold give them nothing while they are inactive. Switching it off ends their
      sessions at once and shows an *account is disabled* screen, from which they can ask to be
      reactivated (once a week), with their username and password, which count toward the
      lockout of S13.7.5.1 as a sign-in's do. Users and groups are deactivated rather than
      deleted.
   8. **Groups**: admins make named groups of users. Being an admin is membership of the
      built-in **Admins** group. The last active admin cannot be removed or deactivated.
   9. **Emails** (plain text): invitation, sign-up confirmation and decision, reset,
      email-change confirmation (to the new address) and notice (to the old one, once the
      change took effect, so a change the person didn't make is noticed), a sign-in from an
      address the user hasn't signed in from in 30 days (once they have signed in from
      somewhere; the addresses seen are kept on the user for those 30 days, and each session
      records its own), password changed, two-step turned on or off, a sign-in with a recovery
      code, an access token made (S10.9.1), reactivated, and alerts (S12.11). In dev mode they
      are written to a folder (S17.7).
2. **Admins are trusted operators.** An admin manages users, groups and Settings, and the app
   shows them only what is shared with them: another user's money stays off their screens. It
   cannot keep them out: an admin holds the recovery phrase and the host (S15), opens the
   emails written while SMTP isn't set up (S16.2), resets a user's two-step (S10.1.6.4), and
   chooses the SMTP host and the public URL that links are built from, so an admin who sets out
   to can reach any account. Opening a written email is recorded in Activity, with the user it
   is addressed to as its owner (S10.8). Users are not deleted: a user who leaves is made
   inactive (S10.1.7), and their data stays.
3. **What can be shared**: eight kinds of item, each with one owner and its own list of shares
   (people are the household's, S10.10.2):
   | Kind | A share includes |
   |---|---|
   | **Account** | its transactions, holdings, positions and receipts; a loan's payoff plans and a physical-asset account's items |
   | **Portfolio** | its charts and the accounts in it, as S5.1 says |
   | **Budget** | its categories, plan, moves, leave-outs, actuals, reserves and trends (S7.1) |
   | **Gift plan** | its person's occasions, budget, notes and gifts (S7.8.5) |
   | **Giving plan** | its target, pace, donations and organisations (S7.9.1) |
   | **Tax book** | its panels, filings and documents (S8.14.3) |
   | **Projection** | its inputs, results and tracking (S6) |
   | **Person** | a private person: their name, birthday and relationships (S10.10.2) |

   Each can be shared with a **user** or a **group**, at:
   1. **read**: see everything about it. A read share cannot change it, attach receipts or
      re-share it.
   2. **write**: also change what the item holds: for an account, add and edit transactions,
      import, categorise and attach receipts; for the other kinds, edit their entries. A
      write share cannot delete the item, change its sharing, or see or change its secrets
      (keys and credentials), which stay the owner's.
   3. **People on linked servers**: any of the eight kinds can also be shared with named users
      of a linked server (S11), always **read**. Each server sends its peers its list of active
      users (display name, username, email, sex and stable id, S11.3), so they can be chosen
      like local users. Groups are not sent. When a remote user is deactivated, their shares
      are suspended. When the link ends, the shares are removed.
      1. **A remote user is a `User` record** with its `linkId` set, so it appears wherever
         a share is chosen, beside local users, under its server's name. It has no password,
         two-step or sessions (a `CHECK` enforces it), and its fields come only from its
         server (S11.3).
      2. **Only local users** appear where a user signs in, owns or changes something here:
         sign-in, Users and Groups, group membership (a group can hold write shares, and a
         remote user only ever reads), the Admins group, tax-book filers (S8.14.1), a
         spouse (S10.10.4), the owner of anything, and who receives alerts (S12.11). A
         remote user has a person too, filled from its server and used only for gifts
         (S10.10.1).
      3. **Settings › Linked servers** lists each link's users, read only.
4. **The Share dialog** lists every active user, then every active group, then the people on
   each linked server, each list alphabetical under a heading with a line on what sharing
   gives. Local users and groups have a three-way switch **None · Read · Write**. People on
   a linked server have **None · Read**, under the server's name, which notes that it
   confirms who they are. Each linked server with anyone set to Read has **Include
   receipts** (off by default, S11.5). A user who has access only through a group is shown
   *via* it. Nothing changes until **Save** (with **Cancel** beside it). When a share is
   removed, the receiver's access ends on their next request. Their own annotations, such as
   their tags on the account's transactions, are deleted.
5. **Through a group**: every member holds the share while they are in the group and it is
   active. A user with both a direct and a group share gets the higher level.
6. **A shared account appears in the receiver's lists** with a *shared with me* mark, the
   owner's avatar, and the level (an eye for read, a pencil for write). The owner's lists
   mark *shared by me* and how many people have it. Filters: All, Mine, Shared with me,
   Shared by me, From linked servers.
7. **A receiver's totals** (net worth, Dashboard) include shared accounts only if the
   receiver ticks **Count in my totals** on them, which is off by default. A spouse's accounts
   then count once, and a parent's shared accounts don't inflate a child's net worth. What a
   linked server shares never counts in this household's totals: it is shown only in its
   own window (S12.10).
8. **Activity** lists the changes worth showing, each naming who made it and what it is about,
   to the people concerned (the owner, the receivers of any of the eight kinds, and admins for
   users and groups): shares given or taken away, accounts created, closed or deleted, imports,
   rule changes, links made or ended, a written email opened (S10.2), and who did each. A
   receiver whose share is removed keeps the entry that says so. Amounts are never named
   (R3.8).
9. **Agents (MCP).** An AI assistant can read, and never change, what a user can see,
   through a **Model Context Protocol** endpoint at `/mcp` (Streamable HTTP).
   1. **Access tokens**: each user makes their own in **Profile › Access tokens**: a name,
      what it can read (everything the user can see, or chosen items), and an expiry (30
      days, 90 days by default, or a year). The token is shown once and stored as a hash.
      The list shows each token's name, scope, expiry and last use, with **Revoke**. A token
      reads `mkt_<id>.<secret>`; only a SHA-256 hash of its random secret is kept, and it is
      sent as a bearer token. Chosen items are accounts and portfolios the user can see.
   2. **Read only, always.** There is no write scope. The tools list and read accounts,
      balances, holdings, transactions, portfolios, budgets, gifts, giving and tax panels,
      through the user's shares at the moment of the call. A write share gives a token no
      more than read.
   3. **Never through a token**: secrets, Settings, other users' data that isn't shared with
      the user, and linked households, whose access key is for a person at the screen
      (S11.9).
   4. A token works only at `/mcp`, never at `/ui/api`. It stops when it is revoked or expires,
      when its user is made inactive, and when its user's password is changed or reset. Each
      call is recorded in Activity under the token's name, and calls are limited to 60 a minute
      per token.
   5. **The tools**: `list_accounts`, `get_account_holdings`, `list_transactions` (one
      account or all, between dates, by payee, at most 500), `list_positions`,
      `list_portfolios`, `get_portfolio` (value, holdings and returns), `list_budgets`,
      `get_budget_month`, `list_upcoming_gifts`, `get_giving`, `list_tax_books` and
      `get_tax_panels`. Each answers with what the matching screen shows. A token with chosen
      items reads only those accounts and portfolios; the tools about the whole household
      (budgets, gifts, giving, taxes) refuse it.
   6. **The protocol**: JSON-RPC 2.0 over POST, answered as JSON (no server-sent stream, so
      GET is refused); the token as a bearer token; a request whose Origin header names
      another site is refused, so a web page can't use a token it has found.
10. **People and relationships.**
    1. **A person** has a name, a **sex** (*male* or *female*, required), a **birthday** (the
       year optional, for their age) and, once they have died, the date (`diedOn`). **Every
       user is a person**: a user's display name and birthday are their person's, edited in
       Profile. A remote user's person is filled from its server (S10.3.3.1) and is used only
       for gifts. A new local user whose name is already that of a person here who isn't a user
       becomes that person. A remote user gets a person of its own, joined to an existing
       person only when a local user who can change that person confirms it, which never
       changes whether the person is private.
    2. **People are the household's.** A new person is seen by every local user. Its creator
       may make it **private**, and then share it as any item (S10.3). A person is changed by
       that person once they are a user here, by its creator until then (and for a linked
       server's user, who never signs in here), and by an admin.
    3. **One person, once.** Adding a person whose name matches one already here, ignoring
       case, shows that person instead. A private one shows **Ask to share**, which asks its
       creator and the admins (an alert, S12.11). **A different person** adds the new one
       only once both have birth years and they differ, so the two can be told apart.
    4. **A relationship** joins two people from a date (optional) to a date (empty while it
       holds): *spouse*, *couple*, *child*, *friend*, *colleague* or *family*, the last with an
       optional label (*godmother*). *Child* runs from the parent to the child; the rest run
       both ways. A user adds relationships they are in; an admin adds any. A spouse needs both
       people's confirmation, the other's from their own Profile (an admin confirms for a
       person who isn't a user); until both have confirmed, the marriage counts for gifts only,
       not for wash sales (S3.8) or a joint tax book (S8.14.1).
       1. **At most one spouse at a time**, and no one is their own ancestor.
       2. **A marriage ends** by divorce (its end date) or by death (a spouse's `diedOn`,
          which ends it on that date). The same two people can marry again: a new row.
       3. **The spouse** is read for wash sales on the date of the sale (S3.8) and for a
          joint tax book on the last day of its year (S8.14.1). Couples, friends and
          colleagues are for gifts and sharing only.
    5. **The family tree** is worked out from *child*, *spouse* and *couple*, never stored,
       as of a date, so a past year shows that year's family (R3.10):

       | Shown as | Worked out from |
       |---|---|
       | mother, father / son, daughter | *child* |
       | sister, brother | both parents shared |
       | half-sister, half-brother | one parent shared |
       | grandmother, grandfather / granddaughter, grandson; great- and further | chains of *child* |
       | aunt, uncle / niece, nephew | a parent's sibling |
       | cousin | a child of a parent's sibling; anyone further out is a *relative* |
       | stepmother, stepfather / stepdaughter, stepson / stepsister, stepbrother | a parent's spouse who isn't a parent, and their children |
       | mother-in-law, father-in-law / daughter-in-law, son-in-law / sister-in-law, brother-in-law | through a spouse, or a child's spouse |
       | ex-wife, ex-husband | a marriage ended by divorce; the in-laws through it end with it |
       | wife, husband, widow, widower | *spouse*, ended by death for the last two |

       The words follow each person's sex. Adoption and guardianship are *child*. A person
       related in a way the tree can't show is entered as *family* with a label.
    6. **Shown** in the person's gift plan as their relationships, stored and worked out,
       and on the Gifts screen as the person's relation to the user (*Emma, your
       granddaughter*). Profile lists the user's own with their dates, adds them, and changes
       or removes them; an admin's dialog also names whose relationship it is (S12.2).
