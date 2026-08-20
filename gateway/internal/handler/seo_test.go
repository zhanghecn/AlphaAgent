package handler

import (
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"
)

func TestRobotsListsPrivatePathsAndUsesRequestOrigin(t *testing.T) {
	request := httptest.NewRequest(http.MethodGet, "http://alphaagent.example/robots.txt", nil)
	request.Header.Set("X-Forwarded-Proto", "https")
	response := httptest.NewRecorder()

	Robots(true).ServeHTTP(response, request)

	if response.Code != http.StatusOK {
		t.Fatalf("status = %d, want 200", response.Code)
	}
	body := response.Body.String()
	for _, expected := range []string{
		"Allow: /",
		"Disallow: /login",
		"Disallow: /data",
		"Disallow: /api/",
		"Sitemap: https://alphaagent.example/sitemap.xml",
	} {
		if !strings.Contains(body, expected) {
			t.Errorf("robots.txt missing %q:\n%s", expected, body)
		}
	}
}

func TestRobotsDisallowsAllWhenTheApplicationRequiresAuthentication(t *testing.T) {
	request := httptest.NewRequest(http.MethodGet, "http://alphaagent.example/robots.txt", nil)
	response := httptest.NewRecorder()

	Robots(false).ServeHTTP(response, request)

	if response.Code != http.StatusOK {
		t.Fatalf("status = %d, want 200", response.Code)
	}
	if body := response.Body.String(); body != "User-agent: *\nDisallow: /\n" {
		t.Fatalf("robots.txt = %q", body)
	}
}

func TestSitemapListsOnlyStablePublicPages(t *testing.T) {
	request := httptest.NewRequest(http.MethodGet, "http://alphaagent.example/sitemap.xml", nil)
	request.Header.Set("X-Forwarded-Proto", "https")
	response := httptest.NewRecorder()

	Sitemap(true).ServeHTTP(response, request)

	if response.Code != http.StatusOK {
		t.Fatalf("status = %d, want 200", response.Code)
	}
	body := response.Body.String()
	for _, expected := range []string{
		"https://alphaagent.example/",
		"https://alphaagent.example/stocks",
		"https://alphaagent.example/mainline",
		"https://alphaagent.example/lianban/ladder",
	} {
		if !strings.Contains(body, expected) {
			t.Errorf("sitemap.xml missing %q:\n%s", expected, body)
		}
	}
	for _, unexpected := range []string{"/login", "/data", "/stocks/600519.SSE"} {
		if strings.Contains(body, unexpected) {
			t.Errorf("sitemap.xml unexpectedly contains %q:\n%s", unexpected, body)
		}
	}
}

func TestSitemapIsUnavailableWhenTheApplicationRequiresAuthentication(t *testing.T) {
	request := httptest.NewRequest(http.MethodGet, "http://alphaagent.example/sitemap.xml", nil)
	response := httptest.NewRecorder()

	Sitemap(false).ServeHTTP(response, request)

	if response.Code != http.StatusNotFound {
		t.Fatalf("status = %d, want 404", response.Code)
	}
}

func TestNoIndexAddsResponseHeader(t *testing.T) {
	next := http.HandlerFunc(func(w http.ResponseWriter, _ *http.Request) {
		w.WriteHeader(http.StatusOK)
	})
	request := httptest.NewRequest(http.MethodGet, "http://alphaagent.example/login", nil)
	response := httptest.NewRecorder()

	NoIndex(next).ServeHTTP(response, request)

	if got := response.Header().Get("X-Robots-Tag"); got != "noindex, nofollow, noarchive" {
		t.Fatalf("X-Robots-Tag = %q", got)
	}
}
