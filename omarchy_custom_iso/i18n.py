#!/usr/bin/env python3
"""Tiny translation layer for the TUI, CLI and build log."""

from __future__ import annotations

LANGUAGES = {"en": "English", "ru": "Русский"}
DEFAULT_LANGUAGE = "ru"
_current = DEFAULT_LANGUAGE


def set_language(language: str | None) -> str:
    global _current
    _current = language if language in LANGUAGES else DEFAULT_LANGUAGE
    return _current


def get_language() -> str:
    return _current


MESSAGES: dict[str, dict[str, str]] = {
    "en": {
        # app / UI
        "app.subtitle": "search AUR → select → build ISO with preinstalled apps",
        "binding.quit": "Quit",
        "binding.build": "Build ISO",
        "binding.settings": "Settings",
        "binding.search": "Search",
        "binding.remove": "Remove",
        "settings.title": "[b]Build settings[/b]",
        "settings.repo_dir": "omarchy-iso checkout directory:",
        "settings.sudo_password": "sudo password (stored locally only, file mode 0600):",
        "settings.language": "Language:",
        "common.cancel": "Cancel",
        "common.save": "Save",
        "common.add": "Add",
        "common.remove": "Remove",
        "common.clear": "Clear",
        "common.build_iso": "Build ISO",
        "search.title": "[b]Package search[/b] (AUR and Arch repositories)",
        "search.placeholder": "for example: telegram-desktop-bin",
        "search.find": "Search",
        "selected.title": "[b]Selected applications[/b]",
        "log.title": "[b]Log[/b]",
        "welcome": "Omarchy Custom ISO",
        "hint.select": (
            "Select packages on the left and press “Add”. "
            "AUR packages will be built locally, then the ISO build starts."
        ),
        "status.selected": "Selected: {count}  (AUR: {aur}, repo: {repo})",
        "pkg.already_selected": "[yellow]{name} is already selected.[/yellow]",
        "pkg.added": "[green]Added:[/green] {name} ({source})",
        "settings.saved": "[green]Settings saved.[/green] Checkout: {repo}",
        "search.starting": "Searching: {query} …",
        "search.log": "[b]Search:[/b] {query}",
        "search.nothing": "[yellow]Nothing found.[/yellow]",
        "search.nothing_status": "Nothing found",
        "search.found": (
            "[green]Found {count}[/green] (AUR: {aur}, repo: {repo}). "
            "Enter on a result adds the package."
        ),
        "search.found_status": "Found: {count}",
        "verify.checking": "Checking: {name} …",
        "verify.not_found": (
            "[red]Package {name} was not found in AUR or Arch repositories.[/red]"
        ),
        "verify.not_found_status": "Package not found",
        "verify.unsupported": (
            "[red]{name} is only in repository {repo}[/red], which is not present "
            "in the Omarchy ISO. Choose an AUR package."
        ),
        "verify.unsupported_status": "Unsupported repository",
        "remove.done": "[yellow]Removed:[/yellow] {name}",
        "clear.done": "[yellow]Selected list cleared.[/yellow]",
        "build.status": "Building…",
        "build.header": "=== Building a custom Omarchy ISO ===",
        "build.checkout": "Checkout: {repo}",
        "build.log": "Log: {path}",
        "build.no_iso_make": "No bin/omarchy-iso-make in {repo}",
        "build.no_packages": "No packages selected",
        "build.verifying": "Verifying selected packages…",
        "build.pkg_gone": "Package {name} is no longer available",
        "build.pkg_unsupported": (
            "Package {name} is only in repository {repo}, which is not in the ISO"
        ),
        "build.aur_building": (
            "Building AUR packages (makepkg --nodeps, selected apps are not "
            "installed on the host)…"
        ),
        "build.built": "Built packages: {names}",
        "build.no_aur": "No AUR packages: repository packages only.",
        "build.preparing": "Preparing the build root and patching build scripts…",
        "build.running": "=== Running omarchy-iso-make ===",
        "build.exit_code": "omarchy-iso-make exited with code {code}",
        "build.done": "=== Build finished ===",
        "build.iso": "ISO: {path}",
        "build.done_status": "Done: {name}",
        "build.iso_not_found": "ISO not found in the release directory, check the log.",
        "build.done_no_iso": "Build finished, ISO not found",
        "build.interrupted": "Build interrupted",
        "build.error_status": "Error — see the log",
        "language.picker_title": "Omarchy Custom ISO",
        "language.prompt": "Choose interface language / Выберите язык интерфейса",
        "language.english": "English",
        "language.russian": "Русский",
        # core / build log
        "core.launch_failed": "failed to start {cmd}: {error}",
        "core.srcinfo_failed": "makepkg --printsrcinfo failed in {directory}: {stderr}",
        "core.aur_for_build": "AUR packages to build: {names}",
        "core.repo_deps": "Repository dependencies: {names}",
        "core.paru_get_failed": "paru -G failed",
        "core.paru_no_pkgbuild": "paru -G did not create any directory with a PKGBUILD",
        "core.srcinfo_no_pkgname": "no pkgname in {directory}/.SRCINFO",
        "core.build_order": "Build order: {names}",
        "core.install_repo_dep": "Installing repository build dependency: {dep}",
        "core.install_repo_dep_failed": "WARNING: failed to install build dependency {dep}",
        "core.makepkg_failed": "makepkg failed in {directory}",
        "core.install_built_dep": "Installing build dependency: {names}",
        "core.install_built_dep_failed": (
            "WARNING: failed to install build dependency {names}"
        ),
        "core.not_built": "Packages not built: {names}",
        "core.patch_failed": (
            "Failed to patch a build script ({label}): template found {count} time(s). "
            "The upstream script appears to have changed."
        ),
        "core.checkout_missing": (
            "omarchy-iso checkout not found in {repo} "
            "(bin/omarchy-iso-make and builder/build-iso.sh are required)"
        ),
        "core.checkout_incomplete": (
            "omarchy-iso checkout in {repo} is incomplete: missing {missing}"
        ),
        "core.buildroot_ready": "Temporary build root ready: {path}",
        # environment report / CLI
        "env.checkout_found": "Checkout omarchy-iso: {repo} found",
        "env.checkout_missing": "Checkout omarchy-iso: {repo} NOT found",
        "env.paru_missing": "paru: NOT found",
        "env.none": "none",
        "env.docker_available": "docker: available",
        "env.docker_via_sudo": "docker: via sudo",
        "env.pacman_missing": "pacman: NOT found",
        "cli.config": "Config: {path}",
        "cli.builds": "Builds: {path}",
        "cli.not_found": "not found",
        "cli.unsupported": (
            "only available in repository {repo}, which is not in the ISO"
        ),
        "cli.buildroot_ready": "build root ready",
    },
    "ru": {
        # app / UI
        "app.subtitle": "поиск AUR → выбор → сборка ISO с предустановленными приложениями",
        "binding.quit": "Выход",
        "binding.build": "Собрать ISO",
        "binding.settings": "Настройки",
        "binding.search": "Поиск",
        "binding.remove": "Убрать",
        "settings.title": "[b]Настройки сборки[/b]",
        "settings.repo_dir": "Каталог checkout omarchy-iso:",
        "settings.sudo_password": "Пароль sudo (используется только локально, файл 0600):",
        "settings.language": "Язык:",
        "common.cancel": "Отмена",
        "common.save": "Сохранить",
        "common.add": "Добавить",
        "common.remove": "Убрать",
        "common.clear": "Очистить",
        "common.build_iso": "Собрать ISO",
        "search.title": "[b]Поиск пакетов[/b] (AUR и репозитории Arch)",
        "search.placeholder": "например: telegram-desktop-bin",
        "search.find": "Найти",
        "selected.title": "[b]Выбранные приложения[/b]",
        "log.title": "[b]Журнал[/b]",
        "welcome": "Omarchy Custom ISO",
        "hint.select": (
            "Выберите пакеты слева и нажмите «Добавить». "
            "AUR-пакеты будут собраны локально, затем запустится сборка ISO."
        ),
        "status.selected": "Выбрано: {count}  (AUR: {aur}, repo: {repo})",
        "pkg.already_selected": "[yellow]{name} уже выбран.[/yellow]",
        "pkg.added": "[green]Добавлен:[/green] {name} ({source})",
        "settings.saved": "[green]Настройки сохранены.[/green] Checkout: {repo}",
        "search.starting": "Поиск: {query} …",
        "search.log": "[b]Поиск:[/b] {query}",
        "search.nothing": "[yellow]Ничего не найдено.[/yellow]",
        "search.nothing_status": "Ничего не найдено",
        "search.found": (
            "[green]Найдено {count}[/green] (AUR: {aur}, repo: {repo}). "
            "Enter на результате добавляет пакет."
        ),
        "search.found_status": "Найдено: {count}",
        "verify.checking": "Проверка: {name} …",
        "verify.not_found": (
            "[red]Пакет {name} не найден ни в AUR, ни в репозиториях Arch.[/red]"
        ),
        "verify.not_found_status": "Пакет не найден",
        "verify.unsupported": (
            "[red]{name} есть только в репозитории {repo}[/red], "
            "которого нет в ISO Omarchy. Выберите AUR-пакет."
        ),
        "verify.unsupported_status": "Неподдерживаемый репозиторий",
        "remove.done": "[yellow]Удалён:[/yellow] {name}",
        "clear.done": "[yellow]Список выбранных очищен.[/yellow]",
        "build.status": "Сборка…",
        "build.header": "=== Сборка пользовательского ISO Omarchy ===",
        "build.checkout": "Checkout: {repo}",
        "build.log": "Журнал: {path}",
        "build.no_iso_make": "В {repo} нет bin/omarchy-iso-make",
        "build.no_packages": "Не выбрано ни одного пакета",
        "build.verifying": "Проверяю выбранные пакеты…",
        "build.pkg_gone": "Пакет {name} больше не найден",
        "build.pkg_unsupported": (
            "Пакет {name} есть только в репозитории {repo}, которого нет в ISO"
        ),
        "build.aur_building": (
            "Собираю AUR-пакеты (makepkg --nodeps, выбранные приложения "
            "на хост не ставятся)…"
        ),
        "build.built": "Готовые пакеты: {names}",
        "build.no_aur": "AUR-пакетов нет: только пакеты из репозиториев.",
        "build.preparing": "Готовлю build root и патчу скрипты сборки…",
        "build.running": "=== Запуск omarchy-iso-make ===",
        "build.exit_code": "omarchy-iso-make завершился с кодом {code}",
        "build.done": "=== Сборка завершена ===",
        "build.iso": "ISO: {path}",
        "build.done_status": "Готово: {name}",
        "build.iso_not_found": "ISO не найден в каталоге release, проверьте журнал.",
        "build.done_no_iso": "Сборка завершена, ISO не найден",
        "build.interrupted": "Сборка прервана",
        "build.error_status": "Ошибка — смотрите журнал",
        "language.picker_title": "Omarchy Custom ISO",
        "language.prompt": "Choose interface language / Выберите язык интерфейса",
        "language.english": "English",
        "language.russian": "Русский",
        # core / build log
        "core.launch_failed": "не удалось запустить {cmd}: {error}",
        "core.srcinfo_failed": "makepkg --printsrcinfo не сработал в {directory}: {stderr}",
        "core.aur_for_build": "AUR для сборки: {names}",
        "core.repo_deps": "Зависимости из репозиториев: {names}",
        "core.paru_get_failed": "paru -G завершился с ошибкой",
        "core.paru_no_pkgbuild": "paru -G не создал ни одного каталога с PKGBUILD",
        "core.srcinfo_no_pkgname": "в {directory}/.SRCINFO нет pkgname",
        "core.build_order": "Порядок сборки: {names}",
        "core.install_repo_dep": "Ставлю build-зависимость из репозитория: {dep}",
        "core.install_repo_dep_failed": (
            "WARNING: не удалось установить build-зависимость {dep}"
        ),
        "core.makepkg_failed": "makepkg завершился с ошибкой в {directory}",
        "core.install_built_dep": "Ставлю build-зависимость: {names}",
        "core.install_built_dep_failed": (
            "WARNING: не удалось установить build-зависимость {names}"
        ),
        "core.not_built": "Не собраны пакеты: {names}",
        "core.patch_failed": (
            "Не удалось применить патч к скрипту сборки ({label}): "
            "шаблон найден {count} раз(а). "
            "Похоже, upstream-скрипт изменился."
        ),
        "core.checkout_missing": (
            "Не найден checkout omarchy-iso в {repo} "
            "(нужны bin/omarchy-iso-make и builder/build-iso.sh)"
        ),
        "core.checkout_incomplete": (
            "Checkout omarchy-iso в {repo} неполный: нет {missing}"
        ),
        "core.buildroot_ready": "Временный build root готов: {path}",
        # environment report / CLI
        "env.checkout_found": "Checkout omarchy-iso: {repo} найден",
        "env.checkout_missing": "Checkout omarchy-iso: {repo} НЕ найден",
        "env.paru_missing": "paru: НЕ найден",
        "env.none": "нет",
        "env.docker_available": "docker: доступен",
        "env.docker_via_sudo": "docker: через sudo",
        "env.pacman_missing": "pacman: НЕ найден",
        "cli.config": "Конфиг: {path}",
        "cli.builds": "Сборки: {path}",
        "cli.not_found": "не найден",
        "cli.unsupported": (
            "есть только в репозитории {repo}, которого нет в ISO"
        ),
        "cli.buildroot_ready": "build root готов",
    },
}


def tr(key: str, **kwargs: object) -> str:
    text = MESSAGES.get(_current, MESSAGES[DEFAULT_LANGUAGE]).get(key)
    if text is None:
        text = MESSAGES[DEFAULT_LANGUAGE].get(key, key)
    return text.format(**kwargs) if kwargs else text
