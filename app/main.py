from __future__ import annotations

import json
import re
import threading
from collections.abc import Mapping
from copy import deepcopy
from datetime import date
from pathlib import Path
from tkinter import messagebox
from typing import Any, Callable

import customtkinter as ctk

from .api_client import ApiClientError, check_health, fetch_default_search_config
from .local_config import AppConfig, ConfigError, load_config, save_config
from .validators import (
    ValidationError,
    validate_api_url,
    validate_collection_regex,
    validate_config,
    validate_message_key,
    validate_token,
)


APP_TITLE = "Alerta dos Notebooks"
PROJECT_ROOT = Path(__file__).resolve().parent.parent
EXPORTS_DIR = PROJECT_ROOT / "exports"
SENSITIVE_BACKUP_KEY_PARTS = (
    "api_base_url",
    "api_url",
    "apibaseurl",
    "token",
    "secret",
    "password",
    "senha",
    "api_key",
    "authorization",
)

DEFAULT_CONFIG: dict[str, Any] = {
    "config_id": "default",
    "ativa": True,
    "version": 1,
    "MENSAGENS": [],
    "COLETA": {
        "RAM": {"enabled": True, "pattern": r"\d+\s*GB"},
        "SSD": {"enabled": True, "pattern": r"\d+\s*(GB|TB)"},
        "preco": {"enabled": True, "pattern": r"R\$\s*[0-9\.\,]+"},
        "link": {"enabled": True, "pattern": r"https?://\S+"},
    },
    "LIMITES": {
        "max_mensagens_historico": 500,
        "max_tamanho_texto": 5000,
        "timeout_telegram_segundos": 30,
    },
}


def get_default_config() -> dict[str, Any]:
    return deepcopy(DEFAULT_CONFIG)


def get_default_collection_config() -> dict[str, dict[str, Any]]:
    return deepcopy(DEFAULT_CONFIG["COLETA"])


def get_backup_path(today: date | None = None) -> Path:
    export_date = today or date.today()
    return EXPORTS_DIR / f"search_backup_{export_date:%Y_%m_%d}.json"


def _is_sensitive_backup_key(key: Any) -> bool:
    normalized_key = str(key).casefold().replace("-", "_").replace(" ", "_")
    return any(key_part in normalized_key for key_part in SENSITIVE_BACKUP_KEY_PARTS)


