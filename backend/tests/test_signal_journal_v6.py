import uuid
import pytest

from app import signal_journal as journal
from app import v11_platform as v11

from sqlalchemy import delete
from app.database import session_scope
from app.db_models import Signal, User


@pytest.fixture(autouse=True)
def cleanup_test_signals_and_users(monkeypatch):
    created_signal_ids = []
    created_user_ids = []
    original_create = journal.create_signal
    original_register = v11.register_user

    def tracked_create(*args, **kwargs):
        result = original_create(*args, **kwargs)
        created_signal_ids.append(result["id"])
        return result

    def tracked_register(*args, **kwargs):
        result = original_register(*args, **kwargs)
        created_user_ids.append(result["id"])
        return result

    monkeypatch.setattr(journal, "create_signal", tracked_create)
    monkeypatch.setattr(v11, "register_user", tracked_register)

    yield

    with session_scope() as db:
        if created_signal_ids:
            db.execute(delete(Signal).where(Signal.id.in_(created_signal_ids)))
        if created_user_ids:
            db.execute(delete(User).where(User.id.in_(created_user_ids)))



def unique_symbol():
    return "T" + uuid.uuid4().hex[:10].upper()


def plan(direction="bullish", symbol=None):
    if direction == "bullish":
        entry, stop, tps = 100, 98, [102, 104, 106]
        current_price = 105
    else:
        entry, stop, tps = 100, 102, [98, 96, 94]
        current_price = 95

    return {
        "symbol": symbol or unique_symbol(),
        "status": "pending_retest",
        "direction": direction,
        "setup_class": "aligned",
        "quality_score": 70,
        "entry": entry,
        "stop_loss": stop,
        "take_profits": [{"price": x} for x in tps],
        "zone": {"low": 99, "high": 101},
        "minimum_rr_requested": 2,
        "risk_percent_setting": 0.5,
        "current_price": current_price,
        "execution_allowed": False,
    }


def test_create_signal_persists_and_logs_event():
    saved = journal.create_signal(plan())

    assert saved["status"] == "WAITING_ENTRY"
    assert saved["id"]
    assert saved["symbol"]

    events = journal.signal_events(saved["id"])
    assert len(events) == 1

    fetched = journal.get_signal(saved["id"])
    assert fetched["symbol"] == saved["symbol"]


def test_bullish_lifecycle_entry_tp1_tp2_tp3():
    saved = journal.create_signal(plan())
    sid = saved["id"]

    assert journal.update_signal_price(sid, 99.5)["status"] == "OPEN"
    assert journal.update_signal_price(sid, 102)["status"] == "TP1_HIT"
    assert journal.update_signal_price(sid, 104)["status"] == "TP2_HIT"
    assert journal.update_signal_price(sid, 106)["status"] == "TP3_HIT"

    assert len(journal.signal_events(sid)) == 5


def test_bearish_lifecycle_stop_loss():
    saved = journal.create_signal(plan("bearish"))
    sid = saved["id"]

    assert journal.update_signal_price(sid, 100.5)["status"] == "OPEN"
    assert journal.update_signal_price(sid, 102.1)["status"] == "STOPPED"


def test_rejects_invalid_plan_and_nonpositive_price():
    invalid_plan = plan()
    invalid_plan["execution_allowed"] = True

    with pytest.raises(ValueError):
        journal.create_signal(invalid_plan)

    saved = journal.create_signal(plan())

    with pytest.raises(ValueError):
        journal.update_signal_price(saved["id"], 0)


def test_list_filters_by_symbol():
    target_symbol = unique_symbol()
    other_symbol = unique_symbol()

    target = journal.create_signal(plan(symbol=target_symbol))
    journal.create_signal(plan(symbol=other_symbol))

    results = journal.list_signals(symbol=target_symbol)

    assert len(results) == 1
    assert results[0]["id"] == target["id"]
    assert results[0]["symbol"] == target_symbol

    other_results = journal.list_signals(symbol=other_symbol)

    assert len(other_results) == 1
    assert other_results[0]["symbol"] == other_symbol


def test_price_gap_can_reach_tp3_in_one_update():
    saved = journal.create_signal(plan())

    journal.update_signal_price(saved["id"], 99.5)
    updated = journal.update_signal_price(saved["id"], 106)

    assert updated["status"] == "TP3_HIT"
    assert updated["closed_at"] is not None


def test_price_update_rejects_nan_and_infinity():
    saved = journal.create_signal(plan())

    for value in (float("nan"), float("inf"), float("-inf")):
        with pytest.raises(ValueError):
            journal.update_signal_price(saved["id"], value)


def test_private_signal_requires_owner():
    with pytest.raises(ValueError):
        journal.create_signal(plan(), visibility="private")


def test_private_signal_is_not_visible_to_other_users():
    owner = v11.register_user(
        f"private-owner-{uuid.uuid4().hex[:12]}@example.com",
        "correct-horse-battery",
    )["id"]

    saved = journal.create_signal(
        plan(),
        user_id=owner,
        visibility="private",
    )

    assert journal.get_signal(saved["id"], user_id=owner) is not None
    assert journal.get_signal(saved["id"], user_id=str(uuid.uuid4())) is None
    assert journal.get_signal(saved["id"]) is None


def test_internal_price_monitor_can_update_private_signal():
    owner = v11.register_user(
        f"private-monitor-{uuid.uuid4().hex[:12]}@example.com",
        "correct-horse-battery",
    )["id"]
    saved = journal.create_signal(plan(), user_id=owner, visibility="private")

    assert journal.update_signal_price(
        saved["id"], 99.5, include_private=True
    )["status"] == "OPEN"
    assert journal.get_signal(saved["id"], user_id=owner)["status"] == "OPEN"
