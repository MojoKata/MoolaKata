# Running MoolaKata

How to install, upgrade, watch, back up and restore a MoolaKata server. The requirements say
what the server does (S13 architecture, S14 storage, S15 the master key, S17.8 packaging);
this page says what to do. Commands are run from the folder holding `compose.yaml`.

## 1. What runs where

One container, from one image (`moolakata:<version>`), as an unprivileged user (uid 10001),
listening on port 37373. It needs three things from the host, and one thing from a person:

| On the host     | In the container          | Holds                                          |
|-----------------|---------------------------|------------------------------------------------|
| `data/`         | `/var/lib/moolakata`      | the database, its keyring, receipts, linked copies, copies made before upgrades |
| `backups/`      | `/var/backups/moolakata`  | the daily backups                               |
| `moolakata.toml`| `/etc/moolakata.toml` (read only) | the configuration; never a secret       |

The master key is the **recovery phrase**, and it is never stored: a new server's page
welcomes its first admin and shows the phrase once, and after that the server starts locked
after every start (a restart, an upgrade, a reboot) until someone enters the phrase, on the
locked screen in a browser or with `docker compose exec moolakata moolakata keys unlock`
(S15.4). Nothing on the host holds a key, so the host can be snapshotted and backed up whole.

`install/compose.yaml` runs it behind the household's reverse proxy (`proxy` mode);
`install/proxy/` has Caddy, nginx and haproxy examples. `install/compose.tls.yaml` runs its
own HTTPS with a self-signed certificate, for trying it on a local network. Each release
has these files attached as they are at its tag
(`https://github.com/MojoKata/MoolaKata/releases/download/v<version>/<file>`).

### 1.1 Exposing only `/link/`

A linked server (S11) reaches this one at its own address under `/link/`; there is no
separate port. To let a linked household in without exposing the app, have the reverse proxy
pass only that path from the outside, for example with Caddy:

```
money.example.org {
    @link path /link/*
    handle @link {
        reverse_proxy moolakata:37373
    }
    respond 404
}
```

The app itself (`/ui`) stays reachable only on the household's own network or overlay.

## 2. Installing

