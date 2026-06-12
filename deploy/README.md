# AlphaAgent Deployment Files

This directory follows the deployment style used by `~/project/ai/sub2api`: the user-facing deployment entry is Docker Compose, while image build and release details stay in Dockerfile/CI.

## Files

| File | Description |
|------|-------------|
| `docker-compose.local.yml` | Production-style Compose with local data directories |
| `.env.example` | Environment variable template |
| `docker-deploy.sh` | Prepares `.env` and local data directories |

## Release Images

Tag releases publish two GHCR images through `.github/workflows/docker-release.yml`:

- `ghcr.io/zhanghecn/alphaagent-api`
- `ghcr.io/zhanghecn/alphaagent-web`

`docker-compose.local.yml` pulls those images by default. The web image serves a static build with Nginx and writes `/config.js` from `VITE_API_BASE_URL` at container startup, so changing the API URL does not require rebuilding the frontend image.

## Local Directory Deployment

```bash
cd deploy
./docker-deploy.sh
docker compose -f docker-compose.local.yml up -d
docker compose -f docker-compose.local.yml logs -f alphaagent-api
```

Open:

```text
http://localhost:5173
```

All persistent data stays under this directory:

- `data/`
- `vntrader/`
- `postgres_data/`
- `redis_data/`

This makes server migration straightforward: stop Compose, copy the whole deployment directory, then start Compose on the new server.

`postgres_data/` is the AlphaAgent research database: stock lists, daily/minute bars, sector data, financial data, sync jobs, quant recommendations, backtests, portfolios, and simulation records. `vntrader/` is the vn.py runtime directory: `vt_setting.json`, vn.py SQLite `database.db`, logs, and any DataManager/Datafeed local files. Keep both directories when backing up or migrating.

The deploy script replaces the template `POSTGRES_PASSWORD=change-me` with a generated secret. Keep the generated `.env` private.

## Development

Development from repository root remains:

```bash
docker compose up --build
```

Do not require developers or operators to remember special Docker build targets.
