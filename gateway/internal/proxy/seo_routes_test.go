package proxy

import (
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"
	"time"

	"github.com/go-chi/chi/v5"

	"github.com/zhanghecn/alphaagent-gateway/internal/auth"
	"github.com/zhanghecn/alphaagent-gateway/internal/config"
)

func mountSEOTestRouter(t *testing.T, webHandler http.Handler) chi.Router {
	t.Helper()
	api := httptest.NewServer(http.NotFoundHandler())
	t.Cleanup(api.Close)
	web := httptest.NewServer(webHandler)
	t.Cleanup(web.Close)

	cfg := &config.Config{
		TokenTTL:    time.Hour,
		APIUpstream: api.URL,
		WebUpstream: web.URL,
	}
	router := chi.NewRouter()
	Mount(router, cfg, auth.New(cfg))
	return router
}

func TestMountServesSitemapWithoutCallingWebUpstream(t *testing.T) {
	called := false
	router := mountSEOTestRouter(t, http.HandlerFunc(func(w http.ResponseWriter, _ *http.Request) {
		called = true
		w.WriteHeader(http.StatusOK)
	}))
	request := httptest.NewRequest(http.MethodGet, "https://alphaagent.example/sitemap.xml", nil)
	response := httptest.NewRecorder()

	router.ServeHTTP(response, request)

	if response.Code != http.StatusOK {
		t.Fatalf("status = %d, want 200", response.Code)
	}
	if !strings.Contains(response.Body.String(), "https://alphaagent.example/mainline") {
		t.Fatalf("sitemap.xml = %s", response.Body.String())
	}
	if called {
		t.Fatal("sitemap.xml unexpectedly reached the web upstream")
	}
}

func TestMountAddsNoIndexToPrivateAndParameterizedPages(t *testing.T) {
	router := mountSEOTestRouter(t, http.HandlerFunc(func(w http.ResponseWriter, _ *http.Request) {
		w.WriteHeader(http.StatusOK)
	}))

	for _, path := range []string{"/login", "/data", "/stocks/600519.SSE", "/indices/000001.SH"} {
		response := httptest.NewRecorder()
		router.ServeHTTP(response, httptest.NewRequest(http.MethodGet, path, nil))

		if got := response.Header().Get("X-Robots-Tag"); got != "noindex, nofollow, noarchive" {
			t.Errorf("%s: X-Robots-Tag = %q", path, got)
		}
	}
}

func TestMountPermanentlyRedirectsLegacyAliases(t *testing.T) {
	router := mountSEOTestRouter(t, http.NotFoundHandler())

	for _, method := range []string{http.MethodGet, http.MethodHead} {
		request := httptest.NewRequest(method, "/explore?sector=ai", nil)
		response := httptest.NewRecorder()

		router.ServeHTTP(response, request)

		if response.Code != http.StatusMovedPermanently {
			t.Errorf("%s: status = %d, want 301", method, response.Code)
		}
		if got := response.Header().Get("Location"); got != "/mainline?sector=ai" {
			t.Errorf("%s: Location = %q", method, got)
		}
	}
}
