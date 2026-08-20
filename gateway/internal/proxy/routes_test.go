package proxy

import (
	"net/http"
	"net/http/httptest"
	"testing"
	"time"

	"github.com/go-chi/chi/v5"

	"github.com/zhanghecn/alphaagent-gateway/internal/auth"
	"github.com/zhanghecn/alphaagent-gateway/internal/config"
)

func TestAnonymousModeProxiesAPIWithoutBearerToken(t *testing.T) {
	api := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.URL.Path != "/api/market/overview" {
			t.Fatalf("path = %q", r.URL.Path)
		}
		w.WriteHeader(http.StatusOK)
	}))
	defer api.Close()
	web := httptest.NewServer(http.NotFoundHandler())
	defer web.Close()

	cfg := &config.Config{
		AuthRequired: false,
		JWTSecret:    []byte("test-secret-at-least-32-bytes-long-padding!!"),
		TokenTTL:     time.Hour,
		APIUpstream:  api.URL,
		WebUpstream:  web.URL,
	}
	r := chi.NewRouter()
	Mount(r, cfg, auth.New(cfg))

	response := httptest.NewRecorder()
	r.ServeHTTP(response, httptest.NewRequest(http.MethodGet, "/api/market/overview", nil))

	if response.Code != http.StatusOK {
		t.Fatalf("status = %d, want 200; body=%s", response.Code, response.Body.String())
	}
}

func TestAnonymousModeRejectsWritesWithoutOperatorCredentials(t *testing.T) {
	called := false
	api := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		called = true
		w.WriteHeader(http.StatusOK)
	}))
	defer api.Close()
	web := httptest.NewServer(http.NotFoundHandler())
	defer web.Close()

	cfg := &config.Config{
		AuthRequired:        false,
		OperatorAuthEnabled: false,
		TokenTTL:            time.Hour,
		APIUpstream:         api.URL,
		WebUpstream:         web.URL,
	}
	r := chi.NewRouter()
	Mount(r, cfg, auth.New(cfg))

	response := httptest.NewRecorder()
	r.ServeHTTP(response, httptest.NewRequest(http.MethodPost, "/api/data-sync/batches/run-all", nil))

	if response.Code != http.StatusForbidden {
		t.Fatalf("status = %d, want 403; body=%s", response.Code, response.Body.String())
	}
	if called {
		t.Error("write request unexpectedly reached API upstream")
	}
}

func TestAnonymousModeRejectsDataManagementReadsWithoutAdministratorToken(t *testing.T) {
	called := false
	api := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		called = true
		w.WriteHeader(http.StatusOK)
	}))
	defer api.Close()
	web := httptest.NewServer(http.NotFoundHandler())
	defer web.Close()

	cfg := &config.Config{
		AuthRequired:        false,
		OperatorAuthEnabled: true,
		AdminUsername:       "admin",
		AdminPassword:       "pw",
		JWTSecret:           []byte("test-secret-at-least-32-bytes-long-padding!!"),
		TokenTTL:            time.Hour,
		APIUpstream:         api.URL,
		WebUpstream:         web.URL,
	}
	r := chi.NewRouter()
	Mount(r, cfg, auth.New(cfg))

	for _, path := range []string{"/api/data-sync/sources", "/api/data/status"} {
		response := httptest.NewRecorder()
		r.ServeHTTP(response, httptest.NewRequest(http.MethodGet, path, nil))

		if response.Code != http.StatusUnauthorized {
			t.Fatalf("%s: status = %d, want 401; body=%s", path, response.Code, response.Body.String())
		}
	}
	if called {
		t.Error("data management read unexpectedly reached API upstream")
	}
}

func TestAnonymousModeAllowsAdministratorDataManagementReads(t *testing.T) {
	api := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.URL.Path != "/api/data-sync/health" {
			t.Fatalf("path = %q, want /api/data-sync/health", r.URL.Path)
		}
		w.WriteHeader(http.StatusOK)
	}))
	defer api.Close()
	web := httptest.NewServer(http.NotFoundHandler())
	defer web.Close()

	cfg := &config.Config{
		AuthRequired:        false,
		OperatorAuthEnabled: true,
		AdminUsername:       "admin",
		AdminPassword:       "pw",
		JWTSecret:           []byte("test-secret-at-least-32-bytes-long-padding!!"),
		TokenTTL:            time.Hour,
		APIUpstream:         api.URL,
		WebUpstream:         web.URL,
	}
	authSvc := auth.New(cfg)
	token, _, err := authSvc.Issue("admin")
	if err != nil {
		t.Fatalf("issue token: %v", err)
	}
	r := chi.NewRouter()
	Mount(r, cfg, authSvc)

	request := httptest.NewRequest(http.MethodGet, "/api/data-sync/health", nil)
	request.Header.Set("Authorization", "Bearer "+token)
	response := httptest.NewRecorder()
	r.ServeHTTP(response, request)

	if response.Code != http.StatusOK {
		t.Fatalf("status = %d, want 200; body=%s", response.Code, response.Body.String())
	}
}

func TestAnonymousModeAllowsAdministratorWrites(t *testing.T) {
	api := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.Method != http.MethodPost {
			t.Fatalf("method = %q, want POST", r.Method)
		}
		if r.URL.Path != "/api/system/update" {
			t.Fatalf("path = %q, want /api/system/update", r.URL.Path)
		}
		w.WriteHeader(http.StatusOK)
	}))
	defer api.Close()
	web := httptest.NewServer(http.NotFoundHandler())
	defer web.Close()

	cfg := &config.Config{
		AuthRequired:        false,
		OperatorAuthEnabled: true,
		AdminUsername:       "admin",
		AdminPassword:       "pw",
		JWTSecret:           []byte("test-secret-at-least-32-bytes-long-padding!!"),
		TokenTTL:            time.Hour,
		APIUpstream:         api.URL,
		WebUpstream:         web.URL,
	}
	authSvc := auth.New(cfg)
	token, _, err := authSvc.Issue("admin")
	if err != nil {
		t.Fatalf("issue token: %v", err)
	}
	r := chi.NewRouter()
	Mount(r, cfg, authSvc)

	request := httptest.NewRequest(http.MethodPost, "/api/system/update", nil)
	request.Header.Set("Authorization", "Bearer "+token)
	response := httptest.NewRecorder()
	r.ServeHTTP(response, request)

	if response.Code != http.StatusOK {
		t.Fatalf("status = %d, want 200; body=%s", response.Code, response.Body.String())
	}
}

func TestAnonymousModeRejectsSystemUpdateWithoutAdministratorToken(t *testing.T) {
	called := false
	api := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		called = true
		w.WriteHeader(http.StatusOK)
	}))
	defer api.Close()
	web := httptest.NewServer(http.NotFoundHandler())
	defer web.Close()

	cfg := &config.Config{
		AuthRequired:        false,
		OperatorAuthEnabled: true,
		AdminUsername:       "admin",
		AdminPassword:       "pw",
		JWTSecret:           []byte("test-secret-at-least-32-bytes-long-padding!!"),
		TokenTTL:            time.Hour,
		APIUpstream:         api.URL,
		WebUpstream:         web.URL,
	}
	r := chi.NewRouter()
	Mount(r, cfg, auth.New(cfg))

	response := httptest.NewRecorder()
	r.ServeHTTP(response, httptest.NewRequest(http.MethodPost, "/api/system/update", nil))

	if response.Code != http.StatusUnauthorized {
		t.Fatalf("status = %d, want 401; body=%s", response.Code, response.Body.String())
	}
	if called {
		t.Error("system update unexpectedly reached API upstream")
	}
}
