# S12.15. Editing and saving

15. **Editing and saving.** A form that changes records, in a dialog or on a screen
    (Settings, Profile), edits a **draft** of them (`app/draft.js`, S17.3.9), and nothing
    reaches the server until **Save**.
    1. **The draft** holds each record the form loaded, read from the route that reads it,
       never from a screen's figures, with the version it was read at (S13.8.6): its values as
       they stand and, for each field changed, the value it had. A field set back to that value
       is unchanged again, and a field, or the whole form, can be put back. An edit a rule
       makes because of another (a field cleared when it stops applying) is put back with
       the edit that caused it. Only what changed is sent, so a form saved without changes
       sends nothing.
    2. **Fields** take their type from the API's own description (S13.8.2): text, money, a
       quantity, a percentage, a whole number, yes or no, a date, a month, a choice from a list,
       a reference to another record, a list, or a structured value. Each type reads what is
       typed, shows a value back, and compares two values as values, so `42` and `42.00` are
       the same amount. Each is typed in its kind's input (S12.18). What is typed but doesn't
       read yet stays in its field, marked with the reason when the field is left; the draft
       keeps the last value that did, and Save refuses it at its field.
    3. **A new record** takes its id in the browser (`schema.md` §2), so another new record in
       the same draft can refer to it. Records with a stated order keep it: a field's
       (a category's path, a date), the order they were made in, or a position the person sets
       where a screen lets them arrange the order.
    4. **One save, all or nothing.** **Save** sends the whole draft in one request (S13.8.11),
       applied in one database transaction or not at all. A refusal changes nothing; each
       reason is shown at its field, or on its row for a record the dialog shows as a row, or
       above the buttons when it belongs to no field. A save that asks first (a transaction in
       a reconciled period, an edit to a year whose return is filed, a reserve that stops being
       kept while it holds money) lists every question together, and the dialog's button that
       goes ahead (**Save anyway**, **Change it anyway**) confirms exactly those; a question
       that arises after them is asked again.
    5. **Changed meanwhile.** When a record changed since the dialog read it (S13.8.6), nothing
       is saved: the dialog says so, with **Reload**, which opens it again from the records as
       they stand and loses the changes made in it, and **Cancel**.
    6. **Changes not saved.** While a draft holds changes, Escape, ✕, **Cancel** or the
       browser's Back asks **Save your changes?**, with **Keep editing**, focused and what
       Escape answers, **Discard**, in red, and **Save**; a click on the dimmed content does
       nothing; and on a screen's form, so does moving elsewhere in the app. **Save** saves
       and goes on; one refused, or one that asks first (S12.15.4), stays, with the reasons
       or questions shown. Typed text that doesn't read yet counts as a change.
       Leaving or reloading the page brings the browser's own question. A dialog without
       changes closes as S12.1.3 says. A
       session that ends, or a server that locks, while a dialog holds changes loses them, and
       the sign-in or locked screen says so.
    7. **A dialog opened from a dialog** opens over it, and the first, as it was, is back when
       it closes. One that makes a record on the way (a person for a gift, an organisation
       for a donation, a category with **New category…**, S12.2.6, a rule with **Make a
       rule**, S2.7.6) saves it with its own **Save**, and the first dialog then refers to it
       where it asked (the category chosen in the field that offered it); cancelling the
       first leaves it. One that fills in a record the first dialog's records own (a split, a
       plan line's reserve, a gift plan's occasion) edits the first dialog's draft: **Done**
       keeps its changes without saving them, **Cancel** puts back what it changed, and they
       are saved, or discarded, with the first dialog's.
