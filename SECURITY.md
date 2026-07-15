# Security Policy

## Supported Versions

| Version | Supported |
|---------|-----------|
| 0.5.x   | Yes       |
| < 0.5   | No        |

## Reporting a Vulnerability

Provena is a security-sensitive library (context governance, tamper-evident audit trails). We take security reports seriously.

**Do NOT open a public GitHub issue for security vulnerabilities.**

Instead, please report vulnerabilities through GitHub's private security advisory feature:

1. Go to https://github.com/rajfirke/provena/security/advisories
2. Click "New draft security advisory"
3. Fill in the details

You can expect:
- **Acknowledgment** within 48 hours
- **Assessment** within 1 week
- **Fix or mitigation** within 2 weeks for confirmed vulnerabilities

## Scope

The following are in scope for security reports:

- Hash chain integrity bypass (ways to tamper without detection)
- SQLite injection or data corruption
- HMAC key leakage or signing bypass
- Audit trail data loss or silent truncation
- Dependencies with known CVEs

## Out of Scope

- The hash chain without HMAC signing is designed to detect tampering, not prevent it (this is documented). An attacker with file access can rebuild the chain — use HMAC signing for stronger guarantees.
- Content is hashed, not encrypted. Provena does not provide data-at-rest encryption.
