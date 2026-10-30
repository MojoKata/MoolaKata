"""The image and the compose files keep what requirements S17.8, S15.4 and S13.6 promise:
the unprivileged user, the port, the mounts, the read-only key directory, the health check and
the restart policy. Checked on the files themselves, so a tag or a path can't
drift from the server's own constants."""

import re
import tomllib
from pathlib import Path

import yaml
from PIL import Image

from moolakata import config, paths
from moolakata.dev import wheels
from moolakata.keys.cli import SERVER_UID

INSTALL = paths.WEB / "install"
REGISTRY = "ghcr.io/mojokata"  # where releases are published (S17.8.2)
DOCKERFILE = (INSTALL / "Dockerfile").read_text()
COMPOSE = {
    name: yaml.safe_load((INSTALL / name).read_text())
    for name in ("compose.yaml", "compose.tls.yaml")
}
EXAMPLE = config.parse(tomllib.loads((INSTALL / "moolakata.toml").read_text()), "moolakata.toml")
VERSION = paths.version()


def _numbers(version: str) -> tuple[int, ...]:
    return tuple(int(n) for n in version.split("."))


def _the_installed_release(found: set[str], where: str):
    """The install files name one release: web/VERSION's on a release's commit, and an
    earlier one while web/VERSION names the next release with -dev (S17.10.2.2)."""
    assert len(found) == 1, f"{where} name {found}"
    (release,) = found
    if VERSION.endswith("-dev"):
        assert _numbers(release) < _numbers(VERSION.removesuffix("-dev")), (
            f"{where} name {release}, not a release before {VERSION}"
        )
    else:
        assert release == VERSION, f"{where} name {release}, the build {VERSION}"


def _mounts(service: dict) -> dict[str, tuple[str, bool]]:
    """{container path: (host path, read only)} of a service's bind mounts."""
    out = {}
    for volume in service.get("volumes", []):
        host, target, *flags = volume.split(":")
        out[target] = (host, "ro" in flags)
    return out


def test_the_image_runs_as_the_server_account_on_its_port():
    assert f"USER {SERVER_UID}:{SERVER_UID}" in DOCKERFILE
    assert f"useradd --uid {SERVER_UID} --gid {SERVER_UID}" in DOCKERFILE
    assert f"EXPOSE {config.DEFAULT_PORT}" in DOCKERFILE
    assert 'ENTRYPOINT ["moolakata"]' in DOCKERFILE and 'CMD ["serve"]' in DOCKERFILE
    assert re.search(r'HEALTHCHECK .*\n\s+CMD \["moolakata", "health"\]', DOCKERFILE)


def test_the_image_is_built_from_pinned_sources():
    """A base pinned by digest, the build tool pinned with hashes, and no secret or dev file in
    the build context (S13.7.11, S15.4.5)."""
    base = rf"^ARG PYTHON=python:3\.{wheels.MINOR}-[\w.-]+@sha256:[0-9a-f]{{64}}$"
    assert re.search(base, DOCKERFILE, re.M), "the base image must be the project's Python"
    requirements = (INSTALL / "build-requirements.txt").read_text()
    assert "--hash=sha256:" in requirements
    assert "--require-hashes" in DOCKERFILE
    ignored = (paths.ROOT / ".dockerignore").read_text().split()
    for entry in (".git", "**/.venv", "web/.dev"):
        assert entry in ignored, f".dockerignore must leave out {entry}"


def test_the_image_makes_the_directories_the_example_config_names():
    data, backups = EXAMPLE.data_dir, EXAMPLE.backup_dir
    assert f"install -d -o {SERVER_UID} -g {SERVER_UID} -m 0700 {data} {backups}" in DOCKERFILE
    assert EXAMPLE.mode == "proxy" and EXAMPLE.port == config.DEFAULT_PORT


def test_the_version_is_a_release_or_the_next_ones_dev():
    """S17.10.2.2: a release's three numbers on its commit, the next release's with -dev between
    releases; the connector carries the server's."""
    assert re.fullmatch(r"\d+\.\d+\.\d+(-dev)?", VERSION), VERSION
    connector = paths.ROOT / "connector"
    project = tomllib.loads((connector / "pyproject.toml").read_text())["project"]
    package = (connector / "moolakata_connector" / "__init__.py").read_text()
    assert project["version"] == VERSION and f'VERSION = "{VERSION}"' in package


