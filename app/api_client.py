from __future__ import annotations

from typing import Any
from urllib.parse import urlparse

import httpx


EXPECTED_SERVICE_NAME = "alerta-dos-notebooks-api"
DEFAULT_SEARCH_CONFIG_PATH = "/api/v1/search-configs/default"


class ApiClientError(Exception):
    """User-safe error raised when the API health check fails."""


def _build_api_url(api_base_url: str, path: str) -> str:
    base_url = api_base_url.strip().rstrip("/")
    if not base_url:
        raise ApiClientError("Informe a URL da API.")

    parsed = urlparse(base_url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ApiClientError("Informe uma URL valida, iniciando com http:// ou https://.")

    return f"{base_url}/{path.lstrip('/')}"


def _auth_headers(auth_token: str) -> dict[str, str]:
    headers = {}
    token = auth_token.strip()
    if token:
        headers["Authorization"] = f"Bearer {token}"

    return headers


def _get_json(api_base_url: str, path: str, auth_token: str = "", timeout: float = 5.0) -> dict[str, Any]:
    url = _build_api_url(api_base_url, path)

    try:
        response = httpx.get(url, headers=_auth_headers(auth_token), timeout=timeout)
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

    return data


def check_health(api_base_url: str, auth_token: str = "", timeout: float = 5.0) -> dict[str, Any]:
    data = _get_json(api_base_url, "/health", auth_token, timeout)

    if data.get("status") != "ok" or data.get("service") != EXPECTED_SERVICE_NAME:
        raise ApiClientError("Servidor respondeu, mas nao parece ser a API esperada.")

    return data


def fetch_default_search_config(
    api_base_url: str,
    auth_token: str = "",
    timeout: float = 5.0,
) -> dict[str, Any]:
    return _get_json(api_base_url, DEFAULT_SEARCH_CONFIG_PATH, auth_token, timeout)
