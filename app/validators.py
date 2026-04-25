from __future__ import annotations

import re
import unicodedata
from collections.abc import Mapping, Sequence
from typing import Any
from urllib.parse import urlparse


class ValidationError(ValueError):
    """Raised with a user-safe validation message."""


MESSAGE_QUERY_KEYS = (
    "query",
    "message",
    "mensagem",
    "mensagem_chave",
    "keyword",
)
MESSAGE_ID_KEYS = ("id", "message_id", "mensagem_id")
MESSAGE_LIST_KEYS = ("messages", "mensagens")
COLLECTION_FIELD_KEYS = (
    "collection_fields",
    "campos_coleta",
    "fields",
    "coleta",
)


def _has_control_char(value: str) -> bool:
    return any(unicodedata.category(character) == "Cc" for character in value)


def _normalize_duplicate_spaces(value: str) -> str:
    return re.sub(r" {2,}", " ", value.strip())


def _first_existing_key(data: Mapping[str, Any], keys: Sequence[str]) -> str | None:
    for key in keys:
        if key in data:
            return key
    return None


def _read_first_value(data: Mapping[str, Any], keys: Sequence[str]) -> tuple[str | None, Any]:
    key = _first_existing_key(data, keys)
    if key is None:
        return None, None
    return key, data.get(key)


def _is_enabled(value: Any, *, default: bool = False) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return default
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "sim", "yes", "on"}
    return bool(value)


def validate_api_url(api_base_url: str, *, production: bool = False) -> str:
    value = str(api_base_url or "").strip().rstrip("/")

    if not value:
        raise ValidationError("Informe a URL da API.")

    if _has_control_char(value) or any(character.isspace() for character in value):
        raise ValidationError("A URL da API nao pode conter espacos ou quebras de linha.")

    parsed = urlparse(value)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValidationError("Informe uma URL valida, iniciando com http:// ou https://.")

    if production and parsed.scheme != "https":
        raise ValidationError("Em producao, a URL da API deve iniciar com https://.")

    return value


def validate_token(auth_token: str) -> str:
    value = str(auth_token or "").strip()

    if not value:
        raise ValidationError("Informe o token de autenticacao.")

    if _has_control_char(value):
        raise ValidationError("O token nao pode conter quebras de linha.")

    if len(value) < 10:
        raise ValidationError("O token deve ter pelo menos 10 caracteres.")

    return value


def validate_message_key(message_key: str) -> str:
    value = str(message_key or "")

    if _has_control_char(value):
        raise ValidationError("A mensagem-chave nao pode conter caracteres de controle.")

    value = _normalize_duplicate_spaces(value)

    if not value:
        raise ValidationError("Informe a mensagem-chave.")

    if len(value) < 2:
        raise ValidationError("A mensagem-chave deve ter pelo menos 2 caracteres.")

    if len(value) > 200:
        raise ValidationError("A mensagem-chave deve ter no maximo 200 caracteres.")

    return value


def validate_message_list(messages: Sequence[Any]) -> list[Any]:
    if isinstance(messages, (str, bytes)) or not isinstance(messages, Sequence):
        raise ValidationError("A lista de mensagens deve ser uma lista.")

    normalized_messages: list[Any] = []

    for index, message in enumerate(messages, start=1):
        if isinstance(message, Mapping):
            query_key, query = _read_first_value(message, MESSAGE_QUERY_KEYS)
            if query_key is None:
                raise ValidationError(f"A mensagem {index} precisa ter uma query.")

            normalized_message = dict(message)
            normalized_message[query_key] = validate_message_key(query)
            normalized_messages.append(normalized_message)
            continue

        normalized_messages.append(validate_message_key(message))

    return normalized_messages


def validate_collection_regex(pattern: str) -> str:
    value = str(pattern or "").strip()

    if not value:
        raise ValidationError("Informe a regex de coleta.")

    if len(value) > 300:
        raise ValidationError("A regex de coleta deve ter no maximo 300 caracteres.")

    try:
        re.compile(value)
    except re.error as exc:
        raise ValidationError(f"Regex de coleta invalida: {exc.msg}.") from exc

    return value


def _message_id(message: Any) -> Any:
    if not isinstance(message, Mapping):
        return None

    _, value = _read_first_value(message, MESSAGE_ID_KEYS)
    return value


def _message_query(message: Any) -> str:
    if isinstance(message, Mapping):
        _, value = _read_first_value(message, MESSAGE_QUERY_KEYS)
        return str(value or "")

    return str(message or "")


def _message_enabled(message: Any) -> bool:
    if not isinstance(message, Mapping):
        return True

    return _is_enabled(message.get("enabled"), default=True)


def _iter_collection_fields(fields: Any) -> list[Any]:
    if fields is None:
        return []
    if isinstance(fields, Mapping):
        return list(fields.values())
    if isinstance(fields, Sequence) and not isinstance(fields, (str, bytes)):
        return list(fields)
    raise ValidationError("Os campos de coleta devem estar em uma lista.")


def _has_enabled_collection_field(fields: Sequence[Any]) -> bool:
    for field in fields:
        if isinstance(field, Mapping):
            if _is_enabled(field.get("enabled"), default=False):
                return True
            continue

        if _is_enabled(field, default=False):
            return True

    return False


def validate_complete_config(config: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(config, Mapping):
        raise ValidationError("A configuracao deve estar em um formato valido.")

    messages_key, messages = _read_first_value(config, MESSAGE_LIST_KEYS)
    if messages_key is None:
        raise ValidationError("Informe a lista de mensagens.")

    normalized_messages = validate_message_list(messages)

    if not any(_message_enabled(message) for message in normalized_messages):
        raise ValidationError("A configuracao deve ter pelo menos uma mensagem ativa.")

    seen_ids: set[str] = set()
    seen_queries: set[str] = set()

    for message in normalized_messages:
        message_id = _message_id(message)
        if message_id not in (None, ""):
            normalized_id = str(message_id)
            if normalized_id in seen_ids:
                raise ValidationError(f"O id de mensagem '{normalized_id}' esta repetido.")
            seen_ids.add(normalized_id)

        normalized_query = _message_query(message).casefold()
        if normalized_query in seen_queries:
            raise ValidationError(f"A query '{_message_query(message)}' esta repetida.")
        seen_queries.add(normalized_query)

    collection_key, collection_fields = _read_first_value(config, COLLECTION_FIELD_KEYS)
    if collection_key is None:
        raise ValidationError("Informe os campos de coleta.")

    fields = _iter_collection_fields(collection_fields)
    if not _has_enabled_collection_field(fields):
        raise ValidationError("A configuracao deve ter pelo menos um campo de coleta ativo.")

    normalized_config = dict(config)
    normalized_config[messages_key] = normalized_messages
    normalized_config[collection_key] = collection_fields
    return normalized_config


def validate_limit_date(value: str) -> str:
    normalized_value = str(value or "").strip()
    match = re.fullmatch(r"(\d{2})/(\d{2})", normalized_value)

    if match is None:
        raise ValidationError("Informe a data limite no formato DD/MM.")

    day = int(match.group(1))
    month = int(match.group(2))

    if day < 1 or day > 31:
        raise ValidationError("O dia da data limite deve estar entre 01 e 31.")

    if month < 1 or month > 12:
        raise ValidationError("O mes da data limite deve estar entre 01 e 12.")

    return normalized_value


validate_regex = validate_collection_regex
validate_historical_date = validate_limit_date
