# S6. Projections

1. **A projection** asks how money will grow and what it will pay for. It has an owner, a name,
   a **goal type** (S6.2), what it is **built on**, and whether it is **active** (S6.7). It is
   shared like an account (S10.3): a viewer sees its results, and the values and tracking of
   only the accounts shared with them.
   1. **Built on** chosen accounts, a portfolio, or a typed amount for a what-if. Built on
      accounts or a portfolio, it starts from their **current values** each time it opens,
      with their *as of*, and from their allocation by asset class.
   2. **Contributions**: an amount, its frequency, growth per year, and until when. Capping
      them, for retirement accounts, by the limits of S1.4 comes later ([later work](later.md),
      L7).
2. **Goal types.** All three use the same models (S6.4).
   1. **Retirement**, for one person or a **couple**: each person's birth year and
      retirement age, and the accounts that are theirs. After retirement come
      **withdrawals** (the 4% rule, a fixed amount rising with inflation, or a percentage
      of the balance) set against **other income**: Social Security from an age, a pension,
      each with its amount. The answer: the **chance the money lasts** to the horizon (age
      95 by default), and the balance by age.
   2. **Education**, for one beneficiary, built on their 529 accounts (S1.8). The beneficiary's
      birth year gives the first year of school, which starts on Sep 1; contributions go on
      until then. The user sets the years of school and the yearly cost in today's dollars:
      typed, or a shipped average of tuition, fees, room and board for public four-year
      (in-state) and private nonprofit four-year colleges, from the National Center for
      Education Statistics' *Digest of Education Statistics* (table 330.10, public domain,
      updated yearly and shipped with the tax tables), and the contributions, flagged where one
      person's gifts pass the annual exclusion (S1.8.2). The answer: the projected balance when
      school starts against the cost, the **percentage funded**, and the monthly contribution
      that would fund it fully, or *no monthly saving reaches it by then*. A 529's **Goal** tab
      shows this projection.
   3. **Savings target**: an amount by a date (a house deposit, a car), built on any
      accounts. The answer: the **chance of reaching it** by the date, and the monthly
      saving that would, or *no monthly saving reaches it by then*.
3. **Assumptions**, kept once per user in **Profile › Assumptions**: expected return and
   volatility for each asset class (US stocks, international stocks, bonds, cash, crypto,
   real estate, metals), general inflation (2.5% by default) and education inflation (5% by
   default). Every projection uses them unless it overrides a figure, so the user's
   projections and the payoff planner (S6.10) agree with each other. Fees per projection.
   1. **Bitcoin models.** For the bitcoin in what a projection is built on, the user can choose
      a published model in place of the crypto assumption, in Profile › Assumptions or per
      projection. Other coins keep the crypto assumption; a typed amount names no coins, so
      its crypto is taken as bitcoin. Each model gives a median path from
      today's price, which the crypto assumption's volatility spreads into the Monte Carlo fan,
      as it does the default's:

      | Model | What it is |
      |---|---|
      | **Your assumption** (the default) | log-normal at the crypto return and volatility above |
      | **Power law** (Santostasi) | price = A × (days since the genesis block)^n, n ≈ 5.8 |
      | **Log regression** (the "rainbow chart") | a logarithmic curve fitted to the price history |
      | **Stock-to-flow** (PlanB) | value from the ratio of supply to new issuance, stepping up at each halving |
      | **Saylor, Bitcoin24** (2024) | $3M, $13M and $49M by 2045 (bear, base, bull) |
      | **ARK Invest** (2030 targets) | $500K, $1.2M and $2.4M by 2030 (bear, base, bull) |

      1. **Compare models** shows every model's median path on one chart (log scale) with
         the price history behind it, and a table of each model's figures for 2030, 2035 and
         2045.
      2. **Each model states its source and record.** Stock-to-flow has run below its own
         band since 2022; the targets of Saylor and ARK are forecasts by people with a stake
         in the outcome; the curve fits describe the past and say nothing about why it
         should continue. MoolaKata shows these as models others publish, not as its own
         view, and not as advice (R1.16).
      3. **Their figures ship with the app**, dated and with their source, in Settings ›
         Tax tables, and are updated with it (a new ARK target, a refit of the power law).
      4. A projection that uses a model with bear, base and bull cases shows those three
         paths in place of a fan, since they are not percentiles.
