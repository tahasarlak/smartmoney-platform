from __future__ import annotations
import hashlib
import os
from cryptography.fernet import Fernet, InvalidToken

class CredentialVaultError(RuntimeError):
    pass

def _fernet() -> Fernet:
    key = os.getenv("TRADF_CREDENTIAL_ENCRYPTION_KEY", "").strip()
    if not key:
        raise CredentialVaultError("TRADF_CREDENTIAL_ENCRYPTION_KEY is not configured")
    try:
        return Fernet(key.encode("ascii"))
    except Exception as exc:
        raise CredentialVaultError("TRADF_CREDENTIAL_ENCRYPTION_KEY is invalid") from exc

def encrypt_secret(value: str) -> str:
    if not value or len(value) > 512:
        raise ValueError("Credential value is empty or too long")
    return _fernet().encrypt(value.encode("utf-8")).decode("ascii")

def decrypt_secret(value: str) -> str:
    try:
        return _fernet().decrypt(value.encode("ascii")).decode("utf-8")
    except (InvalidToken, ValueError, UnicodeError) as exc:
        raise CredentialVaultError("Stored credential cannot be decrypted; rotate the key or re-enter credentials") from exc

def key_fingerprint(api_key: str) -> str:
    return hashlib.sha256(api_key.encode("utf-8")).hexdigest()[:12]

def vault_ready() -> bool:
    try:
        _fernet()
        return True
    except CredentialVaultError:
        return False
