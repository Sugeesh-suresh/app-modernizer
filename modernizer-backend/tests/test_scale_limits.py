"""
Tests for the ingestion, tool-budget and result-collection limits that decide how
large a repository the pipeline can actually handle.

The one that matters most is truncation visibility. Every later stage -- the RE
inventory, the plan's file manifest, the change audit's "is every untouched file
genuinely irrelevant" check -- reasons about *the whole repository*. A workspace
that is quietly partial does not make those answers worse, it makes them wrong
while they still read as confident, so an incomplete upload has to be impossible
to mistake for a complete one.
"""
import io
import zipfile
from pathlib import Path

import pytest

import main
from agents import config
from agents.shared import workspace_tools


def _zip_of(files: dict[str, str]) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        for name, content in files.items():
            zf.writestr(name, content)
    return buf.getvalue()


class TestExtractionTruncation:
    def test_complete_upload_reports_complete(self, tmp_path):
        result = main._extract_zip_to_dir(_zip_of({f"src/F{i}.java": "x" for i in range(20)}), tmp_path)

        assert result.files == 20
        assert result.truncated == 0
        assert result.complete
        assert result.warning() == ""

    def test_truncated_upload_counts_what_it_left_behind(self, tmp_path, monkeypatch):
        """The old code `break`-ed out of the loop and returned only a count, so a
        repo too big for the workspace looked like a successful upload."""
        monkeypatch.setattr(config, "WORKSPACE_MAX_FILES", 5)

        result = main._extract_zip_to_dir(_zip_of({f"src/F{i}.java": "x" for i in range(20)}), tmp_path)

        assert result.files == 5
        assert result.truncated == 15
        assert not result.complete

    def test_truncation_warning_names_the_scale_and_the_fix(self, tmp_path, monkeypatch):
        monkeypatch.setattr(config, "WORKSPACE_MAX_FILES", 5)

        warning = main._extract_zip_to_dir(
            _zip_of({f"src/F{i}.java": "x" for i in range(20)}), tmp_path
        ).warning()

        assert "15 of 20 files were not unpacked" in warning
        assert "PARTIAL" in warning
        assert "WORKSPACE_MAX_FILES" in warning  # says how to fix it

    def test_byte_cap_also_truncates_rather_than_silently_stopping(self, tmp_path, monkeypatch):
        monkeypatch.setattr(config, "WORKSPACE_MAX_TOTAL_BYTES", 50)

        result = main._extract_zip_to_dir(_zip_of({f"F{i}.java": "x" * 40 for i in range(10)}), tmp_path)

        assert result.truncated > 0
        assert not result.complete

    def test_excluded_dirs_do_not_count_as_truncated(self, tmp_path):
        """Build output is deliberately not repository source, so skipping it is
        not incompleteness — conflating the two would warn on every upload."""
        result = main._extract_zip_to_dir(
            _zip_of({"src/A.java": "a", "target/classes/A.class": "x", "node_modules/p/i.js": "y"}),
            tmp_path,
        )

        assert result.files == 1
        assert result.truncated == 0
        assert result.complete

    def test_zip_slip_entries_are_rejected_and_counted(self, tmp_path):
        result = main._extract_zip_to_dir(_zip_of({"../escape.java": "x", "ok.java": "y"}), tmp_path)

        assert result.unsafe == 1
        assert not (tmp_path.parent / "escape.java").exists()
        assert "outside the workspace" in result.warning()

    def test_default_limits_accommodate_a_large_monorepo(self):
        """2M lines of Java is roughly 15k-25k files; the old 5,000-file cap
        truncated any real monorepo."""
        assert config.WORKSPACE_MAX_FILES >= 50_000
        assert config.WORKSPACE_MAX_TOTAL_BYTES >= 1_000_000_000


