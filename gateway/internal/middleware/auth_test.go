package middleware

import (
	"net/http"
	"net/http/httptest"
	"testing"
	"time"

	"github.com/zhanghecn/alphaagent-gateway/internal/auth"
	"github.com/zhanghecn/alphaagent-gateway/internal/config"
)

func testAuth() (*config.Config, *auth.Service) {
	cfg := &config.Config{
		AdminUsername: "admin",
		AdminPassword: "pw",
		JWTSecret:     []byte("test-secret-at-least-32-bytes-long-padding!!"),
		TokenTTL:      time.Hour,
	}
	return cfg, auth.New(cfg)
}

func TestAuthNoTokenReturns401(t *testing.T) {
	cfg, svc := testAuth()
	h := Auth(cfg, svc)(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		t.Error("next should not be called without token")
	}))
	rec := httptest.NewRecorder()
	h.ServeHTTP(rec, httptest.NewRequest("GET", "/api/health", nil))
	if rec.Code != http.StatusUnauthorized {
		t.Errorf("status = %d, want 401", rec.Code)
	}
}

func TestAuthInvalidTokenReturns401(t *testing.T) {
	cfg, svc := testAuth()
	h := Auth(cfg, svc)(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		t.Error("next should not be called with invalid token")
	}))
	rec := httptest.NewRecorder()
	req := httptest.NewRequest("GET", "/api/health", nil)
	req.Header.Set("Authorization", "Bearer garbage")
	h.ServeHTTP(rec, req)
	if rec.Code != http.StatusUnauthorized {
		t.Errorf("status = %d, want 401", rec.Code)
	}
}

func TestAuthValidTokenPassesThrough(t *testing.T) {
	cfg, svc := testAuth()
	token, _, _ := svc.Issue("admin")
	called := false
	h := Auth(cfg, svc)(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		called = true
		w.WriteHeader(http.StatusOK)
	}))
	rec := httptest.NewRecorder()
	req := httptest.NewRequest("GET", "/api/health", nil)
	req.Header.Set("Authorization", "Bearer "+token)
	h.ServeHTTP(rec, req)
	if !called {
		t.Error("next should be called with valid token")
	}
	if rec.Code != http.StatusOK {
		t.Errorf("status = %d, want 200", rec.Code)
	}
}