4. **Models:**
   1. **deterministic**: future value at a constant rate, in nominal and today's dollars;
   2. **Monte Carlo**: *N* runs (1000 by default) drawing yearly returns from the asset
      classes' mean and volatility (log-normal; a historical bootstrap later), showing the
      10th/50th/90th percentile **fan** and the type's answer (S6.2).
      1. **Each year**, the balance grows by its mix of asset classes' returns, each drawn
         log-normal on its own (correlation between classes is not modelled), less fees;
         contributions are added, rising by their growth, until retirement or the target
         date; after retirement the withdrawal is taken, less what other income covers. A
         couple's household retires when the last of them does. A target date part-way
         through a year counts that part of it.
      2. **The mix** comes from the holdings of what it is built on: cash and money-market
         funds are cash, bonds and bond funds bonds, crypto crypto, metals metals (precious-
         metal items too, at spot); other funds and shares are US stocks unless their name says
         international, emerging or real estate. A typed amount gives its own mix (60/40
         stocks and bonds unless set). A loan, an item other than a precious metal (a home, a
         car) and options aren't grown: the projection leaves them out of its start and its
         tracking alike and names each, with its value, under its chart, to a viewer only where
         they can see the account.
      3. **A bitcoin model** sets the median growth of the bitcoin each year, and the
         crypto volatility spreads it.
      4. **The savings answer** names the monthly saving that reaches the target with a 90%
         chance, to the dollar a year, a date part-way through a year counting only that
         part of a year's saving.
   3. **Glide path** *(later)*: the allocation shifting toward bonds as the goal nears, as
      age-based 529 portfolios and target-date funds do.
5. **Tax-aware buckets** (later): taxable, deferred and free balances projected apart, with
   RMDs from the required age and an assumed tax rate on withdrawals.
6. **Scenarios compare** side by side, for example retiring at 60 against 65, or contributing
   $500 more a month. Projections that are not active are the scenarios.
7. **Active projections** are the plans being followed.
   1. **At most one per subject**: one retirement projection per person or couple, one
      education projection per beneficiary, one per savings target. Making one active asks
      before turning off the one it replaces.
   2. **The baseline**: making a projection active stores its median path and its 10th–90th
      percentile band as of that day.
   3. **Tracking**: the actual balance of what it is built on, plotted against the baseline
      to date, and a status: **on track** inside the band, **ahead** above it, **behind**
      below it. The band grows from the actual balance on the baseline's day (prices that
      arrive later that day don't count against it), and is never narrower than 2% of its
      median either way, so day-to-day noise isn't called a plan going wrong. A projection built on a
      typed amount has nothing to track. Beside it, the type's answer run again from today's balance.
   4. **Changing an active projection's inputs** asks whether to **re-baseline**. Without
      it, tracking keeps comparing against the plan as it was made active.
   5. **Falling behind** raises an alert (S12.11), checked monthly, and resolves when the
      balance is back inside the band.
8. **Where active projections show:**
   1. the **Dashboard's Plans** card: one row each, with the type and name, the status, the
      type's headline figure (*87% chance of success*, *64% funded*, *$28,000 of $40,000 by
      2028*), and a small chart of the actual balance against the baseline;
   2. **on what it is built on**, when that is one account or one portfolio: a 529's Goal
      tab, an account's Overview, or a portfolio's *Projections* tab. A projection built on
      several accounts shows only on the Dashboard and the Projections screen;
   3. an active projection **shared with you** shows on your Dashboard only when you tick
      **Show on my Dashboard** on it, which is off by default, as **Count in my totals** is
      for accounts (S10.7). A linked household's projections show only in its window
      (S12.10).
9. **The computation runs on the server**, seeded so a scenario's figures are reproducible, and
   returns percentiles per year. It uses NumPy, in floats: the one exception to R1.9, since its
   figures are estimates. Its percentiles are rounded to cents and sent as exact numbers
   (S13.8.2.1), and the start value and the tracking figures stay exact. The screen states its
   assumptions in full under the chart and says plainly that it is a model, not a forecast.
10. **Loan payoff planner** (on each loan's *Payoff* tab, S1.9.5). It compares the schedule
    with the user's **overpayment** plans:
    1. **Plans**, combined freely: an extra amount every month (from a date, until a date),
       an extra amount once a year (a bonus month), one-time **lump sums** on dates,
       **biweekly** payments (26 half-payments a year), and rounding each payment up.
    2. **Results** for each plan against the schedule: the new payoff date, months saved,
       **interest saved**, total paid, and the balance over time as two lines on one chart,
       with the amortization table of each.
    3. **Recast**: after a lump sum, a mortgage can be **recast** (the term kept, the payment
       lowered) instead of shortened. The planner shows both, with the servicer's recast fee.
    4. **Against investing the extra**: the same money invested in an asset class the user
       picks, at their expected return for it (S6.3), shows its value at the payoff date
       next to the interest saved.
       It is a comparison, not advice, and says so (R1.16).
    5. **Saved plans** are kept per loan. One can be marked **the plan I'm following**, and
       the loan's screen then shows whether actual overpayments since it was chosen are
       ahead of it or behind. The *Payoff* tab opens on that plan.
    6. Rates for an ARM's future resets are the user's assumption, shown as such.
