"""moolakata.toml: what the operator sets on the host (requirements S13.3, S15.4, S17.8).

Everything a user or admin can change at run time is a Setting in the database (settings.py).
This file holds only what the server needs before the database is open, and it never holds a
secret: the master key is a recovery phrase that is never stored anywhere (S15.4).
"""

import ipaddress
import os
import tomllib
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

DEFAULT_PORT = 37373
DEFAULT_CONFIG = Path("/etc/moolakata.toml")
# Where host commands reach the running server (S13.6): a tmpfs of the server's account.
DEFAULT_SOCKET = Path("/run/moolakata/sock")


class RefuseStart(Exception):
    """A reason only an operator can fix: the server says why on one line and exits 78."""


@dataclass(frozen=True)
class Config:
    name: str
    mode: Literal["proxy", "tls"]
    data_dir: Path
    backup_dir: Path
    host: str = "0.0.0.0"  # noqa: S104 - all of the container's interfaces (S13.3)
    port: int = DEFAULT_PORT
    trusted_proxies: tuple[ipaddress.IPv4Address | ipaddress.IPv6Address, ...] = ()
    tls_cert: Path | None = None
    tls_key: Path | None = None
    dev: bool = False
    stubs: bool = False
    path: Path | None = None
    mail_folder: Path | None = None
    cert_names: tuple[str, ...] = ()  # more names for the self-signed certificate
    socket_path: Path = DEFAULT_SOCKET

    @property
    def db_path(self) -> Path:
        return self.data_dir / "moolakata.db"

    @property
    def keyring_path(self) -> Path:
        return self.data_dir / "keyring"

    @property
    def receipts_dir(self) -> Path:
        return self.data_dir / "receipts"

    @property
    def tls_dir(self) -> Path:
        return self.data_dir / "tls"

    @property
    def mail_dir(self) -> Path:
        """Where emails are written while SMTP is not set up (and always in dev mode)."""
        return self.mail_folder or self.data_dir / "mail"

    @property
    def outbox_dir(self) -> Path:
        """Where an earlier release kept emails waiting for SMTP, in the clear; the mail task
        moves what it finds into the database's queue (S16.2)."""
        return self.data_dir / "outbox"


# Every key the file may hold, by section; any other refuses the start.
KEYS = {
    "server": {"name", "mode", "host", "port", "trusted_proxies"},
    "paths": {"data", "backups", "socket"},
    "tls": {"cert", "key", "names"},
}


def _path(table: dict, key: str, where: str) -> Path:
    value = table.get(key)
    if not isinstance(value, str) or not value:
        raise RefuseStart(f"{where}: [{key}] must be set to a path")
    return Path(value)


# The configuration given in the environment instead of a file (S17.8): the same TOML, for
# hosts where mounting a file is awkward, such as TrueNAS's Install via YAML.
CONFIG_ENV = "MOOLAKATA_CONFIG"


def configured(given: str | None = None, env: Mapping[str, str] = os.environ) -> Config:
    """The server's configuration: the file named with --config, else the TOML in
    MOOLAKATA_CONFIG, else /etc/moolakata.toml. It holds no secret either way."""
    if given:
        return load(Path(given))
    if text := env.get(CONFIG_ENV, "").strip():
        try:
            raw = tomllib.loads(text)
        except tomllib.TOMLDecodeError as e:
            raise RefuseStart(f"{CONFIG_ENV} is not valid TOML: {e}") from None
        return parse(raw, CONFIG_ENV)
    return load(DEFAULT_CONFIG)


def load(path: Path) -> Config:
    """Read and check the config file; any problem refuses the start."""
    try:
        raw = tomllib.loads(path.read_text())
    except FileNotFoundError:
        raise RefuseStart(f"config file {path} does not exist") from None
    except PermissionError:
        raise RefuseStart(f"config file {path} cannot be read by this account") from None
    except tomllib.TOMLDecodeError as e:
        raise RefuseStart(f"config file {path} is not valid TOML: {e}") from None
    return parse(raw, str(path), path)


