# Rules

Your rules for the transactions you import: each says what a payee looks like and what to set
when one matches. They are yours alone, never shared, and never sent to a linked server. The
list is on the left; the rule you choose is on the right.

## First match wins {#first-match}

A transaction takes the first rule, top to bottom, that it matches, so a narrow rule goes above a
broad one: `re:^KROGER FUEL` above `kroger`. Move a rule with **↑** and **↓**. While the rule
you're changing has changes, they and **Apply** are off: save changes first.

Rules set a category only where there is none, and never touch a split, a transfer between your
accounts or a trade. They run on every file, statement and connector fetch you import, and on the
receipts you add: a rule that renames a payee renames the merchant a receipt names.

## Add rule

Adds a rule at the end of the list and shows it on the right; **Discard** takes it away again. A
transaction's own dialog offers **Make a rule**, which opens **New rule** over it with its payee
and category filled in.

## Apply to the uncategorised

Beside **Add rule** while any are uncategorised: runs your saved rules now over the uncategorised
transactions in the accounts you can change. Activity records how many it set, never an amount.

## Save and Discard

Show while the rule has changes, and go when you put it back as it was. Choosing another rule, or
going elsewhere, with changes asks first: **Keep editing**, **Discard** or **Save**.

## Payee contains

Text the payee holds as the bank writes it, case aside: `whole foods` matches `WHOLE FOODS
#123`. Start with `re:` for a regular expression: `re:^AMZN` matches a payee that starts with
AMZN. It takes [RE2's syntax](https://github.com/google/re2/wiki/Syntax), which has no
back-references (`\1`), look-arounds (`(?=…)`, `(?<!…)`), atomic groups (`(?>…)`), possessive
repeats (`a++`) or conditionals. Case is aside unless the pattern starts with `(?-i)`.

## Amount from

The smallest amount it matches, without its sign: 20 matches −$20.00 and $20.00. Leave it empty
for any.

## Amount to

The largest amount it matches. With **Amount from**, a range: 0 to 20 for small purchases.

## Direction

Money in, money out, or either: a payroll deposit is money in, a refund from a shop too.

## Account

One account, or any of those you can change.

## Category

What a matching transaction is filed under, when it has no category yet. **Leave it as it is**
for a rule that only renames or tags.

## New category…

At the end of the list: opens **New category** over this page. The category it makes is chosen
here when you add it, and everyone sees it: the household has one tree of categories.

## Rename to

The payee shown in your lists: `Amazon` for `AMZN Mktp US*2K4LL`. The bank's text stays beside
it, and the rules match on the bank's text.

## Tags

Your own tags, added to each match: `coffee, work`.

## Delete

Removes the rule, after asking. What it set before stays as it is.