def sanitize_config_for_backup(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {
            key: sanitize_config_for_backup(item)
            for key, item in value.items()
            if not _is_sensitive_backup_key(key)
        }

    if isinstance(value, list):
        return [sanitize_config_for_backup(item) for item in value]

    return value


class ConnectionFrame(ctk.CTkFrame):
    def __init__(
        self,
        master: ctk.CTk,
        config: AppConfig,
        on_continue: Callable[[AppConfig, dict[str, Any], bool, str], None],
        startup_error: str = "",
    ) -> None:
        super().__init__(master, fg_color="transparent")
        self.on_continue = on_continue

        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(0, weight=1)

        panel = ctk.CTkFrame(self, corner_radius=8)
        panel.grid(row=0, column=0, sticky="nsew", padx=32, pady=32)
        panel.grid_columnconfigure(0, weight=1)

        title = ctk.CTkLabel(
            panel,
            text=APP_TITLE,
            font=ctk.CTkFont(size=24, weight="bold"),
        )
        title.grid(row=0, column=0, sticky="w", padx=28, pady=(28, 4))

        subtitle = ctk.CTkLabel(
            panel,
            text="Configure a conex\u00e3o com a API do servidor.",
            text_color=("gray35", "gray70"),
        )
        subtitle.grid(row=1, column=0, sticky="w", padx=28, pady=(0, 24))

        api_label = ctk.CTkLabel(panel, text="URL da API")
        api_label.grid(row=2, column=0, sticky="w", padx=28, pady=(0, 6))

        self.api_url_entry = ctk.CTkEntry(
            panel,
            height=40,
            placeholder_text="http://localhost:8000",
        )
        self.api_url_entry.grid(row=3, column=0, sticky="ew", padx=28, pady=(0, 16))
        self.api_url_entry.insert(0, config.api_base_url)

        token_label = ctk.CTkLabel(panel, text="Token")
        token_label.grid(row=4, column=0, sticky="w", padx=28, pady=(0, 6))

        self.token_entry = ctk.CTkEntry(
            panel,
            height=40,
            placeholder_text="Token de autentica\u00e7\u00e3o da API",
            show="*",
        )
        self.token_entry.grid(row=5, column=0, sticky="ew", padx=28, pady=(0, 18))
        self.token_entry.insert(0, config.auth_token)

        actions = ctk.CTkFrame(panel, fg_color="transparent")
        actions.grid(row=6, column=0, sticky="ew", padx=28, pady=(0, 16))
        actions.grid_columnconfigure(0, weight=1)

        self.test_button = ctk.CTkButton(
            actions,
            text="Testar conex\u00e3o",
            command=self.test_connection,
        )
        self.test_button.grid(row=0, column=1, sticky="e", padx=(0, 10))

        self.continue_button = ctk.CTkButton(
            actions,
            text="Continuar",
            command=self.continue_to_app,
        )
        self.continue_button.grid(row=0, column=2, sticky="e")

        self.status_label = ctk.CTkLabel(
            panel,
            text=startup_error,
            anchor="w",
            justify="left",
            text_color="#d97706" if startup_error else ("gray35", "gray70"),
            wraplength=560,
        )
        self.status_label.grid(row=7, column=0, sticky="ew", padx=28, pady=(0, 28))

    def _current_config(self) -> AppConfig:
        return AppConfig(
            api_base_url=self.api_url_entry.get().strip(),
            auth_token=self.token_entry.get(),
        )

    def _set_status(self, message: str, color: str | tuple[str, str]) -> None:
        self.status_label.configure(text=message, text_color=color)

    def _set_controls_enabled(self, enabled: bool) -> None:
        state = "normal" if enabled else "disabled"
        self.api_url_entry.configure(state=state)
        self.token_entry.configure(state=state)
        self.test_button.configure(state=state)
        self.continue_button.configure(state=state)

    def _update_api_url_entry(self, api_base_url: str) -> None:
        self.api_url_entry.delete(0, "end")
        self.api_url_entry.insert(0, api_base_url)

    def test_connection(self) -> None:
        raw_config = self._current_config()

        try:
            api_base_url = validate_api_url(raw_config.api_base_url)
        except ValidationError as exc:
            self._set_status(str(exc), "#dc2626")
            return

        self._update_api_url_entry(api_base_url)
        config = AppConfig(api_base_url=api_base_url, auth_token=raw_config.auth_token)

        self.test_button.configure(state="disabled", text="Testando...")
        self._set_status("Testando conex\u00e3o com o servidor...", ("gray35", "gray70"))

        def worker() -> None:
            try:
                check_health(config.api_base_url, config.auth_token)
            except ApiClientError as exc:
                message = str(exc)
                self.after(0, lambda: self._finish_test(message, "#dc2626"))
            else:
                self.after(0, lambda: self._finish_test("Servidor online", "#16a34a"))

        threading.Thread(target=worker, daemon=True).start()

    def _finish_test(self, message: str, color: str) -> None:
        self.test_button.configure(state="normal", text="Testar conex\u00e3o")
        self._set_status(message, color)

    def continue_to_app(self) -> None:
        raw_config = self._current_config()

        try:
            api_base_url = validate_api_url(raw_config.api_base_url)
            auth_token = validate_token(raw_config.auth_token)
        except ValidationError as exc:
            self._set_status(str(exc), "#dc2626")
            return

        self._update_api_url_entry(api_base_url)
        connection_config = AppConfig(api_base_url=api_base_url, auth_token=auth_token)

        try:
            save_config(connection_config)
        except ConfigError as exc:
            self._set_status(str(exc), "#dc2626")
            return

        self._set_controls_enabled(False)
        self.continue_button.configure(text="Carregando...")
        self._set_status("Carregando configura\u00e7\u00e3o do servidor...", ("gray35", "gray70"))

        def worker() -> None:
            try:
                current_config = fetch_default_search_config(
                    connection_config.api_base_url,
                    connection_config.auth_token,
                )
            except ApiClientError as exc:
                message = (
                    "Modo local/offline ativo. Nao foi possivel carregar a "
                    f"configura\u00e7\u00e3o do servidor: {exc}"
                )
                self.after(
                    0,
                    lambda: self.on_continue(
                        connection_config,
                        get_default_config(),
                        True,
                        message,
                    ),
                )
            else:
                self.after(
                    0,
                    lambda: self.on_continue(
                        connection_config,
                        current_config,
                        False,
                        "Configura\u00e7\u00e3o do servidor carregada.",
                    ),
                )

        threading.Thread(target=worker, daemon=True).start()


class MessageConfigFrame(ctk.CTkFrame):
    def __init__(
        self,
        master: ctk.CTk,
        current_config: dict[str, Any],
        is_offline: bool,
        mode_message: str,
        on_back: Callable[[], None],
        on_current_config_changed: Callable[[dict[str, Any], bool, str], None],
    ) -> None:
        super().__init__(master, fg_color="transparent")
        self.current_config = current_config
        self.is_offline = is_offline
        self.mode_message = mode_message
        self.on_back = on_back
        self.on_current_config_changed = on_current_config_changed
        self.editing_message_id: int | None = None

        self._normalize_messages()

        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(0, weight=1)

        panel = ctk.CTkFrame(self, corner_radius=8)
        panel.grid(row=0, column=0, sticky="nsew", padx=28, pady=28)
        panel.grid_columnconfigure(0, weight=1)
        panel.grid_rowconfigure(4, weight=1)

        header = ctk.CTkFrame(panel, fg_color="transparent")
        header.grid(row=0, column=0, sticky="ew", padx=24, pady=(24, 10))
        header.grid_columnconfigure(0, weight=1)

        title = ctk.CTkLabel(
            header,
            text="Configurar mensagens-chave",
            font=ctk.CTkFont(size=24, weight="bold"),
        )
        title.grid(row=0, column=0, sticky="w")

        back_button = ctk.CTkButton(header, text="Voltar", width=110, command=self.on_back)
        back_button.grid(row=0, column=1, sticky="e")

        mode_text = "Modo local/offline" if is_offline else "Servidor online"
        mode_color = "#d97706" if is_offline else "#16a34a"
        mode_label = ctk.CTkLabel(
            panel,
            text=f"{mode_text}. Alteracoes salvas apenas no estado local.",
            text_color=mode_color,
            anchor="w",
            justify="left",
            wraplength=700,
        )
        mode_label.grid(row=1, column=0, sticky="ew", padx=24, pady=(0, 16))

        form = ctk.CTkFrame(panel, corner_radius=8)
        form.grid(row=2, column=0, sticky="ew", padx=24, pady=(0, 18))
        form.grid_columnconfigure(0, weight=1)

        input_label = ctk.CTkLabel(form, text="Mensagem-chave")
        input_label.grid(row=0, column=0, columnspan=3, sticky="w", padx=16, pady=(14, 6))

        self.query_entry = ctk.CTkEntry(
            form,
            height=40,
            placeholder_text="notebook vision ryzen 7",
        )
        self.query_entry.grid(row=1, column=0, sticky="ew", padx=(16, 10), pady=(0, 16))

        self.submit_button = ctk.CTkButton(
            form,
            text="Adicionar",
            width=130,
            command=self.save_message,
        )
        self.submit_button.grid(row=1, column=1, sticky="e", padx=(0, 10), pady=(0, 16))

        self.cancel_edit_button = ctk.CTkButton(
            form,
            text="Cancelar",
            width=110,
            command=self.cancel_edit,
            state="disabled",
        )
        self.cancel_edit_button.grid(row=1, column=2, sticky="e", padx=(0, 16), pady=(0, 16))

        list_header = ctk.CTkFrame(panel, fg_color="transparent")
        list_header.grid(row=3, column=0, sticky="ew", padx=24, pady=(0, 8))
        list_header.grid_columnconfigure(0, weight=1)

        self.count_label = ctk.CTkLabel(
            list_header,
            text="Mensagens atuais",
            font=ctk.CTkFont(size=15, weight="bold"),
        )
        self.count_label.grid(row=0, column=0, sticky="w")

        self.messages_container = ctk.CTkScrollableFrame(panel, corner_radius=8)
        self.messages_container.grid(row=4, column=0, sticky="nsew", padx=24, pady=(0, 16))
        self.messages_container.grid_columnconfigure(0, weight=1)

        self.status_label = ctk.CTkLabel(
            panel,
            text="Adicione, edite, ative ou remova termos localmente.",
            text_color=("gray35", "gray70"),
            wraplength=700,
            justify="left",
            anchor="w",
        )
        self.status_label.grid(row=5, column=0, sticky="ew", padx=24, pady=(0, 24))

        self.refresh_messages()

    def _set_status(self, message: str, color: str | tuple[str, str] = ("gray35", "gray70")) -> None:
        self.status_label.configure(text=message, text_color=color)

    def _messages(self) -> list[dict[str, Any]]:
        messages = self.current_config.get("MENSAGENS")
        if not isinstance(messages, list):
            messages = []
            self.current_config["MENSAGENS"] = messages
        return messages

    def _normalize_messages(self) -> None:
        raw_messages = self.current_config.get("MENSAGENS")
        if not isinstance(raw_messages, list):
            self.current_config["MENSAGENS"] = []
            return

        normalized_messages: list[dict[str, Any]] = []
        used_ids: set[int] = set()
        next_id = self._next_available_id(raw_messages, used_ids)

        for item in raw_messages:
            message = dict(item) if isinstance(item, dict) else {"query": str(item or "")}
            message_id = self._coerce_id(message.get("id"))

            if message_id is None or message_id in used_ids:
                message_id = next_id
                next_id += 1

            used_ids.add(message_id)
            message["id"] = message_id
            message["query"] = str(message.get("query") or "")

            if "ativa" not in message:
                message["ativa"] = self._coerce_bool(message.get("enabled"), default=True)

            normalized_messages.append(message)

        self.current_config["MENSAGENS"] = normalized_messages

    def _next_available_id(self, messages: list[Any], used_ids: set[int] | None = None) -> int:
        used_ids = used_ids or set()
        numeric_ids: list[int] = []

        for message in messages:
            if isinstance(message, dict):
                message_id = self._coerce_id(message.get("id"))
                if message_id is not None:
                    numeric_ids.append(message_id)

        next_id = max(numeric_ids, default=0) + 1
        while next_id in used_ids:
            next_id += 1
        return next_id

    def _coerce_id(self, value: Any) -> int | None:
        if isinstance(value, bool):
            return None
        if isinstance(value, int):
            return value
        if isinstance(value, str) and value.strip().isdigit():
            return int(value.strip())
        return None

    def _coerce_bool(self, value: Any, *, default: bool = True) -> bool:
        if isinstance(value, bool):
            return value
        if value is None:
            return default
        if isinstance(value, str):
            return value.strip().lower() in {"1", "true", "sim", "yes", "on"}
        return bool(value)

    def _message_active(self, message: dict[str, Any]) -> bool:
        if "ativa" in message:
            return self._coerce_bool(message["ativa"], default=True)
        return self._coerce_bool(message.get("enabled"), default=True)

    def _find_message(self, message_id: int) -> dict[str, Any] | None:
        for message in self._messages():
            if self._coerce_id(message.get("id")) == message_id:
                return message
        return None

    def _query_exists(self, query: str, ignored_message_id: int | None = None) -> bool:
        target = self._query_compare_key(query)

        for message in self._messages():
            message_id = self._coerce_id(message.get("id"))
            if ignored_message_id is not None and message_id == ignored_message_id:
                continue
            if self._query_compare_key(str(message.get("query") or "")) == target:
                return True

        return False

    def _query_compare_key(self, query: str) -> str:
        try:
            return validate_message_key(query).casefold()
        except ValidationError:
            return str(query or "").strip().casefold()

    def _notify_config_changed(self, message: str) -> None:
        self.mode_message = message
        self.on_current_config_changed(self.current_config, self.is_offline, message)

    def refresh_messages(self) -> None:
        for child in self.messages_container.winfo_children():
            child.destroy()

        messages = self._messages()
        total = len(messages)
        active_total = sum(1 for message in messages if self._message_active(message))
        self.count_label.configure(text=f"Mensagens atuais: {total} ({active_total} ativas)")

        if not messages:
            empty_label = ctk.CTkLabel(
                self.messages_container,
                text="Nenhuma mensagem-chave cadastrada.",
                text_color=("gray35", "gray70"),
                anchor="w",
            )
            empty_label.grid(row=0, column=0, sticky="ew", padx=12, pady=16)
            return

        for row_index, message in enumerate(messages):
            self._create_message_row(row_index, message)

    def _create_message_row(self, row_index: int, message: dict[str, Any]) -> None:
        message_id = self._coerce_id(message.get("id")) or 0
        query = str(message.get("query") or "")
        is_active = self._message_active(message)

        row = ctk.CTkFrame(self.messages_container, corner_radius=8)
        row.grid(row=row_index, column=0, sticky="ew", padx=8, pady=6)
        row.grid_columnconfigure(2, weight=1)

        id_label = ctk.CTkLabel(row, text=f"#{message_id}", width=54)
        id_label.grid(row=0, column=0, sticky="w", padx=(12, 8), pady=10)

        active_label = ctk.CTkLabel(
            row,
            text="Ativa" if is_active else "Inativa",
            text_color="#16a34a" if is_active else "#d97706",
            width=70,
        )
        active_label.grid(row=0, column=1, sticky="w", padx=(0, 8), pady=10)

        query_label = ctk.CTkLabel(
            row,
            text=query or "(sem query)",
            anchor="w",
            justify="left",
            wraplength=360,
        )
        query_label.grid(row=0, column=2, sticky="ew", padx=(0, 10), pady=10)

        edit_button = ctk.CTkButton(
            row,
            text="Editar",
            width=74,
            command=lambda selected_id=message_id: self.start_edit(selected_id),
        )
        edit_button.grid(row=0, column=3, sticky="e", padx=(0, 8), pady=10)

        toggle_button = ctk.CTkButton(
            row,
            text="Desativar" if is_active else "Ativar",
            width=88,
            command=lambda selected_id=message_id: self.toggle_message(selected_id),
        )
        toggle_button.grid(row=0, column=4, sticky="e", padx=(0, 8), pady=10)

        delete_button = ctk.CTkButton(
            row,
            text="Deletar",
            width=78,
            fg_color="#b91c1c",
            hover_color="#991b1b",
            command=lambda selected_id=message_id: self.delete_message(selected_id),
        )
        delete_button.grid(row=0, column=5, sticky="e", padx=(0, 12), pady=10)

    def save_message(self) -> None:
        try:
            query = validate_message_key(self.query_entry.get())
        except ValidationError as exc:
            self._set_status(str(exc), "#dc2626")
            return

        if self.editing_message_id is None:
            self.add_message(query)
            return

        self.update_message(self.editing_message_id, query)

    def add_message(self, query: str) -> None:
        if self._query_exists(query):
            self._set_status("Esta mensagem-chave ja esta cadastrada.", "#dc2626")
            return

        messages = self._messages()
        messages.append(
            {
                "id": self._next_available_id(messages),
                "query": query,
                "ativa": True,
            }
        )

        self.query_entry.delete(0, "end")
        self._notify_config_changed("Mensagens-chave atualizadas em memoria.")
        self.refresh_messages()
        self._set_status("Mensagem-chave adicionada.", "#16a34a")

    def start_edit(self, message_id: int) -> None:
        message = self._find_message(message_id)
        if message is None:
            self._set_status("Mensagem-chave nao encontrada.", "#dc2626")
            return

        self.editing_message_id = message_id
        self.query_entry.delete(0, "end")
        self.query_entry.insert(0, str(message.get("query") or ""))
        self.submit_button.configure(text="Salvar")
        self.cancel_edit_button.configure(state="normal")
        self._set_status(f"Editando mensagem #{message_id}.", ("gray35", "gray70"))

    def update_message(self, message_id: int, query: str) -> None:
        if self._query_exists(query, ignored_message_id=message_id):
            self._set_status("Ja existe outra mensagem-chave com esse texto.", "#dc2626")
            return

        message = self._find_message(message_id)
        if message is None:
            self._set_status("Mensagem-chave nao encontrada.", "#dc2626")
            return

        message["query"] = query
        self.cancel_edit()
        self._notify_config_changed("Mensagens-chave atualizadas em memoria.")
        self.refresh_messages()
        self._set_status("Mensagem-chave editada.", "#16a34a")

    def cancel_edit(self) -> None:
        self.editing_message_id = None
        self.query_entry.delete(0, "end")
        self.submit_button.configure(text="Adicionar")
        self.cancel_edit_button.configure(state="disabled")

    def toggle_message(self, message_id: int) -> None:
        message = self._find_message(message_id)
        if message is None:
            self._set_status("Mensagem-chave nao encontrada.", "#dc2626")
            return

        message["ativa"] = not self._message_active(message)
        self._notify_config_changed("Mensagens-chave atualizadas em memoria.")
        self.refresh_messages()

        status = "ativada" if self._message_active(message) else "desativada"
        self._set_status(f"Mensagem-chave {status}.", "#16a34a")

    def delete_message(self, message_id: int) -> None:
        message = self._find_message(message_id)
        if message is None:
            self._set_status("Mensagem-chave nao encontrada.", "#dc2626")
            return

        query = str(message.get("query") or "")
        confirmed = messagebox.askyesno(
            "Confirmar exclusao",
            f"Deletar a mensagem-chave #{message_id}?\n\n{query}",
            parent=self,
        )
        if not confirmed:
            self._set_status("Exclusao cancelada.", ("gray35", "gray70"))
            return

        self.current_config["MENSAGENS"] = [
            item for item in self._messages() if self._coerce_id(item.get("id")) != message_id
        ]

        if self.editing_message_id == message_id:
            self.cancel_edit()

        self._notify_config_changed("Mensagens-chave atualizadas em memoria.")
        self.refresh_messages()
        self._set_status("Mensagem-chave deletada.", "#16a34a")


class CollectionConfigFrame(ctk.CTkFrame):
    def __init__(
        self,
        master: ctk.CTk,
        current_config: dict[str, Any],
        is_offline: bool,
        mode_message: str,
        on_back: Callable[[], None],
        on_current_config_changed: Callable[[dict[str, Any], bool, str], None],
    ) -> None:
        super().__init__(master, fg_color="transparent")
        self.current_config = current_config
        self.is_offline = is_offline
        self.mode_message = mode_message
        self.on_back = on_back
        self.on_current_config_changed = on_current_config_changed
        self.draft_collection = self._build_draft_collection()
        self.pattern_entries: dict[str, ctk.CTkEntry] = {}
        self.enabled_switches: dict[str, ctk.CTkSwitch] = {}

        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(0, weight=1)

        panel = ctk.CTkFrame(self, corner_radius=8)
        panel.grid(row=0, column=0, sticky="nsew", padx=28, pady=28)
        panel.grid_columnconfigure(0, weight=1)
        panel.grid_rowconfigure(4, weight=1)

        header = ctk.CTkFrame(panel, fg_color="transparent")
        header.grid(row=0, column=0, sticky="ew", padx=24, pady=(24, 10))
        header.grid_columnconfigure(0, weight=1)

        title = ctk.CTkLabel(
            header,
            text="Configurar dados de coleta",
            font=ctk.CTkFont(size=24, weight="bold"),
        )
        title.grid(row=0, column=0, sticky="w")

        back_button = ctk.CTkButton(header, text="Voltar", width=110, command=self.on_back)
        back_button.grid(row=0, column=1, sticky="e")

        mode_text = "Modo local/offline" if is_offline else "Servidor online"
        mode_color = "#d97706" if is_offline else "#16a34a"
        mode_label = ctk.CTkLabel(
            panel,
            text=f"{mode_text}. Alteracoes salvas apenas no estado local.",
            text_color=mode_color,
            anchor="w",
            justify="left",
            wraplength=700,
        )
        mode_label.grid(row=1, column=0, sticky="ew", padx=24, pady=(0, 14))

        example_panel = ctk.CTkFrame(panel, corner_radius=8)
        example_panel.grid(row=2, column=0, sticky="ew", padx=24, pady=(0, 14))
        example_panel.grid_columnconfigure(0, weight=1)

        example_label = ctk.CTkLabel(example_panel, text="Texto de exemplo para testar regex")
        example_label.grid(row=0, column=0, sticky="w", padx=16, pady=(14, 6))

        self.example_textbox = ctk.CTkTextbox(example_panel, height=82, wrap="word")
        self.example_textbox.grid(row=1, column=0, sticky="ew", padx=16, pady=(0, 16))
        self.example_textbox.insert(
            "1.0",
            "Notebook Vision Ryzen 7 com 16GB RAM, SSD 512GB, preco R$ 3.499,90 "
            "e link https://loja.exemplo/notebook",
        )

        actions = ctk.CTkFrame(panel, fg_color="transparent")
        actions.grid(row=3, column=0, sticky="ew", padx=24, pady=(0, 10))
        actions.grid_columnconfigure(0, weight=1)

        fields_label = ctk.CTkLabel(
            actions,
            text="Campos de coleta",
            font=ctk.CTkFont(size=15, weight="bold"),
        )
        fields_label.grid(row=0, column=0, sticky="w")

        restore_button = ctk.CTkButton(
            actions,
            text="Restaurar padr\u00f5es",
            width=150,
            command=self.restore_defaults,
        )
        restore_button.grid(row=0, column=1, sticky="e", padx=(0, 10))

        save_button = ctk.CTkButton(
            actions,
            text="Salvar localmente",
            width=150,
            command=self.save_local,
        )
        save_button.grid(row=0, column=2, sticky="e")

        self.fields_container = ctk.CTkScrollableFrame(panel, corner_radius=8)
        self.fields_container.grid(row=4, column=0, sticky="nsew", padx=24, pady=(0, 16))
        self.fields_container.grid_columnconfigure(0, weight=1)

        self.status_label = ctk.CTkLabel(
            panel,
            text="Edite os patterns e teste contra o texto de exemplo antes de salvar.",
            text_color=("gray35", "gray70"),
            wraplength=700,
            justify="left",
            anchor="w",
        )
        self.status_label.grid(row=5, column=0, sticky="ew", padx=24, pady=(0, 24))

        self.refresh_fields()

    def _set_status(self, message: str, color: str | tuple[str, str] = ("gray35", "gray70")) -> None:
        self.status_label.configure(text=message, text_color=color)

    def _coerce_bool(self, value: Any, *, default: bool = True) -> bool:
        if isinstance(value, bool):
            return value
        if value is None:
            return default
        if isinstance(value, str):
            return value.strip().lower() in {"1", "true", "sim", "yes", "on"}
        return bool(value)

    def _build_draft_collection(self) -> dict[str, dict[str, Any]]:
        default_collection = get_default_collection_config()
        raw_collection = self.current_config.get("COLETA")
        if not isinstance(raw_collection, Mapping):
            raw_collection = {}

        draft: dict[str, dict[str, Any]] = {}

        for field_name, default_field in default_collection.items():
            raw_field = raw_collection.get(field_name)
            draft[field_name] = self._normalize_field(raw_field, default_field)

        for field_name, raw_field in raw_collection.items():
            if field_name in draft:
                continue
            draft[str(field_name)] = self._normalize_field(
                raw_field,
                {"enabled": True, "pattern": ""},
            )

        return draft

    def _normalize_field(self, raw_field: Any, default_field: Mapping[str, Any]) -> dict[str, Any]:
        if not isinstance(raw_field, Mapping):
            raw_field = {}

        default_pattern = str(default_field.get("pattern") or "")
        pattern = str(raw_field.get("pattern") or default_pattern)
        enabled = self._coerce_bool(
            raw_field.get("enabled"),
            default=self._coerce_bool(default_field.get("enabled"), default=True),
        )

        return {"enabled": enabled, "pattern": pattern}

    def _ordered_field_names(self) -> list[str]:
        default_names = list(get_default_collection_config().keys())
        extra_names = [name for name in self.draft_collection if name not in default_names]
        return default_names + sorted(extra_names)

    def refresh_fields(self) -> None:
        for child in self.fields_container.winfo_children():
            child.destroy()

        self.pattern_entries.clear()
        self.enabled_switches.clear()

        for row_index, field_name in enumerate(self._ordered_field_names()):
            field = self.draft_collection.setdefault(
                field_name,
                {"enabled": True, "pattern": ""},
            )
            self._create_field_row(row_index, field_name, field)

    def _create_field_row(self, row_index: int, field_name: str, field: dict[str, Any]) -> None:
        row = ctk.CTkFrame(self.fields_container, corner_radius=8)
        row.grid(row=row_index, column=0, sticky="ew", padx=8, pady=6)
        row.grid_columnconfigure(2, weight=1)

        name_label = ctk.CTkLabel(
            row,
            text=field_name,
            width=80,
            font=ctk.CTkFont(weight="bold"),
        )
        name_label.grid(row=0, column=0, sticky="w", padx=(12, 8), pady=10)

        enabled_switch = ctk.CTkSwitch(row, text="", width=52, onvalue=True, offvalue=False)
        enabled_switch.grid(row=0, column=1, sticky="w", padx=(0, 8), pady=10)
        if self._coerce_bool(field.get("enabled"), default=True):
            enabled_switch.select()
        else:
            enabled_switch.deselect()
        self.enabled_switches[field_name] = enabled_switch

        pattern_entry = ctk.CTkEntry(row, height=38)
        pattern_entry.grid(row=0, column=2, sticky="ew", padx=(0, 10), pady=10)
        pattern_entry.insert(0, str(field.get("pattern") or ""))
        self.pattern_entries[field_name] = pattern_entry

        test_button = ctk.CTkButton(
            row,
            text="Testar",
            width=82,
            command=lambda selected_field=field_name: self.test_pattern(selected_field),
        )
        test_button.grid(row=0, column=3, sticky="e", padx=(0, 12), pady=10)

    def _read_draft_from_ui(self) -> dict[str, dict[str, Any]]:
        draft: dict[str, dict[str, Any]] = {}

        for field_name in self._ordered_field_names():
            switch = self.enabled_switches[field_name]
            entry = self.pattern_entries[field_name]
            draft[field_name] = {
                "enabled": bool(switch.get()),
                "pattern": entry.get().strip(),
            }

        return draft

    def _validate_collection(self, collection: dict[str, dict[str, Any]]) -> dict[str, dict[str, Any]]:
        if not any(bool(field.get("enabled")) for field in collection.values()):
            raise ValidationError("Ative pelo menos um campo de coleta.")

        validated: dict[str, dict[str, Any]] = {}

        for field_name, field in collection.items():
            try:
                pattern = validate_collection_regex(str(field.get("pattern") or ""))
            except ValidationError as exc:
                raise ValidationError(f"{field_name}: {exc}") from exc

            validated[field_name] = {
                "enabled": bool(field.get("enabled")),
                "pattern": pattern,
            }

        return validated

    def test_pattern(self, field_name: str) -> None:
        pattern = self.pattern_entries[field_name].get().strip()

        try:
            validated_pattern = validate_collection_regex(pattern)
        except ValidationError as exc:
            self._set_status(f"{field_name}: {exc}", "#dc2626")
            return

        sample_text = self.example_textbox.get("1.0", "end").strip()
        if not sample_text:
            self._set_status("Informe um texto de exemplo para testar a regex.", "#dc2626")
            return

        compiled_pattern = re.compile(validated_pattern)
        matches = list(compiled_pattern.finditer(sample_text))

        if not matches:
            self._set_status(f"{field_name}: regex valida, mas sem correspondencias.", "#d97706")
            return

        preview = ", ".join(match.group(0)[:80] for match in matches[:5])
        extra_count = len(matches) - 5
        suffix = f" (+{extra_count})" if extra_count > 0 else ""
        self._set_status(
            f"{field_name}: {len(matches)} correspondencia(s){suffix}: {preview}",
            "#16a34a",
        )

    def restore_defaults(self) -> None:
        self.draft_collection = get_default_collection_config()
        self.refresh_fields()
        self._set_status("Patterns padrao restaurados no rascunho. Clique em Salvar localmente para aplicar.", "#16a34a")

    def save_local(self) -> None:
        try:
            validated_collection = self._validate_collection(self._read_draft_from_ui())
        except ValidationError as exc:
            self._set_status(str(exc), "#dc2626")
            return

        self.draft_collection = deepcopy(validated_collection)
        self.current_config["COLETA"] = deepcopy(validated_collection)
        message = "Dados de coleta salvos no estado local."
        self.mode_message = message
        self.on_current_config_changed(self.current_config, self.is_offline, message)
        self.refresh_fields()
        self._set_status(message, "#16a34a")


class MainMenuFrame(ctk.CTkFrame):
    def __init__(
        self,
        master: ctk.CTk,
        connection_config: AppConfig,
        current_config: dict[str, Any],
        is_offline: bool,
        mode_message: str,
        on_edit_connection: Callable[[], None],
        on_configure_messages: Callable[[], None],
        on_configure_collection: Callable[[], None],
        on_current_config_changed: Callable[[dict[str, Any], bool, str], None],
        on_exit: Callable[[], None],
    ) -> None:
        super().__init__(master, fg_color="transparent")
        self.connection_config = connection_config
        self.current_config = current_config
        self.is_offline = is_offline
        self.on_edit_connection = on_edit_connection
        self.on_configure_messages = on_configure_messages
        self.on_configure_collection = on_configure_collection
        self.on_current_config_changed = on_current_config_changed
        self.on_exit = on_exit

        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(0, weight=1)

        panel = ctk.CTkFrame(self, corner_radius=8)
        panel.grid(row=0, column=0, sticky="nsew", padx=28, pady=28)
        panel.grid_columnconfigure(0, weight=1)
        panel.grid_rowconfigure(4, weight=1)

        header = ctk.CTkFrame(panel, fg_color="transparent")
        header.grid(row=0, column=0, sticky="ew", padx=24, pady=(24, 6))
        header.grid_columnconfigure(0, weight=1)

        title = ctk.CTkLabel(
            header,
            text="Menu principal",
            font=ctk.CTkFont(size=24, weight="bold"),
        )
        title.grid(row=0, column=0, sticky="w")

        self.mode_label = ctk.CTkLabel(
            header,
            text=self._mode_label_text(),
            text_color=self._mode_color(),
            font=ctk.CTkFont(weight="bold"),
        )
        self.mode_label.grid(row=0, column=1, sticky="e")

        api_label = ctk.CTkLabel(
            panel,
            text=f"API configurada: {connection_config.api_base_url}",
            text_color=("gray35", "gray70"),
            wraplength=680,
            justify="left",
        )
        api_label.grid(row=1, column=0, sticky="ew", padx=24, pady=(0, 4))

        self.mode_message_label = ctk.CTkLabel(
            panel,
            text=mode_message,
            text_color=self._mode_color(),
            wraplength=680,
            justify="left",
            anchor="w",
        )
        self.mode_message_label.grid(row=2, column=0, sticky="ew", padx=24, pady=(0, 18))

        buttons = ctk.CTkFrame(panel, fg_color="transparent")
        buttons.grid(row=3, column=0, sticky="ew", padx=24, pady=(0, 20))
        buttons.grid_columnconfigure(0, weight=1)
        buttons.grid_columnconfigure(1, weight=1)

        menu_actions: list[tuple[str, Callable[[], None]]] = [
            ("Configurar mensagens-chave", self.configure_messages),
            ("Configurar dados de coleta", self.configure_collection),
            ("Validar configura\u00e7\u00e3o local", self.validate_local_config),
            ("Sincronizar com servidor", self.sync_with_server),
            ("Ver configura\u00e7\u00e3o do servidor", self.view_server_config),
            ("Exportar backup search.json", self.export_backup),
            ("Executar pesquisa hist\u00f3rica", self.run_historical_search),
            ("Consultar pesquisa hist\u00f3rica", self.consult_historical_search),
            ("Status do servidor", self.check_server_status),
            ("Sair", self.on_exit),
        ]

        for index, (text, command) in enumerate(menu_actions):
            row = index // 2
            column = index % 2
            button = ctk.CTkButton(
                buttons,
                text=text,
                height=42,
                command=command,
                fg_color="#b91c1c" if text == "Sair" else None,
                hover_color="#991b1b" if text == "Sair" else None,
            )
            button.grid(row=row, column=column, sticky="ew", padx=6, pady=6)

        self.status_label = ctk.CTkLabel(
            panel,
            text="Escolha uma a\u00e7\u00e3o para continuar.",
            text_color=("gray35", "gray70"),
            wraplength=680,
            justify="left",
            anchor="w",
        )
        self.status_label.grid(row=4, column=0, sticky="new", padx=24, pady=(0, 24))

    def _mode_label_text(self) -> str:
        return "Modo local/offline" if self.is_offline else "Servidor online"

    def _mode_color(self) -> str:
        return "#d97706" if self.is_offline else "#16a34a"

    def _set_status(self, message: str, color: str | tuple[str, str] = ("gray35", "gray70")) -> None:
        self.status_label.configure(text=message, text_color=color)

    def _set_mode(self, is_offline: bool, message: str) -> None:
        self.is_offline = is_offline
        self.mode_label.configure(text=self._mode_label_text(), text_color=self._mode_color())
        self.mode_message_label.configure(text=message, text_color=self._mode_color())
        self.on_current_config_changed(self.current_config, self.is_offline, message)

    def _replace_current_config(self, current_config: dict[str, Any], is_offline: bool, message: str) -> None:
        self.current_config = current_config
        self._set_mode(is_offline, message)

    def _not_ready(self, feature_name: str) -> None:
        self._set_status(f"{feature_name} sera implementado em uma pr\u00f3xima etapa.", "#d97706")

    def configure_messages(self) -> None:
        self.on_configure_messages()

    def configure_collection(self) -> None:
        self.on_configure_collection()

    def validate_local_config(self) -> None:
        try:
            validated_config = validate_config(self.current_config)
        except ValidationError as exc:
            field = exc.field or "configuracao"
            reason = exc.reason or str(exc)
            self._set_status(
                f"Configura\u00e7\u00e3o local inv\u00e1lida. Campo: {field}. Motivo: {reason}.",
                "#dc2626",
            )
            return

        self._replace_current_config(
            validated_config,
            self.is_offline,
            "Configura\u00e7\u00e3o local validada em memoria.",
        )
        self._set_status("Configura\u00e7\u00e3o local v\u00e1lida.", "#16a34a")

    def sync_with_server(self) -> None:
        self._set_status("Sincronizacao com servidor ainda nao tem endpoint definido.", "#d97706")

    def view_server_config(self) -> None:
        self._set_status("Carregando configura\u00e7\u00e3o do servidor...", ("gray35", "gray70"))

        def worker() -> None:
            try:
                server_config = fetch_default_search_config(
                    self.connection_config.api_base_url,
                    self.connection_config.auth_token,
                )
            except ApiClientError as exc:
                message = str(exc)
                self.after(
                    0,
                    lambda: self._set_status(
                        f"Nao foi possivel carregar a configura\u00e7\u00e3o do servidor: {message}",
                        "#dc2626",
                    ),
                )
            else:
                self.after(0, lambda: self._finish_view_server_config(server_config))

        threading.Thread(target=worker, daemon=True).start()

    def _finish_view_server_config(self, server_config: dict[str, Any]) -> None:
        self._replace_current_config(
            server_config,
            False,
            "Configura\u00e7\u00e3o do servidor carregada.",
        )
        self._set_status("Configura\u00e7\u00e3o do servidor carregada.", "#16a34a")
        self._show_json_window("Configura\u00e7\u00e3o do servidor", server_config)

    def export_backup(self) -> None:
        backup_path = get_backup_path()

        try:
            backup_path.parent.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            self._set_status(f"Nao foi possivel criar a pasta exports: {exc}", "#dc2626")
            return

        if backup_path.exists():
            relative_path = backup_path.relative_to(PROJECT_ROOT)
            confirmed = messagebox.askyesno(
                "Confirmar exportacao",
                f"O arquivo {relative_path} ja existe.\n\nDeseja substituir?",
                parent=self,
            )
            if not confirmed:
                self._set_status("Exportacao cancelada.", ("gray35", "gray70"))
                return

        backup_config = sanitize_config_for_backup(self.current_config)

        try:
            with backup_path.open("w", encoding="utf-8") as backup_file:
                json.dump(backup_config, backup_file, ensure_ascii=False, indent=2)
                backup_file.write("\n")
        except OSError as exc:
            self._set_status(f"Nao foi possivel exportar o backup: {exc}", "#dc2626")
            return

        relative_path = backup_path.relative_to(PROJECT_ROOT)
        self._set_status(f"Backup exportado para {relative_path}.", "#16a34a")

    def run_historical_search(self) -> None:
        self._not_ready("Executar pesquisa hist\u00f3rica")

    def consult_historical_search(self) -> None:
        self._not_ready("Consultar pesquisa hist\u00f3rica")

    def check_server_status(self) -> None:
        self._set_status("Consultando status do servidor...", ("gray35", "gray70"))

        def worker() -> None:
            try:
                check_health(
                    self.connection_config.api_base_url,
                    self.connection_config.auth_token,
                )
            except ApiClientError as exc:
                message = str(exc)
                self.after(
                    0,
                    lambda: self._finish_server_status(
                        True,
                        f"Servidor indisponivel: {message}",
                    ),
                )
            else:
                self.after(
                    0,
                    lambda: self._finish_server_status(False, "Servidor online."),
                )

        threading.Thread(target=worker, daemon=True).start()

    def _finish_server_status(self, is_offline: bool, message: str) -> None:
        self._set_mode(is_offline, message)
        self._set_status(message, "#d97706" if is_offline else "#16a34a")

    def _show_json_window(self, title: str, data: dict[str, Any]) -> None:
        window = ctk.CTkToplevel(self)
        window.title(title)
        window.geometry("720x520")
        window.minsize(520, 360)
        window.transient(self.winfo_toplevel())
        window.grid_columnconfigure(0, weight=1)
        window.grid_rowconfigure(0, weight=1)

        textbox = ctk.CTkTextbox(window, wrap="none")
        textbox.grid(row=0, column=0, sticky="nsew", padx=16, pady=(16, 10))
        textbox.insert("1.0", json.dumps(data, ensure_ascii=False, indent=2))
        textbox.configure(state="disabled")

        close_button = ctk.CTkButton(window, text="Fechar", command=window.destroy)
        close_button.grid(row=1, column=0, sticky="e", padx=16, pady=(0, 16))


class App(ctk.CTk):
    def __init__(self) -> None:
        super().__init__()

        ctk.set_appearance_mode("system")
        ctk.set_default_color_theme("blue")

        self.title(APP_TITLE)
        self.geometry("800x640")
        self.minsize(640, 520)

        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(0, weight=1)

        self.connection_config = AppConfig()
        self.current_config = get_default_config()
        self.is_offline = True
        self.mode_message = "Configura\u00e7\u00e3o local padrao carregada."
        startup_error = ""

        try:
            self.connection_config = load_config()
        except ConfigError as exc:
            startup_error = str(exc)

        self.show_connection(startup_error=startup_error)

    def _replace_frame(self, frame: ctk.CTkFrame) -> None:
        for child in self.winfo_children():
            if child is not frame:
                child.destroy()
        frame.grid(row=0, column=0, sticky="nsew")

    def _update_current_config(
        self,
        current_config: dict[str, Any],
        is_offline: bool,
        mode_message: str,
    ) -> None:
        self.current_config = current_config
        self.is_offline = is_offline
        self.mode_message = mode_message

    def show_connection(self, startup_error: str = "") -> None:
        self._replace_frame(
            ConnectionFrame(
                self,
                config=self.connection_config,
                on_continue=self.show_main_menu,
                startup_error=startup_error,
            )
        )

    def show_main_menu(
        self,
        connection_config: AppConfig,
        current_config: dict[str, Any],
        is_offline: bool,
        mode_message: str,
    ) -> None:
        self.connection_config = connection_config
        self._update_current_config(current_config, is_offline, mode_message)
        self._replace_frame(
            MainMenuFrame(
                self,
                connection_config=connection_config,
                current_config=self.current_config,
                is_offline=self.is_offline,
                mode_message=self.mode_message,
                on_edit_connection=self.show_connection,
                on_configure_messages=self.show_messages_screen,
                on_configure_collection=self.show_collection_screen,
                on_current_config_changed=self._update_current_config,
                on_exit=self.destroy,
            )
        )

    def show_messages_screen(self) -> None:
        self._replace_frame(
            MessageConfigFrame(
                self,
                current_config=self.current_config,
                is_offline=self.is_offline,
                mode_message=self.mode_message,
                on_back=lambda: self.show_main_menu(
                    self.connection_config,
                    self.current_config,
                    self.is_offline,
                    self.mode_message,
                ),
                on_current_config_changed=self._update_current_config,
            )
        )

    def show_collection_screen(self) -> None:
        self._replace_frame(
            CollectionConfigFrame(
                self,
                current_config=self.current_config,
                is_offline=self.is_offline,
                mode_message=self.mode_message,
                on_back=lambda: self.show_main_menu(
                    self.connection_config,
                    self.current_config,
                    self.is_offline,
                    self.mode_message,
                ),
                on_current_config_changed=self._update_current_config,
            )
        )


def main() -> None:
    app = App()
    app.mainloop()


if __name__ == "__main__":
    main()
