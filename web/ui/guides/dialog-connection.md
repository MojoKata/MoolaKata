# New connection

A sign-in at one institution, kept by the MoolaKata Connector. What you type is encrypted in
your browser for the connector before it is sent: MoolaKata keeps only what it can't read, until
the connector collects it, and never shows it back. Sealing asks for your password again when it
was given over 10 minutes ago, and waits until an admin has confirmed the connector's pairing.

## Institution {#driver}

Which driver fetches it: **Schwab** (its official Trader API, signed in on Schwab's own page),
or **OFX Direct Connect** (a bank or credit union that still runs an OFX server, with a username
and password). An institution neither reaches is kept current by the statements and exports
you download and upload yourself.

## Connection name {#label}

A name to tell it apart: *Schwab login*, *Credit union*.

## OFX server address {#ofx-url}

The institution's OFX Direct Connect address, from the institution or a directory such as
ofxhome.com. The sign-in you seal is bound to this address: the connector sends it there and
nowhere else, and if the address is changed later the connection asks for the sign-in again.

## ORG {#ofx-org}

The institution's OFX organisation name, as the directory lists it.

## FID {#ofx-fid}

The institution's OFX id, as the directory lists it.

## Routing number {#ofx-bank-id}

The bank's routing number, which a bank account's OFX request names; a card or an investment
account has none.

## Account type {#ofx-account-type}

Checking, savings, credit card or investment, as the OFX server expects it.

## Account number {#ofx-account-id}

The account's number at the institution, which the OFX server asks for. It is a setting, not a
credential: MoolaKata keeps it with the Connection and hands it to the connector, which sends it
to the OFX server.

## App key {#schwab-app-key}

Your Schwab developer account's app key, which the driver signs in with. It isn't a secret: the
sign-in is.

## How you sign in {#how-you-sign-in}

**Here, sealed for the connector**: the usual way; your browser encrypts what you type to the
connector's key, and MoolaKata can't open it. **An admin types it on the connector's host**: the
stricter way; the dialog shows the command, and MoolaKata never handles the credentials at all.

## App secret {#schwab-app-secret}

Your Schwab app's secret, which the driver signs in with beside the app key. A secret: sealed
for the connector with the sign-in, never seen by MoolaKata.

## The address you landed on {#landed}

After signing in on the institution's own page, the address your browser lands on. It carries
the sign-in for the connector; sealed here like a password. Schwab's lasts seven days.

## Username

Your username at the institution. Sealed for the connector.

## Password

Your password at the institution. Sealed for the connector, never seen by MoolaKata.

## Connect command {#connect-command}

For the stricter way: an admin runs it on the connector's host and types the credentials there.
