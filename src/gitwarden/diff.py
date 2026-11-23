"""Turn `git diff` output into the list of lines that were added.

We only scan added lines: deleting a secret should never block a commit.
"""

import re
from dataclasses import dataclass, field

# "@@ -10,2 +12,3 @@" -> the new file's changes start at line 12
HUNK_HEADER = re.compile(r"^@@ -\d+(?:,\d+)? \+(\d+)(?:,\d+)? @@")
# "Binary files /dev/null and b/logo.png differ"
BINARY_LINE = re.compile(r"^Binary files (.+?) and (.+) differ$")


@dataclass
class AddedLine:
    """One added line: which file, which line number, and its text."""

    path: str
    line_no: int
    text: str
    commit: str | None = None  # None for staged changes, else the commit SHA


@dataclass
class ParsedDiff:
    """Everything a diff tells the scanner: added lines and binary files."""

    lines: list[AddedLine] = field(default_factory=list)
    binary_paths: list[str] = field(default_factory=list)


def parse_diff(diff_text: str, commit: str | None = None) -> ParsedDiff:
    """Read unified diff text (from `git diff` or `git show`) and collect the added lines."""
    result = ParsedDiff()
    path: str | None = None  # file we are in; None for deleted files
    in_hunk = False  # False while reading a file's header lines
    line_no = 0  # line number in the new file of the next added or context line

    for raw in diff_text.split("\n"):
        if raw.startswith("diff --git "):
            path, in_hunk = None, False
            continue
        hunk = HUNK_HEADER.match(raw)
        if hunk:
            in_hunk = True
            line_no = int(hunk.group(1))
            continue
        if not in_hunk:
            path = _read_header_line(raw, path, result)
            continue
        if raw.startswith("+"):
            if path is not None:
                result.lines.append(AddedLine(path, line_no, raw[1:].rstrip("\r"), commit))
            line_no += 1
        elif raw.startswith(" "):
            line_no += 1
        # "-" lines and "\ No newline at end of file" don't move the new file's line number

    return result


def lines_from_file(path: str, content: str) -> list[AddedLine]:
    """Treat every line of a whole file as added (used by `gitwarden scan PATH`)."""
    lines = []
    for number, text in enumerate(content.split("\n"), start=1):
        lines.append(AddedLine(path, number, text.rstrip("\r")))
    return lines


def _read_header_line(raw: str, path: str | None, result: ParsedDiff) -> str | None:
    """Handle one line from a file's header. Returns the (maybe new) current path."""
    if raw.startswith("+++ "):
        return _clean_path(raw[4:])
    binary = BINARY_LINE.match(raw)
    if binary:
        binary_path = _clean_path(binary.group(2))
        if binary_path is not None:
            result.binary_paths.append(binary_path)
    return path


def _clean_path(name: str) -> str | None:
    """'b/src/app.py' -> 'src/app.py'; '/dev/null' (file deleted) -> None."""
    name = name.rstrip("\t")  # git adds a tab after file names that contain spaces
    if name.startswith('"') and name.endswith('"'):
        name = name[1:-1]  # git quotes names with special characters
    if name == "/dev/null":
        return None
    if name.startswith("b/"):
        return name[2:]
    return name
