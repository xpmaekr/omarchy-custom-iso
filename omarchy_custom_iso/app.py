#!/usr/bin/env python3
"""Textual TUI for building a custom Omarchy ISO with preinstalled AUR apps."""

from __future__ import annotations

import asyncio
import time
from pathlib import Path
from typing import Optional

from rich.text import Text
from textual import work
from textual.app import App, ComposeResult
from textual.containers import Horizontal, Vertical
from textual.screen import ModalScreen
from textual.widgets import (
    Button,
    Footer,
    Header,
    Input,
    Label,
    ListItem,
    ListView,
    RichLog,
    Select,
    Static,
)

from . import core, i18n
from .core import Config, Package
from .i18n import tr


class PackageItem(ListItem):
    """A list row that remembers the package record it shows."""

    def __init__(self, package: dict) -> None:
        self.package = package
        super().__init__(Label(_package_text(package)))


def _package_text(package: dict) -> Text:
    name = package.get("name", "")
    version = package.get("version", "")
    source = package.get("source", "")
    repo = package.get("repo", "")
    tag = "AUR" if source == "aur" else f"repo:{repo}" if repo else "repo"
    text = Text()
    text.append(name, style="bold")
    if version:
        text.append(f"  {version}", style="dim")
    text.append(f"  {tag}", style="cyan")
    if package.get("description"):
        text.append(f"  {package['description'][:90]}", style="dim italic")
    return text


class LanguagePickerApp(App[str]):
    """First-launch language chooser."""

    TITLE = "Omarchy Custom ISO"
    CSS = """
    Screen {
        align: center middle;
    }
    #language-dialog {
        width: 64;
        height: auto;
        border: thick $accent;
        background: $surface;
        padding: 1 2;
    }
    #language-dialog Label {
        width: 100%;
        content-align: center middle;
        margin-bottom: 1;
    }
    #language-dialog Button {
        width: 100%;
        margin-top: 1;
    }
    """

    BINDINGS = [("escape", "default_language", "Esc")]

    def compose(self) -> ComposeResult:
        with Vertical(id="language-dialog"):
            yield Label(tr("language.prompt"))
            yield Button(tr("language.english"), id="en", variant="primary")
            yield Button(tr("language.russian"), id="ru")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        self.exit(event.button.id or i18n.DEFAULT_LANGUAGE)

    def action_default_language(self) -> None:
        self.exit(i18n.DEFAULT_LANGUAGE)


class SettingsScreen(ModalScreen[Optional[dict]]):
    CSS = """
    SettingsScreen {
        align: center middle;
    }
    #dialog {
        width: 78;
        height: auto;
        border: thick $accent;
        background: $surface;
        padding: 1 2;
    }
    #dialog Input, #dialog Select {
        margin-bottom: 1;
    }
    #buttons {
        height: auto;
        align-horizontal: right;
    }
    #buttons Button {
        margin-left: 1;
    }
    """

    def __init__(self, repo_dir: str, password: str, language: str) -> None:
        super().__init__()
        self.repo_dir = repo_dir
        self.password = password
        self.language = language if language in i18n.LANGUAGES else i18n.DEFAULT_LANGUAGE

    def compose(self) -> ComposeResult:
        with Vertical(id="dialog"):
            yield Label(tr("settings.title"))
            yield Label(tr("settings.repo_dir"))
            yield Input(value=self.repo_dir, id="repo-dir")
            yield Label(tr("settings.sudo_password"))
            yield Input(value=self.password, password=True, id="sudo-password")
            yield Label(tr("settings.language"))
            yield Select(
                [
                    (tr("language.english"), "en"),
                    (tr("language.russian"), "ru"),
                ],
                value=self.language,
                allow_blank=False,
                id="language",
            )
            with Horizontal(id="buttons"):
                yield Button(tr("common.cancel"), id="cancel")
                yield Button(tr("common.save"), id="save", variant="success")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "save":
            repo = self.query_one("#repo-dir", Input).value.strip()
            password = self.query_one("#sudo-password", Input).value
            language = self.query_one("#language", Select).value
            self.dismiss(
                {
                    "repo_dir": repo,
                    "sudo_password": password,
                    "language": str(language),
                }
            )
        else:
            self.dismiss(None)


