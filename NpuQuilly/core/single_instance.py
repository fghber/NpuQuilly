"""Single-instance lock via lockfile in temp dir.

A lock is honored ONLY with positive evidence: the recorded PID exists AND its
command line belongs to NpuQuilly. Dead PIDs, recycled PIDs and garbage content
are reclaimed. Query failures fail closed (keep the lock) to avoid duplicates.
"""
import os
import subprocess
import tempfile
from pathlib import Path

LOCK = Path(tempfile.gettempdir()) / "npuquilly.lock"
MARKERS = ("npuquilly", "main.py")


def lock_pid() -> int | None:
    try:
        return int(LOCK.read_text(encoding="utf-8").strip().split()[0])
    except Exception:
        return None


def proc_cmdline(pid: int) -> str | None:
    """Owning command line via CIM. None = query failed (unknown). '' = PID dead."""
    try:
        ps = f"(Get-CimInstance Win32_Process -Filter 'ProcessId={pid}').CommandLine"
        r = subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command", ps],
                           capture_output=True, text=True, timeout=20)
        if r.returncode != 0:
            return None
        return (r.stdout or "").strip()
    except Exception:
        return None


def owner_live(pid: int) -> bool:
    cmd = proc_cmdline(pid)
    if cmd is None:
        return True  # unknown: fail closed, don't clobber a maybe-live instance
    if not cmd:
        return False  # PID dead
    return any(m in cmd.lower() for m in MARKERS)  # recycled PID -> False


def _claim() -> bool:
    fd = os.open(str(LOCK), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    os.write(fd, str(os.getpid()).encode())
    os.close(fd)
    return True


def acquire() -> bool:
    try:
        return _claim()
    except FileExistsError:
        pass
    pid = lock_pid()
    if pid is not None and owner_live(pid):
        return False
    # Stale, recycled, or garbage lock — reclaim.
    try:
        LOCK.unlink()
    except FileNotFoundError:
        pass
    try:
        return _claim()
    except FileExistsError:
        return False


def release():
    try:
        # Only remove our own lock (avoid deleting a successor's after reclaim races).
        if lock_pid() == os.getpid():
            LOCK.unlink()
    except FileNotFoundError:
        pass
