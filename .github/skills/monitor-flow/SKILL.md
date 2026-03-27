---
name: monitor-flow
description: Use when the user asks to execute a multi-step task or workflow and wants strict step-by-step execution with immediate failure reporting instead of automatic retries or fixes.
---

# Monitor Flow

## Overview

Execute tasks exactly as instructed, one step at a time. **If any step fails, stop immediately and report — never attempt to fix, retry, or work around the failure.**

## Rules

### 1. Step-by-Step Execution

- Follow the user's instructions in the exact order given.
- Complete each step fully before moving to the next.
- Report progress after each step completes successfully.

### 2. Stop on Failure — No Fixing

When any step fails:

1. **STOP** — do not proceed to the next step.
2. **Report** the failure with full detail:
   - Which step failed
   - The exact command or action that was attempted
   - The complete error output or failure reason
   - Any relevant context (paths, versions, state)
3. **Wait** for the user to decide what to do next.

**Prohibited on failure:**
- Do NOT retry the failed step
- Do NOT modify the command or parameters
- Do NOT attempt an alternative approach
- Do NOT diagnose or suggest fixes
- Do NOT continue to subsequent steps

## Red Flags — You Are Violating This Skill

- "Let me try a different approach..."
- "I'll fix that by..."
- "That failed, but I can work around it..."
- "Retrying with..."
- Continuing to the next step after a failure

**If you catch yourself doing any of the above: STOP. Report the original failure to the user.**
