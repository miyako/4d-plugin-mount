"""Rebuild only Mount's proven generated outputs, preserving packaged inputs."""

import argparse
from pathlib import Path
import shutil


PRODUCT = "Mount"
BASE = Path("test/Plugins")
BUNDLE = BASE / (PRODUCT + ".bundle")
FILES = tuple(BUNDLE / relative for relative in (
    f"Contents/MacOS/{PRODUCT}", "Contents/Info.plist",
    "Contents/Resources/English.lproj/InfoPlist.strings",
    "Contents/Resources/constants.xlf", "Contents/Resources/manifest.json",
    "Contents/_CodeSignature/CodeResources",
))
CLEAN_FILES = tuple(path for path in FILES
                    if path.name not in ("constants.xlf", "manifest.json"))
DIRECTORIES = (
    Path("build/XCBuildData"),
    Path("build") / (PRODUCT + ".build"),
    Path("build/Default") / (PRODUCT + ".build"),
    BASE / (PRODUCT + ".build"),
    BASE / "Default" / (PRODUCT + ".build"),
)


def generated(path):
    return (path in set(map(str, FILES))
            or any(path.startswith(str(directory) + "/") for directory in DIRECTORIES))


def validate_paths(paths):
    root = Path.cwd().resolve()
    for path in paths:
        for parent in (path, *path.parents):
            if parent == Path("."):
                break
            if parent.is_symlink():
                raise ValueError(f"Refusing symlink output: {parent}")
        if not path.resolve().is_relative_to(root):
            raise ValueError(f"Output escapes checkout: {path}")
        if path.is_dir():
            for descendant in path.rglob("*"):
                if descendant.is_symlink():
                    raise ValueError(f"Refusing symlink output: {descendant}")


def prepare():
    validate_paths((*FILES, *DIRECTORIES))
    for path in CLEAN_FILES:
        path.unlink(missing_ok=True)
    for path in DIRECTORIES:
        if path.exists():
            shutil.rmtree(path)


def require_file(path):
    validate_paths((path,))
    if not path.is_file() or path.stat().st_size == 0:
        raise ValueError(f"Missing or empty native output: {path}")


def verify_resources():
    for name in ("manifest.json", "constants.xlf"):
        copied = BUNDLE / "Contents/Resources" / name
        require_file(copied)
        if copied.read_bytes() != Path(name).read_bytes():
            raise ValueError(f"Copied resource differs from source: {copied}")
    import source_version
    source_version.verify_bundle(BUNDLE)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("phase", choices=("clean-macos", "verify-resources"))
    if parser.parse_args().phase == "clean-macos":
        prepare()
    else:
        verify_resources()
