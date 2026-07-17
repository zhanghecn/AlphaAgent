# AlphaAgent Service And Frontend Execution Contract

## Runtime Shape

- 本地开发：`docker compose up --build`。
- API：FastAPI，容器服务 `alphaagent-api`。
- Web：React/Vite 构建后由 Nginx 提供，网关入口 `http://localhost:8080`。
- 数据：PostgreSQL 和 Redis 由根 `docker-compose.yml` 管理。
- 发布：`v*` 标签通过 `.github/workflows/docker-release.yml` 发布 API/Web 镜像。

## Backend Contract

保留的主要路由：

- `/api/market/*`
- `/api/stocks/*`
- `/api/research/*`
- `/api/mainline-replay/*`
- `/api/market-timing/*`
- `/api/limit-up/*`
- `/api/data-sync/*`
- `/api/vnpy/*`

已删除的路由：

- `/api/quant/*`
- `/api/backtests/*`
- `/api/portfolios/*`
- `/api/simulation/*`

## Frontend Contract

- 导航只显示当前可用产品。
- `/short-term` 是短线研究入口；`/limit-up` 重定向到它。
- 现阶段不显示未验证的低吸 Tab、占位绩效或策略按钮。
- 个股页只读行情、概念/龙头、K 线、指标、主营和财务。
- 数据管理不显示尾盘量化、回测 ID 或用户缺口文件；历史分钟缺口由数据库覆盖审计自动发现并交给服务端供应商补偿。

## Next Delivery

清理完成后，低吸研究按以下顺序进入下一份实施计划：

1. 审计真实历史覆盖、概念指数和点时成分/龙头可用性。
2. 建立沪深主板合格股票池和概念主升标签。
3. 生成概念 Top3 龙头的候选事件数据集。
4. 对金/银手指和低吸形态做无未来函数事件研究。
5. 比较 D+1 与 3-5 日退出、成本和组合复利。
6. 只有通过 10% 回撤门和样本外验证后，才添加低吸 Tab/API。

## Verification

```bash
uv run python -m compileall alphaagent/server alphaagent/market alphaagent/data_sources
uv run --group server pytest tests/alphaagent -q
pnpm --dir frontend test -- --run
pnpm --dir frontend run build
docker compose up -d --build alphaagent-api alphaagent-web
```
