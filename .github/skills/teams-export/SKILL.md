---
name: teams-export
description: Export, download, or archive Microsoft Teams channel conversations from a channel URL and date range into Markdown using Agency. Use for saving channel posts and all their replies locally without summarizing the content.
---

# Export Teams channel conversations

Run the bundled deterministic `scripts\Export-TeamsChannel.ps1` with its
colocated Python renderer. See [README.md](README.md) for prerequisites,
standalone usage, time semantics, output layout and retry behavior.

## Agent boundary

- Gather only missing `ChannelUrl`, `StartTime` and `EndTime`, plus optional
  `OutputDir` and `TimeZone`. Accept a raw channel URL or Markdown channel link.
  Preserve the user's exact date/time strings: `StartTime` is inclusive and
  **`EndTime` is exclusive**, based on root creation time. Explain this boundary;
  do not silently add a day or otherwise reinterpret the dates.
- Resolve the **absolute** script path relative to this actual `SKILL.md`
  location, not the repository or current working directory. Keep the bundled
  script and renderer together.
- Resolve an explicit, fully qualified `OutputDir`; default to
  `teams-export` under the caller's working directory, not under this skill.
  Omit `TimeZone` for the machine-local zone. An explicit offset or `Z` in a
  timestamp still denotes an absolute instant.
- The script owns **all** authentication checks, Agency/MCP startup, channel
  resolution, pagination, filtering, reply collection, rendering, retries and
  process cleanup. Do not reproduce these operations in the agent, invoke a
  nested `agency copilot`/LLM, page message tools yourself, or summarize,
  regenerate or replace the script.
- Never load raw/exported message bodies, Markdown, thread JSON or full log
  contents into model context. Explicit subsequent content analysis is a
  **separate task**, not part of exporting.

## Safe invocation and visible progress

1. Serialize a JSON **data file**, never interpolate user values into shell
   source. Its only allowed keys are `ChannelUrl`, `StartTime`, `EndTime`,
   `OutputDir` (all required nonempty strings), and optional nonempty string
   `TimeZone`. `OutputDir` must be fully qualified.
2. Choose a fresh GUID per run. Prefer the OS temporary directory for absolute
   `teams-export-run-<GUID>.input.json` and
   `teams-export-run-<GUID>.result.json` paths, subject to host file-access
   policy; otherwise use a private permitted directory. Write only the input
   file. **Do not precreate the result file**: `SummaryPath` is exclusively
   claimed by the script and existing files are refused.
3. Run the absolute bundled script with absolute input and result paths:

   ```powershell
   pwsh -NoProfile -File $absoluteScriptPath `
       -InputPath $absoluteInputPath -SummaryPath $absoluteSummaryPath
   ```

   These variables hold trusted resolved paths, not interpolated shell source.
   Use `SummaryPath` for the result without hiding console progress.
4. **Keep progress visible while running.** Prefer a foreground visible
   terminal/canvas when the host supports it; otherwise use a streaming
   terminal. The script emits timestamped operations, progress counters,
   retries and terminal errors: INFO/ERROR use `Write-Host`, while WARN uses
   the warning stream. Both remain visible independently of Copilot UI support.
   If capturing output, tee progress to the terminal:
   never silently hide it behind a background command or redirect everything
   to a file. Do not detach unless explicitly requested. If the host cannot
   display streaming output, disclose that limitation and point to the
   script's live readable log and result/status paths; do not claim visibility.
   Do not repeatedly ingest full progress or log output into model context.
5. Wait for the process to finish, retain its exit code, then read **only the
   small result JSON**. Success requires **exit code 0 AND `status: complete`**.
   Existing Markdown, a previous result or an exit code alone is not proof.
   Binding/pre-start failures can leave no result: explicitly report failure
   rather than treating missing metadata as success.

## Result and failure reporting

The result is metadata only: `status`, `phase`, `outputPath` (absolute Markdown
path), `manifestPath`, `dataDirectory`, `counts`, `timeZone`,
`startTimeInclusive`, `endTimeExclusive`, `diagnosticsPath`, and sanitized
`error`. It transitions through `in_progress` to `complete`, `incomplete` or
`failed`.

Report status, absolute output/manifest/data paths, counts and the interpreted
timezone and interval. On failure, report the sanitized phase and available
diagnostics/status paths; request only bounded metadata-only diagnostics if
truly blocked. Never expose message bodies or read full logs to diagnose.
The script preserves its unique OS-temp `teams-export-run-<GUID>.log`; report
that path instead of its contents. Remove the invocation input JSON after
completion; retain the result and diagnostics for troubleshooting. Never
delete existing exports or retry over them: no-overwrite protection applies
to Markdown and same-stem `.data` directories, including incomplete exports.
