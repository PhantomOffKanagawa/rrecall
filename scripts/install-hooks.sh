#!/usr/bin/env bash
# Install rrecall hooks into Claude Code settings.
# Usage: ./install-hooks.sh [--user | --project]
#   --user     Install to ~/.claude/settings.json (default)
#   --project  Install to .claude/settings.json in cwd

set -euo pipefail

SCOPE="user"
if [[ "${1:-}" == "--project" ]]; then
    SCOPE="project"
fi

if [[ "$SCOPE" == "user" ]]; then
    SETTINGS_DIR="$HOME/.claude"
    SETTINGS_FILE="$SETTINGS_DIR/settings.json"
else
    SETTINGS_DIR=".claude"
    SETTINGS_FILE="$SETTINGS_DIR/settings.json"
fi

mkdir -p "$SETTINGS_DIR"

# Back up existing settings
if [[ -f "$SETTINGS_FILE" ]]; then
    cp "$SETTINGS_FILE" "${SETTINGS_FILE}.bak.$(date +%s)"
    EXISTING=$(cat "$SETTINGS_FILE")
else
    EXISTING="{}"
fi

# Use Python to safely merge hooks into settings JSON
python3 -c "
import json, sys

settings = json.loads('''$EXISTING''')

hooks = settings.setdefault('hooks', {})

pre_compact_hook = {
    'type': 'command',
    'command': 'python -m rrecall.hooks.pre_compact'
}
session_end_hook = {
    'type': 'command',
    'command': 'python -m rrecall.hooks.session_end'
}

# Check for existing rrecall hooks to avoid duplicates
def has_rrecall_hook(hook_list, module_name):
    for entry in hook_list:
        for h in entry.get('hooks', []):
            if module_name in h.get('command', ''):
                return True
    return False

if not has_rrecall_hook(hooks.get('PreCompact', []), 'rrecall.hooks.pre_compact'):
    hooks.setdefault('PreCompact', []).append({
        'hooks': [pre_compact_hook]
    })

if not has_rrecall_hook(hooks.get('SessionEnd', []), 'rrecall.hooks.session_end'):
    hooks.setdefault('SessionEnd', []).append({
        'hooks': [session_end_hook]
    })

print(json.dumps(settings, indent=2))
" > "${SETTINGS_FILE}.tmp"

mv "${SETTINGS_FILE}.tmp" "$SETTINGS_FILE"

echo "rrecall hooks installed to $SETTINGS_FILE"
echo "  PreCompact  -> python -m rrecall.hooks.pre_compact"
echo "  SessionEnd  -> python -m rrecall.hooks.session_end"
