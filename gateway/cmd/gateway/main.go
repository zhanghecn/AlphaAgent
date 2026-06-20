// Command gateway 是 AlphaAgent 的统一入口认证与反向代理网关。
package main

import (
	"context"
	"log"
	"log/slog"
	"net/http"
	"os"
	"os/signal"
	"syscall"
	"time"

	"github.com/go-chi/chi/v5"
	chimw "github.com/go-chi/chi/v5/middleware"

	"github.com/zhanghecn/alphaagent-gateway/internal/auth"
	"github.com/zhanghecn/alphaagent-gateway/internal/config"
	"github.com/zhanghecn/alphaagent-gateway/internal/proxy"
)

// Version 在构建时通过 -ldflags 注入，默认 dev。
var Version = "dev"

func main() {
	// healthcheck 模式：供 compose healthcheck 调用，自连 /healthz 后以退出码表示状态。
	if len(os.Args) > 1 && os.Args[1] == "-healthcheck" {
		os.Exit(runHealthcheck())
	}

	cfg, err := config.Load()
	if err != nil {
		log.Fatalf("config load failed: %v", err)
	}
	slog.Info("starting alphaagent gateway", "version", Version, "addr", cfg.GatewayAddr)

	authSvc := auth.New(cfg)

	r := chi.NewRouter()
	r.Use(chimw.RealIP)
	r.Use(chimw.RequestID)
	r.Use(chimw.Recoverer)
	r.Use(requestLogger)
	r.Use(chimw.Timeout(60 * time.Second))

	proxy.Mount(r, cfg, authSvc)

	srv := &http.Server{
		Addr:              cfg.GatewayAddr,
		Handler:           r,
		ReadHeaderTimeout: 10 * time.Second,
		ReadTimeout:       30 * time.Second,
		WriteTimeout:      60 * time.Second,
		IdleTimeout:       120 * time.Second,
	}

	go func() {
		if err := srv.ListenAndServe(); err != nil && err != http.ErrServerClosed {
			log.Fatalf("listen failed: %v", err)
		}
	}()

	quit := make(chan os.Signal, 1)
	signal.Notify(quit, syscall.SIGINT, syscall.SIGTERM)
	<-quit
	slog.Info("shutting down gateway")

	ctx, cancel := context.WithTimeout(context.Background(), 10*time.Second)
	defer cancel()
	if err := srv.Shutdown(ctx); err != nil {
		slog.Error("graceful shutdown failed", "err", err)
	}
	slog.Info("gateway stopped")
}

// requestLogger 输出精简 access 日志（方法/路径/状态/耗时）。
func requestLogger(next http.Handler) http.Handler {
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		start := time.Now()
		ww := chimw.NewWrapResponseWriter(w, r.ProtoMajor)
		next.ServeHTTP(ww, r)
		slog.Info("http",
			"method", r.Method,
			"path", r.URL.Path,
			"status", ww.Status(),
			"ms", time.Since(start).Milliseconds(),
		)
	})
}

// runHealthcheck 自连本地 /healthz，成功返回 0。
func runHealthcheck() int {
	port := os.Getenv("GATEWAY_PORT")
	if port == "" {
		port = "80"
	}
	client := http.Client{Timeout: 3 * time.Second}
	resp, err := client.Get("http://localhost:" + port + "/healthz")
	if err != nil {
		return 1
	}
	defer resp.Body.Close()
	if resp.StatusCode != http.StatusOK {
		return 1
	}
	return 0
}
