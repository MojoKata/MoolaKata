# S17.8. Packaging

8. **Packaging: one Docker (OCI) image for the server** (the connector has an image of its own,
   S18.10) holding its own Python and venv, the browser app, RapidOCR's models and the
   `moolakata` command, running as an unprivileged user (uid 10001). It serves on port 37373
   and takes two mounts: the **data directory** (database, keyring, receipts, linked copies)
   and the **backup directory**. `moolakata.toml` is mounted too, at `/etc/moolakata.toml`;
   where mounting a file is awkward, the same TOML is given in the environment variable
   `MOOLAKATA_CONFIG`, read when `--config` names no file. The configuration holds no secret
   either way: secrets never come from environment variables, and no key is mounted at all: the master key is the recovery phrase,
   entered after every start (S15.4). `install/compose.yaml` is the example to start from; it
   publishes the plain-HTTP listener on the host's loopback only (the proxy examples reach the
   service by name), gives the container the host's time zone (`/etc/localtime` and `TZ`,
   S14.9.2), and keeps the logs Docker holds to five files of 10 MB. The example
   `moolakata.toml` trusts only the proxy's own address (S13.3). `docs/operations.md` is the
   runbook: installing, upgrading, backups, health, logs, restoring and drills. The image is
   about 600 MB, most of it the receipt reader (ONNX Runtime, OpenCV and the models); the
   reader's worker takes about 350 MB more while it runs, which a host too small for it avoids
   by turning reading off (S9.8.7).
   1. **Architectures**: one multi-architecture image for **amd64** and **arm64**. A release
      builds each natively, on a GitHub runner of its own architecture (S17.10); a build of
      the other architecture on a developer's machine runs under QEMU emulation. Every
      dependency must install from a published wheel for both (onnxruntime, opencv, numpy,
      pi-heif, sqlcipher3 among them), so nothing is compiled in the image; a check fails
      when one has no arm64 wheel. Each architecture's release gate is `web/install/smoke.sh`
      on its own runner (a refused start, the welcome's key and first admin, a locked restart and
      its unlock, health, a sign-in, a receipt read, the connector's vault made on its page and
      its unlock after a restart, clean stops); the trial on household hardware
      (a Raspberry Pi, an arm64 NAS), which alone measures the reader's speed there
      (S9.8.4.5), is in the manual test plan (S17.9.7.8), and a release says whether it was
      run.
   2. **Published images.** Each release is published as `ghcr.io/mojokata/moolakata` and
      `ghcr.io/mojokata/moolakata-connector`, tagged with the version, one tag for both
      architectures. There is no other tag, no `latest` and none that moves: a server starts
      locked after every update (S15.4), so an upgrade is always the household's decision.
      Each image has a build-provenance attestation that anyone can check. The check
      `gh attestation verify oci://ghcr.io/mojokata/moolakata:<version> -R MojoKata/MoolaKata
      --signer-workflow MojoKata/MoolaKata/.github/workflows/release.yml --source-ref
      refs/tags/v<version> --deny-self-hosted-runners` passes only for an image that
      `release.yml` built from the version's tag on GitHub's own runners. Each release is
      also on Docker Hub, as `docker.io/mojokata/moolakata` and
      `docker.io/mojokata/moolakata-connector`, copied with the same digests, so the same
      attestation and the same check cover those copies.
      The compose files name them, so a host pulls them. The image can still be built from
      the source, and carried to a host with no internet access (`docker save` and
      `docker load`). Catalogs make the install a form rather than a file: TrueNAS's apps
      catalog first (S17.8.3.1); others may follow.
   3. **Documented hosts**: **Proxmox** (Docker in a VM, or in an LXC container with nesting
      on) and **TrueNAS** (a custom app from `install/compose.truenas.yaml`, its configuration
      in `MOOLAKATA_CONFIG` and a one-time step giving the datasets to the server's account,
      so nothing is typed in a shell). `DEPLOY.md`
      takes a test server onto each, step by step, from a fresh Debian VM on Proxmox VE and
      from TrueNAS Community Edition's **Install via YAML**; `operations.md` covers their
      mounts, backups and upgrades.
      1. **TrueNAS's catalog**: `publish/truenas/` holds MoolaKata and the MoolaKata
         Connector as two apps for TrueNAS's community catalog (`ix-dev/community/moolakata/`
         and `ix-dev/community/moolakata-connector/` in `truenas/apps`), each with its
         metadata, its install form, its compose template and its test values (one plain,
         one with a certificate, one on host paths and the host network). TrueNAS decides
         what its catalog includes; until the apps are in it, **Install via YAML** is the
         way, and once they are, TrueNAS's own update bot moves their images to each new
         release.
      2. **The server's form**: its time zone, in TrueNAS's own field, which a user's
         **Auto** zone follows (S14.9.2); the addresses browsers use, for the certificate the
         server makes for itself; the web port (37373); a certificate from **System ›
         Certificates**, or none for the server's own, its help saying that TrueNAS restarts
         the app when it renews the certificate and the server then starts locked (S15.4);
         the data and the backups storage, each an ixVolume (the default) or a host path,
         a host path given to the server's account when its top directory belongs to
         anyone else and it holds no files yet, its help saying that the folders above it
         must let the account through (an SMB dataset needs it given Traverse); the host
         network, the Docker networks to
         join and labels, as every catalog app has them; and limits of 2 CPUs and 4 GB.
      3. **The connector's form**: the same for its page (S18.11.1): its time zone; its
         addresses, at least one, since the first is the one MoolaKata links to and the
         install stops without it; its port (37374); a certificate, with the same help; one
         storage for its data; and limits of 1 CPU and 1 GB. Neither form offers extra
         environment variables or storage, which every other catalog app has: neither app
         has a setting to tune or reads anything outside its own storage, and the
         connector's one other variable, a development switch, would let it reach the
         addresses its egress check refuses.
      4. **What the templates fix**: `tls` mode, its configuration in `MOOLAKATA_CONFIG` (the
         connector's in its own variables); each image's own account (10001, 10002), which
         the catalog's permissions step gives the storage to, so there is no user and group
         section; the image's health check (alive, S13.6); no capabilities, no new
         privileges, `/tmp` and the socket's directory in memory; a read-only root
         filesystem unless a certificate is chosen, since compose copies a chosen
         certificate into the container and a read-only root can't take it; and notes,
         shown at install, on the welcome and the locked start.
      5. **Tried before TrueNAS sees them**: `check.sh` renders each test case with TrueNAS's own
         renderer, in a checkout of their catalog, starts it, and fails unless it came up
         alive, as its image's account, with the root filesystem the case calls for and the
         certificate it was given or made. `create-pr.sh` runs it, checks each image's
         provenance (S17.8.2) and pins it by its digest, and puts both apps on a branch of
         `truenas/apps` where TrueNAS's tools add their library and metadata. Nothing leaves
         the machine until the maintainer runs it again with `--open`, which pushes the
         branch to their fork and opens the pull request as a draft, or updates the open one.
         The request links the icons and screenshots TrueNAS copies to its own servers: the
         server's favicon, and in `publish/truenas/media/` the connector's icon (its page's
         mark) and screenshots of the release's pages over the dev seed's household.
   4. **TLS**: the example `compose.yaml` runs in `proxy` mode behind the household's
      reverse proxy. A second example runs `tls` mode with a self-signed certificate for
      testing on a local network (S13.3).
   5. **The base image's updates.** The Dockerfile pins its base by digest, so a rebuild
      changes nothing until the digest moves, and the image never runs `apt-get upgrade` at
      build: the same Dockerfile gives the same image. The digest moves with each release,
      and between releases when Debian or Python publishes a fix for something the image
      uses (OpenSSL, zlib, libjpeg, expat, SQLite, Python itself): `web/dev.sh base-update`
      fetches the tag's current digest, writes it into the Dockerfile and the register
      (`docs/dependencies.md`, with the date and what the move picked up), and prints the
      Debian packages that changed between the two for the commit message. `web/check`
      warns, without failing, when the pinned digest is older than 90 days, since the check
      needs the network and a release shouldn't fail on it.
