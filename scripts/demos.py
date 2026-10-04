"""Live demos: one registry of apps, deployable to whichever target portfolio.yaml (or DEMOS_TARGET) names.

    python scripts/demos.py list                       # apps, their paths and the resolved target/URLs
    python scripts/demos.py render selfhost [--out D]  # docker-compose.yml + Caddyfile + landing page
    python scripts/demos.py render cloudflare          # wrangler.jsonc + Worker for Cloudflare Containers
    python scripts/demos.py render cloudrun            # router Caddyfile + deploy plan for Google Cloud Run
    python scripts/demos.py deploy [target]            # what CI runs (huggingface | cloudflare | cloudrun)

An app is any project with a Dockerfile.space, in portfolio.yaml order — a new project is deployed with no change
here. Every image listens on 7860 and serves under a path prefix when told to (Streamlit:
STREAMLIT_SERVER_BASE_URL_PATH; the console: ROOT_PATH), so the same image works at a domain root (Hugging Face)
or at <base_url>/<slug>/ (self-host, Cloudflare, Cloud Run).
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from portfolio_config import CONSOLE, governance_url, links, resolve  # noqa: E402

PORT = 7860
DEFAULT_MEMORY = {"trade-ops-exceptions": "3g", "eod-heartbeat": "3g"}


# ---------------------------------------------------------------- registry
def apps() -> list[dict]:
    order = yaml.safe_load((ROOT / "portfolio.yaml").read_text()).get("projects", [])
    found = [p.name for p in (ROOT / "projects").iterdir() if (p / "Dockerfile.space").exists()]
    out = []
    for slug in [s for s in order if s in found] + sorted(s for s in found if s not in order):
        spec_p = ROOT / "specs" / f"{slug}.yaml"
        spec = yaml.safe_load(spec_p.read_text()) if spec_p.exists() else {}
        demo = spec.get("demo") or {}
        kind = demo.get("server") or ("fastapi" if slug == CONSOLE else "streamlit")
        out.append({"slug": slug, "path": f"/{slug}", "kind": kind, "needs": demo.get("needs", []),
                    "title": demo.get("title", slug), "emoji": demo.get("emoji", "🤖"),
                    "description": demo.get("short_description", spec.get("title", "")),
                    "memory": demo.get("memory", DEFAULT_MEMORY.get(slug, "2g")),
                    "env_passthrough": demo.get("env", []), "volume": demo.get("volume", ""),
                    # internet access: only apps that need it (email, fetching the site, model pulls); the console
                    # always (alert emails). Everything else runs on an internal network with no route out.
                    "egress": bool(demo.get("egress", slug == CONSOLE))})
    return out


def app_env(app: dict, c: dict, with_prefix: bool) -> dict[str, str]:
    """Non-secret environment for one app. Secrets (ingest/admin tokens, DATABASE_URL) are added per target."""
    l = links(app["slug"], c)
    env = {"PORTFOLIO_DEMO": "1",
           "PORTFOLIO_BLOG_URL": l["blog_url"], "PORTFOLIO_SOURCE_URL": l["source_url"],
           "PORTFOLIO_PORTFOLIO_URL": l["portfolio_url"], "PORTFOLIO_DEMO_URL": l["demo_url"],
           "PORTFOLIO_CONSOLE_URL": l["console_url"],
           # the banner the apps share with the blog
           "PORTFOLIO_SITE_TITLE": l["site_title"], "PORTFOLIO_STANDARD_URL": l["standard_url"],
           "PORTFOLIO_BLOG_INDEX_URL": l["blog_index_url"], "PORTFOLIO_ABOUT_URL": l["about_url"],
           "PORTFOLIO_DEMOS_HOME_URL": l["demos_home_url"]}
    if app["kind"] == "streamlit":
        if with_prefix:
            env["STREAMLIT_SERVER_BASE_URL_PATH"] = app["slug"]
    elif with_prefix:
        env["ROOT_PATH"] = app["path"]
    if app["slug"] != CONSOLE:
        env["GOVERNANCE_URL"] = governance_url(c)
    if app["kind"] == "fastapi":
        env.update({"PORTFOLIO_SITE_URL": c["site_url"], "PORTFOLIO_GITHUB_OWNER": c["github_owner"],
                    "PORTFOLIO_DEMOS_URL": c["demos_url"], "PORTFOLIO_DEMOS_TARGET": c["demos_target"],
                    "PORTFOLIO_SOURCE_BASE": l["source_url"].rsplit("/", 1)[0]})
    return {k: v for k, v in env.items() if v}


def landing_html(c: dict, items: list[dict]) -> str:
    """The page at <base_url>/ — a list of the demos with links back to the write-ups."""
    rows = "\n".join(
        f'<li><a class="app" href="{a["path"]}/"><span class="e">{a["emoji"]}</span><b>{a["title"]}</b></a>'
        f'<span class="d">{a["description"]}</span>'
        f'<a class="w" href="{links(a["slug"], c)["blog_url"]}">write-up</a></li>' for a in items)
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1"><title>Live demos · AI workflow portfolio</title>
<style>
:root{{color-scheme:light dark;--bg:#f9f9f7;--card:#fff;--ink:#0b0b0b;--mut:#52514e;--line:rgba(0,0,0,.1);--a:#2a78d6}}
@media (prefers-color-scheme:dark){{:root{{--bg:#0d0d0d;--card:#1a1a19;--ink:#fff;--mut:#c3c2b7;--line:rgba(255,255,255,.12);--a:#6da7ec}}}}
body{{margin:0;background:var(--bg);color:var(--ink);font:15px/1.5 system-ui,-apple-system,"Segoe UI",sans-serif}}
main{{max-width:760px;margin:0 auto;padding:40px 16px}} h1{{font-size:26px;margin:0 0 6px}} p{{color:var(--mut)}}
ul{{list-style:none;padding:0;margin:24px 0}} li{{background:var(--card);border:1px solid var(--line);border-radius:12px;
padding:14px 16px;margin:10px 0;display:grid;grid-template-columns:1fr auto;gap:2px 12px}}
.app{{color:var(--ink);text-decoration:none;font-size:17px}} .app:hover b{{text-decoration:underline}} .e{{margin-right:8px}}
.d{{grid-column:1;color:var(--mut);font-size:14px}} .w{{grid-row:1;grid-column:2;color:var(--a);font-size:14px}}
</style></head><body><main>
<h1>Live demos</h1>
<p>Each app runs the offline mock model — no API keys — and gives every visitor a private copy of the synthetic data.
Every visit and action is reported to the governance console, which can switch any app off.
Back to the <a href="{c['site_url']}/" style="color:var(--a)">portfolio</a>.</p>
<ul>
{rows}
</ul></main></body></html>
"""


