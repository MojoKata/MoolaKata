"""What a process gives up before it reads a file someone brought (requirements S9.8.4.2):
every socket, local ones included, and signals to any process but itself, through a seccomp
filter; the data directory and everything else it doesn't
need to read, through Landlock where the kernel has it (Linux 5.13 or later); and core dumps.
And the server's own `non-dumpable` mark, so no other process of its account can read its
memory. Linux only, through the C library: no dependency beyond the standard library."""

import ctypes
import ctypes.util
import errno
import os
import platform
import resource
import struct
import sys
from pathlib import Path

PR_SET_DUMPABLE = 4
PR_SET_SECCOMP = 22
PR_SET_NO_NEW_PRIVS = 38
SECCOMP_MODE_FILTER = 2
SECCOMP_RET_ALLOW = 0x7FFF0000
SECCOMP_RET_ERRNO = 0x00050000

# Per machine: its audit arch; the calls refused outright (io_uring could open sockets past the
# filter; a socket of any family, a socket pair, connecting and binding: the worker talks only
# over the pipes it inherited); and the calls that send a signal, allowed only to itself, by
# the process id in their first argument; and where the machine has a second set of numbers
# under the same arch (x86_64's x32 ABI, at bit 30), the first of them: from there on every
# call is refused, so only the native numbers are judged.
ARCHES = {
    "x86_64": {
        "arch": 0xC000003E,
        # io_uring_setup, socket, socketpair, connect, bind, tkill, pidfd_send_signal
        "refused": (425, 41, 53, 42, 49, 200, 424),
        # kill, tgkill, rt_sigqueueinfo, rt_tgsigqueueinfo
        "own": (62, 234, 129, 297),
        "x32": 0x40000000,
    },
    "aarch64": {
        "arch": 0xC00000B7,
        "refused": (425, 198, 199, 203, 200, 130, 424),
        "own": (129, 131, 138, 240),
        "x32": None,
    },
}
ARCHES["arm64"] = ARCHES["aarch64"]
LANDLOCK_CREATE_RULESET, LANDLOCK_ADD_RULE, LANDLOCK_RESTRICT_SELF = 444, 445, 446
LANDLOCK_CREATE_RULESET_VERSION = 1
LANDLOCK_RULE_PATH_BENEATH = 1
FS_EXECUTE, FS_WRITE_FILE, FS_READ_FILE, FS_READ_DIR = 1, 2, 4, 8
FS_ALL_V1 = (1 << 13) - 1  # every right of Landlock's first version
READ = FS_EXECUTE | FS_READ_FILE | FS_READ_DIR


def _libc():
    return ctypes.CDLL(ctypes.util.find_library("c") or "libc.so.6", use_errno=True)


def _prctl(option: int, arg: int = 0, ptr=None) -> None:
    libc = _libc()
    libc.prctl.argtypes = [
        ctypes.c_int,
        ctypes.c_ulong,
        ctypes.c_void_p,
        ctypes.c_ulong,
        ctypes.c_ulong,
    ]
    if libc.prctl(option, arg, ptr, 0, 0) != 0:
        e = ctypes.get_errno()
        raise OSError(e, os.strerror(e))


def not_dumpable() -> bool:
    """This process: no core dump, and its memory closed to the account's other processes."""
    if sys.platform != "linux":
        return False
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
    try:
        _prctl(PR_SET_DUMPABLE, 0)
    except OSError:
        return False
    return True


