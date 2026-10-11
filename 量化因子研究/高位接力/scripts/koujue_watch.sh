#!/bin/bash
# 口诀监控自动化(月度): 导最新数据 → 跑监控报告 → 落盘固定位置。
# 用法: 手动 bash koujue_watch.sh / 已挂 crontab(每月2日 08:17)
# 报告: 量化因子研究/高位接力/口诀监控报告_YYYYMM.txt (最新一份固定名: 口诀监控报告.md)
set -uo pipefail
cd "$(dirname "$0")/../../.."   # 仓库根

DETAIL=/tmp/koujue_detail_$$.csv
OUT_DIR="量化因子研究/高位接力"
STAMP=$(date +%Y%m)
echo "[1/2] 导数据(容器内 dump, 约2分钟)..."
docker exec -i vnpy-alphaagent-api-1 python < "量化因子研究/高位接力/scripts/relay_4to5_dump.py" > "$DETAIL" 2>/tmp/koujue_dump_err.log
if [ ! -s "$DETAIL" ]; then
  echo "导数据失败, 详见 /tmp/koujue_dump_err.log"; exit 1
fi
echo "[2/2] 跑监控报告..."
KOUJUE_CSV="$DETAIL" python3 "量化因子研究/高位接力/scripts/koujue_monitor.py" \
  > "${OUT_DIR}/口诀监控报告_${STAMP}.txt" 2>&1
cp "${OUT_DIR}/口诀监控报告_${STAMP}.txt" "${OUT_DIR}/口诀监控报告.md"
rm -f "$DETAIL"
echo "完成: ${OUT_DIR}/口诀监控报告_${STAMP}.txt (最新固定名: 口诀监控报告.md)"
