package handler

import (
	"encoding/xml"
	"net/http"
	"net/url"
	"strings"
)

var sitemapPaths = []string{
	"/",
	"/stocks",
	"/market",
	"/mainline",
	"/short-term",
	"/lianban",
	"/lianban/ladder",
	"/sectors",
}

type sitemapURLSet struct {
	XMLName xml.Name     `xml:"urlset"`
	Xmlns   string       `xml:"xmlns,attr"`
	URLs    []sitemapURL `xml:"url"`
}

type sitemapURL struct {
	Location string `xml:"loc"`
}

// Robots returns crawler directives for the deployment's current visibility mode.
func Robots(indexable bool) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Content-Type", "text/plain; charset=utf-8")
		w.Header().Set("Cache-Control", "public, max-age=3600")

		if !indexable {
			_, _ = w.Write([]byte("User-agent: *\nDisallow: /\n"))
			return
		}

		var body strings.Builder
		body.WriteString("User-agent: *\nAllow: /\nDisallow: /login\nDisallow: /data\nDisallow: /api/\n")
		if origin, ok := requestOrigin(r); ok {
			body.WriteString("Sitemap: ")
			body.WriteString(origin)
			body.WriteString("/sitemap.xml\n")
		}
		_, _ = w.Write([]byte(body.String()))
	}
}

// Sitemap returns the stable, anonymous pages that search engines may crawl.
func Sitemap(indexable bool) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		if !indexable {
			http.NotFound(w, r)
			return
		}

		origin, ok := requestOrigin(r)
		if !ok {
			http.Error(w, "invalid request host", http.StatusBadRequest)
			return
		}

		urls := make([]sitemapURL, 0, len(sitemapPaths))
		for _, path := range sitemapPaths {
			urls = append(urls, sitemapURL{Location: origin + path})
		}

		w.Header().Set("Content-Type", "application/xml; charset=utf-8")
		w.Header().Set("Cache-Control", "public, max-age=3600")
		_, _ = w.Write([]byte(xml.Header))
		_ = xml.NewEncoder(w).Encode(sitemapURLSet{
			Xmlns: "http://www.sitemaps.org/schemas/sitemap/0.9",
			URLs:  urls,
		})
	}
}

// NoIndex marks a proxied response as unsuitable for search indexes.
func NoIndex(next http.Handler) http.Handler {
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("X-Robots-Tag", "noindex, nofollow, noarchive")
		next.ServeHTTP(w, r)
	})
}

// PermanentRedirect keeps old client-side aliases out of the crawl graph.
func PermanentRedirect(target string) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		location := target
		if r.URL.RawQuery != "" {
			location += "?" + r.URL.RawQuery
		}
		http.Redirect(w, r, location, http.StatusMovedPermanently)
	}
}

func requestOrigin(r *http.Request) (string, bool) {
	host := strings.TrimSpace(r.Host)
	parsedHost, err := url.Parse("http://" + host)
	if host == "" || err != nil || parsedHost.Host != host || parsedHost.User != nil || parsedHost.Path != "" || parsedHost.RawQuery != "" {
		return "", false
	}

	scheme := "http"
	if r.TLS != nil {
		scheme = "https"
	} else if forwarded := strings.Split(r.Header.Get("X-Forwarded-Proto"), ",")[0]; forwarded != "" {
		switch strings.ToLower(strings.TrimSpace(forwarded)) {
		case "http", "https":
			scheme = strings.ToLower(strings.TrimSpace(forwarded))
		}
	}

	return (&url.URL{Scheme: scheme, Host: host}).String(), true
}