1. **Get the image.** Each release is published as `ghcr.io/mojokata/moolakata:<version>`
   (and `ghcr.io/mojokata/moolakata-connector`), one tag for amd64 and arm64 (S17.8.2), which
   the compose files name: Docker pulls it the first time a command needs it. The same
   images, with the same digests, are on Docker Hub as `mojokata/moolakata` and
   `mojokata/moolakata-connector`, and either registry works in the `image:` lines.
   `gh attestation verify` checks that the image is the one the release workflow built from
   the release's tag ([`DEPLOY.md`](DEPLOY.md) §2 has the command). To build it yourself
   instead, from a checkout of the release's tag, or to carry it to a host with no internet
   access:

   ```sh
   git checkout v0.1.0                                                            # the release's source
   docker buildx build -f web/install/Dockerfile -t ghcr.io/mojokata/moolakata:0.1.0 --load .
   docker save ghcr.io/mojokata/moolakata:0.1.0 | gzip > moolakata-0.1.0.tar.gz   # on the build machine
   docker load < moolakata-0.1.0.tar.gz                                           # on the server
   ```

   `web/install/smoke.sh [linux/arm64]` builds both images for a platform and runs them
   once, as a release's gate does (S17.8.1): a refused start, the welcome's key and first
   admin, a locked restart and its unlock, health, a sign-in, a receipt read, the connector's
   vault and unlock, and clean stops. Another
   platform than the machine's own runs under QEMU (`docker run --privileged --rm
   tonistiigi/binfmt --install arm64`, once).
2. **Make the folders**, owned by the container's user:

   ```sh
   mkdir -p data backups && sudo chown 10001:10001 data backups
   ```

   Keep `backups/` inside what the host backs up, beside `data/` (S14.6): a backup here is the
   database only, and the host's own backup of both is what keeps the receipts. A further copy
   off the host is welcome, as long as the phrase never goes with it.
3. **Start it**: `docker compose up -d`, then point the reverse proxy at it and set
   `trusted_proxies` in `moolakata.toml` to the proxy's own address, never a whole range
   (S13.3): anything else in the range could pose as the proxy. The listener speaks plain HTTP
   in `proxy` mode, so the compose file publishes it on the host's loopback only. A proxy in
   the same compose project (`proxy/` is written that way) reaches `moolakata:37373` by name
   and has an address of its own to trust, which is the setup to prefer: the compose file fixes
   the project's range at `172.30.37.0/24` and gives its commented-out proxy `172.30.37.10`,
   the address the example `moolakata.toml` trusts. A proxy on the host reaches
   `127.0.0.1:37373` from the bridge's gateway, `172.30.37.1`, as every other process on the
   host does. The compose file gives the container the host's time zone (`/etc/localtime` and
   `TZ`), which backups and daily emails follow.
4. **Open it: the welcome.** With no keyring, the server starts uninitialised and its page
   welcomes the first admin (S15.4.4): **Show my recovery phrase** shows the 12 words once,
   three typed back make the key, and **Set up the admin account** makes `admin`, signed in at
   once (S10.1.2). The phrase is the key: nothing of it is written, and nothing shows it again.
   Store it as S15.6 says: two copies in two places, one offline, never with the backups.
   Whoever reaches a new server first can finish its welcome; one that asks for words nobody
   wrote down is stopped, its `data/` emptied (the database too: a new key can't open the
   one left behind), and started again. The welcome is the only way to make the key: no
   command shows a phrase, since Docker's log keeps what a container's terminal shows.
5. **Unlock it after every start**: it starts locked. Open the app and enter the phrase on the
   locked screen, or run `docker compose exec moolakata moolakata keys unlock` and type it
   there.

### 2.1 On Proxmox

- **In a VM**: [`DEPLOY.md`](DEPLOY.md) §3 makes a fresh Debian VM on Proxmox VE with Docker
  and runs a test server on it in `tls` mode; for real use, the same VM runs §2's steps, with
  `compose.yaml` behind your reverse proxy. Give the VM 2 GB of memory, or 1 GB with receipt
  reading turned off (Settings › Receipts).
- **In an LXC container** (*not yet tried on a real host*): turn on **nesting** (Options ›
  Features), install Docker inside, then as above.
- Proxmox's own backups of the VM or container can include everything: no key is on the
  disk, and nothing in them opens without the phrase.

### 2.2 On TrueNAS

[`DEPLOY.md`](DEPLOY.md) §4 installs it on TrueNAS Community Edition manually, step by step,
with nothing typed in a shell: two datasets for data and backups; a **custom app** from
**Install via YAML** (`install/compose.truenas.yaml`), with the datasets as host paths, a
one-time `permissions` step that gives them to uid 10001, and the configuration in
`MOOLAKATA_CONFIG` (the same TOML as `moolakata.toml`, which the server reads when no file is
named with `--config`); and the welcome, which makes the key and the admin.
Both datasets go into snapshot and replication tasks as they are: nothing in them opens
without the phrase. Unlock after each start (§2 step 5).

### 2.3 On ZFS, with snapshots and replication

- Snapshot and replicate the datasets holding `data/` and `backups/` as you do the rest of
  the host: nothing in them opens without the phrase, and a raw send of an encrypted dataset
  opens only with the dataset's own key as well. Keep the phrase out of them.
- Every snapshot and replica is a **copy** (S15.8): it opens with the phrase of its day for
  as long as it exists, and MoolaKata cannot see or prune it. After a rotation or a leak,
  the snapshots made before are yours to destroy, on both ends of the replication.
- The live database file in a snapshot is crash-consistent at best; the verified copy in
  `backups/` from the same day is the one to restore from.

## 3. Upgrading

1. **Read the release's notes** on the
   [releases page](https://github.com/MojoKata/MoolaKata/releases). A major release opens
   with **Before you upgrade**, which says what the upgrade needs from you. Do that first.
2. **Change the tags** in `compose.yaml` to the new version, on the `moolakata` and
   `connector` services' `image:` lines. The key commands run through the `moolakata`
   service, so they follow it. Then pull the new images and restart:

   ```sh
   docker compose pull
   docker compose up -d
   ```

   On TrueNAS, change the tags in each app's YAML instead ([`DEPLOY.md`](DEPLOY.md) §6). A
   host with no internet access loads the new images first (`docker load`, §2 step 1).
3. At the unlock the server copies the database into `data/pre-upgrade/` and checks the copy,
   then migrates it one revision at a time. The three newest copies are kept.
4. Unlock it (§2 step 5), and the connector on its page (§8 step 4). Then watch the server
   come up: `/healthz` answers `ok` once it serves.

**Going back** to the earlier release: stop it, set the old tag again, and restore the copy
made before the upgrade with `db restore data/pre-upgrade/<copy>` (or the last backup, §6). An
older release refuses a database that a newer one has migrated: it says so in a `refusing to
start:` line (§5.1).

## 4. Backups

- **The host backs up the files.** MoolaKata's own backup never copies the receipt files,
  the linked copies or anything else in `data/`: your backup of the host does (snapshots,
  replication, any backup tool), and `data/` is safe to back up whole, since nothing in it
  opens without the phrase. Put `backups/` inside what the host backs up too.
- **Every day** at the time in Settings › Backups, the server writes a coherent, verified
  copy of the database with its keyring into `backups/moolakata-<date>-<time>/`, with a
  `manifest.json` of each file's size and hash, so the host's backup holds a consistent
  database beside the live one it also picks up. **Backup pruning** keeps the number of
  copies set there (14 by default) and removes older ones. No backup runs while a
  re-encryption does; each waits for the other.
- **Now**: Settings › Backups › **Back up now**, or `docker compose exec moolakata moolakata db
  backup` on the host, which asks the running server; with the server stopped, `docker compose
  run --rm moolakata db backup`, with the phrase.
- A backup opens only with the phrase of its day; each carries its own keyring, and a rotation
  re-encrypts them (§7).
- A backup that fails raises an alert for admins (and an email, for those who chose it).

## 5. Watching it

- **Clocks**: keep the host's clock with NTP (as the connector's host and every linked
  household do): signed calls between servers and from the connector are refused when the
  clocks differ by more than a minute, and two-step codes drift with them.
- **Health**: the image checks itself every 30 seconds (`moolakata health`, which asks
  `/healthz`): it is healthy whenever the server answers, ready, locked or uninitialised, so
  `docker compose ps` (and an orchestrator waiting for healthy containers) shows `healthy`
  while the server waits for its phrase, and `unhealthy` only when nothing answers (S13.6).
  Whether it is ready is `/healthz`'s own answer. From outside,
  point an uptime monitor (Uptime Kuma, for example) at `https://<your address>/healthz`: it
  answers `{"status": "ok", "version": …}` once the server is unlocked and ready, 503 with
  `"re-encrypting"` while a re-encryption runs at the unlock, 503 with `"locked"` while it
  waits for the phrase, which is how anyone learns that a reboot happened and the phrase is
  needed, and 503 with `"uninitialised"` on a new server, until its welcome makes the key.
