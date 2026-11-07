#!/usr/bin/env python3
"""Core helpers for the Omarchy custom ISO builder.

Nothing in here touches the upstream omarchy-iso checkout.  The build is run
through a generated "build root" full of symlinks: patched copies of
bin/omarchy-iso-make, builder/build-iso.sh and builder/build-root-image.sh
live in a temporary directory, everything else points back at the real
checkout.  That keeps the upstream git tree clean (no backups to restore, no
diffs to resolve after a pull).

The patched scripts learn two things:

  * packages mounted at /custom-packages are copied into the offline mirror,
    their repository dependencies are pulled into the mirror, and the packages
    are added to the root filesystem image (so they are preinstalled);
  * names in $OMARCHY_CUSTOM_REPO_PACKAGES are added to the mirror and to the
    root image too (for normal repository packages).

The root image patch also switches Russian layouts with Alt+Shift instead of
Omarchy's Left Alt + Right Alt.
"""

from __future__ import annotations

import json
import os
import platform
import re
import shlex
import shutil
import subprocess
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable, Optional

from . import __version__
from .i18n import tr

AUR_RPC = "https://aur.archlinux.org/rpc/v5"
ISO_REPOS = {"core", "extra", "multilib", "omarchy"}
DEFAULT_REPO_DIR = Path.home() / "omarchy-iso-build"
DEFAULT_SUDO_PASSWORD = ""

CONFIG_HOME = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
CACHE_HOME = Path(os.environ.get("XDG_CACHE_HOME", Path.home() / ".cache"))
STATE_HOME = Path(os.environ.get("XDG_STATE_HOME", Path.home() / ".local/state"))

CONFIG_DIR = CONFIG_HOME / "omarchy-custom-iso"
CONFIG_FILE = CONFIG_DIR / "config.json"
ARCH_ONLY_PACMAN_CONF = CONFIG_DIR / "pacman-arch-only.conf"

STATE_DIR = CACHE_HOME / "omarchy-custom-iso"
PACKAGES_DIR = STATE_DIR / "packages"
CLONE_DIR = STATE_DIR / "aur-clone"
ARTIFACTS_DIR = STATE_DIR / "aur-artifacts"
BUILDROOT_DIR = STATE_DIR / "buildroot"
PASSWORD_FILE = STATE_DIR / "sudo-password"
SUDO_WRAPPER = STATE_DIR / "sudo-wrapper.sh"
LOG_DIR = STATE_HOME / "omarchy-custom-iso" / "logs"

USER_AGENT = f"omarchy-custom-iso/{__version__}"


# ---------------------------------------------------------------------------
# Package records and configuration
# ---------------------------------------------------------------------------


@dataclass
class Package:
    name: str
    source: str = "aur"  # "aur" or "repo"
    version: str = ""
    description: str = ""
    repo: str = ""

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "source": self.source,
            "version": self.version,
            "description": self.description,
            "repo": self.repo,
        }

    @classmethod
    def from_dict(cls, raw: dict) -> "Package":
        return cls(
            name=str(raw.get("name", "")).strip(),
            source=str(raw.get("source", "aur")),
            version=str(raw.get("version", "")),
            description=str(raw.get("description", "")),
            repo=str(raw.get("repo", "")),
        )


@dataclass
class Config:
    repo_dir: str = str(DEFAULT_REPO_DIR)
    sudo_password: str = DEFAULT_SUDO_PASSWORD
    extra_build_args: list[str] = field(default_factory=list)
    packages: list[Package] = field(default_factory=list)
    language: str = ""

    def to_dict(self) -> dict:
        return {
            "repo_dir": self.repo_dir,
            "sudo_password": self.sudo_password,
            "extra_build_args": self.extra_build_args,
            "packages": [p.to_dict() for p in self.packages],
            "language": self.language,
        }

    @classmethod
    def from_dict(cls, raw: dict) -> "Config":
        packages = []
        for item in raw.get("packages", []):
            try:
                packages.append(Package.from_dict(item))
            except Exception:
                continue
        return cls(
            repo_dir=str(raw.get("repo_dir", DEFAULT_REPO_DIR)),
            sudo_password=str(raw.get("sudo_password", DEFAULT_SUDO_PASSWORD)),
            extra_build_args=[str(a) for a in raw.get("extra_build_args", [])],
            packages=packages,
            language=str(raw.get("language", "")),
        )


def ensure_dirs() -> None:
    for path in (CONFIG_DIR, STATE_DIR, LOG_DIR):
        path.mkdir(parents=True, exist_ok=True)


def load_config() -> Config:
    ensure_dirs()
    if not CONFIG_FILE.exists():
        config = Config()
        save_config(config)
        return config
    try:
        raw = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
        return Config.from_dict(raw)
    except Exception:
        config = Config()
        save_config(config)
        return config


