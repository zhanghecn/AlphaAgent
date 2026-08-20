package proxy

import (
	"net/url"

	"github.com/go-chi/chi/v5"

	"github.com/zhanghecn/alphaagent-gateway/internal/auth"
	"github.com/zhanghecn/alphaagent-gateway/internal/config"
	"github.com/zhanghecn/alphaagent-gateway/internal/handler"
	mw "github.com/zhanghecn/alphaagent-gateway/internal/middleware"
)

// Mount 在 router 上装配全部网关路由：
//  1. /healthz、/readyz —— 网关自身健康（不鉴权）；
//  2. /api/auth/*       —— 登录/登出/当前用户（不鉴权）；
//  3. /api/*            —— 可按 AUTH_REQUIRED 选择鉴权后转发到 alphaagent-api；
//  4. /*                —— 转发到 alphaagent-web（SPA fallback 由 nginx 处理）。
func Mount(r chi.Router, cfg *config.Config, authSvc *auth.Service) {
	apiURL, err := url.Parse(cfg.APIUpstream)
	if err != nil {
		panic("invalid API_UPSTREAM: " + err.Error())
	}
	webURL, err := url.Parse(cfg.WebUpstream)
	if err != nil {
		panic("invalid WEB_UPSTREAM: " + err.Error())
	}

	apiProxy := New(apiURL, "alphaagent-api")
	webProxy := New(webURL, "alphaagent-web")
	authHandler := handler.NewAuthHandler(cfg, authSvc)

	// 1. 健康检查
	r.Get("/healthz", handler.Healthz)
	r.Get("/readyz", handler.Ready(apiURL, webURL))

	// 2. 认证端点（公开）
	r.Route("/api/auth", func(r chi.Router) {
		r.Post("/login", authHandler.Login)
		r.Post("/logout", authHandler.Logout)
		r.Get("/me", authHandler.Me)
	})

	// 3. 其余 /api/* —— 全站鉴权或匿名读取 + 管理员写入，转发到后端。
	if cfg.AuthRequired {
		r.Group(func(r chi.Router) {
			r.Use(mw.Auth(cfg, authSvc))
			r.Handle("/api/*", apiProxy)
		})
	} else {
		r.Group(func(r chi.Router) {
			r.Use(mw.PublicReadOrAuth(cfg, authSvc))
			r.Handle("/api/*", apiProxy)
		})
	}

	// 4. 前端静态资源与 SPA 路由 —— 转发到 nginx
	r.Handle("/*", webProxy)
}
