# AlphaAgent 部署与发版手册

> 覆盖「本地开发 → 服务器部署 → 发版」全流程。
> 核心原则：**本地、服务器、正式版三套环境完全同步**，都用 `docker compose`，入口统一网关。

---

## 一、架构（30 秒看懂）

```
浏览器 → gateway:8080（唯一入口，匿名读取 + 管理员写操作 + 反向代理）
         ├─ /api/auth/*   → 网关自己处理（登录/登出/当前用户）
         ├─ /api/*        → 默认匿名读取；写操作校验管理员 JWT 后转发到 alphaagent-api:8000
         └─ /*            → 转发到 alphaagent-web:80（前端 nginx）
```

| 服务 | 作用 | 端口 |
|---|---|---|
| `alphaagent-gateway` | Go 网关：匿名读取、管理员写操作、反向代理 | **8080（对外唯一）** |
| `alphaagent-api` | FastAPI 后端 | 8000（仅内部） |
| `alphaagent-web` | 前端（nginx serve dist） | 80（仅内部） |
| `postgres` / `redis` | 数据 + 缓存 | 仅内部 |

api/web 不对外，所有访问都经网关。默认读取功能无需登录；管理员写操作才需要登录。

---

## 二、本地开发（和服务器完全一样）

### 首次启动
```bash
cp .env.example .env
# 编辑 .env，至少设置 POSTGRES_PASSWORD；管理员写操作凭证见第四节
docker compose up -d --build
```
打开 http://localhost:8080 直接使用。需要手动同步、回测、升级等写操作时，再访问 `/login`。

### 🤖 你的开发循环（AI 写代码 → 你测试）

每次让 AI 改完代码，**只需重建改动的那一个容器**（不用全量重建）：

| AI 改了什么 | 你执行的命令 |
|---|---|
| 前端（`frontend/`） | `docker compose up -d --build alphaagent-web` |
| 后端（`alphaagent/`） | `docker compose up -d --build alphaagent-api` |
| 网关（`gateway/`） | `docker compose up -d --build alphaagent-gateway` |
| 不确定改了啥 | `docker compose up -d --build`（全量，慢一点） |

然后浏览器刷新 http://localhost:8080 测试。满意了再让 AI `git commit && git push`。

> 浏览器记得**强制刷新**（Ctrl+Shift+R）或用无痕窗口，避免缓存旧前端。

---

## 三、服务器部署

### 首次部署
```bash
# 前提：服务器已装 docker（没有：curl -fsSL https://get.docker.com | sh）

git clone https://github.com/zhanghecn/AlphaAgent.git
cd AlphaAgent
cp .env.example .env
vi .env            # 至少设好 POSTGRES_PASSWORD；管理员写操作凭证见第四节
docker compose up -d --build    # 首次较慢（装 Python 依赖），之后就快
docker compose logs -f alphaagent-gateway   # 看网关日志确认起来
```
浏览器打开 `http://<服务器IP>:8080`，无需登录即可使用读取功能。

> 防火墙开 **8080**（或改 `.env` 的 `GATEWAY_PORT=80` 用标准 80 端口）。

### 后续更新（一条命令）
```bash
cd AlphaAgent
git pull && docker compose up -d --build
```

---

## 四、访问与管理员权限（`.env`）

在项目根目录 `.env` 文件里配（服务器和本地都一样）：

```bash
AUTH_REQUIRED=false                           # 默认：读取接口无需登录
ADMIN_USERNAME=admin                          # 管理员账号（可改）
ADMIN_PASSWORD=你的强密码                       # 可选；与 JWT_SECRET 成对设置
JWT_SECRET=openssl-rand-hex-32-的输出          # 可选；至少 32 字节
POSTGRES_PASSWORD=你的数据库密码                 # 必填
GATEWAY_PORT=8080                             # 网关端口
```

`AUTH_REQUIRED=false` 时：

- `ADMIN_PASSWORD` 和 `JWT_SECRET` 都留空：页面和读取接口可直接使用；网关会拒绝同步、回测、升级等写操作。
- 两项都设置：页面和读取接口仍无需登录；管理员访问 `/login` 获得 JWT 后可执行写操作。
- `AUTH_REQUIRED=true`：恢复旧行为，所有 API 都要求 JWT 登录。