def save_config(config: Config) -> None:
    ensure_dirs()
    tmp = CONFIG_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(config.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")
    os.chmod(tmp, 0o600)
    tmp.replace(CONFIG_FILE)


# ---------------------------------------------------------------------------
# AUR RPC
# ---------------------------------------------------------------------------


def _http_json(url: str, timeout: float = 20.0) -> dict:
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def aur_search(query: str, limit: int = 60) -> list[dict]:
    query = query.strip()
    if not query:
        return []
    url = f"{AUR_RPC}/search/{urllib.parse.quote(query, safe='')}?by=name-desc"
    try:
        payload = _http_json(url)
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError):
        return []
    results = payload.get("results", [])
    results.sort(key=lambda r: (-int(r.get("NumVotes", 0)), r.get("Name", "")))
    return results[:limit]


def aur_info(names: Iterable[str]) -> dict[str, dict]:
    """Return AUR metadata for every name that exists in the AUR."""
    wanted = sorted({n.strip() for n in names if n and n.strip()})
    found: dict[str, dict] = {}
    for start in range(0, len(wanted), 100):
        chunk = wanted[start : start + 100]
        params = "&".join("arg[]=" + urllib.parse.quote(n, safe="") for n in chunk)
        try:
            payload = _http_json(f"{AUR_RPC}/info?{params}")
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError):
            continue
        for item in payload.get("results", []):
            name = item.get("Name")
            if name:
                found[name] = item
    return found


def aur_versions(names: Iterable[str]) -> dict[str, str]:
    return {name: str(info.get("Version", "")) for name, info in aur_info(names).items()}


# ---------------------------------------------------------------------------
# Repository search / verification
# ---------------------------------------------------------------------------


def _clean_dep(dep: str) -> str:
    """'foo>=1.2' -> 'foo'; sonames and empty strings are dropped later."""
    name = re.split(r"[<>=]", dep, maxsplit=1)[0].strip()
    return name


def _arch_pacman_conf() -> Path:
    """A pacman config with only the repositories the Omarchy ISO installs from.

    The host (CachyOS) has extra repositories, and `pacman -Si firefox` there
    answers cachyos-extra-v3 even though firefox is also in Arch's extra.  This
    config reuses the already-synced core/extra/multilib databases, so it
    answers what the ISO's pacman would see, without a network sync.
    """
    ensure_dirs()
    if not ARCH_ONLY_PACMAN_CONF.exists():
        ARCH_ONLY_PACMAN_CONF.write_text(
            "[options]\n"
            "Architecture = auto\n"
            "SigLevel = Never\n"
            "NoProgressBar\n"
            "\n"
            "[core]\n"
            "Include = /etc/pacman.d/mirrorlist\n"
            "\n"
            "[extra]\n"
            "Include = /etc/pacman.d/mirrorlist\n"
            "\n"
            "[multilib]\n"
            "Include = /etc/pacman.d/mirrorlist\n",
            encoding="utf-8",
        )
    return ARCH_ONLY_PACMAN_CONF


def _pacman(args: list[str], config: Optional[Path] = None, timeout: float = 45) -> Optional[subprocess.CompletedProcess]:
    env = dict(os.environ, LC_ALL="C", LANG="C")
    cmd = ["pacman"]
    if config is not None:
        cmd += ["--config", str(config)]
    cmd += args
    try:
        return subprocess.run(cmd, capture_output=True, text=True, env=env, timeout=timeout)
    except (OSError, subprocess.TimeoutExpired):
        return None


def _parse_info(text: str) -> dict[str, str]:
    fields: dict[str, str] = {}
    for line in text.splitlines():
        if ":" in line:
            key, value = line.split(":", 1)
            fields.setdefault(key.strip(), value.strip())
    return fields


def _repo_package_info(name: str) -> Optional[dict]:
    """Package from core/extra/multilib, i.e. something the ISO can mirror."""
    proc = _pacman(["-Si", "--", name], config=_arch_pacman_conf())
    if proc is None or proc.returncode != 0:
        return None
    fields = _parse_info(proc.stdout)
    repo = fields.get("Repository", "")
    if repo not in ISO_REPOS:
        return None
    return {
        "name": fields.get("Name", name),
        "version": fields.get("Version", ""),
        "source": "repo",
        "repo": repo,
        "description": fields.get("Description", ""),
    }


def _host_repo_package_info(name: str) -> Optional[dict]:
    """Package that exists only in a host repository the ISO does not ship."""
    proc = _pacman(["-Si", "--", name])
    if proc is None or proc.returncode != 0:
        return None
    fields = _parse_info(proc.stdout)
    repo = fields.get("Repository", "")
    if not repo or repo in ISO_REPOS:
        return None
    return {
        "name": fields.get("Name", name),
        "version": fields.get("Version", ""),
        "source": "unsupported",
        "repo": repo,
        "description": fields.get("Description", ""),
    }


