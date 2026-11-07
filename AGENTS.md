# AGENTS.md — Omarchy Custom ISO

## What this project is

TUI-приложение на Textual, которое собирает кастомный ISO Omarchy с
предустановленными приложениями из AUR (и обычных репозиториев Arch).

**Расположение проекта:** `/home/nazk/omarchy-custom-iso`
**Репозиторий:** `https://github.com/xpmaekr/omarchy-custom-iso`
**Версия:** 1.0.0 (`omarchy_custom_iso/__init__.py`)

Запуск:

```bash
cd ~/omarchy-custom-iso
./omarchy-custom-iso
```

Проверка без TUI:

```bash
./omarchy-custom-iso --check
./omarchy-custom-iso --search telegram
./omarchy-custom-iso --verify telegram-desktop-bin
./omarchy-custom-iso --prepare
./omarchy-custom-iso --list
./omarchy-custom-iso --build      # полная сборка ISO без TUI
./omarchy-custom-iso --version
```

Тесты (без сети, pacman, paru и Docker):

```bash
python3 -m unittest discover -s tests -v   # 18 тестов
```

## Главное правило: всё документировать здесь

Любое изменение по проекту (код, конфиги, патчи, зависимости, поведение,
команды запуска, известные проблемы и их решения) сразу записывать в этот
файл. Не оставлять знания только в чате: контекст сессии заканчивается.
Обновлять при изменениях разделы «Текущий статус», «Ключевые файлы»,
«Известные ограничения / следующие шаги» и «Старые попытки».

## Текущий статус

- TUI запускается, поиск AUR/репозиториев, проверка пакетов, сохранение
  выбранных пакетов и настройки работают.
- Сборка AUR через `makepkg --nodeps` протестирована на `cmatrix-git`,
  `opencode-desktop-bin` и `pfetch`.
- Патчи `build-iso.sh` / `omarchy-iso-make` генерируются и проходят `bash -n`.
- Парсер `.SRCINFO` учитывает архитектурные makedepends
  (`makedepends_x86_64`), поэтому repo-makedepends вроде `asar` (extra)
  ставятся на хост перед `makepkg`.
- **Полная сборка ISO успешно пройдена end-to-end** через `--build` в
  изолированных XDG-каталогах (`/tmp/opencode/oci-e2e/...`, пакеты
  pfetch из AUR + cmatrix из репозитория). Лог: `/tmp/opencode/e2e-build5.log`,
  ISO: `/home/nazk/omarchy-iso-build/release/omarchy-2026.11.07-x86_64-quattro.iso`
  (6.2G). Проверено по образу: в root image (`omarchy-root` subvolume,
  `var/lib/pacman/local`) есть `cmatrix-2.0-4` и `pfetch-1.11.0-1`,
  бинарники `/usr/bin/cmatrix` и `/usr/bin/pfetch` на месте. Live
  `airootfs.sfs` их не содержит — это нормально, приложения ставятся в
  целевую систему. Во время отладки были два сбоя окружения: потерянный
  лог Docker-клиента (контейнер продолжил работу) и разовый
  `paru -G ... corrupted double-linked list`; повторный запуск прошёл.
  Для длинных прогонов дублировать лог контейнера через `docker logs -f`.
- **Критический фикс**: `buildroot/builder/` теперь реальная копия
  (`shutil.copytree`), а не ферма симлинков. Docker монтирует каталог внутрь
  контейнера, где абсолютные симлинки на хост-пути не работают — первая
  сборка падала на `/builder/node-release.sh: No such file or directory`.
  После фикса `node-release.sh` — настоящий файл, симлинков в `builder/` нет.
- Добавлен неинтерактивный режим `--build` (использует `core.run_build`).
- Добавлены офлайн-тесты (18), CI (Python 3.10/3.12/3.13) и release-workflow
  по тегу `v*`.
- Добавлены `pyproject.toml`, `LICENSE` (MIT), `CHANGELOG.md`, `.gitignore`,
  `.gitattributes`, `README.en.md`, `docs/screenshot.svg`.
- Проект опубликован: https://github.com/xpmaekr/omarchy-custom-iso
  (ветка `main`, автор `xpmaekr <263990399+xpmaekr@users.noreply.github.com>`).
- Релиз `v1.0.0` создан, GitHub Actions собрал wheel и sdist:
  https://github.com/xpmaekr/omarchy-custom-iso/releases/tag/v1.0.0
  CI и Release workflow завершились успешно.
