// Package config 负责读取并校验网关运行所需的环境变量配置。
package config

import (
	"errors"
	"fmt"
	"os"
	"strconv"
	"strings"
	"time"
)

// Config 是网关运行配置，全部由环境变量注入。
type Config struct {
	AuthRequired        bool   // 是否要求所有 API 请求携带 JWT
	OperatorAuthEnabled bool   // 匿名读取模式下是否允许管理员令牌执行写操作
	AdminUsername       string // 管理员用户名
	AdminPassword       string // 管理员密码（明文，来自环境变量）
	JWTSecret           []byte // JWT 签名密钥
	TokenTTL            time.Duration

	GatewayAddr string // 监听地址，如 ":80"
	APIUpstream string // 后端 FastAPI 上游
	WebUpstream string // 前端 nginx 上游
}

// Load 从环境变量读取并校验配置，缺关键字段时 fail-fast。
func Load() (*Config, error) {
	authRequired, err := getEnvBool("AUTH_REQUIRED", false)
	if err != nil {
		return nil, err
	}
	c := &Config{
		AuthRequired:  authRequired,
		AdminUsername: getEnv("ADMIN_USERNAME", "admin"),
		AdminPassword: os.Getenv("ADMIN_PASSWORD"),
		JWTSecret:     []byte(os.Getenv("JWT_SECRET")),
		TokenTTL:      getEnvDuration("JWT_TOKEN_TTL", 24*time.Hour),
		GatewayAddr:   ":" + strings.TrimPrefix(getEnv("GATEWAY_PORT", "80"), ":"),
		APIUpstream:   getEnv("API_UPSTREAM", "http://alphaagent-api:8000"),
		WebUpstream:   getEnv("WEB_UPSTREAM", "http://alphaagent-web:80"),
	}

	if c.AuthRequired {
		if c.AdminPassword == "" {
			return nil, errors.New("ADMIN_PASSWORD is required")
		}
		if len(c.JWTSecret) < 32 {
			return nil, fmt.Errorf("JWT_SECRET must be at least 32 bytes (got %d)", len(c.JWTSecret))
		}
		c.OperatorAuthEnabled = true
		return c, nil
	}

	// 默认允许匿名读取。若配置了管理员凭证，写操作仍必须使用 JWT；两项
	// 凭证必须一起出现，避免意外用空密钥签发令牌。
	hasPassword := c.AdminPassword != ""
	hasSecret := len(c.JWTSecret) > 0
	if hasPassword != hasSecret {
		return nil, errors.New("ADMIN_PASSWORD and JWT_SECRET must be configured together")
	}
	if hasSecret && len(c.JWTSecret) < 32 {
		return nil, fmt.Errorf("JWT_SECRET must be at least 32 bytes (got %d)", len(c.JWTSecret))
	}
	c.OperatorAuthEnabled = hasPassword
	return c, nil
}

func getEnvBool(key string, def bool) (bool, error) {
	v := os.Getenv(key)
	if v == "" {
		return def, nil
	}
	parsed, err := strconv.ParseBool(v)
	if err != nil {
		return false, fmt.Errorf("%s must be a boolean: %w", key, err)
	}
	return parsed, nil
}

func getEnv(key, def string) string {
	if v := os.Getenv(key); v != "" {
		return v
	}
	return def
}

// getEnvDuration 支持 "24h" / "30m" / "3600"（秒）三种写法。
func getEnvDuration(key string, def time.Duration) time.Duration {
	v := os.Getenv(key)
	if v == "" {
		return def
	}
	if d, err := time.ParseDuration(v); err == nil {
		return d
	}
	if sec, err := strconv.Atoi(v); err == nil {
		return time.Duration(sec) * time.Second
	}
	return def
}
