# New rule

A new rule, made from a transaction over its dialog: what a transaction must match, and what the
rule sets, its payee and category filled in from the transaction. It needs at least one of a
category, a new payee or a tag. **Add the rule** saves it; the transaction stays as it is. The
rules are listed on Transactions › Rules.

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

At the end of the list: opens **New Category** over this dialog. The category it makes
is chosen here when you add it, and everyone sees it: the household has one tree of categories.

## Rename to

The payee shown in your lists: `Amazon` for `AMZN Mktp US*2K4LL`. The bank's text stays beside
it, and the rules match on the bank's text.

## Tags

Your own tags, added to each match: _coffee_, _work_. Type one and press Enter or a comma; a name you haven't used makes a new tag when you save.
