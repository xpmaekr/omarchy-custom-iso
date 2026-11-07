"""Offline unit tests: no pacman, paru, docker or network access required."""

from __future__ import annotations

import json
import platform
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from omarchy_custom_iso import core, i18n


class PatchTests(unittest.TestCase):
    def test_build_iso_gets_all_pieces(self) -> None:
        source = (
            'offline_mirror_dir="$build_cache_dir/airootfs/var/cache/omarchy/mirror/offline"\n'
            'mkdir -p "$build_cache_dir" "$offline_mirror_dir"\n'
            "mkdir -p /tmp/offlinedb\n"
            'pacman --config "$online_pacman_conf" --noconfirm -Sy '
            "--dbpath /tmp/offlinedb >/dev/null\n"
            "printf '%s\\n' \"${required_package_files[@]}\" |\n"
            '  bash /builder/prune-offline-mirror.sh "$offline_mirror_dir"\n'
            "image_package_list() {\n"
            "  {\n"
            "    grep -hv '^#\\|^$' "
            '"$build_cache_dir/airootfs/usr/share/omarchy-iso/omarchy-base.packages"\n'
            '    printf \'%s\\n\' "$OMARCHY_RUNTIME_PACKAGE" '
            '"$OMARCHY_SETTINGS_PACKAGE" "$OMARCHY_NVIM_PACKAGE"\n'
            "  } | sort -u\n"
            "}\n"
        )
        patched = core.patch_build_iso(source)

        self.assertIn("custom packages", patched)
        self.assertIn("repository packages to preinstall", patched)
        self.assertIn("repository dependencies of the local packages", patched)
        self.assertIn("keep the locally built packages", patched)
        self.assertIn('printf \'%s\\n\' "${custom_package_names[@]}"', patched)
        # The anchors themselves stay in place, in their original order.
        for anchor in ("mkdir -p /tmp/offlinedb", "prune-offline-mirror.sh"):
            self.assertIn(anchor, patched)
        self.assertLess(
            patched.index("repository packages to preinstall"),
            patched.index("repository dependencies of the local packages"),
        )

    def test_missing_anchor_is_an_error(self) -> None:
        with self.assertRaises(RuntimeError):
            core.patch_build_iso("nothing to patch here\n")

    def test_iso_make_gets_mount_and_sudo_wrapper(self) -> None:
        source = (
            "  -v \"$BUILD_ROOT/configs:/configs:ro\"\n"
            ")\n"
            "\n"
            "if [[ $EUID -ne 0 ]]; then\n"
            "  DOCKER=(sudo docker)\n"
            "else\n"
            "  DOCKER=(docker)\n"
            "fi\n"
        )
        patched = core.patch_iso_make(source)

        self.assertIn('DOCKER_ARGS+=(-v "$OMARCHY_CUSTOM_PACKAGES_DIR:/custom-packages:ro")', patched)
        self.assertIn('OMARCHY_CUSTOM_REPO_PACKAGES=${OMARCHY_CUSTOM_REPO_PACKAGES:-}', patched)
        self.assertIn('DOCKER=("${OMARCHY_SUDO_WRAPPER:-sudo}" docker)', patched)

    def test_root_image_gets_russian_alt_shift(self) -> None:
        source = (
            'installed=$(find "$root/var/lib/pacman/local" -mindepth 1 '
            '-maxdepth 1 -type d | wc -l)\n'
            'echo "Root image holds $installed packages"\n'
        )
        patched = core.patch_root_image(source)

        self.assertIn("Alt+Shift switching for Russian installs", patched)
        self.assertIn('input_lua="$root/usr/share/omarchy/default/hypr/input.lua"', patched)
        self.assertIn('kb_layout:find("ru", 1, true)', patched)
        self.assertIn("grp:alt_shift_toggle", patched)
        # The anchor itself stays in place, so the image build still reports it.
        self.assertIn('echo "Root image holds $installed packages"', patched)

    def test_root_image_missing_anchor_is_an_error(self) -> None:
        with self.assertRaises(RuntimeError):
            core.patch_root_image("nothing to patch here\n")