- **Alerts**: problems that need someone show in Alerts for admins, and are emailed to those
  who chose it: a failed backup, a price source, email, the bitcoin node or a linked server
  failing for longer than Settings › Alerts allows, and a recovery phrase not confirmed.
- **Logs**: one line per event on the container's output, `docker compose logs -f moolakata`.
  They never hold amounts, names of accounts or payees, secrets or passwords. The example
  compose files keep five files of 10 MB each.
- **Space**: Settings › Storage shows the size of the database and the receipts, and what
  could be removed by file pruning (S14.10).

### 5.1 When it won't start

A problem only you can fix stops the start with one line beginning `refusing to start:`
and exit code 78. The compose file tries again with Docker's back-off, which reaches once a
minute, so `docker compose ps` shows it `Restarting` until the cause is fixed or it is stopped
(`docker compose stop moolakata`). `docker compose logs moolakata` shows the line. The usual
causes:

| The line says                         | Do                                                      |
|---------------------------------------|---------------------------------------------------------|
| the keyring can't be read              | restore it with a backup (§6); a new server has no keyring at all, and starts uninitialised |
| the database has no keyring beside it  | restore a backup, which brings its keyring (§6); a new server whose welcome someone else finished is emptied instead (§2 step 4) |
| the config file has a problem, or a key it doesn't know | fix `moolakata.toml` as the line says |
| the data directory is in use          | another server, or a host command, is using the same `data/`: stop it |

