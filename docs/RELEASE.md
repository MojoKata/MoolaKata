# Making a release

How a new version of MoolaKata reaches testers and households. A release is a `v<version>` tag
on `main` and a GitHub release that names it. The tag starts `.github/workflows/release.yml`
(requirements S17.10.2). It builds both images on an amd64 and an arm64 runner and runs
`web/install/smoke.sh` on each, which is the release gate (S17.8.1). It then pushes the images
to `ghcr.io/mojokata`, joins each image's two architectures under the version's tag, and
attests both images (S17.8.2). Everything before the tag happens in an ordinary pull request.
Everything after it is checking what was published.

The steps were written from 0.1.0's release. Every release from then on has a tag its
maintainer signs (§5). `web/release.sh` runs the steps done from a terminal, one command each
(§5–§9), and the checks that keep the setup working (§12). Run alone, it lists them.

## 1. Before you start

Settings, plans, limits and commands on GitHub and Docker Hub change over time. Each one
below links to the page it comes from, so recheck that page when a step stops matching what
you see.

- **Write access to `MojoKata/MoolaKata`.** The release and its tag are made there; a fork
  can open the release's pull request but not tag it.
- **A GPG key on your GitHub account** (**Settings › SSH and GPG keys**), to sign the tag
  (§5). See GitHub's [signing tags](https://docs.github.com/en/authentication/managing-commit-signature-verification/signing-tags)
  and [signature verification](https://docs.github.com/en/authentication/managing-commit-signature-verification/about-commit-signature-verification).
- **[`gh`](https://cli.github.com/)**, GitHub's command line. Get it from
  [cli.github.com](https://cli.github.com/) (for Linux, its
  [install page](https://github.com/cli/cli/blob/trunk/docs/install_linux.md) adds GitHub's
  package repository), and sign in once with `gh auth login`. `gh release verify` (§8) needs
  [version 2.81](https://github.com/cli/cli/releases/tag/v2.81.0) or later.
- **Docker** with buildx, to check what was published (§7).
- **A checkout set up for development** (`web/dev.sh setup`, README), for the regenerated
  files and `web/check`. Its remote for MojoKata/MoolaKata is called `upstream` below. In a
  clone of MojoKata/MoolaKata itself, that remote is `origin`. `web/release.sh` finds that
  remote by its address, whatever it is called.
- **The setup done once**, recorded in [`GENESIS.md`](GENESIS.md) with the steps and what was
  chosen. That covers the organization's package creation setting, the Actions settings,
  the rulesets on release tags and on `main`, immutable releases, the packages made public
  on ghcr.io, and Docker Hub's account, repositories, token and `docker-hub` environment.
  `web/release.sh setup` checks it (§12).

## 2. Pick the version

MoolaKata uses [semantic versioning](https://semver.org): `MAJOR.MINOR.PATCH` (`1.4.2`),
tagged `v` and the same numbers (`v1.4.2`). `release.yml` refuses a tag that isn't `v`
followed by `web/VERSION`'s text.

1. **MAJOR**: the upgrade needs something from the people who run or use the server, beyond
   changing the tag and unlocking. Examples are a migration that needs a step by hand or a
   guide, a configuration key to edit, a new mount, re-pairing the connector, and linked
   servers that must upgrade together. The release ships with its guide, and its notes open
   with it (§4).
2. **MINOR**: new features.
3. **PATCH**: fixes.

Any of them can carry a migration that the server runs by itself at the unlock. Once that
migration has run, an older release refuses the database. Going back then means restoring the
copy made before the upgrade (`operations.md` §3), and the notes' **Upgrading** section says
so. This lists the migrations since the last release. Read each one to decide whether any of
them needs something from people:

```sh
git diff --stat v0.1.0..upstream/main -- web/server/src/moolakata/store/alembic/versions/
```

The rule holds from 0.1.0 on, with no exception for 0.x. The first upgrade that needs a guide
is 1.0.0, unless 1.0.0 is released earlier by choice. What marks a release for testers is
being a pre-release on GitHub (§8) and the README's **Release** line, not its number.

**Tags.** Each image gets exactly its version's tag on both registries (`0.2.0`), plus the
build's per-architecture tags on ghcr.io. There is no `latest`, and no tag that moves to a
newer release. A server starts locked after every update (S15.4), so an automatic update
would leave it waiting for its phrase. Every upgrade should be someone's decision.

A version is never reused. Browsers keep the app's files for a year under `/ui/v/<version>/`,
and testers may already have pulled the images under that tag. A second build under the same
version would be served stale to the first group and silently replaced for the second.

**Between releases.** As soon as a release is published, `main` moves to the next minor
release with `-dev` (§9): once 0.2.0 is out, `web/VERSION` and the connector's version say
`0.3.0-dev`, so no build from `main` carries a released version. A `-dev` build's files
change under one version, so the server sends them without the year's cache (S17.3.5). The
next release's pull request gives the version the number this section picks, which may be a
patch or a major instead (§3 step 2). Until then the compose files, `DEPLOY.md` and
`operations.md` name the last release, since that is what they install. The tests check that
the compose files and `DEPLOY.md` name one release: `web/VERSION`'s on a release's commit, and
an earlier one between releases.

## 3. The release's pull request

1. **Branch from an up-to-date `main`**: `git switch -c release-0.2.0 main` once `main`
   matches MojoKata's.
2. **Change the version everywhere it is written by hand.** `web/VERSION` (the server's
   version, which the app, the API's document and the release workflow all read) and the
   connector's `connector/pyproject.toml` and `connector/moolakata_connector/__init__.py` go
   from the `-dev` version (§9) to the release's. The image tags in the four
   `web/install/compose*.yaml` files, the two TrueNAS catalog apps' `ix_values.yaml` and
   `app_version`s in `publish/truenas/`, `docs/DEPLOY.md`, `docs/operations.md` and the
   README's **Release** line go from the last release to this one. From the repository's root:

   ```sh
   git fetch upstream --tags
   dev=$(cat web/VERSION) new=0.2.0                                  # main's -dev version, and this release
   old=$(git describe --tags --abbrev=0 --match 'v[0-9]*' upstream/main)
   old=${old#v}                                                      # the last release, 0.1.0
   sed -i "s/${dev//./\\.}/$new/" web/VERSION connector/pyproject.toml connector/moolakata_connector/__init__.py
   git grep -lF "$old" -- web/install publish/truenas docs/DEPLOY.md docs/operations.md README.md |
     xargs sed -i "s/${old//./\\.}/$new/g"
   git diff --stat        # 14 files
   ```

   Then read the diff for two lines that need a person's judgement:
   - `DEPLOY.md`'s second paragraph says which release its steps were run with. Put the old
     version back there until §10 has run them with the new one.
   - The README's **Release** line still says *a pre-release for testers*. Keep that
     unless this release is meant for households to rely on.

   The `0.1.0`s left in the dev seed (`seed_connector.py`, `seed_links.py`), in the tests and
   in the hand-written mockup are sample data, and stay as they are.
3. **Move the base image** (S17.8.5). Both Dockerfiles pin `python:3.14-slim-bookworm` by
   digest, and the digest moves with each release:

   ```sh
   web/dev.sh base-update --packages
   ```

   It writes the new digest into both Dockerfiles and records the move in `web/audit.json`.
   It also prints the Debian packages that changed, for the commit message and the release
   notes. Bring the base image's row in `docs/dependencies.md` up to date by hand: the date
   it last moved and what the move picked up.
4. **Regenerate what carries the version**: the API's OpenAPI document (S13.8.9), in a few
   seconds, and the generated mockup, in about ten minutes:

   ```sh
   web/dev.sh codegen                                                       # web/ui/api/openapi.json
   web/dev.sh mockup                                                        # docs/mockups/MoolaKata-app.html
   ```

   The mockup's diff is the version alone, in its `mk-version` meta tag and the recorded
   `/ui/api/session` and `/ui/api/unlock` answers. Anything more means `main` had drifted
   already. Find out why before going on.
5. **Bring every document that goes with the release up to date**, in this same pull
   request. Its documents describe the release from the moment it is tagged. Start from
   what changed since the last release, `git log --oneline v0.1.0..upstream/main`, and
   check each document against it:
   1. **README**: the **Release** line and the **Status** paragraph.
   2. **`docs/DEPLOY.md`**: every step the release changed (a setting, a screen, a port, a
      file), and new screenshots of the screens that now look different. Its second
      paragraph waits for §10.
   3. **`docs/operations.md`**: the runbook for anything the release changed, such as
      upgrading, commands, configuration keys and backups.
   4. **`docs/test-plan.md`**: a test for anything new that the build can't try by itself.
   5. **The app's guides** (`web/ui/guides/`), which ship inside the image. Each screen the
      release changed must still read true. Retake the screenshots of those screens with
      `web/dev.sh help-shots <key> …`.
   6. **`docs/api.md`, `docs/connector-protocol.md` and `docs/link-protocol.md`**: every
      change to the API, the connector's protocol or the link protocol since the last
      release. The release notes say what each change means for a server and a connector,
      or for two linked servers, that are at different releases (§4).
   7. **`docs/dependencies.md`**: the base image's row (step 3), and any library whose
      **Revisit** has come due.
   8. **`docs/requirements/`**: they carry no versions, so nothing changes for the release
      itself. Check that the README's tables of gaps and open questions match what this
      release leaves open.
6. **Run every check**: `web/check`, which takes about 20 minutes, and look for its last line,
   `all checks passed`. A compose file or a `DEPLOY.md` tag left at the old version fails
   `test_install.py`.
   The generated mockup's crawl sometimes fails without a diff: a Playwright route-handler
   error, or a screen that *drew nothing in 20 s*. When that is the only failure, run it
   again alone, `web/dev.sh uv run --frozen python ../ui/mockup/build.py --check`.
7. **Commit and open the pull request** against `MojoKata/MoolaKata`'s `main`, titled
   `Release 0.2.0`. Because it touches `web/install/`, two workflows run on it: `check`
   (`web/check`, about half an hour) and `release`, which builds both images and smoke-runs
   them on both architectures without pushing anything. A green pull request means the tag
   will build.
8. **Squash-merge it.** Nothing else should merge between this and the tag. If something
   does, the tag goes on the release's commit rather than on `main`'s head (§5).

## 4. The release notes

The notes tell a tester what changed, how to upgrade, and what was tried by hand. Write them
before tagging, so the release page is complete the moment it appears. A starting point:

```markdown
For testers. A new install follows docs/DEPLOY.md; a server you already run upgrades with
DEPLOY.md §6, then unlocks.

## Before you upgrade
(A major release only: what the upgrade needs from you, step by step.)

## What's new
- (one line for each pull request merged since v0.1.0)

## Upgrading
(A release with a migration:) At its first unlock the server copies its database to
data/pre-upgrade/ and migrates it by itself; an older release can't open it after that, so
going back means restoring that copy (docs/operations.md §3). (A release without one:) Going
back is setting the old tag again. The connector takes the same version.

## Compatibility
(What a server at this release and a connector or linked server at the last one do
together, or that both must be upgraded.)

## Tried by hand (docs/test-plan.md)
Run: T10 on Proxmox VE 9.2 with a Debian 13 guest; T11 on TrueNAS 25.10.7 (by whom).
Not run: T1–T9, T12, T13.

## Images
ghcr.io/mojokata/moolakata:0.2.0 and ghcr.io/mojokata/moolakata-connector:0.2.0, for amd64
and arm64, each with a build-provenance attestation:
gh attestation verify oci://ghcr.io/mojokata/moolakata:0.2.0 -R MojoKata/MoolaKata \
  --signer-workflow MojoKata/MoolaKata/.github/workflows/release.yml \
  --source-ref refs/tags/v0.2.0 --deny-self-hosted-runners
```

- **Before you upgrade**: a major release's guide (§2), placed first so that nobody
  upgrades without reading it. Leave the section out of any other release.
- **What's new**: list the pull requests since the last tag with
  `git log --format='- %s' v0.1.0..upstream/main`. Each squash commit's subject ends in its
  number, and GitHub links `(#9)` to the pull request. GitHub's own list, with authors,
  comes from `gh api repos/MojoKata/MoolaKata/releases/generate-notes -f tag_name=v0.2.0
  -f previous_tag_name=v0.1.0 --jq .body`
  ([generate release notes](https://docs.github.com/en/rest/releases/releases#generate-release-notes-content-for-a-release)).
  Add the base image's move from §3 step 3, naming the Debian packages it picked up.
- **Compatibility**: comes from the protocol changes found in §3 step 5.
- **Tried by hand**: the manual test plan requires every release to say which of T1–T13
  were run, by whom and on what, and which were not (S17.9.7.8). That includes T7, the arm64
  image on household hardware, which no runner replaces.
- Link to the documents at the tag (`https://github.com/MojoKata/MoolaKata/blob/v0.2.0/docs/DEPLOY.md`),
  so a later change on `main` doesn't move the instructions under an old release.

## 5. Tag the release

The tag and the release are made separately, about five minutes apart:

1. The maintainer signs the tag by hand with their own GPG key and pushes it (this section).
2. The push starts `release.yml`. It builds both images, smoke-runs them, publishes them to
   ghcr.io, and joins and attests each one. It then copies them to Docker Hub with the same
   digests, and drafts the GitHub release with the tag's install files attached (§6).
3. The maintainer checks the published images (§7).
4. Only then does the maintainer publish the draft with its notes, using `gh release edit`
   (§8).

Until that last step there is only a draft, which only people with write access can see.
Testers see nothing, never a release page without its images. A failed build can be fixed
and tagged again under the same version (§11). Once published, the release is immutable
(GENESIS.md §3 step 3). Its tag and files are locked for good, and only its title and notes
can still change. GitHub's **Draft a new release** form isn't used at any point, because a
tag it makes carries no signature.

`web/release.sh sign 0.2.0` does the three steps below. It checks that `web/VERSION` says
`0.2.0` on the commit it tags (MojoKata's `main`) and that no `v0.2.0` exists yet, shows the
commit, the tagger and the key, and asks before signing and again before pushing. To tag
another commit (step 1), give it as well: `web/release.sh sign 0.2.0 <commit>`. Run it where your own GPG key and
your own push access are, since the tag carries the signature of whoever runs it.

1. **Find the release's commit**:

   ```sh
   git fetch upstream
   git log --oneline -1 upstream/main       # Release 0.2.0 (#NN)
   ```

   If something merged after the release's pull request, tag that pull request's commit
   instead of `upstream/main`.
2. **Sign the tag**, and check its signature:

   ```sh
   git tag -s v0.2.0 -m "MoolaKata 0.2.0" upstream/main
   git tag -v v0.2.0                        # gpg: Good signature from …
   ```

   GitHub shows the tag as **Verified** when two things hold. The key must be on your GitHub
   account. The tagger's email (`git config user.email`) must be one of the key's addresses,
   verified on that account
   ([signature verification](https://docs.github.com/en/authentication/managing-commit-signature-verification/about-commit-signature-verification)).
3. **Push the tag.** The push starts `release.yml` (§6):

   ```sh
   git push upstream v0.2.0
   ```

## 6. Watch the workflow

**Actions › release** shows the tag's run. `web/release.sh watch 0.2.0` follows it in the
terminal, names any job that failed, and then lists the draft's files. It runs:

```sh
gh run watch -R MojoKata/MoolaKata "$(gh run list -R MojoKata/MoolaKata --workflow release.yml \
  --branch v0.2.0 --limit 1 --json databaseId --jq '.[0].databaseId')"
```

Five jobs. The first three took about two minutes in all at 0.1.0:

1. **build and smoke (amd64)** and **build and smoke (arm64)**, side by side, on runners
   of their own architecture. Each first checks that the tag names `web/VERSION`, then runs
   `smoke.sh`, then pushes its images as `0.2.0-amd64` or `0.2.0-arm64`.
2. **one tag per image, attested**, once both have passed. It joins each image's two
   architectures under `0.2.0` and attests each joined image.
3. **the images copied to Docker Hub**, after that. It copies both joined images to
   `docker.io/mojokata/…:0.2.0` as they are, and checks that each copy's digest is the
   original's. The attestations were made for those digests, so they verify the copies too.
   It runs in the `docker-hub` environment, the only place Docker Hub's token can be read
   (GENESIS.md §5). If Docker Hub isn't set up yet, the job copies nothing and leaves a
   warning on the run.
4. **the release drafted, with the tag's install files**, beside the copy. It drafts the
   release *MoolaKata 0.2.0* and attaches, from the tagged commit:
   1. the four `compose*.yaml` files;
   2. the example `moolakata.toml`;
   3. the proxy examples (`Caddyfile`, `nginx.conf`, `haproxy.cfg`).

   This is the only job whose token can write to the repository. The ruleset (GENESIS.md §3
   step 2) still keeps it from creating or moving a release tag. The draft shows under
   **Releases** to people with write access, or with `gh release list -R MojoKata/MoolaKata`.

![0.1.0's run of release.yml: the two builds, then the joining and attesting](release/release-run.png)

The picture is 0.1.0's run, which had only the first three jobs. From 0.2.0 on, the Docker Hub
copy and the draft follow the joining job.

A failure says which step failed in the run's annotations (the job's page, or
`gh api repos/MojoKata/MoolaKata/check-runs/<job id>/annotations`). §11 says what to do next.

## 7. Check what was published

`web/release.sh check 0.2.0` runs these checks and prints a line for each, `ok` or `FAIL`.
If anything fails, don't publish the release (§11). It checks the Docker Hub copies'
attestations at `registry-1.docker.io`, the address Docker Hub's registry answers on, because
`gh` reads `docker.io` as `index.docker.io`, which some networks block. Its pulls use an empty
Docker configuration, so they sign in nowhere and leave your own logins as they are. By hand:

```sh
for registry in ghcr.io docker.io; do
  for image in moolakata moolakata-connector; do
    docker buildx imagetools inspect $registry/mojokata/$image:0.2.0                # linux/amd64 and linux/arm64
    gh attestation verify oci://$registry/mojokata/$image:0.2.0 -R MojoKata/MoolaKata \
      --signer-workflow MojoKata/MoolaKata/.github/workflows/release.yml \
      --source-ref refs/tags/v0.2.0 --deny-self-hosted-runners
  done
done
docker logout ghcr.io && docker pull ghcr.io/mojokata/moolakata:0.2.0            # pulls without signing in
docker logout docker.io && docker pull docker.io/mojokata/moolakata:0.2.0
```

1. Each `inspect` lists both platforms under one index, and shows the same digest on both
   registries.
2. Each `verify` passes only for an image that this repository's `release.yml` built from the
   tag `v0.2.0`, on GitHub's own runners
   ([`gh attestation verify`](https://cli.github.com/manual/gh_attestation_verify)). The
   image's attestation was signed through Sigstore by the workflow's own identity, so no key
   is kept anywhere. It is kept in GitHub's attestation store, where `gh attestation verify`
   finds it by the image's digest, rather than as a tag beside the image: on ghcr.io such a
   tag (`sha256-<digest>`) would show as the package's newest version. Docker's own signing,
   Content Trust, isn't used: Docker is
   [retiring it](https://www.docker.com/blog/docker-content-trust-retirement-and-migration-guidance/).
3. The anonymous pulls prove both registries serve the images to anyone.

## 8. Publish the release

Once §7's checks pass, publish the draft that §6 made, with the notes from §4 saved as
`notes-0.2.0.md`. Then check what GitHub attested. `web/release.sh publish 0.2.0
notes-0.2.0.md` does all of it: it first checks that the draft holds exactly the tag's
install files, then asks for the tag to be typed back before publishing, and verifies the
release and each of its files afterwards. By hand:

```sh
gh release edit v0.2.0 -R MojoKata/MoolaKata --draft=false --prerelease \
  --notes-file notes-0.2.0.md
gh release verify v0.2.0 -R MojoKata/MoolaKata                   # the release attestation GitHub signed
gh release download v0.2.0 -R MojoKata/MoolaKata -p compose.yaml -D /tmp/v0.2.0
gh release verify-asset v0.2.0 /tmp/v0.2.0/compose.yaml -R MojoKata/MoolaKata   # one of its files
```

Keep `--prerelease` while releases are for testers (0.1.0 was one), and leave it out for a
release meant for households (`web/release.sh publish 0.2.0 notes-0.2.0.md --households`).

![0.1.0's release page: a pre-release, its tag and commit, its notes and its files](release/release-page.png)

This is 0.1.0, published through GitHub's web form before releases were drafted with their
files; its eight install files were attached afterwards (`web/release.sh attach`). It shows
the pre-release badge, the tag and the commit, the notes, and under **Assets** the eight
files, each with its SHA-256, beside the two source archives GitHub adds to every release.
Before publishing, check that the draft's **Assets** list all eight install files.

Publishing makes the release immutable. From then on its tag can't be moved or deleted,
nothing can be attached to it or removed from it, and deleting the release would retire its
version for good
([immutable releases](https://docs.github.com/en/code-security/concepts/supply-chain-security/immutable-releases)).
Its title and notes can still be edited, with `gh release edit` or the release page's
**Edit**
([managing releases](https://docs.github.com/en/repositories/releasing-projects-on-github/managing-releases-in-a-repository)).
The commands are in `gh`'s manual: [`release edit`](https://cli.github.com/manual/gh_release_edit),
[`release verify`](https://cli.github.com/manual/gh_release_verify) and
[`release verify-asset`](https://cli.github.com/manual/gh_release_verify-asset). GitHub's
[verifying release integrity](https://docs.github.com/en/code-security/how-tos/secure-your-supply-chain/secure-your-dependencies/verify-release-integrity)
explains what they check.

Then **move Docker Hub's pull commands to the new tag.** Each repository's overview on Docker
Hub shows `docker pull mojokata/<image>:<version>` (GENESIS.md §5 step 2), and nothing
updates it by itself. Sign in to [Docker Hub](https://hub.docker.com) as `mojokata`, go to
**My Hub › Repositories**, and for `moolakata` and then `moolakata-connector` open the
repository, choose **Edit** under **Repository overview**, change the version in the pull
command to `0.2.0`, and choose **Update**
([repository information](https://docs.docker.com/docker-hub/repos/manage/information/)).
Change its **Status** line too if the release changes it (from *alpha*, say).

## 9. Open the next version

As soon as the release is published, `main` moves on to the next minor version with `-dev`
(`0.3.0-dev` after 0.2.0), so that nothing merged from then on builds under the release's
number (§2). It waits until the release is published because a failed build is tagged again
under the same version (§11). The next release's pull request gives the version the number
it really takes (§3 step 2).

1. **Branch from an up-to-date `main`**: `git switch -c next-0.3.0 upstream/main`.
2. **Set the version**: `web/release.sh next 0.3.0`. It checks that `web/VERSION` names a
   published release and that `0.3.0` comes after it. It then writes `0.3.0-dev` into
   `web/VERSION`, `connector/pyproject.toml` and `connector/moolakata_connector/__init__.py`,
   and regenerates the API's document, `web/ui/api/openapi.json`.
3. **Regenerate the generated mockup**: `web/dev.sh mockup`, in about ten minutes. Its diff
   is the version alone, as in §3 step 4.
4. **Run every check** (`web/check`), then commit and open the pull request, titled
   `Open 0.3.0-dev`, and squash-merge it. The compose files and the documents still name
   the published release, which is what they install.

## 10. Run DEPLOY.md with the release

The release isn't finished until its documented install has been run with the published
images:

1. **Upgrade a test server** on each host as `DEPLOY.md` §6 says, and **install one fresh**
   where the steps changed. Once it is unlocked, the app's sidebar shows the new version
   under the household's name, and the connector's page shows it beside its name:

   ![The version in MoolaKata's sidebar](release/version-app.png)

   ![The version on the connector's page](release/version-connector.png)

2. **Record the run** in a small pull request. `DEPLOY.md`'s second paragraph names this
   release and the versions of the hosts it was run on. Every other document already went
   with the release (§3 step 5), so the only other changes are fixes the run found. For
   0.1.0 this was the pull request *0.1.0 is published: DEPLOY.md run with the release
   itself*.
3. **Add the runs to the release's notes** (T10, T11 and any other test from the plan):
   `gh release edit v0.2.0 -R MojoKata/MoolaKata --notes-file notes-0.2.0.md`.

## 11. When something goes wrong

Before §8 there is only a draft, so a version can still be tagged again. The next run's
draft replaces any draft an earlier run made. A wrong tag is deleted by a maintainer, because
the ruleset (GENESIS.md §3 step 2) lets only them:

```sh
git push upstream :refs/tags/v0.2.0      # GitHub's tag
git tag -d v0.2.0                        # your own copy
```

- **The tag doesn't name the version** (*the tag names this version* fails): nothing was
  pushed. Delete the tag and repeat §5 on the right commit.
- **A build or smoke run fails.** No `0.2.0` exists on ghcr.io yet, at most the other
  architecture's `0.2.0-<arch>`. If the cause is outside the code (a runner, the network),
  use **Re-run failed jobs** on the run. If the code is at fault, delete the tag, fix the
  code in a pull request, and tag the same version again (§5). The next run overwrites the
  per-architecture tags.
- **The joining or attesting job fails**: **Re-run failed jobs**. It reads only the
  per-architecture images the builds pushed, so it can run again on its own.
- **The Docker Hub job fails** (Docker Hub down, or the token expired): renew the token if
  it has expired (§12), then **Re-run failed jobs**. The copy can run again on its own, and
  ghcr.io and the draft don't depend on it. If it still can't run, `web/release.sh copy
  0.2.0` makes the same copy from your terminal, signed in to Docker Hub as `mojokata`.
- **The drafting job fails**: **Re-run failed jobs**. It deletes any draft for the tag before
  making its own, so a rerun never leaves two. A draft that ends up without all its files
  takes them from the tag with `web/release.sh attach 0.2.0`.
- **§7 finds something wrong with the joined images**: `0.2.0` is on ghcr.io, and anyone may
  have pulled it. Don't publish its release and don't move its image. Fix forward with a new
  patch (`0.2.1`), whose notes say that 0.2.0 was skipped and why.
- **Something is wrong after the release is published**: the release is immutable. Fix
  forward with a new patch (`0.2.1`), and say in `0.2.0`'s notes what is wrong with it.

## 12. Upkeep

What keeps releases working between them. `web/release.sh setup` checks everything
`GENESIS.md` set up: immutable releases, the tag ruleset and its bypass list, the
`docker-hub` environment with its secret and variable, and both registries' repositories
being public (GENESIS.md §7). Some of these only an admin can read, so run it signed in to
`gh` as a maintainer: before each release, and after any change below.

- **Docker Hub's token, every year.** The token stops working on the expiry date set in
  GENESIS.md §5 step 3, and then only the Docker Hub copy fails (§11). Before that date, make
  a new token the same way (Repo Read & Write, at most a year), then run `web/release.sh
  token`. It checks that the token signs in as `mojokata`, without touching your own Docker
  logins, and stores it as the `docker-hub` environment's secret `DOCKERHUB_TOKEN`. Then
  revoke the old token in Docker Home (**Account settings › Personal access tokens**), set
  the next reminder, and write the new expiry date into GENESIS.md §5 step 3. `setup` warns
  once the secret was set more than 11 months ago.
- **A token that may have leaked** (in a log, a screenshot, a lost laptop): revoke it in
  Docker Home at once, then make and store a new one as above. Run `web/release.sh check`
  for each release since the token was made: a Docker Hub copy whose digest isn't ghcr.io's
  wasn't made by `release.yml`, and `web/release.sh copy` puts the right one back. See
  Docker's
  [personal access tokens](https://docs.docker.com/security/access-tokens/personal-access-tokens/).
- **The open-source program, every year, once joined.** A Docker-Sponsored Open Source
  membership lasts a year (GENESIS.md §5 step 5, which says whether the namespace has one).
  Renew it when Docker asks, through the same
  [program](https://docs.docker.com/docker-hub/repos/manage/trusted-content/dsos-program/).
  If it lapses, anyone not signed in is held to the pull limit again.
- **The Docker Hub account.** Two-factor authentication stays on, and the password and
  recovery codes stay in the maintainers' password manager. Update them there whenever they
  change.
- **Your GPG key.** A key that has expired can't sign the next tag. Before it expires,
  extend it (`gpg --quick-set-expire <fingerprint> 1y`) and add the updated public key to
  your GitHub account again
  ([adding a GPG key](https://docs.github.com/en/authentication/managing-commit-signature-verification/adding-a-gpg-key-to-your-github-account)).
- **Another maintainer.** They need write access to MojoKata/MoolaKata, a GPG key on their
  own GitHub account (§1), and a place in the tag ruleset's bypass list (**Settings › Rules
  › Rulesets**), unless they are an admin of the MojoKata organization, which the list
  already holds. For Docker Hub they share the `mojokata` sign-in from the password manager,
  or the account is converted into an organization so that each has their own (GENESIS.md
  §5 step 1). The `docker-hub` environment and its token stay as they are.
- **Settings that stay on.** Immutable releases and the tag ruleset (GENESIS.md §3) are what
  make a published release trustworthy. Don't turn either off, not even to mend a release:
  §11 fixes forward instead. `setup` reports either one off.
- **A third image.** Its package on ghcr.io starts private (GENESIS.md §4 step 2), and it
  needs its own Docker Hub repository, its place in `release.yml`'s jobs, and in `IMAGES` in
  `web/release.sh`.
- **TrueNAS's catalog** (S17.8.3.1). Proposing the two apps is the maintainer's decision,
  made once: open an [issue](https://github.com/truenas/apps/issues) there first, as their
  pull request template asks, and fork `truenas/apps` under your account (`gh repo fork
  truenas/apps --clone=false`). Then, after a published release, run
  `publish/truenas/create-pr.sh`. It runs `publish/truenas/check.sh`, pins both images by
  digest once their provenance checks out, and leaves a branch and the request's text in
  `web/.dev/`. Read both, then run it again with `--open`, which pushes the branch to your
  fork and opens the pull request as a draft, or updates the open one. Once the apps are in
  the catalog, TrueNAS's update bot moves their images to each new release by itself; run
  `create-pr.sh --open` again only for a release that changes either app's form or
  template.
- **A step that no longer matches** what GitHub or Docker Hub shows: fix this document,
  `GENESIS.md` and `web/release.sh` together, in a pull request.