class TestListFilesPaging:
    def _ctx(self, tmp_path, count: int):
        for i in range(count):
            (tmp_path / f"m{i % 4}").mkdir(exist_ok=True)
            (tmp_path / f"m{i % 4}" / f"F{i}.java").write_text("x")

        class Ctx:
            state = {"workspace_dir": str(tmp_path)}
        return Ctx()

    def test_page_is_capped_and_says_how_to_continue(self, tmp_path):
        ctx = self._ctx(tmp_path, 50)

        out = workspace_tools.list_files(ctx, ".", max_paths=10)

        assert "files 1-10 of 50" in out
        assert "offset=10" in out
        assert len([l for l in out.splitlines() if l.endswith(".java")]) == 10

    def test_offset_walks_the_listing(self, tmp_path):
        ctx = self._ctx(tmp_path, 50)

        out = workspace_tools.list_files(ctx, ".", offset=40, max_paths=10)

        assert "files 41-50 of 50" in out
        assert "offset=" not in out.splitlines()[0]  # last page: no continuation

    def test_paged_listing_includes_a_directory_rollup(self, tmp_path):
        """So an agent can narrow by subdir instead of paging a whole monorepo."""
        ctx = self._ctx(tmp_path, 50)

        out = workspace_tools.list_files(ctx, ".", max_paths=10)

        assert "Where the 50 files are" in out
        assert "m0" in out

    def test_small_listing_has_no_rollup_or_continuation(self, tmp_path):
        ctx = self._ctx(tmp_path, 3)

        out = workspace_tools.list_files(ctx, ".")

        assert "files 1-3 of 3" in out
        assert "Where the" not in out

    def test_summary_mode_returns_no_paths_at_all(self, tmp_path):
        ctx = self._ctx(tmp_path, 50)

        out = workspace_tools.list_files(ctx, ".", summary=True)

        assert "directory rollup only" in out
        assert ".java" not in out

    def test_offset_past_the_end_is_an_error_not_an_empty_page(self, tmp_path):
        ctx = self._ctx(tmp_path, 5)

        assert workspace_tools.list_files(ctx, ".", offset=99).startswith("ERROR:")

    def test_default_page_size_bounds_a_huge_tree(self, tmp_path):
        ctx = self._ctx(tmp_path, config.LIST_FILES_MAX_PATHS + 25)

        out = workspace_tools.list_files(ctx, ".")

        assert len([l for l in out.splitlines() if l.endswith(".java")]) == config.LIST_FILES_MAX_PATHS


class TestCommandOutputClipping:
    def test_short_output_is_untouched(self):
        assert workspace_tools._clip_command_output("all good") == "all good"

    def test_long_output_keeps_the_tail_where_the_errors_are(self):
        """A Maven reactor build opens with module banners and puts every
        [ERROR] and the reactor summary at the end. Head-first truncation handed
        the fixer the part with no errors in it."""
        output = ("BANNER\n" * 5_000) + "[ERROR] Foo.java:[12,7] cannot find symbol\nBUILD FAILURE\n"

        clipped = workspace_tools._clip_command_output(output, budget=2_000)

        assert "[ERROR] Foo.java:[12,7] cannot find symbol" in clipped
        assert "BUILD FAILURE" in clipped
        assert "BANNER" in clipped          # head kept too
        assert "omitted from the MIDDLE" in clipped
        assert len(clipped) < len(output)

    def test_clip_says_not_to_guess_the_omitted_middle(self):
        clipped = workspace_tools._clip_command_output("x" * 10_000, budget=500)

        assert "rather than assuming what it said" in clipped

    def test_build_timeout_is_generous_enough_for_a_reactor_build(self):
        """180s could not finish a multi-module build, so the loop failed on the
        clock and reported it indistinguishably from a real build failure."""
        assert config.COMMAND_TIMEOUT_SECONDS >= 900


class TestResultCollection:
    def _workspace(self, tmp_path, count: int) -> str:
        for i in range(count):
            (tmp_path / f"F{i}.java").write_text(f"class F{i} {{}}")
        (tmp_path / "target").mkdir()
        (tmp_path / "target" / "F.class").write_text("binary")
        return str(tmp_path)

    def test_preview_is_capped_but_reports_the_real_total(self, tmp_path, monkeypatch):
        monkeypatch.setattr(config, "RESULT_PREVIEW_MAX_FILES", 5)
        workspace = self._workspace(tmp_path, 30)

        files, total = main._workspace_to_files(workspace, "java")

        assert len(files) == 5
        assert total == 30  # build output excluded from both

    def test_archive_contains_every_file_not_just_the_preview(self, tmp_path, monkeypatch):
        monkeypatch.setattr(config, "RESULT_PREVIEW_MAX_FILES", 5)
        workspace = self._workspace(tmp_path, 30)

        archive = main._archive_workspace(workspace)

        assert archive
        with zipfile.ZipFile(archive) as zf:
            names = zf.namelist()
        assert len(names) == 30
        assert not any(n.startswith("target/") for n in names)
        Path(archive).unlink(missing_ok=True)

    def test_empty_workspace_produces_no_archive(self, tmp_path):
        assert main._archive_workspace(str(tmp_path)) is None

    def test_missing_workspace_is_not_fatal(self, tmp_path):
        assert main._archive_workspace(str(tmp_path / "gone")) is None
        assert main._workspace_to_files(str(tmp_path / "gone"), "java") == ([], 0)
