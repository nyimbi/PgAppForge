# Security Policy

## Supported Versions

| Version | Supported |
|---------|-----------|
| 0.90.x  | Yes    |
| < 0.90  | No     |

## Reporting a Vulnerability

**Please do not file public GitHub issues for security vulnerabilities.**

Report security issues privately by email to **nyimbi+pgaf@gmail.com** with subject line:
`[SECURITY] pgappforge - <brief description>`

Please include:
- pgappforge version (`import pgappforge; print(pgappforge.__version__)`)
- Python version and OS
- Description of the vulnerability
- Steps to reproduce
- Potential impact assessment
- Suggested fix (if any)

## Response Timeline

- **Acknowledgement**: within 48 hours
- **Assessment**: within 7 days
- **Fix + release**: within 30 days for critical, 90 days for moderate
- **Public disclosure**: coordinated after fix is released

## Scope

**In scope:**
- Authentication and authorization (session handling, permission checks, CSRF)
- Code generator output (XSS in generated views, SQL injection)
- Plugin security (audit trail, integration hub credential handling, webhook signature verification)
- Template system (DDL injection via `_qi()` identifier safety)
- REST API (input validation, `ModelRestApi` endpoints)

**Out of scope:**
- Vulnerabilities in Flask, SQLAlchemy, or other upstream dependencies (report to them directly)
- Issues requiring physical access to the server
- Social engineering attacks
- Denial of service attacks
