# Deploying MoolaKata

How to put a MoolaKata server where people can start testing it, on the first two hosts it
targets: **a fresh VM on Proxmox VE** and **TrueNAS**. Both run the same image, and
both serve HTTPS themselves on port 37373 with a self-signed certificate (`tls` mode,
requirements S13.3), which is what a test on a local network needs. A server the household
relies on goes behind its reverse proxy instead ([`operations.md`](operations.md) §2), and
`operations.md` is the runbook for everything after the install: upgrades, backups, restoring,
keys and the connector.

The steps were run on Proxmox VE 9.2 with a Debian 13 guest and Docker Engine 29, and on
TrueNAS Community Edition 25.10.7, each pulling the published 0.1.0 images (§2) and, on the VM,
the compose file from the release's tag. The screenshots are from those hosts, and §5's from a
server built from the same source.

## 1. What you need

- **A host**: amd64 or arm64 (S17.8.1), with **2 GB of memory** for MoolaKata (1 GB with
  receipt reading turned off, Settings › Receipts) and about **3 GB of disk** for the image
  and the data.
- **Internet access** from the host to `ghcr.io`, where the images are published, and to
  `github.com` and `release-assets.githubusercontent.com` for the release's example files.
- **Paper and a pen.** The server's master key is a **recovery phrase** of 12 words, shown
  once and never stored (S15). It is asked for after every start of the server: a reboot, an
  upgrade, a restart. Without it the data can't be opened, by anyone.
- **A browser** on the same network as the host.

## 2. The image

