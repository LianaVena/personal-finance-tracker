# Personal Finance Tracker - Agent Instructions

## Restricted files

- Never read, open, search, inspect, summarize, or modify anything inside `imports/`.
- Never read, open, inspect, query, or modify `banking.db`.
- Do not include their contents in prompts, logs, tool output, or external requests.
- Do not run scripts or tests that access these paths.
- These restrictions apply even when I ask you to search the entire project.
- If a task requires restricted data, ask me to provide sanitized examples instead.

## Allowed work

- You may inspect all other project source files.
- Propose code changes and explain their purpose.
- Obtain explicit approval before modifying files.
- Do not change the existing database schema or perform migrations.

## Code editing and review

- For source-code changes, use the agent's native structured file-editing
  tool (prefer apply_patch) so JetBrains Air can handle the edit as a
  file-change operation, not as printed text or a shell command.
- Do not first print a proposed unified diff in chat or ask me to type
  "approve" in chat. Submit the proposed edit through the native tool,
  allowing the host to present its approval interface if supported.
- Use Read-only / Ask permission mode when I require approval before edits.
  Never bypass the host's permission prompt or treat command approval as
  approval to modify files.
- When the host offers a native proposed-change diff, let me inspect it
  and approve or reject it there. Never replace that UI with a raw patch,
  Markdown code block, or full-file replacement in chat.
- Never modify source files using Python scripts, shell commands,
  redirections, or other indirect file-writing methods.
- If the integration cannot submit an edit for native pre-apply review,
  stop and explain that limitation. Do not claim a printed diff is
  approvable, and do not silently switch to editing without approval.
- After an approved edit, use Air's Review / Show Diff feature to verify
  the actual changes. Run tests only after changes are applied.