- GitHub CLI (`gh`) установлен и авторизован под аккаунтом `xpmaekr`;
  `gh auth setup-git` настроен для push по HTTPS.
- Пароль sudo по умолчанию теперь пустой: пустое поле — обычный запрос sudo.

## Ключевые файлы

```
omarchy-custom-iso/
├── omarchy-custom-iso          # bash-лаунчер (python3 -m omarchy_custom_iso)
├── pyproject.toml              # пакет, entry point, textual>=0.80
├── README.md                   # документация (RU)
├── README.en.md                # документация (EN)
├── CHANGELOG.md                # история версий
├── LICENSE                     # MIT
├── docs/screenshot.svg         # скриншот TUI для README
├── tests/test_core.py          # 18 офлайн-тестов
├── .github/workflows/          # ci.yml, release.yml
├── AGENTS.md                   # этот файл
└── omarchy_custom_iso/
    ├── __init__.py             # __version__ = "1.0.0"
    ├── __main__.py             # CLI: --check/--search/--verify/--prepare/
    │                           #      --list/--build/--version
    ├── app.py                  # Textual UI, настройки, запуск run_build в потоке
    ├── core.py                 # AUR RPC, поиск, патчи, makepkg, run_build
    └── i18n.py                 # строки RU/EN
```

## Главный принцип: upstream не трогаем

Checkout `~/omarchy-iso-build` **не модифицируется**. `core.prepare_build_root()`
создаёт `~/.cache/omarchy-custom-iso/buildroot`:

- `buildroot/builder/` — **реальная копия** upstream `builder/`
  (`shutil.copytree(..., symlinks=False)`), в которой заменён `build-iso.sh`
  на патченную версию. Копия нужна потому, что каталог монтируется в
  Docker-контейнер, где симлинки на хост-пути не разрешаются.
- `buildroot/bin/omarchy-iso-make` — патченная копия upstream-скрипта;
- `buildroot/archiso`, `buildroot/configs`, `buildroot/release` — симлинки
  (Docker разрешает источник bind-mount на хосте).

Затем запускается `buildroot/bin/omarchy-iso-make` с `cwd =
~/omarchy-iso-build`. Поэтому `BUILD_ROOT` внутри скрипта указывает на
buildroot, а `git submodule update` и `lint_file_permissions` работают на
настоящем checkout.

`--keep-pkg-cache --no-boot-offer` передаются всегда, чтобы не чистить
host-кэш pacman и не вызывать `gum` в конце.

## Как пакеты попадают в ISO

1. AUR RPC (`https://aur.archlinux.org/rpc/v5`) ищет/проверяет пакеты.
2. Репозиторные пакеты проверяются через **отдельный pacman-конфиг**
   `~/.config/omarchy-custom-iso/pacman-arch-only.conf`
   (только `core`, `extra`, `multilib`, без CachyOS-репозиториев).
   Это важно: на CachyOS `pacman -Si firefox` отвечает `cachyos-extra-v3`,
   хотя в ISO есть Arch `extra`. Не менять на обычный `pacman -Si`.
3. Для AUR рекурсивно собирается closure из `Depends` + `MakeDepends`.
4. `paru -G` клонирует PKGBUILD в `~/.cache/omarchy-custom-iso/aur-clone`.
5. `core.build_aur_packages()` собирает каждый пакет через
   `makepkg -f --nodeps --nocheck --noconfirm --noprogressbar`.
   **Не использовать `paru -B`** для этой задачи: он разрешает и пытается
   установить runtime-зависимости, падает на конфликтах (например
   `cmatrix-git` vs установленный `cmatrix`) и засоряет хост.
6. Repo-makedepends ставятся `sudo pacman -S --needed --asdeps`.
   AUR-makedepends, которые реально нужны для сборки, ставятся после сборки
   через `sudo pacman -U --needed --asdeps`. Сами выбранные приложения
   на хост не устанавливаются.
7. `PKGDEST` указывает в `~/.cache/omarchy-custom-iso/aur-artifacts`;
   `collect_artifacts()` копирует готовые `*.pkg.tar.zst` в
   `~/.cache/omarchy-custom-iso/packages` (debug-пакеты исключаются).
8. Patched `build-iso.sh` монтирует эту папку как `/custom-packages`:
   - копирует архивы в offline mirror;
   - читает `.PKGINFO`, добавляет repo-зависимости в `all_packages`;
   - добавляет файлы в `required_package_files` (чтобы prune их не удалил);
   - добавляет имена пакетов в `image_package_list()` → они попадают в root
     image, то есть предустанавливаются;
   - repo-пакеты передаются через env `OMARCHY_CUSTOM_REPO_PACKAGES` и тоже
     добавляются в mirror + image.

