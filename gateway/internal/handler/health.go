package handler

import (
	"net/http"
	"net/url"
	"time"

	"github.com/zhanghecn/alphaagent-gateway/internal/httputil"
)

// Healthz 返回网关自身存活状态，供 compose healthcheck 使用。
func Healthz(w http.ResponseWriter, _ *http.Request) {
	httputil.WriteData(w, http.StatusOK, map[string]any{"status": "ok"})
}

// Ready 探测上游 api / web 是否可达，供编排层判断就绪。
func Ready(apiURL, webURL *url.URL) http.HandlerFunc {
	client := &http.Client{Timeout: 3 * time.Second}
	return func(w http.ResponseWriter, _ *http.Request) {
		status := map[string]any{
			"api": probe(client, apiURL.String()+"/api/health"),
			"web": probe(client, webURL.String()+"/"),
		}
		code := http.StatusOK
		if status["api"] != "ok" || status["web"] != "ok" {
			code = http.StatusServiceUnavailable
		}
		httputil.WriteJSON(w, code, status)
	}
}

func probe(client *http.Client, target string) string {
	resp, err := client.Get(target)
	if err != nil {
		return "unreachable"
	}
	defer resp.Body.Close()
	if resp.StatusCode >= 500 {
		return "unhealthy"
	}
	return "ok"
}