A server that started but stays locked after the phrase was entered says why in its log
(`refusing to unlock:`): a database from a newer MoolaKata (run that release or a later one,
or restore a backup made by this one), or a keyring the phrase doesn't open (the wrong
phrase, or the keyring from another server: the line names its fingerprint).

## 6. Restoring

### 6.1 A backup onto the same server

1. Choose the backup: `ls backups/`. Check it first:
   `docker compose run --rm moolakata db verify-backup /var/backups/moolakata/<backup>`,
   which asks for the phrase and says when the backup was made, by its manifest; it refuses a
   backup whose name says another time.
2. Stop the server: `docker compose stop moolakata`.
3. Restore it: `docker compose run --rm moolakata db restore /var/backups/moolakata/<backup>`,
   with the phrase. It checks the backup again, refuses one from a newer release, and moves
   what it replaces (the database, its keyring and the linked copies) into
   `data/before-restore-<time>/` rather than deleting it. The receipt files stay where they
   are; when a re-encryption came after the backup, the restore re-wraps them to the backup's
   key, asking for the replaced keyring's phrase if it is another. A backup made under an
   earlier phrase restores under that phrase: the restore names it and asks first. Settings ›
   Storage then counts any file the restored database no longer names, with Remove.
4. Start and unlock: `docker compose up -d`, then §2 step 5. The server opens the restored
   database, migrates it if it came from an earlier release, and reports anything it can't
   open. Linked households pull their copies again in full. A backup older than the
   connector's pairing ends it: the restored server knows neither the pairing nor its
   Connections, so the connector forgets them and deletes their credentials at its next
   report; pair it again (§8 step 5), and each owner makes their Connections and enters their
   sign-ins again.
5. Once you're satisfied, remove `data/before-restore-<time>/`.

### 6.2 Onto a new host

1. Install the image and make the folders as in §2, but don't start it: a server started on
   an empty `data/` would welcome a new admin and make a new key, and the backup brings its own
   keyring, under its phrase.
2. Put `data/receipts/` back from the host's own backup, taken as near the backup's time as it
   has: a backup here holds no receipts (§4).
3. Copy the backup folder into the new `backups/`, then restore, start and unlock as in §6.1,
   steps 3 and 4. The restore checks the phrase opens the backup before it changes anything.

### 6.3 Drills

- **Monthly**: `docker compose run --rm moolakata db verify-backup`, with the phrase. It
  checks the newest backup's hashes, when it was made and that it opens, and changes nothing.
- **Yearly**: rehearse §6.2 into a throwaway folder on another machine or a scratch VM, with
  the phrase from its offline copy. That proves the backups, the phrase and these steps
  together. In the same sitting, check the phrase's copies are readable and check each with
  **Verify key** in Settings › Key storage (or `docker compose run --rm moolakata keys verify`,
  S15.6.5). Every unlock after a restart is a check as well.

## 7. Keys

- **Unlock after a start**: `docker compose exec moolakata moolakata keys unlock`, which hands
  the phrase to the server over its socket, or the locked screen in a browser. Nothing shows
  the phrase again: it is never stored.
- **Check a copy of the phrase**: **Verify key** in Settings › Key storage, or `docker compose
  run --rm moolakata keys verify`.
