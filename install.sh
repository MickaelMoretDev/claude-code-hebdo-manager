#!/usr/bin/env bash
# Installation / réinstallation complète de claude-usage-budget (WSL, Linux, macOS).
# Idempotent : relançable autant de fois que nécessaire.
#
#   bash install.sh            # installe, configure la statusline, teste
#   bash install.sh --no-test  # sans le toast de test
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$HERE"   # cwd sûr même si le shell était dans un dossier supprimé
RUN_TEST=1
[[ "${1:-}" == "--no-test" ]] && RUN_TEST=0

say() { printf '\033[1;34m▶ %s\033[0m\n' "$*"; }

# ------------------------------------------------------------------ Windows (Git Bash / MSYS / Cygwin)
case "$(uname -s 2>/dev/null)" in
  MINGW*|MSYS*|CYGWIN*)
    say "Windows détecté (Git Bash) → délégation à install.ps1"
    ARGS=(); [[ $RUN_TEST -eq 0 ]] && ARGS+=(-NoTest)
    exec powershell.exe -NoProfile -ExecutionPolicy Bypass -File "$(cygpath -w "$HERE/install.ps1")" "${ARGS[@]}"
    ;;
esac

# ------------------------------------------------------------------ pipx
if ! command -v pipx >/dev/null 2>&1; then
  say "Installation de pipx"
  if command -v apt-get >/dev/null 2>&1; then
    sudo apt-get install -y pipx
  elif command -v brew >/dev/null 2>&1; then
    brew install pipx
  else
    python3 -m pip install --user pipx || python3 -m pip install --user --break-system-packages pipx
  fi
fi
export PATH="$HOME/.local/bin:$PATH"
pipx ensurepath >/dev/null 2>&1 || true

# ------------------------------------------------------------------ package
say "Installation du package (mode éditable depuis $HERE)"
pipx install --force -e "$HERE" >/dev/null
BIN="$(command -v claude-usage-budget || echo "$HOME/.local/bin/claude-usage-budget")"
say "Exécutable : $BIN"

# ------------------------------------------------------------------ config
CLAUDE_DIR="${CLAUDE_CONFIG_DIR:-$HOME/.claude}"
mkdir -p "$CLAUDE_DIR"
if [[ ! -f "$CLAUDE_DIR/usage-budget.json" ]]; then
  say "Création de la config par défaut"
  "$BIN" init >/dev/null
else
  say "Config existante conservée : $CLAUDE_DIR/usage-budget.json"
fi

# ------------------------------------------------------------------ settings.json
say "Mise à jour de $CLAUDE_DIR/settings.json (statusLine)"
BIN="$BIN" CLAUDE_DIR="$CLAUDE_DIR" python3 - <<'EOF'
import json, os, shutil
p = os.path.join(os.environ["CLAUDE_DIR"], "settings.json")
s = {}
if os.path.exists(p):
    shutil.copy(p, p + ".bak")
    with open(p, encoding="utf-8") as f:
        try:
            s = json.load(f)
        except ValueError:
            s = {}
s["statusLine"] = {"type": "command", "command": os.environ["BIN"] + " statusline", "padding": 0}
with open(p, "w", encoding="utf-8") as f:
    json.dump(s, f, indent=2, ensure_ascii=False)
print("   statusLine.command =", s["statusLine"]["command"])
EOF

# ------------------------------------------------------------------ tests
say "Rendu de la statusline (payload d'exemple)"
"$BIN" statusline < "$HERE/examples/statusline-payload.json"; echo
if [[ $RUN_TEST -eq 1 ]]; then
  say "Notification de test"
  "$BIN" test-notify || true
fi

cat <<EOF

✔ Terminé. Relance Claude Code pour voir la statusline.

Commandes utiles :
  claude-usage-budget edit                             # ouvrir la config
  claude-usage-budget set ramp 30 45 60 72 84 94 100   # plafonds cumulés j1..j7
  claude-usage-budget simulate 20 40 55 70 80 92 99    # prévisualiser une semaine
  claude-usage-budget show                             # config + état des alertes
EOF
