# Receipts

How receipts are kept: encrypted in the data directory, each file once however often it is uploaded.
Backups hold the database alone; the host's own backup of the data directory keeps the files. A
receipt is a PDF, JPEG, PNG, WebP or HEIC file, checked from its content, never its name.

Reading runs without its file sandbox on a host that doesn't offer Landlock (Linux 5.13 or later,
and a container that allows it): the reader could then open the data directory. It still has no
network, and it still runs apart from the server. Admins have an alert while it lasts.

## Largest file (MB) {#receipt-max-mb}

The largest receipt that can be uploaded, 25 MB by default.

## Read receipts

MoolaKata reads each receipt's date, total and merchant on this server, with RapidOCR, and suggests
the transaction it belongs to. Nothing leaves the server, and no outside service or download is
involved. A PDF with text in it is read directly; a photo or scan is read by OCR. Turn it off on a
host too small to run it: receipts still upload and can be filled in by hand.

## Jobs at a time {#receipt-read-jobs}

How many receipts are read at once, each in its own process limited to 2 threads, a lower priority,
1.5 GB of memory and 60 seconds a receipt. A batch of uploads works through the queue. 1 suits
most hosts; more read a batch faster.

## Reading

The queue: receipts waiting, read, and those that couldn't be read, with the reason on each.

## Without its file sandbox {#file-sandbox}

Every file someone brings (a receipt, a statement, a photo, an OFX or CSV import) is opened only
by the reader's own process, never by the server, and that process gives up what it doesn't need
before it reads: it can open no network connection, and on Linux 5.13 or later (Landlock) it
can't open the data directory either. It uses Landlock wherever the host offers it. On a host
that doesn't (an older kernel, or a container that doesn't allow it), this section says the
reader runs without that file sandbox, and admins have an alert while it lasts; the reader still
has no network and still runs apart from the server.

## Re-read All Receipts

After an update with new models: every receipt is read again. Only empty fields, and those still
holding what was read before, are replaced; anything a person typed stays.