# ---------------------------------------------------------------- self-host (docker compose + Caddy + Cloudflare Tunnel)
# Every container: no privilege escalation, no Linux capabilities and a cap on processes, on top of a memory and CPU
# limit. Caddy gets back NET_BIND_SERVICE and nothing else: its image marks /usr/bin/caddy with that file capability,
# so without it in the container the binary can't even start ("operation not permitted"), whatever port it binds. deploy/selfhost/deploy-guard.py refuses a stack without these.
HARDEN = {"security_opt": ["no-new-privileges:true"], "cap_drop": ["ALL"], "pids_limit": 512}


def render_selfhost(out: Path, c: dict) -> list[Path]:
    items = apps()
    out.mkdir(parents=True, exist_ok=True)
    rel = os.path.relpath(ROOT, out)
    services: dict = {}
    for a in items:
        env = app_env(a, c, with_prefix=True)
        env["GOVERNANCE_INGEST_TOKEN"] = "${GOVERNANCE_INGEST_TOKEN:-}"
        svc = {"build": {"context": f"{rel}/projects/{a['slug']}", "dockerfile": "Dockerfile.space"},
               "image": f"ai-portfolio/{a['slug']}:latest", "restart": "unless-stopped",
               "environment": env, "mem_limit": a["memory"], "cpus": 2.0, **HARDEN,
               "networks": ["demos", "egress"] if a["egress"] else ["demos"]}
        if a["slug"] != CONSOLE and a["kind"] == "fastapi":
            env.update({"FORWARDED_ALLOW_IPS": "*", **{k: "${%s:-}" % k for k in a.get("env_passthrough", [])}})
        if "ollama" in a["needs"]:
            env.update({"OLLAMA_URL": "http://ollama:11434", "OLLAMA_MODEL": "${OLLAMA_MODEL:-}",
                        "OLLAMA_THINK": "${OLLAMA_THINK:-}", "OLLAMA_NUM_THREAD": "${OLLAMA_NUM_THREAD:-}"})
        if a["slug"] != CONSOLE and a.get("volume"):
            svc["volumes"] = [f"{a['slug']}-data:{a['volume']}"]
        if a["slug"] == CONSOLE:
            env.update({"GOVERNANCE_ADMIN_TOKEN": "${GOVERNANCE_ADMIN_TOKEN:-}", "DATABASE_URL": "${GOVERNANCE_DATABASE_URL:-}",
                        "FORWARDED_ALLOW_IPS": "*",
                        # Content tab: ratings and suggestions from the site assistant, over the compose network
                        **({"ASSISTANT_URL": "http://site-assistant:7860",
                            "ASSISTANT_ADMIN_TOKEN": "${ASSISTANT_ADMIN_TOKEN:-}"}
                           if any(x["slug"] == "site-assistant" for x in items) else {}),
                        # governance alert emails (console Settings page); empty = kept in the console's outbox only
                        **{k: "${%s:-}" % k for k in ("SMTP_HOST", "SMTP_PORT", "SMTP_USER", "SMTP_PASSWORD", "SMTP_FROM",
                                                      "GOVERNANCE_ALERT_EMAIL")}})
            svc["volumes"] = ["console-data:/app/warehouse"]   # live history survives restarts and rebuilds
        services[a["slug"]] = svc
    if any("ollama" in a["needs"] for a in items):
        # local open models for apps that need them (site-assistant). CPU by default; for the AMD iGPU see the
        # README ("Faster answers"): Vulkan via docker-compose.override.yml. One model, one request at a time keeps
        # memory low and lets the cached prompt prefix (rules + profile card) be reused between questions.
        # Capped so a burst of questions can't starve the demos or the machine (OLLAMA_CPUS / OLLAMA_MEM_LIMIT in .env).
        services["ollama"] = {"image": "${OLLAMA_IMAGE:-ollama/ollama:latest}", "restart": "unless-stopped",
                              "volumes": ["ollama-models:/root/.ollama"], "networks": ["demos", "egress"],
                              "mem_limit": "${OLLAMA_MEM_LIMIT:-14g}", "cpus": "${OLLAMA_CPUS:-8}", **HARDEN,
                              "environment": {"OLLAMA_KEEP_ALIVE": "24h", "OLLAMA_NUM_PARALLEL": "1",
                                              "OLLAMA_MAX_LOADED_MODELS": "1"}}
    services["caddy"] = {"image": "caddy:2-alpine", "restart": "unless-stopped",
                         "ports": ["${DEMOS_BIND:-127.0.0.1}:${DEMOS_PORT:-8088}:80"],
                         "volumes": ["./Caddyfile:/etc/caddy/Caddyfile:ro", "./site:/srv:ro"],
                         "mem_limit": "256m", "cpus": 1.0, **HARDEN, "cap_add": ["NET_BIND_SERVICE"],
                         "depends_on": [a["slug"] for a in items], "networks": ["demos", "egress"]}
    services["cloudflared"] = {"image": "cloudflare/cloudflared:latest", "restart": "unless-stopped",
                               "command": "tunnel --no-autoupdate run", "environment": {"TUNNEL_TOKEN": "${TUNNEL_TOKEN:-}"},
                               "mem_limit": "256m", "cpus": 1.0, **HARDEN,
                               "depends_on": ["caddy"], "networks": ["demos", "egress"], "profiles": ["tunnel"]}
    compose = {"name": "ai-portfolio-demos", "services": services,
               # demos: internal only (no route to the internet); egress: for the services that need to reach out
               "networks": {"demos": {"internal": True}, "egress": {}},
               "volumes": {"console-data": {}, "ollama-models": {},
                           **{f"{a['slug']}-data": {} for a in items if a["slug"] != CONSOLE and a.get("volume")}}}
    header = ("# GENERATED by scripts/demos.py render selfhost — edit the generator, not this file.\n"
              "# Run from deploy/selfhost: docker compose -f generated/docker-compose.yml --env-file .env up -d --build\n")
    files = []
    p = out / "docker-compose.yml"
    p.write_text(header + yaml.safe_dump(compose, sort_keys=False, width=120))
    files.append(p)
    routes = "\n".join(f"\tredir {a['path']} {a['path']}/ 308\n\thandle {a['path']}/* {{\n\t\treverse_proxy {a['slug']}:{PORT}\n\t}}"
                       for a in items)
    p = out / "Caddyfile"
    p.write_text("# GENERATED by scripts/demos.py — one path per app; WebSockets (Streamlit) pass through.\n"
                 "{\n\tadmin off\n\tauto_https off\n}\n\n:80 {\n"
                 # visitors arrive through Cloudflare, which says which scheme they used: send plain HTTP to HTTPS
                 "\t@plainhttp header X-Forwarded-Proto http\n\tredir @plainhttp https://{host}{uri} 308\n"
                 "\theader {\n\t\t-Server\n\t\tStrict-Transport-Security \"max-age=15552000\"\n"
                 "\t\tX-Content-Type-Options nosniff\n\t\tX-Frame-Options SAMEORIGIN\n"
                 "\t\tReferrer-Policy strict-origin-when-cross-origin\n\t}\n\tencode gzip\n" + routes + "\n\thandle {\n\t\troot * /srv\n\t\tfile_server\n\t}\n}\n")
    files.append(p)
    (out / "site").mkdir(exist_ok=True)
    p = out / "site" / "index.html"
    p.write_text(landing_html(c, items))
    files.append(p)
    return files


