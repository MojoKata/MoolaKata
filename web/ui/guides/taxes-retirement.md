# Taxes: Retirement

Contributions against the year's limits, distributions, and the required minimum distributions due.

![Retirement](shots/taxes-retirement.png)

## Tax book

The book shown, for one tax year. Its panels count the book's accounts only, and say which were left
out.

## Contributions against the Limits

What went into each retirement account for the year, against its limit from the tax tables, with the
catch-up by age. A rollover or a conversion is no contribution: money moved from another retirement
account, matched as a transfer, is listed below instead. An HSA counts its employer's money too, and
its limit is its coverage's (set on the account), $1,000 more at 55.

A Roth IRA's contributions are read against the year's phase-out (Settings › Tax Tables) at the
MAGI typed on the Summary, by the federal filing's status (a joint book's is joint): eligible,
partly, with the most the MAGI allows (the limit cut in proportion, raised to the next $10, and to
$200 when less), or not. Past what it allows, the row is marked **over**. Until the MAGI and the
status are typed, it says which it waits for. A separate return's range is $0 to $10,000; one filed
by someone who didn't live with their spouse during the year takes the single range instead,
which MoolaKata can't tell.

A backdoor Roth is its steps, each on its row: the contribution to a traditional IRA, marked
**Not deductible**, which counts against the IRA limit and adds to the Form 8606 basis; and its
conversion, under Roth Conversions with its taxed part. A conversion is no Roth contribution, so
the phase-out doesn't hold it.

## Distributions

What came out of each retirement account, but for rollovers and conversions.

## Form 8606 basis {#basis-8606}

Each filer's own: the basis their return carried from last year, plus this year's contributions to
their traditional IRAs marked **Not deductible** in the transaction form. A contribution still
**Not decided** is counted, and named, until it is marked.

## Required Minimum Distributions {#rmds}

For an owner at the RMD age: the account's value at the end of last year divided by the Uniform
Lifetime Table's factor for their age. None is due until an owner reaches the RMD age.

## Roth Conversions {#conversions}

Money moved from a traditional IRA or a 401(k) to a Roth IRA. A conversion from a traditional IRA
shows its taxed part: the conversion less its share of its owner's Form 8606 basis, over the
year-end value of that owner's traditional IRAs and what left them in the year. Each spouse's is
their own. The taxed part waits, saying for what, while last year's basis isn't typed or a
contribution this year isn't marked deductible or not.

## Rollovers {#rollovers}

Money moved between retirement accounts of the same kind, a trustee-to-trustee transfer too: no
contribution, and no distribution.