def test_every_compose_service_runs_an_image_of_the_installed_release():
    found = set()
    for name, compose in COMPOSE.items():
        for service, spec in compose["services"].items():
            image = re.fullmatch(
                rf"{REGISTRY}/moolakata(-connector)?:(\d+\.\d+\.\d+)", spec["image"]
            )
            assert image, f"{name}: {service} runs {spec['image']}"
            found.add(image[2])
        assert compose["services"]["connector"]["image"].startswith(
            f"{REGISTRY}/moolakata-connector:"
        )
    _the_installed_release(found, "the compose files")


CONNECTOR_PORT = int(
    re.search(
        r"^PORT = (\d+)$",
        (paths.ROOT / "connector" / "moolakata_connector" / "page.py").read_text(),
        re.M,
    ).group(1)
)


def test_the_connector_service_is_apart_locked_down_and_reaches_nothing_in():
    """Its own volume that MoolaKata never mounts, its page's port the only one published,
    read only, all capabilities dropped (S18.2.1, S18.10, S18.11); its socket on a tmpfs
    inside the container."""
    for name, compose in COMPOSE.items():
        c = compose["services"]["connector"]
        assert c["ports"] == [f"{CONNECTOR_PORT}:{CONNECTOR_PORT}"], name
        assert "MOOLAKATA_CONNECTOR_NAMES" in c["environment"], name
        assert c["restart"] == "unless-stopped", name
        assert c["read_only"] is True and c["cap_drop"] == ["ALL"], name
        assert "no-new-privileges:true" in c["security_opt"], name
        assert any(x.startswith("/run/moolakata-connector:uid=10002") for x in c["tmpfs"]), name
        mounts = _mounts(c)
        assert "/var/lib/moolakata-connector" in mounts, name
        assert mounts["/var/lib/moolakata-connector"][0] == "connector-data", name
        assert "connector-data" in compose["volumes"], name
        server = _mounts(compose["services"]["moolakata"])
        assert not any(h == "connector-data" for h, _ in server.values()), name
        for h, _ in mounts.values():
            assert h not in {h2 for h2, _ in server.values()}, f"{name}: a mount shared"
    dockerfile = (paths.ROOT / "connector" / "Dockerfile").read_text()
    assert "USER 10002:10002" in dockerfile and f"EXPOSE {CONNECTOR_PORT}\n" in dockerfile
    assert re.search(r"^ARG PYTHON=python:3\.14-[\w.-]+@sha256:[0-9a-f]{64}$", dockerfile, re.M)
    assert "--require-hashes" in dockerfile


def test_the_server_service_is_locked_down_and_mounts_no_key():
    """The master key is a phrase, never a file (S15.4): nothing named keys is mounted."""
    for name, compose in COMPOSE.items():
        service = compose["services"]["moolakata"]
        assert service["read_only"] is True, name
        assert service["cap_drop"] == ["ALL"], name
        assert "no-new-privileges:true" in service["security_opt"], name
        assert "/tmp" in service["tmpfs"], name
        # Back after every reboot, locked: a server stopped by a shutdown exited cleanly, which
        # on-failure would leave down (S13.6).
        assert service["restart"] == "unless-stopped", name
        mounts = _mounts(service)
        assert mounts[str(config.DEFAULT_CONFIG)][1], f"{name}: moolakata.toml must be read only"
        assert not mounts[str(EXAMPLE.data_dir)][1] and not mounts[str(EXAMPLE.backup_dir)][1]
        # And the host's time zone, read only, which backups and daily emails follow (S14.9.2).
        assert mounts["/etc/localtime"] == ("/etc/localtime", True), name
        assert service["environment"]["TZ"] == "${TZ:-}", name
        assert set(mounts) == {
            str(EXAMPLE.data_dir),
            str(EXAMPLE.backup_dir),
            str(config.DEFAULT_CONFIG),
            "/etc/localtime",
        }, f"{name}: the server mounts its data, its backups, its config and the zone, nothing else"
        for spec in compose["services"].values():
            for v in spec.get("volumes", []):
                assert "keys" not in str(v), f"{name}: no key directory exists any more"


