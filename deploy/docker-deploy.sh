#!/bin/bash
# =============================================================================
# AlphaAgent Docker Deployment Preparation Script
# =============================================================================
# Prepares a local-directory Docker deployment:
#   - Copies .env.example to .env
#   - Generates POSTGRES_PASSWORD when unset or still using the template value
#   - Creates data directories
#
# Start after preparation:
#   docker compose -f docker-compose.local.yml up -d
# =============================================================================

set -e

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

print_info() { echo -e "${BLUE}[INFO]${NC} $1"; }
print_success() { echo -e "${GREEN}[SUCCESS]${NC} $1"; }
print_warning() { echo -e "${YELLOW}[WARNING]${NC} $1"; }
print_error() { echo -e "${RED}[ERROR]${NC} $1"; }

command_exists() {
    command -v "$1" >/dev/null 2>&1
}

generate_secret() {
    openssl rand -hex 32
}

main() {
    echo ""
    echo "=========================================="
    echo "  AlphaAgent Docker Deployment Setup"
    echo "=========================================="
    echo ""

    if ! command_exists openssl; then
        print_error "openssl is not installed. Please install openssl first."
        exit 1
    fi

    if [ ! -f "docker-compose.local.yml" ] || [ ! -f ".env.example" ]; then
        print_error "Run this script inside the deploy/ directory."
        exit 1
    fi

    if [ -f ".env" ]; then
        print_warning ".env already exists."
        read -p "Overwrite .env? (y/N): " -r
        echo
        if [[ ! $REPLY =~ ^[Yy]$ ]]; then
            print_info "Keeping existing .env."
        else
            cp .env.example .env
        fi
    else
        cp .env.example .env
    fi

    CURRENT_POSTGRES_PASSWORD=$(grep "^POSTGRES_PASSWORD=" .env 2>/dev/null | cut -d= -f2-)
    if [ -z "$CURRENT_POSTGRES_PASSWORD" ] || [ "$CURRENT_POSTGRES_PASSWORD" = "change-me" ]; then
        POSTGRES_PASSWORD=$(generate_secret)
        if sed --version >/dev/null 2>&1; then
            sed -i "s/^POSTGRES_PASSWORD=.*/POSTGRES_PASSWORD=${POSTGRES_PASSWORD}/" .env
        else
            sed -i '' "s/^POSTGRES_PASSWORD=.*/POSTGRES_PASSWORD=${POSTGRES_PASSWORD}/" .env
        fi
        print_success "Generated POSTGRES_PASSWORD."
    else
        print_info "POSTGRES_PASSWORD already set."
    fi

    # JWT_SECRET：留空或仍是占位值则随机生成（≥32 字节）。
    CURRENT_JWT_SECRET=$(grep "^JWT_SECRET=" .env 2>/dev/null | cut -d= -f2-)
    if [ -z "$CURRENT_JWT_SECRET" ] || [ "$CURRENT_JWT_SECRET" = "change-me-32-bytes-or-longer-random-hex" ]; then
        JWT_SECRET=$(generate_secret)
        if sed --version >/dev/null 2>&1; then
            sed -i "s/^JWT_SECRET=.*/JWT_SECRET=${JWT_SECRET}/" .env
        else
            sed -i '' "s/^JWT_SECRET=.*/JWT_SECRET=${JWT_SECRET}/" .env
        fi
        print_success "Generated JWT_SECRET."
    else
        print_info "JWT_SECRET already set."
    fi

    # ADMIN_PASSWORD：留空或仍是占位值则随机生成并打印（务必保存）。
    CURRENT_ADMIN_PASSWORD=$(grep "^ADMIN_PASSWORD=" .env 2>/dev/null | cut -d= -f2-)
    if [ -z "$CURRENT_ADMIN_PASSWORD" ] || [ "$CURRENT_ADMIN_PASSWORD" = "change-me-strong-password" ]; then
        # 只保留字母数字，避免破坏 .env / sed；24 位足够强。
        ADMIN_PASSWORD=$(openssl rand -base64 24 | tr -d '/+=' | cut -c1-24)
        if sed --version >/dev/null 2>&1; then
            sed -i "s/^ADMIN_PASSWORD=.*/ADMIN_PASSWORD=${ADMIN_PASSWORD}/" .env
        else
            sed -i '' "s/^ADMIN_PASSWORD=.*/ADMIN_PASSWORD=${ADMIN_PASSWORD}/" .env
        fi
        print_success "Generated ADMIN_PASSWORD."
        ADMIN_USERNAME=$(grep "^ADMIN_USERNAME=" .env 2>/dev/null | cut -d= -f2-)
        ADMIN_USERNAME=${ADMIN_USERNAME:-admin}
        print_warning "管理员写操作登录  ->  username: ${ADMIN_USERNAME}  password: ${ADMIN_PASSWORD}"
        print_warning "请立即保存此密码（.env 已 chmod 600）。"
    else
        print_info "ADMIN_PASSWORD already set."
    fi

    mkdir -p data vntrader postgres_data redis_data
    chmod 600 .env

    print_success "Deployment files are ready."
    echo ""
    echo "Next steps:"
    echo "  docker compose -f docker-compose.local.yml up -d"
    echo "  docker compose -f docker-compose.local.yml logs -f alphaagent-gateway"
    echo "  open http://localhost  (or http://<server-ip>)"
    echo "  read-only pages are available without login; use /login only for administrator writes"
    echo ""
}

main "$@"
