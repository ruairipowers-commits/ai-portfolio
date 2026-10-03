"""deploy/selfhost/deploy-guard.py: the root-owned check update.sh runs before every deploy."""
import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location("guard", ROOT / "deploy" / "selfhost" / "deploy-guard.py")
G = importlib.util.module_from_spec(spec)
spec.loader.exec_module(G)

SAFE = {"security_opt": ["no-new-privileges:true"], "cap_drop": ["ALL"], "mem_limit": "268435456", "cpus": 1.0}


def stack(**services):
    return {"services": services}


def app(**kw):
    return {**SAFE, "build": {"context": str(ROOT / "projects" / "site-assistant")}, **kw}


def test_the_generated_stack_shape_passes(tmp_path):
    caddy = {**SAFE, "image": "caddy:2-alpine", "cap_add": ["NET_BIND_SERVICE"],
             "ports": [{"host_ip": "127.0.0.1", "target": 80, "published": "8088"}],
             "volumes": [{"type": "bind", "source": str(ROOT / "deploy/selfhost/generated/Caddyfile"), "target": "/etc/caddy/Caddyfile"}]}
    ollama = {**SAFE, "image": "ollama/ollama:latest", "devices": [{"source": "/dev/dri", "target": "/dev/dri"}],
              "volumes": [{"type": "volume", "source": "ollama-models", "target": "/root/.ollama"}]}
    assert G.check(stack(**{"site-assistant": app(), "caddy": caddy, "ollama": ollama}), ROOT) == []


def test_everything_dangerous_is_refused():
    bad = {"privileged": True, "network_mode": "host", "pid": "host", "cap_add": ["SYS_ADMIN"],
           "security_opt": ["seccomp:unconfined"], "image": "evil/miner:latest",
           "volumes": [{"type": "bind", "source": "/var/run/docker.sock", "target": "/var/run/docker.sock"},
                       {"type": "bind", "source": "/etc", "target": "/host-etc"}],
           "devices": ["/dev/sda:/dev/sda"], "ports": [{"host_ip": "", "target": 22, "published": "2222"}]}
    problems = "\n".join(G.check(stack(x=bad), ROOT))
    for want in ("privileged", "network_mode: host", "pid: host", "drop all capabilities", "SYS_ADMIN",
                 "no-new-privileges", "unconfined", "no memory limit", "no CPU limit", "Docker socket",
                 "bind-mounts /etc", "host device /dev/sda", "all interfaces", "unexpected image"):
        assert want in problems, want


def test_ports_on_tailscale_ok_but_lan_refused_and_builds_outside_projects_refused():
    ok = app(ports=[{"host_ip": "100.101.102.103", "target": 80, "published": "8088"}])
    lan = app(ports=[{"host_ip": "192.168.1.20", "target": 80, "published": "8088"}])
    outside = {**SAFE, "build": {"context": "/tmp/whatever"}}
    assert G.check(stack(a=ok), ROOT) == []
    assert "192.168.1.20" in G.check(stack(a=lan), ROOT)[0]
    assert "only the repo's projects/ folder" in G.check(stack(a=outside), ROOT)[0]
    gpu_elsewhere = app(devices=[{"source": "/dev/dri", "target": "/dev/dri"}])
    assert "host device /dev/dri" in G.check(stack(**{"site-assistant": gpu_elsewhere}), ROOT)[0]


def test_cli_exit_codes(tmp_path, capsys):
    import json
    f = tmp_path / "c.json"
    f.write_text(json.dumps(stack(a=app())))
    assert G.main([str(f), "--root", str(ROOT)]) == 0
    f.write_text(json.dumps(stack(a={"image": "ai-portfolio/x"})))
    assert G.main([str(f), "--root", str(ROOT)]) == 1 and "refused:" in capsys.readouterr().out
