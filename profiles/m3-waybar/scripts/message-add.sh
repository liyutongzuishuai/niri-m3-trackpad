#!/usr/bin/env bash
# waybar-m3 · scripts/message-add.sh
# 往消息池追加一条消息（一行一条 JSON），供 dunst/mako 钩子或你自己的脚本调用。
# 消息池是消息来源的兜底：没有 mako / dunst 时，容器框照样能显示消息。
#
# 用法：message-add.sh <应用名> <标题> [正文]
# 例：  message-add.sh qq 女神 我喜欢你

set -u
SCRIPT_DIR="$(dirname "$(readlink -f "$0")")"
. "$SCRIPT_DIR/lib.sh"

SPOOL="${WAYBAR_M3_SPOOL:-${XDG_RUNTIME_DIR:-/tmp}/waybar-m3/messages.jsonl}"
KEEP="${WAYBAR_M3_SPOOL_KEEP:-50}"

mkdir -p "$(dirname "$SPOOL")"
jq -cn --arg app "${1:-未知}" --arg summary "${2:-}" --arg body "${3:-}" \
    '{app: $app, summary: $summary, body: $body}' >>"$SPOOL"

# 只保留最近 KEEP 条
if [ "$(wc -l <"$SPOOL")" -gt "$KEEP" ]; then
    tail -n "$KEEP" "$SPOOL" >"$SPOOL.tmp" && mv "$SPOOL.tmp" "$SPOOL"
fi
