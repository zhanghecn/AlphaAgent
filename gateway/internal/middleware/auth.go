// Package middleware 提供网关的 HTTP 中间件，当前仅含登录态过滤。
package middleware

import (
	"net/http"

	"github.com/zhanghecn/alphaagent-gateway/internal/auth"
	"github.com/zhanghecn/alphaagent-gateway/internal/config"
	"github.com/zhanghecn/alphaagent-gateway/internal/handler"
	"github.com/zhanghecn/alphaagent-gateway/internal/httputil"
)

// Auth 是登录态过滤器：从 Authorization 头取 JWT 校验，失败返回 401。
// 仅挂在需要鉴权的路由组（除 /api/auth/* 外的 /api/*）。
func Auth(cfg *config.Config, authSvc *auth.Service) func(http.Handler) http.Handler {
	return func(next http.Handler) http.Handler {
		return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
			token := handler.BearerToken(r)
			if token == "" {
				httputil.WriteError(w, http.StatusUnauthorized, "UNAUTHENTICATED", "请先登录")
				return
			}
			if _, err := authSvc.Parse(token); err != nil {
				httputil.WriteError(w, http.StatusUnauthorized, "INVALID_TOKEN", "登录已过期，请重新登录")
				return
			}
			next.ServeHTTP(w, r)
		})
	}
}
