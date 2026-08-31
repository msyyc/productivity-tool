---
name: teams-send-message
description: Send a Microsoft Teams message to a person by alias, UPN, email, display name, or to the signed-in user through Microsoft's Agency CLI. Use when the user asks to send, post, notify, ping, or message someone in Teams, including completion notifications.
---

# Send a Teams message with Agency

Use the bundled `send-teams-message.ps1` helper. It resolves the recipient with
the Agency Microsoft 365 user MCP server, then sends through the Agency Teams
MCP server.

## Usage

Run from PowerShell:

```powershell
& "<skill-directory>\send-teams-message.ps1" `
  -Recipient "<alias, UPN, email, display name, me, or self>" `
  -Message "<message>"
```

For a rich Teams message:

```powershell
& "<skill-directory>\send-teams-message.ps1" `
  -Recipient "<recipient>" `
  -Message "<p>Completed: <b>task name</b></p>" `
  -ContentType html
```

Optional importance values are `normal`, `high`, and `urgent`. Use `urgent`
only when the user explicitly requests it.

## Rules

1. Preserve the user's intended message. Add a short label only when the user
   asks for a test and provides no message text.
2. Never guess or construct a UPN from a name or alias. Let the helper resolve
   it through Agency.
3. If the helper reports multiple matches, show the candidates and ask the
   user to choose one. Do not send until the recipient is unambiguous.
4. If Agency is missing, give the installation command printed by the helper.
   Never install Agency without explicit user confirmation.
5. Treat sending as an external side effect. Run the helper only after the user
   has asked to send the message.
6. Report success only when the helper returns a Teams message ID.
7. Do not expose Teams user IDs, chat IDs, access tokens, or correlation IDs in
   the response unless needed to diagnose a failure.

## Completion notifications

When asked to notify the user after a long-running task, finish the task and
its validation first, then invoke this helper as the final action. This is
best-effort: a notification cannot be sent if the agent process terminates
before reaching the final action.
