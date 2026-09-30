# Correct Dictation

A desktop window for correcting dictated text using a persistent Copilot CLI
connection. App files and tests live here; editing instructions come from the
existing repository [skill](../.github/skills/correct-dictation/SKILL.md).
Clone or copy the repository to another Windows machine, preserving this
directory and the root `.github/skills/correct-dictation` directory. Copying
only this app directory is not sufficient.

## Requirements

- Python with Tkinter (included in the standard Windows Python installer).
- Native GitHub Copilot CLI on PATH, authenticated with `copilot login`.
- Copilot access and an internet connection.

Install the CLI with `winget install GitHub.Copilot` if needed. Use a current
version with ACP support (tested with native CLI 1.0.90-5). No Copilot SDK,
third-party Python packages, or local server is required.

## Run

Double-click [correct_dictation.pyw](correct_dictation.pyw), or run this command
from this directory:

```powershell
python correct_dictation.pyw
```

Paste a transcript into Input and click Start. After the correction finishes,
edit the output directly if needed, then click Copy to copy your edited text
for Ctrl+V. Output editing supports undo and is disabled while text is streaming;
Copy is enabled only after successful completion. Cancel stops a correction; closing the window
cancels an active request and stops the CLI process.

Keep [dictation_client.py](dictation_client.py) alongside the window script.
The app reads the existing repository
[skill](../.github/skills/correct-dictation/SKILL.md) for each correction and
includes its contents in the prompt. There is no separate app copy to maintain;
changes to the repository skill apply to the next correction.

## Browser Bookmark

Run [install-dictation-bookmark.ps1](install-dictation-bookmark.ps1) once on each
Windows machine, from this directory:

```powershell
.\install-dictation-bookmark.ps1
```

It detects Python and registers `dictation-helper://open` for your Windows user
account only. No administrator privileges are required. To choose a specific
Python installation:

```powershell
.\install-dictation-bookmark.ps1 -PythonPath 'C:\path\to\python.exe'
```

In Edge or Chrome's bookmarks manager, create a favorite named **Correct
Dictation** with URL `dictation-helper://open` and place it on the bookmarks bar.
Click it to open the window directly, without an intermediate webpage. The
browser may ask to open an external app; browser or organization policy may
require confirmation every time. Switching to an existing tab alone does not
launch the app.

The registration persists across restarts. Rerun setup after moving this folder
or changing Python installations, including when upgrading from the former
repository-root layout. Your bookmark URL stays the same. The handler opens a
fixed script and never forwards URL content as commands or transcripts.

Preview setup with `-WhatIf`. Remove the registration with
`.\install-dictation-bookmark.ps1 -Uninstall`, then delete the browser favorite.

## Connection And Safety

The app starts one `copilot --acp` process when the window opens and reuses it.
Each correction has a fresh session; earlier transcripts are not included in
later requests. Sessions are closed when supported, or the process is recycled
after 20 corrections to bound retained session resources.

Cancellation keeps the connection when acknowledged. A disconnected or
unresponsive agent is stopped; the next Start reconnects without automatically
resending a failed request. Prompt requests time out after three minutes;
connection and session setup have separate 30-second timeouts. The app does not
override ACP model selection, which may differ from the CLI's one-shot default.

The app requests an empty tool list (`--available-tools=`), explicitly denies
shell and write tools, rejects ACP permission requests, and exposes no client
filesystem or terminal capabilities. Any reported tool call stops the correction.
It never grants `--allow-all-tools`. Sessions use an empty temporary working
directory. Text is sent as JSON through standard input, not evaluated by a shell.
Windows' command-length limit does not apply, but model context limits still do.

Copilot sends transcripts to its AI service and may retain normal CLI session
history. This is not an offline or no-retention tool.

## Tests

Run the offline protocol tests from this directory:

```powershell
python -m unittest discover -s tests -p test_dictation_client.py -v
```
