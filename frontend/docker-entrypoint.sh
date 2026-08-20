#!/bin/sh
set -eu

api_base_url=$(printf '%s' "${VITE_API_BASE_URL:-/api}" | sed 's/\\/\\\\/g; s/"/\\"/g')
auth_required=$(printf '%s' "${AUTH_REQUIRED:-${VITE_AUTH_REQUIRED:-false}}" | tr '[:upper:]' '[:lower:]')

case "${auth_required}" in
  1|true|yes|on) auth_required=true ;;
  *) auth_required=false ;;
esac

cat > /usr/share/nginx/html/config.js <<EOF
window.__ALPHAAGENT_CONFIG__ = {
  API_BASE_URL: "${api_base_url}",
  AUTH_REQUIRED: ${auth_required}
};
EOF