def test_host_commands_have_their_socket_and_the_proxy_is_trusted_alone():
    """Host commands reach the server over a Unix socket on a tmpfs of its account (S13.6), and
    the example trusts the proxy's own address, never a range anything else could share
    (S13.3)."""
    import ipaddress

    folder = str(config.DEFAULT_SOCKET.parent)
    for name, compose in COMPOSE.items():
        tmpfs = compose["services"]["moolakata"]["tmpfs"]
        assert f"{folder}:uid={SERVER_UID},gid={SERVER_UID},mode=0700" in tmpfs, name
    assert EXAMPLE.trusted_proxies
    subnet = ipaddress.ip_network(
        COMPOSE["compose.yaml"]["networks"]["default"]["ipam"]["config"][0]["subnet"]
    )
    for net in EXAMPLE.trusted_proxies:
        assert net.num_addresses == 1 and net.network_address in subnet, net
    assert (
        f"ipv4_address: {EXAMPLE.trusted_proxies[0].network_address}"
        in (INSTALL / "compose.yaml").read_text()
    )


def test_the_published_port_fits_each_mode():
    """Behind a reverse proxy the plain-HTTP listener is published on the host's loopback only;
    the proxy examples reach it by service name. The tls example serves the LAN itself."""
    port = config.DEFAULT_PORT
    assert COMPOSE["compose.yaml"]["services"]["moolakata"]["ports"] == [f"127.0.0.1:{port}:{port}"]
    assert COMPOSE["compose.tls.yaml"]["services"]["moolakata"]["ports"] == [f"{port}:{port}"]
    for example in (INSTALL / "proxy").iterdir():
        assert f"moolakata:{port}" in example.read_text(), example.name


def test_no_service_runs_as_root_and_the_key_commands_need_none():
    """The key commands run as the image's own user: the keyring is in the data directory,
    which the server's account owns. The welcome makes the key, so no command shows a phrase
    (S15.4.4, S15.4.7)."""
    for name, compose in COMPOSE.items():
        services = compose["services"]
        assert set(services) == {"moolakata", "connector"}, name
        for service, spec in services.items():
            assert "user" not in spec, f"{name}: {service} must run as the image's user"
    text = (INSTALL / "compose.yaml").read_text()
    assert "keys init" not in text and "welcome" in text
    assert "keys unlock" in text


def test_the_smoke_script_is_there_for_each_platform():
    """The release gate (S17.8.1): both images built for a platform and run once."""
    script = INSTALL / "smoke.sh"
    assert script.exists() and script.stat().st_mode & 0o111, (
        "web/install/smoke.sh must be executable"
    )
    text = script.read_text()
    assert "linux/arm64" in text and "keys unlock" in text
    # A new server's welcome, then the locked start after a restart (S15.4).
    assert "wait_for uninitialised" in text and "/ui/api/welcome/key" in text
    assert "wait_for locked" in text


def _one_time_step(compose: dict, service: str, uid: int, owned: list[str]) -> None:
    """A TrueNAS app's `permissions` step: root with CHOWN alone, no network, its datasets and
    nothing else, giving them to the service's account once before it starts, which waits for
    it to succeed; so nothing is typed in a shell."""
    app, step = compose["services"][service], compose["services"]["permissions"]
    assert app["depends_on"] == {"permissions": {"condition": "service_completed_successfully"}}
    assert step["image"] == app["image"] and step["user"] == "0:0"
    assert step["entrypoint"] == ["chown", f"{uid}:{uid}", *owned]
    assert step["cap_drop"] == ["ALL"] and step["cap_add"] == ["CHOWN"]
    assert step["network_mode"] == "none" and step["restart"] == "no" and step["read_only"]
    assert "no-new-privileges:true" in step["security_opt"]
    assert _mounts(step) == {t: m for t, m in _mounts(app).items() if t != "/etc/localtime"}
    assert set(owned) == set(_mounts(step))


