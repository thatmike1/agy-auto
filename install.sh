#!/usr/bin/env bash
#
# install.sh — put agy-auto on PATH and register the guard hook with agy.
#
#   ./install.sh                 # guard + agy-auto + agy-image
#   ./install.sh --with-claude   # also install the grunt subagent for Claude Code
#
# Nothing here overwrites a file you already edited: an existing hooks.json or
# agy-guard.py is left alone and the difference is reported instead.

set -euo pipefail

SRC="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CONFIG="${HOME}/.gemini/config"
BIN="${HOME}/.local/bin"
AGENTS="${HOME}/.claude/agents"
WITH_CLAUDE=0

for arg in "$@"; do
  case "$arg" in
    --with-claude) WITH_CLAUDE=1 ;;
    -h|--help) sed -n '3,10p' "$0" | sed 's/^# \?//'; exit 0 ;;
    *) echo "install.sh: unknown argument: $arg" >&2; exit 1 ;;
  esac
done

command -v python3 >/dev/null || { echo "install.sh: python3 is required" >&2; exit 1; }
command -v agy >/dev/null || echo "install.sh: warning — agy is not on PATH yet"

mkdir -p "$CONFIG" "$BIN"

# the guard, and its test suite next to it so it stays runnable after install
for f in agy-guard.py test-agy-guard.py agy-guard.local.example.json; do
  if [[ -e "$CONFIG/$f" ]] && ! cmp -s "$SRC/guard/$f" "$CONFIG/$f"; then
    echo "install.sh: $CONFIG/$f differs from this checkout — leaving it alone"
  else
    install -m 0755 "$SRC/guard/$f" "$CONFIG/$f"
  fi
done

# hooks.json is shared with any other agy hook, so never clobber it
if [[ -e "$CONFIG/hooks.json" ]]; then
  if python3 -c "
import json, sys
h = json.load(open('$CONFIG/hooks.json'))
sys.exit(0 if 'agy-guard' in h else 1)
" 2>/dev/null; then
    echo "install.sh: hooks.json already registers agy-guard"
  else
    echo "install.sh: $CONFIG/hooks.json exists and does not register the guard."
    echo "            merge this entry into it by hand:"
    echo
    python3 -c "
import json
print(json.dumps({'agy-guard': json.load(open('$SRC/guard/hooks.json'))['agy-guard']}, indent=2))
"
    echo
  fi
else
  install -m 0644 "$SRC/guard/hooks.json" "$CONFIG/hooks.json"
fi

install -m 0755 "$SRC/bin/agy-auto" "$BIN/agy-auto"
install -m 0755 "$SRC/bin/agy-image" "$BIN/agy-image"

if [[ "$WITH_CLAUDE" == 1 ]]; then
  mkdir -p "$AGENTS"
  install -m 0644 "$SRC/claude/agents/grunt.md" "$AGENTS/grunt.md"
  echo "install.sh: installed the grunt subagent to $AGENTS"
fi

echo
python3 "$CONFIG/agy-guard.py" --self-test

case ":$PATH:" in
  *":$BIN:"*) ;;
  *) echo "install.sh: $BIN is not on your PATH — add it to use agy-auto" ;;
esac

echo
echo "Done. Restart any running agy session; hooks load at startup."
echo "Check it end to end with:  agy-auto -p='Run: echo GUARD_CANARY'"
