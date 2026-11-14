# Pair a connector

A one-time code that pairs a connector with this server.

## Pairing code {#pairing-code}

Paste it into **Pair** on the connector's page, with its words, within 24 hours, or run the
command under it on the connector's host. The code holds this server's address, its
key's fingerprint and a one-time secret; it works once. The connector checks the fingerprint
before it sends anything, makes new keys for this pairing, and introduces itself. Both sides
then show the connector's fingerprint: compare them before trusting it. Pairing another
connector replaces the one paired, as Unpair does: its Connections stop and their accounts' sync
turns off.
