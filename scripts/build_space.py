"""Package a project as a Hugging Face Space (Docker SDK) and, optionally, push it.

    python scripts/build_space.py altdata-triage            # -> dist/spaces/altdata-triage/
    python scripts/build_space.py altdata-triage --push     # also create/update the Space (needs HF_TOKEN)

The Space is the published project repo (scripts/publish_project.sh: placeholders resolved,
portfolio_links.json written) with Dockerfile.space as its Dockerfile and Space metadata
prepended to the README. Demos run the offline mock model only; no model API keys go into a Space.

Governance wiring (set as Space variables/secrets, never written into the files):
  every workflow Space   variable GOVERNANCE_URL = the console Space's URL; secret GOVERNANCE_INGEST_TOKEN
  the console Space      secrets GOVERNANCE_INGEST_TOKEN, GOVERNANCE_ADMIN_TOKEN, optional DATABASE_URL

Env: HF_TOKEN (write access), PORTFOLIO_HF_OWNER (default: GitHub owner),
     GOVERNANCE_INGEST_TOKEN, GOVERNANCE_ADMIN_TOKEN, GOVERNANCE_DATABASE_URL (all optional),
     HF_SPACE_HARDWARE (optional, e.g. cpu-upgrade for always-on; paid),
     plus the PORTFOLIO_* settings read by portfolio_config.py.
"""
from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from portfolio_config import CONSOLE, links, resolve, space_host  # noqa: E402


def front_matter(slug: str, spec: dict, cfg: dict) -> str:
    demo = spec.get("demo", {})
    meta = {
        "title": demo.get("title", slug),
        "emoji": demo.get("emoji", "🤖"),
        "colorFrom": demo.get("color_from", "blue"),
        "colorTo": demo.get("color_to", "indigo"),
        "sdk": "docker",
        "app_port": 7860,
        "pinned": False,
        "license": "mit",
        "short_description": demo.get("short_description", spec["title"])[:60],
    }
    return "---\n" + yaml.safe_dump(meta, sort_keys=False, allow_unicode=True) + "---\n\n"


def build(slug: str) -> Path:
    src = ROOT / "projects" / slug
    if not (src / "Dockerfile.space").exists():
        sys.exit(f"{slug}: no Dockerfile.space, so it has no hosted demo")
    if slug == CONSOLE:   # the console's catalog must include every project as of this build
        subprocess.run([sys.executable, str(ROOT / "scripts" / "build_catalog.py")], check=True)
    subprocess.run([str(ROOT / "scripts" / "publish_project.sh"), slug], check=True)
    pub, out = ROOT / "dist" / slug, ROOT / "dist" / "spaces" / slug
    shutil.rmtree(out, ignore_errors=True)
    shutil.copytree(pub, out)
    shutil.move(out / "Dockerfile.space", out / "Dockerfile")
    cfg = resolve()
    spec = yaml.safe_load((ROOT / "specs" / f"{slug}.yaml").read_text())
    l = links(slug, cfg)
    about = (spec.get("demo") or {}).get("about") or \
        "Runs the offline mock model; each visitor gets a private copy of the synthetic data."
    banner = (f"> **Live demo** of [{slug}]({l['source_url']}) from the [AI workflow portfolio]({l['portfolio_url']}). "
              f"Read the [write-up]({l['blog_url']}). {about}\n\n")
    (out / "README.md").write_text(front_matter(slug, spec, cfg) + banner + (out / "README.md").read_text())
    print(f"Built Space folder {out}")
    return out


def fail(msg: str) -> None:
    """Exit with a GitHub Actions error annotation (readable on the run page without opening the log)."""
    print(f"::error::{msg}")
    sys.exit(1)


def preflight(api, owner: str) -> None:
    """Check the token works, can write, and may create Spaces under `owner` — with a fix for each failure."""
    try:
        me = api.whoami()
    except Exception as e:
        fail(f"Hugging Face rejected HF_TOKEN ({type(e).__name__}: {str(e)[:150]}). Create a new token with the Write role.")
    user = me.get("name", "")
    orgs = [o.get("name") for o in me.get("orgs", [])]
    role = ((me.get("auth") or {}).get("accessToken") or {}).get("role", "")
    print(f"Hugging Face token belongs to '{user}' (role: {role or 'unknown'}); target namespace '{owner}'")
    if role == "read":
        fail(f"HF_TOKEN for '{user}' is read-only. Create a token with the Write role and update the HF_TOKEN secret.")
    if owner not in [user, *orgs]:
        fail(f"Spaces would be created under '{owner}', but the token belongs to '{user}'. Add a repository variable "
             f"HF_OWNER = {user} (Settings > Secrets and variables > Actions > Variables) and re-run.")


def push(slug: str, folder: Path) -> None:
    from huggingface_hub import HfApi

    token = os.getenv("HF_TOKEN")
    if not token:
        sys.exit("HF_TOKEN is not set (a Hugging Face token with write access)")
    cfg = resolve()
    repo_id = f"{cfg['hf_owner']}/{slug}"
    api = HfApi(token=token)
    preflight(api, cfg["hf_owner"])
    api.create_repo(repo_id, repo_type="space", space_sdk="docker", exist_ok=True)
    sha = os.getenv("GITHUB_SHA", "local")[:7]
    api.upload_folder(repo_id=repo_id, repo_type="space", folder_path=str(folder),
                      commit_message=f"Sync {slug} from ai-portfolio@{sha}", delete_patterns=["*"])
    ingest = os.getenv("GOVERNANCE_INGEST_TOKEN")
    if slug == CONSOLE:
        for key, val in (("GOVERNANCE_INGEST_TOKEN", ingest), ("GOVERNANCE_ADMIN_TOKEN", os.getenv("GOVERNANCE_ADMIN_TOKEN")),
                         ("DATABASE_URL", os.getenv("GOVERNANCE_DATABASE_URL"))):
            if val:
                api.add_space_secret(repo_id, key, val)
    else:
        api.add_space_variable(repo_id, "GOVERNANCE_URL", space_host(cfg["hf_owner"], CONSOLE))
        if ingest:
            api.add_space_secret(repo_id, "GOVERNANCE_INGEST_TOKEN", ingest)
    hw = os.getenv("HF_SPACE_HARDWARE")
    if hw:   # e.g. cpu-upgrade: never sleeps, billed hourly by Hugging Face
        api.request_space_hardware(repo_id, hw)
    print(f"Pushed https://huggingface.co/spaces/{repo_id}")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("slug")
    ap.add_argument("--push", action="store_true")
    a = ap.parse_args()
    folder = build(a.slug)
    if a.push:
        try:
            push(a.slug, folder)
        except SystemExit:
            raise
        except Exception as e:   # surface the reason as an annotation on the run page
            fail(f"{a.slug}: push to Hugging Face failed — {type(e).__name__}: {str(e)[:300]}")


if __name__ == "__main__":
    main()
