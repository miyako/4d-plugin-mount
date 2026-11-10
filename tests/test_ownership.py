"""Unsigned macOS engine-boundary tests; never invoke disk operations or 4D."""

import os
from pathlib import Path
import platform
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
SOURCE = Path(os.environ.get("MOUNT_OWNERSHIP_SOURCE_ROOT", ROOT)).resolve()


@unittest.skipUnless(platform.system() == "Darwin", "requires macOS frameworks")
class OwnershipTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.build = tempfile.TemporaryDirectory(prefix="mount-ownership-")
        cls.addClassCleanup(cls.build.cleanup)
        cls.binary = Path(cls.build.name) / "ownership"
        command = [
            "clang++", "-std=c++11", "-g", "-O1",
            "-fsanitize=address,undefined", "-fno-omit-frame-pointer",
            "-Wno-deprecated-declarations", "-Wno-multichar",
            "-x", "objective-c++",
            "-I", str(SOURCE), "-I", str(SOURCE / "4D Plugin API"),
            "-I", str(SOURCE / "4D Plugin API/Classes"),
            "-I", str(SOURCE / "include/json"), "-I", str(SOURCE / "support"),
            str(ROOT / "tests/ownership.mm"),
            str(SOURCE / "4D Plugin API/4DPluginAPI.c"),
            str(SOURCE / "4D Plugin API/Classes/C_TEXT.cpp"),
            str(SOURCE / "4D Plugin API/Classes/ARRAY_TEXT.cpp"),
            str(SOURCE / "support/4DPlugin-JSON.cpp"),
            "-x", "none", str(SOURCE / "a/libjsoncpp.a"),
            "-framework", "Cocoa", "-framework", "DiskArbitration",
            "-framework", "CoreGraphics", "-o", str(cls.binary),
        ]
        result = subprocess.run(command, capture_output=True, text=True)
        if result.returncode:
            raise RuntimeError(result.stdout + result.stderr)

    def run_case(self, case):
        env = dict(os.environ, UBSAN_OPTIONS="halt_on_error=1")
        result = subprocess.run([str(self.binary), case], env=env,
                                capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_direct_callback_returns(self):
        self.run_case("callbacks-direct")

    def test_fallback_callback_returns(self):
        self.run_case("callbacks-fallback")

    def test_property_results(self):
        self.run_case("properties")

    def test_scalar_setters_and_stringify(self):
        self.run_case("setters")

    def test_array_transfers_and_copies(self):
        self.run_case("arrays")
