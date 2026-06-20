package handler

import (
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"
	"time"

	"github.com/zhanghecn/alphaagent-gateway/internal/auth"
	"github.com/zhanghecn/alphaagent-gateway/internal/config"
)

func newAuthHandler() (*AuthHandler, *auth.Service) {
	cfg := &config.Config{
		AdminUsername: "admin",
		AdminPassword: "s3cret-pw",
		JWTSecret:     []byte("test-secret-at-least-32-bytes-long-padding!!"),
		TokenTTL:      time.Hour,
	}
	return NewAuthHandler(cfg, auth.New(cfg)), auth.New(cfg)
}

func doLogin(h *AuthHandler, body string) *httptest.ResponseRecorder {
	rec := httptest.NewRecorder()
	req := httptest.NewRequest("POST", "/api/auth/login", strings.NewReader(body))
	h.Login(rec, req)
	return rec
}

func TestLoginSuccess(t *testing.T) {
	h, _ := newAuthHandler()
	rec := doLogin(h, `{"username":"admin","password":"s3cret-pw"}`)
	if rec.Code != http.StatusOK {
		t.Fatalf("status = %d, want 200; body=%s", rec.Code, rec.Body.String())
	}
	var resp struct {
		Success bool `json:"success"`
		Data    struct {
			Token     string `json:"token"`
			Username  string `json:"username"`
			TokenType string `json:"token_type"`
		} `json:"data"`
	}
	if err := json.Unmarshal(rec.Body.Bytes(), &resp); err != nil {
		t.Fatalf("unmarshal: %v", err)
	}
	if !resp.Success || resp.Data.Token == "" || resp.Data.TokenType != "Bearer" || resp.Data.Username != "admin" {
		t.Errorf("unexpected login payload: %+v", resp)
	}
}

func TestLoginWrongPassword(t *testing.T) {
	h, _ := newAuthHandler()
	rec := doLogin(h, `{"username":"admin","password":"wrong"}`)
	if rec.Code != http.StatusUnauthorized {
		t.Errorf("status = %d, want 401", rec.Code)
	}
}

func TestLoginBadJSON(t *testing.T) {
	h, _ := newAuthHandler()
	rec := doLogin(h, `not-json`)
	if rec.Code != http.StatusBadRequest {
		t.Errorf("status = %d, want 400", rec.Code)
	}
}

func TestMeWithoutToken(t *testing.T) {
	h, _ := newAuthHandler()
	rec := httptest.NewRecorder()
	h.Me(rec, httptest.NewRequest("GET", "/api/auth/me", nil))
	if rec.Code != http.StatusOK {
		t.Fatalf("status = %d, want 200", rec.Code)
	}
	var resp struct {
		Data struct {
			Authenticated bool `json:"authenticated"`
		} `json:"data"`
	}
	json.Unmarshal(rec.Body.Bytes(), &resp)
	if resp.Data.Authenticated {
		t.Error("should be unauthenticated without token")
	}
}

func TestMeWithToken(t *testing.T) {
	h, svc := newAuthHandler()
	token, _, _ := svc.Issue("admin")
	rec := httptest.NewRecorder()
	req := httptest.NewRequest("GET", "/api/auth/me", nil)
	req.Header.Set("Authorization", "Bearer "+token)
	h.Me(rec, req)
	var resp struct {
		Data struct {
			Authenticated bool   `json:"authenticated"`
			Username      string `json:"username"`
		} `json:"data"`
	}
	json.Unmarshal(rec.Body.Bytes(), &resp)
	if !resp.Data.Authenticated || resp.Data.Username != "admin" {
		t.Errorf("expected authenticated admin, got %+v", resp.Data)
	}
}

func TestLogout(t *testing.T) {
	h, _ := newAuthHandler()
	rec := httptest.NewRecorder()
	h.Logout(rec, httptest.NewRequest("POST", "/api/auth/logout", nil))
	if rec.Code != http.StatusOK {
		t.Errorf("status = %d, want 200", rec.Code)
	}
}
