package auth

import "testing"

func TestVerifySecret(t *testing.T) {
	cases := []struct {
		name        string
		input       string
		expected    string
		shouldMatch bool
	}{
		{"identical", "admin", "admin", true},
		{"case-sensitive", "admin", "Admin", false},
		{"different", "admin", "root", false},
		{"both-empty", "", "", true},
		{"input-empty", "", "x", false},
		{"expected-empty", "x", "", false},
		{"long-password", "a-very-long-and-complex-p@ssw0rd!", "a-very-long-and-complex-p@ssw0rd!", true},
	}
	for _, c := range cases {
		t.Run(c.name, func(t *testing.T) {
			got := VerifySecret(c.input, c.expected)
			if got != c.shouldMatch {
				t.Errorf("VerifySecret(%q,%q) = %v, want %v", c.input, c.expected, got, c.shouldMatch)
			}
		})
	}
}
