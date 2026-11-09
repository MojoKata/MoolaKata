# S17.10. Continuous integration and releases

10. **Continuous integration and releases**, on GitHub Actions, whose standard runners are
    free for a public repository.
    1. **Checks**: `.github/workflows/check.yml` runs `web/check` on every pull request and
       every push to `main`, after `web/dev.sh setup` (which installs uv from
       `install/build-requirements.txt` by its hashes, into a venv of its own), and with the `coworker` submodule
       checked out and its `status` run unattended (`COWORKER_UNATTENDED=1`), so a need
       missing from `.coworker/deps.json` shows on a runner as it would on a developer's
       machine. It runs `web/check`'s parts as jobs
       side by side (the server's tests in seven parts (`MK_TEST_PART`), the first with the
       static checks and the last with the connector's tests; the browser tests in four parts
       the same way; the parts split by measured time, each test weighing what it took in a
       recent run (`web/server/tests/durations.json`, which `web/dev.sh ci-durations` gathers
       from a run's artifacts), the longest first, each to the part with the least so far, a
       module whose tests run one after another kept whole; the generated mockup's drift; the hand-written mockup's screens),
       then the coverage of the test jobs together, from their measurements passed on as
       artifacts; the `check` job, the status the rulesets require, passes when every part
       does. Each job fetches the commit before as well, for the coverage of the changed
       lines, and the coverage reports (S17.5.8) are kept as the
       run's artifact. A newer push to a pull request cancels its older run; on `main`,
       runs queue instead, and after a passing check the `coverage site` job publishes the
       coverage site (S17.5.8.5) to the repository's GitHub Pages, through the
       `github-pages` environment, which takes `main` alone.
    2. **Releases**: `.github/workflows/release.yml`, on a `v<version>` tag matching
       `web/VERSION`, builds both images on an amd64 and an arm64 runner, runs
       `smoke.sh` on each (S17.8.1), pushes the images that passed to `ghcr.io/mojokata`
       under per-architecture tags, joins them under the version's tag, and attests each
       (GitHub's build provenance, signed through Sigstore's public instance and recorded in
       its transparency log, and kept in GitHub's attestation store, not in the registry).
       Then it copies both joined images to Docker Hub with their digests unchanged
       (S17.8.2), and drafts the GitHub release with the tag's install files attached: the
       compose files, the example `moolakata.toml` and the proxy examples. On a pull request that touches what goes into the images, it builds and
       smoke-runs both and pushes nothing. A new package on ghcr.io starts private: after the
       first release, an owner of MojoKata makes both public, once.
       1. **Tags and releases**: the maintainer who makes a release signs its tag with their
          own GPG key and pushes it. Once the published images check out, the same
          maintainer publishes the draft with its notes (`docs/RELEASE.md`; `web/release.sh`
          runs these steps from a terminal, one command each). Releases are immutable
          (GitHub's setting, with a ruleset on `v*` tags): once a release is published, its
          tag and files can't change, and GitHub attests the release.
       2. **The version between releases**: `web/VERSION`, which the server, the app and
          the API's document read, and the connector's own version name a release only on
          that release's commit. Once a release is published, `main` moves to the next minor
          release with `-dev` (after 1.4.2, `1.5.0-dev`), so a build from `main` never
          carries a released version. The next release's pull request gives it the number that
          release takes, whether patch, minor or major. The compose files and the install guide
          keep naming the last release meanwhile, since that is what they install.
    3. **Their own dependencies**: the actions are GitHub's own (`actions/checkout`,
       `actions/attest-build-provenance`), pinned by commit and listed in the register
       (S17.2.1). Everything else is the repository's own scripts and the runners' own
       `gh`. Each job's token has only the permissions it needs: `contents: read`
       everywhere, `packages: write` to push, `id-token` and `attestations: write` for the
       attestation alone, and `contents: write` only to draft the release. The one secret,
       Docker Hub's token, lives in an environment (`docker-hub`) that only runs for `v*`
       tags can read.
    4. **The mutation baseline**: `.github/workflows/mutate.yml`, started by hand on `main`,
       runs every server module's mutation run (S17.5.12) on the standard runners side by
       side: the fast tests once in six parts under coverage, for the map of the test files
       that reach each module; then one job per group of an area's modules, each stopped
       before the runner's six hours with what it finished kept, and its outcomes and
       survivors kept as the run's artifacts for 90 days. It runs at most as many jobs at once
       as its input says (14 by default), leaving the rest of the account's runners to pull
       requests' checks. Named jobs can be run again on their own, and their outcomes taken
       over the earlier run's. A pull request that changes it or its tools runs it on two
       small modules.
