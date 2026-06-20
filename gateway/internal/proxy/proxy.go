// Package proxy 构造反向代理并装配网关路由。
package proxy

import (
	"fmt"
	"log/slog"
	"net/http"
	nethttputil "net/http/httputil" // 别名，避免与本项目 internal/httputil 包名冲突
	"net/url"

	"github.com/zhanghecn/alphaagent-gateway/internal/httputil"
)

// New 构造一个指向 target 的反向代理：
//   - 注入 X-Forwarded-Host / X-Forwarded-Proto，保留原始请求来源信息；
//   - 上游不可达时返回 502（而非默认的连接错误页）；
//   - FlushInterval=-1 立即刷新，为未来可能的 SSE/流式响应预留（当前零成本）。
func New(target *url.URL, name string) *nethttputil.ReverseProxy {
	p := nethttputil.NewSingleHostReverseProxy(target)
	origDirector := p.Director
	p.Director = func(req *http.Request) {
		origDirector(req)
		req.Header.Set("X-Forwarded-Host", req.Host)
		req.Header.Set("X-Forwarded-Proto", schemeOf(req))
	}
	p.ErrorHandler = func(w http.ResponseWriter, r *http.Request, err error) {
		slog.Error("upstream proxy error", "name", name, "path", r.URL.Path, "err", err)
		httputil.WriteError(w, http.StatusBadGateway, "UPSTREAM_UNREACHABLE",
			fmt.Sprintf("%s 上游服务不可用", name))
	}
	p.FlushInterval = -1
	return p
}

func schemeOf(r *http.Request) string {
	if r.TLS != nil {
		return "https"
	}
	if proto := r.Header.Get("X-Forwarded-Proto"); proto != "" {
		return proto
	}
	return "http"
}
