# Teams export skill: standalone script reference

Export root posts created in a chosen interval, with **all available replies**
(including replies created after the interval), to one combined Markdown file.
This uses JSON-RPC directly with `agency mcp teams --transport http`, not an AI
runtime. It does not download linked files.

## Use as a skill

Ask Copilot: "Export this Teams channel to Markdown from 2026-09-01 inclusive
to 2026-09-24 exclusive: `<channel URL>`." You may also specify an output
directory or timezone. See [SKILL.md](SKILL.md) for the strict agent boundary:
the agent gathers inputs, runs the bundled script and reports metadata without
reading or summarizing conversation content.

## Requirements and usage

Install PowerShell **7.5+** (`ConvertFrom-Json -DateKind String`), Python **3.10+**
(`python` on PATH; standard library only), and Agency (`agency` on PATH),
authenticated to the work account that can access the team/channel. The script
does not install dependencies or change account/tenant automatically.

From this repository's root in PowerShell:

```powershell
$channelUrl = Read-Host 'Paste the Teams channel URL or [channel name](URL)'
pwsh -NoProfile -File .\.github\skills\teams-export\scripts\Export-TeamsChannel.ps1 `
    -ChannelUrl $channelUrl `
    -StartTime '2026-09-01' -EndTime '2026-09-24' `
    -OutputDir '.\teams-export'
```

Use a channel link with this shape on `teams.microsoft.com` or
`teams.cloud.microsoft`:

```text
https://teams.microsoft.com/l/channel/<encoded-channel-id>/<encoded-channel-name>?groupId=<team-guid>&tenantId=<tenant-guid>
```

Raw links and pasted `[channel name](URL)` wrappers are supported. Both
`groupId` and `tenantId` must be present, unique, nonempty GUIDs; channel IDs,
display names, percent encoding, host and path are validated before Agency
starts. The URL tenant is retained and checked if Agency exposes tenant
metadata; the URL alone does not prove the signed-in account's tenant.
The exporter resolves the actual accessible team/channel with `ListTeams`
and `ListChannels`. A stale name in the URL does not override the actual
channel name or metadata.

Alternatively, use the existing explicit-ID mode:

```powershell
pwsh -NoProfile -File .\.github\skills\teams-export\scripts\Export-TeamsChannel.ps1 `
    -TeamsChannelId '19:your-channel-id@thread.tacv2' `
    -TeamId '11111111-2222-3333-4444-555555555555' `
    -StartTime '2026-09-01' -EndTime '2026-09-24' -TimeZone 'UTC'
```

Replace the illustrative IDs with real ones. `-TeamId` is optional in ID mode;
without it, accessible teams are searched. Do not combine ID parameters with
`-ChannelUrl`.

### Agent input and result files

For agent invocation, resolve the absolute script path from the actual
`SKILL.md` location (never assume the repository is the current directory).
Serialize user values into a UTF-8 JSON data file, not interpolated shell
source. Example data:

```json
{
  "ChannelUrl": "https://teams.microsoft.com/l/channel/19%3Aexample%40thread.tacv2/Example?groupId=11111111-2222-3333-4444-555555555555&tenantId=aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee",
  "StartTime": "2026-09-01",
  "EndTime": "2026-09-24",
  "OutputDir": "C:\\exports\\teams-export"
}
```

The only allowed keys are `ChannelUrl`, `StartTime`, `EndTime`, `OutputDir`
(required nonempty strings), and optional nonempty string `TimeZone`.
`OutputDir` must be fully qualified; the agent defaults it to the caller's
working directory plus `teams-export`. Omit `TimeZone` for machine-local time.
Preserve the supplied date/time strings exactly and explain the exclusive end.

Use fresh absolute paths named `teams-export-run-<GUID>.input.json` and
`teams-export-run-<GUID>.result.json`, preferably in the OS temporary directory
where host policy allows it. Write the input file, but **do not create the
result file** before invoking:

```powershell
pwsh -NoProfile -File $absoluteScriptPath `
    -InputPath $absoluteInputPath -SummaryPath $absoluteSummaryPath
$exitCode = $LASTEXITCODE
```

`SummaryPath` is claimed exclusively and refuses an existing file. It reports
`in_progress`, then `complete`, `incomplete` or `failed`, using only these
metadata fields: `status`, `phase`, `outputPath` (absolute Markdown path),
`manifestPath`, `dataDirectory`, `counts`, `timeZone`, `startTimeInclusive`,
`endTimeExclusive`, `diagnosticsPath`, and sanitized `error`. Read this small
result once the process finishes: **exit code 0 and `status: "complete"` are
both required**.
Binding/pre-start errors may not create a result; report that failure
explicitly. Never infer success from existing files. Use `SummaryPath` for
the result without hiding console progress.
`InputPath` and `SummaryPath` are optional for manual URL/ID parameter calls;
the standalone examples above continue to work without them.

### Visible progress

The script emits timestamped operation/progress messages, counters, retries
and terminal errors: INFO/ERROR use `Write-Host`, while WARN uses the warning
stream. Both remain visible independently of Copilot UI support.
Run it in a foreground visible terminal/canvas if supported,
otherwise a streaming terminal. If logging console output, tee it to the
terminal, rather than redirecting everything or silently running in the
background. Do not detach unless explicitly requested. If the host cannot
display streaming output, disclose that limitation and provide the live
readable log and result/status paths instead of claiming progress is visible.

Agents must not repeatedly ingest progress/full logs or any exported message
bodies. Report only the final small summary and absolute artifact paths/counts.
On failure, use the sanitized phase and diagnostics path, requesting bounded
metadata-only diagnostics if necessary. An explicit later request to analyze
content is a separate task.

## Time selection

- `StartTime` is **inclusive** and `EndTime` is **exclusive**, based on root
  post **creation** time, not last activity.
- Date-only (`2026-09-01`) and offset-free ISO timestamps
  (`2026-09-01T09:30:00`) use `-TimeZone`, defaulting to
  `[TimeZoneInfo]::Local.Id`. Use `-TimeZone 'China Standard Time'` or another
  installed timezone ID to override it.
- Timestamps with `Z` or an explicit offset are absolute instants. For example,
  `2026-09-01T00:00:00+08:00` identifies the same instant regardless of
  `-TimeZone`. The selected timezone still controls display and filename dates.
- Ambiguous or nonexistent local times at a DST transition fail explicitly:
  supply an explicit offset instead.

All channel root pages are scanned because pages can be activity-ordered.
An old post with a recent reply is **not** selected unless the root's creation
time is in range. Selected roots and their replies are deduplicated and sorted
chronologically, and every reply page is consumed without a date cutoff.

## Output and completeness

For channel `API Spec Review`, start `2026-09-01` and exclusive end
`2026-09-24`, the output is:

```text
teams-export\
  API Spec Review_2026-09-01_2026-09-23.md
  API Spec Review_2026-09-01_2026-09-23.data\
    manifest.json
    threads\
      1.json
      2.json
