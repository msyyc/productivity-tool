"""Tests for compare_reports.py"""

import os
import tempfile

import pytest

import sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from compare_reports import parse_changelog, update_changelog


# ---------------------------------------------------------------------------
# parse_changelog
# ---------------------------------------------------------------------------
class TestParseChangelog:
    def test_extracts_content_between_markers(self):
        output = (
            "some prefix\n"
            "===== changelog start =====\n"
            "### Breaking Changes\n"
            "\n"
            "  - Removed model `Foo`\n"
            "  - Renamed `bar` to `baz`\n"
            "===== changelog end =====\n"
            "some suffix\n"
        )
        result = parse_changelog(output)
        assert "### Breaking Changes" in result
        assert "Removed model `Foo`" in result
        assert "Renamed `bar` to `baz`" in result

    def test_no_markers_returns_none(self):
        output = "no changelog markers here\njust normal output\n"
        result = parse_changelog(output)
        assert result is None

    def test_empty_changelog(self):
        output = (
            "===== changelog start =====\n"
            "\n"
            "===== changelog end =====\n"
        )
        result = parse_changelog(output)
        # Empty string stripped becomes empty or None-ish
        assert result == "" or result is None

    def test_multiline_changelog(self):
        output = (
            "===== changelog start =====\n"
            "### Breaking Changes\n"
            "\n"
            "  - Change 1\n"
            "\n"
            "### Features Added\n"
            "\n"
            "  - Feature 1\n"
            "\n"
            "### Other Changes\n"
            "\n"
            "  - Migrated from Swagger to TypeSpec\n"
            "===== changelog end =====\n"
        )
        result = parse_changelog(output)
        assert "### Breaking Changes" in result
        assert "### Features Added" in result
        assert "### Other Changes" in result

    def test_markers_in_stderr_mixed(self):
        output = (
            "stdout stuff\n"
            "\n"
            "===== changelog start =====\n"
            "### Other Changes\n"
            "\n"
            "  - Migration\n"
            "===== changelog end =====\n"
        )
        result = parse_changelog(output)
        assert "### Other Changes" in result


# ---------------------------------------------------------------------------
# update_changelog
# ---------------------------------------------------------------------------
class TestUpdateChangelog:
    def test_creates_new_file_when_missing(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            changelog_path = os.path.join(tmpdir, "CHANGELOG.md")
            update_changelog(changelog_path, "### Breaking Changes\n\n  - Removed Foo")
            assert os.path.isfile(changelog_path)
            with open(changelog_path, "r", encoding="utf-8") as f:
                content = f.read()
            assert "# Release History" in content
            assert "### Breaking Changes" in content
            assert "Removed Foo" in content

    def test_inserts_under_first_version_heading(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            changelog_path = os.path.join(tmpdir, "CHANGELOG.md")
            original = (
                "# Release History\n"
                "\n"
                "## 1.0.0b1 (Unreleased)\n"
                "\n"
                "## 0.9.0 (2025-01-01)\n"
                "\n"
                "### Features Added\n"
                "\n"
                "  - Old feature\n"
            )
            with open(changelog_path, "w", encoding="utf-8") as f:
                f.write(original)

            update_changelog(changelog_path, "### Breaking Changes\n\n  - Removed Foo")

            with open(changelog_path, "r", encoding="utf-8") as f:
                content = f.read()
            # New content should be under the first ## heading
            assert content.index("### Breaking Changes") < content.index("## 0.9.0")
            assert "Removed Foo" in content
            # Old content under second heading should be preserved
            assert "Old feature" in content

    def test_replaces_existing_content_under_heading(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            changelog_path = os.path.join(tmpdir, "CHANGELOG.md")
            original = (
                "# Release History\n"
                "\n"
                "## 1.0.0b1 (Unreleased)\n"
                "\n"
                "### Other Changes\n"
                "\n"
                "  - Placeholder\n"
                "\n"
                "## 0.9.0 (2025-01-01)\n"
                "\n"
                "  - Old stuff\n"
            )
            with open(changelog_path, "w", encoding="utf-8") as f:
                f.write(original)

            update_changelog(changelog_path, "### Breaking Changes\n\n  - New breaking change")

            with open(changelog_path, "r", encoding="utf-8") as f:
                content = f.read()
            # Placeholder should be replaced
            assert "Placeholder" not in content
            assert "New breaking change" in content
            # Second version section preserved
            assert "Old stuff" in content

    def test_appends_when_no_version_heading(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            changelog_path = os.path.join(tmpdir, "CHANGELOG.md")
            original = "# Release History\n\nSome intro text.\n"
            with open(changelog_path, "w", encoding="utf-8") as f:
                f.write(original)

            update_changelog(changelog_path, "### Other Changes\n\n  - Migration")

            with open(changelog_path, "r", encoding="utf-8") as f:
                content = f.read()
            assert "### Other Changes" in content
            assert "Migration" in content

    def test_preserves_multiple_version_sections(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            changelog_path = os.path.join(tmpdir, "CHANGELOG.md")
            original = (
                "# Release History\n"
                "\n"
                "## 2.0.0 (Unreleased)\n"
                "\n"
                "## 1.0.0 (2025-06-01)\n"
                "\n"
                "  - v1 feature\n"
                "\n"
                "## 0.5.0 (2025-01-01)\n"
                "\n"
                "  - v0.5 feature\n"
            )
            with open(changelog_path, "w", encoding="utf-8") as f:
                f.write(original)

            update_changelog(changelog_path, "### Features Added\n\n  - New feature")

            with open(changelog_path, "r", encoding="utf-8") as f:
                content = f.read()
            assert "New feature" in content
            assert "v1 feature" in content
            assert "v0.5 feature" in content
