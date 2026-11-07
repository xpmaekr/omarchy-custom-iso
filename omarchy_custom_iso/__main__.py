#!/usr/bin/env python3
"""Entry point: TUI by default, small CLI helpers for debugging."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from . import __version__, core, i18n
from .i18n import tr


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="omarchy-custom-iso",
        description="Build an Omarchy ISO with preinstalled AUR and repository apps.",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    parser.add_argument("--check", action="store_true", help="show the environment and exit")
    parser.add_argument("--search", metavar="QUERY", help="search AUR and Arch repositories")
    parser.add_argument("--verify", metavar="PACKAGE", help="check that a package exists")
    parser.add_argument("--prepare", action="store_true", help="generate the patched build root and exit")
    parser.add_argument("--list", action="store_true", help="list the selected packages")
    parser.add_argument("--build", action="store_true", help="build the ISO without the TUI")
    args = parser.parse_args(argv)

    config = core.load_config()
    i18n.set_language(config.language or i18n.DEFAULT_LANGUAGE)

    if args.check:
        for line in core.environment_report(Path(config.repo_dir).expanduser()):
            print(line)
        print(tr("cli.config", path=core.CONFIG_FILE))
        print(tr("cli.builds", path=core.STATE_DIR))
        return 0

    if args.search:
        for item in core.search_packages(args.search):
            print(
                f"{item['source']:5} {item['name']:40} {item.get('version', ''):20} "
                f"{item.get('description', '')[:70]}"
            )
        return 0

    if args.verify:
        result = core.verify_package(args.verify)
        if result is None:
            print(tr("cli.not_found"))
            return 1
        if result.get("source") == "unsupported":
            print(
                tr("cli.unsupported", repo=result.get("repo")),
                file=sys.stderr,
            )
            return 2
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0

    if args.list:
        for package in config.packages:
            print(f"{package.source:5} {package.name} {package.version}")
        return 0

    if args.prepare:
        core.prepare_build_root(Path(config.repo_dir).expanduser(), print)
        print(tr("cli.buildroot_ready"))
        return 0

    if args.build:
        try:
            iso = core.run_build(config, lambda line: print(line, flush=True))
        except RuntimeError as error:
            print(f"ERROR: {error}", file=sys.stderr)
            return 1
        except KeyboardInterrupt:
            print(tr("build.interrupted"), file=sys.stderr)
            return 130
        if iso is None:
            print(tr("build.iso_not_found"), file=sys.stderr)
            return 1
        print(tr("build.iso", path=iso))
        return 0

    from .app import LanguagePickerApp, OmarchyCustomISOApp

    if config.language not in i18n.LANGUAGES:
        choice = LanguagePickerApp().run()
        config.language = i18n.set_language(choice)
        core.save_config(config)
        i18n.set_language(config.language)

    OmarchyCustomISOApp().run()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