def test_the_truenas_app_keeps_the_compose_files_promises():
    """install/compose.truenas.yaml (S17.8.3), which docs/DEPLOY.md shows to paste, is the tls
    example's server with the datasets for host paths and its configuration in
    MOOLAKATA_CONFIG (S17.8), after a one-time step that gives the datasets to its account:
    the same lockdown, port, restart and logs, and the release they install; nothing typed in
    a shell."""
    truenas = yaml.safe_load((INSTALL / "compose.truenas.yaml").read_text())
    connector = yaml.safe_load((INSTALL / "compose.connector-truenas.yaml").read_text())
    guide = (paths.ROOT / "docs" / "DEPLOY.md").read_text()
    blocks = re.findall(r"^```yaml\n(.*?)^```", guide, re.M | re.S)
    assert [yaml.safe_load(b) for b in blocks] == [truenas, connector], (
        "the guide shows the files as they are"
    )
    # The connector's app (S18.10) is the compose file's connector, with a dataset for its
    # volume, given to its account by the same kind of one-time step, and the NAS's address
    # for its page.
    app = connector["services"]["connector"]
    example = COMPOSE["compose.tls.yaml"]["services"]["connector"]
    differ = {"volumes", "environment", "depends_on"}
    assert {k: v for k, v in app.items() if k not in differ} == {
        k: v for k, v in example.items() if k not in differ
    }
    assert set(_mounts(app)) == {"/var/lib/moolakata-connector", "/etc/localtime"}
    assert app["environment"]["MOOLAKATA_CONNECTOR_NAMES"]
    _one_time_step(connector, "connector", 10002, ["/var/lib/moolakata-connector"])
    app = truenas["services"]["moolakata"]
    tls = COMPOSE["compose.tls.yaml"]["services"]["moolakata"]
    differ = {"volumes", "environment", "depends_on"}
    assert {k: v for k, v in app.items() if k not in differ} == {
        k: v for k, v in tls.items() if k not in differ
    }
    want = {t: ro for t, (_, ro) in _mounts(tls).items() if t != str(config.DEFAULT_CONFIG)}
    assert {t: ro for t, (_, ro) in _mounts(app).items()} == want
    given = config.configured(None, app["environment"])
    assert (given.mode, given.port) == ("tls", 37373) and given.cert_names
    assert {str(given.data_dir), str(given.backup_dir)} <= set(_mounts(app))
    _one_time_step(truenas, "moolakata", SERVER_UID, [str(given.data_dir), str(given.backup_dir)])
    tags = re.findall(r"moolakata[:-](\d+\.\d+\.\d+)", guide)
    assert tags
    _the_installed_release(set(tags), "the guide's tags")


CATALOG = paths.ROOT / "publish" / "truenas"


def _catalog_config(template: str, consts: dict, certificate: bool) -> str:
    """The TOML the server's catalog template gives MOOLAKATA_CONFIG, for one certificate
    choice, the default port and one address: its block's few substitutions, done here."""
    block = re.search(r"\{% set config -%\}\n(.*?)\{%- endset %\}", template, re.S).group(1)
    block = re.sub(
        r"\{% if values\.network\.certificate_id -%\}\n(.*?)\{% endif -%\}\n",
        lambda m: m.group(1) if certificate else "",
        block,
        flags=re.S,
    )
    given = {
        "values.network.web_port.port_number": str(config.DEFAULT_PORT),
        "values.moolakata.names | tojson": '["192.168.1.20"]',
        **{f"values.consts.{k}": str(v) for k, v in consts.items()},
    }
    out = re.sub(r"\{\{ (.*?) \}\}", lambda m: given[m.group(1)], block)
    assert "{%" not in out and "{{" not in out, "the block uses only what is substituted here"
    return out


