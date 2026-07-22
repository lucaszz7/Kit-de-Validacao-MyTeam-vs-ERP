from core.credentials import (
    save_secure_config,
    load_secure_config,
    clear_secure_config,
    clear_key,
)


def load_config() -> dict:
    data = load_secure_config()
    if data is None:
        raise FileNotFoundError("Nenhuma configuração guardada no Cofre do Windows")
    return data


def save_config(data: dict) -> None:
    save_creds = data.get("save_credentials", False)

    if save_creds:
        save_secure_config(data)
    else:
        clear_secure_config()
        clear_key()
