#!/usr/bin/env python3
"""Deploy guard: refuse to start a demo stack that could take over this machine.

update.sh deploys whatever passes CI on main. That makes anyone who can push to main able to run code here, so
before every deploy update.sh asks this guard to check the *resolved* stack (`docker compose … config --format
json`). The installed copy lives at /usr/local/lib/ai-portfolio/deploy-guard.py, owned by root. A change pushed to
the repo can't loosen it: the repo copy is only the source that `sudo install.sh` copies.

Every service must:
  - not be privileged, and not share the host's network, PID, IPC or user namespaces;
  - drop all capabilities (`cap_drop: [ALL]`) and add back nothing beyond NET_BIND_SERVICE (none of ours do);
  - set `no-new-privileges`, and not switch off seccomp or AppArmor;
  - have a memory limit and a CPU limit;
  - only bind-mount paths inside deploy/selfhost (never the Docker socket or anything else on the host);
  - publish ports only on loopback (127.0.0.1) or a Tailscale address (100.64.0.0/10);
  - pass through no host devices other than /dev/dri (the iGPU, for Ollama only);
  - build from the repo's projects/ folder or run one of the known images.

    python3 deploy-guard.py resolved-compose.json [--root /path/to/ai-portfolio]
Exit 0: allowed. Exit 1: refused, with one line per problem. Standard library only (runs with any python3).
"""
from __future__ import annotations

import ipaddress
import json
import sys
from pathlib import Path

ALLOWED_CAP_ADD = {"NET_BIND_SERVICE"}
ALLOWED_IMAGES = ("ai-portfolio/", "ollama/ollama", "caddy", "cloudflare/cloudflared",
                  "docker.io/ollama/ollama", "docker.io/library/caddy", "docker.io/cloudflare/cloudflared")
DEVICE_OK = {"ollama": {"/dev/dri"}}
TAILSCALE = ipaddress.ip_network("100.64.0.0/10")


def _limits(svc: dict) -> tuple[bool, bool]:
    lim = ((svc.get("deploy") or {}).get("resources") or {}).get("limits") or {}
    mem = svc.get("mem_limit") or lim.get("memory")
    cpu = svc.get("cpus") or lim.get("cpus") or svc.get("cpu_quota")
    return bool(mem and str(mem) not in ("0", "-1")), bool(cpu and str(cpu) not in ("0", "0.0"))


def _inside(path: str, allowed: Path) -> bool:
    try:
        Path(path).resolve().relative_to(allowed.resolve())
        return True
    except ValueError:
        return False


def check(stack: dict, root: Path) -> list[str]:
    problems: list[str] = []
    selfhost = root / "deploy" / "selfhost"
    projects = root / "projects"
    for name, svc in (stack.get("services") or {}).items():
        p = lambda msg: problems.append(f"{name}: {msg}")          # noqa: E731
        if svc.get("privileged"):
            p("privileged container")
        for key in ("network_mode", "pid", "ipc", "userns_mode", "uts"):
            v = str(svc.get(key) or "")
            if v == "host" or v.startswith("container:") or v.startswith("service:"):
                p(f"{key}: {v} (shares the host's or another container's namespace)")
        caps_drop = {c.upper() for c in svc.get("cap_drop") or []}
        if "ALL" not in caps_drop:
            p("does not drop all capabilities (cap_drop: [ALL])")
        extra = {c.upper().removeprefix("CAP_") for c in svc.get("cap_add") or []} - ALLOWED_CAP_ADD
        if extra:
            p(f"adds capabilities {sorted(extra)}")
        sec = [str(s).replace("=", ":") for s in svc.get("security_opt") or []]
        if not any(s.startswith("no-new-privileges") and not s.endswith("false") for s in sec):
            p("missing security_opt no-new-privileges:true")
        if any("unconfined" in s for s in sec):
            p(f"security_opt switches off a protection: {sec}")
        has_mem, has_cpu = _limits(svc)
        if not has_mem:
            p("no memory limit")
        if not has_cpu:
            p("no CPU limit")
        for v in svc.get("volumes") or []:
            if isinstance(v, str):                                   # short syntax (unresolved file)
                src = v.split(":")[0]
                kind = "bind" if src.startswith((".", "/", "~")) else "volume"
            else:
                src, kind = str(v.get("source") or ""), v.get("type", "volume")
            if "docker.sock" in src:
                p(f"mounts the Docker socket ({src}): that is root on the host")
            elif kind == "bind" and not _inside(src, selfhost):
                p(f"bind-mounts {src} from the host (only deploy/selfhost is allowed)")
        for d in svc.get("devices") or []:
            src = d.get("source") if isinstance(d, dict) else str(d).split(":")[0]
            if src not in DEVICE_OK.get(name, set()):
                p(f"passes through host device {src}")
        for port in svc.get("ports") or []:
            ip = (port.get("host_ip") if isinstance(port, dict) else None) or ""
            if isinstance(port, str):
                parts = port.split(":")
                ip = parts[0] if len(parts) == 3 else ""
            try:
                ok = ip and (ipaddress.ip_address(ip).is_loopback or ipaddress.ip_address(ip) in TAILSCALE)
            except ValueError:
                ok = False
            if not ok:
                p(f"publishes a port on {ip or 'all interfaces'} (allowed: 127.0.0.1 or a Tailscale address)")
        build = svc.get("build")
        if build:
            ctx = build.get("context") if isinstance(build, dict) else str(build)
            if not _inside(str(ctx), projects):
                p(f"builds from {ctx} (only the repo's projects/ folder is allowed)")
        elif not str(svc.get("image") or "").startswith(ALLOWED_IMAGES):
            p(f"runs an unexpected image {svc.get('image')!r}")
    return problems


def main(argv: list[str]) -> int:
    if not argv or argv[0] in ("-h", "--help"):
        print(__doc__)
        return 0 if argv else 2
    root = Path(__file__).resolve().parents[2]
    if "--root" in argv:
        root = Path(argv[argv.index("--root") + 1])
    stack = json.loads(Path(argv[0]).read_text())
    problems = check(stack, root)
    for line in problems:
        print(f"refused: {line}")
    if not problems:
        print(f"deploy guard: {len(stack.get('services') or {})} services OK")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
