# Remove a Copy

A copy on this host, removed for good: a backup, the database as it was before a migration, or what
a restore set aside.

## Recovery phrase

The server's 12 words, as they are now. Removing a copy can't be undone, so it asks for the phrase
as well as your password: a session someone took over can't delete the backups. A wrong phrase
counts like a wrong password.
