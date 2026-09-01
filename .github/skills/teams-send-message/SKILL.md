---
name: teams-send-message
description: Send a Microsoft Teams message to a person, the signed-in user, or a team channel through Microsoft's Agency CLI. Use when the user asks to send, post, notify, ping, or message someone or a channel in Teams, including completion notifications.
---

# Send a Teams message with Agency

Use the bundled `send-teams-message.ps1` helper. It resolves users with the
Agency Microsoft 365 user MCP server or teams and channels with the Agency
Teams MCP server, then sends through the Teams MCP server.

## Usage

With no target option, the helper sends to the default channel
`TaskDone-YuchaoYan`:

```powershell
& "<skill-directory>\send-teams-message.ps1" `
  -Message "<message>"
```

Use `-ToPerson` to send to the default person, `Yuchao Yan`:

```powershell
& "<skill-directory>\send-teams-message.ps1" `
  -ToPerson `
  -Message "<message>"
```

Override the defaults with `-Recipient`, a Teams `-ChannelLink`, or team and
channel display names:

```powershell
& "<skill-directory>\send-teams-message.ps1" `
  -ChannelLink "<Teams channel URL>" `
  -Message "<message>"
```

The helper calls `ListTeams`, then `ListChannels`, then
`SendMessageToChannel`. It extracts the team and channel IDs from channel
links, then verifies both against the list results. Team and channel names
must match exactly and unambiguously. Never guess or fabricate their IDs.

Optional importance values are `normal`, `high`, and `urgent`. Use `urgent`
only when the user explicitly requests it.

Channel messages also support `-Subject`, `-Mentions`, `-AdaptiveCardJson`,
and `-AttachmentsJson`. Mentions, Adaptive Cards, and attachments use the JSON
formats accepted by Agency. `-AdaptiveCardJson` and `-AttachmentsJson` cannot
be combined.

## Rules

1. Preserve the user's intended message. Add a short label only when the user
   asks for a test and provides no message text.
2. Never guess or construct a UPN from a name or alias. Let the helper resolve
   it through Agency.
3. If the helper reports multiple user, team, or channel matches, show the
   candidates and ask the user to choose one. Do not send until the target is
   unambiguous.
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