class HelperTests(unittest.TestCase):
    def test_clean_dep(self) -> None:
        self.assertEqual(core._clean_dep("foo>=1.2"), "foo")
        self.assertEqual(core._clean_dep("bar<3"), "bar")
        self.assertEqual(core._clean_dep(" baz "), "baz")

    def test_parse_srcinfo_reads_arch_makedepends(self) -> None:
        arch = platform.machine() or "x86_64"
        text = (
            "pkgbase = demo\n"
            "pkgname = demo\n"
            "depends = libfoo\n"
            "makedepends = cmake\n"
            f"makedepends_{arch} = asar\n"
            "provides = demo-provider\n"
        )
        pkgnames, provides, makedepends = core._parse_srcinfo(text)

        self.assertEqual(pkgnames, ["demo"])
        self.assertIn("cmake", makedepends)
        self.assertIn("asar", makedepends)
        self.assertIn("demo-provider", provides)

    def test_topological_order_puts_dependencies_first(self) -> None:
        infos = {
            "app": {"Depends": ["lib>=1"]},
            "lib": {"Depends": []},
            "tool-bin": {"MakeDepends": ["app"]},
        }
        dirs = [Path("/x/app"), Path("/x/lib"), Path("/x/tool-bin")]
        name_to_dir = {
            "app": Path("/x/app"),
            "lib": Path("/x/lib"),
            "tool-bin": Path("/x/tool-bin"),
        }
        order = core._topological_dirs(infos, dirs, name_to_dir)

        self.assertLess(order.index(Path("/x/lib")), order.index(Path("/x/app")))
        self.assertLess(order.index(Path("/x/app")), order.index(Path("/x/tool-bin")))

    def test_printsrcinfo_is_cached(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            (directory / ".SRCINFO").write_text("pkgname = x\n", encoding="utf-8")
            with mock.patch.object(core.subprocess, "run") as run:
                self.assertEqual(core._srcinfo_text(directory), "pkgname = x\n")
                run.assert_not_called()

    def test_newest_iso(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            release = Path(tmp) / "release"
            release.mkdir()
            old = release / "old.iso"
            new = release / "new.iso"
            old.write_bytes(b"")
            new.write_bytes(b"")
            old.touch()
            new.touch()
            self.assertEqual(core.newest_iso(Path(tmp), 0), new)


class ConfigTests(unittest.TestCase):
    def test_roundtrip_and_permissions(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config_dir = Path(tmp)
            config_file = config_dir / "config.json"
            config = core.Config(
                repo_dir="/tmp/checkout",
                sudo_password="secret",
                packages=[core.Package("pfetch", version="1.0")],
                language="en",
            )
            with mock.patch.object(core, "CONFIG_DIR", config_dir), mock.patch.object(
                core, "CONFIG_FILE", config_file
            ), mock.patch.object(core, "ensure_dirs", lambda: config_dir.mkdir(parents=True, exist_ok=True)):
                core.save_config(config)
                loaded = core.load_config()

            self.assertEqual(config_file.stat().st_mode & 0o777, 0o600)
            self.assertEqual(loaded.repo_dir, "/tmp/checkout")
            self.assertEqual(loaded.language, "en")
            self.assertEqual([p.name for p in loaded.packages], ["pfetch"])

    def test_broken_config_falls_back_to_defaults(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config_dir = Path(tmp)
            config_file = config_dir / "config.json"
            config_file.write_text("{not json", encoding="utf-8")
            with mock.patch.object(core, "CONFIG_FILE", config_file), mock.patch.object(
                core, "save_config", lambda config: None
            ):
                loaded = core.load_config()
            self.assertEqual(loaded.repo_dir, str(core.DEFAULT_REPO_DIR))


class SearchTests(unittest.TestCase):
    def test_repository_result_wins_on_same_name(self) -> None:
        with mock.patch.object(
            core, "aur_search", lambda query: [{"Name": "firefox", "Version": "1", "NumVotes": 5}]
        ), mock.patch.object(
            core,
            "repo_search",
            lambda query: [
                {"name": "firefox", "version": "2", "source": "repo", "repo": "extra", "description": ""}
            ],
        ):
            results = core.search_packages("firefox")

        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["source"], "repo")

    def test_resolve_aur_build_set(self) -> None:
        infos = {
            "app": {"Depends": ["lib", "glibc>=2"], "MakeDepends": ["cmake"]},
            "lib": {"Depends": []},
        }
        with mock.patch.object(core, "aur_info", lambda names: {n: infos[n] for n in names if n in infos}):
            build, repository = core.resolve_aur_build_set(["app"])

        self.assertEqual(build, ["app", "lib"])
        self.assertEqual(repository, ["cmake", "glibc"])

    def test_verify_prefers_iso_repository(self) -> None:
        with mock.patch.object(
            core, "_repo_package_info", lambda name: {"name": name, "source": "repo", "repo": "extra"}
        ), mock.patch.object(core, "aur_info", lambda names: {"x": {"Name": "x"}}):
            self.assertEqual(core.verify_package("x")["source"], "repo")

    def test_verify_reports_unsupported_host_repository(self) -> None:
        with mock.patch.object(core, "_repo_package_info", lambda name: None), mock.patch.object(
            core, "aur_info", lambda names: {}
        ), mock.patch.object(
            core, "_host_repo_package_info", lambda name: {"name": name, "source": "unsupported", "repo": "cachyos"}
        ):
            self.assertEqual(core.verify_package("x")["repo"], "cachyos")


class BuildPipelineTests(unittest.TestCase):
    def test_run_build_wires_everything(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            (repo / "bin").mkdir()
            (repo / "bin" / "omarchy-iso-make").write_text("", encoding="utf-8")
            config = core.Config(repo_dir=str(repo), packages=[core.Package("cmatrix")])
            calls: dict[str, object] = {}

            def fake_stream(cmd, cwd, env, log_cb):
                calls["cmd"] = cmd
                calls["cwd"] = cwd
                calls["env"] = env
                return 0

            with mock.patch.object(core, "verify_package", lambda name: {"name": name, "source": "repo", "repo": "extra"}), mock.patch.object(
                core, "save_config", lambda config: None
            ), mock.patch.object(core, "reset_dir", lambda path: path.mkdir(parents=True, exist_ok=True)), mock.patch.object(
                core, "ensure_sudo_wrapper", lambda password: Path(tmp) / "sudo.sh"
            ), mock.patch.object(
                core, "sudo_env", lambda wrapper: {"OMARCHY_SUDO_WRAPPER": str(wrapper)}
            ), mock.patch.object(
                core, "prepare_build_root", lambda repo_dir, log: Path(tmp) / "omarchy-iso-make"
            ), mock.patch.object(
                core, "_run_stream", fake_stream
            ), mock.patch.object(
                core, "newest_iso", lambda repo_dir, newer_than: repo / "release" / "x.iso"
            ):
                iso = core.run_build(config, lambda line: None)

            self.assertEqual(iso, repo / "release" / "x.iso")
            self.assertIn("--keep-pkg-cache", calls["cmd"])
            self.assertIn("--no-boot-offer", calls["cmd"])
            self.assertEqual(calls["env"]["OMARCHY_CUSTOM_REPO_PACKAGES"], "cmatrix")
            self.assertEqual(calls["cwd"], repo)

    def test_run_build_rejects_missing_checkout(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config = core.Config(repo_dir=tmp, packages=[core.Package("x")])
            with self.assertRaises(RuntimeError):
                core.run_build(config, lambda line: None)


class I18nTests(unittest.TestCase):
    def test_both_languages_have_the_same_keys(self) -> None:
        english = set(i18n.MESSAGES["en"])
        russian = set(i18n.MESSAGES["ru"])
        self.assertEqual(english, russian)

    def test_missing_key_returns_the_key(self) -> None:
        i18n.set_language("en")
        try:
            self.assertEqual(i18n.tr("does.not.exist"), "does.not.exist")
        finally:
            i18n.set_language(i18n.DEFAULT_LANGUAGE)


if __name__ == "__main__":
    unittest.main()
