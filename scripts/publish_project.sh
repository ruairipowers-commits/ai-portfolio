#!/usr/bin/env bash
# Package projects/<slug> as its own public GitHub repo (and a zip).
#   scripts/publish_project.sh altdata-triage            # zip only -> dist/<slug>.zip
#   scripts/publish_project.sh altdata-triage --push     # also create/push github.com/<owner>/<slug>
# Requires: python3 + pyyaml; for --push, the GitHub CLI (`gh auth login`) and git.
set -euo pipefail
SLUG="${1:?usage: publish_project.sh <slug> [--push]}"; PUSH="${2:-}"
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
SRC="$ROOT/projects/$SLUG"; OUT="$ROOT/dist/$SLUG"
[ -d "$SRC" ] || { echo "no project $SRC"; exit 1; }

python3 "$ROOT/scripts/check_governance.py" "$SLUG"

read -r SITE OWNER < <(python3 "$ROOT/scripts/portfolio_config.py")
if [[ "$OWNER" == REPLACE* ]]; then echo "Can't determine GitHub owner: run 'gh auth login' or set PORTFOLIO_GITHUB_OWNER"; exit 1; fi
TITLE=$(python3 -c "import yaml;print(yaml.safe_load(open('$ROOT/specs/$SLUG.yaml'))['title'])")

rm -rf "$OUT" && mkdir -p "$OUT"
python3 - "$SRC" "$OUT" <<'PY'
import fnmatch, shutil, sys
from pathlib import Path
src, out = Path(sys.argv[1]), Path(sys.argv[2])
pats = [l.strip().rstrip("/") for l in (src / ".gitignore").read_text().splitlines() if l.strip() and not l.startswith("#")]
def ignored(rel: str) -> bool:
    return rel.startswith(".git/") or any(fnmatch.fnmatch(rel, p) or fnmatch.fnmatch(rel.split("/")[-1], p)
                                          or rel == p or rel.startswith(p + "/") for p in pats)
for f in src.rglob("*"):
    rel = f.relative_to(src).as_posix()
    if f.is_file() and not ignored(rel) and not any(ignored(str(Path(*f.relative_to(src).parts[:i]).as_posix())) for i in range(1, len(f.relative_to(src).parts))):
        (out / rel).parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(f, out / rel)
PY
# Standalone repo carries its own copy of the standard + checker.
mkdir -p "$OUT/governance"
cp "$ROOT/governance/controls.md" "$OUT/governance/controls.md"
# Substitute portfolio placeholders.
grep -rl --include='*.md' '{{' "$OUT" | while read -r f; do
  sed -i.bak -e "s#{{SITE_URL}}#$SITE#g" -e "s#{{GITHUB_OWNER}}#$OWNER#g" -e "s#{{BLOG_TITLE}}#$TITLE#g" "$f" && rm -f "$f.bak"
done
(cd "$ROOT/dist" && rm -f "$SLUG.zip" && zip -qr "$SLUG.zip" "$SLUG")
echo "Packaged $OUT and dist/$SLUG.zip"

if [[ "$PUSH" == "--push" ]]; then
  cd "$OUT"
  git init -q -b main && git add -A && git commit -qm "Publish $SLUG from ai-portfolio"
  if gh repo view "$OWNER/$SLUG" >/dev/null 2>&1; then
    git remote add origin "https://github.com/$OWNER/$SLUG.git"
    git push -f origin main
  else
    gh repo create "$OWNER/$SLUG" --public --source . --push --description "$TITLE"
  fi
  python3 - "$ROOT/specs/$SLUG.yaml" "https://github.com/$OWNER/$SLUG" <<'PY'
import re, sys
p, url = sys.argv[1], sys.argv[2]
t = open(p).read()
t = re.sub(r'repo: ""', f'repo: "{url}"', t, count=1)
t = re.sub(r"(?m)^status: \w+", "status: published", t, count=1)
open(p, "w").write(t)
PY
  echo "Published https://github.com/$OWNER/$SLUG"
fi
