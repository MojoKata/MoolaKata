# Receipt

The receipt, its fields, and what it is attached to. A photo opens full size; a PDF opens in the
browser's own viewer.

When it was uploaded, MoolaKata read it on the server: its date, total and merchant fill the empty
fields, marked _read from the receipt_ with how sure the reader was. Check them; anything you type
stays yours and is never replaced. **Read Again** reads it once more.

A receipt whose file is pruned keeps its record: its amounts, dates and links, and the text read
from it; with no file, it has no **Read Again**. One being read on the server fills in its fields
when it's done, and they can be typed meanwhile; one that couldn't be read is typed by hand.

A PDF is read page by page: a page with text in it directly, a scanned page by OCR, so an emailed
letter with a scanned receipt behind it is read whole.

A transaction of the receipt's amount within five days of its date is offered to attach it to; one
that hasn't arrived is attached from the transaction when it does. A receipt without a date and
amount is attached from the transaction itself.

## The text and the scan disagree

A total read from a PDF's text is checked against the picture of that page. When they differ (a
scanner's own text can misread a digit), both readings are shown and no transaction is offered
until you confirm the amount: **Use** one of them, or type it, and save. It is then yours, as a
typed amount is.

## Keep

Keeps the file for ever, whatever its retention: for a warranty, or a medical bill an HSA may repay
later. Its tooltip says how long the file is kept otherwise, and what sets it.

A file is kept for as long as what it is attached to needs it, then the period its category sets
(**Keep receipts for**, Settings › Storage; a subcategory without one takes its parent's). The
date is counted from when what it is attached to ended: a transaction's date, a lot's last sale, a
gift's occasion; over everything it is kept with, the latest end and the longest period win. A
transfer, an uncategorised transaction or a category with no period keeps it for ever, as does
being attached to nothing. A statement is kept for the statements' period after its own last day;
a loan's other documents (a closing disclosure) are kept while the loan is open, then the
statements' period from the day it is paid off. The category that sets the date is named only when
it is shared with you, else _Kept for something not shared with you_.

A warning shows by Keep only while it applies: _Expires Dec 2026_ within 90 days of the date, and
_Expired, prunable_ once it has passed, when an admin may prune the file in Settings › Storage. A
pruned file's record keeps its amounts, dates and links.

## Date {#receipt-date}

The date on the receipt: the transaction it belongs to is looked for within five days of it.

## Amount {#receipt-amount}

The total paid. A transaction up to 25% larger still matches, for a tip added after the receipt was
printed.

## Payee {#receipt-payee}

Who was paid, as the receipt says, renamed by your payee rules or, when none renames it, as a payee
of your own accounts' transactions that has its words: _Blue Bottle Coffee #042_ is read as _Blue
Bottle Coffee Hayes Valley_ when that is how your transactions name it.

## Notes {#receipt-notes}

Anything worth keeping with it.

## Tags {#receipt-tags}

Words to find it by, such as _medical_ or _warranty_. They are yours only: no one it is shared
with sees them. Type one and press Enter or a comma; a name you haven't used makes a new tag when you save.

## Attached To {#attached-to}

The transactions it supports, and what else it is kept with. Until it is attached to something, it
waits in the inbox. **Attach** takes the best match among
your transactions with the same amount near its date; the buttons beside it are the next two.
**Detach** returns it to the inbox when nothing else links to it. Both happen when you save.
What it is kept with that isn't shared with you is only counted: _Also kept with 2 things not
shared with you_, never named.

## Text read from the receipt

Everything the reader found, which the Receipts screen searches.

## Delete

Only its owner, and only once nothing links to it, including what isn't shared with them.
