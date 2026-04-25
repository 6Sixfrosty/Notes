from __future__ import annotations

import threading
from typing import Callable

import customtkinter as ctk

from .api_client import ApiClientError, check_health
from .local_config import AppConfig, ConfigError, load_config, save_config
from .validators import ValidationError, validate_api_url, validate_token


APP_TITLE = "Alerta dos Notebooks"


class ConnectionFrame(ctk.CTkFrame):
    def __init__(
        self,
        master: ctk.CTk,
        config: AppConfig,
        on_continue: Callable[[AppConfig], None],
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
            text="Configure a conexão com a API do servidor.",
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
            placeholder_text="Token de autenticação da API",
            show="*",
        )
        self.token_entry.grid(row=5, column=0, sticky="ew", padx=28, pady=(0, 18))
        self.token_entry.insert(0, config.auth_token)

        actions = ctk.CTkFrame(panel, fg_color="transparent")
        actions.grid(row=6, column=0, sticky="ew", padx=28, pady=(0, 16))
        actions.grid_columnconfigure(0, weight=1)

        self.test_button = ctk.CTkButton(
            actions,
            text="Testar conexão",
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
        self._set_status("Testando conexão com o servidor...", ("gray35", "gray70"))

        def worker() -> None:
            try:
                check_health(config.api_base_url, config.auth_token)
            except ApiClientError as exc:
                self.after(0, lambda: self._finish_test(str(exc), "#dc2626"))
            else:
                self.after(0, lambda: self._finish_test("Servidor online", "#16a34a"))

        threading.Thread(target=worker, daemon=True).start()

    def _finish_test(self, message: str, color: str) -> None:
        self.test_button.configure(state="normal", text="Testar conexão")
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
        config = AppConfig(api_base_url=api_base_url, auth_token=auth_token)

        try:
            save_config(config)
        except ConfigError as exc:
            self._set_status(str(exc), "#dc2626")
            return

        self.on_continue(config)


class MainMenuFrame(ctk.CTkFrame):
    def __init__(
        self,
        master: ctk.CTk,
        config: AppConfig,
        on_edit_connection: Callable[[], None],
    ) -> None:
        super().__init__(master, fg_color="transparent")
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(0, weight=1)

        panel = ctk.CTkFrame(self, corner_radius=8)
        panel.grid(row=0, column=0, sticky="nsew", padx=32, pady=32)
        panel.grid_columnconfigure(0, weight=1)

        title = ctk.CTkLabel(
            panel,
            text="Menu principal",
            font=ctk.CTkFont(size=24, weight="bold"),
        )
        title.grid(row=0, column=0, sticky="w", padx=28, pady=(28, 8))

        api_label = ctk.CTkLabel(
            panel,
            text=f"API configurada: {config.api_base_url}",
            text_color=("gray35", "gray70"),
            wraplength=560,
            justify="left",
        )
        api_label.grid(row=1, column=0, sticky="w", padx=28, pady=(0, 24))

        edit_button = ctk.CTkButton(
            panel,
            text="Editar conexão",
            command=on_edit_connection,
        )
        edit_button.grid(row=2, column=0, sticky="w", padx=28, pady=(0, 28))


class App(ctk.CTk):
    def __init__(self) -> None:
        super().__init__()

        ctk.set_appearance_mode("system")
        ctk.set_default_color_theme("blue")

        self.title(APP_TITLE)
        self.geometry("720x460")
        self.minsize(560, 380)

        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(0, weight=1)

        self.config_data = AppConfig()
        startup_error = ""

        try:
            self.config_data = load_config()
        except ConfigError as exc:
            startup_error = str(exc)

        self.show_connection(startup_error=startup_error)

    def _replace_frame(self, frame: ctk.CTkFrame) -> None:
        for child in self.winfo_children():
            if child is not frame:
                child.destroy()
        frame.grid(row=0, column=0, sticky="nsew")

    def show_connection(self, startup_error: str = "") -> None:
        self._replace_frame(
            ConnectionFrame(
                self,
                config=self.config_data,
                on_continue=self.show_main_menu,
                startup_error=startup_error,
            )
        )

    def show_main_menu(self, config: AppConfig) -> None:
        self.config_data = config
        self._replace_frame(
            MainMenuFrame(
                self,
                config=config,
                on_edit_connection=self.show_connection,
            )
        )


def main() -> None:
    app = App()
    app.mainloop()


if __name__ == "__main__":
    main()