管理员凭证必须成对设置，`JWT_SECRET` 至少 32 字节。可用 `openssl rand -hex 32` 生成签名密钥。

- **改管理员密码**：改 `.env` 的 `ADMIN_PASSWORD` → `docker compose up -d`
- **让管理员 token 立即失效**：改 `.env` 的 `JWT_SECRET` → `docker compose up -d`

---

## 五、发版方式（两种，任选）

### 方式 A：服务器直接 build（推荐 ⭐，简单、不依赖 GitHub）

就是第三节「服务器部署」——服务器 `git pull` 后自己 `docker compose --build`。
- ✅ 不依赖 GitHub Actions
- ✅ 不依赖 ghcr.io（避开国内拉镜像慢的坑）
- ✅ 本地 = 服务器，完全同步

### 方式 B：GitHub CI 自动构建（可选，进阶）

让 GitHub 帮你 build 镜像推到 ghcr.io，服务器只 pull 不 build：

```bash
./deploy/release.sh            # 交互式发版脚本，打 tag 触发 CI
```

CI 完成后，服务器用 `deploy/docker-compose.local.yml`（image 模式）：
```bash
cd deploy
docker compose -f docker-compose.local.yml up -d   # pull_policy:always 自动拉最新
```

> 方式 B 适合服务器在国外或想自动化。国内服务器建议方式 A。

---

## 六、常见操作速查

| 需求 | 命令 |
|---|---|
| 看服务状态 | `docker compose ps` |
| 看网关日志 | `docker compose logs -f alphaagent-gateway` |
| 看后端日志 | `docker compose logs -f alphaagent-api` |
| 改前端后生效 | `docker compose up -d --build alphaagent-web` |
| 改后端后生效 | `docker compose up -d --build alphaagent-api` |
| 改访问模式或管理员凭证 | 改 `.env` → `docker compose up -d` |
| 停止全部 | `docker compose down` |
| 停止并清数据（⚠️慎用） | `docker compose down -v` |
| 进后端容器排错 | `docker compose exec alphaagent-api bash` |

---

## 七、数据与备份

方式 A（服务器 build，根 `docker-compose.yml`）数据在 **docker named volumes**；
方式 B（GitHub CI，`deploy/docker-compose.local.yml`）数据在**本地目录** `./data`、`./vntrader`、`./postgres_data`、`./redis_data`。

关键数据：
- `postgres_data` / postgres volume：研究数据库（股票清单、日线/分钟、板块、财务、回测、持仓、模拟）
- `vntrader`：vn.py 运行目录（设置、vn.py SQLite、日志）
- `data`：业务数据缓存

**迁移服务器**：方式 B 直接打包整个目录拷贝；方式 A 用 `docker volume` 相关命令迁移。备份时务必保留 postgres 和 vntrader 两份数据。

---

## 八、并发与首次部署配置

默认 Compose 使用两个 API worker，读取数据优先来自 PostgreSQL 快照和 Redis 共享缓存：

```bash
ALPHAAGENT_API_WORKERS=2
ALPHAAGENT_API_CPUS=1.0
ALPHAAGENT_SCHEDULER_CPUS=0.5
ALPHAAGENT_POSTGRES_CPUS=1.0
DATABASE_POOL_SIZE=8
DATABASE_MAX_OVERFLOW=8
```

这组默认值会让两个 API worker 最多打开 32 条数据库连接。上线前应按实际查询负载压测；需要继续扩容时，将 API 容器横向扩展，并让所有实例共用同一个 PostgreSQL、Redis 与负载均衡入口。

首次部署最小配置：

```bash
AUTH_REQUIRED=false
POSTGRES_USER=alphaagent
POSTGRES_DB=alphaagent
POSTGRES_PASSWORD=改成你自己的数据库密码
GATEWAY_PORT=8080
```

需要管理员写操作时，再补充 `ADMIN_PASSWORD` 与 `JWT_SECRET`。
