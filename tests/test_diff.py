from gitwarden.diff import AddedLine, lines_from_file, parse_diff

NEW_FILE_DIFF = """\
diff --git a/app/settings.py b/app/settings.py
new file mode 100644
index 0000000..3b18e51
--- /dev/null
+++ b/app/settings.py
@@ -0,0 +1,2 @@
+DEBUG = False
+TOKEN = "abc"
"""

MODIFIED_DIFF = """\
diff --git a/config.yml b/config.yml
index 1111111..2222222 100644
--- a/config.yml
+++ b/config.yml
@@ -3 +3 @@ name: app
-password: old
+password: new
@@ -10,0 +11,2 @@ other:
+  a: 1
+  b: 2
"""


def test_new_file_lines_are_added_with_line_numbers():
    parsed = parse_diff(NEW_FILE_DIFF)
    assert parsed.lines == [
        AddedLine("app/settings.py", 1, "DEBUG = False"),
        AddedLine("app/settings.py", 2, 'TOKEN = "abc"'),
    ]


def test_removed_lines_are_ignored_and_hunks_set_line_numbers():
    parsed = parse_diff(MODIFIED_DIFF)
    assert [(line.line_no, line.text) for line in parsed.lines] == [
        (3, "password: new"),
        (11, "  a: 1"),
        (12, "  b: 2"),
    ]


def test_added_line_that_starts_with_plus_signs_is_content_not_header():
    diff = MODIFIED_DIFF + "@@ -20,0 +21 @@\n+++ not a header\n"
    parsed = parse_diff(diff)
    assert parsed.lines[-1] == AddedLine("config.yml", 21, "++ not a header")


def test_binary_files_are_reported_not_scanned():
    diff = (
        "diff --git a/logo.png b/logo.png\n"
        "new file mode 100644\n"
        "index 0000000..1234567\n"
        "Binary files /dev/null and b/logo.png differ\n"
    )
    parsed = parse_diff(diff)
    assert parsed.lines == []
    assert parsed.binary_paths == ["logo.png"]


def test_renamed_file_uses_new_name_and_no_newline_marker_is_ignored():
    diff = (
        "diff --git a/old name.txt b/new name.txt\n"
        "similarity index 80%\n"
        "rename from old name.txt\n"
        "rename to new name.txt\n"
        "--- a/old name.txt\t\n"
        "+++ b/new name.txt\t\n"
        "@@ -1 +1 @@\n"
        "-hello\n"
        "+hello world\n"
        "\\ No newline at end of file\n"
    )
    parsed = parse_diff(diff)
    assert parsed.lines == [AddedLine("new name.txt", 1, "hello world")]


def test_commit_sha_is_attached_and_crlf_is_stripped():
    diff = NEW_FILE_DIFF.replace("+DEBUG = False\n", "+DEBUG = False\r\n")
    parsed = parse_diff(diff, commit="abc123")
    assert parsed.lines[0] == AddedLine("app/settings.py", 1, "DEBUG = False", "abc123")


def test_lines_from_file_numbers_every_line():
    assert lines_from_file("a.txt", "one\r\ntwo\n") == [
        AddedLine("a.txt", 1, "one"),
        AddedLine("a.txt", 2, "two"),
        AddedLine("a.txt", 3, ""),
    ]