def repo_search(query: str, limit: int = 60) -> list[dict]:
    query = query.strip()
    if not query:
        return []
    proc = _pacman(["-Ss", "--", query], config=_arch_pacman_conf())
    if proc is None or proc.returncode != 0:
        return []

    results: list[dict] = []
    current: Optional[dict] = None
    for line in proc.stdout.splitlines():
        if not line.strip():
            current = None
            continue
        if line[0].isspace():
            if current is not None and not current["description"]:
                current["description"] = line.strip()
            continue
        parts = line.split()
        if not parts or "/" not in parts[0]:
            current = None
            continue
        repo, name = parts[0].split("/", 1)
        if repo not in ISO_REPOS:
            current = None
            continue
        current = {
            "name": name,
            "version": parts[1] if len(parts) > 1 else "",
            "source": "repo",
            "repo": repo,
            "description": "",
        }
        results.append(current)
        if len(results) >= limit:
            break
    return results


def search_packages(query: str) -> list[dict]:
    """Search the AUR and the Arch repositories the ISO actually installs from."""
    aur_results = []
    for item in aur_search(query):
        aur_results.append(
            {
                "name": item.get("Name", ""),
                "version": str(item.get("Version", "")),
                "source": "aur",
                "repo": "aur",
                "description": item.get("Description", "") or "",
                "votes": int(item.get("NumVotes", 0) or 0),
            }
        )
    repo_results = repo_search(query)

    # Prefer a repository package when both offer the same exact name: it is
    # already part of the ISO's mirror and needs no AUR build.
    merged: dict[str, dict] = {}
    for item in repo_results:
        merged[item["name"]] = item
    for item in aur_results:
        if item["name"] not in merged:
            merged[item["name"]] = item
    return list(merged.values())


def verify_package(name: str) -> Optional[dict]:
    """Check whether a package exists in the ISO repos or in the AUR."""
    name = name.strip()
    if not name:
        return None

    repo_info = _repo_package_info(name)
    if repo_info:
        return repo_info

    info = aur_info([name]).get(name)
    if info:
        return {
            "name": info.get("Name", name),
            "version": str(info.get("Version", "")),
            "source": "aur",
            "repo": "aur",
            "description": info.get("Description", "") or "",
        }

    unsupported = _host_repo_package_info(name)
    if unsupported:
        return unsupported
    return None


# ---------------------------------------------------------------------------
# AUR dependency resolution
# ---------------------------------------------------------------------------


def resolve_aur_build_set(targets: Iterable[str]) -> tuple[list[str], list[str]]:
    """Return (AUR packages to build, repository dependencies found on the way)."""
    closure: dict[str, dict] = {}
    repository_deps: set[str] = set()
    pending = {t.strip() for t in targets if t.strip()}

    while pending:
        batch = sorted(pending)[:100]
        infos = aur_info(batch)
        nxt: set[str] = set()
        for name in batch:
            info = infos.get(name)
            if not info:
                repository_deps.add(name)
                continue
            closure[name] = info
            deps = list(info.get("Depends", []) or []) + list(info.get("MakeDepends", []) or [])
            for dep in deps:
                dep_name = _clean_dep(dep)
                if not dep_name or ".so" in dep_name:
                    continue
                if dep_name in closure or dep_name in repository_deps:
                    continue
                nxt.add(dep_name)
        pending = nxt - closure.keys()

    return sorted(closure), sorted(repository_deps)


# ---------------------------------------------------------------------------
# Host-side AUR build
# ---------------------------------------------------------------------------


def ensure_sudo_wrapper(password: str) -> Path:
    """Write a sudo wrapper that feeds the configured password on stdin.

    An empty password means "use the normal sudo prompt": the wrapper then
    execs sudo directly, so a normal passwordless or keyring-backed sudo keeps
    working without storing a secret.
    """
    ensure_dirs()
    PASSWORD_FILE.write_text(password + "\n" if password else "", encoding="utf-8")
    os.chmod(PASSWORD_FILE, 0o600)
    SUDO_WRAPPER.write_text(
        "#!/bin/sh\n"
        '# Written by omarchy-custom-iso. Feeds the configured password to sudo.\n'
        'pwfile="${OMARCHY_SUDO_PASSWORD_FILE:-' + str(PASSWORD_FILE) + '}"\n'
        'if [ -s "$pwfile" ]; then\n'
        '  cat "$pwfile" | /usr/bin/sudo -S -p \'\' "$@"\n'
        "else\n"
        '  exec /usr/bin/sudo "$@"\n'
        "fi\n",
        encoding="utf-8",
    )
    os.chmod(SUDO_WRAPPER, 0o700)
    return SUDO_WRAPPER


def sudo_env(wrapper: Path) -> dict[str, str]:
    env = dict(os.environ)
    env["OMARCHY_SUDO_WRAPPER"] = str(wrapper)
    env["OMARCHY_SUDO_PASSWORD_FILE"] = str(PASSWORD_FILE)
    return env