# ---------------------------------------------------------------- Cloudflare Containers (untested)
def _cls(slug: str) -> str:
    return "".join(w.capitalize() for w in slug.split("-"))


def render_cloudflare(out: Path, c: dict) -> list[Path]:
    if not c["demos_url"]:
        raise SystemExit("Set DEMOS_URL (e.g. https://demos.example.com) for the cloudflare target")
    items = apps()
    host = c["demos_url"].split("://", 1)[1].split("/")[0]
    zone = ".".join(host.split(".")[-2:])
    (out / "src").mkdir(parents=True, exist_ok=True)
    rel = os.path.relpath(ROOT, out)
    cfg = {"name": "ai-portfolio-demos", "main": "src/index.js", "compatibility_date": "2026-09-01",
           "routes": [{"pattern": f"{host}/*", "zone_name": zone}],
           "containers": [{"class_name": _cls(a["slug"]), "image": f"{rel}/projects/{a['slug']}/Dockerfile.space",
                           "instance_type": "standard-1" if a["memory"] in ("3g", "4g") else "basic", "max_instances": 1}
                          for a in items],
           "durable_objects": {"bindings": [{"name": _cls(a["slug"]).upper(), "class_name": _cls(a["slug"])} for a in items]},
           "migrations": [{"tag": "v1", "new_sqlite_classes": [_cls(a["slug"]) for a in items]}]}
    files = [out / "wrangler.jsonc"]
    files[0].write_text("// GENERATED by scripts/demos.py render cloudflare\n" + json.dumps(cfg, indent=2) + "\n")
    classes, routes = [], []
    for a in items:
        env = app_env(a, c, with_prefix=True)
        secrets = ["GOVERNANCE_INGEST_TOKEN"] + (["GOVERNANCE_ADMIN_TOKEN", "DATABASE_URL"] if a["slug"] == CONSOLE else [])
        classes.append(f"""export class {_cls(a['slug'])} extends Container {{
  defaultPort = {PORT};
  sleepAfter = "15m";   // scale to zero; the next visit wakes it (data is baked into the image)
  constructor(ctx, env) {{
    super(ctx, env);
    this.envVars = {{ ...{json.dumps(env)}, {", ".join(f'{s}: env.{s} || ""' for s in secrets)} }};
  }}
}}""")
        routes.append(f'  "{a["slug"]}": "{_cls(a["slug"]).upper()}",')
    js = f"""// GENERATED by scripts/demos.py render cloudflare — routes {c['demos_url']}/<app>/ to that app's container.
import {{ Container, getContainer }} from "@cloudflare/containers";

{chr(10).join(classes)}

const APPS = {{
{chr(10).join(routes)}
}};

const LANDING = {json.dumps(landing_html(c, items))};

export default {{
  async fetch(request, env) {{
    const url = new URL(request.url);
    const slug = url.pathname.split("/")[1];
    if (!slug) return new Response(LANDING, {{ headers: {{ "content-type": "text/html; charset=utf-8" }} }});
    const binding = APPS[slug];
    if (!binding) return new Response("Not found", {{ status: 404 }});
    if (url.pathname === "/" + slug) return Response.redirect(url.origin + "/" + slug + "/", 308);
    return getContainer(env[binding]).fetch(request);   // one instance per app: per-visitor sandboxes live in it
  }},
}};
"""
    p = out / "src" / "index.js"
    p.write_text(js)
    files.append(p)
    p = out / "package.json"
    p.write_text(json.dumps({"name": "ai-portfolio-demos", "private": True, "type": "module",
                             "dependencies": {"@cloudflare/containers": "^0.0.28"},
                             "devDependencies": {"wrangler": "^4"}}, indent=2) + "\n")
    files.append(p)
    return files


