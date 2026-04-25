from __future__ import annotations

from typing import Any
from urllib.parse import urlparse

import httpx


EXPECTED_SERVICE_NAME = "alerta-dos-notebooks-api"


class ApiClientError(Exception):
    """User-safe error raised when the API health check fails."""


def _build_health_url(api_base_url: str) -> str:
    base_url = api_base_url.strip().rstrip("/")
    if not base_url:
        raise ApiClientError("Informe a URL da API.")

    parsed = urlparse(base_url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ApiClientError("Informe uma URL valida, iniciando com http:// ou https://.")

    return f"{base_url}/health"


def check_health(api_base_url: str, auth_token: str = "", timeout: float = 5.0) -> dict[str, Any]:
    health_url = _build_health_url(api_base_url)
    headers = {}

    token = auth_token.strip()
    if token:
        headers["Authorization"] = f"Bearer {token}"

    try:
        response = httpx.get(health_url, headers=headers, timeout=timeout)
        response.raise_for_status()
    except httpx.HTTPStatusError as exc:
        status_code = exc.response.status_code
        raise ApiClientError(f"Servidor respondeu com status HTTP {status_code}.") from exc
    except httpx.TimeoutException as exc:
        raise ApiClientError("Tempo esgotado ao tentar conectar ao servidor.") from exc
    except httpx.RequestError as exc:
        raise ApiClientError("Nao foi possivel conectar ao servidor. Verifique a URL da API.") from exc

    try:
        data = response.json()
    except ValueError as exc:
        raise ApiClientError("Servidor respondeu, mas nao retornou JSON valido.") from exc

    if not isinstance(data, dict):
        raise ApiClientError("Servidor respondeu em um formato inesperado.")

    if data.get("status") != "ok" or data.get("service") != EXPECTED_SERVICE_NAME:
        raise ApiClientError("Servidor respondeu, mas nao parece ser a API esperada.")

    return data
