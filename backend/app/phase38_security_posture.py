"""Phase 38: authenticated account/security posture summary; no secrets exposed."""
from __future__ import annotations
from typing import Any

def build_security_posture(*, authenticated: bool, database_ok: bool,
                           tls_termination_expected: bool, secret_store_configured: bool,
                           api_key_withdrawals_disabled: bool,
                           user_isolation_verified: bool) -> dict[str, Any]:
    checks=[
        ("authenticated_session",authenticated),
        ("database_available",database_ok),
        ("tls_termination_expected",tls_termination_expected),
        ("secret_store_configured",secret_store_configured),
        ("exchange_key_withdrawals_disabled",api_key_withdrawals_disabled),
        ("tenant_isolation_verified",user_isolation_verified),
    ]
    rows=[{"name":name,"ok":bool(ok)} for name,ok in checks]
    missing=[x["name"] for x in rows if not x["ok"]]
    return {"status":"passed" if not missing else "review_required","checks":rows,
            "missing_controls":missing,"secrets_returned":False,"execution_allowed":False,
            "limitations":["This report does not perform a penetration test or independently inspect cloud-provider settings.",
                           "TLS, secret-store and exchange-key controls must be verified in the deployment and exchange consoles.",
                           "Tenant isolation requires dedicated integration tests across multiple real user accounts."]}
