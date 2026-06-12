# AlphaAgent 后端 MVP 工程执行计划

状态：可执行计划，待用户审查后进入实现。  
范围：只搭建 AlphaAgent 上层后端服务骨架，不修改 `vnpy/` 核心包和官方 examples。  
目标：让 AlphaAgent 后端以 Docker Compose 方式运行，提供 `/api/health` 和 `/api/ready`，并通过现有 PostgreSQL/Redis 完成基础就绪检查，为后续全 A 股票、指数、推荐、模拟和回测 API 打地基。

## 1. 当前结论

### 1.1 用户想要的系统

用户希望拥有的是一个服务端化 A 股量化交易和智能投研系统：

- 能看全 A 股票、指数、股票详情、板块、产业链。
- 能做智能选股、解释推荐理由、模拟建仓、风控和回测。
- 后续能接 vn.py Gateway/Datafeed/Database/MainEngine 能力。
- 不再用临时脚本堆功能。
- 不把 AlphaAgent 业务代码混入 `vnpy/` 官方核心包。

### 1.2 本阶段只做什么

本阶段只做后端 MVP 骨架：

- 新增 `alphaagent/` 上层业务包。
- 新增 FastAPI 服务入口。
- 新增配置管理。
- 新增数据库和 Redis 连接检查。
- 新增统一响应格式。
- 新增 Dockerfile、Compose、`.env.example`。
- 新增 Alembic 基础目录和首个最小 migration。
- 新增测试，确保应用可创建、配置可解析、健康检查格式稳定。

本阶段不做：

- 不接真实 A 股数据源。
- 不实现选股算法。
- 不实现前端。
- 不实现实盘下单。
- 不修改 `vnpy/`。
- 不提交、不 push，除非用户明确要求。

## 2. 固定技术决策

### 2.1 后端运行方式

AlphaAgent 后端 MVP 默认用 Docker Compose 运行，不走宿主机 `uv` 直跑作为主路径。

后续实现命令：

```bash
docker compose up alphaagent-api
```

### 2.2 PostgreSQL

使用现有 `1Panel-postgresql-657K`。

- 宿主机入口：`localhost:5432`
- 后端容器入口：`host.docker.internal:5432`
- 数据库名：`alphaagent`
- 用户：`root`
- 密码：只放本地 `.env`，不写入仓库

首次启动前需要在现有 PostgreSQL 中创建数据库：

```sql
CREATE DATABASE alphaagent;
```

如果数据库已存在，不重复创建。

### 2.3 Redis

使用现有 `1Panel-redis-aeey`。

- 当前按 host 网络处理。
- 宿主机入口：`localhost:6379`
- 后端容器入口：`host.docker.internal:6379`
- 当前按无密码处理；如果后续发现有密码，再调整 `REDIS_URL`。

### 2.4 Docker 网络

后端容器需要访问宿主机已有 PostgreSQL/Redis，Compose 服务必须包含：

```yaml
extra_hosts:
  - "host.docker.internal:host-gateway"
```

### 2.5 前端约定

前端由 Claude Code 后续实现。

- Vite dev server 默认：`http://localhost:5173`
- 后端 API 默认：`http://localhost:8000/api`
- 后端 CORS 开放：`http://localhost:5173`

## 3. 目标目录结构

本阶段新增这些文件和目录：

```text
alphaagent/
  __init__.py
  server/
    __init__.py
    main.py
    api/
      __init__.py
      router.py
      health.py
    core/
      __init__.py
      config.py
      responses.py
    db/
      __init__.py
      session.py
      health.py
    cache/
      __init__.py
      redis.py
      health.py
  shared/
    __init__.py
  vnpy_bridge/
    __init__.py

alembic/
  env.py
  script.py.mako
  versions/
    0001_create_system_tables.py

tests/
  alphaagent/
    test_config.py
    test_health_api.py
    test_ready_api.py

.env.example
Dockerfile.alphaagent-api
docker-compose.yml
alembic.ini
```

暂不新增前端目录。

## 4. 环境变量

新增 `.env.example`：

