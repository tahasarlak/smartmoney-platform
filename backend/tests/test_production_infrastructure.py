import hashlib
import hmac
from urllib.parse import parse_qs
import pytest
from cryptography.fernet import Fernet
import asyncio
import httpx
from app.production_security import encrypt_secret, decrypt_secret, key_fingerprint, CredentialVaultError
from app.production_exchange import BinanceSpotTestnet, BINANCE_SPOT_TESTNET_BASE, ExchangeTestnetError
from app.production_infrastructure import _global_kill_enabled, _user_kill_enabled

def test_vault_encrypts_and_decrypts(monkeypatch):
    monkeypatch.setenv("TRADF_CREDENTIAL_ENCRYPTION_KEY", Fernet.generate_key().decode())
    encrypted=encrypt_secret("test-secret-value")
    assert encrypted != "test-secret-value"
    assert decrypt_secret(encrypted)=="test-secret-value"

def test_vault_fails_closed_without_key(monkeypatch):
    monkeypatch.delenv("TRADF_CREDENTIAL_ENCRYPTION_KEY",raising=False)
    with pytest.raises(CredentialVaultError): encrypt_secret("secret")

def test_vault_rejects_tampered_ciphertext(monkeypatch):
    monkeypatch.setenv("TRADF_CREDENTIAL_ENCRYPTION_KEY", Fernet.generate_key().decode())
    encrypted=encrypt_secret("secret")
    with pytest.raises(CredentialVaultError): decrypt_secret(encrypted[:-4]+"xxxx")

def test_fingerprint_is_short_non_reversible_identifier():
    assert key_fingerprint("example-api-key") == hashlib.sha256(b"example-api-key").hexdigest()[:12]

def test_exchange_adapter_is_testnet_only():
    assert BINANCE_SPOT_TESTNET_BASE == "https://testnet.binance.vision"
    assert "api.binance.com" not in BINANCE_SPOT_TESTNET_BASE

def test_signed_query_uses_hmac_sha256(monkeypatch):
    monkeypatch.setattr("app.production_exchange.time.time",lambda: 1000)
    adapter=BinanceSpotTestnet("key","secret")
    query=adapter._signed_query({"symbol":"BTCUSDT","side":"BUY"})
    parts=parse_qs(query)
    signature=parts.pop("signature")[0]
    unsigned="symbol=BTCUSDT&side=BUY&timestamp=1000000&recvWindow=5000"
    assert signature==hmac.new(b"secret",unsigned.encode(),hashlib.sha256).hexdigest()

def test_global_kill_switch_defaults_enabled(monkeypatch):
    monkeypatch.delenv("TRADF_GLOBAL_KILL_SWITCH",raising=False)
    assert _global_kill_enabled() is True

def test_global_kill_switch_env_override_false_still_fails_closed_without_database(monkeypatch):
    monkeypatch.setenv("TRADF_GLOBAL_KILL_SWITCH","false")
    assert _global_kill_enabled() is True

def test_global_kill_switch_can_be_resumed_only_by_database_record(monkeypatch):
    monkeypatch.setenv("TRADF_GLOBAL_KILL_SWITCH","false")
    class Row:
        enabled=False
    class DB:
        def get(self,*_): return Row()
    assert _global_kill_enabled(DB()) is False

def test_user_kill_switch_defaults_enabled():
    class DB:
        def get(self,*_): return None
    assert _user_kill_enabled(DB(),"user-id") is True


def test_testnet_account_verification_uses_testnet_host_and_checks_permissions():
    async def handler(request):
        assert request.url.host == "testnet.binance.vision"
        assert request.url.path == "/api/v3/account"
        assert request.headers["X-MBX-APIKEY"] == "public-test-key"
        return httpx.Response(200,json={"canTrade":True,"canWithdraw":False,"accountType":"SPOT","balances":[]})
    adapter=BinanceSpotTestnet("public-test-key","private-test-secret",transport=httpx.MockTransport(handler))
    result=asyncio.run(adapter.verify_account())
    assert result["can_trade"] is True
    assert result["can_withdraw"] is False

def test_testnet_account_verification_rejects_withdrawal_permission():
    async def handler(request):
        return httpx.Response(200,json={"canTrade":True,"canWithdraw":True,"balances":[]})
    adapter=BinanceSpotTestnet("key","secret",transport=httpx.MockTransport(handler))
    with pytest.raises(ExchangeTestnetError) as err:
        asyncio.run(adapter.verify_account())
    assert err.value.code == "WITHDRAWAL_PERMISSION_ENABLED" or err.value.code == "WITHDRAWAL_PERMISSION_UNVERIFIED"

def test_invalid_decimal_order_is_rejected_without_network():
    adapter=BinanceSpotTestnet("key","secret")
    with pytest.raises(ValueError):
        asyncio.run(adapter.place_limit_order(symbol="BTCUSDT",side="BUY",quantity="nope",price="1",client_order_id="clientid123"))


def test_execution_gate_uses_global_and_user_advisory_locks():
    from app.production_infrastructure import _acquire_execution_locks
    class FakeDB:
        def __init__(self): self.calls=[]
        def execute(self,statement,params): self.calls.append((str(statement),params))
    fake=FakeDB()
    _acquire_execution_locks(fake,"user-123")
    assert len(fake.calls)==2
    assert all("pg_advisory_xact_lock" in call[0] for call in fake.calls)
    assert fake.calls[0][1]["lock_id"]==0
    assert fake.calls[1][1]["lock_id"]!=0

def test_limit_order_schema_rejects_non_decimal_values():
    from app.production_infrastructure import LimitOrderCreate
    with pytest.raises(Exception):
        LimitOrderCreate(credential_id="c",portfolio_id="p",symbol="BTCUSDT",side="BUY",
            quantity="NaN",price="100",client_request_id="request-123",confirm_testnet_only=True)

def test_limit_order_schema_accepts_positive_decimal_strings():
    from app.production_infrastructure import LimitOrderCreate
    value=LimitOrderCreate(credential_id="c",portfolio_id="p",symbol="BTCUSDT",side="BUY",
        quantity="0.00100",price="60000.00",client_request_id="request-123",confirm_testnet_only=True)
    assert value.quantity=="0.001"
    assert value.price=="60000"