## Патчи и их якоря (core.py)

Все патчи — строковые вставки в `core.py`:

- `CUSTOM_BLOCK` — после создания `offline_mirror_dir`;
- `REPO_ADD_BLOCK` — перед `mkdir -p /tmp/offlinedb`;
- `DEP_BLOCK` — после `pacman ... -Sy --dbpath /tmp/offlinedb`;
- `REQUIRED_BLOCK` — перед `prune-offline-mirror.sh`;
- `IMAGE_INSERT` — в `image_package_list()`;
- `patch_iso_make()` — добавление bind-mount `/custom-packages` и замена
  `DOCKER=(sudo docker)` на `DOCKER=("${OMARCHY_SUDO_WRAPPER:-sudo}" docker)`.

`_replace_once()` проверяет, что якорь встречается ровно один раз. Если
upstream изменит `build-iso.sh`, приложение явно упадёт с понятной ошибкой —
это защита от тихой поломки. Тогда нужно обновить якоря в `core.py`.
`prepare_build_root()` также проверяет наличие `archiso` и `configs` в
checkout (`core.checkout_incomplete`).

## Пароль sudo

Пароль **не имеет значения по умолчанию** (`DEFAULT_SUDO_PASSWORD = ""`).
Поле в настройках необязательное; при пустом значении wrapper просто делает
`exec /usr/bin/sudo "$@"` (обычный запрос пароля). Если пароль задан, он
хранится в `~/.config/omarchy-custom-iso/config.json` (0600). Для
неинтерактивных вызовов создаются:

- `~/.cache/omarchy-custom-iso/sudo-password` (0600);
- `~/.cache/omarchy-custom-iso/sudo-wrapper.sh` (0700), который при непустом
  пароле делает `cat password | sudo -S -p '' "$@"`, иначе `exec sudo`.

`OMARCHY_SUDO_WRAPPER` и `OMARCHY_SUDO_PASSWORD_FILE` передаются в
patched `omarchy-iso-make`, поэтому Docker через sudo тоже работает.

## Конфиг и кэш

| Путь | Назначение |
| --- | --- |
| `~/.config/omarchy-custom-iso/config.json` | repo_dir, пароль, язык, выбранные пакеты |
| `~/.config/omarchy-custom-iso/pacman-arch-only.conf` | проверка repo-пакетов |
| `~/.cache/omarchy-custom-iso/buildroot` | копия builder + патчи + симлинки |
| `~/.cache/omarchy-custom-iso/packages` | готовые AUR-пакеты для ISO |
| `~/.cache/omarchy-custom-iso/aur-clone` | PKGBUILD/исходники |
| `~/.cache/omarchy-custom-iso/aur-artifacts` | вывод makepkg |
| `~/.local/state/omarchy-custom-iso/logs` | журналы сборок |

## Известные ограничения / следующие шаги

1. Полная сборка ISO проверена (см. «Текущий статус»): pfetch и cmatrix
   есть в установленной системе (root image), repo-пакет cmatrix не
   собирался через makepkg.
2. Проверить сценарий repo-пакета на чужом примере (например `firefox`) —
   он не должен собираться, только попасть в image.
3. Проверить пакет с AUR-зависимостью (не только одиночные `-bin`/скрипты).
4. Docker на этой машине работает только через sudo (в `--check` пишет
   «через sudo»). Wrapper это покрывает; полный прогон проверен.
5. Первая сборка ISO скачивает Docker image и гигабайты пакетов, может идти
   десятки минут.
6. UI: при желании добавить настройку extra-аргументов `omarchy-iso-make`
   (поле `extra_build_args` в конфиге уже есть).
7. После изменений: `git push` + при необходимости новый тег `v*` (Release
   workflow сам соберёт артефакты). Перед тегом обновить версию в
   `omarchy_custom_iso/__init__.py` и `CHANGELOG.md`.

## Старые попытки

Старые файлы (`omarchy-tui.py`, `aur_packages/`, `custom_repo/`,
`install-omarchy-tui.sh`) перемещены в:
`/home/nazk/.omarchy-custom-iso-backup-20261108-005407/`
Они больше не используются. Upstream checkout чист (`git status` пуст).

Полный бэкап проекта перед релизной правкой:
`/home/nazk/.omarchy-custom-iso-backup-20261108-013010/`
