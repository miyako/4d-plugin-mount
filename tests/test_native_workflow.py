"""Run actual workflow Bash with closed-PATH native and credential stubs."""

import json
from pathlib import Path
import re
import shutil
import subprocess
import sys
import unittest

import yaml

from helper_support import Fixture, ROOT, original, source
import native


WORKFLOW = ROOT / ".github/workflows/release.yml"
PRODUCT = "Mount"
CONTENTS = native.BUNDLE / "Contents"

STUB = r'''#!PYTHON
import base64, json, os, pathlib, plistlib, shutil, sys
tool = pathlib.Path(sys.argv[0]).name
args = sys.argv[1:]
with open(os.environ["NATIVE_LOG"], "a") as stream:
    stream.write(json.dumps([tool, *args]) + "\n")
if os.environ.get("FAIL_TOOL") == tool:
    sys.exit(23)
contents = pathlib.Path("test/Plugins/Mount.bundle/Contents")
if tool == "python3":
    if args and args[0].endswith("release.py"):
        assert os.environ["GH_TOKEN"] == "offline-only"
        assert os.environ["GITHUB_REPOSITORY"] == "miyako/4d-plugin-mount"
        assert args[2:4] == ["--sha", os.environ["GITHUB_SHA"]]
        if args[1] == "publish":
            assert args[4:] == [f"Mount-{os.environ['VERSION']}.zip",
                                f"Mount-{os.environ['VERSION']}.dmg"]
        if os.environ.get("FAIL_PUBLICATION") or (
                args[1] == "preflight" and os.environ.get("FAIL_PREFLIGHT")):
            sys.exit(9)
    else:
        os.execv(sys.executable, [sys.executable, *args])
elif tool == "xcodebuild":
    assert args == ["-project", "Mount.xcodeproj", "-target", "Mount",
                    "-configuration", "Default", "ARCHS=arm64 x86_64", "ONLY_ACTIVE_ARCH=NO",
                    "MACOSX_DEPLOYMENT_TARGET=11.5", "CODE_SIGNING_ALLOWED=NO",
                    "CONFIGURATION_BUILD_DIR=" + str(pathlib.Path.cwd() / "test/Plugins"), "build"]
    for relative in ("MacOS/Mount", "Info.plist",
                     "Resources/English.lproj/InfoPlist.strings", "_CodeSignature/CodeResources"):
        assert not (contents / relative).exists(), relative
    for relative in ("Resources/constants.xlf", "Resources/manifest.json",
                     "Windows64/Mount.4DX", "QuickLook/Thumbnail.png"):
        assert (contents / relative).read_bytes() == pathlib.Path(
            os.environ["PROTECTED_ROOT"], relative).read_bytes(), relative
    if not os.environ.get("STALE_BUILD"):
        (contents / "MacOS").mkdir(parents=True, exist_ok=True)
        (contents / "MacOS/Mount").write_bytes(b"fresh-macos")
        source_plist = plistlib.loads(pathlib.Path("Info.plist").read_bytes())
        (contents / "Info.plist").write_bytes(plistlib.dumps({
            key: os.environ["SOURCE_VERSION"] for key in
            ("CFBundleShortVersionString", "CFBundleVersion") if key in source_plist
        }, fmt=plistlib.FMT_BINARY))
        (contents / "Resources/English.lproj").mkdir(parents=True, exist_ok=True)
        (contents / "Resources/English.lproj/InfoPlist.strings").write_bytes(
            pathlib.Path("English.lproj/InfoPlist.strings").read_text().encode("utf-16"))
        for resource in ("manifest.json", "constants.xlf"):
            shutil.copyfile(resource, contents / "Resources" / resource)
        db = pathlib.Path("build/XCBuildData")
        db.mkdir(parents=True, exist_ok=True)
        for name in ("build.db", "build.db-wal", "build.db-shm"):
            (db / name).write_bytes(b"fresh-database")
elif tool == "lipo":
    print(os.environ.get("DYLIB_ARCHES" if args[-1].endswith(".dylib") else "ARCHES",
                         "arm64 x86_64"))
elif tool == "base64":
    pathlib.Path(args[args.index("-o") + 1]).write_bytes(base64.b64decode(sys.stdin.read()))
elif tool == "security":
    if args[0] == "find-identity":
        print("" if os.environ.get("MISSING_IDENTITY") else
              '  1) OFFLINE "Developer ID Application: Fixture"')
elif tool == "codesign":
    if "--verify" in args and os.environ.get("FAIL_VERIFY"):
        sys.exit(7)
    if "--verify" not in args:
        (contents / "_CodeSignature").mkdir(exist_ok=True)
        (contents / "_CodeSignature/CodeResources").write_bytes(b"fresh-signature")
elif tool in ("ditto", "hdiutil"):
    suffix = "zip" if tool == "ditto" else "dmg"
    assert args[-1] == f"Mount-{os.environ['VERSION']}.{suffix}"
    pathlib.Path(args[-1]).write_bytes(b"offline-package")
elif tool == "xcrun":
    if args[:2] == ["notarytool", "submit"]:
        response = os.environ.get("NOTARY_JSON")
        print(response if response is not None else json.dumps(
            {"id": "offline-id", "status": os.environ.get("NOTARY_STATUS", "Accepted")}))
        sys.exit(int(os.environ.get("NOTARY_EXIT", "0")))
    elif args[:2] == ["stapler", "staple"]:
        sys.exit(int(os.environ.get("STAPLE_EXIT", "0")))
    else:
        assert args[:2] == ["notarytool", "store-credentials"], args
else:
    sys.exit("Unexpected stub: " + tool)
'''


