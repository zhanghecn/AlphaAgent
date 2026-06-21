#!/bin/bash
# =============================================================================
# AlphaAgent Release Script（交互式发版）
# =============================================================================
# 展示当前 git/CI/镜像全貌，建议下一个 tag，确认后打 tag 触发 CI 自动构建。
#
# 用法：
#   ./deploy/release.sh              # 交互式，回车用建议的默认 tag
#   ./deploy/release.sh v2.2.0       # 直接指定 tag
#   ./deploy/release.sh --dry-run    # 只展示信息，不实际打 tag
# =============================================================================

set -e

RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'
BLUE='\033[0;34m'; CYAN='\033[0;36m'; BOLD='\033[1m'; NC='\033[0m'
print_info()    { echo -e "${BLUE}[INFO]${NC} $1"; }
print_success() { echo -e "${GREEN}[OK]${NC} $1"; }
print_warning() { echo -e "${YELLOW}[WARN]${NC} $1"; }
print_error()   { echo -e "${RED}[ERROR]${NC} $1"; }
print_section() { echo -e "\n${BOLD}${CYAN}═══════ $1 ═══════${NC}"; }

DRY_RUN=false
INPUT_TAG=""
for arg in "$@"; do
  case "$arg" in
    --dry-run) DRY_RUN=true ;;
    -h|--help) sed -n '2,12p' "$0"; exit 0 ;;
    *) INPUT_TAG="$arg" ;;
  esac
done

# ----- 前置：必须在 git 仓库内 -----
if ! git rev-parse --is-inside-work-tree >/dev/null 2>&1; then
  print_error "当前目录不在 git 仓库内"; exit 1
fi

# ----- 收集 git 状态 -----
BRANCH=$(git rev-parse --abbrev-ref HEAD)
HEAD_SHORT=$(git rev-parse --short HEAD)
HEAD_MSG=$(git log -1 --pretty=%s)
LATEST_TAG=$(git tag -l 'v*' --sort=-v:refname 2>/dev/null | head -1)
REMOTE_URL=$(git remote get-url origin 2>/dev/null || echo "")
AHEAD=$(git rev-list --count @{u}..HEAD 2>/dev/null || echo "?")
BEHIND=$(git rev-list --count HEAD..@{u} 2>/dev/null || echo "?")

if [ -n "$LATEST_TAG" ]; then
  TAG_COMMIT=$(git rev-list -n 1 "$LATEST_TAG" 2>/dev/null | cut -c1-7)
  TAG_DATE=$(git log -1 --format=%cs "$LATEST_TAG" 2>/dev/null)
else
  TAG_COMMIT="-"; TAG_DATE="-"
fi

if git diff --quiet && git diff --cached --quiet; then
  WORKDIR_CLEAN=true; WORKDIR_DESC="干净 ✓"
else
  WORKDIR_CLEAN=false
  CHANGED=$(git status --porcelain | wc -l | tr -d ' ')
  WORKDIR_DESC="脏（${CHANGED} 个未提交改动）"
fi

# GHCR owner 从 remote 解析，失败回退 zhanghecn
OWNER="zhanghecn"
if [ -n "$REMOTE_URL" ]; then
  PARSED=$(echo "$REMOTE_URL" | sed -nE 's#.*github\.com[:/]([^/]+)/[^/]+.*#\1#p')
  [ -n "$PARSED" ] && OWNER="$PARSED"
fi

