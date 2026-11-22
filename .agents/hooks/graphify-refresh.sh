#!/usr/bin/env bash
# =============================================================================
# graphify-refresh.sh — refresh the graphify knowledge graph after git changes the code
#
# Purpose:
#   Keeps `graphify-out/` current automatically without anyone remembering to run `graphify update .`:
#     - 0 LLM tokens: `graphify update` only re-parses AST; hub nodes name communities.
#     - Never blocks git: runs in a background subshell; git's own exit status is unaffected.
#     - Leaves projects without `graphify-out/` alone (silent exit 0).
#     - Recovers from stale `.hook.lock` directories older than 10 minutes.
#     - Retains only the 3 newest dated backup directories inside `graphify-out/`.
#     - Reports failures to stderr or `graphify-out/.hook.log` (never hides problems silently).
#
# Called by: post-commit, post-merge, post-checkout (branch switches only).
# =============================================================================
set -u

root="$(git rev-parse --show-toplevel 2>/dev/null)" || exit 0
out="$root/graphify-out"
[ -d "$out" ] || exit 0

if ! command -v graphify >/dev/null 2>&1; then
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

(
  cd "$root" || exit 0
  started="$(date '+%Y-%m-%d %H:%M:%S')"
  if graphify update . >"$out/.hook.log" 2>&1; then
    echo "[$started] graph refreshed" >>"$out/.hook.log"
  else
    echo "[$started] graphify update FAILED; see above" >>"$out/.hook.log"
  fi
  ls -1d "$out"/20[0-9][0-9]-[0-9][0-9]-[0-9][0-9] 2>/dev/null | sort -r | tail -n +4 | while read -r old; do
    rm -rf "$old" && echo "[$started] removed old backup $(basename "$old")" >>"$out/.hook.log"
  done
  rmdir "$lock" 2>/dev/null || true
) >/dev/null 2>&1 &

exit 0