def _filter(machine: dict, pid: int) -> bytes:
    """A seccomp program for one of `ARCHES`: its `refused` calls refused; its `own` calls,
    which send a signal, allowed only when their first argument is this process (`pid`); a call
    made under another architecture, or numbered at or past its `x32`, refused; everything else
    allowed."""
    arch, refused, own = machine["arch"], machine["refused"], machine["own"]

    def ins(code: int, jt: int, jf: int, k: int) -> bytes:
        return struct.pack("HBBI", code, jt, jf, k)

    ld, jeq, jge, ret = 0x20, 0x15, 0x35, 0x06
    deny = ins(ret, 0, 0, SECCOMP_RET_ERRNO | errno.EPERM)
    allow = ins(ret, 0, 0, SECCOMP_RET_ALLOW)
    out = [
        ins(ld, 0, 0, 4),  # the call's architecture
        ins(jeq, 1, 0, arch),  # ours: on past the next
        deny,
        ins(ld, 0, 0, 0),  # the call's number
    ]
    if machine["x32"] is not None:
        out += [ins(jge, 0, 1, machine["x32"]), deny]  # another ABI's number: refused
    # Each refused call: equal, on to the denial at the end of the list.
    n_ref, n_own = len(refused), len(own)
    for i, nr in enumerate(refused):
        # Skip to `deny_at`: the rest of the refused, the own checks, and the allow before it.
        out.append(ins(jeq, (n_ref - 1 - i) + n_own + 1 + 3, 0, nr))
    for i, nr in enumerate(own):
        out.append(ins(jeq, (n_own - 1 - i) + 1, 0, nr))  # to the pid check
    out += [
        allow,  # anything else
        ins(ld, 0, 0, 16),  # a signal's target: the first argument's low 32 bits
        ins(jeq, 0, 1, pid & 0xFFFFFFFF),  # this process: allowed
        allow,
        deny,
    ]
    return b"".join(out)


def no_network() -> bool:
    """A seccomp filter that refuses this process any socket and any signal to another process,
    for good: it can't be lifted, and it passes to anything the process starts."""
    found = ARCHES.get(platform.machine())
    if sys.platform != "linux" or found is None:
        return False
    program = _filter(found, os.getpid())
    buf = ctypes.create_string_buffer(program)

    class Fprog(ctypes.Structure):
        _fields_ = [("len", ctypes.c_ushort), ("filter", ctypes.c_void_p)]

    prog = Fprog(len(program) // 8, ctypes.cast(buf, ctypes.c_void_p))
    try:
        _prctl(PR_SET_NO_NEW_PRIVS, 1)
        _prctl(PR_SET_SECCOMP, SECCOMP_MODE_FILTER, ctypes.addressof(prog))
    except OSError:
        return False
    return True


def _syscall(nr: int, *args) -> int:
    libc = _libc()
    libc.syscall.restype = ctypes.c_long
    return libc.syscall(ctypes.c_long(nr), *args)


def landlock_abi() -> int:
    """Landlock's version on this kernel; 0 where it has none."""
    if sys.platform != "linux":
        return 0
    v = _syscall(
        LANDLOCK_CREATE_RULESET,
        None,
        ctypes.c_size_t(0),
        ctypes.c_uint32(LANDLOCK_CREATE_RULESET_VERSION),
    )
    return int(v) if v > 0 else 0


def read_only(roots: list[Path], writable: list[Path] = (), refuse: Path | None = None) -> bool:
    """Landlock: from now on this process reads only beneath `roots` (and writes only beneath
    `writable`), so the data directory, which no root contains, is closed to it. A root that
    contains `refuse` is left out. False where the kernel has no Landlock."""
    if landlock_abi() < 1:
        return False
    attr = struct.pack("Q", FS_ALL_V1)
    fd = _syscall(
        LANDLOCK_CREATE_RULESET,
        ctypes.c_char_p(attr),
        ctypes.c_size_t(len(attr)),
        ctypes.c_uint32(0),
    )
    if fd < 0:
        return False
    try:
        rules = [(p, READ) for p in roots] + [(p, READ | FS_WRITE_FILE) for p in writable]
        for path, access in rules:
            path = Path(path)
            if refuse is not None and (refuse == path or path in refuse.parents):
                continue
            try:
                pfd = os.open(path, os.O_PATH | os.O_CLOEXEC)
            except OSError:
                continue
            try:
                allowed = (
                    access
                    if path.is_dir()
                    else access & (FS_EXECUTE | FS_READ_FILE | FS_WRITE_FILE)
                )
                rule = struct.pack("=Qi", allowed, pfd)
                _syscall(
                    LANDLOCK_ADD_RULE,
                    ctypes.c_int(fd),
                    ctypes.c_int(LANDLOCK_RULE_PATH_BENEATH),
                    ctypes.c_char_p(rule),
                    ctypes.c_uint32(0),
                )
            finally:
                os.close(pfd)
        _prctl(PR_SET_NO_NEW_PRIVS, 1)
        return _syscall(LANDLOCK_RESTRICT_SELF, ctypes.c_int(fd), ctypes.c_uint32(0)) == 0
    finally:
        os.close(fd)