```env
ALPHAAGENT_ENV=local
ALPHAAGENT_API_HOST=0.0.0.0
ALPHAAGENT_API_PORT=8000

POSTGRES_PASSWORD=change-me
DATABASE_URL=postgresql+psycopg://root:${POSTGRES_PASSWORD}@host.docker.internal:5432/alphaagent
REDIS_URL=redis://host.docker.internal:6379/0

CORS_ORIGINS=http://localhost:5173
```

规则：

- `.env.example` 只放示例值。
- `.env` 不提交。
- 不把真实数据库密码写进任何 md、py、toml、yaml。

## 5. 后端依赖

需要把后端服务依赖加入项目依赖或可选 extra。建议先加入 `pyproject.toml` 的主依赖，因为后端是 AlphaAgent 目标形态的一部分：

- `fastapi`
- `uvicorn`
- `pydantic-settings`
- `sqlalchemy`
- `alembic`
- `psycopg`
- `redis`

如果担心影响 vn.py 发行包兼容，也可以新增 dependency group：

```toml
[dependency-groups]
server = [
    "fastapi>=0.115",
    "uvicorn[standard]>=0.30",
    "pydantic-settings>=2.4",
    "sqlalchemy>=2.0",
    "alembic>=1.13",
    "psycopg[binary]>=3.2",
    "redis>=5.0",
]
```

执行时 Dockerfile 使用：

```bash
uv sync --group server
```

本计划推荐使用 `server` dependency group，减少对原 vn.py 主依赖的扰动。

## 6. API 契约

### 6.1 统一响应格式

成功：

```json
{
  "success": true,
  "data": {},
  "error": null,
  "request_id": "req_local"
}
```

失败：

```json
{
  "success": false,
  "data": null,
  "error": {
    "code": "SERVICE_NOT_READY",
    "message": "service dependency is not ready",
    "detail": {}
  },
  "request_id": "req_local"
}
```

### 6.2 `GET /api/health`

用途：只检查 API 进程活着，不访问 PostgreSQL/Redis。

返回：

```json
{
  "success": true,
  "data": {
    "status": "ok",
    "service": "alphaagent-api"
  },
  "error": null,
  "request_id": "req_local"
}
```

### 6.3 `GET /api/ready`

用途：检查 API 依赖是否可用。

必须检查：

- PostgreSQL：执行 `SELECT 1`
- Redis：执行 `PING`

全部成功时：

```json
{
  "success": true,
  "data": {
    "status": "ready",
    "postgres": "ok",
    "redis": "ok"
  },
  "error": null,
  "request_id": "req_local"
}
```

任一失败时：

- HTTP 状态码：`503`
- `success`: `false`
- `error.code`: `SERVICE_NOT_READY`
- `detail` 中标明 PostgreSQL/Redis 哪个失败，但不返回密码和完整连接串。

## 7. 任务拆分

### Task 1：新增 AlphaAgent 包骨架

文件：

- 创建 `alphaagent/__init__.py`
- 创建 `alphaagent/server/__init__.py`
- 创建 `alphaagent/server/main.py`
- 创建 `alphaagent/server/api/__init__.py`
- 创建 `alphaagent/server/api/router.py`
- 创建 `alphaagent/shared/__init__.py`
- 创建 `alphaagent/vnpy_bridge/__init__.py`

步骤：

1. 新建目录和空包文件。
2. 在 `main.py` 暴露 `create_app()`。
3. `create_app()` 返回 FastAPI 实例，标题为 `AlphaAgent API`。
4. 在 `router.py` 暴露 `api_router`。
5. `main.py` 挂载 `api_router` 到 `/api`。
6. 本任务不实现业务接口，只保证 app 能创建。

验证：

```bash
uv run python -c "from alphaagent.server.main import create_app; app = create_app(); print(app.title)"
```

期望输出：

```text
AlphaAgent API
```

### Task 2：新增配置模块和 `.env.example`

文件：

- 创建 `alphaagent/server/core/config.py`
- 创建 `.env.example`
- 修改 `pyproject.toml`

步骤：

