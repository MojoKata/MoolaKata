# S12.10. Linked households

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
    3. **The window** is the same frame, read only, drawn by the source's own release, which
       a worker on this server runs (S11.10):
       1. the household's **avatar and name** in place of this household's, always as the
          source server sets them (S16.1);
       2. the sidebar tinted with **a colour each user chooses** for that household, from a
          fixed palette that reads well in dark and light themes. A new household gets the
          next unused colour. The name, avatar and a header strip always show as well, so
          colour is never the only sign;
       3. a **header strip**: *doe-parents · read only · synced 41 min ago · unlocked by
          Jane at 14:05 · Lock now*;
       4. the screens for the kinds shared with you, **every screen and tab of each**, as its
          owner sees them but read only: Dashboard (only what is shared with you), Accounts,
          Portfolios, Positions (an account's holdings), Transactions, Projections (with their
          charts), Budgets (with cash flow and recurring payments), Gifts, Giving (with its
          months and organisations), Taxes and Receipts. The source sends what each screen
          needs (S11.3.1). A receipt still on its way (S11.4) is listed, *not arrived*, with
          what came with it (its date, amount and payee), and opens once it has. Positions with their gains and option trades, a loan's view and a
          physical-asset account's items come later ([F#562](https://github.com/MojoKata/MoolaKata/issues/562)). The
          navigation lists only the kinds you have something from. There is no Settings,
          Profile, Watchlist, import, sharing or editing;
       5. the user tile shows you, the local user, *viewing doe-parents*.
    4. **Locked**: the window shows only the household's name and avatar and the request for
       the access key (S11.9.3). If the copy locks while the window is open, the window
       returns to that request.
    5. **Never mixed**: nothing from a linked household appears in this household's lists,
       totals, charts, search, portfolios, budgets, taxes or Activity, but for S11.8's records
       of the link, which name kinds, owners and counts, never an item's name.
    6. **Can't show yet**: while no worker can run the source's release (S11.10.4), the
       window shows only the household's name and avatar, its sync line and what's missing:
       *doe-parents runs MoolaKata 1.6, which this server can't show yet: allow downloads in
       Settings › Linked Servers*.