class NativeWorkflowTests(Fixture):
    def setUp(self):
        super().setUp()
        self.checkout = self.root / "checkout"
        self.checkout.mkdir()
        self.bin = self.root / "tools"
        self.bin.mkdir()
        self.log = self.root / "native.jsonl"
        for tool in ("python3", "xcodebuild", "lipo", "base64", "security",
                     "codesign", "ditto", "hdiutil", "xcrun"):
            path = self.bin / tool
            path.write_text(STUB.replace("PYTHON", sys.executable))
            path.chmod(0o755)
        for tool in ("bash", "grep", "head", "sed", "sort"):
            (self.bin / tool).symlink_to(shutil.which(tool))
        version = source.read(ROOT)
        self.env = {
            "PATH": str(self.bin), "HOME": str(self.checkout), "LC_ALL": "C",
            "RUNNER_TEMP": str(self.checkout), "NATIVE_LOG": str(self.log),
            "SOURCE_VERSION": version, "PRODUCT_NAME": PRODUCT, "BASE_DIR": "test",
            "MACOS_DEPLOYMENT_TARGET": "11.5", "VERSION": version,
            "KEYCHAIN_PATH": str(self.checkout / "offline.keychain"),
            "GITHUB_ENV": str(self.checkout / "github-env"),
            "ZIP_PATH": f"Mount-{version}.zip", "DMG_PATH": f"Mount-{version}.dmg",
            "GITHUB_SHA": "a" * 40, "GH_TOKEN": "offline-only",
            "GITHUB_REPOSITORY": "miyako/4d-plugin-mount",
            "PYTHONDONTWRITEBYTECODE": "1",
            "CERT_BASE64": "b2ZmbGluZQ==", "CERT_PASSWORD": "offline-only",
            "KEYCHAIN_PASSWORD": "offline-only", "APPLE_ID": "offline@example.invalid",
            "TEAM_ID": "OFFLINEONLY", "APP_PASSWORD": "offline-only",
            "PROTECTED_ROOT": str(self.root / "protected"),
        }
        shutil.copytree(ROOT / ".github/scripts", self.checkout / ".github/scripts",
                        ignore=shutil.ignore_patterns("__pycache__"))
        self.sources(self.checkout)
        self.assertEqual(source.read(self.checkout), version)
        for relative in ("manifest.json", "constants.xlf", "Mount.xcodeproj/project.pbxproj"):
            if not (self.checkout / relative).exists():
                self.write(Path("checkout") / relative, original(relative))
        self.jobs = yaml.safe_load(WORKFLOW.read_text())["jobs"]
        self.contents = self.checkout / CONTENTS
        self.protected = {}
        for relative in ("MacOS/runtime.dylib", "QuickLook/Thumbnail.png",
                         "Resources/custom.txt", "Windows64/Mount.4DX",
                         "Resources/constants.xlf", "Resources/manifest.json"):
            data = (original(relative.removeprefix("Resources/"))
                    if relative in ("Resources/constants.xlf", "Resources/manifest.json")
                    else b"preserved")
            path = self.write(Path("checkout") / CONTENTS / relative, data)
            self.write(Path("protected") / relative, data)
            self.protected[path] = data
        for relative in native.CLEAN_FILES:
            self.write(Path("checkout") / relative, b"stale")
        for relative in ("test/Plugins/Default/keep", "build/unrelated/keep",
                         "a/libjsoncpp.a", "lib/windows64/jsoncpp.lib"):
            path = self.write(Path("checkout") / relative, b"preserved")
            self.protected[path] = b"preserved"

    def calls(self):
        return [json.loads(line) for line in self.log.read_text().splitlines()] if self.log.exists() else []

    def run_step(self, job, name, success=True):
        step = next(step for step in self.jobs[job]["steps"] if step.get("name") == name)
        script = step["run"]
        self.assertNotIn("${{", script)
        self.assertIn(step.get("shell", "bash"), ("bash",))
        result = subprocess.run(
            ["/bin/bash", "--noprofile", "--norc", "-eo", "pipefail", "-c", script],
            cwd=self.checkout, env=self.env, capture_output=True, text=True, timeout=30)
        if success is True:
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        elif success is False:
            self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
        if result.returncode == 0:
            env_file = Path(self.env["GITHUB_ENV"])
            if env_file.exists():
                for line in env_file.read_text().splitlines():
                    key, value = line.split("=", 1)
                    self.env[key] = value
        return result

    def mac_step(self, name, success=True):
        return self.run_step("build-macos", name, success)

    def build(self):
        self.mac_step("build macOS plugin (universal)")

    def pipeline(self):
        for job in ("version", "build-macos"):
            for step in self.jobs[job]["steps"]:
                if "run" not in step:
                    continue
                result = self.run_step(job, step["name"], success=None)
                if result.returncode:
                    return result
        return result

    def test_complete_real_shell_pipeline_is_fresh_and_publishes_only_after_staple(self):
        result = self.pipeline()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual((self.contents / "MacOS/Mount").read_bytes(), b"fresh-macos")
        self.assertEqual((self.contents / "_CodeSignature/CodeResources").read_bytes(), b"fresh-signature")
        for path, data in self.protected.items():
            self.assertEqual(path.read_bytes(), data)
        calls = self.calls()
        index = lambda test: next(i for i, call in enumerate(calls) if test(call))
        xcode = index(lambda call: call[0] == "xcodebuild")
        sign = index(lambda call: call[0] == "codesign")
        package = index(lambda call: call[0] == "ditto")
        staple = index(lambda call: call[:3] == ["xcrun", "stapler", "staple"])
        publish = index(lambda call: call[0] == "python3" and "publish" in call)
        self.assertLess(xcode, sign)
        self.assertLess(sign, package)
        self.assertLess(package, staple)
        self.assertLess(staple, publish)
        self.assertEqual(sum(call[:3] == ["xcrun", "notarytool", "submit"] for call in calls), 2)
        self.assertTrue(all("--strict" in call and "--deep" in call for call in calls
                            if call[0] == "codesign" and "--verify" in call))

    def test_pipeline_uses_selected_source_version_not_the_intake_literal(self):
        before, version = self.env["VERSION"], "3.2.1"
        for path in source.SOURCE_PATHS:
            target = self.checkout / path
            target.write_bytes(target.read_bytes().replace(before.encode(), version.encode()))
        self.env.update(SOURCE_VERSION=version, VERSION=version,
                        ZIP_PATH=f"Mount-{version}.zip", DMG_PATH=f"Mount-{version}.dmg")
        self.assertEqual(source.read(self.checkout), version)
        result = self.pipeline()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        for suffix in ("zip", "dmg"):
            self.assertTrue((self.checkout / f"Mount-{version}.{suffix}").is_file())

    def test_cleanup_error_never_reaches_xcode(self):
        path = self.contents / "Info.plist"
        path.unlink()
        path.mkdir()
        self.mac_step("build macOS plugin (universal)", success=False)
        self.assertFalse(any(call[0] == "xcodebuild" for call in self.calls()))

    def test_missing_original_prebuilt_dependency_stops_before_credentials_or_native(self):
        (self.checkout / "a/libjsoncpp.a").unlink()
        result = self.pipeline()
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse(any(call[0] in ("security", "xcodebuild", "codesign") for call in self.calls()))

    def test_missing_empty_stale_binary_and_exact_architecture_tokens(self):
        self.env["STALE_BUILD"] = "1"
        self.build()
        self.mac_step("verify universal binary", success=False)
        self.env.pop("STALE_BUILD")
        self.build()
        binary = self.contents / "MacOS/Mount"
        binary.write_bytes(b"")
        self.mac_step("verify universal binary", success=False)
        binary.write_bytes(b"fresh")
        for arches in ("arm64e x86_64", "arm64 x86_64h", "", "arm64 x86_64 i386"):
            self.env["ARCHES"] = arches
            self.mac_step("verify universal binary", success=False)
        self.env["ARCHES"] = "arm64 x86_64 arm64e"
        self.env["DYLIB_ARCHES"] = "arm64 x86_64 i386"
        self.mac_step("verify universal binary")
        for arches in ("arm64e x86_64", "arm64 x86_64h", "arm64"):
            self.env["DYLIB_ARCHES"] = arches
            self.mac_step("verify universal binary", success=False)

    def test_missing_and_drifted_fresh_metadata_or_resources_rejected(self):
        self.build()
        for relative in ("Info.plist", "Resources/English.lproj/InfoPlist.strings",
                         "Resources/constants.xlf", "Resources/manifest.json"):
            path = self.contents / relative
            saved = path.read_bytes()
            for raw in (None, b"", b"drift"):
                with self.subTest(relative=relative, raw=raw):
                    if raw is None:
                        path.unlink()
                    else:
                        path.write_bytes(raw)
                    self.mac_step("verify universal binary", success=False)
                    path.write_bytes(saved)

    def test_xcode_compiled_localization_and_xml_plist_are_verified(self):
        import plistlib
        self.build()
        path = self.contents / "Resources/English.lproj/InfoPlist.strings"
        fields = source.localized_fields(source.decode(path.read_bytes())[0])
        path.write_bytes(plistlib.dumps({key: value[0] for key, value in fields.items()},
                                       fmt=plistlib.FMT_BINARY))
        plist = self.contents / "Info.plist"
        plist.write_bytes(plistlib.dumps(plistlib.loads(plist.read_bytes())))
        self.mac_step("verify universal binary")
        path.write_bytes(plistlib.dumps({"CFBundleShortVersionString": "0.0.0"}))
        self.mac_step("verify universal binary", success=False)

    def test_native_credential_arch_sign_notary_and_staple_failures_never_publish(self):
        cases = [
            {"FAIL_TOOL": tool} for tool in ("python3", "base64", "security", "xcrun",
                                           "xcodebuild", "lipo", "codesign", "ditto", "hdiutil")
        ] + [
            {"FAIL_PREFLIGHT": "1"}, {"MISSING_IDENTITY": "1"}, {"FAIL_VERIFY": "1"},
            {"STALE_BUILD": "1"}, {"ARCHES": "arm64e x86_64"},
            {"ARCHES": "arm64 x86_64 i386"}, {"DYLIB_ARCHES": "arm64e x86_64"},
            {"NOTARY_EXIT": "5", "NOTARY_STATUS": "Accepted"},
            {"NOTARY_STATUS": "Invalid"}, {"NOTARY_STATUS": ""},
            {"NOTARY_JSON": "not json"}, {"NOTARY_JSON": "[]"},
            {"NOTARY_JSON": "{}"}, {"STAPLE_EXIT": "8"},
            {"NOTARY_JSON": '{"status":"Invalid","status":"Accepted"}'},
            {"NOTARY_JSON": '{"status":"Accepted","extra":{"id":1,"id":2}}'},
            {"NOTARY_JSON": '{"status":"Accepted","extra":NaN}'},
            {"NOTARY_JSON": '{"status":"Accepted","extra":Infinity}'},
            {"NOTARY_JSON": '{"status":"Accepted","extra":-Infinity}'},
            {"NOTARY_JSON": '{"status":"Accepted","extra":1e999}'},
        ]
        original_env = dict(self.env)
        for case in cases:
            with self.subTest(case=case):
                self.env = {**original_env, **case}
                self.log.unlink(missing_ok=True)
                for suffix in ("zip", "dmg"):
                    (self.checkout / f"Mount-{self.env['VERSION']}.{suffix}").unlink(missing_ok=True)
                result = self.pipeline()
                self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
                self.assertFalse(any(call[0] == "python3" and "publish" in call
                                     for call in self.calls()))