- **Rotate the master key** (S15.7.1): Settings › Key storage › **Rotate**. A rotation brings a
  new data key as well, so the data is re-encrypted. It asks for your password and the current
  phrase, lists every copy on the host (backups, pre-upgrade copies, before-restore folders)
  with **re-encrypt** (the default), **delete** or **leave** for each, shows the new phrase and
  asks three words back. MoolaKata then restarts itself, locked: unlock it with the new phrase
  and the re-encryption runs first, a few minutes, its progress on the locked screen. Store the
  new phrase before anything else. Settings › Key storage then says which copies, if any, still
  need the previous phrase; the host's snapshots and backups made before the rotation always
  do, until you destroy them. When nothing needs it, **Forget** it there and destroy its
  copies.
- **A lost phrase, the server still running** (S15.5.2): rotate before it ever restarts, with a
  break-glass code in place of the phrase. `docker compose exec moolakata moolakata keys
  break-glass` prints one; type it into **Rotate** within 15 minutes. It works once, and every
  admin is alerted that one was asked for.
- **Re-encrypt the data** (S15.7.2), the phrase unchanged: Settings › Key storage ›
  **Re-encrypt now**. MoolaKata restarts; unlock it and the re-encryption runs before the
  server serves, with its progress on the locked screen. Or, with the server stopped,
  `docker compose run --rm moolakata keys reencrypt`. For when the data key may have been read:
  a memory dump, or a debugging session on the live server. A leaked phrase calls for a
  rotation (below).
