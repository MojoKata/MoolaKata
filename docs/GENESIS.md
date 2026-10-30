# Genesis: how publishing was set up

This records how MoolaKata was set up for publishing. It covers the GitHub organization and
repository, the packages on ghcr.io and the Docker Hub account, which every release relies on
([`RELEASE.md`](RELEASE.md)). All of it was done once, around 0.1.0's release. Each part gives
the steps and then what was chosen (**As set up**), so the setup can be checked, done again
after a loss, or corrected. `web/release.sh setup` checks what it can (§7). RELEASE.md §12
says what has to be renewed and how another maintainer joins.

Settings, plans, limits and commands on GitHub and Docker Hub change over time. Each one
below links to the page it comes from, so recheck that page when a step stops matching what
you see. Correct this document whenever a setting changes, in the same pull request as
anything else the change touches.

## 1. Accounts and roles

1. **The maintainer** is an owner of the MojoKata organization. The maintainer signs and
   pushes release tags, publishes releases, is in the tag ruleset's bypass list (§3 step 2),
   and holds Docker Hub's sign-in. What a maintainer needs on their own machine (a GPG key on
   their GitHub account, `gh`, Docker) is in RELEASE.md §1.
2. **Contributors** work in a fork and open pull requests against `main`, which a maintainer
   squash-merges. The build's own fork, `donclaudio777/MoolaKata`, has read access to
   MojoKata/MoolaKata and nothing more, so it can't push, tag, or rerun a failed job.
3. **`release.yml`** pushes the images, attests them, copies them to Docker Hub and drafts the
   release. Each job's token gets only the permissions that job needs (S17.10.3).
4. **Docker Hub's account `mojokata`** has a single sign-in, which the maintainers share
   through their password manager (§5 step 1).

## 2. The GitHub organization

MojoKata is a GitHub organization on the free plan. It owns the repository and its packages.