# ---------------------------------------------------------------- Google Cloud Run (untested)
def deploy_cloudrun(c: dict, dry_run: bool = False) -> None:
    project, region = os.environ.get("GCP_PROJECT", ""), os.environ.get("GCP_REGION", "us-east1")
    if not project and not dry_run:
        raise SystemExit("Set GCP_PROJECT (and optionally GCP_REGION)")
    repo = f"{region}-docker.pkg.dev/{project}/demos"
    run = (lambda cmd: print("$", " ".join(cmd))) if dry_run else (lambda cmd: subprocess.run(cmd, check=True))
    urls = {}
    if not dry_run:   # Artifact Registry repo for the images (already exists after the first deploy)
        subprocess.run(["gcloud", "artifacts", "repositories", "create", "demos", "--repository-format", "docker",
                        "--location", region, "--project", project, "--quiet"], check=False)
    for a in apps():
        ctx = ROOT / "dist" / "cloudrun" / a["slug"]
        shutil.rmtree(ctx, ignore_errors=True)
        shutil.copytree(ROOT / "projects" / a["slug"], ctx, ignore=shutil.ignore_patterns(
            "warehouse", "output", ".venv", "__pycache__", "node_modules", "dist", "*.egg-info"))
        shutil.copy(ctx / "Dockerfile.space", ctx / "Dockerfile")
        image = f"{repo}/{a['slug']}:latest"
        run(["gcloud", "builds", "submit", str(ctx), "--tag", image, "--project", project, "--quiet"])
        env = app_env(a, c, with_prefix=True)
        for s in ["GOVERNANCE_INGEST_TOKEN"] + (["GOVERNANCE_ADMIN_TOKEN"] if a["slug"] == CONSOLE else []):
            if os.getenv(s):
                env[s] = os.environ[s]
        run(["gcloud", "run", "deploy", a["slug"], "--image", image, "--region", region, "--project", project,
             "--allow-unauthenticated", "--port", str(PORT), "--memory", a["memory"].replace("g", "Gi"), "--cpu", "1",
             "--min-instances", "0", "--max-instances", "1", "--session-affinity", "--timeout", "3600",
             "--set-env-vars", "^|^" + "|".join(f"{k}={v}" for k, v in env.items()), "--quiet"])
        urls[a["slug"]] = "" if dry_run else subprocess.run(
            ["gcloud", "run", "services", "describe", a["slug"], "--region", region, "--project", project,
             "--format", "value(status.url)"], capture_output=True, text=True, check=True).stdout.strip()
    # One public entry point at DEMOS_URL: a Caddy router that sends /<slug>/ to each service (paths preserved).
    rdir = ROOT / "dist" / "cloudrun" / "router"
    rdir.mkdir(parents=True, exist_ok=True)
    routes = "\n".join(f"\thandle /{s}/* {{\n\t\treverse_proxy {u or 'https://SERVICE-URL'} {{\n\t\t\theader_up Host {{upstream_hostport}}\n\t\t}}\n\t}}"
                       for s, u in urls.items())
    (rdir / "Caddyfile").write_text("{\n\tadmin off\n\tauto_https off\n}\n:8080 {\n" + routes +
                                   "\n\thandle {\n\t\troot * /srv\n\t\tfile_server\n\t}\n}\n")
    (rdir / "index.html").write_text(landing_html(c, apps()))
    (rdir / "Dockerfile").write_text("FROM caddy:2-alpine\nCOPY Caddyfile /etc/caddy/Caddyfile\nCOPY index.html /srv/index.html\n")
    run(["gcloud", "builds", "submit", str(rdir), "--tag", f"{repo}/router:latest", "--project", project, "--quiet"])
    run(["gcloud", "run", "deploy", "demos-router", "--image", f"{repo}/router:latest", "--region", region,
         "--project", project, "--allow-unauthenticated", "--port", "8080", "--min-instances", "0", "--quiet"])
    print("Map your domain to the router once: gcloud beta run domain-mappings create --service demos-router "
          f"--domain {c['demos_url'].split('://')[-1] or 'demos.example.com'} --region {region}")