class OmarchyCustomISOApp(App):
    TITLE = "Omarchy Custom ISO"
    SUB_TITLE = ""

    CSS = """
    Screen {
        layout: vertical;
    }
    #main {
        height: 1fr;
        layout: horizontal;
    }
    #left {
        width: 42%;
        border: round $accent;
        padding: 0 1;
    }
    #middle {
        width: 26%;
        border: round $accent;
        padding: 0 1;
    }
    #right {
        width: 32%;
        border: round $accent;
        padding: 0 1;
    }
    #search-row {
        height: auto;
    }
    #search {
        width: 1fr;
    }
    #search-btn {
        width: 10;
    }
    #results {
        height: 1fr;
        margin-top: 1;
    }
    #selected {
        height: 1fr;
        margin-top: 1;
    }
    .row-buttons {
        height: auto;
    }
    .row-buttons Button {
        margin-right: 1;
    }
    #build-btn {
        width: 100%;
        margin-top: 1;
    }
    #status {
        height: auto;
        margin-top: 1;
        color: $text-muted;
    }
    #log {
        height: 1fr;
    }
    #log-title {
        height: auto;
    }
    """

    BINDINGS = [
        ("ctrl+q", "quit", "Quit"),
        ("ctrl+s", "build", "Build ISO"),
        ("ctrl+n", "settings", "Settings"),
        ("f5", "search", "Search"),
        ("delete", "remove_selected", "Remove"),
    ]

    def __init__(self) -> None:
        super().__init__()
        self.config: Config = core.load_config()
        i18n.set_language(self.config.language or i18n.DEFAULT_LANGUAGE)
        self.sub_title = tr("app.subtitle")
        self._results: list[dict] = []
        self._busy = False
        self._current_log = None
        self._update_bindings()

    # ------------------------------------------------------------------ UI

    def _update_bindings(self) -> None:
        for key in ("ctrl+q", "ctrl+s", "ctrl+n", "f5", "delete"):
            self._bindings.key_to_bindings.pop(key, None)
        self.bind("ctrl+q", "quit", description=tr("binding.quit"))
        self.bind("ctrl+s", "build", description=tr("binding.build"))
        self.bind("ctrl+n", "settings", description=tr("binding.settings"))
        self.bind("f5", "search", description=tr("binding.search"))
        self.bind("delete", "remove_selected", description=tr("binding.remove"))
        self.refresh_bindings()

    def compose(self) -> ComposeResult:
        yield Header()
        with Horizontal(id="main"):
            with Vertical(id="left"):
                yield Label(tr("search.title"), id="search-title")
                with Horizontal(id="search-row"):
                    yield Input(placeholder=tr("search.placeholder"), id="search")
                    yield Button(tr("search.find"), id="search-btn", variant="primary")
                yield ListView(id="results")
                with Horizontal(classes="row-buttons"):
                    yield Button(tr("common.add"), id="add-btn", variant="success")
            with Vertical(id="middle"):
                yield Label(tr("selected.title"), id="selected-title")
                yield ListView(id="selected")
                with Horizontal(classes="row-buttons"):
                    yield Button(tr("common.remove"), id="remove-btn", variant="warning")
                    yield Button(tr("common.clear"), id="clear-btn")
                yield Button(tr("common.build_iso"), id="build-btn", variant="success")
                yield Static("", id="status")
            with Vertical(id="right"):
                yield Label(tr("log.title"), id="log-title")
                yield RichLog(id="log", max_lines=8000, min_width=1, wrap=True, markup=False, auto_scroll=True)
        yield Footer()

    def _apply_language(self) -> None:
        self.sub_title = tr("app.subtitle")
        self._update_bindings()
        labels = {
            "#search-title": tr("search.title"),
            "#selected-title": tr("selected.title"),
            "#log-title": tr("log.title"),
        }
        for selector, markup in labels.items():
            self.query_one(selector, Label).update(Text.from_markup(markup))
        buttons = {
            "#search-btn": tr("search.find"),
            "#add-btn": tr("common.add"),
            "#remove-btn": tr("common.remove"),
            "#clear-btn": tr("common.clear"),
            "#build-btn": tr("common.build_iso"),
        }
        for selector, text in buttons.items():
            self.query_one(selector, Button).label = text
        self.query_one("#search", Input).placeholder = tr("search.placeholder")
        if not self._busy:
            self._update_status()

    async def on_mount(self) -> None:
        self.write_log(Text.from_markup(f"[bold]{tr('welcome')}[/bold]"))
        for line in core.environment_report(Path(self.config.repo_dir).expanduser()):
            self.write_log(Text(line))
        self.write_log(Text(tr("hint.select")))
        await self.refresh_selected()
        self.query_one("#search", Input).focus()

    def write_log(self, renderable, newline: bool = True) -> None:
        if isinstance(renderable, str):
            renderable = Text(renderable)
        log = self.query_one("#log", RichLog)
        log.write(renderable)
        if self._current_log is not None:
            try:
                self._current_log.write(str(renderable) + "\n")
                self._current_log.flush()
            except Exception:
                pass

    def status(self, message: str) -> None:
        self.query_one("#status", Static).update(message)

    def set_busy(self, busy: bool) -> None:
        self._busy = busy
        for widget_id in ("#search", "#search-btn", "#add-btn", "#remove-btn", "#clear-btn", "#build-btn"):
            try:
                self.query_one(widget_id).disabled = busy
            except Exception:
                pass

    def _update_status(self) -> None:
        aur = sum(1 for p in self.config.packages if p.source == "aur")
        repo = len(self.config.packages) - aur
        self.status(
            tr(
                "status.selected",
                count=len(self.config.packages),
                aur=aur,
                repo=repo,
            )
        )

    async def refresh_selected(self) -> None:
        view = self.query_one("#selected", ListView)
        await view.clear()
        items = [PackageItem(p.to_dict()) for p in self.config.packages]
        if items:
            await view.extend(items)
        self._update_status()

    def _schedule_refresh_selected(self) -> None:
        # Exclusive: several quick Add/Remove clicks must not interleave their
        # clear()/extend() pairs and show duplicate rows.
        self.run_worker(self.refresh_selected(), group="selected", exclusive=True)

    def add_package(self, package: dict) -> None:
        name = str(package.get("name", "")).strip()
        if not name:
            return
        if any(p.name == name for p in self.config.packages):
            self.write_log(Text.from_markup(tr("pkg.already_selected", name=name)))
            return
        self.config.packages.append(
            Package(
                name=name,
                source=str(package.get("source", "aur")),
                version=str(package.get("version", "")),
                description=str(package.get("description", "")),
                repo=str(package.get("repo", "")),
            )
        )
        core.save_config(self.config)
        self.write_log(
            Text.from_markup(
                tr("pkg.added", name=name, source=package.get("source", "aur"))
            )
        )
        self._schedule_refresh_selected()

    # -------------------------------------------------------------- actions

    def action_search(self) -> None:
        if self._busy:
            return
        query = self.query_one("#search", Input).value.strip()
        if query:
            self.start_search(query)

    def action_build(self) -> None:
        if not self._busy:
            self.build_iso()

    def action_settings(self) -> None:
        if self._busy:
            return
        self.push_screen(
            SettingsScreen(
                self.config.repo_dir,
                self.config.sudo_password,
                self.config.language or i18n.DEFAULT_LANGUAGE,
            ),
            self.apply_settings,
        )

    def action_remove_selected(self) -> None:
        if not self._busy:
            self.remove_highlighted()

    def apply_settings(self, result: Optional[dict]) -> None:
        if not result:
            return
        repo_dir = result.get("repo_dir") or str(core.DEFAULT_REPO_DIR)
        language = str(result.get("language") or self.config.language or i18n.DEFAULT_LANGUAGE)
        language_changed = language != self.config.language
        self.config.repo_dir = repo_dir
        self.config.sudo_password = result.get("sudo_password", self.config.sudo_password)
        self.config.language = i18n.set_language(language)
        core.save_config(self.config)
        if language_changed:
            self._apply_language()
        self.write_log(Text.from_markup(tr("settings.saved", repo=repo_dir)))

    # -------------------------------------------------------------- events

    def on_input_submitted(self, event: Input.Submitted) -> None:
        if event.input.id == "search":
            query = event.value.strip()
            if query:
                self.start_search(query)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        button = event.button.id
        if button == "search-btn":
            self.action_search()
        elif button == "add-btn":
            self.add_highlighted()
        elif button == "remove-btn":
            self.remove_highlighted()
        elif button == "clear-btn":
            self.clear_selected()
        elif button == "build-btn":
            self.action_build()

    def on_list_view_selected(self, event: ListView.Selected) -> None:
        if event.list_view.id == "results":
            item = event.item
            if isinstance(item, PackageItem):
                self.add_package(item.package)

    # --------------------------------------------------------------- search

    @work(exclusive=True, group="search")
    async def start_search(self, query: str) -> None:
        self.status(tr("search.starting", query=query))
        self.write_log(Text.from_markup(tr("search.log", query=query)))
        results = await asyncio.to_thread(core.search_packages, query)
        self._results = results
        view = self.query_one("#results", ListView)
        await view.clear()
        if not results:
            self.write_log(Text.from_markup(tr("search.nothing")))
            self.status(tr("search.nothing_status"))
            return
        await view.extend([PackageItem(item) for item in results])
        aur = sum(1 for r in results if r.get("source") == "aur")
        self.write_log(
            Text.from_markup(
                tr(
                    "search.found",
                    count=len(results),
                    aur=aur,
                    repo=len(results) - aur,
                )
            )
        )
        self.status(tr("search.found_status", count=len(results)))

    def add_highlighted(self) -> None:
        if self._busy:
            return
        view = self.query_one("#results", ListView)
        item = view.highlighted_child
        if isinstance(item, PackageItem):
            self.add_package(item.package)
            return
        name = self.query_one("#search", Input).value.strip()
        if name:
            self.add_typed(name)

    @work(exclusive=True, group="verify")
    async def add_typed(self, name: str) -> None:
        self.status(tr("verify.checking", name=name))
        result = await asyncio.to_thread(core.verify_package, name)
        if result is None:
            self.write_log(Text.from_markup(tr("verify.not_found", name=name)))
            self.status(tr("verify.not_found_status"))
            return
        if result.get("source") == "unsupported":
            self.write_log(
                Text.from_markup(
                    tr("verify.unsupported", name=name, repo=result.get("repo"))
                )
            )
            self.status(tr("verify.unsupported_status"))
            return
        self.add_package(result)

    def remove_highlighted(self) -> None:
        view = self.query_one("#selected", ListView)
        item = view.highlighted_child
        if not isinstance(item, PackageItem):
            return
        name = item.package.get("name", "")
        self.config.packages = [p for p in self.config.packages if p.name != name]
        core.save_config(self.config)
        self.write_log(Text.from_markup(tr("remove.done", name=name)))
        self._schedule_refresh_selected()

    def clear_selected(self) -> None:
        if not self.config.packages:
            return
        self.config.packages.clear()
        core.save_config(self.config)
        self.write_log(Text.from_markup(tr("clear.done")))
        self._schedule_refresh_selected()

    # ---------------------------------------------------------------- build

    @work(exclusive=True, group="build")
    async def build_iso(self) -> None:
        if self._busy:
            return
        self.set_busy(True)
        self.status(tr("build.status"))
        log = self.query_one("#log", RichLog)
        log.clear()
        core.LOG_DIR.mkdir(parents=True, exist_ok=True)
        log_path = core.LOG_DIR / time.strftime("build-%Y%m%d-%H%M%S.log")
        self._current_log = log_path.open("w", encoding="utf-8")
        self.write_log(Text(tr("build.log", path=log_path)))

        def thread_log(message: str) -> None:
            self.call_from_thread(self.write_log, Text(str(message)))

        try:
            iso = await asyncio.to_thread(core.run_build, self.config, thread_log)
            if iso is not None:
                self.write_log(Text.from_markup(f"[bold green]ISO:[/bold green] {iso}"))
                self.status(tr("build.done_status", name=iso.name))
            else:
                self.status(tr("build.done_no_iso"))
        except Exception as error:  # noqa: BLE001 - show any failure in the TUI
            self.write_log(Text.from_markup(f"[bold red]ERROR:[/bold red] {error}"))
            self.status(tr("build.error_status"))
        finally:
            if self._current_log is not None:
                self._current_log.close()
                self._current_log = None
            self.set_busy(False)
