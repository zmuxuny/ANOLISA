#!/usr/bin/env bash
# Detect whether the tokenless CLI is installed and functional.
#
# Output:
#   JSON on stdout:  {"installed": true, "version": "0.1.0", "path": "/usr/bin/tokenless"}
#                    or {"installed": false}
# Exit code: 0 either way (fail-open — plugin activation is controlled by capabilities)

set -euo pipefail

TOKENLESS_BIN=""

# Search PATH first
if command -v tokenless >/dev/null 2>&1; then
    TOKENLESS_BIN="$(command -v tokenless)"
fi

# Fallback paths
if [[ -z "$TOKENLESS_BIN" ]]; then
    for fp in \
        "$HOME/.local/bin/tokenless" \
        "/usr/local/bin/tokenless" \
        "/usr/bin/tokenless" \
        "$HOME/.local/share/anolisa/tokenless/tokenless" \
        "$HOME/.local/lib/anolisa/tokenless/tokenless"; do
        if [[ -f "$fp" && -x "$fp" ]]; then
            TOKENLESS_BIN="$fp"
            break
        fi
    done
fi

if [[ -z "$TOKENLESS_BIN" ]]; then
    echo '{"installed": false}'
    exit 0
fi

# Verify it actually runs
VERSION="$("$TOKENLESS_BIN" --version 2>/dev/null || true)"
if [[ -z "$VERSION" ]]; then
    echo '{"installed": false}'
    exit 0
fi

# Extract version number
VERSION_CLEAN="$(echo "$VERSION" | grep -oE '[0-9]+\.[0-9]+\.[0-9]+' | head -1 || echo "unknown")"

# Use jq --arg to safely embed variables into JSON — avoids broken output
# when paths contain characters that need JSON escaping.
if command -v jq &>/dev/null; then
  jq -n --arg ver "$VERSION_CLEAN" --arg p "$TOKENLESS_BIN" \
    '{installed: true, version: $ver, path: $p}'
else
  # Escape JSON strings without adding a fallback runtime dependency.
  json_escape() {
    local value="$1" code character replacement
    value="${value//\\/\\\\}"
    value="${value//\"/\\\"}"
    for ((code = 1; code < 32; code++)); do
      printf -v character '\\%03o' "$code"
      printf -v character '%b' "$character"
      printf -v replacement '\\u%04x' "$code"
      value="${value//"$character"/"$replacement"}"
    done
    printf '%s' "$value"
  }
  cat <<EOF
{
  "installed": true,
  "version": "$(json_escape "$VERSION_CLEAN")",
  "path": "$(json_escape "$TOKENLESS_BIN")"
}
EOF
fi
