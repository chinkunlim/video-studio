#!/usr/bin/env bash
# =============================================================================
# graphify-refresh.sh — refresh the graphify knowledge graph after git changes the code
#
# Purpose:
#   Keeps `graphify-out/` current automatically without anyone remembering to run `graphify update .`:
#     - 0 LLM tokens: `graphify update` only re-parses AST; hub nodes name communities.
#     - Never blocks git: runs detached via `nohup` so agent/subshell exit cannot kill it.
#     - Leaves projects without `graphify-out/` alone (silent exit 0; closeout initializes it).
#     - Resolves `graphify` from PATH, `$HOME/.local/bin/graphify`, or Homebrew.
#     - Recovers from stale `.hook.lock` directories older than 10 minutes and cleans up via `trap`.
#     - Retains only the 3 newest dated backup directories inside `graphify-out/`.
#     - Reports failures to stderr or `graphify-out/.hook.log` (never hides problems silently).
#
# Refs: ISSUE-006
# Called by: post-commit, post-merge, post-checkout (branch switches only).
# =============================================================================
set -u

[ "${SKIP_GRAPHIFY:-0}" = "1" ] && exit 0
[ "${SKIP_GRAPHIFY_HOOK:-0}" = "1" ] && exit 0

root="$(git rev-parse --show-toplevel 2>/dev/null)" || exit 0
out="$root/graphify-out"
[ -d "$out" ] || exit 0

GRAPHIFY_BIN="$(command -v graphify 2>/dev/null || true)"
if [ -z "$GRAPHIFY_BIN" ] && [ -x "$HOME/.local/bin/graphify" ]; then
  GRAPHIFY_BIN="$HOME/.local/bin/graphify"
elif [ -z "$GRAPHIFY_BIN" ] && [ -x "/opt/homebrew/bin/graphify" ]; then
  GRAPHIFY_BIN="/opt/homebrew/bin/graphify"
elif [ -z "$GRAPHIFY_BIN" ] && [ -x "/usr/local/bin/graphify" ]; then
  GRAPHIFY_BIN="/usr/local/bin/graphify"
fi

if [ -z "$GRAPHIFY_BIN" ]; then
  echo "[graphify-refresh] graphify not installed; knowledge graph not refreshed (uv tool install graphifyy)" >&2
  exit 0
fi

lock="$out/.hook.lock"
if [ -d "$lock" ] && [ -n "$(find "$lock" -maxdepth 0 -mmin +10 2>/dev/null)" ]; then
  rmdir "$lock" 2>/dev/null && echo "[graphify-refresh] removed a stale lock" >&2
fi
if ! mkdir "$lock" 2>/dev/null; then
  echo "[graphify-refresh] another refresh is running; skipped" >&2
  exit 0
fi

nohup bash -c '
  root="$1"
  out="$2"
  lock="$3"
  bin="$4"
  _cleanup() { rmdir "$lock" 2>/dev/null || true; }
  trap _cleanup EXIT
  cd "$root" || exit 0
  started="$(date "+%Y-%m-%d %H:%M:%S")"
  if "$bin" update . >"$out/.hook.log" 2>&1; then
    echo "[$started] graph refreshed" >>"$out/.hook.log"
  else
    echo "[$started] graphify update FAILED; see above" >>"$out/.hook.log"
  fi
  ls -1d "$out"/20[0-9][0-9]-[0-9][0-9]-[0-9][0-9] 2>/dev/null | sort -r | tail -n +4 | while read -r old; do
    rm -rf "$old" && echo "[$started] removed old backup $(basename "$old")" >>"$out/.hook.log"
  done
' _ "$root" "$out" "$lock" "$GRAPHIFY_BIN" </dev/null >/dev/null 2>&1 &
disown 2>/dev/null || true

exit 0
