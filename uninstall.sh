#!/usr/bin/env bash
# Désinstalle claude-usage-budget et retire la statusline de settings.json (config conservée).
set -euo pipefail
cd "$HOME"
export PATH="$HOME/.local/bin:$PATH"
pipx uninstall claude-usage-budget >/dev/null 2>&1 && echo "▶ package désinstallé" || echo "▶ package déjà absent"
CLAUDE_DIR="${CLAUDE_CONFIG_DIR:-$HOME/.claude}"
CLAUDE_DIR="$CLAUDE_DIR" python3 - <<'PY'
import json, os
p = os.path.join(os.environ["CLAUDE_DIR"], "settings.json")
if os.path.exists(p):
    s = json.load(open(p, encoding="utf-8"))
    if "claude-usage-budget" in json.dumps(s.get("statusLine", {})):
        s.pop("statusLine", None)
        json.dump(s, open(p, "w", encoding="utf-8"), indent=2, ensure_ascii=False)
        print("▶ statusLine retirée de settings.json")
PY
echo "Config conservée : $CLAUDE_DIR/usage-budget.json (supprime-la à la main si besoin)"
