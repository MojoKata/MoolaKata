# A rule

What a transaction must match, and what the rule sets. It needs at least one of a category, a
new payee or a tag.

## Payee contains

Text the payee holds as the bank writes it, case aside: `whole foods` matches `WHOLE FOODS
#123`. Start with `re:` for a regular expression: `re:^AMZN` matches a payee that starts with
AMZN. It takes [RE2's syntax](https://github.com/google/re2/wiki/Syntax), which has no
back-references (`\1`) or look-arounds (`(?=…)`, `(?<!…)`).

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

## Rename to

The payee shown in your lists: `Amazon` for `AMZN Mktp US*2K4LL`. The bank's text stays beside
it, and the rules match on the bank's text.

## Tags

Your own tags, added to each match: `coffee, work`.
