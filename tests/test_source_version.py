"""Coordinated Mount metadata: immutable intake evidence and dynamic live fixtures."""

import importlib.util
from pathlib import Path
import plistlib
import shutil
import stat
import subprocess
import sys
import unittest
from unittest.mock import patch
from uuid import uuid4


ROOT = Path(__file__).resolve().parents[1]
INTAKE = "21c7578dc34c29f155203802c4904e57823eb22e"
CREATION = "ec7b3ad4129b263861ef35d59bd6f3ce57f7f0b5"
sys.dont_write_bytecode = True
spec = importlib.util.spec_from_file_location(
    "mount_source_version", ROOT / ".github/scripts/source_version.py",
)
source = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = source
spec.loader.exec_module(source)


def original(path, revision=INTAKE):
    return subprocess.check_output(["git", "show", f"{revision}:{path}"], cwd=ROOT)


class SourceVersionTests(unittest.TestCase):
    def setUp(self):
        self.root = ROOT / (".source-tests-" + uuid4().hex)
        self.root.mkdir()
        self.addCleanup(shutil.rmtree, self.root)
        self.sources()
        self.version = source.read(self.root)

    def sources(self):
        for path in source.SOURCE_PATHS:
            target = self.root / path
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(ROOT / path, target)

    def snapshot(self):
        return {path: ((self.root / path).read_bytes(),
                       stat.S_IMODE((self.root / path).stat().st_mode))
                for path in source.SOURCE_PATHS if (self.root / path).exists()}

    def modify(self, path, transform):
        target = self.root / path
        target.write_bytes(transform(target.read_bytes()))

    def plist(self, **fields):
        path = self.root / source.PLIST
        data = plistlib.loads(path.read_bytes())
        data.update(fields)
        path.write_bytes(plistlib.dumps(data))

    def reject(self):
        before = self.snapshot()
        with patch.object(Path, "write_bytes") as write:
            with self.assertRaises((ValueError, UnicodeError, OSError)):
                source.read(self.root)
            with self.assertRaises((ValueError, UnicodeError, OSError)):
                source.bump("patch", self.root)
        write.assert_not_called()
        self.assertEqual(self.snapshot(), before)

    def test_exact_intake_authority_and_serialization(self):
        self.assertEqual(source.SETTING_COUNT, 6)
        self.assertEqual(source.SETTING_COUNTS, {
            "MARKETING_VERSION": 6, "CURRENT_PROJECT_VERSION": 3,
        })
        fields = source.project_settings(original(source.PROJECT).decode())
        self.assertEqual({key: [value for value, _, _ in values]
                          for key, values in fields.items()},
                         {key: ["1.3.0"] * source.SETTING_COUNTS[key]
                          for key in source.KEYS})
        plist = plistlib.loads(original(source.PLIST))
        self.assertEqual(plist[source.SHORT], "$(MARKETING_VERSION)")
        self.assertNotIn(source.BUILD, plist)
        raw = original(source.LOCALIZED)
        self.assertIn(b"\r", raw)
        self.assertNotIn(b"\n", raw)
        self.assertEqual(raw.decode("ascii").encode("ascii"), raw)
        self.assertIn(b'CFBundleShortVersionString = "1.2.2";', raw)
        self.assertIn(b"Mount version 1.2.2, Copyright 2020 miyako.", raw)

    def test_immutable_header_rename_history_and_exact_narrow_source_repair(self):
        header = original(".github/workflows/bump-version.yml", CREATION).decode()
        self.assertIn("MARKETING_VERSION/CURRENT_PROJECT_VERSION AND Info.plist", header)
        self.assertIn("CFBundleShortVersionString/CFBundleVersion", header)
        self.assertIn('sed -i -E "s/(${KEY} = )', header)
        history = subprocess.check_output([
            "git", "log", "--follow", "--name-status", "--format=%H", INTAKE,
            "--", str(source.LOCALIZED),
        ], cwd=ROOT).decode()
        self.assertIn("R100\tmount/English.lproj/InfoPlist.strings\tEnglish.lproj/InfoPlist.strings",
                      history)
        self.assertEqual(original(source.LOCALIZED, CREATION),
                         original("mount/English.lproj/InfoPlist.strings", CREATION + "^"))
        prior = original("mount/Mount.xcodeproj/project.pbxproj", CREATION + "^")
        self.assertEqual(prior.count(b"MARKETING_VERSION = 1.3.0;"), 3)
        self.assertNotIn(b"CURRENT_PROJECT_VERSION =", prior)
        version = source.read(ROOT).encode()
        for path in source.SOURCE_PATHS:
            expected = original(path)
            if path == source.PROJECT:
                for key in source.KEYS:
                    expected = expected.replace(
                        f"{key} = 1.3.0;".encode(), key.encode() + b" = " + version + b";")
            elif path == source.LOCALIZED:
                expected = expected.replace(
                    b'CFBundleShortVersionString = "1.2.2";',
                    b'CFBundleShortVersionString = "' + version + b'";',
                ).replace(b"Mount version 1.2.2,", b"Mount version " + version + b",")
            self.assertEqual((ROOT / path).read_bytes(), expected, path)

    def test_live_and_stable_all_modes_exact_bytes_modes_and_absence(self):
        for version in (self.version, "3.2.1"):
            for mode in ("major", "minor", "patch"):
                with self.subTest(version=version, mode=mode):
                    self.sources()
                    for path in source.SOURCE_PATHS:
                        self.modify(path, lambda raw: raw.replace(
                            self.version.encode(), version.encode()))
                        (self.root / path).chmod(0o750)
                    before = self.snapshot()
                    parts = list(map(int, version.split(".")))
                    index = ("major", "minor", "patch").index(mode)
                    parts[index] += 1
                    parts[index + 1:] = [0] * (2 - index)
                    new = ".".join(map(str, parts))
                    self.assertEqual(source.bump(mode, self.root), new)
                    self.assertEqual(source.read(self.root), new)
                    for path, (raw, filemode) in before.items():
                        self.assertEqual((self.root / path).read_bytes(),
                                         raw.replace(version.encode(), new.encode()))
                        self.assertEqual(stat.S_IMODE((self.root / path).stat().st_mode), filemode)
                    self.assertNotIn(source.BUILD,
                                     plistlib.loads((self.root / source.PLIST).read_bytes()))

    def test_invalid_missing_extra_drifting_and_cyclic_settings_never_write(self):
        for key in source.KEYS:
            for value in ("1.2", "7", "01.2.3", "1.02.3", "1.2.03", "v1.2.3",
                          "1.2.3-rc", "$(UNKNOWN)", "", f"$({key})", f"${{{key}}}",
                          "900.800.700"):
                self.sources()
                self.modify(source.PROJECT, lambda raw: raw.replace(
                    f"{key} = {self.version};".encode(), f"{key} = {value};".encode(), 1))
                self.reject()
            self.sources()
            self.modify(source.PROJECT, lambda raw: raw.replace(
                f"{key} = {self.version};".encode(), b"", 1))
            self.reject()
            for extra in (f"{key} = {self.version};", f'"{key}" = "{self.version}";',
                          f"{key} = {self.version}", f"{key} = ;"):
                self.sources()
                self.modify(source.PROJECT, lambda raw: raw + extra.encode())
                self.reject()
        self.sources()
        for key, target in (source.KEYS, tuple(reversed(source.KEYS))):
            self.modify(source.PROJECT, lambda raw: raw.replace(
                f"{key} = {self.version};".encode(), f"{key} = $({target});".encode()))
        self.reject()
        self.sources()
        self.modify(source.PROJECT, lambda raw: raw.replace(
            f"CURRENT_PROJECT_VERSION = {self.version};".encode(),
            b"CURRENT_PROJECT_VERSION = 900.800.700;"))
        self.reject()

    def test_every_quoted_unquoted_inline_duplicate_rejected(self):
        for key in source.KEYS:
            for quoted in (False, True):
                for prefix in ("", 'OTHER = "noise"; ', "/* noise */ "):
                    self.sources()
                    token = f"{key} = {self.version};".encode()
                    name = f'"{key}"' if quoted else key
                    extra = (prefix + f'{name} = "{self.version}"; ').encode()
                    self.modify(source.PROJECT, lambda raw: raw.replace(token, extra + token, 1))
                    self.reject()
                    # Preserve the global count: a duplicate cannot replace a missing config.
                    self.sources()
                    raw = (self.root / source.PROJECT).read_bytes()
                    first = raw.index(token)
                    second = raw.index(token, first + len(token))
                    raw = raw[:second] + raw[second:].replace(token, b"", 1)
                    raw = raw[:first] + extra + raw[first:]
                    (self.root / source.PROJECT).write_bytes(raw)
                    self.reject()

    def test_configuration_names_identities_and_key_placement(self):
        for old, new in ((b"name = Default;", b"name = Debug;"),
                         (b"42D60B400A9DDBC8002ABB42", b"42D60B400A9DDBC8002ABB43"),
                         (b"isa = XCBuildConfiguration;", b"isa = PBXGroup;"),
                         (b"buildSettings = {", b"OTHER = {")):
            self.sources()
            self.modify(source.PROJECT, lambda raw: raw.replace(old, new))
            self.reject()
        for key in source.KEYS:
            self.sources()
            token = f"{key} = {self.version};".encode()
            self.modify(source.PROJECT, lambda raw: raw.replace(token, b"", 1) + token)
            self.reject()
        self.sources()
        raw = (self.root / source.PROJECT).read_bytes()
        token = f"CURRENT_PROJECT_VERSION = {self.version};".encode()
        raw = raw.replace(token, b"", 1).replace(
            b"buildSettings = {", b"buildSettings = {" + token, 1)
        (self.root / source.PROJECT).write_bytes(raw)
        self.reject()

    def test_quoted_inline_scoped_assignments_and_comment_string_noise(self):
        project = "/* MARKETING_VERSION = 0.0.0; */\n{\n"
        for identifier, name in source.CONFIGURATIONS.items():
            project += (f'{identifier} = {{ isa = XCBuildConfiguration; name = "{name}"; '
                        'buildSettings = { OTHER = "CURRENT_PROJECT_VERSION = 9.9.9;"; ')
            for key in source.KEYS:
                if identifier in source.SETTING_CONFIGURATIONS[key]:
                    project += f'"{key}" = "{self.version}"; '
            project += "}; };\r\n"
        project += "}\n// MARKETING_VERSION = 8.8.8;\r"
        (self.root / source.PROJECT).write_bytes(project.encode())
        new = source.bump("patch", self.root)
        self.assertEqual((self.root / source.PROJECT).read_bytes(),
                         project.replace(self.version, new).encode())
        for noise in ("/* unterminated", '"unterminated', "}", "{"):
            self.sources()
            self.modify(source.PROJECT, lambda raw: raw + noise.encode())
            self.reject()

    def test_recursive_references_both_syntaxes_and_quotes_preserved(self):
        for referencing, target in (source.KEYS, tuple(reversed(source.KEYS))):
            for reference in (f"$({target})", f"${{{target}}}"):
                for quoted in (False, True):
                    for plist_ref in source.REFERENCES:
                        self.sources()
                        replacement = f'"{reference}"' if quoted else reference
                        self.modify(source.PROJECT, lambda raw: raw.replace(
                            f"{referencing} = {self.version};".encode(),
                            f"{referencing} = {replacement};".encode()))
                        self.plist(**{source.SHORT: plist_ref, source.BUILD: plist_ref})
                        new = source.bump("patch", self.root)
                        self.assertIn(reference.encode(), (self.root / source.PROJECT).read_bytes())
                        actual = plistlib.loads((self.root / source.PLIST).read_bytes())
                        self.assertEqual(actual[source.SHORT], plist_ref)
                        self.assertEqual(actual[source.BUILD], plist_ref)
                        self.assertEqual(source.read(self.root), new)

    def test_required_short_optional_build_invalid_plist_zero_writes(self):
        for key in (source.SHORT, source.BUILD):
            for bad in (True, 123, [], {}, "", "$(UNKNOWN)", "01.2.3", "900.800.700"):
                self.sources()
                self.plist(**{key: bad})
                self.reject()
        for fields in ({}, {source.BUILD: self.version}):
            self.sources()
            (self.root / source.PLIST).write_bytes(plistlib.dumps(fields))
            self.reject()
        self.sources()
        self.plist(**{source.BUILD: self.version})
        new = source.bump("minor", self.root)
        self.assertEqual(plistlib.loads((self.root / source.PLIST).read_bytes())[source.BUILD], new)
        for raw in (b"not plist", plistlib.dumps([]),
                    plistlib.dumps({source.SHORT: self.version}, fmt=plistlib.FMT_BINARY)):
            self.sources()
            (self.root / source.PLIST).write_bytes(raw)
            self.reject()

    def test_duplicate_xml_localized_keys_and_unknown_serialization(self):
        for key in (source.SHORT, source.BUILD, "CFBundleIdentifier"):
            self.sources()
            self.plist(**{key: self.version})
            self.modify(source.PLIST, lambda raw: raw.replace(
                b"</dict>", f"<key>{key}</key><string>{self.version}</string></dict>".encode()))
            self.reject()
        for key in (source.SHORT, source.INFO, "CFBundleName", source.BUILD):
            for quoted in (False, True):
                self.sources()
                name = f'"{key}"' if quoted else key
                extra = f'{name} = "{self.version}";'.encode()
                if key == source.BUILD:
                    self.modify(source.LOCALIZED, lambda raw: raw + extra)
                self.modify(source.LOCALIZED, lambda raw: raw + b'OTHER = "noise"; ' + extra)
                self.reject()
        for old, new in (("Copyright 2020", "Copyright 2025"),
                         ("Mount version ", "Other Product version ")):
            self.sources()
            self.modify(source.LOCALIZED, lambda raw: raw.replace(old.encode(), new.encode()))
            self.reject()
        for raw in (b"broken", b'CFBundleShortVersionString = "unterminated'):
            self.sources()
            (self.root / source.LOCALIZED).write_bytes(raw)
            self.reject()
        for key in (source.SHORT, source.INFO):
            self.sources()
            self.modify(source.LOCALIZED, lambda raw: raw.replace(key.encode(), b"Unknown"))
            self.reject()

    def test_encoding_individual_newlines_quotes_comments_unrelated_bytes(self):
        encodings = (("utf-8", b""), ("utf-8", b"\xef\xbb\xbf"),
                     ("utf-16-le", b"\xff\xfe"), ("utf-16-be", b"\xfe\xff"),
                     ("utf-16-le", b""), ("utf-16-be", b""))
        for codec, bom in encodings:
            for ending in ("\r", "\n", "\r\n", "mixed"):
                self.sources()
                originals = {}
                for i, path in enumerate(source.SOURCE_PATHS):
                    value = source.text(self.root / path)
                    if path == source.PLIST and codec.startswith("utf-16"):
                        value = value.replace('encoding="UTF-8"', 'encoding="UTF-16"')
                    value = "".join(line + (("\r", "\r\n", "\n")[j % 3]
                                            if ending == "mixed" else ending)
                                    for j, line in enumerate(value.splitlines()))
                    raw = bom + value.encode(codec)
                    (self.root / path).write_bytes(raw)
                    (self.root / path).chmod((0o755, 0o640, 0o644)[i])
                    originals[path] = raw
                before = self.snapshot()
                new = source.bump("patch", self.root)
                for path, raw in originals.items():
                    self.assertEqual((self.root / path).read_bytes(),
                                     raw.replace(self.version.encode(codec), new.encode(codec)))
                    self.assertEqual(stat.S_IMODE((self.root / path).stat().st_mode), before[path][1])
        self.sources()
        self.plist(**{"UnrelatedVersion": self.version})
        noise = f"<!-- <key>{source.SHORT}</key><string>9.9.9</string> -->"
        self.modify(source.PLIST, lambda raw: raw.replace(b"</dict>", noise.encode() + b"</dict>"))
        before = (self.root / source.PLIST).read_bytes()
        source.bump("patch", self.root)
        self.assertEqual(before, (self.root / source.PLIST).read_bytes())
        self.assertIn(f"<string>{self.version}</string>".encode(), before)

    def test_mixed_encodings_per_file_and_unrelated_quoted_version(self):
        self.modify(source.PROJECT, lambda raw: raw.replace(
            b'PRODUCT_NAME = Mount;', f'PRODUCT_NAME = Mount; OTHER = "{self.version}";'.encode()))
        raw_project = (self.root / source.PROJECT).read_bytes()
        plist = source.text(self.root / source.PLIST).replace('encoding="UTF-8"', 'encoding="UTF-16"')
        (self.root / source.PLIST).write_bytes(b"\xfe\xff" + plist.encode("utf-16-be"))
        local = source.text(self.root / source.LOCALIZED)
        (self.root / source.LOCALIZED).write_bytes(local.encode("utf-16-le"))
        new = source.bump("patch", self.root)
        expected = raw_project
        for key in source.KEYS:
            expected = expected.replace(f"{key} = {self.version};".encode(),
                                        f"{key} = {new};".encode())
        self.assertEqual((self.root / source.PROJECT).read_bytes(), expected)
        self.assertEqual((self.root / source.PLIST).read_bytes(),
                         b"\xfe\xff" + plist.encode("utf-16-be"))
        self.assertEqual((self.root / source.LOCALIZED).read_bytes(),
                         local.replace(self.version, new).encode("utf-16-le"))

    def test_missing_source_invalid_encoding_and_mode_never_write(self):
        for path in source.SOURCE_PATHS:
            self.sources()
            (self.root / path).unlink()
            self.reject()
            for bad in (b"\xffbroken", b"\x00", b"\x00\x00", b"\xff\xfe\x00"):
                self.sources()
                (self.root / path).write_bytes(bad)
                self.reject()
        self.sources()
        before = self.snapshot()
        with patch.object(Path, "write_bytes") as write:
            with self.assertRaises(ValueError):
                source.bump("other", self.root)
        write.assert_not_called()
        self.assertEqual(before, self.snapshot())

    def test_localized_version_references_and_optional_build_preserved(self):
        for reference in source.REFERENCES:
            self.sources()
            self.modify(source.LOCALIZED, lambda raw: raw.replace(
                f'{source.SHORT} = "{self.version}"'.encode(),
                f'"{source.SHORT}" = "{reference}"'.encode())
                + b'CFBundleVersion = "${CURRENT_PROJECT_VERSION}";\r')
            new = source.bump("patch", self.root)
            self.assertEqual(source.read(self.root), new)
            raw = (self.root / source.LOCALIZED).read_bytes()
            self.assertIn(reference.encode(), raw)
            self.assertIn(b'${CURRENT_PROJECT_VERSION}', raw)
            self.assertNotIn(source.BUILD, plistlib.loads((self.root / source.PLIST).read_bytes()))

    def build_fixture(self, fmt=plistlib.FMT_XML):
        bundle = self.root / "built.bundle"
        localized = bundle / "Contents/Resources" / source.LOCALIZED
        localized.parent.mkdir(parents=True, exist_ok=True)
        localized.write_bytes((self.root / source.LOCALIZED).read_bytes())
        (bundle / "Contents/Info.plist").write_bytes(plistlib.dumps(
            {source.SHORT: self.version}, fmt=fmt))
        return bundle, localized

    def test_built_binary_xml_utf16_metadata_optional_absence_and_failures(self):
        for fmt in (plistlib.FMT_BINARY, plistlib.FMT_XML):
            bundle, localized = self.build_fixture(fmt)
            expected = {key: field[0] for key, field in
                        source.localized_fields(source.text(self.root / source.LOCALIZED)).items()}
            for style in ("strings", "utf-8-sig", "utf-16", "utf-16-be", "xml", "binary"):
                if style in ("xml", "binary"):
                    raw = plistlib.dumps(expected, fmt=(
                        plistlib.FMT_XML if style == "xml" else plistlib.FMT_BINARY))
                else:
                    value = source.text(self.root / source.LOCALIZED)
                    raw = value.encode("utf-8" if style == "strings" else style)
                    if style == "utf-16-be":
                        raw = b"\xfe\xff" + raw
                localized.write_bytes(raw)
                source.verify_bundle(bundle, self.root)
            for fields in ({}, [], {**expected, source.INFO: "wrong"},
                           {**expected, source.SHORT: "900.800.700"},
                           {**expected, source.BUILD: self.version}):
                localized.write_bytes(plistlib.dumps(fields, fmt=fmt))
                with self.assertRaises(ValueError):
                    source.verify_bundle(bundle, self.root)
            localized.write_bytes(plistlib.dumps(expected))
            for fields in ({}, [], {source.SHORT: self.version, source.BUILD: self.version},
                           {source.SHORT: "900.800.700"}, {source.SHORT: "$(MARKETING_VERSION)"}):
                (bundle / "Contents/Info.plist").write_bytes(plistlib.dumps(fields, fmt=fmt))
                with self.assertRaises(ValueError):
                    source.verify_bundle(bundle, self.root)
            (bundle / "Contents/Info.plist").write_bytes(
                f'{source.SHORT} = "{self.version}";'.encode())
            with self.assertRaises(ValueError):
                source.verify_bundle(bundle, self.root)

    def test_built_optional_build_present_and_compiled_duplicate_rejected(self):
        self.plist(**{source.BUILD: "$(CURRENT_PROJECT_VERSION)"})
        self.modify(source.LOCALIZED, lambda raw: raw + (
            f'{source.BUILD} = "${{CURRENT_PROJECT_VERSION}}";').encode())
        bundle, localized = self.build_fixture()
        fields = {key: field[0] for key, field in
                  source.localized_fields(source.text(self.root / source.LOCALIZED)).items()}
        fields[source.BUILD] = self.version
        localized.write_bytes(plistlib.dumps(fields, fmt=plistlib.FMT_BINARY))
        actual = {source.SHORT: self.version, source.BUILD: self.version}
        (bundle / "Contents/Info.plist").write_bytes(plistlib.dumps(actual))
        source.verify_bundle(bundle, self.root)
        del actual[source.BUILD]
        (bundle / "Contents/Info.plist").write_bytes(plistlib.dumps(actual))
        with self.assertRaises(ValueError):
            source.verify_bundle(bundle, self.root)
        actual[source.BUILD] = self.version
        (bundle / "Contents/Info.plist").write_bytes(plistlib.dumps(actual))
        raw = plistlib.dumps(fields).replace(b"</dict>", (
            f"<key>{source.SHORT}</key><string>{self.version}</string></dict>").encode())
        localized.write_bytes(raw)
        with self.assertRaises(ValueError):
            source.verify_bundle(bundle, self.root)

    def test_prebuilt_resources_counters_and_dependencies_untouched(self):
        excluded = {
            "test/Plugins/Mount.bundle/Contents/Info.plist": b"old prebuilt",
            "test/Plugins/Mount.bundle/Contents/Resources/English.lproj/InfoPlist.strings":
                b"\xff\xfeold prebuilt",
            "manifest.json": b'{"version":"1.0","id":20000}',
            "constants.xlf": b'<xliff version="1.0"/>',
            "test/Project/Sources/catalog.4DCatalog": b"4D counter",
            "test/Plugins/Mount.bundle/Contents/Windows64/Mount.4DX": b"stub",
            "a/library.a": b"dependency",
        }
        for path, raw in excluded.items():
            target = self.root / path
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(raw)
        source.bump("major", self.root)
        for path, raw in excluded.items():
            self.assertEqual((self.root / path).read_bytes(), raw)
        prebuilt = "test/Plugins/Mount.bundle/Contents/Resources/English.lproj/InfoPlist.strings"
        self.assertTrue(original(prebuilt).startswith(b"\xff\xfe"))
        self.assertEqual((ROOT / prebuilt).read_bytes(), original(prebuilt))

    def test_cli_read_bump_and_built_validation(self):
        script = str(ROOT / ".github/scripts/source_version.py")
        before = self.snapshot()
        result = subprocess.run([sys.executable, script], cwd=self.root, check=True,
                                capture_output=True, text=True)
        self.assertEqual(result.stdout.strip(), self.version)
        self.assertEqual(before, self.snapshot())
        bundle, _ = self.build_fixture()
        result = subprocess.run([sys.executable, script, "--verify-bundle", str(bundle)],
                                cwd=self.root, capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        result = subprocess.run([sys.executable, script, "--bump", "patch"],
                                cwd=self.root, check=True, capture_output=True, text=True)
        self.assertEqual(result.stdout.strip(), source.read(self.root))
        result = subprocess.run([sys.executable, script, "--verify-bundle", str(bundle)],
                                cwd=self.root, capture_output=True, text=True)
        self.assertNotEqual(result.returncode, 0)


if __name__ == "__main__":
    unittest.main()
