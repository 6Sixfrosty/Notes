from __future__ import annotations

from typing import Any
from urllib.parse import urlparse

import httpx


EXPECTED_SERVICE_NAME = "alerta-dos-notebooks-api"
DEFAULT_SEARCH_CONFIG_PATH = "/api/v1/search-configs/default"
SYNC_STATUS_MESSAGES = {
    400: "JSON inv\u00e1lido.",
    401: "Token ausente ou expirado.",
    403: "Token inv\u00e1lido.",
    409: "Conflito de vers\u00e3o. Recarregue a configura\u00e7\u00e3o do servidor.",
    422: "Configura\u00e7\u00e3o inv\u00e1lida no servidor.",
    429: "Muitas requisi\u00e7\u00f5es. Tente novamente depois.",
    500: "Erro interno do servidor.",
}


class ApiClientError(Exception):
    """User-safe error raised when the API health check fails."""

    def __init__(self, message: str, *, status_code: int | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code


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


def _request_json(
    method: str,
    api_base_url: str,
    path: str,
    auth_token: str = "",
    timeout: float = 5.0,
    json_body: dict[str, Any] | None = None,
    status_messages: dict[int, str] | None = None,
    timeout_message: str = "Tempo esgotado ao tentar conectar ao servidor.",
    request_error_message: str = "Nao foi possivel conectar ao servidor. Verifique a URL da API.",
) -> dict[str, Any]:
    url = _build_api_url(api_base_url, path)

    try:
        response = httpx.request(
            method,
            url,
            headers=_auth_headers(auth_token),
            json=json_body,
            timeout=timeout,
        )
        response.raise_for_status()
    except httpx.HTTPStatusError as exc:
        status_code = exc.response.status_code
        message = (
            status_messages.get(status_code)
            if status_messages is not None
            else f"Servidor respondeu com status HTTP {status_code}."
        )
        raise ApiClientError(message, status_code=status_code) from exc
    except httpx.TimeoutException as exc:
        raise ApiClientError(timeout_message) from exc
    except httpx.RequestError as exc:
        raise ApiClientError(request_error_message) from exc

    try:
        data = response.json()
    except ValueError as exc:
        raise ApiClientError("Servidor respondeu, mas nao retornou JSON valido.") from exc

    if not isinstance(data, dict):
        raise ApiClientError("Servidor respondeu em um formato inesperado.")

    return data


def _get_json(api_base_url: str, path: str, auth_token: str = "", timeout: float = 5.0) -> dict[str, Any]:
    return _request_json("GET", api_base_url, path, auth_token, timeout)


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


def sync_default_search_config(
    api_base_url: str,
    auth_token: str,
    current_config: dict[str, Any],
    timeout: float = 10.0,
) -> dict[str, Any]:
    return _request_json(
        "PUT",
        api_base_url,
        DEFAULT_SEARCH_CONFIG_PATH,
        auth_token,
        timeout,
        json_body=current_config,
        status_messages=SYNC_STATUS_MESSAGES,
        timeout_message="Tempo de conex\u00e3o excedido.",
        request_error_message="Servidor indispon\u00edvel. Configura\u00e7\u00e3o mantida localmente.",
    )