# ---------------------------------------------------------------- CLI
def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("list")
    r = sub.add_parser("render")
    r.add_argument("target", choices=["selfhost", "cloudflare"])
    r.add_argument("--out")
    d = sub.add_parser("deploy")
    d.add_argument("target", nargs="?")
    d.add_argument("--only", help="one app slug (huggingface)")
    d.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()
    c = resolve()
    if a.cmd == "list":
        print(f"target={c['demos_target']}  base={c['demos_url'] or '(DEMOS_URL not set)'}  console={governance_url(c)}")
        for x in apps():
            print(f"  {x['slug']:24s} {x['kind']:9s} {x['memory']:3s}  {links(x['slug'], c)['demo_url'] or '-'}")
    elif a.cmd == "render":
        out = Path(a.out) if a.out else ROOT / "deploy" / a.target / "generated"
        fn = render_selfhost if a.target == "selfhost" else render_cloudflare
        for f in fn(out, c):
            print("wrote", f.relative_to(ROOT) if f.is_relative_to(ROOT) else f)
    elif a.cmd == "deploy":
        target = a.target or c["demos_target"]
        if target == "huggingface":
            for x in apps():
                if not a.only or x["slug"] == a.only:
                    subprocess.run([sys.executable, str(ROOT / "scripts" / "build_space.py"), x["slug"], "--push"], check=True)
        elif target == "cloudflare":
            out = ROOT / "deploy" / "cloudflare" / "generated"
            render_cloudflare(out, c)
            subprocess.run(["npm", "install", "--no-audit", "--no-fund"], cwd=out, check=True)
            subprocess.run(["npx", "wrangler", "deploy"], cwd=out, check=True)
            for name, src in (("GOVERNANCE_INGEST_TOKEN", "GOVERNANCE_INGEST_TOKEN"),
                              ("GOVERNANCE_ADMIN_TOKEN", "GOVERNANCE_ADMIN_TOKEN"), ("DATABASE_URL", "GOVERNANCE_DATABASE_URL")):
                if os.getenv(src):   # Worker secrets, read by the container classes' envVars
                    subprocess.run(["npx", "wrangler", "secret", "put", name], cwd=out, check=True,
                                   input=os.environ[src], text=True)
        elif target == "cloudrun":
            deploy_cloudrun(c, a.dry_run)
        else:
            print("selfhost: nothing to push — the demo host pulls main and rebuilds (deploy/selfhost/update.sh).")


if __name__ == "__main__":
    main()
