"""Validate that every internal anchor reference in a markdown file
points to an existing heading.

Usage:  python validate_markdown_anchors.py <file_path>

Exit code 0 — all anchors resolve.
Exit code 1 — one or more dead anchors found (details on stderr).
"""

import re
import sys


def strip_inline_formatting(text: str) -> str:
    """Remove markdown inline formatting from heading text."""
    # Strip links: [text](url) → text
    text = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", text)
    # Strip bold: **text** or __text__ → text
    text = re.sub(r"\*\*(.+?)\*\*", r"\1", text)
    text = re.sub(r"__(.+?)__", r"\1", text)
    # Strip italic: *text* or _text_ → text
    text = re.sub(r"\*(.+?)\*", r"\1", text)
    text = re.sub(r"(?<!\w)_(.+?)_(?!\w)", r"\1", text)
    # Strip inline code: `text` → text
    text = re.sub(r"`(.+?)`", r"\1", text)
    return text


def heading_to_anchor(heading_text: str) -> str:
    """Convert a markdown heading to a GitHub-style anchor identifier."""
    text = strip_inline_formatting(heading_text)
    text = text.strip().lower()
    # Keep only word characters (letters, digits, underscore), spaces, and hyphens
    text = re.sub(r"[^\w\s-]", "", text)
    # Replace whitespace runs with a single hyphen
    text = re.sub(r"\s+", "-", text)
    return text


def extract_anchors_from_headings(content: str) -> dict[str, list[str]]:
    """Return a set of anchor identifiers derived from all headings.

    When duplicate headings exist, GitHub appends -1, -2, etc.
    This function replicates that behaviour.
    """
    heading_pattern = re.compile(r"^#{1,6}\s+(.+)$", re.MULTILINE)
    occurrence_counts: dict[str, int] = {}
    anchors: dict[str, list[str]] = {}

    for match in heading_pattern.finditer(content):
        raw_heading = match.group(1)
        base_anchor = heading_to_anchor(raw_heading)

        if base_anchor in occurrence_counts:
            occurrence_counts[base_anchor] += 1
            final_anchor = f"{base_anchor}-{occurrence_counts[base_anchor]}"
        else:
            occurrence_counts[base_anchor] = 0
            final_anchor = base_anchor

        anchors[final_anchor] = anchors.get(final_anchor, [])
        anchors[final_anchor].append(raw_heading)

    return anchors


def extract_same_file_anchor_references(content: str) -> list[tuple[str, str, int]]:
    """Return a list of (link_text, anchor, line_number) for same-file anchor links."""
    references = []
    for line_number, line in enumerate(content.splitlines(), start=1):
        for match in re.finditer(r"\[([^\]]*)\]\(#([^)]+)\)", line):
            link_text = match.group(1)
            anchor = match.group(2)
            references.append((link_text, anchor, line_number))
    return references


def main() -> int:
    if len(sys.argv) != 2:
        print("Usage: python validate_markdown_anchors.py <file_path>", file=sys.stderr)
        return 1

    file_path = sys.argv[1]

    try:
        with open(file_path, "r", encoding="utf-8") as file_handle:
            content = file_handle.read()
    except FileNotFoundError:
        print(f"File not found: {file_path}", file=sys.stderr)
        return 1

    anchors = extract_anchors_from_headings(content)
    references = extract_same_file_anchor_references(content)

    errors = []
    for link_text, anchor, line_number in references:
        if anchor not in anchors:
            errors.append(
                f"  line {line_number}: [{link_text}](#{anchor})"
            )

    if errors:
        print(f"Dead anchor links in {file_path}:", file=sys.stderr)
        for error in errors:
            print(error, file=sys.stderr)
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
