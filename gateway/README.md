# AlphaAgent Gateway

AlphaAgent 的统一入口网关，用 Go 实现，职责：

1. **匿名读取**：默认允许 `GET`、`HEAD` 和 `OPTIONS` 请求直达后端，无需登录。
2. **管理员写操作**：配置 `ADMIN_PASSWORD` 与 `JWT_SECRET` 后，`POST /api/auth/login` 签发 JWT；改变服务状态的请求必须携带该 JWT。
3. **全站认证开关**：设置 `AUTH_REQUIRED=true` 后，除认证端点外的全部 `/api/*` 请求都要求 JWT。
4. **反向代理**：`/api/*` 转发到 `alphaagent-api`，`/*` 转发到 `alphaagent-web`（nginx）。
5. **统一入口**：对外只暴露网关端口，api/web 不直接对外。

## 架构

```
浏览器 → gateway:80
         ├─ POST /api/auth/login   → 校验密码 → 返回 JWT
         ├─ GET  /api/auth/me      → 返回 {authenticated}
         ├─ POST /api/auth/logout  → 返回成功（前端清 token）
         ├─ GET  /healthz          → 网关自身存活
         ├─ GET  /readyz           → 探测 api/web 上游
         ├─ /api/*（其余）         → 默认匿名读取；写操作校验 JWT 后代理到 alphaagent-api:8000
         └─ /*                     → 代理到 alphaagent-web:80
```

## 配置（环境变量）

| 变量 | 必填 | 默认 | 说明 |
| --- | --- | --- | --- |
| `AUTH_REQUIRED` | 否 | `false` | `true` 时恢复全站 JWT 登录 |
| `ADMIN_USERNAME` | 否 | `admin` | 管理员用户名 |
| `ADMIN_PASSWORD` | 条件必填 | — | 与 `JWT_SECRET` 成对设置后启用管理员写操作 |
| `JWT_SECRET` | 条件必填 | — | 与 `ADMIN_PASSWORD` 成对设置，至少 32 字节 |
| `JWT_TOKEN_TTL` | 否 | `24h` | token 有效期（`24h` / `30m` / `3600` 秒） |
| `GATEWAY_PORT` | 否 | `80` | 监听端口 |
| `API_UPSTREAM` | 否 | `http://alphaagent-api:8000` | 后端上游 |
| `WEB_UPSTREAM` | 否 | `http://alphaagent-web:80` | 前端上游 |

## 本地开发

```bash
cd gateway
go mod tidy
AUTH_REQUIRED=false \
API_UPSTREAM=http://localhost:8000 \
WEB_UPSTREAM=http://localhost:5173 \
go run ./cmd/gateway

go test ./...
```

管理员写操作的本地调试可在上面的环境变量后追加 `ADMIN_PASSWORD` 和长度不少于 32 字节的 `JWT_SECRET`。两项都不设置时，读取请求可用，写请求返回 `403 OPERATOR_AUTH_DISABLED`。

> 完整联调请用根目录 `docker compose up -d --build`，会自动起 api/web/gateway 三件套。
