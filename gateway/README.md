# AlphaAgent Gateway

AlphaAgent 的统一入口网关，用 Go 实现，职责：

1. **管理员登录**：校验 `ADMIN_USERNAME` / `ADMIN_PASSWORD`，签发 JWT（`POST /api/auth/login`）。
2. **登录态过滤**：除登录相关端点外，所有 `/api/*` 请求必须携带 `Authorization: Bearer <token>`，否则返回 401。
3. **反向代理**：`/api/*`（鉴权通过后）转发到 `alphaagent-api`，`/*` 转发到 `alphaagent-web`（nginx）。
4. **统一入口**：对外只暴露网关端口，api/web 不直接对外，杜绝绕过认证。

## 架构

```
浏览器 → gateway:80
         ├─ POST /api/auth/login   → 校验密码 → 返回 JWT
         ├─ GET  /api/auth/me      → 返回 {authenticated}
         ├─ POST /api/auth/logout  → 返回成功（前端清 token）
         ├─ GET  /healthz          → 网关自身存活
         ├─ GET  /readyz           → 探测 api/web 上游
         ├─ /api/*（其余）         → 鉴权 → 代理到 alphaagent-api:8000
         └─ /*                     → 代理到 alphaagent-web:80
```

## 配置（环境变量）

| 变量 | 必填 | 默认 | 说明 |
| --- | --- | --- | --- |
| `ADMIN_USERNAME` | 否 | `admin` | 管理员用户名 |
| `ADMIN_PASSWORD` | **是** | — | 管理员密码 |
| `JWT_SECRET` | **是** | — | JWT 签名密钥，≥32 字节 |
| `JWT_TOKEN_TTL` | 否 | `24h` | token 有效期（`24h` / `30m` / `3600` 秒） |
| `GATEWAY_PORT` | 否 | `80` | 监听端口 |
| `API_UPSTREAM` | 否 | `http://alphaagent-api:8000` | 后端上游 |
| `WEB_UPSTREAM` | 否 | `http://alphaagent-web:80` | 前端上游 |

## 本地开发

```bash
cd gateway
go mod tidy
go run ./cmd/gateway \
  -ADMIN_PASSWORD=local-only \
  -JWT_SECRET=local-dev-secret-32-bytes-minimum-padding \
  -API_UPSTREAM=http://localhost:8000 \
  -WEB_UPSTREAM=http://localhost:5173

go test ./...
```

> 完整联调请用根目录 `docker compose up -d --build`，会自动起 api/web/gateway 三件套。
