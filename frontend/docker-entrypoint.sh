#!/bin/sh
set -eu

api_base_url=$(printf '%s' "${VITE_API_BASE_URL:-/api}" | sed 's/\\/\\\\/g; s/"/\\"/g')

cat > /usr/share/nginx/html/config.js <<EOF
window.__ALPHAAGENT_CONFIG__ = {
  API_BASE_URL: "${api_base_url}"
};
EOF
