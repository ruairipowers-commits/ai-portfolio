"""Run puzzle code (the generator's reference code, the solver's own code) away from the app.

The subprocess backend (default; works inside the hardened demo container, which can't start Docker):
  - a fresh temporary workspace holding only the code and copies of the allowed asset files (data/<name>/<file>);
  - Python in isolated mode (-I: no user site, no PYTHON* variables) with an EMPTY environment apart from a few
    determinism settings — no API keys, tokens or database URLs exist in the child;
  - resource limits (CPU seconds, address space, file size, open files) and a wall-clock timeout that kills the
    whole process group;
  - a guard (Python audit hooks) installed before the code runs that refuses network connections, starting
    processes, writing outside the workspace, reading outside the workspace and the Python installation, and
    unpickling (so only safetensors / CSV / JSON can be loaded). Every refusal is recorded even if the code catches
    the exception, and any refusal fails the run.

Audit hooks stop mistakes and casual misuse by model-written code; they are not a boundary against a determined
attacker (native extensions can bypass them). That's acceptable here because the only code that runs is written by
our own generator/solver models from our own prompts — players submit answers, never code. For stronger isolation
use a container per run (`--network none --read-only`), gVisor or Firecracker; see docs/governance.md (SEC-03).
"""
from __future__ import annotations

import hashlib
import os
import resource
import shutil
import signal
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path

GUARD = r'''
import os, sys, site, runpy
WS = os.path.realpath(os.getcwd())
_vfd = os.open(os.path.join(WS, ".violations"), os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
READ_OK = [WS] + [os.path.realpath(p) for p in {sys.prefix, sys.base_prefix, sys.exec_prefix, *site.getsitepackages()}] + \
          ["/proc", "/sys", "/dev", "/usr/lib", "/usr/lib64", "/lib", "/lib64", "/usr/share", "/etc/ld.so.cache",
           "/etc/localtime", "/usr/local/lib"]
WRITE_OK = [WS, "/dev/null"]
BLOCK = {"socket.connect", "socket.bind", "socket.getaddrinfo", "socket.gethostbyname", "subprocess.Popen",
         "os.system", "os.exec", "os.posix_spawn", "os.spawn", "os.fork", "os.forkpty", "pty.spawn",
         "pickle.find_class", "os.kill", "os.killpg", "sys.addaudithook", "urllib.Request"}

def _under(path, roots):
    try:
        p = os.path.realpath(path)
    except Exception:
        return False
    return any(p == r or p.startswith(r.rstrip("/") + "/") for r in roots)

def _deny(why):
    os.write(_vfd, (why[:180] + "\n").encode())
    raise PermissionError("blocked by the puzzle sandbox: " + why)

def hook(event, args):
    if event in BLOCK:
        _deny(event)
    if event == "open" and args and isinstance(args[0], (str, bytes, os.PathLike)):
        path, mode, flags = args[0], args[1] if len(args) > 1 else "r", args[2] if len(args) > 2 else 0
        path = os.fsdecode(path)
        writing = (isinstance(mode, str) and any(c in mode for c in "wax+")) or \
                  (isinstance(flags, int) and flags & (os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_APPEND | os.O_TRUNC))
        if writing and not _under(path, WRITE_OK):
            _deny("write outside the workspace: " + path)
        if not writing and not _under(path, READ_OK):
            _deny("read outside the workspace: " + path)
    if event in ("os.remove", "os.rename", "os.rmdir", "shutil.rmtree", "os.mkdir", "os.chmod", "os.symlink", "os.link"):
        for a in args[:2]:
            if isinstance(a, (str, bytes, os.PathLike)) and not _under(os.fsdecode(a), [WS]):
                _deny(event + " outside the workspace")

sys.addaudithook(hook)
sys.argv[:] = ["main.py"]
runpy.run_path("main.py", run_name="__main__")
'''

