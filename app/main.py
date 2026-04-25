from __future__ import annotations

import json
import threading
from copy import deepcopy
from pathlib import Path
from tkinter import filedialog
from typing import Any, Callable

import customtkinter as ctk

from .api_client import ApiClientError, check_health, fetch_default_search_config
from .local_config import AppConfig, ConfigError, load_config, save_config
from .validators import (
    ValidationError,
    validate_api_url,
    validate_complete_config,
    validate_token,
)


APP_TITLE = "Alerta dos Notebooks"

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


class MainMenuFrame(ctk.CTkFrame):
    def __init__(
        self,
        master: ctk.CTk,
        connection_config: AppConfig,
        current_config: dict[str, Any],
        is_offline: bool,
        mode_message: str,
        on_edit_connection: Callable[[], None],
        on_current_config_changed: Callable[[dict[str, Any], bool, str], None],
        on_exit: Callable[[], None],
    ) -> None:
        super().__init__(master, fg_color="transparent")
        self.connection_config = connection_config
        self.current_config = current_config
        self.is_offline = is_offline
        self.on_edit_connection = on_edit_connection
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
        self._not_ready("Configurar mensagens-chave")

    def configure_collection(self) -> None:
        self._not_ready("Configurar dados de coleta")

    def validate_local_config(self) -> None:
        try:
            validated_config = validate_complete_config(self.current_config)
        except ValidationError as exc:
            self._set_status(f"Configura\u00e7\u00e3o local invalida: {exc}", "#dc2626")
            return

        self._replace_current_config(
            validated_config,
            self.is_offline,
            "Configura\u00e7\u00e3o local validada em memoria.",
        )
        self._set_status("Configura\u00e7\u00e3o local valida.", "#16a34a")

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
        file_path = filedialog.asksaveasfilename(
            title="Exportar backup",
            initialfile="search.json",
            defaultextension=".json",
            filetypes=[("Arquivos JSON", "*.json"), ("Todos os arquivos", "*.*")],
        )

        if not file_path:
            self._set_status("Exportacao cancelada.", ("gray35", "gray70"))
            return

        try:
            with Path(file_path).open("w", encoding="utf-8") as backup_file:
                json.dump(self.current_config, backup_file, ensure_ascii=False, indent=2)
                backup_file.write("\n")
        except OSError as exc:
            self._set_status(f"Nao foi possivel exportar o backup: {exc}", "#dc2626")
            return

        self._set_status(f"Backup exportado para {file_path}.", "#16a34a")

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
                on_current_config_changed=self._update_current_config,
                on_exit=self.destroy,
            )
        )


def main() -> None:
    app = App()
    app.mainloop()


if __name__ == "__main__":
    main()
