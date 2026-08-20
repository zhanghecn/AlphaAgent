package config

import (
	"testing"
	"time"
)

func TestLoadRequiresAdminPassword(t *testing.T) {
	t.Setenv("AUTH_REQUIRED", "true")
	t.Setenv("ADMIN_PASSWORD", "")
	t.Setenv("JWT_SECRET", "long-enough-secret-32-bytes-padding!!!")
	if _, err := Load(); err == nil {
		t.Error("expected error when ADMIN_PASSWORD empty")
	}
}

func TestLoadRequiresJWTSecretLength(t *testing.T) {
	t.Setenv("AUTH_REQUIRED", "true")
	t.Setenv("ADMIN_PASSWORD", "pw")
	t.Setenv("JWT_SECRET", "short")
	if _, err := Load(); err == nil {
		t.Error("expected error when JWT_SECRET too short")
	}
}

func TestLoadValid(t *testing.T) {
	t.Setenv("AUTH_REQUIRED", "true")
	t.Setenv("ADMIN_PASSWORD", "pw")
	t.Setenv("JWT_SECRET", "long-enough-secret-32-bytes-padding!!!")
	t.Setenv("GATEWAY_PORT", "9090")
	cfg, err := Load()
	if err != nil {
		t.Fatalf("load: %v", err)
	}
	if cfg.GatewayAddr != ":9090" {
		t.Errorf("addr = %q, want :9090", cfg.GatewayAddr)
	}
	if cfg.TokenTTL != 24*time.Hour {
		t.Errorf("ttl = %v, want 24h", cfg.TokenTTL)
	}
	if cfg.AdminUsername != "admin" {
		t.Errorf("username = %q, want admin", cfg.AdminUsername)
	}
	if !cfg.OperatorAuthEnabled {
		t.Error("OperatorAuthEnabled = false, want true")
	}
}

func TestLoadAllowsAnonymousModeWithoutCredentials(t *testing.T) {
	t.Setenv("AUTH_REQUIRED", "false")
	t.Setenv("ADMIN_PASSWORD", "")
	t.Setenv("JWT_SECRET", "")

	cfg, err := Load()
	if err != nil {
		t.Fatalf("anonymous mode should not require credentials: %v", err)
	}
	if cfg.AuthRequired {
		t.Error("AuthRequired = true, want false")
	}
	if cfg.OperatorAuthEnabled {
		t.Error("OperatorAuthEnabled = true, want false")
	}
}

func TestLoadAnonymousModeEnablesOperatorWritesWhenCredentialsConfigured(t *testing.T) {
	t.Setenv("AUTH_REQUIRED", "false")
	t.Setenv("ADMIN_PASSWORD", "pw")
	t.Setenv("JWT_SECRET", "long-enough-secret-32-bytes-padding!!!")

	cfg, err := Load()
	if err != nil {
		t.Fatalf("load: %v", err)
	}
	if !cfg.OperatorAuthEnabled {
		t.Error("OperatorAuthEnabled = false, want true")
	}
}

func TestLoadRejectsPartialOperatorCredentials(t *testing.T) {
	t.Setenv("AUTH_REQUIRED", "false")
	t.Setenv("ADMIN_PASSWORD", "pw")
	t.Setenv("JWT_SECRET", "")
	if _, err := Load(); err == nil {
		t.Error("expected error for partial operator credentials")
	}
}

func TestGetEnvDuration(t *testing.T) {
	cases := []struct {
		in   string
		want time.Duration
	}{
		{"24h", 24 * time.Hour},
		{"30m", 30 * time.Minute},
		{"3600", 3600 * time.Second},
		{"", 24 * time.Hour}, // 空值取默认
	}
	for _, c := range cases {
		t.Run(c.in, func(t *testing.T) {
			t.Setenv("JWT_TOKEN_TTL", c.in)
			if got := getEnvDuration("JWT_TOKEN_TTL", 24*time.Hour); got != c.want {
				t.Errorf("getEnvDuration(%q) = %v, want %v", c.in, got, c.want)
			}
		})
	}
}
