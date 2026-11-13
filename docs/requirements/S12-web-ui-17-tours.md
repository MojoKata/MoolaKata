# S12.17. Tours

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
