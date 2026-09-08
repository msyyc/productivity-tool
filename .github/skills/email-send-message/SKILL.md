---
name: email-send-message
description: Send an email to the signed-in user's work mailbox or explicit recipients through Microsoft's Agency CLI. Use when the user asks to email, send mail, email themselves, or send an email completion notification.
---

# Send an email with Agency

Use the bundled `send-email-message.ps1` helper with PowerShell 7.1+ and Agency.
It uses Agency's `mail` and `m365-user` MCP servers without manual server
configuration. Both this skill and `teams-send-message` depend on the sibling
`common\agency-mcp.ps1`; retain that folder when copying either skill.

## Usage

By default, send to the signed-in user's work email, resolved by `GetMyDetails`.
`-Message` sets both subject and plain-text body:

```powershell
& "<skill-directory>\send-email-message.ps1" `
  -Message "test 2026-09-08 4:15"
```

If only `-Subject` or only `-Body` is supplied, use that exact text for both.
When supplied explicitly, `-Subject` and `-Body` override `-Message` independently:

```powershell
& "<skill-directory>\send-email-message.ps1" `
  -Subject "Proposal review" `
  -Body "Review the proposal tomorrow."
```

Use `-To` (alias `-Recipient`) for one or more bare email addresses, exact
display names, directory aliases, or `me`/`myself`/`self`. Optional `-Cc` and
`-Bcc` accept the same values:

```powershell
& "<skill-directory>\send-email-message.ps1" `
  -To @("Jane Doe", "colleague@example.com") `
  -Cc @("reviewer@example.com") `
  -Bcc @("me") `
  -Message "The proposal is ready for review."
```

Explicit email addresses are validated and used as given, including external
addresses. Names and aliases are resolved through `GetMultipleUsersDetails`;
only an unambiguous exact match is accepted. Use the resolved `mail` field,
not a guessed address or a UPN fallback.

Use `-WhatIf` to resolve recipients and display the email without sending.
It may contact the identity MCP, but never calls the mail send tool. HTML,
attachments, and mailbox draft creation are not supported.

## Rules

1. An explicit send request authorizes sending without a second approval.
   If the user requests a preview, draft, or approval before sending, show the
   recipients and content and wait. Use `-WhatIf` if resolution is needed.
2. Preserve supplied text. Unless the user explicitly distinguishes subject
   and body, use identical text for both. If no content is supplied, infer it
   from the requested task or completion notification only when clear;
   otherwise ask. The helper requires at least one content parameter.
3. With no recipient specified, use the signed-in account, never a hardcoded
   address. Resolve every To/Cc/Bcc recipient before sending. If resolution is
   ambiguous, incomplete, or has no mailbox, show candidates when available
   and ask the user to clarify. Never guess an address from a name or alias.
4. Use the helper rather than launching a nested `agency copilot` session.
   If Agency is missing, show its installation guidance; never install it
   without explicit approval.
5. Report success only when the helper returns `status: sent` with a message
   ID. Show the recipient and subject concisely; do not expose tokens,
   correlation IDs, or message IDs unless needed to diagnose a failure.
6. Never automatically retry a failed or timed-out send. Delivery may have
   succeeded despite the missing response. Report the failure or uncertainty
   and inspect Sent Items before considering another send.

## Completion notifications

When asked to email after a task, finish the task and its validation first,
then invoke the helper as the final action. Use the same completion text for
subject and body unless the user specifies otherwise. This is best-effort:
no notification is possible if the agent terminates before that final action.
