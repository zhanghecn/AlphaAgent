// Package auth 提供 JWT 签发/解析与密码常量时间校验。
package auth

import (
	"fmt"
	"time"

	"github.com/golang-jwt/jwt/v5"

	"github.com/zhanghecn/alphaagent-gateway/internal/config"
)

// Claims 是网关签发的 JWT 载荷。
type Claims struct {
	Username string `json:"username"`
	jwt.RegisteredClaims
}

// Service 封装 JWT 签发与解析。
type Service struct {
	cfg *config.Config
}

// New 构造认证服务。
func New(cfg *config.Config) *Service {
	return &Service{cfg: cfg}
}

// Issue 为指定用户签发 JWT，返回 token 字符串与过期时间。
func (s *Service) Issue(username string) (string, time.Time, error) {
	now := time.Now()
	exp := now.Add(s.cfg.TokenTTL)
	claims := Claims{
		Username: username,
		RegisteredClaims: jwt.RegisteredClaims{
			Issuer:    "alphaagent-gateway",
			IssuedAt:  jwt.NewNumericDate(now),
			ExpiresAt: jwt.NewNumericDate(exp),
		},
	}
	token := jwt.NewWithClaims(jwt.SigningMethodHS256, claims)
	signed, err := token.SignedString(s.cfg.JWTSecret)
	if err != nil {
		return "", time.Time{}, fmt.Errorf("sign token: %w", err)
	}
	return signed, exp, nil
}

// Parse 校验并解析 token，失败（签名错误/过期/格式错）返回 error。
func (s *Service) Parse(tokenStr string) (*Claims, error) {
	claims := &Claims{}
	tok, err := jwt.ParseWithClaims(tokenStr, claims, func(t *jwt.Token) (any, error) {
		// 强制 HS256，防止 alg 混淆攻击。
		if _, ok := t.Method.(*jwt.SigningMethodHMAC); !ok {
			return nil, fmt.Errorf("unexpected signing method: %v", t.Header["alg"])
		}
		return s.cfg.JWTSecret, nil
	})
	if err != nil {
		return nil, err
	}
	if !tok.Valid {
		return nil, fmt.Errorf("invalid token")
	}
	return claims, nil
}
