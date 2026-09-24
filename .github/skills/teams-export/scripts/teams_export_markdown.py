"""Render a raw Agency sidecar export as one combined Markdown file."""

import argparse
import html
import json
import re
from datetime import date, datetime, timedelta
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import quote, urlencode


def escape(text):
    return re.sub(r"([\\`*_\[\]<>#|])", r"\\\1", str(text))


def link_target(value):
    return str(value).replace(" ", "%20").replace("(", "%28").replace(")", "%29").replace("\n", "%0A")


def instant(value):
    result = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if result.tzinfo is None:
        raise ValueError("Message timestamps and export boundaries must include a time zone")
    return result


def covered_date(value):
    if not isinstance(value, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
        raise ValueError("Invalid covered date")
    return date.fromisoformat(value)


def output_filename(value):
    if (
        not isinstance(value, str)
        or not value.endswith(".md")
        or not value[:-3].strip()
        or re.search(r'[<>:"/\\|?*\x00-\x1f]', value)
        or value.split(".")[0].upper() in {
            "CON", "PRN", "AUX", "NUL",
            *(f"COM{i}" for i in range(1, 10)),
            *(f"LPT{i}" for i in range(1, 10)),
        }
    ):
        raise ValueError("markdownFile must be a safe single .md filename")
    return value


class BodyRenderer(HTMLParser):
    """Render common Teams HTML; retain unknown markup in an escaped fallback."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts = []
        self.links = []
        self.lists = []
        self.pre_depth = 0
        self.code_depth = 0
        self.unknown = set()

    def handle_starttag(self, tag, attributes):
        attrs = dict(attributes)
        if tag in {"p", "div", "blockquote"} or re.fullmatch(r"h[1-6]", tag):
            self.parts.append("\n\n")
        elif tag == "br":
            self.parts.append("\n")
        elif tag in {"strong", "b"}:
            self.parts.append("**")
        elif tag in {"em", "i"}:
            self.parts.append("*")
        elif tag in {"s", "del"}:
            self.parts.append("~~")
        elif tag == "pre":
            self.pre_depth += 1
            self.parts.append("\n\n<pre>")
        elif tag == "code":
            self.code_depth += 1
            self.parts.append("<code>")
        elif tag == "a":
            self.links.append(attrs.get("href"))
            self.parts.append("[")
        elif tag == "img":
            self.parts.append(
                f"![{escape(attrs.get('alt', 'Image'))}]({link_target(attrs.get('src', ''))})"
            )
        elif tag == "at":
            self.parts.append("@")
        elif tag in {"ol", "ul"}:
            self.lists.append([tag, int(attrs.get("start", "1")) - 1])
            self.parts.append("\n\n")
        elif tag == "li":
            if not self.lists:
                self.unknown.add("li-without-list")
                self.parts.append("\n- ")
            else:
                self.lists[-1][1] += 1
                marker = f"{self.lists[-1][1]}." if self.lists[-1][0] == "ol" else "-"
                self.parts.append(f"\n{'    ' * (len(self.lists) - 1)}{marker} ")
        elif tag == "hr":
            self.parts.append("\n\n---\n\n")
        elif tag in {"span", "body", "html"}:
            pass
        elif tag in {"table", "thead", "tbody", "tr", "td", "th"}:
            self.unknown.add(tag)
            self.parts.append("\n" if tag in {"table", "tr"} else " | ")
        else:
            self.unknown.add(tag)

    def handle_endtag(self, tag):
        if tag in {"p", "div", "blockquote"} or re.fullmatch(r"h[1-6]", tag):
            self.parts.append("\n\n")
        elif tag in {"strong", "b"}:
            self.parts.append("**")
        elif tag in {"em", "i"}:
            self.parts.append("*")
        elif tag in {"s", "del"}:
            self.parts.append("~~")
        elif tag == "pre":
            self.parts.append("</pre>\n\n")
            self.pre_depth = max(0, self.pre_depth - 1)
        elif tag == "code":
            self.parts.append("</code>")
            self.code_depth = max(0, self.code_depth - 1)
        elif tag == "a":
            if not self.links:
                raise ValueError("Unbalanced link markup")
            target = self.links.pop()
            self.parts.append(f"]({link_target(target)})" if target else "]")
        elif tag in {"ol", "ul"}:
            if not self.lists:
                raise ValueError("Unbalanced list markup")
            self.lists.pop()
            self.parts.append("\n\n")
        elif tag == "li":
            self.parts.append("\n")

    def handle_data(self, data):
        if self.pre_depth or self.code_depth:
            self.parts.append(html.escape(data, quote=False))
        else:
            self.parts.append(escape(re.sub(r"\s+", " ", data.replace("\xa0", " "))))

    def render(self, source):
        self.feed(source)
        self.close()
        if self.links or self.lists or self.code_depth or self.pre_depth:
            raise ValueError("Unbalanced message HTML")
        result = "".join(self.parts).strip()
        if self.unknown:
            # Unknown markup is never silently discarded, especially cards and tables.
            result += (
                "\n\n<details><summary>Original HTML (formatting not fully supported)</summary>\n\n"
                "<pre>" + html.escape(source) + "</pre>\n\n</details>"
            )
        return result


def message_body(message):
    body = message.get("body")
    if not isinstance(body, dict) or not isinstance(body.get("content"), str):
        if message.get("deletedDateTime"):
            return "_Message body unavailable; message was deleted._"
        raise ValueError(f"Message {message.get('id')} has no body")
    kind = body.get("contentType", "").lower()
    if kind == "html":
        return BodyRenderer().render(body["content"])
    if kind == "text":
        return escape(body["content"])
    raise ValueError(f"Unsupported body content type: {kind!r}")


def message_link(manifest, message_id, parent_id):
    query = urlencode({"groupId": manifest["teamId"], "parentMessageId": parent_id})
    return (
        f"https://teams.microsoft.com/l/message/{quote(manifest['channelId'], safe='')}/"
        f"{quote(str(message_id), safe='')}?{query}"
    )


def author(message):
    sender = message.get("from") or {}
    sender = sender.get("user") or sender.get("application") or sender
    return sender.get("displayName") or "Unknown author", sender.get("id")


def metadata(message, manifest, parent_id):
    name, sender_id = author(message)
    lines = [
        f"- **Author:** {escape(name)}",
        f"- **Created:** {message['exportCreatedTime']}",
        f"- **Message ID:** `{message['id']}`",
        f"- **Source:** [Open in Teams]({message_link(manifest, message['id'], parent_id)})",
    ]
    if sender_id:
        lines.append(f"- **Author ID:** `{sender_id}`")
    if message.get("exportModifiedTime"):
        lines.append(f"- **Last modified:** {message['exportModifiedTime']}")
    return "\n".join(lines)


def extras(message):
    lines = []
    if message.get("mentions"):
        lines.extend([
            "", "**Mentions (raw metadata):**",
            "<pre>" + html.escape(json.dumps(message["mentions"], ensure_ascii=False, indent=2)) + "</pre>",
        ])
    for attachment in message.get("attachments") or []:
        name = attachment.get("name") or attachment.get("id") or "Attachment"
        url = attachment.get("contentUrl")
        lines.extend(["", f"**Attachment:** [{escape(name)}]({link_target(url)})" if url
                      else f"**Attachment:** {escape(name)}"])
        # Preserve card content and other fields even when there is no downloadable URL.
        lines.append("<pre>" + html.escape(json.dumps(attachment, ensure_ascii=False, indent=2)) + "</pre>")
    for reaction in message.get("reactions") or []:
        lines.extend(["", "**Reaction:** " + escape(json.dumps(reaction, ensure_ascii=False))])
    return "\n".join(lines)


def render_export(directory):
    directory = Path(directory)
    manifest = json.loads((directory / "manifest.json").read_text(encoding="utf-8-sig"))
    path = directory.parent / output_filename(manifest["markdownFile"])
    first_day = covered_date(manifest["firstCoveredDate"])
    last_day = covered_date(manifest["lastCoveredDate"])
    if first_day > last_day:
        raise ValueError("Covered date range is reversed")
    start = instant(manifest["startTimeInclusive"])
    end = instant(manifest["endTimeExclusive"])
    if start >= end or start.utcoffset() != timedelta(0) or end.utcoffset() != timedelta(0):
        raise ValueError("Export boundaries must be increasing UTC timestamps")
    counts = manifest["counts"]
    if any(type(counts[key]) is not int or counts[key] < 0 for key in ("posts", "replies")):
        raise ValueError("Manifest counts must be nonnegative integers")
    threads_directory = directory / "threads"
    if not threads_directory.is_dir():
        raise ValueError("Required raw threads folder is missing")
    threads = []
    post_ids = set()
    reply_count = 0
    for file in threads_directory.glob("*.json"):
        thread = json.loads(file.read_text(encoding="utf-8-sig"))
        post = thread["post"]
        if post["id"] in post_ids:
            raise ValueError("Duplicate root post")
        post_ids.add(post["id"])
        day = covered_date(thread["day"])
        if not first_day <= day <= last_day:
            raise ValueError("Thread day is outside the covered date range")
        ids = [reply["id"] for reply in thread["replies"]]
        if len(ids) != len(set(ids)):
            raise ValueError("Duplicate replies")
        reply_count += len(ids)
        threads.append(thread)
    if len(post_ids) != manifest["counts"]["posts"] or reply_count != manifest["counts"]["replies"]:
        raise ValueError("Manifest counts do not match downloaded threads")
    threads.sort(key=lambda t: (instant(t["post"]["createdDateTime"]), t["post"]["id"]))
    sidecar = directory.name
    sidecar_link = quote(sidecar, safe="")
    lines = [
        f"# {escape(manifest['channelName'])} - {first_day} through {last_day}", "",
        f"Covered dates (inclusive): {first_day} through {last_day}",
        f"Time zone: {escape(manifest['timeZone'])}",
        f"Team ID: {escape(manifest['teamId'])}",
        f"Channel ID: {escape(manifest['channelId'])}",
        f"Posts: {len(post_ids)} | Replies: {reply_count}", "",
        f"UTC start (inclusive): {manifest['startTimeInclusive']}",
        f"UTC end (exclusive): {manifest['endTimeExclusive']}", "",
        "Posts are selected by creation time. Replies include all available dates.",
        f"Filename-scoped sidecar: [{escape(sidecar)}]({sidecar_link}/).",
        f"Raw message data: [{escape(sidecar + '/threads/')}]({sidecar_link}/threads/).",
        f"Completeness status: [{escape(sidecar + '/manifest.json')}]({sidecar_link}/manifest.json) "
        "is authoritative. This Markdown file alone does not certify a complete export; "
        "check the manifest's current status and any recorded failures.",
    ]
    for thread in threads:
        post = thread["post"]
        subject = post.get("subject") or f"Post {post['id']}"
        lines.extend(["", "---", "", "## " + escape(re.sub(r"\s+", " ", subject)), "",
                      metadata(post, manifest, post["id"]), "", message_body(post), extras(post)])
        replies = sorted(thread["replies"],
                         key=lambda m: (instant(m["createdDateTime"]), m["id"]))
        for index, reply in enumerate(replies, 1):
            name, _ = author(reply)
            lines.extend(["", f"### Reply {index} - {escape(name)}", "",
                          metadata(reply, manifest, post["id"]), "",
                          message_body(reply), extras(reply)])
    # Validate and render every thread before creating the sole output file.
    with path.open("x", encoding="utf-8", newline="\n") as stream:
        stream.write("\n".join(lines).rstrip() + "\n")
    print(f"Rendered {len(post_ids)} posts and {reply_count} replies into {path.name}.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--export-dir", required=True, type=Path)
    render_export(parser.parse_args().export_dir)
