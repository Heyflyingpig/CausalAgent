#!/bin/sh
# 在 gateway 容器内启动 nginx 并按策略轮转弃用 JSONL 与 error 日志。
# 背景：nginx:1.27-alpine 不含 logrotate(8) 与 cron，宿主机 logrotate 无法
# 对命名卷内的 /var/log/nginx 生效，因此轮转必须在容器内执行。
set -u

LOG_DIR="${LOG_DIR:-/var/log/nginx}"
PID_FILE="${PID_FILE:-/tmp/nginx.pid}"
POLICY_FILE="${POLICY_FILE:-/etc/nginx/logrotate.conf}"
STATE_FILE="${STATE_FILE:-$LOG_DIR/.last_rotation_epoch}"
STREAMS="deprecation.jsonl error.log"

if [ -f "$POLICY_FILE" ]; then
    # shellcheck disable=SC1090
    . "$POLICY_FILE"
fi
ROTATION_MAX_AGE_HOURS="${ROTATION_MAX_AGE_HOURS:-24}"
ROTATION_MAX_SIZE_MB="${ROTATION_MAX_SIZE_MB:-20}"
RETENTION_ROTATIONS="${RETENTION_ROTATIONS:-45}"
CHECK_INTERVAL_SECONDS="${CHECK_INTERVAL_SECONDS:-3600}"

now_epoch() { date +%s; }

stop_gateway() {
    if [ -s "$PID_FILE" ]; then
        kill -QUIT "$(cat "$PID_FILE")" 2>/dev/null || true
    fi
    exit 0
}
trap stop_gateway TERM INT

signal_reopen() {
    [ -s "$PID_FILE" ] || return 0
    kill -USR1 "$(cat "$PID_FILE")" 2>/dev/null || true
}

stream_size_bytes() {
    [ -f "$1" ] || return 0
    wc -c < "$1" | tr -d '[:space:]'
}

should_rotate() {
    # missingok：文件不存在不轮转；notifempty：空文件不轮转。
    [ -s "$1" ] || return 1
    size_limit=$((ROTATION_MAX_SIZE_MB * 1024 * 1024))
    [ "$(stream_size_bytes "$1")" -ge "$size_limit" ] && return 0
    last=$(cat "$STATE_FILE" 2>/dev/null || echo "$(now_epoch)")
    [ $(( $(now_epoch) - last )) -ge $((ROTATION_MAX_AGE_HOURS * 3600)) ]
}

perform_rotation() {
    rotated=0
    stamp=$(date -u +%Y%m%dT%H%M%SZ)
    for stream in $STREAMS; do
        current="$LOG_DIR/$stream"
        [ -s "$current" ] || continue
        mv "$current" "$current.$stamp" && rotated=1
    done
    if [ "$rotated" -eq 1 ]; then
        # sharedscripts 语义：本轮所有流移动完成后只通知一次 nginx 重开日志。
        signal_reopen
        now=$(now_epoch)
        echo "$now" > "$STATE_FILE"
        for stream in $STREAMS; do
            # USR1 之后旧文件已关闭，可立即压缩（等价 compress；无 delaycompress）。
            for archived in "$LOG_DIR/$stream."*; do
                [ -f "$archived" ] || continue
                case "$archived" in
                    *.gz) continue ;;
                esac
                gzip -f "$archived"
            done
            count=0
            for archived in $(ls -1t "$LOG_DIR/$stream."*.gz 2>/dev/null); do
                count=$((count + 1))
                [ "$count" -le "$RETENTION_ROTATIONS" ] && continue
                rm -f "$archived"
            done
        done
    fi
}

[ -f "$STATE_FILE" ] || echo "$(now_epoch)" > "$STATE_FILE"

nginx

while :; do
    sleep "$CHECK_INTERVAL_SECONDS" &
    wait "$!" || true
    for stream in $STREAMS; do
        if should_rotate "$LOG_DIR/$stream"; then
            perform_rotation
            break
        fi
    done
done