```

The filename contains the first and last **covered local dates**, not the
dates of the first/last returned posts. A non-midnight end includes that
calendar date; an exclusive midnight end uses the preceding date. One file
is written even for zero posts. It sits directly in `OutputDir` and contains
the whole requested range, never one file per day.

Windows-invalid filename characters become underscores; trailing spaces/dots
are removed and very long names are capped at 120 UTF-16 code units. The
unmodified actual name remains in the manifest. Existing Markdown files or
matching `.data` sidecars are **never overwritten**, including incomplete
exports. Names that sanitize to the same stem, different channels with the
same name, and different time intervals with the same covered dates therefore
fail safely instead of colliding: choose a different `OutputDir`.

`<stem>.data\manifest.json` is authoritative: only `status: "complete"` means
all advertised message/reply pages were consumed and Markdown rendering
succeeded. It records actual team/channel metadata, parsed URL metadata,
timezone, absolute interval boundaries, counts, output filename and errors.
After output is claimed, failures leave `status: "incomplete"` and exit
nonzero; interrupted processes may leave `in_progress`. Invalid input,
inaccessible channels and existing-artifact collisions fail before creating
an export manifest. An existing Markdown file by itself does not prove
completeness.

`<stem>.data\threads` preserves raw returned message fields plus selected-zone
display timestamps. Markdown preserves bodies, code, mentions, links,
attachment references and reactions; unsupported HTML also appears in an
escaped original-HTML fallback. Raw JSON is retained for fields/formatting
the renderer cannot interpret. Linked files, deleted bodies, edit history and
fields not exposed by Agency cannot be recovered. Live enumeration is not
an atomic snapshot.

The exporter owns and stops only the Agency process it starts (including its
children). Its unique OS-temp `teams-export-run-<GUID>.log` is preserved and
reported via `diagnosticsPath`, including on success. Process working files
are cleaned up only on successful export; on failure, proxy logs are retained
and their path is reported. Report log paths rather than loading full logs
into model context. Remove invocation input JSON after completion; retain
result metadata and diagnostics for troubleshooting. Exports/raw sidecars and
logs can contain private data. The repository ignores date-range-named export
artifacts and narrowly named run input/result/log files. Keep them private,
especially when selecting paths outside the repository.

## Transient failures and retries

Each read-tool request has **five total attempts**, shared across transport
failures, HTTP 429/502/503/504 responses and the specifically identified Agency
error `The request was canceled due to the configured HttpClient.Timeout of
... seconds elapsing.` returned with MCP `isError: true`. The loops are not
nested: mixing these failures does not multiply the request budget. Retries
are limited to the four allowlisted read tools, with visible tool/error,
retry number and delay; default waits are 2, 4, 8 and 16 seconds.

A valid HTTP `Retry-After` header (seconds or HTTP date) overrides that wait.
If it requires more than 120 seconds, the exporter stops rather than retrying
earlier than requested. Authentication, permission, invalid-input and other
unrecognized tool errors are not retried. Partial data in an error result is
never accepted as success. Exhaustion preserves the final error details,
including Agency correlation IDs, and fails with the usual incomplete
manifest/nonzero behavior.

Agency's **internal 30-second service timeout** is distinct from this
script's 120-second HTTP timeout. Increasing the latter cannot override the
former, and an internal timeout alone is not evidence of throttling. Retries
can recover a transient failure but cannot repair an unavailable backend.
If `ListTeams`/`ListChannels` fails before output is claimed, rerunning the
same command is safe; no export artifacts were created by that attempt.
Existing artifacts from another attempt still trigger overwrite protection.

## Offline tests

No Agency process, network access or real Teams content is used:

```powershell
pwsh -NoProfile -File .\.github\skills\teams-export\tests\Test-TeamsExport.ps1
pwsh -NoProfile -File .\.github\skills\teams-export\tests\Test-TeamsRetry.ps1
pwsh -NoProfile -File .\.github\skills\teams-export\tests\Test-TeamsSkill.ps1
python -m unittest discover -s .\.github\skills\teams-export\tests -p test_teams_export_markdown.py
```

Tests generate synthetic messages in temporary directories and clean them up.