def docker_available() -> bool:
    try:
        return subprocess.run(
            ["docker", "version"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=20,
        ).returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        return False


def reset_dir(path: Path) -> None:
    if path.exists():
        shutil.rmtree(path)
    path.mkdir(parents=True, exist_ok=True)


def collect_artifacts(search_dirs: Iterable[Path], destination: Path) -> dict[str, Path]:
    """Copy built package archives into destination; return name -> archive path."""
    destination.mkdir(parents=True, exist_ok=True)
    seen: dict[str, Path] = {}
    for directory in search_dirs:
        if not directory.exists():
            continue
        for archive in sorted(directory.rglob("*.pkg.tar.*")):
            if archive.name.endswith(".sig"):
                continue
            if "-debug-" in archive.name:
                continue
            try:
                proc = subprocess.run(
                    ["pacman", "-Qqp", str(archive)],
                    capture_output=True,
                    text=True,
                    timeout=30,
                )
            except (OSError, subprocess.TimeoutExpired):
                continue
            if proc.returncode != 0:
                continue
            name = proc.stdout.strip().splitlines()[0] if proc.stdout.strip() else ""
            if not name:
                continue
            target = destination / archive.name
            shutil.copy2(archive, target)
            seen[name] = target
    return seen


def _run_stream(cmd: list[str], cwd: Optional[Path], env: Optional[dict], log_cb) -> int:
    """Run a command, sending every output line to log_cb, and return its code."""
    log_cb("$ " + shlex.join(cmd))
    try:
        proc = subprocess.Popen(
            cmd,
            cwd=str(cwd) if cwd else None,
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            errors="replace",
            bufsize=1,
        )
    except OSError as error:
        log_cb(tr("core.launch_failed", cmd=cmd[0], error=error))
        return 127
    assert proc.stdout is not None
    try:
        for line in proc.stdout:
            log_cb(line.rstrip("\n"))
    finally:
        proc.stdout.close()
    return proc.wait()


def _parse_srcinfo(text: str) -> tuple[list[str], set[str], set[str]]:
    """Return (pkgname list, provides, makedepends) from a .SRCINFO file."""
    pkgnames: list[str] = []
    provides: set[str] = set()
    makedepends: set[str] = set()
    arch = platform.machine() or "x86_64"
    makedepends_keys = {"makedepends", f"makedepends_{arch}"}
    for line in text.splitlines():
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip()
        if key == "pkgname":
            pkgnames.append(value)
        elif key == "provides":
            provides.add(_clean_dep(value))
        elif key in makedepends_keys:
            cleaned = _clean_dep(value)
            if cleaned:
                makedepends.add(cleaned)
    return pkgnames, provides, makedepends


def _srcinfo_text(directory: Path) -> str:
    path = directory / ".SRCINFO"
    if path.is_file():
        return path.read_text(encoding="utf-8", errors="replace")
    proc = subprocess.run(
        ["makepkg", "--printsrcinfo"],
        cwd=str(directory),
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0:
        raise RuntimeError(tr("core.srcinfo_failed", directory=directory, stderr=proc.stderr.strip()))
    path.write_text(proc.stdout, encoding="utf-8")
    return proc.stdout


def _pacman_satisfied(name: str) -> bool:
    proc = _pacman(["-T", name])
    return proc is not None and proc.returncode == 0


def _topological_dirs(
    closure_infos: dict[str, dict],
    dirs: list[Path],
    name_to_dir: dict[str, Path],
) -> list[Path]:
    deps_of: dict[str, set[str]] = {}
    for name, info in closure_infos.items():
        deps: set[str] = set()
        raw_deps = list(info.get("Depends", []) or []) + list(info.get("MakeDepends", []) or [])
        for dep in raw_deps:
            dep_name = _clean_dep(dep)
            if dep_name in closure_infos and dep_name != name:
                deps.add(dep_name)
        deps_of[name] = deps

    order: list[str] = []
    remaining = set(closure_infos)
    while remaining:
        ready = sorted(name for name in remaining if not (deps_of[name] & remaining))
        if not ready:  # dependency cycle: build what is left in a stable order
            ready = sorted(remaining)
        order.extend(ready)
        remaining -= set(ready)

    seen: set[Path] = set()
    result: list[Path] = []
    for name in order:
        directory = name_to_dir.get(name)
        if directory is not None and directory not in seen:
            seen.add(directory)
            result.append(directory)
    for directory in dirs:
        if directory not in seen:
            result.append(directory)
    return result


def build_aur_packages(targets: Iterable[str], sudo_wrapper: Path, log_cb) -> dict[str, Path]:
    """Build AUR packages (and their AUR dependencies) without installing them.

    makepkg runs with --nodeps/--nocheck, so a target never has to be installed
    on the host and conflicts with installed packages do not matter.  Build
    dependencies are the exception: repository makedepends are installed with
    pacman (asdeps) and freshly built AUR makedepends are installed before the
    packages that need them.
    """
    closure_names_list, repo_deps = resolve_aur_build_set(targets)
    closure_infos = aur_info(closure_names_list)
    if not closure_infos:
        return {}
    closure_names = set(closure_infos) | set(closure_names_list)

    log_cb(tr("core.aur_for_build", names=", ".join(sorted(closure_infos))))
    if repo_deps:
        log_cb(tr("core.repo_deps", names=", ".join(repo_deps)))

    reset_dir(CLONE_DIR)
    reset_dir(ARTIFACTS_DIR)
    reset_dir(PACKAGES_DIR)

    env = dict(os.environ)
    env["AURDEST"] = str(CLONE_DIR)
    names = sorted(closure_infos)
    for start in range(0, len(names), 20):
        chunk = names[start : start + 20]
        # --aur is required: on CachyOS some AUR names also exist in cachyos
        # repos, and without it paru -G tries `pkgctl repo clone`, which fails
        # for packages that are not in the official Arch git repositories.
        code = _run_stream(["paru", "-G", "--aur", *chunk], CLONE_DIR, env, log_cb)
        if code != 0:
            raise RuntimeError(tr("core.paru_get_failed"))

    dirs = sorted(p for p in CLONE_DIR.iterdir() if p.is_dir() and (p / "PKGBUILD").is_file())
    if not dirs:
        raise RuntimeError(tr("core.paru_no_pkgbuild"))

    info_by_dir: dict[Path, tuple[list[str], set[str], set[str]]] = {}
    name_to_dir: dict[str, Path] = {}
    build_dep_names: set[str] = set()
    closure_provides: set[str] = set()
    for directory in dirs:
        pkgnames, provides, makedepends = _parse_srcinfo(_srcinfo_text(directory))
        if not pkgnames:
            raise RuntimeError(tr("core.srcinfo_no_pkgname", directory=directory))
        info_by_dir[directory] = (pkgnames, provides, makedepends)
        for pkgname in pkgnames:
            name_to_dir[pkgname] = directory
        build_dep_names |= makedepends
        closure_provides |= provides

    ordered = _topological_dirs(closure_infos, dirs, name_to_dir)
    log_cb(tr("core.build_order", names=", ".join(d.name for d in ordered)))

    # Repository makedepends.  Installed ones and ones an AUR package in the
    # closure provides are skipped.
    for dep in sorted(build_dep_names):
        if not dep or dep in closure_names or dep in closure_provides:
            continue
        if _pacman_satisfied(dep):
            continue
        log_cb(tr("core.install_repo_dep", dep=dep))
        code = _run_stream(
            [str(sudo_wrapper), "pacman", "-S", "--needed", "--asdeps", "--noconfirm", dep],
            None,
            dict(os.environ),
            log_cb,
        )
        if code != 0:
            log_cb(tr("core.install_repo_dep_failed", dep=dep))

    for directory in ordered:
        pkgnames, provides, _ = info_by_dir[directory]
        log_cb(f"=== makepkg: {directory.name} ({', '.join(pkgnames)}) ===")
        build_env = dict(os.environ)
        build_env["PKGDEST"] = str(ARTIFACTS_DIR)
        code = _run_stream(
            [
                "makepkg",
                "-f",
                "--nodeps",
                "--nocheck",
                "--noconfirm",
                "--noprogressbar",
            ],
            directory,
            build_env,
            log_cb,
        )
        if code != 0:
            raise RuntimeError(tr("core.makepkg_failed", directory=directory.name))

        provided_names = set(pkgnames) | provides
        if not (provided_names & build_dep_names):
            continue
        produced: list[Path] = []
        for archive in ARTIFACTS_DIR.iterdir():
            if archive.name.endswith(".sig") or "-debug-" in archive.name:
                continue
            if any(archive.name.startswith(name + "-") for name in pkgnames):
                produced.append(archive)
        if produced:
            log_cb(tr("core.install_built_dep", names=", ".join(pkgnames)))
            code = _run_stream(
                [
                    str(sudo_wrapper),
                    "pacman",
                    "-U",
                    "--needed",
                    "--asdeps",
                    "--noconfirm",
                    *[str(p) for p in produced],
                ],
                None,
                dict(os.environ),
                log_cb,
            )
            if code != 0:
                log_cb(tr("core.install_built_dep_failed", names=", ".join(pkgnames)))

    built = collect_artifacts([ARTIFACTS_DIR, CLONE_DIR], PACKAGES_DIR)
    missing = [name for name in targets if name not in built]
    if missing:
        raise RuntimeError(tr("core.not_built", names=", ".join(missing)))
    return built



# ---------------------------------------------------------------------------
# Build root generation (patched copies, upstream stays untouched)
# ---------------------------------------------------------------------------


CUSTOM_BLOCK = r'''
# --- omarchy-custom-iso: custom packages -----------------------------------
custom_packages_dir="${OMARCHY_CUSTOM_PACKAGES:-}"
custom_package_names=()
custom_package_files=()
custom_repo_names=()
if [[ -n $custom_packages_dir && -d $custom_packages_dir ]]; then
  shopt -s nullglob
  for custom_archive in "$custom_packages_dir"/*.pkg.tar.*; do
    [[ $custom_archive == *.sig ]] && continue
    custom_base="${custom_archive##*/}"
    if ! custom_name=$(pacman -Qqp "$custom_archive" 2>/dev/null); then
      echo "ERROR: cannot read a package name from $custom_base" >&2
      exit 1
    fi
    cp -f "$custom_archive" "$offline_mirror_dir/"
    custom_package_files+=("$custom_base")
    custom_package_names+=("$custom_name")
  done
fi
if [[ -n ${OMARCHY_CUSTOM_REPO_PACKAGES:-} ]]; then
  read -r -a custom_repo_names <<<"${OMARCHY_CUSTOM_REPO_PACKAGES}"
fi
echo "Custom preinstall: ${#custom_package_files[@]} local package(s), ${#custom_repo_names[@]} repository package(s)"
# --- omarchy-custom-iso: custom packages end -------------------------------
'''

REPO_ADD_BLOCK = r'''
# --- omarchy-custom-iso: repository packages to preinstall -----------------
if (( ${#custom_repo_names[@]} )); then
  all_packages+=("${custom_repo_names[@]}")
  target_packages+=("${custom_repo_names[@]}")
  mapfile -t all_packages < <(printf '%s\n' "${all_packages[@]}" | sort -u)
  mapfile -t target_packages < <(printf '%s\n' "${target_packages[@]}" | sort -u)
fi
# --- omarchy-custom-iso end ------------------------------------------------
'''

DEP_BLOCK = r'''
# --- omarchy-custom-iso: repository dependencies of the local packages -----
if (( ${#custom_package_files[@]} )); then
  custom_dep_candidates=()
  for custom_file in "${custom_package_files[@]}"; do
    while IFS= read -r custom_dep; do
      custom_dep=${custom_dep%%[<>=]*}
      [[ -z $custom_dep || $custom_dep == *.so* ]] && continue
      custom_dep_candidates+=("$custom_dep")
    done < <(bsdtar -xOf "$offline_mirror_dir/$custom_file" .PKGINFO 2>/dev/null | sed -n 's/^depend = //p')
  done
  for custom_dep in $(printf '%s\n' "${custom_dep_candidates[@]}" 2>/dev/null | sort -u); do
    printf '%s\n' "${custom_package_names[@]}" | grep -Fxq "$custom_dep" && continue
    if pacman --config "$online_pacman_conf" --dbpath /tmp/offlinedb -Sp "$custom_dep" >/dev/null 2>&1; then
      all_packages+=("$custom_dep")
    fi
  done
  mapfile -t all_packages < <(printf '%s\n' "${all_packages[@]}" | sort -u)
fi
# --- omarchy-custom-iso end ------------------------------------------------
'''

REQUIRED_BLOCK = r'''
# --- omarchy-custom-iso: keep the locally built packages in the mirror -----
if (( ${#custom_package_files[@]} )); then
  required_package_files+=("${custom_package_files[@]}")
fi
# --- omarchy-custom-iso end ------------------------------------------------
'''

IMAGE_INSERT = r'''    ((${#custom_package_names[@]} == 0)) || printf '%s\n' "${custom_package_names[@]}"
    ((${#custom_repo_names[@]} == 0)) || printf '%s\n' "${custom_repo_names[@]}"
'''

ROOT_IMAGE_KEYBOARD = r'''
# --- omarchy-custom-iso: Alt+Shift switching for Russian installs ----------
# Omarchy pairs a non-Latin layout with us and toggles the pair with Left Alt +
# Right Alt. Russian users expect Alt+Shift, so use grp:alt_shift_toggle when
# the layout list contains ru. The image is static but the chosen layout is
# not, hence the runtime check in the Lua that reads /etc/vconsole.conf.
input_lua="$root/usr/share/omarchy/default/hypr/input.lua"
if [[ -f $input_lua ]]; then
  sed -i \
    -e 's|kb_options = kb_options \.\. ",grp:alts_toggle"|kb_options = kb_options .. (kb_layout:find("ru", 1, true) and ",grp:alt_shift_toggle" or ",grp:alts_toggle")|g' \
    -e 's|if not kb_options:find("grp:alts_toggle", 1, true) then|if not (kb_options:find("grp:alts_toggle", 1, true) or kb_options:find("grp:alt_shift_toggle", 1, true)) then|' \
    "$input_lua"
  if ! grep -q 'grp:alt_shift_toggle' "$input_lua"; then
    echo "WARNING: omarchy-custom-iso: could not patch the keyboard layout switch in $input_lua" >&2
  fi
fi
# --- omarchy-custom-iso end ------------------------------------------------
'''


def _replace_once(text: str, old: str, new: str, label: str) -> str:
    if text.count(old) != 1:
        raise RuntimeError(
            tr("core.patch_failed", label=label, count=text.count(old))
        )
    return text.replace(old, new, 1)


def patch_build_iso(source: str) -> str:
    text = source

    anchor = (
        'offline_mirror_dir="$build_cache_dir/airootfs/var/cache/omarchy/mirror/offline"\n'
        'mkdir -p "$build_cache_dir" "$offline_mirror_dir"\n'
    )
    text = _replace_once(text, anchor, anchor + CUSTOM_BLOCK, "custom block")

    anchor = "mkdir -p /tmp/offlinedb\n"
    text = _replace_once(text, anchor, REPO_ADD_BLOCK + "\n" + anchor, "repository list")

    anchor = (
        'pacman --config "$online_pacman_conf" --noconfirm -Sy '
        '--dbpath /tmp/offlinedb >/dev/null\n'
    )
    text = _replace_once(text, anchor, anchor + DEP_BLOCK, "dependency block")

    anchor = (
        'printf \'%s\\n\' "${required_package_files[@]}" |\n'
        '  bash /builder/prune-offline-mirror.sh "$offline_mirror_dir"\n'
    )
    text = _replace_once(text, anchor, REQUIRED_BLOCK + "\n" + anchor, "keep custom files")

    anchor = (
        '    grep -hv \'^#\\|^$\' '
        '"$build_cache_dir/airootfs/usr/share/omarchy-iso/omarchy-base.packages"\n'
        '    printf \'%s\\n\' "$OMARCHY_RUNTIME_PACKAGE" "$OMARCHY_SETTINGS_PACKAGE" '
        '"$OMARCHY_NVIM_PACKAGE"\n'
        '  } | sort -u\n'
    )
    replacement = (
        '    grep -hv \'^#\\|^$\' '
        '"$build_cache_dir/airootfs/usr/share/omarchy-iso/omarchy-base.packages"\n'
        + IMAGE_INSERT +
        '    printf \'%s\\n\' "$OMARCHY_RUNTIME_PACKAGE" "$OMARCHY_SETTINGS_PACKAGE" '
        '"$OMARCHY_NVIM_PACKAGE"\n'
        '  } | sort -u\n'
    )
    text = _replace_once(text, anchor, replacement, "image package list")

    return text


def patch_iso_make(source: str) -> str:
    text = source

    anchor = '  -v "$BUILD_ROOT/configs:/configs:ro"\n)\n'
    insertion = (
        '  -v "$BUILD_ROOT/configs:/configs:ro"\n'
        ')\n'
        '\n'
        '# omarchy-custom-iso: custom packages and repository names from the TUI.\n'
        'if [[ -n ${OMARCHY_CUSTOM_PACKAGES_DIR:-} ]]; then\n'
        '  DOCKER_ARGS+=(-v "$OMARCHY_CUSTOM_PACKAGES_DIR:/custom-packages:ro")\n'
        'fi\n'
        'DOCKER_ARGS+=(-e "OMARCHY_CUSTOM_PACKAGES=/custom-packages")\n'
        'DOCKER_ARGS+=(-e "OMARCHY_CUSTOM_REPO_PACKAGES=${OMARCHY_CUSTOM_REPO_PACKAGES:-}")\n'
    )
    text = _replace_once(text, anchor, insertion, "docker custom mount")

    anchor = "  DOCKER=(sudo docker)\n"
    replacement = '  DOCKER=("${OMARCHY_SUDO_WRAPPER:-sudo}" docker)\n'
    text = _replace_once(text, anchor, replacement, "sudo wrapper for docker")

    return text


def patch_root_image(source: str) -> str:
    """Teach the root image to switch Russian layouts with Alt+Shift."""
    anchor = (
        'installed=$(find "$root/var/lib/pacman/local" -mindepth 1 '
        '-maxdepth 1 -type d | wc -l)\n'
        'echo "Root image holds $installed packages"\n'
    )
    text = _replace_once(source, anchor, anchor + ROOT_IMAGE_KEYBOARD, "root image keyboard patch")
    return text


def prepare_build_root(repo_dir: Path, log) -> Path:
    """Create a build root with patched copies of the upstream scripts.

    ``builder/`` must be a real copy, not a symlink farm: it is bind-mounted
    into the Docker container, where absolute symlinks back into the host
    checkout do not exist.  ``archiso``, ``configs`` and ``release`` stay
    symlinks because Docker resolves the mount source on the host before the
    container starts.
    """
    repo_dir = repo_dir.resolve()
    iso_make = repo_dir / "bin" / "omarchy-iso-make"
    build_iso = repo_dir / "builder" / "build-iso.sh"
    build_root_image = repo_dir / "builder" / "build-root-image.sh"
    if not iso_make.is_file() or not build_iso.is_file() or not build_root_image.is_file():
        raise RuntimeError(tr("core.checkout_missing", repo=repo_dir))
    missing_dirs = [name for name in ("archiso", "configs") if not (repo_dir / name).is_dir()]
    if missing_dirs:
        raise RuntimeError(
            tr("core.checkout_incomplete", repo=repo_dir, missing=", ".join(missing_dirs))
        )

    reset_dir(BUILDROOT_DIR)
    bin_dir = BUILDROOT_DIR / "bin"
    builder_dir = BUILDROOT_DIR / "builder"
    bin_dir.mkdir(parents=True)

    patched_make = patch_iso_make(iso_make.read_text(encoding="utf-8"))
    (bin_dir / "omarchy-iso-make").write_text(patched_make, encoding="utf-8")
    os.chmod(bin_dir / "omarchy-iso-make", 0o755)

    shutil.copytree(repo_dir / "builder", builder_dir, symlinks=False)

    patched_iso = patch_build_iso(build_iso.read_text(encoding="utf-8"))
    (builder_dir / "build-iso.sh").write_text(patched_iso, encoding="utf-8")
    os.chmod(builder_dir / "build-iso.sh", 0o755)

    patched_root_image = patch_root_image(build_root_image.read_text(encoding="utf-8"))
    (builder_dir / "build-root-image.sh").write_text(patched_root_image, encoding="utf-8")
    os.chmod(builder_dir / "build-root-image.sh", 0o755)

    for name in ("archiso", "configs"):
        os.symlink(repo_dir / name, BUILDROOT_DIR / name)

    release = repo_dir / "release"
    release.mkdir(parents=True, exist_ok=True)
    os.symlink(release, BUILDROOT_DIR / "release")

    log(tr("core.buildroot_ready", path=BUILDROOT_DIR))
    return BUILDROOT_DIR / "bin" / "omarchy-iso-make"


def newest_iso(repo_dir: Path, newer_than: float) -> Optional[Path]:
    release = repo_dir / "release"
    if not release.is_dir():
        return None
    candidates = [p for p in release.glob("*.iso") if p.is_file() and p.stat().st_mtime >= newer_than - 2]
    if not candidates:
        return None
    return max(candidates, key=lambda p: p.stat().st_mtime)


def run_build(config: Config, log_cb) -> Optional[Path]:
    """Verify, build the AUR packages and run the patched ISO build.

    This is the whole pipeline used by both the TUI and ``--build``.  Selected
    applications are never installed on the host; only build dependencies are.
    """
    started = time.time()
    repo = Path(config.repo_dir).expanduser().resolve()

    log_cb(tr("build.header"))
    log_cb(tr("build.checkout", repo=repo))
    if not (repo / "bin" / "omarchy-iso-make").is_file():
        raise RuntimeError(tr("build.no_iso_make", repo=repo))
    if not config.packages:
        raise RuntimeError(tr("build.no_packages"))

    log_cb(tr("build.verifying"))
    verified: list[Package] = []
    for package in config.packages:
        result = verify_package(package.name)
        if result is None:
            raise RuntimeError(tr("build.pkg_gone", name=package.name))
        if result.get("source") == "unsupported":
            raise RuntimeError(
                tr("build.pkg_unsupported", name=package.name, repo=result.get("repo"))
            )
        verified.append(
            Package(
                name=str(result.get("name", package.name)),
                source=str(result.get("source", "aur")),
                version=str(result.get("version", "")),
                description=str(result.get("description", package.description)),
                repo=str(result.get("repo", "")),
            )
        )
    config.packages = verified
    save_config(config)

    aur_targets = [p.name for p in config.packages if p.source == "aur"]
    repo_names = [p.name for p in config.packages if p.source == "repo"]

    wrapper = ensure_sudo_wrapper(config.sudo_password)
    env = sudo_env(wrapper)

    if aur_targets:
        log_cb(tr("build.aur_building"))
        built = build_aur_packages(aur_targets, wrapper, log_cb)
        log_cb(tr("build.built", names=", ".join(sorted(built))))
    else:
        reset_dir(PACKAGES_DIR)
        log_cb(tr("build.no_aur"))

    log_cb(tr("build.preparing"))
    iso_make = prepare_build_root(repo, log_cb)

    iso_env = dict(env)
    iso_env["OMARCHY_CUSTOM_PACKAGES_DIR"] = str(PACKAGES_DIR)
    iso_env["OMARCHY_CUSTOM_REPO_PACKAGES"] = " ".join(repo_names)
    build_args = [
        str(iso_make),
        "--keep-pkg-cache",
        "--no-boot-offer",
        *config.extra_build_args,
    ]
    log_cb(tr("build.running"))
    code = _run_stream(build_args, repo, iso_env, log_cb)
    if code != 0:
        raise RuntimeError(tr("build.exit_code", code=code))

    iso = newest_iso(repo, started)
    log_cb(tr("build.done"))
    if iso is not None:
        log_cb(tr("build.iso", path=iso))
    else:
        log_cb(tr("build.iso_not_found"))
    return iso


# ---------------------------------------------------------------------------
# Misc
# ---------------------------------------------------------------------------


def environment_report(repo_dir: Path) -> list[str]:
    lines = []
    lines.append(
        tr("env.checkout_found" if (repo_dir / "bin/omarchy-iso-make").is_file() else "env.checkout_missing", repo=repo_dir)
    )
    try:
        paru = subprocess.run(["paru", "--version"], capture_output=True, text=True, timeout=20)
        lines.append("paru: " + (paru.stdout.splitlines()[0] if paru.stdout else tr("env.none")))
    except Exception:
        lines.append(tr("env.paru_missing"))
    lines.append(tr("env.docker_available") if docker_available() else tr("env.docker_via_sudo"))
    try:
        pacman = subprocess.run(["pacman", "-V"], capture_output=True, text=True, timeout=20)
        pacman_line = tr("env.none")
        for line in pacman.stdout.splitlines():
            if "Pacman v" in line:
                pacman_line = line[line.index("Pacman v") :].strip()
                break
        lines.append("pacman: " + pacman_line)
    except Exception:
        lines.append(tr("env.pacman_missing"))
    return lines
