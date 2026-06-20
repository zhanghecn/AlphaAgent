# syntax=docker/dockerfile:1.7
# =============================================================================
# AlphaAgent Gateway Dockerfile
# 多阶段构建：golang 编译静态二进制 → alpine 最小运行层
# =============================================================================
ARG GOLANG_IMAGE=golang:1.23-alpine
ARG RUNTIME_IMAGE=alpine:3.20

# ----- Stage 1: build --------------------------------------------------------
FROM ${GOLANG_IMAGE} AS build
ARG VERSION=dev
# GOPROXY 默认走七牛 goproxy.cn（国内可达、全球加速）；CI 国外环境如需可覆盖为官方代理。
ARG GOPROXY=https://goproxy.cn,direct
ENV GOPROXY=${GOPROXY}
WORKDIR /src

COPY go.mod go.sum ./
RUN --mount=type=cache,target=/go/pkg/mod \
    go mod download

COPY . .
# CGO_ENABLED=0 产纯静态二进制；-trimpath/-s/-w 去调试符号缩体积；VERSION 注入版本号。
RUN --mount=type=cache,target=/go/pkg/mod \
    --mount=type=cache,target=/root/.cache/go-build \
    CGO_ENABLED=0 GOOS=linux go build \
      -trimpath -ldflags="-s -w -X main.Version=${VERSION}" \
      -o /out/gateway ./cmd/gateway

# ----- Stage 2: runtime ------------------------------------------------------
FROM ${RUNTIME_IMAGE}
# ca-certificates：访问 https 上游需要；不再装 wget，健康检查走内置 -healthcheck flag。
RUN apk add --no-cache ca-certificates tzdata && \
    adduser -D -u 10001 gateway && \
    cp /usr/share/zoneinfo/Asia/Shanghai /etc/localtime && \
    echo "Asia/Shanghai" > /etc/timezone

COPY --from=build /out/gateway /usr/local/bin/gateway

USER gateway
EXPOSE 80
ENTRYPOINT ["/usr/local/bin/gateway"]