SAFE_ENV = {"PYTHONHASHSEED": "0", "OMP_NUM_THREADS": "1", "OPENBLAS_NUM_THREADS": "1", "MKL_NUM_THREADS": "1",
            "HF_HUB_OFFLINE": "1", "TRANSFORMERS_OFFLINE": "1", "PYTHONDONTWRITEBYTECODE": "1", "LANG": "C.UTF-8"}


@dataclass
class Result:
    ok: bool
    stdout: str = ""
    stderr: str = ""
    seconds: float = 0.0
    violations: list[str] = field(default_factory=list)
    timed_out: bool = False
    returncode: int | None = None

    @property
    def answer(self) -> str:
        """By convention the answer is the last line the program prints."""
        lines = [l.strip() for l in self.stdout.strip().splitlines() if l.strip()]
        return lines[-1] if lines else ""

    @property
    def problem(self) -> str:
        if self.violations:
            return "sandbox refused: " + "; ".join(sorted(set(self.violations)))[:300]
        if self.timed_out:
            return "timed out"
        if not self.ok:
            tail = (self.stderr.strip().splitlines() or ["no output"])[-1]
            return f"exited with an error: {tail[:200]}"
        if not self.answer:
            return "printed nothing"
        return ""


def _limits(seconds: int, memory_mb: int):
    def apply():
        os.setsid()
        resource.setrlimit(resource.RLIMIT_CPU, (seconds + 5, seconds + 10))
        if memory_mb:
            resource.setrlimit(resource.RLIMIT_AS, (memory_mb * 2**20, memory_mb * 2**20))
        resource.setrlimit(resource.RLIMIT_FSIZE, (50 * 2**20, 50 * 2**20))
        resource.setrlimit(resource.RLIMIT_NOFILE, (256, 256))
        resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
    return apply


def sha(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()[:16]


def run(code: str, assets: list[dict] | None = None, timeout_s: int | None = None, memory_mb: int | None = None,
        max_output_kb: int | None = None, cfg: dict | None = None) -> Result:
    """Run `code` as main.py in a fresh workspace with the given (already allow-listed) assets staged under data/."""
    from . import assets as assets_mod
    cfg = cfg or _cfg()
    timeout_s = timeout_s or int(cfg.get("timeout_s", 300))
    memory_mb = memory_mb if memory_mb is not None else int(cfg.get("memory_mb", 4096))
    max_out = (max_output_kb or int(cfg.get("max_output_kb", 64))) * 1024
    ws = Path(tempfile.mkdtemp(prefix="puzzle-sbx-"))
    try:
        (ws / "main.py").write_text(code)
        (ws / "_guard.py").write_text(GUARD)
        (ws / "tmp").mkdir()
        for a in assets or []:
            assets_mod.stage(a, ws / "data")
        env = dict(SAFE_ENV, PATH="/usr/bin:/bin", HOME=str(ws), TMPDIR=str(ws / "tmp"))
        t0 = time.perf_counter()
        p = subprocess.Popen([sys.executable, "-I", "-B", "_guard.py"], cwd=ws, env=env, stdout=subprocess.PIPE,
                             stderr=subprocess.PIPE, stdin=subprocess.DEVNULL, preexec_fn=_limits(timeout_s, memory_mb))
        timed_out = False
        try:
            out, err = p.communicate(timeout=timeout_s)
        except subprocess.TimeoutExpired:
            timed_out = True
            try:
                os.killpg(p.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            out, err = p.communicate()
        secs = time.perf_counter() - t0
        vf = ws / ".violations"
        violations = [l for l in vf.read_text().splitlines() if l.strip()] if vf.exists() else []
        res = Result(ok=p.returncode == 0 and not violations and not timed_out,
                     stdout=out[:max_out].decode(errors="replace"), stderr=err[-4000:].decode(errors="replace"),
                     seconds=round(secs, 2), violations=violations, timed_out=timed_out, returncode=p.returncode)
        return res
    finally:
        shutil.rmtree(ws, ignore_errors=True)


def _cfg() -> dict:
    try:
        from .config import Settings
        return Settings.load().puzzles.get("sandbox", {})
    except Exception:  # noqa: BLE001
        return {}
