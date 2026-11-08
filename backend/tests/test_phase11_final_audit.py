from app.phase11_final_audit import run_phase11_final_audit


def _status_inputs():
    return (
        {"running": True, "connected": True, "last_error": None},
        {"running": True, "last_error": None},
        {"active": True, "last_error": None},
    )


def test_structural_audit_checks_existing_operational_contracts():
    result = run_phase11_final_audit()
    assert result["failed_count"] == 0
    assert result["scope"]["structural_contracts"] is True
    assert result["execution_allowed"] is False


def test_missing_runtime_telemetry_is_not_misreported_as_success():
    result = run_phase11_final_audit()
    assert result["status"] == "incomplete"
    assert result["not_run_count"] == 3
    assert result["scope"]["runtime_readiness_certified"] is False


def test_healthy_supplied_runtime_telemetry_completes_audit():
    price, signal, paper = _status_inputs()
    result = run_phase11_final_audit(
        live_price_status=price,
        live_signal_status=signal,
        paper_status=paper,
    )
    assert result["status"] == "passed"
    assert result["blocked_count"] == 0
    assert result["not_run_count"] == 0


def test_disconnected_market_feed_blocks_runtime_audit():
    price, signal, paper = _status_inputs()
    price["connected"] = False
    result = run_phase11_final_audit(
        live_price_status=price,
        live_signal_status=signal,
        paper_status=paper,
    )
    assert result["status"] == "incomplete"
    assert result["blocked_count"] == 1
    assert any(x["name"] == "live_price_runtime" and x["status"] == "blocked" for x in result["checks"])


def test_runtime_error_blocks_audit():
    price, signal, paper = _status_inputs()
    signal["last_error"] = "database unavailable"
    result = run_phase11_final_audit(
        live_price_status=price,
        live_signal_status=signal,
        paper_status=paper,
    )
    assert result["blocked_count"] == 1


def test_paper_automation_must_be_active_for_runtime_pass():
    price, signal, paper = _status_inputs()
    paper["active"] = False
    result = run_phase11_final_audit(
        live_price_status=price,
        live_signal_status=signal,
        paper_status=paper,
    )
    assert result["blocked_count"] == 1


def test_audit_never_enables_exchange_execution():
    price, signal, paper = _status_inputs()
    result = run_phase11_final_audit(
        live_price_status=price,
        live_signal_status=signal,
        paper_status=paper,
    )
    assert result["execution_allowed"] is False
    assert result["scope"]["exchange_orders_submitted"] is False


def test_schema_contracts_are_reported():
    result = run_phase11_final_audit()
    schema_checks = [x for x in result["checks"] if x["name"].startswith("schema_contract_")]
    assert len(schema_checks) == 4
    assert all(x["status"] == "passed" for x in schema_checks)
