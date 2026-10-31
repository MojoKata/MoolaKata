# Copies kept

How many days of backups the server keeps: every backup of each of the most recent days that
have one, 3 to 365. A second backup the same day, **Back up now**, never pushes out an earlier
day's.

## Days of backups kept

More days keeps more. Fewer days than the backups there are deletes some at the next backup,
which can't be undone.

## Recovery phrase

Asked only when the number is fewer than the days of backups kept: the server's 12 words, with
your password, so a session someone took over can't delete the backups. A wrong phrase counts
like a wrong password.