# ----- 建议下一个 tag（最新 tag 的 patch +1）-----
suggest_tag() {
  if [ -z "$LATEST_TAG" ]; then echo "v0.1.0"; return; fi
  local base=${LATEST_TAG#v}
  local major minor patch
  major=$(echo "$base" | cut -d. -f1)
  minor=$(echo "$base" | cut -d. -f2)
  patch=$(echo "$base" | cut -d. -f3)
  patch=$((patch + 1))
  echo "v${major}.${minor}.${patch}"
}
SUGGESTED=$(suggest_tag)

# ===================== 展示当前全貌 =====================
print_section "AlphaAgent 发版概览"
echo -e "  ${BOLD}当前分支${NC}      : $BRANCH"
echo -e "  ${BOLD}最新 commit${NC}   : $HEAD_SHORT — $HEAD_MSG"
echo -e "  ${BOLD}工作区状态${NC}    : $WORKDIR_DESC"
echo -e "  ${BOLD}当前最新 tag${NC}  : ${LATEST_TAG:-(无)}"
[ -n "$LATEST_TAG" ] && echo -e "                     （指向 $TAG_COMMIT，$TAG_DATE）"
echo -e "  ${BOLD}远程 origin${NC}   : ${REMOTE_URL:-(未配置)}"
echo -e "  ${BOLD}与 origin 同步${NC}: 领先 $AHEAD / 落后 $BEHIND 个 commit"

print_section "发版会做什么"
echo -e "  ${BOLD}Workflow${NC} : .github/workflows/docker-release.yml"
echo -e "  ${BOLD}触发条件${NC} : push 形如 v* 的 tag"
echo -e "  ${BOLD}并行构建并推送${NC}（latest + 本次 tag 双标签）："
echo -e "     • ghcr.io/${OWNER}/alphaagent-api"
echo -e "     • ghcr.io/${OWNER}/alphaagent-web"
echo -e "     • ghcr.io/${OWNER}/alphaagent-gateway"

print_section "Tag 建议"
echo -e "  最新 tag : ${LATEST_TAG:-(无)}"
echo -e "  ${GREEN}建议 tag : $SUGGESTED${NC}  （= 最新 tag 的 patch +1）"
echo -e "  ${YELLOW}提示${NC}     : 大版本改动可手动输 v2.2.0(minor) 或 v3.0.0(major)"

# ===================== 前置检查（警告但不阻塞）=====================
print_section "前置检查"
BLOCK=false
if [ "$WORKDIR_CLEAN" = false ]; then
  print_warning "工作区有未提交改动！tag 会打在 $HEAD_SHORT 上，【不含】这些改动。"
  print_warning "  → 若这些改动属于本次发版，请先 git add && git commit && git push。"
  BLOCK=true
fi
if [ "$AHEAD" != "0" ] && [ "$AHEAD" != "?" ]; then
  print_warning "本地领先 origin $AHEAD 个 commit，tag 指向的 commit 可能尚未推到远程。"
  print_warning "  → 建议先 git push origin $BRANCH。"
  BLOCK=true
fi
[ "$BLOCK" = false ] && print_success "工作区干净，本地与远程同步，可直接发版。"

# ===================== 确定 tag =====================
echo
if [ -n "$INPUT_TAG" ]; then
  TAG="$INPUT_TAG"
  print_info "使用传入的 tag: $TAG"
else
  read -rp "输入要发布的 tag（回车=默认 $SUGGESTED）: " TAG
  TAG="${TAG:-$SUGGESTED}"
fi

# 校验格式
if ! echo "$TAG" | grep -qE '^v[0-9]+\.[0-9]+\.[0-9]+([.-].*)?$'; then
  print_error "tag 格式应为 vMAJOR.MINOR.PATCH（如 v2.2.0），收到: $TAG"; exit 1
fi
# 校验不存在
if git rev-parse -q --verify "refs/tags/$TAG" >/dev/null 2>&1; then
  print_error "tag $TAG 已存在！换个版本号。"; exit 1
fi

echo
print_section "即将执行"
echo -e "  ${BOLD}git tag $TAG${NC}"
echo -e "  ${BOLD}git push origin $TAG${NC}"
echo -e "  → 触发 GitHub Actions 构建并推送三镜像到 ghcr.io/${OWNER}/"

if [ "$DRY_RUN" = true ]; then
  print_info "dry-run 模式，以上命令不会执行。"; exit 0
fi

echo
read -rp "确认发版 $TAG ？(y/N) " -r
if [[ ! $REPLY =~ ^[Yy]$ ]]; then
  print_info "已取消，未做任何改动。"; exit 0
fi

# ===================== 执行发版 =====================
git tag "$TAG"
git push origin "$TAG"
print_success "已推送 tag $TAG，CI 已触发！"

echo
print_section "下一步"
echo -e "  1. 查看 CI 进度: GitHub 仓库 → Actions → Docker Release"
echo -e "     （约 5-10 分钟构建三镜像）"
echo -e "  2. CI 完成后，到服务器更新:"
echo -e "     ${CYAN}ssh -p 55918 root@45.152.66.158 'cd /opt/1panel/project/AlphaAgent && docker compose -f docker-compose.ghcr.yml pull && docker compose -f docker-compose.ghcr.yml up -d'${NC}"
echo -e "     （线上 ghcr 镜像 public 免登录；pull_policy:always 自动拉取并滚动重启；postgres/redis named volume 保数据）"
