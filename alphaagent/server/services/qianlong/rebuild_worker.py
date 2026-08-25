"""手动回测重建的独立执行进程。

uvicorn --workers 多进程下,在 worker 进程内跑全量回放会间歇性杀死 worker:
新容器启动后(并发 spawn 的原装 worker)首次 rebuild 必崩,之后重试必成,
进程无声死亡(faulthandler 无输出、非 OOM),root cause 未定;调度路径在
data_sync_worker 单进程容器执行不受影响。故手动路径改由独立子进程执行:
与 worker 生命周期解耦(worker 崩溃回放照常完成),子进程崩溃由
repository.fail_stale_rebuild_runs 兜底标记,重试即可恢复。
"""

from __future__ import annotations

import logging
import sys

from alphaagent.server.services.qianlong import service as qianlong_service

logger = logging.getLogger(__name__)


def main() -> None:
    if len(sys.argv) != 2:
        raise SystemExit("usage: python -m ...rebuild_worker <run_id>")
    run_id = int(sys.argv[1])
    try:
        qianlong_service._execute_rebuild(run_id)
    except Exception:  # noqa: BLE001  # _execute_rebuild 已写 failed 状态
        logger.warning("qianlong rebuild worker run %s failed", run_id, exc_info=True)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    main()
