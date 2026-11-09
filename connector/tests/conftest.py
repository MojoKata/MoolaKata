"""The connector's tests run under the server's environment (web/check), which has
`cryptography` and, for the end-to-end test, MoolaKata itself. The connector's package is put
on the path here; it imports nothing from MoolaKata (S18.1.2). The server's own test
fixtures (a server, its clients, users) are loaded from its conftest under another name and
registered here, so the end-to-end test can stand up a real MoolaKata in-process."""

import importlib.util
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

SERVER_TESTS = ROOT.parent / "web" / "server" / "tests"
if str(SERVER_TESTS) not in sys.path:
    sys.path.append(str(SERVER_TESTS))

_spec = importlib.util.spec_from_file_location("server_conftest", SERVER_TESTS / "conftest.py")
server_conftest = importlib.util.module_from_spec(_spec)
sys.modules["server_conftest"] = server_conftest
_spec.loader.exec_module(server_conftest)

for _name in (
    "config",
    "migrated",
    "master_key",
    "keyed_config",
    "store",
    "server",
    "client",
    "admin_client",
):
    globals()[_name] = getattr(server_conftest, _name)
