# Receipt

The receipt, its fields, and what it is attached to. A photo opens full size; a PDF opens in the
browser's own viewer.

When it was uploaded, MoolaKata read it on the server: its date, total and merchant fill the empty
fields, marked _read from the receipt_ with how sure the reader was. Check them; anything you type
stays yours and is never replaced. **Read again** reads it once more.

A receipt whose file is pruned keeps its record: its amounts, dates and links. One being read on the
server fills in its fields when it's done, and they can be typed meanwhile; one that couldn't be
read is typed by hand.

A transaction of the receipt's amount within five days of its date is offered to attach it to; one
that hasn't arrived is attached from the transaction when it does. A receipt without a date and
amount is attached from the transaction itself.

## Keep

Keeps the file for ever, whatever its retention: for a warranty, or a medical bill an HSA may repay
later. Beside it, how long the file is kept otherwise: _Kept until Mar 2031_ (in bold within 90
days), _Kept while the lot is open_ while what it is attached to hasn't ended, or _Kept for ever_.
The date is the file's own, over everything it is kept with; the category that sets it is named
only when that is shared with you, else _Kept for something not shared with you_.
An expired file shows _Expired Mar 2031, prunable_, and an admin may prune it in Settings ›
Storage; a pruned file's record keeps its amounts, dates and links.

## Date {#receipt-date}

The date on the receipt: the transaction it belongs to is looked for within five days of it.

## Amount {#receipt-amount}

The total paid. A transaction up to 25% larger still matches, for a tip added after the receipt was
printed.

## Payee {#receipt-payee}

Who was paid, as the receipt says.

## Notes {#receipt-notes}

Anything worth keeping with it.

## Tags {#receipt-tags}

Words to find it by, such as _medical_ or _warranty_. Type one and press Enter or a comma; a name you haven't used makes a new tag when you save.

## Attached to {#attached-to}

The transactions it supports, and what else it is kept with. **Attach** takes the best match among
your transactions with the same amount near its date; the buttons beside it are the next two.
**Detach** returns it to the inbox when nothing else links to it. Both happen when you save.
What it is kept with that isn't shared with you is only counted: _Also kept with 2 things not
shared with you_, never named.

## Text read from the receipt

Everything the reader found, which the Receipts screen searches.

## Delete

Only its owner, and only once nothing links to it, including what isn't shared with them.
