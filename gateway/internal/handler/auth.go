// Package handler 实现网关自身的 HTTP 端点（认证与健康检查）。
package handler

import (
	"encoding/json"
	"net/http"
	"strings"

	"github.com/zhanghecn/alphaagent-gateway/internal/auth"
	"github.com/zhanghecn/alphaagent-gateway/internal/config"
	"github.com/zhanghecn/alphaagent-gateway/internal/httputil"
)

// AuthHandler 处理登录、登出、当前用户三个端点。
type AuthHandler struct {
	cfg     *config.Config
	authSvc *auth.Service
}

// NewAuthHandler 构造认证处理器。
func NewAuthHandler(cfg *config.Config, authSvc *auth.Service) *AuthHandler {
	return &AuthHandler{cfg: cfg, authSvc: authSvc}
}

type loginRequest struct {
	Username string `json:"username"`
	Password string `json:"password"`
}

// Login: POST /api/auth/login
// 校验用户名密码（都用常量时间比较，统一 401 不区分错误项），通过则签发 JWT。
func (h *AuthHandler) Login(w http.ResponseWriter, r *http.Request) {
	if !h.cfg.OperatorAuthEnabled {
		httputil.WriteError(w, http.StatusForbidden, "OPERATOR_AUTH_DISABLED", "未配置管理员写入权限")
		return
	}
	var req loginRequest
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		httputil.WriteError(w, http.StatusBadRequest, "BAD_REQUEST", "请求体格式错误")
		return
	}
	if !auth.VerifySecret(req.Username, h.cfg.AdminUsername) ||
		!auth.VerifySecret(req.Password, h.cfg.AdminPassword) {
		httputil.WriteError(w, http.StatusUnauthorized, "INVALID_CREDENTIALS", "用户名或密码错误")
		return
	}
	token, exp, err := h.authSvc.Issue(h.cfg.AdminUsername)
	if err != nil {
		httputil.WriteError(w, http.StatusInternalServerError, "TOKEN_ERROR", "签发令牌失败")
		return
	}
	httputil.WriteData(w, http.StatusOK, map[string]any{
		"token":      token,
		"token_type": "Bearer",
		"expires_at": exp.Unix(),
		"username":   h.cfg.AdminUsername,
	})
}

// Logout: POST /api/auth/logout
// JWT 无状态，实际登出由前端清除本地 token 完成；此处仅返回成功以保持 API 对称。
func (h *AuthHandler) Logout(w http.ResponseWriter, _ *http.Request) {
	httputil.WriteData(w, http.StatusOK, nil)
}

// Me: GET /api/auth/me
// 读 Authorization 头判断登录态。注意：本端点不返回 401，而是返回
// {authenticated:false}，前端路由守卫无需处理异常分支。
func (h *AuthHandler) Me(w http.ResponseWriter, r *http.Request) {
	token := BearerToken(r)
	if token == "" {
		httputil.WriteData(w, http.StatusOK, map[string]any{"authenticated": false})
		return
	}
	claims, err := h.authSvc.Parse(token)
	if err != nil {
		httputil.WriteData(w, http.StatusOK, map[string]any{"authenticated": false})
		return
	}
	httputil.WriteData(w, http.StatusOK, map[string]any{
		"authenticated": true,
		"username":      claims.Username,
	})
}

// BearerToken 从 Authorization: Bearer <token> 头提取 token，供中间件复用。
func BearerToken(r *http.Request) string {
	header := r.Header.Get("Authorization")
	parts := strings.SplitN(header, " ", 2)
	if len(parts) != 2 || !strings.EqualFold(parts[0], "Bearer") {
		return ""
	}
	return strings.TrimSpace(parts[1])
}