1. 在 `pyproject.toml` 新增 `server` extra。
2. 在 `config.py` 使用 `pydantic-settings` 定义 `Settings`。
3. 支持字段：
   - `alphaagent_env`
   - `alphaagent_api_host`
   - `alphaagent_api_port`
   - `database_url`
   - `redis_url`
   - `cors_origins`
4. `cors_origins` 从逗号分隔字符串解析成 list。
5. 提供 `get_settings()`，用 `functools.lru_cache` 缓存。
6. `.env.example` 使用第 4 节示例。

测试：

- 创建 `tests/alphaagent/test_config.py`
- 覆盖默认值和 CORS 解析。

验证：

```bash
uv run pytest tests/alphaagent/test_config.py -q
```

期望：通过。

### Task 3：统一响应结构

文件：

- 创建 `alphaagent/server/core/responses.py`
- 创建或扩展 `tests/alphaagent/test_health_api.py`

步骤：

1. 定义 `success_response(data, request_id="req_local")`。
2. 定义 `error_response(code, message, detail=None, request_id="req_local")`。
3. 统一返回 dict，不在工具函数里直接返回 FastAPI Response。
4. 先不做复杂 request id middleware。

测试：

```bash
uv run pytest tests/alphaagent/test_health_api.py -q
```

期望：响应结构包含 `success`、`data`、`error`、`request_id`。

### Task 4：实现 `/api/health`

文件：

- 创建 `alphaagent/server/api/health.py`
- 修改 `alphaagent/server/api/router.py`
- 修改 `alphaagent/server/main.py`
- 创建 `tests/alphaagent/test_health_api.py`

步骤：

1. 在 `health.py` 定义 APIRouter。
2. 实现 `GET /health`。
3. 返回统一成功响应。
4. 在 `router.py` include health router。
5. 在 `main.py` 配置 CORS，中间件读取 `Settings.cors_origins`。

测试：

```bash
uv run pytest tests/alphaagent/test_health_api.py -q
```

期望：

- `GET /api/health` 返回 200。
- `success == true`。
- `data.status == "ok"`。
- 不尝试连接 PostgreSQL/Redis。

### Task 5：数据库连接和 ready 检查

文件：

- 创建 `alphaagent/server/db/__init__.py`
- 创建 `alphaagent/server/db/session.py`
- 创建 `alphaagent/server/db/health.py`
- 修改 `alphaagent/server/api/health.py`
- 创建 `tests/alphaagent/test_ready_api.py`

步骤：

1. `session.py` 提供 `create_engine_from_settings(settings)`。
2. 使用 SQLAlchemy 2.x engine。
3. `health.py` 提供 `check_postgres(engine)`。
4. `check_postgres` 执行 `SELECT 1`。
5. `/api/ready` 调用 PostgreSQL 检查。
6. 测试里不要连接真实数据库，使用 monkeypatch 替换检查函数。

测试：

```bash
uv run pytest tests/alphaagent/test_ready_api.py -q
```

期望：

- PostgreSQL mocked 成功时，ready 不因数据库失败。
- PostgreSQL mocked 失败时，返回 503，且不泄漏连接串。

### Task 6：Redis 连接和 ready 检查

文件：

- 创建 `alphaagent/server/cache/__init__.py`
- 创建 `alphaagent/server/cache/redis.py`
- 创建 `alphaagent/server/cache/health.py`
- 修改 `alphaagent/server/api/health.py`
- 扩展 `tests/alphaagent/test_ready_api.py`

步骤：

1. `redis.py` 提供 `create_redis_from_settings(settings)`。
2. `health.py` 提供 `check_redis(client)`。
3. `check_redis` 执行 `PING`。
4. `/api/ready` 同时检查 PostgreSQL 和 Redis。
5. 任一失败返回 503。
6. `detail` 只返回 `postgres: ok/error`、`redis: ok/error` 和简短错误类型。

测试：

```bash
uv run pytest tests/alphaagent/test_ready_api.py -q
```

期望：

- 两者 mocked 成功返回 200。
- 任一 mocked 失败返回 503。
- 响应体不包含密码、`DATABASE_URL`、`REDIS_URL`。

### Task 7：Alembic 基础迁移

文件：

- 创建 `alembic.ini`
- 创建 `alembic/env.py`
- 创建 `alembic/script.py.mako`
- 创建 `alembic/versions/0001_create_system_tables.py`