Each release is published as `ghcr.io/mojokata/moolakata:<version>`, one tag for amd64 and
arm64 (S17.8.2). Docker pulls it the first time a command below needs it; the image is under
1 GB. This guide installs **0.1.0**. GitHub records how each release's image was built, and
anyone can check that the one they pulled is it
([`gh`](https://cli.github.com/) installed):

```sh
gh attestation verify oci://ghcr.io/mojokata/moolakata:0.1.0 -R MojoKata/MoolaKata \
  --signer-workflow MojoKata/MoolaKata/.github/workflows/release.yml \
  --source-ref refs/tags/v0.1.0 --deny-self-hosted-runners
```

It passes only for an image that MoolaKata's own release workflow built from the release's
tag, on GitHub's runners.

The same images, with the same digests, are on Docker Hub as `mojokata/moolakata` and
`mojokata/moolakata-connector`. To pull from there instead, change `ghcr.io/mojokata/` to
`mojokata/` in the compose file's `image:` lines. The check above works for them too, with
`oci://docker.io/mojokata/moolakata:0.1.0`. Docker Hub limits how often anyone not signed in
can pull. ghcr.io sets no such limit, which is why this guide uses it.

To build it yourself instead, from a checkout of the release's tag (about three minutes on a
VM with two cores), and to carry it to a host with no internet access:

```sh
git checkout v0.1.0                                                            # the release's source
docker buildx build -f web/install/Dockerfile -t ghcr.io/mojokata/moolakata:0.1.0 --load .
docker save ghcr.io/mojokata/moolakata:0.1.0 | gzip > moolakata-0.1.0.tar.gz   # where it was built
docker load -i moolakata-0.1.0.tar.gz                                          # on the host
```

The **MoolaKata Connector** (S18), which signs in to institutions that have a driver, is a
second image, `ghcr.io/mojokata/moolakata-connector:0.1.0`, and is not needed to try
MoolaKata: accounts are kept current from the files you upload. §8 adds it.

## 3. A fresh VM on Proxmox VE

[Proxmox VE](https://www.proxmox.com/en/products/proxmox-virtual-environment/overview) runs
MoolaKata in a Debian VM with Docker. If Proxmox isn't installed yet:
[download](https://www.proxmox.com/en/downloads/proxmox-virtual-environment/iso) the ISO and
follow the [installation guide](https://pve.proxmox.com/wiki/Installation).

### 3.1 Make the VM

The quickest fresh VM is Debian's own cloud image with
[cloud-init](https://pve.proxmox.com/wiki/Cloud-Init_Support): no installer to click through.
In the Proxmox web UI, select the node and open **Shell**, then:

1. **Fetch the image**, Debian 13 from
   [Debian's cloud images](https://cloud.debian.org/images/cloud/):

   ```sh
   cd /root
   wget https://cloud.debian.org/images/cloud/trixie/latest/debian-13-genericcloud-amd64.qcow2
   ```

2. **Put your SSH public key** in a file, for the VM's user: paste it into
   `/root/moolakata.pub` (`nano /root/moolakata.pub`). It is the `.pub` file in `~/.ssh` on
   your own computer; `ssh-keygen -t ed25519` there makes one if you have none.
3. **Make the VM**: 2 cores, 4 GB of memory (MoolaKata needs 2 GB; the rest leaves the
   receipt reader room), a 32 GB disk made from the image, and a cloud-init drive. `120` is the VM's id
   and `local-lvm` the storage for its disks: use a free id, and your storage if it differs
   (**Datacenter › Storage** lists them; a ZFS install calls it `local-zfs`).

   ```sh
   qm create 120 --name moolakata --cores 2 --memory 4096 --cpu host --ostype l26 \
     --scsihw virtio-scsi-single --net0 virtio,bridge=vmbr0 --agent enabled=1 \
     --scsi0 local-lvm:0,import-from=/root/debian-13-genericcloud-amd64.qcow2,discard=on,ssd=1 \
     --ide2 local-lvm:cloudinit --boot order=scsi0 --serial0 socket --vga serial0 --onboot 1
   qm disk resize 120 scsi0 32G
   qm set 120 --ciuser debian --sshkeys /root/moolakata.pub --ipconfig0 ip=dhcp
   qm start 120
   ```

   For a fixed address, use `--ipconfig0 ip=192.168.1.50/24,gw=192.168.1.1` instead of
   `ip=dhcp`. `--onboot 1` starts the VM when the Proxmox host starts.

   ![The node's Shell after the qm commands](deploy/proxmox-shell.png)

4. **Find its address**: your router's list of DHCP leases shows it under the name
   `moolakata`, unless you gave it a fixed one. (The VM's **Console** shows only its boot and
   a login prompt, and the user has no password: sign in over SSH.) Once
   `qemu-guest-agent` runs (§3.2), the VM's **Summary** shows the address under **IPs**. The
   rest of this section calls it `192.168.1.50`.

   ![The VM's Summary, with its address under IPs](deploy/proxmox-summary.png)

### 3.2 Install Docker

Sign in to the VM (`ssh debian@192.168.1.50`) and install Docker Engine from
[Docker's own repository for Debian](https://docs.docker.com/engine/install/debian/):

```sh
sudo apt-get update
sudo apt-get install -y ca-certificates curl qemu-guest-agent
sudo install -m 0755 -d /etc/apt/keyrings
sudo curl -fsSL https://download.docker.com/linux/debian/gpg -o /etc/apt/keyrings/docker.asc
sudo chmod a+r /etc/apt/keyrings/docker.asc
sudo tee /etc/apt/sources.list.d/docker.sources <<EOF
Types: deb
URIs: https://download.docker.com/linux/debian
Suites: $(. /etc/os-release && echo "$VERSION_CODENAME")
Components: stable
Signed-By: /etc/apt/keyrings/docker.asc
EOF
sudo apt-get update
sudo apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
sudo usermod -aG docker debian
sudo systemctl start qemu-guest-agent
sudo timedatectl set-timezone America/Chicago     # your own: backups and emails follow it
```

Sign out and in again, so `docker` works without `sudo`. `qemu-guest-agent` lets the Proxmox
UI show the VM's address on its **Summary**; it starts by itself at every boot after this one.

### 3.3 Set up

1. **Make a folder for the server**, with the release's example compose file:

   ```sh
   mkdir ~/moolakata && cd ~/moolakata
   curl -fsSLo compose.yaml https://github.com/MojoKata/MoolaKata/releases/download/v0.1.0/compose.tls.yaml
   mkdir data backups && sudo chown 10001:10001 data backups
   ```

2. **Write its configuration**, `moolakata-tls.toml`, naming the address browsers will use, so
   the self-signed certificate covers it:

   ```sh
   cat > moolakata-tls.toml <<'EOF'
   [server]
   name = "moolakata"
   mode = "tls"
   port = 37373

   [paths]
   data = "/var/lib/moolakata"
   backups = "/var/backups/moolakata"

   [tls]
   names = ["192.168.1.50"]
   EOF
   ```

3. **Start it**: `docker compose up -d moolakata`, which first pulls the image (§2): a minute
   or two the first time. Name the service: the compose file's other one is the connector,
   which needs a setup of its own before it starts (§8).
4. **Open it** in a browser: the welcome makes its master key and your account (§5).

### 3.4 After a reboot

The VM starts with the host (`--onboot 1`), and Docker starts MoolaKata with it
(`restart: unless-stopped`, S13.6), **locked**: open it and enter the phrase (§5).
`docker compose ps` in `~/moolakata` shows it `healthy` whenever it answers, locked or not;
`curl -k https://192.168.1.50:37373/healthz` says whether it is waiting for its phrase
(`locked`) or open (`ok`).

## 4. TrueNAS, installed manually

[TrueNAS Community Edition](https://www.truenas.com/truenas-community-edition/) 25.10
("Goldeye") runs apps as Docker Compose projects. These steps install MoolaKata by hand, as a
**custom app** from YAML; they work whether or not you use an app from TrueNAS's catalog, and
give full control of its datasets and configuration. If TrueNAS isn't installed yet:
[download](https://www.truenas.com/download/) the ISO and follow the
[installation guide](https://www.truenas.com/docs/scale/25.10/gettingstarted/install/).
The steps below use a pool named `tank` and the NAS's address `192.168.1.20`.

### 4.1 Pool, apps and datasets

1. **A pool**: **Storage › Create Pool**, if there isn't one.
2. **Apps**: open **Apps**. Until it has a pool it says *Apps Service Not Configured*:
   **Configuration › Choose Pool**, pick `tank`, **Choose**.
3. **Datasets**: **Datasets**, select `tank`, **Add Dataset**: name it `moolakata`, preset
   **Generic**, **Save**. Select `tank/moolakata` and add two datasets inside it the same
   way: `data` and `backups`. Separate datasets let snapshots and replication treat them
   apart (operations.md §2.3).

![The datasets](deploy/truenas-datasets.png)

### 4.2 Install the app

**Apps › Discover Apps**, then **⋮** (**More Options**, beside **Custom App**) **› Install
via YAML**. Name it `moolakata`, paste this as **Custom Config** (it is
`compose.truenas.yaml` among the release's files) with the NAS's address under
`[tls] names`, so the certificate covers it, and your pool's name in place of `tank`, then
**Save**:

```yaml
services:
  # Gives the two datasets to the server's account (uid 10001) before it starts, then ends:
  # root, with the one capability that takes, and no network.
  permissions:
    image: ghcr.io/mojokata/moolakata:0.1.0
    user: "0:0"
    entrypoint: ["chown", "10001:10001", "/var/lib/moolakata", "/var/backups/moolakata"]
    volumes:
      - /mnt/tank/moolakata/data:/var/lib/moolakata
      - /mnt/tank/moolakata/backups:/var/backups/moolakata
    network_mode: none
    read_only: true
    cap_drop: [ALL]
    cap_add: [CHOWN]
    security_opt: ["no-new-privileges:true"]
    restart: "no"
  moolakata:
    image: ghcr.io/mojokata/moolakata:0.1.0
    restart: unless-stopped
    depends_on:
      permissions:
        condition: service_completed_successfully
    ports:
      - "37373:37373"
    environment:
      # moolakata.toml, given here rather than as a file (S17.8).
      MOOLAKATA_CONFIG: |
        [server]
        name = "moolakata"
        mode = "tls"
        port = 37373

        [paths]
        data = "/var/lib/moolakata"
        backups = "/var/backups/moolakata"

        [tls]
        names = ["192.168.1.20"]
    volumes:
      - /mnt/tank/moolakata/data:/var/lib/moolakata
      - /mnt/tank/moolakata/backups:/var/backups/moolakata
      - /etc/localtime:/etc/localtime:ro
    read_only: true
    tmpfs:
      - /tmp
      - /run/moolakata:uid=10001,gid=10001,mode=0700
    cap_drop: [ALL]
    security_opt: ["no-new-privileges:true"]
    stop_grace_period: 10s
    logging:
      driver: json-file
      options: { max-size: "10m", max-file: "5" }
```

![Install via YAML](deploy/truenas-install-yaml.png)

Nothing is typed in a shell. The first service, `permissions`, gives the two datasets to the
server's account (uid 10001) and ends; MoolaKata starts once it has. `MOOLAKATA_CONFIG` is the
server's configuration, the same TOML as `moolakata.toml` on the VM (§3.3), given here so there
is no file to write.

The install pulls the image (§2), a minute or two the first time, and the app shows
**Running** within seconds of that, before anyone has opened it: Running means it answers, not
that it is open (§4.3). Then open it: the welcome makes its master key and your account (§5).
The NAS's time zone (**System › General Settings › Localization › Settings**) is the server's,
for backups and emails.

![The app, Running before the welcome](deploy/truenas-app-running.png)

### 4.3 Snapshots and restarts

- **Data Protection › Periodic Snapshot Tasks › Add**: **Dataset** `tank/moolakata`,
  **Recursive** ticked, **Save**; by default it keeps two weeks of daily snapshots. Nothing
  in them opens without the phrase; operations.md §2.3 says what a snapshot is and isn't.
- After the NAS restarts, the app starts again by itself (`restart: unless-stopped`),
  **locked**, until someone enters the phrase (§5).
- **Running doesn't mean open.** TrueNAS shows **Running** whenever MoolaKata answers: new,
  locked or open alike. Whatever restarts the app locks it: the NAS restarting (a TrueNAS
  update among them), the Apps service stopping or moving to another pool, and every **Edit**
  of the app's YAML, upgrades included (§6). `https://192.168.1.20:37373/healthz` says which
  it is, `uninitialised`, `locked` or `ok`, and an uptime monitor pointed at it notices a
  lock (operations.md §5).
- Deleting the app (the app's **Delete**) offers **Remove Images**, ticked. Either way the
  datasets stay as they are, and the image is pulled again by the next install.

## 5. The welcome

1. Open `https://<address>:37373` (`https://192.168.1.50:37373` for the VM,
   `https://192.168.1.20:37373` for the NAS). The browser warns that the certificate isn't
   trusted, since MoolaKata made it itself: continue to the site.
2. A new server shows **Welcome to MoolaKata**. Have paper and a pen ready, then **Show my
   recovery phrase**.

   ![The welcome](deploy/moolakata-welcome.png)

3. **Write the 12 words down**, in order, with the fingerprint. They're the master key, and
   nothing shows them again: keep two copies in two places, one of them offline, and never
   with the backups (S15.6). Every visit, or another browser, shows other words; only the ones
   you confirm become the key. Then **I've written them down**.

   ![The recovery phrase (blurred here: never put a real one in a picture)](deploy/moolakata-phrase.png)

4. **Type three of the words back**, by their number, then **Make the key**. MoolaKata writes
   its key and opens.
5. **Set up the admin account**: a name, sex, an email address and a password of at least 12
   characters. You sign in as **`admin`** from now on (S10.1.2).

   ![The admin's account](deploy/moolakata-setup.png)

6. Then the **Dashboard**. **Users and Groups** invites the other testers. An invitation is
   an email: until **Settings › Email** has an SMTP server, each is written to the mail folder
   instead, and **Settings › Email** lists them, with **Open** to show the link to pass on.
   The help pane (**F1**) explains every screen, and `/demo` on the same address is the
   clickable mockup with sample data.

   ![The Dashboard](deploy/moolakata-dashboard.png)

**After every restart** the server is **locked** until someone enters the phrase: the page
asks for the 12 words, and sign-in follows. Instead of the browser, the phrase can be entered on
the host: `docker compose exec moolakata moolakata keys unlock` in `~/moolakata` on the VM;
`sudo docker exec -it ix-moolakata-moolakata-1 moolakata keys unlock` on TrueNAS.

![The locked screen](deploy/moolakata-locked.png)

**Check a copy of the phrase** once a year with **Verify key** in Settings › Key storage, and
whenever you make a new copy; the yearly alert opens it.

## 6. A new release

1. Change the image's tag to the new version: in `compose.yaml` on the VM, then
   `docker compose up -d moolakata`, which pulls it; on TrueNAS, **Edit** under **Application
   Info** opens **Edit App YAML**, the YAML as TrueNAS keeps it (its comments gone and its keys
   in alphabetical order, `moolakata` before `permissions`): change the tag on both `image:`
   lines, and **Save** pulls it and makes the containers again.
2. Unlock it (§5). At the unlock the server copies the database aside and migrates it;
   operations.md §3 says how to go back.
3. The connector (§8), when you run it, takes the same version: its tag in the same
   `compose.yaml` and `docker compose up -d connector`, or its own app's YAML on TrueNAS. It
   comes back locked: unlock it on its page.

## 7. When something's wrong

- **It won't start**: `docker compose ps` shows it `Restarting`, since it tries again about
  once a minute. `docker compose logs moolakata` shows why, in a line beginning `refusing to
  start:`; operations.md §5.1 lists the usual causes. On TrueNAS the app shows **Stopped**,
  turning **Deploying** for a moment at each try, and its page has no container to show the
  log of: in **System › Shell**, `sudo docker logs --tail 5 ix-moolakata-moolakata-1` shows
  the line. Its paths are the container's: `/var/lib/moolakata` is `data` (on TrueNAS, the
  `data` dataset), `/var/backups/moolakata` is `backups`, and `/etc/moolakata.toml` is the
  configuration (on TrueNAS, `MOOLAKATA_CONFIG` in the app's YAML).
- **The page won't load**: it is `https://`, on port 37373. A browser that refuses the
  certificate outright was given an address the certificate doesn't name: add it under
  `[tls] names` and restart; the server makes a new certificate.
- **It says it's locked**: it waits for the phrase after every start (§5).
- **A key nobody wrote down**: if someone else on the network finished the welcome first, the
  new server asks for words you never saw. Stop it, empty its `data` and `backups` folders,
  and start it again: the welcome comes back, and nothing is lost on a new server. Remove
  everything in them, not only the keyring: a new key can't open the database left behind,
  and the server refuses to start beside it. On the VM, in `~/moolakata`:
  `docker compose stop moolakata`, then
  `sudo find data backups -mindepth 1 -delete` and `docker compose up -d moolakata`. On
  TrueNAS: **Stop** (■ under **Controls**, in the app's row), then in **System › Shell**
  `sudo find /mnt/tank/moolakata/data /mnt/tank/moolakata/backups -mindepth 1 -delete`,
  and **Start** in the same place.
- **A lost phrase**: a running, unlocked server can still make a new one: **Rotate** in
  Settings › Key storage, with a code from `keys break-glass` in place of the phrase
  (operations.md §7). Once it restarts without one, nothing opens the data.

## 8. The MoolaKata Connector

The connector (S18) signs in to institutions that have a driver (Schwab, and banks that run
OFX Direct Connect) and keeps their accounts current, holding the sign-ins in a vault of its
own that MoolaKata can't open. It serves a small page of its own on port **37374**, where its
vault is made, its words are given after every start, and it is paired with MoolaKata. The
vault's **12 words** are its own, apart from MoolaKata's recovery phrase: keep them in the
household's password manager.

![The connector's page, locked after a restart](deploy/connector-locked.png)

### 8.1 On the VM

1. In `~/moolakata`, name the address browsers will use for its page, so its certificate
   covers it, then start it:

   ```sh
   sed -i 's/MOOLAKATA_CONNECTOR_NAMES: ""/MOOLAKATA_CONNECTOR_NAMES: "192.168.1.50"/' compose.yaml
   docker compose up -d connector
   ```

2. Open `https://192.168.1.50:37374`, past the certificate's warning as for MoolaKata. **Welcome
   to MoolaKata Connector**, then **Show my words**: put the 12 words in the password manager,
   **I've kept them**, type three of them back, and **Make the vault**. The page then shows
   its status, unlocked.

   ![The welcome makes the vault](deploy/connector-welcome.png)

3. Pair it (§8.3).

### 8.2 On TrueNAS

It is an app of its own, beside MoolaKata's, and like it needs nothing typed in a shell.

1. **A dataset**: add a dataset `connector` inside `tank/moolakata`, as in §4.1.
2. **Apps › Discover Apps › More Options (⋮) › Install via YAML** again: name it
   `moolakata-connector`, paste this (it is `compose.connector-truenas.yaml` among the
   release's files),
   with the NAS's address in `MOOLAKATA_CONNECTOR_NAMES` and your pool's name in place of
   `tank`, and **Save**. Its first service, `permissions`, gives the dataset to the
   connector's account (uid 10002) and ends; the connector starts once it has.

   ![The connector's app beside MoolaKata's](deploy/truenas-connector-app.png)

```yaml
services:
  # Gives the dataset to the connector's account (uid 10002) before it starts, then ends:
  # root, with the one capability that takes, and no network.
  permissions:
    image: ghcr.io/mojokata/moolakata-connector:0.1.0
    user: "0:0"
    entrypoint: ["chown", "10002:10002", "/var/lib/moolakata-connector"]
    volumes:
      - /mnt/tank/moolakata/connector:/var/lib/moolakata-connector
    network_mode: none
    read_only: true
    cap_drop: [ALL]
    cap_add: [CHOWN]
    security_opt: ["no-new-privileges:true"]
    restart: "no"
  connector:
    image: ghcr.io/mojokata/moolakata-connector:0.1.0
    restart: unless-stopped
    depends_on:
      permissions:
        condition: service_completed_successfully
    ports:
      - "37374:37374"
    environment:
      MOOLAKATA_CONNECTOR_NAMES: "192.168.1.20"
    volumes:
      - /mnt/tank/moolakata/connector:/var/lib/moolakata-connector
      - /etc/localtime:/etc/localtime:ro
    read_only: true
    tmpfs:
      - /tmp
      - /run/moolakata-connector:uid=10002,gid=10002,mode=0700
    cap_drop: [ALL]
    security_opt: ["no-new-privileges:true"]
    stop_grace_period: 10s
    logging:
      driver: json-file
      options: { max-size: "10m", max-file: "5" }
```

3. Open `https://192.168.1.20:37374`, and make the vault as in §8.1 step 2.
4. Pair it (§8.3).

### 8.3 Pairing

1. In MoolaKata, **Settings › Connector › The connector reaches MoolaKata at** must be the
   address the connector reaches it at (`https://192.168.1.50:37373` on the VM,
   `https://192.168.1.20:37373` on the NAS): the pairing code carries it. Left empty, the code
   carries **Settings › General › Public URL**, which serves when the connector reaches that
   too.
2. **Settings › Connector › Pair** (your password again) shows a one-time code, good for 24
   hours: **Copy the code**.
3. On the connector's page, **Pair…**: paste the code, give the words, **Pair**. It shows the
   connector's fingerprint.
4. Back in **Settings › Connector**, compare that fingerprint with the one shown there. If they
   match, **Confirm** (your password again); until then it gets no sign-in and posts no file.
   Settings › Connector links to the connector's page from its first report, and the page
   shows the pairing confirmed from its next one, within 5 minutes.

   ![Settings › Connector, its page linked](deploy/settings-connector-page-link.png)
5. Each person then adds their sign-ins under **Profile › Connections**, sealed in their
   browser for the connector: MoolaKata stores them, and can't open them.

**After every restart** the connector is **locked** too, and MoolaKata alerts admins until it
is unlocked: open its page and **Unlock** with its words. Its page's other actions (**Lock**,
**Pair**, **Unpair**, **Reset**) each ask for the words as well; operations.md §8 covers
running it on another machine, unpairing a lost one, and lost words.
