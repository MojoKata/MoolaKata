# S12.2. Navigation

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