- **The maintenance shell**: `docker compose exec moolakata moolakata db shell`, beside the
  running server. Run with `docker compose run` instead (a server that won't start), it asks
  first: Docker's log keeps what it shows there.

### 7.1 When the key or phrase may have leaked

A leaked phrase is a leaked copy (S15.8): whoever has the phrase and any backup or copy of
`data/` made under it has everything in that copy, for ever. In this order:

1. Revoke and reissue every secret at its source: price-source keys, the bitcoin node's
   password, the SMTP password; unpair the connector and pair it again (§8).
2. Settings › Key storage › **Rotate**, store the new phrase in two places, then unlock with
   it after the restart, so its re-encryption runs. The leaked phrase no longer unlocks the
   server, and copies made from then on don't open with it.
3. Delete every backup and copy made before step 2, wherever it is: `backups/` (prune by hand:
   `rm -r backups/moolakata-<date>-*` for the old ones), the NAS or bucket, snapshots and VM
   images, `data/pre-upgrade/` and `data/before-restore-*/`. A copy you cannot delete is one
   the finder can read.
4. Then destroy the old phrase's sheet and password-manager entry.

## 8. The MoolaKata Connector

The connector (S18) keeps accounts current from their institutions, holding their credentials
where MoolaKata can't. It is the `connector` service in `compose.yaml`, from the
`moolakata-connector` image of the same version (`connector/Dockerfile`, built from
`connector/`), with a volume of its own, `connector-data`, that MoolaKata never mounts. It
calls out, to MoolaKata and to each driver's institution, and publishes one port, **37374**: its
own page, where its vault is made, its words given and its pairing done (S18.11). On TrueNAS it
is an app of its own (DEPLOY.md §8.2).

1. **Its image** is published beside MoolaKata's, as
   `ghcr.io/mojokata/moolakata-connector:<version>`, and pulled by the steps below; or build it
   (`docker buildx build -f connector/Dockerfile -t ghcr.io/mojokata/moolakata-connector:0.1.0
   --load connector`) and carry it over as in §2.
2. **Start it and make its vault**: set `MOOLAKATA_CONNECTOR_NAMES` in `compose.yaml` to the
   addresses browsers use for its page (its certificate names them, and MoolaKata links to the
   first), `docker compose up -d connector`, and open `https://<address>:37374`. Its welcome
   shows **12 words**: save them in the household's password manager, type three back, and the
   vault is made, unlocked. They open the connector's vault, and nothing else can. On a
   terminal instead, before the first start: `docker compose run --rm connector init`, which
   shows the words on the terminal only.
3. **Its page for anyone on the network** shows whether it is locked, what it is paired with,
   its last report and how many Connections work, never a name, an account or a credential;
   every action there asks for the words, and wrong ones are logged with their address. A
   certificate of your own instead of its self-signed one: `MOOLAKATA_CONNECTOR_TLS_CERT` and
   `MOOLAKATA_CONNECTOR_TLS_KEY`, mounted read only.
4. **Unlock it after every start** (a restart, an update, the host's reboot): **Unlock** on its
   page with the 12 words, or `docker compose exec connector moolakata-connector unlock`. They
   are never stored. MoolaKata alerts admins while it is locked.
5. **Pair it**: in MoolaKata, Settings › Connector › Pair shows a code; paste it into **Pair**
   on the connector's page with the words (or run `docker compose exec connector
   moolakata-connector pair <code>` with the vault unlocked) and compare the fingerprints both
   sides show. If they match, **Confirm** in Settings › Connector: until then
   the connector gets no sign-in and posts no file. If they differ, someone else answered the
   code: Unpair. Pairing makes the connector's keys and files the private halves of its action
   and sealing keys in the vault, so `pair` is refused while the vault is locked. The connector
   reaches MoolaKata at the address in the code: Settings › Connector's **The connector reaches
   MoolaKata at**, or, when it is empty, the public URL; never the link address. That address
   must resolve from inside the container: on one host, the compose service name or the host's LAN address,
   not `localhost`. It verifies MoolaKata's certificate: a public one, or one of MoolaKata's
   own whose fingerprint the code carries.
6. **Banks with nothing to fetch from** (UMB, say) have no driver: download their statements
   and exports and upload them to the account as usual (S1.3).
7. **Credentials typed on the host** (the stricter way, S18.7.2): `docker compose exec
   connector moolakata-connector connect <connection id>`, which shows the host the credentials
   will go to and asks you to confirm it, then asks for each field without echo and files them
   in the vault.
8. **Watching it**: `docker compose exec connector moolakata-connector status` says whether
   it is paired and locked, when it last reported, and each Connection's state; MoolaKata's
   Settings › Connector shows the same from its reports, and alerts when the connector is
   locked or silent for 15 minutes.
9. **On another machine** instead (a laptop): run the same image there with its own
   `connector-data` volume, reaching MoolaKata's address, and add where it calls from to
   Settings › Network › Allowed to connect; nothing else changes.
10. **Unpair**: Settings › Connector › Unpair in MoolaKata, or **Unpair** on the connector's
    page (or `moolakata-connector unpair` on the host); either way the connector deletes the
    credentials it held for that server, at its next report after an Unpair in MoolaKata. A
    locked connector deletes them at its next unlock; `unpair` on its host asks for the words
    to do it at once.
11. **Lost words**: `docker compose exec connector moolakata-connector reset` makes a new vault
    and new words and unpairs, telling MoolaKata (when it says MoolaKata couldn't be told,
    Unpair there); pair again (step 5), and every Connection's credentials are entered again. **Reset** on its page does the same with the words still known, when some
    may have been seen. A new connector whose page asks for words nobody wrote down (someone
    else finished its welcome first): stop it, empty its volume, start it again.
12. **Its logs** say what it did and what failed, never a credential, an amount or an account
    number beyond its last four digits: `docker compose logs -f connector`.
13. **A lost host or volume** (a stolen laptop, a disk sold with the volume on it): Unpair in
    MoolaKata at once. The copy holds the status key, so until then whoever has it can report
    that the connector is locked, and nothing more; the vault stays closed without the words,
    so no action key, no sign-in and no sealed credential, before or after, opens for them. Then make a fresh vault
    on the new host (its page's welcome), pair again, and have each owner enter their sign-ins again.
14. **A Connection that says *the server address changed***: its OFX server address was edited
    after the sign-in was filed. The connector sends nothing to the new address until the owner
    enters the sign-in again under Profile › Connections, which seals it with the new address
    and binds it there.
