"""
The workspace editing tools: windowed reads, the full-overwrite guard that
keeps a partial read from deleting the rest of a file, and replace_in_file.
"""
import types as pytypes

from agents.shared import workspace_tools as wt


def ctx(tmp_path):
    return pytypes.SimpleNamespace(state={"workspace_dir": str(tmp_path)})


def big_file(tmp_path, name: str = "Big.java") -> tuple[object, int]:
    """A file comfortably larger than one read window."""
    lines = [f"// line {i}" for i in range(1, 3001)]
    (tmp_path / name).write_text("\n".join(lines), encoding="utf-8")
    return ctx(tmp_path), len(lines)


def test_read_file_returns_a_window_and_says_how_to_continue(tmp_path):
    context, total = big_file(tmp_path)

    first = wt.read_file(context, "Big.java")

    assert first.startswith(f"# Big.java — lines 1-")
    assert f"of {total}" in first
    assert "call read_file again with start_line=" in first
    assert len(first) <= wt.MAX_OUTPUT_CHARS + 200


def test_read_file_continues_from_the_given_start_line(tmp_path):
    context, total = big_file(tmp_path)

    window = wt.read_file(context, "Big.java", start_line=2900)

    assert f"# Big.java — lines 2900-{total} of {total}" in window
    assert "// line 3000" in window
    assert "not the whole file" not in window


def test_read_file_respects_max_lines(tmp_path):
    context, _ = big_file(tmp_path)

    window = wt.read_file(context, "Big.java", start_line=10, max_lines=3)

    assert "# Big.java — lines 10-12 of 3000" in window
    assert window.strip().endswith("// line 12")


def test_read_file_rejects_a_start_line_past_the_end(tmp_path):
    context, _ = big_file(tmp_path)

    assert wt.read_file(context, "Big.java", start_line=99_999).startswith("ERROR:")


def test_write_file_refuses_to_overwrite_a_file_bigger_than_one_window(tmp_path):
    context, _ = big_file(tmp_path)

    result = wt.write_file(context, "Big.java", "// truncated rewrite")

    assert result.startswith("ERROR:")
    assert "replace_in_file" in result
    # The original must be untouched — this is the data-loss case the guard exists for.
    assert (tmp_path / "Big.java").read_text().count("\n") == 2999


def test_write_file_allows_an_acknowledged_full_overwrite(tmp_path):
    context, _ = big_file(tmp_path)

    result = wt.write_file(context, "Big.java", "// deliberate rewrite", allow_full_overwrite=True)

    assert result.startswith("Wrote ")
    assert (tmp_path / "Big.java").read_text() == "// deliberate rewrite"


def test_write_file_still_creates_and_replaces_normal_files(tmp_path):
    context = ctx(tmp_path)

    assert wt.write_file(context, "src/New.java", "class New {}").startswith("Wrote ")
    assert wt.write_file(context, "src/New.java", "class New2 {}").startswith("Wrote ")
    assert (tmp_path / "src/New.java").read_text() == "class New2 {}"


def test_replace_in_file_edits_just_the_snippet(tmp_path):
    context = ctx(tmp_path)
    (tmp_path / "Dao.java").write_text("import javax.sql.DataSource;\nclass Dao {}\n", encoding="utf-8")

    result = wt.replace_in_file(context, "Dao.java", "import javax.sql.DataSource;", "import javax.sql.DataSource; // kept")

    assert result.startswith("Replaced 1 occurrence")
    assert (tmp_path / "Dao.java").read_text() == "import javax.sql.DataSource; // kept\nclass Dao {}\n"


def test_replace_in_file_refuses_an_ambiguous_snippet(tmp_path):
    context = ctx(tmp_path)
    (tmp_path / "A.java").write_text("int x = 1;\nint x = 1;\n", encoding="utf-8")

    result = wt.replace_in_file(context, "A.java", "int x = 1;", "int x = 2;")

    assert result.startswith("ERROR:")
    assert "occurs 2 times" in result
    assert (tmp_path / "A.java").read_text() == "int x = 1;\nint x = 1;\n"


def test_replace_in_file_can_replace_every_occurrence_on_request(tmp_path):
    context = ctx(tmp_path)
    (tmp_path / "A.java").write_text("int x = 1;\nint x = 1;\n", encoding="utf-8")

    result = wt.replace_in_file(context, "A.java", "int x = 1;", "int x = 2;", expected_count=2)

    assert result.startswith("Replaced 2 occurrence")
    assert (tmp_path / "A.java").read_text() == "int x = 2;\nint x = 2;\n"


def test_replace_in_file_reports_a_snippet_that_is_not_there(tmp_path):
    context = ctx(tmp_path)
    (tmp_path / "A.java").write_text("class A {}\n", encoding="utf-8")

    result = wt.replace_in_file(context, "A.java", "class B {}", "class C {}")

    assert result.startswith("ERROR:")
    assert "not found" in result


def test_replace_in_file_rejects_empty_or_no_op_edits(tmp_path):
    context = ctx(tmp_path)
    (tmp_path / "A.java").write_text("class A {}\n", encoding="utf-8")

    assert wt.replace_in_file(context, "A.java", "", "x").startswith("ERROR:")
    assert wt.replace_in_file(context, "A.java", "class A {}", "class A {}").startswith("ERROR:")


def test_replace_in_file_cannot_escape_the_workspace(tmp_path):
    context = ctx(tmp_path)
    (tmp_path.parent / "outside.txt").write_text("secret", encoding="utf-8")

    assert wt.replace_in_file(context, "../outside.txt", "secret", "leaked").startswith("ERROR:")
    assert (tmp_path.parent / "outside.txt").read_text() == "secret"
