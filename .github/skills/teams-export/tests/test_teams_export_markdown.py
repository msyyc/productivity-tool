import html
import json
import os
import shutil
import subprocess
import sys
import unittest
from pathlib import Path
from uuid import uuid4

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))
from teams_export_markdown import BodyRenderer, message_body, render_export


class RendererTests(unittest.TestCase):
    def test_preformatted_content_is_not_collapsed(self):
        text = BodyRenderer().render("<pre><code>a\n\n\n    &lt;b&gt;`</code></pre>")
        self.assertIn("a\n\n\n    &lt;b&gt;`", text)

    def test_unknown_markup_has_lossless_escaped_fallback(self):
        source = "<table><tr><td>Important</td></tr></table>"
        text = BodyRenderer().render(source)
        self.assertIn("Important", text)
        self.assertIn("&lt;table&gt;", text)

    def test_plain_text_does_not_become_markup(self):
        self.assertEqual(message_body({"body": {"contentType": "text", "content": "<x>*"}}), r"\<x\>\*")

    def test_missing_body_fails_unless_deleted(self):
        with self.assertRaises(ValueError):
            message_body({"id": "1"})
        self.assertIn("deleted", message_body({"deletedDateTime": "2026-09-01T00:00:00Z"}))


class ExportTests(unittest.TestCase):
    def setUp(self):
        self.workspace = Path.cwd() / f".renderer-fixture-{uuid4().hex}"
        self.workspace.mkdir()
        self.addCleanup(shutil.rmtree, self.workspace)
        self.directory = self.workspace / "synthetic channel.data"
        (self.directory / "threads").mkdir(parents=True)
        self.manifest = {
            "markdownFile": "synthetic channel.md",
            "firstCoveredDate": "2026-09-01",
            "lastCoveredDate": "2026-09-02",
            "timeZone": "Asia/Shanghai",
            "channelName": "Synthetic channel",
            "teamId": "synthetic-team",
            "channelId": "synthetic-channel",
            "counts": {"posts": 0, "replies": 0},
            "startTimeInclusive": "2026-08-31T16:00:00Z",
            "endTimeExclusive": "2026-09-02T16:00:00Z",
            "status": "in_progress",
        }
        self.output = self.workspace / self.manifest["markdownFile"]

    def message(self, message_id, created, content=None):
        return {
            "id": message_id,
            "createdDateTime": created,
            "exportCreatedTime": created,
            "from": {"user": {"displayName": f"Author {message_id}", "id": f"user-{message_id}"}},
            "body": {"contentType": "html", "content": content or f"<p>Body {message_id}</p>"},
        }

    def write_manifest(self):
        (self.directory / "manifest.json").write_text(
            json.dumps(self.manifest), encoding="utf-8-sig"
        )

    def write_thread(self, filename, post, replies=None, day="2026-09-01"):
        replies = [] if replies is None else replies
        (self.directory / "threads" / filename).write_text(
            json.dumps({"day": day, "post": post, "replies": replies}), encoding="utf-8"
        )
        self.manifest["counts"]["posts"] += 1
        self.manifest["counts"]["replies"] += len(replies)

    def render(self):
        self.write_manifest()
        render_export(self.directory)
        return self.output.read_text(encoding="utf-8")

    def assert_invalid(self, exception=ValueError):
        self.write_manifest()
        with self.assertRaises(exception):
            render_export(self.directory)
        self.assertEqual(list(self.workspace.rglob("*.md")), [])

    def test_one_exact_combined_filename_and_chronological_threads_and_replies(self):
        self.write_thread(
            "a-later-root.json",
            self.message("later-root", "2026-09-02T00:00:00Z"),
            day="2026-09-02",
        )
        self.write_thread(
            "z-earlier-root.json",
            self.message("earlier-root", "2026-09-01T00:00:00Z"),
            [
                self.message("later-reply", "2026-09-10T00:00:00Z"),
                self.message("earlier-reply", "2026-09-01T01:00:00Z"),
            ],
        )
        text = self.render()
        self.assertEqual(list(self.workspace.rglob("*.md")), [self.output])
        positions = [text.index(f"**Message ID:** `{message_id}`") for message_id in
                     ("earlier-root", "earlier-reply", "later-reply", "later-root")]
        self.assertEqual(positions, sorted(positions))
        self.assertIn("2026-09-10T00:00:00Z", text)
        self.assertIn("Posts: 2 | Replies: 2", text)

    def test_sort_uses_instants_and_id_tiebreaker(self):
        self.write_thread("a.json", self.message("c", "2026-09-01T00:00:00Z"))
        self.write_thread("b.json", self.message("b", "2026-09-01T08:00:00+08:00"))
        self.write_thread("c.json", self.message("a", "2026-09-01T07:00:00+08:00"))
        text = self.render()
        positions = [text.index(f"**Message ID:** `{value}`") for value in ("a", "b", "c")]
        self.assertEqual(positions, sorted(positions))

    def test_zero_posts_creates_one_file_with_range_and_authoritative_sidecar(self):
        text = self.render()
        self.assertEqual(list(self.workspace.rglob("*.md")), [self.output])
        for value in ("2026-09-01 through 2026-09-02", "Asia/Shanghai",
                      "Posts: 0 | Replies: 0", "2026-08-31T16:00:00Z",
                      "2026-09-02T16:00:00Z", "synthetic-team", "synthetic-channel",
                      "(synthetic%20channel.data/threads/)",
                      "(synthetic%20channel.data/manifest.json)", "is authoritative"):
            self.assertIn(value, text)
        self.assertNotIn("Status: complete", text)
        self.assertNotIn("in_progress", text)
        self.assertEqual(json.loads((self.directory / "manifest.json").read_text(
            encoding="utf-8-sig"))["status"], "in_progress")

    def test_missing_threads_folder_is_not_an_empty_export(self):
        (self.directory / "threads").rmdir()
        self.assert_invalid()

    def test_post_count_mismatch(self):
        self.manifest["counts"]["posts"] = 1
        self.assert_invalid()

    def test_reply_count_mismatch(self):
        self.write_thread("one.json", self.message("one", "2026-09-01T00:00:00Z"))
        self.manifest["counts"]["replies"] = 1
        self.assert_invalid()

    def test_invalid_count_types(self):
        for value in (-1, True, 0.0, "0"):
            with self.subTest(value=value):
                self.manifest["counts"]["posts"] = value
                self.assert_invalid()

    def test_duplicate_roots(self):
        post = self.message("same", "2026-09-01T00:00:00Z")
        self.write_thread("one.json", post)
        self.write_thread("two.json", post)
        self.assert_invalid()

    def test_duplicate_replies(self):
        reply = self.message("same-reply", "2026-09-02T00:00:00Z")
        self.write_thread("one.json", self.message("one", "2026-09-01T00:00:00Z"),
                          [reply, reply])
        self.assert_invalid()

    def test_unsafe_output_filenames(self):
        for filename in ("../escaped.md", r"..\escaped.md", "nested/output.md",
                         r"nested\output.md", "/absolute.md", r"C:\absolute.md",
                         "C:relative.md", "bad.md:stream", "output.txt", ".md",
                         "bad\x00.md", "CON.md", "", None):
            with self.subTest(filename=filename):
                self.manifest["markdownFile"] = filename
                self.assert_invalid()

    def test_invalid_covered_dates(self):
        for first, last in (("2026-02-30", "2026-09-02"), ("2026-9-1", "2026-09-02"),
                            ("2026-09-03", "2026-09-02"), ("2026-09-01", "2026-13-01")):
            with self.subTest(first=first, last=last):
                self.manifest["firstCoveredDate"], self.manifest["lastCoveredDate"] = first, last
                self.assert_invalid()

    def test_invalid_thread_day(self):
        for day in ("2026-09-31", "2026-9-1", "2026-09-03"):
            with self.subTest(day=day):
                self.manifest["counts"] = {"posts": 0, "replies": 0}
                self.write_thread("one.json", self.message("one", "2026-09-01T00:00:00Z"), day=day)
                self.assert_invalid()

    def test_invalid_boundaries(self):
        for start in ("not-a-date", "2026-09-03T00:00:00Z", "2026-09-02T16:00:00Z",
                      "2026-08-31T16:00:00", "2026-09-01T00:00:00+08:00"):
            with self.subTest(start=start):
                self.manifest["startTimeInclusive"] = start
                self.assert_invalid()

    def test_invalid_message_timestamp(self):
        self.write_thread("one.json", self.message("one", "2026-02-30T00:00:00Z"))
        self.assert_invalid()

    def test_render_failure_does_not_create_partial_output(self):
        self.write_thread("one.json", self.message("one", "2026-09-01T00:00:00Z"))
        self.write_thread("two.json", self.message("two", "2026-09-02T00:00:00Z", "<a>unclosed"))
        self.assert_invalid()

    def test_overwrite_refused_and_original_untouched(self):
        original = b"Existing Markdown\r\nmust not change.\r\n"
        self.output.write_bytes(original)
        self.write_manifest()
        with self.assertRaises(FileExistsError):
            render_export(self.directory)
        self.assertEqual(self.output.read_bytes(), original)
        self.assertEqual(list(self.workspace.rglob("*.md")), [self.output])

    def test_preserves_html_code_attachments_reactions_and_mentions(self):
        source = (
            '<p>Hello <at id="0">Synthetic Person</at> <strong>bold</strong> '
            '<em>italic</em> <a href="https://example.invalid/a?q=1&amp;x=2">link</a></p>'
            '<pre><code>a\n\n    &lt;b&gt;`</code></pre>'
            '<attachment id="card"></attachment><table><tr><td>Cell</td></tr></table>'
        )
        post = self.message("one", "2026-09-01T00:00:00Z", source)
        post["exportModifiedTime"] = "2026-09-02T00:00:00+08:00"
        post["attachments"] = [
            {"id": "file", "name": "Synthetic file", "contentUrl": "https://example.invalid/a file"},
            {"id": "card", "contentType": "application/example", "content": "<card>important</card>"},
        ]
        post["mentions"] = [{"id": 0, "mentionText": "Synthetic Person",
                             "mentioned": {"user": {"id": "synthetic-mentioned-user"}}}]
        post["reactions"] = [{"reactionType": "like", "user": {"user": {"id": "synthetic-reactor"}}}]
        self.write_thread("one.json", post)
        text = self.render()
        for value in ("@Synthetic Person", "**bold**", "*italic*",
                      "[link](https://example.invalid/a?q=1&x=2)",
                      "a\n\n    &lt;b&gt;`", html.escape(source),
                      "[Synthetic file](https://example.invalid/a%20file)",
                      "&lt;card&gt;important&lt;/card&gt;", "**Reaction:**",
                      "synthetic-reactor", "**Mentions (raw metadata):**",
                      "synthetic-mentioned-user", "**Author ID:** `user-one`",
                      "**Last modified:** 2026-09-02T00:00:00+08:00",
                      "https://teams.microsoft.com/l/message/synthetic-channel/one?"):
            self.assertIn(value, text)
        self.assertIn(html.escape(json.dumps(post["mentions"], ensure_ascii=False, indent=2)), text)

    def test_cli_failures_are_nonzero_and_leave_no_output(self):
        (self.directory / "threads").rmdir()
        self.write_manifest()
        result = subprocess.run(
            [sys.executable, str(SCRIPTS / "teams_export_markdown.py"),
             "--export-dir", str(self.directory)],
            capture_output=True, text=True,
            env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Required raw threads folder is missing", result.stderr)
        self.assertFalse(self.output.exists())


if __name__ == "__main__":
    unittest.main()
