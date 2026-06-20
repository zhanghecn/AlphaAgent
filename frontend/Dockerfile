# syntax=docker/dockerfile:1.7

ARG NODE_IMAGE=node:22-alpine
ARG PNPM_VERSION=11.6.0
ARG PNPM_REGISTRY=https://registry.npmjs.org/

FROM ${NODE_IMAGE} AS deps
WORKDIR /app

ARG PNPM_VERSION
ARG PNPM_REGISTRY
ENV PNPM_HOME=/pnpm
ENV PATH=${PNPM_HOME}:${PATH}
ENV npm_config_registry=${PNPM_REGISTRY}
ENV NPM_CONFIG_REGISTRY=${PNPM_REGISTRY}

RUN npm config set registry "${PNPM_REGISTRY}" && \
    corepack enable && \
    corepack prepare pnpm@${PNPM_VERSION} --activate && \
    pnpm config set registry "${PNPM_REGISTRY}"

COPY package.json pnpm-lock.yaml pnpm-workspace.yaml ./
RUN --mount=type=cache,id=alphaagent-web-pnpm-store,target=/pnpm/store,sharing=locked \
    pnpm install --frozen-lockfile --store-dir=/pnpm/store --prefer-offline

FROM deps AS dev
WORKDIR /app
COPY . .

ENV VITE_API_BASE_URL=/api

EXPOSE 5173

CMD ["pnpm", "run", "dev", "--", "--host", "0.0.0.0"]

FROM deps AS build
WORKDIR /app
COPY . .
RUN pnpm run build

FROM nginx:1.27-alpine AS runtime
COPY --from=build /app/dist /usr/share/nginx/html
COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY docker-entrypoint.sh /docker-entrypoint.d/99-alphaagent-config.sh
RUN chmod +x /docker-entrypoint.d/99-alphaagent-config.sh

ENV VITE_API_BASE_URL=/api

EXPOSE 80
