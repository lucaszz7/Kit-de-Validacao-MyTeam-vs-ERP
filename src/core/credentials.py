"""Gestão segura de credenciais com keyring + Fernet.

A chave de encriptação fica no Windows Credential Manager (keyring).
As credenciais encriptadas ficam também no Windows Credential Manager
sob a chave 'config_data' — nunca em ficheiro no disco.

Fluxo:
  1. save_secure_config() encripta a password com Fernet e guarda todo
     o JSON de config no Cofre do Windows (keyring)
  2. load_secure_config() lê do Cofre, desencripta a password
  3. Se o user desmarca "Guardar", clear_secure_config() + clear_key()
     apagam tudo do cofre
"""

import json

import keyring
from cryptography.fernet import Fernet

KEYRING_SERVICE = "KitValidacaoMyTeam"
KEYRING_USER = "fernet_key"
CONFIG_KEYRING_USER = "config_data"


def _get_key() -> bytes:
    """Busca a chave no Cofre do Windows. Se não existir, gera e guarda."""
    stored = keyring.get_password(KEYRING_SERVICE, KEYRING_USER)
    if stored:
        return stored.encode()
    new_key = Fernet.generate_key()
    keyring.set_password(KEYRING_SERVICE, KEYRING_USER, new_key.decode())
    return new_key


def encrypt_password(plain_password: str) -> str:
    """Encripta a password com AES-128 (Fernet). Devolve string base64."""
    if not plain_password:
        return ""
    return Fernet(_get_key()).encrypt(plain_password.encode()).decode()


def decrypt_password(encrypted_password: str) -> str:
    """Desencripta a password. Se falhar (chave inválida/apagada), devolve ''."""
    if not encrypted_password:
        return ""
    try:
        return Fernet(_get_key()).decrypt(encrypted_password.encode()).decode()
    except Exception:
        return ""


def clear_key() -> None:
    """Apaga a chave do Cofre do Windows (quando user desmarca 'Guardar')."""
    try:
        keyring.delete_password(KEYRING_SERVICE, KEYRING_USER)
    except keyring.errors.PasswordDeleteError:
        pass


def save_secure_config(config: dict) -> None:
    """Guarda toda a config no Cofre do Windows, password encriptada com Fernet."""
    to_store = dict(config)
    pwd = to_store.get("sql_server", {}).get("password", "")
    if pwd:
        to_store["sql_server"] = dict(to_store.get("sql_server", {}))
        to_store["sql_server"]["password"] = encrypt_password(pwd)
    keyring.set_password(
        KEYRING_SERVICE,
        CONFIG_KEYRING_USER,
        json.dumps(to_store, ensure_ascii=False),
    )


def load_secure_config() -> dict | None:
    """Lê a config do Cofre do Windows e desencripta a password."""
    stored = keyring.get_password(KEYRING_SERVICE, CONFIG_KEYRING_USER)
    if not stored:
        return None
    try:
        data = json.loads(stored)
    except (json.JSONDecodeError, TypeError):
        return None

    pwd = data.get("sql_server", {}).get("password", "")
    if pwd and data.get("save_credentials", False):
        decrypted = decrypt_password(pwd)
        if decrypted:
            data["sql_server"]["password"] = decrypted
        else:
            data["sql_server"]["password"] = ""
            data["save_credentials"] = False

    return data


def clear_secure_config() -> None:
    """Apaga a config do Cofre do Windows."""
    try:
        keyring.delete_password(KEYRING_SERVICE, CONFIG_KEYRING_USER)
    except keyring.errors.PasswordDeleteError:
        pass
