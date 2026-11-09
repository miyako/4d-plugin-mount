"""Isolated local-only fixtures shared by the helper regression suites."""

import contextlib
import os
from pathlib import Path
import shutil
import subprocess
import sys
import unittest
import uuid

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[1]
INTAKE = "21c7578dc34c29f155203802c4904e57823eb22e"
TRAILER = "Co-authored-by: Copilot App <223556219+Copilot@users.noreply.github.com>"
sys.path.insert(0, str(ROOT / ".github/scripts"))
import source_version as source


@contextlib.contextmanager
def cwd(path):
    previous = Path.cwd()
    os.chdir(path)
    try:
        yield
    finally:
        os.chdir(previous)


def original(path):
    return subprocess.check_output(["git", "show", f"{INTAKE}:{path}"], cwd=ROOT)


class Fixture(unittest.TestCase):
    def setUp(self):
        self.root = ROOT / "tests" / (".helper-" + uuid.uuid4().hex)
        self.root.mkdir()
        self.addCleanup(shutil.rmtree, self.root)

    def write(self, relative, data):
        target = self.root / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
        return target

    def sources(self, destination=None, *, anchor=False):
        destination = self.root if destination is None else destination
        version = None if anchor else source.read(ROOT).encode()
        for path in source.SOURCE_PATHS:
            target = destination / path
            target.parent.mkdir(parents=True, exist_ok=True)
            raw = original(path)
            if not anchor:
                if path == source.PROJECT:
                    for key in (b"MARKETING_VERSION", b"CURRENT_PROJECT_VERSION"):
                        raw = raw.replace(key + b" = 1.3.0;", key + b" = " + version + b";")
                elif path == source.LOCALIZED:
                    raw = raw.replace(b'CFBundleShortVersionString = "1.2.2";',
                                      b'CFBundleShortVersionString = "' + version + b'";')
                    raw = raw.replace(b"Mount version 1.2.2,",
                                      b"Mount version " + version + b",")
            target.write_bytes(raw)


class GitFixture(Fixture):
    def setUp(self):
        super().setUp()
        self.local = self.root / "checkout"
        self.local.mkdir()
        self.bare = self.root / "origin.git"
        self.home = self.root / "home"
        self.home.mkdir()
        self.env = {
            "PATH": os.environ["PATH"], "HOME": str(self.home),
            "GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_NOSYSTEM": "1",
            "GIT_TERMINAL_PROMPT": "0", "PYTHONDONTWRITEBYTECODE": "1",
            "LC_ALL": "C", "LANG": "C",
        }
        self.git("init", "--quiet", "-b", "selected")
        for key, value in (("user.name", "Offline Fixture"),
                           ("user.email", "fixture@example.invalid"),
                           ("commit.gpgsign", "false"), ("tag.gpgsign", "false"),
                           ("core.autocrlf", "false"), ("core.filemode", "true"),
                           ("push.followTags", "true"), ("safe.bareRepository", "explicit")):
            self.git("config", key, value)
        self.git("commit", "--quiet", "--allow-empty", "-m", "ancestor")
        self.ancestor = self.git("rev-parse", "HEAD")
        self.sources(self.local)
        shutil.copytree(ROOT / ".github/scripts", self.local / ".github/scripts",
                        ignore=shutil.ignore_patterns("__pycache__"))
        shutil.copytree(ROOT / ".github/hooks", self.local / ".github/hooks")
        self.git("add", ".")
        self.git("commit", "--quiet", "-m", "selected source fixture")
        self.sha = self.git("rev-parse", "HEAD")
        self.ref = "refs/heads/selected"
        self.git("init", "--bare", "--quiet", str(self.bare))
        self.git("remote", "add", "origin", str(self.bare))
        self.git("-c", "push.followTags=false", "push", "--quiet", "--no-follow-tags",
                 "origin", f"HEAD:{self.ref}")

    def git(self, *args, input=None, check=True):
        if args and args[0] == "commit" and args[-2:] != ("-m", TRAILER):
            args = (*args, "-m", TRAILER)
        if args and args[0] == "commit-tree":
            input = (input or "").rstrip() + (
                "" if (input or "").rstrip().endswith(TRAILER) else "\n\n" + TRAILER
            ) + "\n"
        result = subprocess.run(["git", *args], cwd=self.local, env=self.env, input=input,
                                text=True, capture_output=True, check=check)
        return result.stdout.strip() if check else result

    def remote(self):
        return self.git("--git-dir=" + str(self.bare), "rev-parse", self.ref)

    def cli(self, relative, *args, env=None):
        return subprocess.run([sys.executable, relative, *args], cwd=self.local,
                              env=self.env if env is None else env, text=True,
                              capture_output=True, timeout=60)