1. **Package creation.** Go to **Settings › Packages › Package creation**
   (`https://github.com/organizations/MojoKata/settings/packages`) and allow **Public**
   packages. Without it no package can be made public, even by an owner. The package's
   **Change visibility** refuses with a message that an organization admin prevents it. See
   GitHub's
   [package creation visibility](https://docs.github.com/en/packages/learn-github-packages/configuring-a-packages-access-control-and-visibility#package-creation-visibility-for-organization-members).

   **As set up:** public packages allowed. This was done at 0.1.0, when making its packages
   public first failed.

No other organization setting was part of the setup.

## 3. The repository

MojoKata/MoolaKata is public, under GPL-3.0, with `main` as its default branch. Being public
is also what makes GitHub's standard runners free (S17.10). The repository and its fork were
first named `MoneyKata`, and both were renamed with the product. GitHub redirects an old name
only while no repository takes it, so `MojoKata/MoneyKata` is never used again.

1. **Actions.** In the organization's **Settings › Actions › General**, which its
   repositories follow
   ([organization's Actions](https://docs.github.com/en/organizations/managing-organization-settings/disabling-or-limiting-github-actions-for-your-organization)),
   or in the repository's own
   ([Actions settings](https://docs.github.com/en/repositories/managing-your-repositorys-settings-and-features/enabling-features-for-your-repository/managing-github-actions-settings-for-a-repository)):
   1. Under the permissions policy, choose **Allow MojoKata, and select non-MojoKata,
      actions and reusable workflows**, and tick **Allow actions created by GitHub**. The
      workflows use only GitHub's own actions, pinned by commit (S17.10.3).
   2. Under **Workflow permissions**, keep **Read repository contents and packages
      permissions**. Each workflow also declares `contents: read` and each job asks for
      more only where it needs it, which `test_install.py` checks, so this default is only
      a fallback.
   3. **Approval for running fork pull request workflows from contributors** decides which
      fork pull requests wait for a maintainer's **Approve and run**. GitHub's default,
      **Require approval for first-time contributors**, holds back anyone who has never had a
      pull request merged here. A fork's pull request runs `check` and `release.yml`'s build
      and smoke run with a token that can only read, and pushes nothing.

   **As set up:** steps 1 and 2 on the organization, step 3 at GitHub's default. The build's
   fork has had pull requests merged, so its pull requests run without approval. In the
   section for forks of private repositories, **Run workflows from fork pull requests** is
   ticked. It has no effect on a public repository.
2. **The release tags' ruleset.** Go to **Settings › Rules › Rulesets › New ruleset › New tag
   ruleset**:
   1. Set its **Enforcement status** to **Active**. A new ruleset starts disabled.
   2. Set its target to tags matching `v*`.
   3. Turn on **Restrict creations**, **Restrict updates** and **Restrict deletions**.
   4. Put the maintainers in its bypass list.

   Only a maintainer can then create a release tag, and only a maintainer can move or
   delete one (RELEASE.md §11). See GitHub's
   [creating rulesets](https://docs.github.com/en/repositories/configuring-branches-and-merges-in-your-repository/managing-rulesets/creating-rulesets-for-a-repository)
   and [available rules](https://docs.github.com/en/repositories/configuring-branches-and-merges-in-your-repository/managing-rulesets/available-rules-for-rulesets).

   **As set up:**
   - The ruleset is *Release rules*, Active, on `refs/tags/v*`.
   - It restricts creations, updates and deletions, and also blocks force pushes.
   - Its bypass list holds the **Organization admin** role and the maintainer's own account,
     both set to **Always**.
   - It was first saved Disabled, then set to Active.
3. **Immutable releases.** Go to **Settings**, scroll to **Releases** and turn on **Enable
   release immutability**. A published release's tag and files are then locked, and GitHub
   signs an attestation of the release (RELEASE.md §8). Releases published before the setting
   was turned on stay as they were. See GitHub's
   [preventing changes to your releases](https://docs.github.com/en/code-security/how-tos/secure-your-supply-chain/establish-provenance-and-integrity/prevent-release-changes)
   and [immutable releases](https://docs.github.com/en/code-security/concepts/supply-chain-security/immutable-releases).

   **As set up:** on, set on the repository rather than enforced by the organization. It was
   turned on after 0.1.0's release, which stays editable (§6).
4. **The `docker-hub` environment** holds Docker Hub's token (§5 step 4).
5. **The `main` branch's ruleset.** Go to **Settings › Rules › Rulesets › New ruleset › New
   branch ruleset**:
   1. Name it *Main rules* and set its **Enforcement status** to **Active**.
   2. Under **Target branches**, choose **Add target › Include default branch**.
   3. Put the **Organization admin** role in its bypass list, set to **Allow for pull
      requests only**. A maintainer can then still merge a pull request whose checks failed,
      by ticking the bypass box when merging, but nobody can push to `main` directly.
   4. Keep **Restrict deletions** and **Block force pushes**, which are on by default.
   5. Turn on **Require a pull request before merging**, with **Required approvals** at 0,
      and under **Allowed merge methods** leave only **Squash**.
   6. Turn on **Require status checks to pass** and add `check`, from GitHub Actions.
   7. Leave **Require branches to be up to date before merging** off. With it on, each
      squash merge would send every other open pull request back for an update.
   8. Don't add `release.yml`'s build and smoke run as a required check. It runs only on
      pull requests that change what goes into the images, so a required check would hold
      back every other pull request.

   Every change then reaches `main` through a squash-merged pull request whose `check`
   passed. See GitHub's
   [available rules](https://docs.github.com/en/repositories/configuring-branches-and-merges-in-your-repository/managing-rulesets/available-rules-for-rulesets).

   **As set up:** *Main rules*, Active, with the settings above. Its bypass list holds the
   **Organization admin** role and the maintainer's own account, both set to **Allow for
   pull requests only**. It was first saved Disabled, then set to Active. GitHub's **Require an additional approval for unattributed
   Copilot pull requests**, on by default, stays on. It has no effect while 0 approvals are
   required.
6. **GitHub Pages**, for the coverage site (S17.5.8). Go to **Settings › Pages** and, under
   **Build and deployment › Source**, choose **GitHub Actions**. GitHub then makes the
   `github-pages` environment, which takes deployments from `main` alone. `check.yml`'s
   `coverage site` job publishes to it after each merge; the first one makes the site at
   `https://mojokata.github.io/MoolaKata/`. See GitHub's
   [publishing with a custom workflow](https://docs.github.com/en/pages/getting-started-with-github-pages/using-custom-workflows-with-github-pages).

   **As set up:** source GitHub Actions, HTTPS enforced, and `github-pages` admitting the
   branch `main` only.

## 4. The images on ghcr.io

1. **The packages.** `ghcr.io/mojokata/moolakata` and `ghcr.io/mojokata/moolakata-connector`
   were created by `release.yml`'s first push, 0.1.0's run, and started private. The
   Dockerfiles' `org.opencontainers.image.source` label links each package to the repository
   ([connecting a repository](https://docs.github.com/en/packages/learn-github-packages/connecting-a-repository-to-a-package)).
2. **Made public, once.** Allow public packages first (§2 step 1). Then, on each package's
   page, go to **Package settings › Danger Zone › Change visibility** and choose **Public**
   ([package visibility](https://docs.github.com/en/packages/learn-github-packages/configuring-a-packages-access-control-and-visibility#configuring-visibility-of-packages-for-an-organization)).
   A public package can't be made private again. Every later version inherits the setting,
   but a third image would need it again (RELEASE.md §12).

   **As set up:** both packages are public. Anyone can pull them without signing in, which
   0.1.0's check confirmed for both architectures, along with the attestations.
3. **No attestation tags.** The attestations are kept in GitHub's attestation store, not as
   tags beside the images (`push-to-registry: false` in `release.yml`, RELEASE.md §7).
   0.1.0 was built while they were still pushed, so each package had a `sha256-<digest>`
   version, which ghcr.io showed as the newest. To delete such a version, go to the package's
   **View and manage all versions**, open the **⋯** beside the `sha256-…` version only, and
   choose **Delete version**
   ([deleting a package version](https://docs.github.com/en/packages/learn-github-packages/deleting-and-restoring-a-package)).

   **As set up:** both `sha256-…` versions were deleted. Each package keeps `0.1.0`,
   `0.1.0-amd64` and `0.1.0-arm64`. The attestations stayed in GitHub's store, so
   `gh attestation verify` still passes.

## 5. Docker Hub

These are what `release.yml` needs to publish to Docker Hub:

1. **The namespace.** Sign up at [hub.docker.com](https://hub.docker.com/signup) for a free
   account whose Docker ID is `mojokata`. A Docker Hub *organization* needs a paid Team or
   Business plan
   ([create an organization](https://docs.docker.com/accounts/organization/setup/orgs/)). The
   account can be
   [converted into an organization](https://docs.docker.com/accounts/organization/setup/convert-account/)
   of the same name later, if one is ever needed. Turn on two-factor authentication, and keep
   the password and recovery codes in the maintainers' password manager.

   **As set up:** a personal account, `mojokata`, with two-factor authentication on and its
   password and recovery codes in the password manager.
2. **The two repositories.** Create `mojokata/moolakata` and `mojokata/moolakata-connector`,
   both **Public** ([create a repository](https://docs.docker.com/docker-hub/repos/create/)).
   Give each a short description, and a **Repository overview** (Docker's name for the full
   description) that links to this repository and `docs/DEPLOY.md` and shows the pull
   command with a version's tag. Without a tag, Docker asks for `latest`, which these
   repositories don't have (RELEASE.md §2). Each release moves both overviews' pull command
   to its own tag (RELEASE.md §8). See Docker's
   [repository information](https://docs.docker.com/docker-hub/repos/manage/information/).

   **As set up:** both are public. Their short descriptions are *Kata for the moola* and
   *Connector for moolakata*. Their overviews, as written at 0.1.0:

   ```text
   Server for local management of financial information (the moola). No connection to
   institutions required (manual upload). For automated uploads, see moolakata-connector

   https://github.com/MojoKata/MoolaKata
   See docs/DEPLOY.md

   docker pull mojokata/moolakata:0.1.0
   Status: alpha
   ```

   ```text
   Connector for moolakata server. This optional server is given read access or statement
   download permission only, via write-only credential or access token. Various drivers
   support different institutions and formats. The credentials are never retrievable and
   stored encrypted.

   The only function of the moolakata-connector is to download statements and upload them
   to moolakata.

   https://github.com/MojoKata/MoolaKata
   See docs/DEPLOY.md

   docker pull mojokata/moolakata-connector:0.1.0
   Status: alpha
   ```

   The connector's description says how it keeps credentials, which depends on the answer
   to Q30.
3. **The workflow's token.** Sign in to [Docker Home](https://app.docker.com/) and go to your
   avatar › **Account settings › Personal access tokens › Generate new token**. Describe it as
   *MoolaKata releases* and give it the repository permission **Repo Read & Write**, never
   Delete. Its permission covers every repository the account has, which is only these two.
   Set an expiry date at most a year away, with a reminder to renew the token before then. The
   token is shown only once. See Docker's
   [personal access tokens](https://docs.docker.com/security/access-tokens/personal-access-tokens/)
   and [their permissions](https://docs.docker.com/security/access-tokens/reference/).

   **As set up:** *MoolaKata releases*, Repo Read & Write. It was made for a year and expires
   on October 20, 2027, with a reminder before then. `web/release.sh setup` also warns 11
   months after the secret was set. Each renewal writes its new expiry date here
   (RELEASE.md §12).
4. **Where GitHub keeps it.** In MojoKata/MoolaKata, go to **Settings › Environments › New
   environment** and create `docker-hub`.
   1. Under **Deployment branches and tags**, choose **Selected branches and tags** and add
      the tag rule `v*`.
   2. Add the secret `DOCKERHUB_TOKEN` (the token) and the variable `DOCKERHUB_USERNAME`
      (`mojokata`).

   Only a job that runs for a release tag can read them; pull requests, including a fork's,
   never can. See GitHub's
   [managing environments](https://docs.github.com/en/actions/how-tos/deploy/configure-and-manage-deployments/manage-environments).
   If the environment is missing or empty, `release.yml`'s Docker Hub job copies nothing and
   leaves a warning on the run.

   **As set up:** `docker-hub` admits only the tag rule `v*`, has no required reviewers, and
   holds the secret and the variable.
5. **No pull limits.** Apply for the namespace to join the
   [Docker-Sponsored Open Source program](https://docs.docker.com/docker-hub/repos/manage/trusted-content/dsos-program/)
   ([application](https://www.docker.com/community/open-source/application/)).
   1. The program asks for an Open Source Initiative licence (GPL-3.0 is one), active
      development, and no path to commercial use.
   2. Once a project is accepted, everyone pulling its public images pulls without limits.
      The namespace also gets the program's badge, a logo for each repository, insights
      into its pulls, and Docker Scout.
   3. Membership lasts a year and is renewed each year.
   4. Until then, Docker Hub limits anyone who isn't signed in to 100 pulls every 6 hours per
      address ([usage and limits](https://docs.docker.com/docker-hub/usage/)).

   ghcr.io sets no such limit for public images. That is why the compose files and the docs
   name ghcr.io and give Docker Hub as the alternative.

   **As set up:** not applied for. Only someone pulling from Docker Hub without signing in
   meets the limit, and one household's installs and upgrades stay far below it.
6. **The releases made before.** Copy each earlier release's images once, the way the workflow
   does. They keep their digests, so their attestations verify the copies. For 0.1.0:

   ```sh
   docker login docker.io -u mojokata
   for image in moolakata moolakata-connector; do
     docker buildx imagetools create -t docker.io/mojokata/$image:0.1.0 ghcr.io/mojokata/$image:0.1.0
   done
   ```

   **As set up:** 0.1.0 was copied. Each copy has the same digest as on ghcr.io, and the
   strict `gh attestation verify` passes on it through `registry-1.docker.io`
   (RELEASE.md §7).

## 6. The first release

0.1.0 was released before most of the process in RELEASE.md existed, so it differs from every
release after it:

1. It was tagged and published through GitHub's **Draft a new release** form, as a
   pre-release on `main`'s commit at the time. The form made `v0.1.0` a lightweight tag,
   with no signature.
2. `release.yml` ran on the tag with its first three jobs: the two builds and smoke runs, and
   the joining and attesting. It created both packages, which were then made public (§2,
   §4).
3. Its eight install files were attached afterwards with `web/release.sh attach 0.1.0`, once
   `DEPLOY.md` linked to them.
4. It was published before immutable releases were turned on, so its files and notes can
   still be changed. The tag ruleset now keeps its tag from being moved or deleted by anyone
   but a maintainer.
5. It was copied to Docker Hub by hand (§5 step 6), and its `sha256-…` versions were deleted
   from ghcr.io (§4 step 3).

## 7. Checking it

`web/release.sh setup` checks the following and prints `ok` or `FAIL` for each:

1. immutable releases;
2. the tag ruleset: active, on `v*` tags, restricting creating, updating and deleting them,
   with a bypass list;
3. the `main` branch's ruleset: active, on `main`, taking changes only through pull requests
   whose `check` passed;
4. the `docker-hub` environment's tag rule, its secret (and the secret's age) and its
   variable;
5. that both images are public on both registries.

Some of these only an admin can read, so run it signed in to `gh` as a maintainer, before
each release and after any change here (RELEASE.md §12).

Some things it can't check, so look at them by hand:

1. the organization's package creation setting (§2);
2. the Actions settings (§3 step 1);
3. Docker Hub's two-factor authentication and the password manager's entries (§5 step 1);
4. the overviews' pull command (§5 step 2);
5. the token's expiry date (§5 step 3);
6. the open-source program's membership, once there is one (§5 step 5).
