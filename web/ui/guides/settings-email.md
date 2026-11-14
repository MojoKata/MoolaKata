# Email (SMTP)

How MoolaKata sends its emails: invitations, password resets, sign-up links and decisions, alerts.
Until a host is set, each email is written to the `mail` folder in the data directory instead, in
the clear, and listed here for an admin to pass its link on.

Emails go out in the background, so nothing waits on the mail server. They wait in the database,
which is encrypted. One that can't be sent stays queued and is tried again every five minutes,
until its link expires; one the server refuses outright is set aside, keeping only who it was for,
its subject and the error. This section shows the queue and the last error.

## Host {#smtp-host}

The mail server's name, such as your email provider's SMTP server or a relay on your network.
MoolaKata reaches only this host for email. Changing it asks for your password again and clears
the stored SMTP password, so it is never sent to the new host: type it again for that host.

## Port {#smtp-port}

587 for STARTTLS, 465 for TLS, 25 for a plain relay.

## Security {#smtp-security}

**STARTTLS** (on port 587) and **TLS** (on 465) encrypt the connection and check the server's
certificate. **None** sends in the clear: only for a relay on your own network.

## Username {#smtp-username}

The account to sign in to the mail server with, often an email address. Leave it empty for a relay
that needs none.

## Password {#smtp-password}

Kept encrypted as a secret, used only when sending, and never shown again: the field says when it
was set and by whom, and a new one typed replaces it. Many providers want an app password rather
than your own. Your password is asked again when it was given over 10 minutes
ago.

## From address {#smtp-from}

The sender emails show, such as `MoolaKata <money@example.com>`. Your provider may insist it matches
the username.

## Send a Test Email

Sends one to your own address now, through the saved settings, and says what failed if it couldn't.

## Written to the mail folder {#written-emails}

The emails written while no host was set, newest first: who each is for, its subject and when.
The eye at the end of its row shows one, links and all, after your password: a link in it signs someone in or resets
a password. Each file is removed once its link has expired: a password reset's after an hour, an
invitation's after a week, the others' after a day.
