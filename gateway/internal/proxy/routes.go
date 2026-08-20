package proxy

import (
	"net/http"
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
//  3. 数据管理接口       —— 始终要求管理员 JWT；
//  4. /api/*            —— 可按 AUTH_REQUIRED 选择鉴权后转发到 alphaagent-api；
//  5. /*                —— 转发到 alphaagent-web（SPA fallback 由 nginx 处理）。
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
	privateWebHandler := handler.NoIndex(webProxy)
	webHandler := http.Handler(webProxy)
	if cfg.AuthRequired {
		webHandler = privateWebHandler
	}

	// 1. 健康检查
	r.Get("/healthz", handler.Healthz)
	r.Get("/readyz", handler.Ready(apiURL, webURL))
	r.Get("/robots.txt", handler.Robots(!cfg.AuthRequired))
	r.Get("/sitemap.xml", handler.Sitemap(!cfg.AuthRequired))

	// 公开路由别名直接重定向，避免搜索引擎将 SPA 内部跳转视为重复内容。
	mountPermanentRedirect(r, "/explore", "/mainline")
	mountPermanentRedirect(r, "/chain", "/mainline")
	mountPermanentRedirect(r, "/data-sync", "/data")

	// 2. 认证端点（公开）
	r.Route("/api/auth", func(r chi.Router) {
		r.Post("/login", authHandler.Login)
		r.Post("/logout", authHandler.Logout)
		r.Get("/me", authHandler.Me)
	})

	// 3. 数据管理读取和写入均为管理员专属；匿名模式不能绕过此规则。
	r.Group(func(r chi.Router) {
		r.Use(mw.AdministratorOnly(cfg, authSvc))
		r.Handle("/api/data-sync", apiProxy)
		r.Handle("/api/data-sync/*", apiProxy)
		r.Handle("/api/data/status", apiProxy)
		r.Handle("/api/data/status/*", apiProxy)
	})

	// 4. 其余 /api/* —— 全站鉴权或匿名读取 + 管理员写入，转发到后端。
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

	// 5. 管理入口不允许收录；其余前端静态资源与 SPA 路由转发到 nginx。
	r.Handle("/login", privateWebHandler)
	r.Handle("/login/*", privateWebHandler)
	r.Handle("/data", privateWebHandler)
	r.Handle("/data/*", privateWebHandler)
	r.Handle("/stocks/*", privateWebHandler)
	r.Handle("/indices/*", privateWebHandler)
	r.Handle("/*", webHandler)
}

func mountPermanentRedirect(r chi.Router, path string, target string) {
	redirect := handler.PermanentRedirect(target)
	r.Get(path, redirect)
	r.Head(path, redirect)
}
