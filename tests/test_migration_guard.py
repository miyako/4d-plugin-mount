"""Migration pushes permit one new branch or one explicit direct-child correction."""

import os
import subprocess

from helper_support import GitFixture, ROOT


class MigrationGuardTests(GitFixture):
    def setUp(self):
        super().setUp()
        self.guard = ROOT / ".github/migration-hooks/pre-push"
        self.migration_ref = "refs/heads/miyako-simplify-mount-workflows"
        self.values = {**self.env, "MIGRATION_SHA": self.sha,
                       "MIGRATION_REF": self.migration_ref}

    def invoke(self, rows, env=None):
        return subprocess.run([str(self.guard)], cwd=self.local, input=rows,
                              env=self.values if env is None else env, text=True,
                              capture_output=True)

    def test_exact_record_executable_and_literal_zero_old(self):
        self.assertTrue(os.access(self.guard, os.X_OK))
        row = f"{self.sha} {self.sha} {self.migration_ref} {'0' * 40}\n"
        self.assertEqual(self.invoke(row).returncode, 0)
        self.assertEqual(self.invoke(row.replace(self.sha + " ", "HEAD ", 1)).returncode, 0)
        for invalid in ("", row * 2, row.replace("0" * 40, self.ancestor),
                        row.replace(self.migration_ref, "refs/tags/v1.3.0"),
                        row.replace(self.sha + " ", "refs/heads/selected ", 1)):
            self.assertNotEqual(self.invoke(invalid).returncode, 0)
        self.assertNotEqual(self.invoke(row, self.env).returncode, 0)

    def test_actual_one_new_ref_push_and_second_push_rejected(self):
        command = ["git", "-c", f"core.hooksPath={self.guard.parent}", "-c",
                   "push.followTags=false", "push", "--no-follow-tags", "--porcelain",
                   "origin", f"{self.sha}:{self.migration_ref}"]
        result = subprocess.run(command, cwd=self.local, env=self.values,
                                text=True, capture_output=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        again = subprocess.run(command, cwd=self.local, env=self.values,
                               text=True, capture_output=True)
        self.assertNotEqual(again.returncode, 0, again.stderr)
        self.assertEqual(self.git("--git-dir=" + str(self.bare), "rev-parse",
                                  self.migration_ref), self.sha)
        self.assertEqual(self.git("--git-dir=" + str(self.bare), "tag", "--list"), "")

    def test_actual_guarded_direct_child_correction_and_exact_old_required(self):
        self.git("-c", "push.followTags=false", "push", "--quiet", "--no-follow-tags",
                 "origin", f"{self.sha}:{self.migration_ref}")
        (self.local / "review-fix.txt").write_text("narrow review correction\n")
        self.git("add", "--", "review-fix.txt")
        self.git("commit", "--quiet", "-m", "review correction")
        new = self.git("rev-parse", "HEAD")
        values = {**self.values, "MIGRATION_SHA": new, "MIGRATION_OLD_SHA": self.sha}
        row = f"{new} {new} {self.migration_ref} {self.sha}\n"
        self.assertEqual(self.invoke(row, values).returncode, 0)
        for invalid in ("", row * 2, row.replace(self.sha, self.ancestor),
                        row.replace(self.migration_ref, "refs/tags/unrelated")):
            self.assertNotEqual(self.invoke(invalid, values).returncode, 0)
        for old in (self.ancestor, new, "invalid"):
            self.assertNotEqual(self.invoke(row, {**values, "MIGRATION_OLD_SHA": old}).returncode, 0)
        command = ["git", "-c", f"core.hooksPath={self.guard.parent}", "-c",
                   "push.followTags=false", "push", "--no-follow-tags", "--porcelain",
                   "origin", f"{new}:{self.migration_ref}"]
        result = subprocess.run(command, cwd=self.local, env=values,
                                text=True, capture_output=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("Validated actual migration advertisement: " + row.strip(), result.stderr)
        again = subprocess.run(command, cwd=self.local, env=values,
                               text=True, capture_output=True)
        self.assertNotEqual(again.returncode, 0)
        self.assertEqual(self.git("--git-dir=" + str(self.bare), "rev-parse",
                                  self.migration_ref), new)
        self.assertEqual(self.git("--git-dir=" + str(self.bare), "tag", "--list"), "")
