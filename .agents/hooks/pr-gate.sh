#!/bin/bash
# Gate `gh pr create` on a completed comment-sicko run — Devin + Cursor.
#
# Wired from .devin/hooks.v1.json (PreToolUse exec / PostToolUse run_subagent)
# and .cursor/hooks.json (beforeShellExecution / subagentStop). The payload
# shapes differ, so this script dispatches on which fields are present:
#
#   Devin  PreToolUse   stdin has .hook_event_name + .tool_input.command
#   Devin  PostToolUse  stdin has .hook_event_name + .tool_input.profile
#   Cursor shell       stdin has .command (top level)
#   Cursor subagent    matcher in hooks.json already limits to comment-sicko

set -u

cd "${DEVIN_PROJECT_DIR:-.}" || exit 0

input=$(cat)

GIT_DIR=$(git rev-parse --git-dir 2>/dev/null) || exit 0
STAMP="$GIT_DIR/comment-sicko-stamp"
GATED_RE='gh[[:space:]]+pr[[:space:]]+create'

stamp_head() {
  git rev-parse HEAD > "$STAMP" 2>/dev/null
}

gate_reason() {
  if [ ! -f "$STAMP" ]; then
    echo "comment-sicko has not run on this branch. Sweep the diff first via .agents/skills/no-comments (spawn the comment-sicko subagent), then retry."
  elif ! git merge-base --is-ancestor "$(cat "$STAMP")" HEAD 2>/dev/null; then
    echo "comment-sicko last stamped $(cat "$STAMP"), which is not an ancestor of HEAD. Re-run the no-comments sweep on the current diff, then retry."
  fi
}

event=$(printf '%s' "$input" | jq -r '.hook_event_name // empty' 2>/dev/null)

if [ -n "$event" ]; then
  case "$event" in
    PostToolUse)
      profile=$(printf '%s' "$input" | jq -r '.tool_input.profile // empty')
      success=$(printf '%s' "$input" | jq -r '.tool_response.success // false')
      [ "$profile" = "comment-sicko" ] && [ "$success" = "true" ] && stamp_head
      ;;
    PreToolUse)
      cmd=$(printf '%s' "$input" | jq -r '.tool_input.command // empty')
      printf '%s' "$cmd" | grep -qE "$GATED_RE" || exit 0
      reason=$(gate_reason)
      [ -n "$reason" ] && jq -n --arg r "$reason" '{decision: "block", reason: $r}'
      ;;
  esac
else
  cmd=$(printf '%s' "$input" | jq -r '.command // empty' 2>/dev/null)
  if [ -n "$cmd" ]; then
    printf '%s' "$cmd" | grep -qE "$GATED_RE" || exit 0
    reason=$(gate_reason)
    if [ -n "$reason" ]; then
      jq -n --arg r "$reason" '{permission: "deny", agent_message: $r, user_message: "Blocked: sweep the diff with comment-sicko before creating the PR."}'
    else
      echo '{"permission": "allow"}'
    fi
  else
    stamp_head
  fi
fi

exit 0