步骤：

1. Alembic 从 `DATABASE_URL` 读取连接。
2. 首个 migration 创建最小系统表 `system_migrations_check`。
3. 字段：
   - `id`
   - `created_at`
4. 只验证 migration 链路，不在本阶段设计全部业务表。

验证：

```bash
docker compose run --rm alphaagent-api alembic upgrade head
```

期望：

- 在 `alphaagent` 数据库创建 `system_migrations_check`。
- Alembic version 表存在。

### Task 8：Dockerfile 和 Compose

文件：

- 创建 `Dockerfile.alphaagent-api`
- 创建 `docker-compose.yml`
- 创建或更新 `.dockerignore`，如果仓库没有则新增

步骤：

1. Dockerfile 使用 Python 3.11 或 3.12 基础镜像。
2. 安装 `uv`。
3. 复制 `pyproject.toml`、`uv.lock`。
4. 执行 `uv sync --group server`。
5. 复制项目源码。
6. 默认命令运行：

```bash
uv run uvicorn alphaagent.server.main:create_app --factory --host 0.0.0.0 --port 8000
```

Compose 服务：

```yaml
services:
  alphaagent-api:
    build:
      context: .
      dockerfile: Dockerfile.alphaagent-api
    env_file:
      - .env
    ports:
      - "8000:8000"
    extra_hosts:
      - "host.docker.internal:host-gateway"
```

明确不加入：

- PostgreSQL service
- Redis service

验证：

```bash
docker compose config
docker compose up alphaagent-api
curl http://localhost:8000/api/health
curl http://localhost:8000/api/ready
```

期望：

- Compose 配置合法。
- `/api/health` 返回 200。
- `/api/ready` 在 PostgreSQL/Redis 可达时返回 200；不可达时返回 503，并指出依赖不可用。

### Task 9：本地测试和最终检查

文件：

- 不新增文件，运行检查。

命令：

```bash
uv run pytest tests/alphaagent -q
docker compose config
rg -n "POSTGRES_PASSWORD=.*[^e-]|postgresql\\+psycopg://root:[^$]|redis://[^/]*:[^@]*@" .
git status --short --branch
```

期望：

- 单元测试通过。
- Compose 配置通过。
- 没有真实密码写入仓库。
- 没有修改 `vnpy/` 和官方 examples。
- 没有 git commit/push。

## 8. 实现顺序

推荐严格按以下顺序执行：

1. `server` extra 依赖和包骨架。
2. 配置模块与 `.env.example`。
3. 统一响应结构。
4. `/api/health`。
5. PostgreSQL ready check。
6. Redis ready check。
7. Alembic migration。
8. Dockerfile 和 Compose。
9. 全量验证。

不要先写股票、推荐、回测 API。原因是数据库、配置、容器和健康检查是所有后续模块的公共地基。

## 9. 验收标准

本阶段完成时必须满足：

- `alphaagent/` 上层包存在。
- `vnpy/` 无改动。
- `.env.example` 存在，且不含真实密码。
- `docker-compose.yml` 只包含 `alphaagent-api`，不新建 PostgreSQL/Redis。
- `docker compose config` 通过。
- `docker compose up alphaagent-api` 能启动服务。
- `GET http://localhost:8000/api/health` 返回 200。
- `GET http://localhost:8000/api/ready` 能检查 PostgreSQL 和 Redis。
- Alembic 能对 `alphaagent` 数据库执行 `upgrade head`。
- `uv run pytest tests/alphaagent -q` 通过。
- 没有执行 git commit/push。

## 10. 后续阶段

后端 MVP 骨架通过后，再进入下一份计划：

1. 股票和指数基础表。
2. `/api/stocks`、`/api/stocks/{vt_symbol}`、`/api/indices`。
3. 临时 seed 数据或可替换数据适配器。
4. vn.py Datafeed/Gateway/Database 适配层。
5. 前端工作台页面。
6. 推荐、模拟、回测。

后续阶段仍要遵守：先基于项目结构和 vn.py 能力边界设计，再实现，不写散落脚本。