def _proxy(entry, where: str) -> ipaddress.IPv4Address | ipaddress.IPv6Address:
    """A trusted proxy: its own address, written alone or as a /32 or /128, never a range,
    since anything else in a range could pose as the proxy (S13.3)."""
    try:
        net = ipaddress.ip_network(entry if isinstance(entry, str) else "", strict=False)
    except ValueError, TypeError:
        raise RefuseStart(f"{where}: server.trusted_proxies: {entry!r} is not an address") from None
    if net.num_addresses != 1:
        raise RefuseStart(
            f"{where}: server.trusted_proxies: {entry!r} is a range; name the proxy's own "
            "address, since anything else in a range could pose as it (S13.3)"
        )
    return net.network_address


def parse(raw: dict, where: str, path: Path | None = None) -> Config:
    if "keys" in raw:
        raise RefuseStart(
            f"{where}: [keys] is not used: the master key is a recovery phrase entered when "
            "the server starts, never a file, and the keyring records its rotations (S15.4)"
        )
    unknown = set(raw) - set(KEYS)
    if unknown:
        raise RefuseStart(f"{where}: unknown section [{sorted(unknown)[0]}]")
    for section, keys in KEYS.items():
        table = raw.get(section, {})
        if not isinstance(table, dict):
            raise RefuseStart(f"{where}: [{section}] must be a section")
        if extra := sorted(set(table) - keys):
            # A misspelt key would otherwise start with its default (S13.6).
            raise RefuseStart(f"{where}: unknown key {section}.{extra[0]}")
    server = raw.get("server", {})
    paths = raw.get("paths", {})
    tls = raw.get("tls", {})

    name = server.get("name", "moolakata")
    if not isinstance(name, str) or not name.strip():
        raise RefuseStart(f"{where}: server.name must be a non-empty string")
    mode = server.get("mode", "proxy")
    if mode not in ("proxy", "tls"):
        raise RefuseStart(f'{where}: server.mode must be "proxy" or "tls", not {mode!r}')
    port = server.get("port", DEFAULT_PORT)
    if not isinstance(port, int) or not 1 <= port <= 65535:
        raise RefuseStart(f"{where}: server.port must be a port number")
    host = server.get("host", "0.0.0.0")  # noqa: S104
    proxies = server.get("trusted_proxies", [])
    if not isinstance(proxies, list):
        raise RefuseStart(f"{where}: server.trusted_proxies must be a list of addresses")
    proxies = [_proxy(entry, where) for entry in proxies]

    data_dir = _path(paths, "data", f"{where} [paths]")
    backup_dir = _path(paths, "backups", f"{where} [paths]")
    socket = _path(paths, "socket", f"{where} [paths]") if "socket" in paths else DEFAULT_SOCKET

    cert = tls.get("cert")
    key = tls.get("key")
    if bool(cert) != bool(key):
        raise RefuseStart(f"{where}: [tls] needs both cert and key, or neither")
    names = tls.get("names", [])
    if not isinstance(names, list) or not all(isinstance(n, str) and n.strip() for n in names):
        raise RefuseStart(f"{where}: [tls] names must be a list of host names or addresses")

    for p, label in ((data_dir, "data"), (backup_dir, "backups"), (socket, "socket")):
        if not p.is_absolute():
            raise RefuseStart(f"{where}: the {label} path must be absolute")
    _check_apart(data_dir, backup_dir)

    return Config(
        name=name.strip(),
        mode=mode,
        host=host,
        port=port,
        trusted_proxies=tuple(proxies),
        data_dir=data_dir,
        backup_dir=backup_dir,
        tls_cert=Path(cert) if cert else None,
        tls_key=Path(key) if key else None,
        cert_names=tuple(n.strip() for n in names),
        path=path,
        socket_path=socket,
    )


def _check_apart(data_dir: Path, backup_dir: Path) -> None:
    if backup_dir.resolve().is_relative_to(data_dir.resolve()):
        raise RefuseStart("the backup directory is inside the data directory")
