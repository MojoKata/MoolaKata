# S17. Implementation

The stack, the repository's layout, the checks, dev mode, the Docker image, the milestones, and
continuous integration and releases. Each first-level item has a file of its own.

| Id | Item | What it covers |
|---|---|---|
| **S17.1** | [Layout](S17-implementation-01-layout.md) | the repository's folders and what each holds |
| **S17.2** | [Server dependencies](S17-implementation-02-server-dependencies.md) | each Python dependency of the server, and why it is there |
| **S17.3** | [The browser app](S17-implementation-03-browser-app.md) | no build step: its libraries, vendoring and the import map |
| **S17.4** | [Charts](S17-implementation-04-charts.md) | the chart library and the constraints it meets |
| **S17.5** | [Tests and checks](S17-implementation-05-tests-and-checks.md) | what `web/check` runs, with no Node.js |
| **S17.6** | [`web/dev.sh`](S17-implementation-06-dev-sh.md) | the developer's front door and its pinned downloads |
| **S17.7** | [Dev mode](S17-implementation-07-dev-mode.md) | the whole server from a checkout, relaxing the surroundings, never the rules |
| **S17.8** | [Packaging](S17-implementation-08-packaging.md) | the server's Docker image, its architectures and where it is published, the documented hosts (Proxmox, TrueNAS), TLS and the base image's updates |
| **S17.9** | [Milestones](S17-implementation-09-milestones.md) | the order the product is built in, and what each milestone holds |
| **S17.10** | [Continuous integration and releases](S17-implementation-10-ci-and-releases.md) | the checks on GitHub Actions, the release workflow, and the workflows' own dependencies |
