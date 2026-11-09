"""Narrow cleanup and final-only generated output retention."""

import shutil
from unittest import mock

from helper_support import Fixture, GitFixture, cwd
import native
import repository


class NativePreparationTests(Fixture):
    def test_selective_cleanup_preserves_resources_dependencies_and_default_siblings(self):
        protected = (
            native.BUNDLE / "Contents/Windows64/Mount.4DX",
            native.BUNDLE / "Contents/QuickLook/Thumbnail.png",
            native.BUNDLE / "Contents/MacOS/runtime.dylib",
            native.BUNDLE / "Contents/Resources/constants.xlf",
            native.BUNDLE / "Contents/Resources/manifest.json",
            native.BUNDLE / "Contents/Resources/custom.txt",
            native.BASE / "Default/Mount.bundle/Contents/Info.plist",
            native.BASE / "Default/Mount.bundle/Contents/Resources/custom.txt",
            native.BASE / "Default/keep", native.BASE / "Other.bundle/keep",
            "build/unrelated/keep", "a/libjsoncpp.a", "lib/windows64/jsoncpp.lib",
        )
        for path in protected:
            self.write(path, b"preserved")
        for path in native.CLEAN_FILES:
            self.write(path, b"stale")
        for path in native.DIRECTORIES:
            self.write(path / "intermediate", b"stale")
        with cwd(self.root):
            native.prepare()
            native.prepare()
        for path in protected:
            self.assertEqual((self.root / path).read_bytes(), b"preserved")
        for path in (*native.CLEAN_FILES, *native.DIRECTORIES):
            self.assertFalse((self.root / path).exists(), path)

    def test_symlink_anywhere_prevalidated_before_first_deletion(self):
        for where in (native.FILES[-1], native.FILES[-2], native.DIRECTORIES[-1], native.BUNDLE,
                      native.DIRECTORIES[0] / "nested/link"):
            with self.subTest(where=where):
                first = self.write(native.FILES[0], b"must remain")
                destination = self.write("outside/keep", b"untouched")
                link = self.root / where
                if link.is_dir():
                    shutil.rmtree(link)
                link.parent.mkdir(parents=True, exist_ok=True)
                link.symlink_to(destination)
                with cwd(self.root), self.assertRaisesRegex(ValueError, "symlink"):
                    native.prepare()
                if where != native.BUNDLE:
                    self.assertEqual(first.read_bytes(), b"must remain")
                self.assertEqual(destination.read_bytes(), b"untouched")
                link.unlink()

    def test_cleanup_io_error_is_fatal(self):
        self.write(native.FILES[0], b"stale")
        with cwd(self.root), mock.patch("pathlib.Path.unlink", side_effect=PermissionError("denied")):
            with self.assertRaises(PermissionError):
                native.prepare()
        self.write(native.DIRECTORIES[0] / "stale", b"stale")
        with cwd(self.root), mock.patch("shutil.rmtree", side_effect=PermissionError("denied")):
            with self.assertRaises(PermissionError):
                native.prepare()

    def test_resources_must_be_fresh_exact_source_copies(self):
        for name in ("constants.xlf", "manifest.json"):
            self.write(name, b"source")
            self.write(native.BUNDLE / "Contents/Resources" / name, b"source")
        with cwd(self.root), mock.patch("source_version.verify_bundle") as verify:
            native.verify_resources()
            verify.assert_called_once_with(native.BUNDLE)
            (native.BUNDLE / "Contents/Resources/constants.xlf").write_bytes(b"stale")
            with self.assertRaisesRegex(ValueError, "differs"):
                native.verify_resources()

    def test_built_metadata_verification_failure_is_fatal(self):
        for name in ("constants.xlf", "manifest.json"):
            self.write(name, b"source")
            self.write(native.BUNDLE / "Contents/Resources" / name, b"source")
        with cwd(self.root), mock.patch("source_version.verify_bundle",
                                        side_effect=ValueError("built metadata")):
            with self.assertRaisesRegex(ValueError, "built metadata"):
                native.verify_resources()


class GeneratedRetentionTests(GitFixture):
    def setUp(self):
        super().setUp()
        (self.local / ".gitignore").write_text("build/\n")
        self.git("add", ".gitignore")
        self.git("commit", "--quiet", "-m", "Ignore actual Xcode intermediates")
        self.sha = self.git("rev-parse", "HEAD")

    def test_actual_xcode_database_wal_and_outputs_are_final_only(self):
        for relative in (
            *native.FILES,
            "build/XCBuildData/build.db", "build/XCBuildData/build.db-wal",
            "build/XCBuildData/build.db-shm",
            "build/XCBuildData/abc.xcbuilddata/build-request.json",
            "build/Mount.build/Default/Mount.build/Objects-normal/arm64/main.o",
            "build/Default/Mount.build/main.o",
            "test/Plugins/Mount.build/main.o",
            "test/Plugins/Default/Mount.build/main.o",
        ):
            target = self.local / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(b"fresh native output")
        with cwd(self.local):
            self.assertEqual(self.git("check-ignore", "build/XCBuildData/build.db"),
                             "build/XCBuildData/build.db")
            with self.assertRaises(ValueError):
                repository.verify_checkout(self.sha, generated=native.generated)
            repository.verify_checkout(self.sha, generated=native.generated, final=True)
        self.assertEqual((self.local / "build/XCBuildData/build.db").read_bytes(),
                         b"fresh native output")

    def test_tracked_generated_metadata_overwrites_are_retained_without_reset(self):
        for path in native.FILES:
            target = self.local / path
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(b"committed old generated bytes")
        self.git("add", *map(str, native.FILES))
        self.git("commit", "--quiet", "-m", "Track packaged generated metadata")
        self.sha = self.git("rev-parse", "HEAD")
        for path in native.FILES:
            (self.local / path).write_bytes(b"retained fresh generated bytes")
        with cwd(self.local):
            with self.assertRaises(ValueError):
                repository.verify_checkout(self.sha, generated=native.generated)
            repository.verify_checkout(self.sha, generated=native.generated, final=True)
        for path in native.FILES:
            self.assertEqual((self.local / path).read_bytes(), b"retained fresh generated bytes")
        self.git("add", str(native.FILES[0]))
        with cwd(self.local), self.assertRaises(ValueError):
            repository.verify_checkout(self.sha, generated=native.generated, final=True)

    def test_evil_siblings_and_protected_resource_never_gain_final_exemption(self):
        for relative in (
            "build/XCBuildData-evil/build.db",
            "build/Mount.build-evil/main.o", "build/unexpected-source.cpp",
            "Objs/Release/main.obj", "winbuild/Mount.4DX",
            "test/Plugins/Default/keep", "test/Plugins/Other.bundle/Contents/Info.plist",
            "test/Plugins/Default/Mount.bundle/Contents/Info.plist",
            str(native.BUNDLE / "Contents/QuickLook/Thumbnail.png"),
            str(native.BUNDLE / "Contents/Windows64/Mount.4DX"),
            str(native.BUNDLE / "Contents/MacOS/runtime.dylib"),
            str(native.BUNDLE / "Contents/Resources/custom.txt"),
            str(native.BUNDLE / "Contents/_CodeSignature/evil"),
        ):
            with self.subTest(relative=relative):
                target = self.local / relative
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(b"unexpected")
                with cwd(self.local), self.assertRaises(ValueError):
                    repository.verify_checkout(self.sha, generated=native.generated, final=True)
                target.unlink()
