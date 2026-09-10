"""
Unit tests for agents/shared/diffing.py's baseline snapshot + per-file
changed-file computation, used to power the final "Changed Files" view.
"""
import shutil

from agents.shared.diffing import compute_changed_files, snapshot_workspace


class TestSnapshotAndDiff:
    def test_modified_file_reports_unified_diff(self, tmp_path):
        workspace = tmp_path / "workspace"
        workspace.mkdir()
        (workspace / "Foo.java").write_text("class Foo {}\n", encoding="utf-8")

        baseline_dir = snapshot_workspace(str(workspace))
        (workspace / "Foo.java").write_text("class Foo { void bar() {} }\n", encoding="utf-8")

        changed = compute_changed_files(baseline_dir, str(workspace))

        assert len(changed) == 1
        assert changed[0]["path"] == "Foo.java"
        assert changed[0]["status"] == "modified"
        assert "-class Foo {}" in changed[0]["diff"]
        assert "+class Foo { void bar() {} }" in changed[0]["diff"]

        shutil.rmtree(baseline_dir, ignore_errors=True)

    def test_added_and_deleted_files_are_reported(self, tmp_path):
        workspace = tmp_path / "workspace"
        workspace.mkdir()
        (workspace / "Keep.java").write_text("class Keep {}\n", encoding="utf-8")
        (workspace / "Remove.java").write_text("class Remove {}\n", encoding="utf-8")

        baseline_dir = snapshot_workspace(str(workspace))
        (workspace / "Remove.java").unlink()
        (workspace / "New.java").write_text("class New {}\n", encoding="utf-8")

        changed = {c["path"]: c for c in compute_changed_files(baseline_dir, str(workspace))}

        assert changed["Remove.java"]["status"] == "deleted"
        assert changed["New.java"]["status"] == "added"
        assert "Keep.java" not in changed  # unchanged files are not reported

        shutil.rmtree(baseline_dir, ignore_errors=True)

    def test_unchanged_workspace_reports_nothing(self, tmp_path):
        workspace = tmp_path / "workspace"
        workspace.mkdir()
        (workspace / "Foo.java").write_text("class Foo {}\n", encoding="utf-8")

        baseline_dir = snapshot_workspace(str(workspace))
        changed = compute_changed_files(baseline_dir, str(workspace))

        assert changed == []
        shutil.rmtree(baseline_dir, ignore_errors=True)

    def test_missing_directories_return_empty_list(self, tmp_path):
        changed = compute_changed_files(str(tmp_path / "no-baseline"), str(tmp_path / "no-workspace"))
        assert changed == []
