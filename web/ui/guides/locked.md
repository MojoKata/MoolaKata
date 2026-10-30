# MoolaKata is locked

The server has started and holds no key: the master key is the recovery phrase, which is
never stored. Until an admin enters it, the server serves this screen and nothing else, and
nobody can sign in. It locks again at every restart.

## Recovery phrase

The 12 words from the recovery sheet, in order, with spaces between them. Four letters of each
word are enough. The eye button shows what was typed. The phrase is checked against the
server's keyring: a wrong phrase is refused, and ten wrong ones in a row are refused for a
quarter of an hour. Every attempt is logged.

## Unlock

Opens the server. On the host, `docker compose exec moolakata moolakata keys unlock` does the
same: the two are equal ways in. Nothing of the phrase is kept once the data key is unwrapped.
The field doesn't autocorrect, capitalise, spell-check or remember what is typed, and masks it
until the eye shows it.

## Re-encrypting

When a re-encryption is due (scheduled in Settings › Key storage, brought by a rotation, or
interrupted before), the unlock runs it before the server serves: a verified backup first,
then the database, the secrets and the receipt files under a new data key, and the copies on
the host as chosen. This screen shows how far it has come; sign-in opens when it is done.

## Restarting

After **Rotate** or **Re-encrypt now** in Settings › Key storage, MoolaKata restarts itself and
this page waits for it, then shows the locked screen: unlock it with the phrase (the new one,
after a rotation), and the re-encryption runs first. If it hasn't come back within a minute,
start it on the host (`docker compose up -d`).