class NativeWorkflowContractTests(unittest.TestCase):
    def test_manual_immutable_cross_branch_workflow_and_topology(self):
        workflow = yaml.load(WORKFLOW.read_text(), Loader=yaml.BaseLoader)
        before = yaml.load(original(".github/workflows/release.yml"), Loader=yaml.BaseLoader)
        self.assertEqual(workflow["name"], "Build")
        self.assertEqual(workflow["on"], {"workflow_dispatch": ""})
        self.assertEqual(workflow["env"]["PRODUCT_NAME"], PRODUCT)
        self.assertEqual(workflow["env"]["BASE_DIR"], "test")
        self.assertEqual(workflow["env"]["MACOS_DEPLOYMENT_TARGET"], "11.5")
        self.assertEqual(list(workflow["jobs"]), list(before["jobs"]))
        for name, job in workflow["jobs"].items():
            self.assertEqual(job["runs-on"], before["jobs"][name]["runs-on"])
            self.assertEqual(job.get("needs"), before["jobs"][name].get("needs"))
            self.assertNotIn("if", job)
            for step in job["steps"]:
                self.assertNotIn("if", step)
                self.assertNotIn("${{", step.get("run", ""))
                if step.get("uses", "").startswith("actions/checkout@"):
                    self.assertEqual(step["with"]["ref"], "${{ github.sha }}")
        mac = workflow["jobs"]["build-macos"]["steps"]
        self.assertIn("release.py preflight", mac[1]["run"])
        self.assertIn("release.py publish", mac[-1]["run"])
        self.assertEqual(mac[-1]["env"]["GH_TOKEN"], "${{ github.token }}")
        for forbidden in ("inputs.", "github.ref", "softprops", "dispatches", "bump.py",
                          "build-windows", "msbuild"):
            self.assertNotIn(forbidden, WORKFLOW.read_text())

    def test_native_projects_dependencies_and_committed_package_preserved(self):
        path = "Mount.xcodeproj/project.pbxproj"
        normalize = lambda data: re.sub(
            rb"((?:MARKETING_VERSION|CURRENT_PROJECT_VERSION)\s*=\s*)[0-9.]+;",
            rb"\g<1>VERSION;", data)
        self.assertEqual(normalize((ROOT / path).read_bytes()), normalize(original(path)))
        for path in ("Mount.vcxproj", "Mount.sln", "constants.xlf", "manifest.json",
                     "a/libjsoncpp.a", "lib/windows/jsoncpp.lib", "lib/windows64/jsoncpp.lib",
                     str(CONTENTS / "Info.plist"),
                     str(CONTENTS / "Resources/English.lproj/InfoPlist.strings"),
                     str(CONTENTS / "Resources/constants.xlf"),
                     str(CONTENTS / "Resources/manifest.json"),
                     str(CONTENTS / "Windows64/Mount.4DX"),
                     str(CONTENTS / "QuickLook/Thumbnail.png")):
            with self.subTest(path=path):
                self.assertEqual((ROOT / path).read_bytes(), original(path))