def test_the_truenas_catalog_apps_keep_the_compose_files_promises():
    """publish/truenas (S17.8.3.1): each app is its compose service's image and release, run
    as the image's account with the same memory mounts and health check, from a form with a
    port, a certificate and a time zone of TrueNAS's, ixVolumes by default and no user section;
    and the server's template gives it the configuration it reads, tls mode, with or without
    a certificate. As TrueNAS's tools write them, so they change nothing."""
    tags = set()
    services = COMPOSE["compose.yaml"]["services"]
    for name, service, uid, port, health in (
        (
            "moolakata",
            "moolakata",
            SERVER_UID,
            config.DEFAULT_PORT,
            '["CMD", "moolakata", "health"]',
        ),
        (
            "moolakata-connector",
            "connector",
            10002,
            37374,
            '["CMD", "moolakata-connector", "status"]',
        ),
    ):
        app = CATALOG / name
        meta, values, questions = (
            yaml.safe_load((app / f).read_text())
            for f in ("app.yaml", "ix_values.yaml", "questions.yaml")
        )
        template = (app / "templates" / "docker-compose.yaml").read_text()
        image = values["images"]["image"]
        assert f"{image['repository']}:{image['tag']}" == services[service]["image"], name
        assert meta["app_version"] == image["tag"] and meta["name"] == name
        tags.add(image["tag"])
        assert meta["train"] == "community" and meta["lib_version_hash"]
        assert (app / "item.yaml").exists()
        assert [c["uid"] for c in meta["run_as_context"]] == [uid]
        consts = values["consts"]
        assert (consts["run_as_user"], consts["run_as_group"]) == (uid, uid)
        assert sorted(p.name for p in (app / "templates" / "test_values").iterdir()) == [
            "basic-values.yaml",
            "hostnet-values.yaml",
            "https-values.yaml",
        ]
        # The form.
        asked = {q["variable"]: q for q in questions["questions"]}
        assert "run_as" not in asked, "the image's account is fixed"
        assert asked["TZ"]["schema"]["$ref"] == ["definitions/timezone"]
        network = {a["variable"]: a["schema"] for a in asked["network"]["schema"]["attrs"]}
        web = {a["variable"]: a["schema"] for a in network["web_port"]["attrs"]}
        assert web["port_number"]["default"] == port
        assert network["certificate_id"]["$ref"] == ["definitions/certificate"]
        for store in asked["storage"]["schema"]["attrs"]:
            kinds = {a["variable"]: a["schema"] for a in store["schema"]["attrs"]}
            assert kinds["type"]["default"] == "ix_volume", store["variable"]
            host = {a["variable"]: a["schema"] for a in kinds["host_path_config"]["attrs"]}
            assert host["auto_permissions"]["default"] is True, store["variable"]
        # The lockdown, as the compose service has it.
        assert "set_user(values.consts.run_as_user, values.consts.run_as_group)" in template
        assert "set_read_only(not values.network.certificate_id)" in template
        assert f"healthcheck.set_custom_test({health})" in template
        assert "add_caps" not in template and "set_privileged" not in template
        for mount in services[service]["tmpfs"]:
            path, _, opts = mount.partition(":")
            if not opts:
                assert f'add_storage("{path}", {{"type": "tmpfs"}})' in template
                continue
            assert opts == f"uid={uid},gid={uid},mode=0700"
            assert (
                f'add_storage("{path}", {{"type": "tmpfs", "tmpfs_config": {{"uid": '
                f'values.consts.run_as_user, "gid": values.consts.run_as_group, "mode": "0700"}}}})'
            ) in template
        if name == "moolakata":
            for certificate in (False, True):
                given = config.configured(
                    None, {"MOOLAKATA_CONFIG": _catalog_config(template, consts, certificate)}
                )
                assert (given.mode, given.port) == ("tls", config.DEFAULT_PORT)
                assert given.cert_names == ("192.168.1.20",)
                assert (str(given.data_dir), str(given.backup_dir)) == (
                    consts["data_path"],
                    consts["backups_path"],
                )
                assert (given.tls_cert, given.tls_key) == (
                    (Path(consts["ssl_cert_path"]), Path(consts["ssl_key_path"]))
                    if certificate
                    else (None, None)
                )
        if name == "moolakata-connector":
            # MoolaKata links to the page at its first address, so the install needs one.
            assert "{% if not values.moolakata_connector.names %}" in template
            assert "tpl.funcs.fail(" in template
    _the_installed_release(tags, "publish/truenas's images")
    # What the request links for TrueNAS's CDN is in the repository: two icons and, for the
    # catalog's pages, screenshots saved as the help shots are, PNG of 256 colours.
    script = (CATALOG / "create-pr.sh").read_text()
    media = re.search(r"^MEDIA=\((.*?)^\)", script, re.M | re.S).group(1).split()
    assert len([m for m in media if m.endswith(".svg")]) == 2
    for path in media:
        assert (paths.ROOT / path).is_file(), path
        if path.endswith(".png"):
            with Image.open(paths.ROOT / path) as shot:
                assert shot.mode == "P" and len(shot.getcolors(256) or []) <= 256, path


def test_the_workflows_pin_their_actions_and_the_register_lists_them():
    """S17.10.3: every action is pinned by a full commit, named in docs/dependencies.md with
    that commit, and a workflow's token can only read unless a job asks for more."""
    register = (paths.ROOT / "docs" / "dependencies.md").read_text()
    workflows = sorted((paths.ROOT / ".github" / "workflows").glob("*.yml"))
    assert workflows
    for wf in workflows:
        text = wf.read_text()
        assert yaml.safe_load(text)["permissions"] == {"contents": "read"}, wf.name
        for action, ref in re.findall(r"uses:\s*([\w.-]+/[\w.-]+)@(\S+)", text):
            assert re.fullmatch(r"[0-9a-f]{40}", ref), f"{wf.name}: {action}@{ref} is not a commit"
            assert f"| {action} |" in register and ref in register, (
                f"{action} isn't in the register"
            )
