// Package httputil 提供统一的 JSON 响应工具，保证网关返回体与
// 后端 FastAPI 的 {success, data, error} 结构一致，前端可复用同一套解析。
package httputil

import (
	"encoding/json"
	"net/http"
)

// Response 是与后端一致的统一响应外壳。
type Response struct {
	Success bool       `json:"success"`
	Data    any        `json:"data"`
	Error   *ErrorBody `json:"error,omitempty"`
}

// ErrorBody 是错误明细。
type ErrorBody struct {
	Code    string `json:"code"`
	Message string `json:"message"`
}

// WriteJSON 以 JSON 写出成功响应。
func WriteJSON(w http.ResponseWriter, status int, body any) {
	resp := Response{Success: status < 400, Data: body}
	write(w, status, resp)
}

// WriteData 显式写出带 success=true 的数据响应。
func WriteData(w http.ResponseWriter, status int, data any) {
	write(w, status, Response{Success: true, Data: data})
}

// WriteError 写出失败响应。
func WriteError(w http.ResponseWriter, status int, code, message string) {
	write(w, status, Response{
		Success: false,
		Error:   &ErrorBody{Code: code, Message: message},
	})
}

func write(w http.ResponseWriter, status int, body any) {
	w.Header().Set("Content-Type", "application/json; charset=utf-8")
	w.WriteHeader(status)
	// 编码失败无法再通知客户端，忽略错误（连接已断）。
	_ = json.NewEncoder(w).Encode(body)
}
