import os
from pathlib import Path
import pytest

from app import signal_journal as journal

@pytest.fixture
def temp_db(tmp_path, monkeypatch):
    db=tmp_path/"signals.sqlite3"
    monkeypatch.setenv("TRADE_JOURNAL_DB",str(db))
    journal.init_db()
    return db

def plan(direction="bullish"):
    if direction=="bullish":
        entry,stop,tps=100,98,[102,104,106]
    else:
        entry,stop,tps=100,102,[98,96,94]
    return {"symbol":"TESTUSDT","status":"pending_retest","direction":direction,
            "setup_class":"aligned","quality_score":70,"entry":entry,"stop_loss":stop,
            "take_profits":[{"price":x} for x in tps],"zone":{"low":99,"high":101},
            "minimum_rr_requested":2,"risk_percent_setting":0.5,
            "current_price":105 if direction=="bullish" else 95,
            "execution_allowed":False}

def test_create_signal_persists_and_logs_event(temp_db):
    saved=journal.create_signal(plan())
    assert saved["status"]=="WAITING_ENTRY"
    assert saved["id"]
    assert len(journal.signal_events(saved["id"]))==1
    assert journal.get_signal(saved["id"])["symbol"]=="TESTUSDT"

def test_bullish_lifecycle_entry_tp1_tp2_tp3(temp_db):
    s=journal.create_signal(plan())
    sid=s["id"]
    assert journal.update_signal_price(sid,99.5)["status"]=="OPEN"
    assert journal.update_signal_price(sid,102)["status"]=="TP1_HIT"
    assert journal.update_signal_price(sid,104)["status"]=="TP2_HIT"
    assert journal.update_signal_price(sid,106)["status"]=="TP3_HIT"
    assert len(journal.signal_events(sid))==5

def test_bearish_lifecycle_stop_loss(temp_db):
    s=journal.create_signal(plan("bearish"))
    sid=s["id"]
    assert journal.update_signal_price(sid,100.5)["status"]=="OPEN"
    assert journal.update_signal_price(sid,102.1)["status"]=="STOPPED"

def test_rejects_invalid_plan_and_nonpositive_price(temp_db):
    p=plan()
    p["execution_allowed"]=True
    with pytest.raises(ValueError): journal.create_signal(p)
    s=journal.create_signal(plan())
    with pytest.raises(ValueError): journal.update_signal_price(s["id"],0)

def test_list_filters_by_symbol(temp_db):
    journal.create_signal(plan())
    assert len(journal.list_signals(symbol="TESTUSDT"))==1
    assert len(journal.list_signals(symbol="OTHERUSDT"))==0


def test_price_gap_can_reach_tp3_in_one_update(temp_db):
    s=journal.create_signal(plan())
    journal.update_signal_price(s["id"],99.5)
    updated=journal.update_signal_price(s["id"],106)
    assert updated["status"]=="TP3_HIT"
    assert updated["closed_at"] is not None


def test_price_update_rejects_nan_and_infinity(temp_db):
    s=journal.create_signal(plan())
    for value in (float("nan"), float("inf"), float("-inf")):
        with pytest.raises(ValueError):
            journal.update_signal_price(s["id"],value)
