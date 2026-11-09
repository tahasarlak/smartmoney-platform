# Independent Security Audit — Required Work, Not Self-Certification

TRADF's in-repository checks are engineering controls and automated scans. They are not an independent audit.

## Required external scope

1. Threat model: account takeover, credential theft, cross-tenant access, replay, duplicate orders, API abuse, SSRF, scheduler abuse, denial of service and exchange API misuse.
2. Source review: authentication/session handling, authorization, credential encryption, key rotation, order idempotency, kill switch, audit trail and error handling.
3. Infrastructure review: Render service access, environment secrets, Neon roles/backup, TLS, network egress, logs, CI permissions and deployment pipeline.
4. Manual penetration test: authenticated and unauthenticated API tests, tenant isolation, IDOR, injection, rate limiting, CSRF/CORS, session revocation and privilege escalation.
5. Exchange testnet review: least-privilege API key, withdrawal disabled, order placement/cancellation, partial fills, timeout reconciliation and emergency stop.
6. Resilience review: worker restart, lease expiry, duplicate worker concurrency, DB outage, exchange outage, key rotation and restore-from-backup.
7. Remediation retest and signed report.

## Evidence to retain

- commit SHA and dependency lock/snapshot;
- CI output for unit tests, Bandit, pip-audit and Gitleaks;
- migration and schema report;
- key generation and rotation procedure;
- testnet order/cancel evidence;
- kill-switch activation and cancellation-failure evidence;
- 21-day paper observation report;
- backup restore evidence;
- external penetration-test report and remediation retest.

## Release decision

No live-capital release is authorized by the code in this bundle. A qualified independent reviewer must assess the deployed system and sign off on remediation before live trading is even considered.
