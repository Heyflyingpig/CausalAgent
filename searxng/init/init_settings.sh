#!/bin/sh
set -eu

# 兜底生成 SearXNG 的 settings.yml：缺失时从 example 复制并注入随机 secret_key。
# 已存在则跳过（幂等），绝不覆盖用户手动配置。
CONFIG_DIR="${SEARXNG_CONFIG_DIR:-/etc/searxng}"
EXAMPLE="${CONFIG_DIR}/settings.yml.example"
TARGET="${CONFIG_DIR}/settings.yml"

if [ -f "$TARGET" ]; then
    echo "settings.yml already exists, skipping generation"
    exit 0
fi

if [ ! -f "$EXAMPLE" ]; then
    echo "ERROR: $EXAMPLE not found, cannot generate settings.yml" >&2
    exit 1
fi

cp "$EXAMPLE" "$TARGET"

# 优先 python3（secrets.token_hex 最规范），其次 openssl，最后 od（busybox 兼容）。
if command -v python3 >/dev/null 2>&1; then
    SECRET=$(python3 -c "import secrets; print(secrets.token_hex(32))")
elif command -v openssl >/dev/null 2>&1; then
    SECRET=$(openssl rand -hex 32)
else
    SECRET=$(head -c 32 /dev/urandom | od -An -tx1 | tr -d ' \n')
fi

if [ -z "${SECRET:-}" ]; then
    echo "ERROR: failed to generate secret_key" >&2
    exit 1
fi

sed -i "s/ultrasecretkey/${SECRET}/" "$TARGET"

if grep -q "ultrasecretkey" "$TARGET"; then
    echo "ERROR: secret_key placeholder replacement failed" >&2
    exit 1
fi

echo "Generated $TARGET with a random secret_key"
