"""The final publication exemption is smaller than the bundle or build roots."""

import unittest

from helper_support import source
import native


class GeneratedOutputTests(unittest.TestCase):
    def test_exact_native_files_and_controlled_directory_descendants(self):
        files = (
            "test/Plugins/Mount.bundle/Contents/MacOS/Mount",
            "test/Plugins/Mount.bundle/Contents/Info.plist",
            "test/Plugins/Mount.bundle/Contents/Resources/English.lproj/InfoPlist.strings",
            "test/Plugins/Mount.bundle/Contents/Resources/constants.xlf",
            "test/Plugins/Mount.bundle/Contents/Resources/manifest.json",
            "test/Plugins/Mount.bundle/Contents/_CodeSignature/CodeResources",
        )
        self.assertEqual(tuple(map(str, native.FILES)), files)
        self.assertEqual(tuple(map(str, native.DIRECTORIES)), (
            "build/XCBuildData", "build/Mount.build", "build/Default/Mount.build",
            "test/Plugins/Mount.build", "test/Plugins/Default/Mount.build",
        ))
        expected = (
            *files,
            "build/XCBuildData/build.db",
            "build/XCBuildData/build.db-wal",
            "build/XCBuildData/build.db-shm",
            "build/Mount.build/Objects-normal/arm64/main.o",
            "build/Default/Mount.build/build.db",
            "test/Plugins/Mount.build/Objects/file.o",
            "test/Plugins/Default/Mount.build/Objects/file.o",
        )
        for path in expected:
            with self.subTest(path=path):
                self.assertTrue(native.generated(path))

    def test_every_resource_source_or_unproven_output_stays_protected(self):
        excluded = (
            "test/Plugins/Mount.bundle/Contents/Windows64/Mount.4DX",
            "winbuild/Mount.4DX", "Objs/Release/Mount.obj",
            "test/Plugins/Mount.bundle/Contents/MacOS/runtime.dylib",
            "test/Plugins/Mount.bundle/Contents/QuickLook/Thumbnail.png",
            "test/Plugins/Default/Mount.bundle/Contents/Info.plist",
            "test/Plugins/Default/keep", "build/XCBuildData-evil/build.db",
            "build/unexpected-source.cpp",
            "build/Mount.build-evil/injected.cpp",
            "test/Plugins/Mount.bundle/Contents/_CodeSignature-evil/file",
            "test/Plugins/Mount.bundle/Contents/Info.plist.backup",
            *map(str, source.SOURCE_PATHS),
        )
        for path in excluded:
            with self.subTest(path=path):
                self.assertFalse(native.generated(path))
