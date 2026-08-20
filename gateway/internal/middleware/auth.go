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
			if !authenticated(w, r, authSvc) {
				return
			}
			next.ServeHTTP(w, r)
		})
	}
}

// PublicReadOrAuth 允许匿名读取；任何改变服务状态的请求仍须携带管理员 JWT。
// 未配置管理员凭证时，写操作明确拒绝，避免公开部署意外暴露同步、回测或升级接口。
func PublicReadOrAuth(cfg *config.Config, authSvc *auth.Service) func(http.Handler) http.Handler {
	return func(next http.Handler) http.Handler {
		return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
			if isReadOnlyMethod(r.Method) {
				next.ServeHTTP(w, r)
				return
			}
			if !cfg.OperatorAuthEnabled {
				httputil.WriteError(w, http.StatusForbidden, "OPERATOR_AUTH_DISABLED", "匿名模式未配置管理员写入权限")
				return
			}
			if !authenticated(w, r, authSvc) {
				return
			}
			next.ServeHTTP(w, r)
		})
	}
}

func isReadOnlyMethod(method string) bool {
	return method == http.MethodGet || method == http.MethodHead || method == http.MethodOptions
}

func authenticated(w http.ResponseWriter, r *http.Request, authSvc *auth.Service) bool {
	token := handler.BearerToken(r)
	if token == "" {
		httputil.WriteError(w, http.StatusUnauthorized, "UNAUTHENTICATED", "请先登录")
		return false
	}
	if _, err := authSvc.Parse(token); err != nil {
		httputil.WriteError(w, http.StatusUnauthorized, "INVALID_TOKEN", "登录已过期，请重新登录")
		return false
	}
	return true
}
