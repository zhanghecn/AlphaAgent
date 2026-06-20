package auth

import (
	"crypto/sha256"
	"crypto/subtle"
)

// VerifySecret 对 input 与 expected 先各自做 SHA-256，再做常量时间比较。
// 先哈希可避免因明文长度差异带来的时序旁路泄漏，用于用户名/密码校验。
func VerifySecret(input, expected string) bool {
	hi := sha256.Sum256([]byte(input))
	he := sha256.Sum256([]byte(expected))
	return subtle.ConstantTimeCompare(hi[:], he[:]) == 1
}
