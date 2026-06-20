package auth

import (
	"testing"
	"time"

	"github.com/zhanghecn/alphaagent-gateway/internal/config"
)

func testService(ttl time.Duration) *Service {
	return New(&config.Config{
		AdminUsername: "admin",
		AdminPassword: "pw",
		JWTSecret:     []byte("test-secret-at-least-32-bytes-long-padding!!"),
		TokenTTL:      ttl,
	})
}

func TestIssueAndParseRoundTrip(t *testing.T) {
	s := testService(time.Hour)
	token, exp, err := s.Issue("admin")
	if err != nil {
		t.Fatalf("issue: %v", err)
	}
	if token == "" {
		t.Fatal("token should not be empty")
	}
	if exp.IsZero() {
		t.Fatal("expiry should not be zero")
	}
	claims, err := s.Parse(token)
	if err != nil {
		t.Fatalf("parse: %v", err)
	}
	if claims.Username != "admin" {
		t.Errorf("username = %q, want admin", claims.Username)
	}
}

func TestParseExpired(t *testing.T) {
	s := testService(-time.Hour) // 签发即过期
	token, _, err := s.Issue("admin")
	if err != nil {
		t.Fatalf("issue: %v", err)
	}
	if _, err := s.Parse(token); err == nil {
		t.Error("expired token should fail to parse")
	}
}

func TestParseWrongSecret(t *testing.T) {
	token, _, _ := testService(time.Hour).Issue("admin")
	other := New(&config.Config{
		JWTSecret: []byte("another-secret-at-least-32-bytes-long-pad"),
		TokenTTL:  time.Hour,
	})
	if _, err := other.Parse(token); err == nil {
		t.Error("token signed with different secret should fail")
	}
}

func TestParseGarbage(t *testing.T) {
	s := testService(time.Hour)
	for _, bad := range []string{"", "not-a-jwt", "a.b.c"} {
		if _, err := s.Parse(bad); err == nil {
			t.Errorf("garbage token %q should fail", bad)
		}
	}
}
