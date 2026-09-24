"""Clave de la API de Claude, guardada en el almacén seguro del sistema.

En Windows es el Administrador de credenciales (cifrado con tu sesión de
Windows). La clave nunca se escribe en archivos del proyecto ni en config.json.
"""

from __future__ import annotations

import os

SERVICE = "UJISync"
ACCOUNT = "anthropic_api_key"


def _keyring():
    import keyring

    return keyring


def _safe(fn, default=None):
    # Algunos backends de keyring fallan con excepciones que no heredan de
    # Exception (p. ej. errores de extensiones nativas); nunca deben tumbar la app.
    try:
        return fn()
    except (KeyboardInterrupt, SystemExit):
        raise
    except BaseException:
        return default


def get_api_key() -> str | None:
    return _safe(lambda: _keyring().get_password(SERVICE, ACCOUNT))


def set_api_key(key: str) -> bool:
    return _safe(lambda: _keyring().set_password(SERVICE, ACCOUNT, key.strip()) or True, False)


def delete_api_key() -> None:
    _safe(lambda: _keyring().delete_password(SERVICE, ACCOUNT))


def has_credentials() -> bool:
    """Hay clave en el almacén seguro o en las variables de entorno del SDK."""
    return bool(
        os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("ANTHROPIC_AUTH_TOKEN") or get_api_key()
    )
