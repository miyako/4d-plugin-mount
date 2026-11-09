"""Static workflow contracts complement actionlint and closed-PATH native tests."""

import re
import subprocess
import unittest

from helper_support import INTAKE, ROOT


class WorkflowTests(unittest.TestCase):
    def setUp(self):
        self.bump = (ROOT / ".github/workflows/bump-version.yml").read_text()
        self.build = (ROOT / ".github/workflows/release.yml").read_text()

    def test_exact_two_independent_manual_workflows_and_required_bump_choice(self):
        self.assertEqual(
            {path.name for path in (ROOT / ".github/workflows").glob("*.yml")},
            {"bump-version.yml", "release.yml"},
        )
        self.assertRegex(self.build, r"(?m)^name: Build$")
        self.assertIn("on:\n  workflow_dispatch:\n\n", self.build)
        self.assertNotIn("inputs:", self.build)
        for workflow in (self.bump, self.build):
            self.assertNotRegex(workflow, r"(?m)^  (push|pull_request|workflow_run|workflow_call):")
            self.assertNotIn("workflow run", workflow)
            self.assertNotIn("repository_dispatch", workflow)
        self.assertEqual(self.bump.count("type: choice"), 1)
        self.assertIn("options:\n          - patch\n          - minor\n          - major", self.bump)
        self.assertIn("default: patch\n        required: true", self.bump)
        self.assertNotIn("release.py", self.bump)
        self.assertNotIn("native.sh", self.bump)
        self.assertNotIn("git tag", self.bump)
        self.assertIn('--sha "$EVENT_SHA" --ref "$EVENT_REF"', self.bump)

    def test_every_checkout_is_immutable_and_publication_serializes_across_refs(self):
        for workflow in (self.bump, self.build):
            checkouts = re.findall(
                r"- uses: actions/checkout@[^\n]+\n(.*?)(?=\n      -|\Z)",
                workflow, re.DOTALL,
            )
            self.assertTrue(checkouts)
            for block in checkouts:
                self.assertIn("ref: ${{ github.sha }}", block)
        group = re.search(r"(?m)^  group: (.+)$", self.build).group(1)
        self.assertEqual(group, "release-publication")
        self.assertNotIn("${{", group)
        self.assertIn("cancel-in-progress: false", self.build)
        self.assertNotIn("github.ref_name", self.build)
        self.assertNotIn("refs/heads/master", self.build)

    def test_actual_macos_only_topology_and_native_order_are_preserved(self):
        original = subprocess.check_output(
            ["git", "show", f"{INTAKE}:.github/workflows/release.yml"], cwd=ROOT, text=True,
        )
        jobs = lambda text: re.findall(r"(?m)^  ([a-z][a-z-]+):\n    (?:name:|runs-on:)", text)
        self.assertEqual(jobs(original), ["version", "build-macos"])
        self.assertEqual(jobs(self.build), jobs(original))
        self.assertIn("MACOS_DEPLOYMENT_TARGET: '11.5'", self.build)
        self.assertIn("BASE_DIR: test", self.build)
        self.assertNotIn("windows-latest", self.build)
        self.assertNotIn("download-artifact", self.build)
        self.assertNotIn("setup-msbuild", self.build)
        self.assertNotIn("softprops/", self.build)
        self.assertNotIn("gh release", self.build)
        mac = self.build.split("  build-macos:", 1)[1]
        steps = (
            'release.py preflight --sha "$GITHUB_SHA"',
            "native.sh check-libraries", "native.sh import-certificate",
            "native.sh store-credentials", "native.sh build", "native.sh verify",
            "--verify-bundle", "native.sh sign", "native.sh package",
            'release.py publish --sha "$GITHUB_SHA"',
        )
        positions = [mac.index(step) for step in steps]
        self.assertEqual(positions, sorted(positions))
        self.assertEqual(self.build.count("GH_TOKEN: ${{ github.token }}"), 3)
        self.assertIn('"Mount-${VERSION}.zip" "Mount-${VERSION}.dmg"', self.build)
