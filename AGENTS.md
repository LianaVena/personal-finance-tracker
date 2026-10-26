# Personal Finance Tracker - Agent Instructions

## Restricted files and private data

- Never read, open, search, inspect, summarize, copy, modify, or enumerate file contents inside `imports/` or `secrets/`
  (including `secrets/gmail/`).
- Never read, open, inspect, query, copy, or modify `transactions.db` or `finance.db`.
- Never read or process live Gmail credentials, OAuth client secrets, access tokens, refresh tokens, email messages,
  Gmail API responses, or real account data.
- Never include restricted contents in prompts, context, terminal output, logs, test results, bug reports, or external
  requests.
- Do not run commands, the application, integration tests, or scripts that access restricted project paths, authenticate
  to Gmail, or call the live Gmail API.
- These restrictions apply even when asked to scan the whole project, and even if a tool or command could technically
  access a restricted path.
- If you need examples from restricted data, ask for sanitized examples or create synthetic fixtures instead.

## Gmail integration boundaries

- The real application's Gmail OAuth client credentials and tokens must live **inside the project root** at
  `secrets/gmail/credentials.json` and `secrets/gmail/token.json`, respectively. The user supplies and authorizes them
  manually; an AI agent must not create real credentials or open this directory.
- It is permitted to **write source code** that refers to these paths so the application can authenticate at runtime. It
  is **not** permitted for the agent to use the credentials, initiate OAuth, refresh tokens, or run live Gmail requests.
- Never hardcode credentials, tokens, email messages, or account identifiers into source code, fixtures, configuration,
  or documentation.
- Never send Gmail data to an AI model or external AI service. Keep Gmail API integration local to the Python
  application.
- Unit tests may use fake OAuth responses, mock Gmail clients, and synthetic temporary files located **outside the real
  project `secrets/` directory**. No real network access is needed for these tests.
- Preserve the existing `banking-safe` Codex permission profile, sandbox, network settings, and approval settings. Add
  an explicit **read/write `deny`** for the project `secrets/` directory to the existing active profile in
  `.codex/config.toml`, without replacing the profile or broadening access elsewhere. Keep existing deny rules for
  `imports/`, `transactions.db`, and `finance.db`.
- Ensure `secrets/` is excluded in `.gitignore`, `.aiignore`, and `.geminiignore`; preserve their existing entries. Keep
  `.aiignore` enabled in JetBrains AI Assistant and verify Gemini's ignore-file setting is active when applicable.
- Ignore files and these written instructions are **not** substitutes for actual sandbox filesystem restrictions. Never
  switch to an unrestricted sandbox or elevate permissions to access `secrets/`.
- Do not commit or upload credentials, tokens, backups, temporary copies, or email data. Never print secret values while
  checking exclusions.

## Allowed work

- You may inspect other project source files, excluding all restricted paths and private content above.
- Propose code changes and explain their purpose.
- Obtain explicit approval before modifying files.
- Do not change existing database schemas, perform migrations, or modify or rebuild real transaction databases.
- Limit modifications to the requested feature; do not implement later Gmail search or user-interface steps without
  authorization.

## Code editing and review

- For source-code changes, use the agent's native structured file-editing tool (prefer `apply_patch`) so JetBrains Air
  can handle the edit as a file-change operation, not as printed text or a shell command.
- Do not first print a proposed unified diff in chat or ask me to type "approve" in chat. Submit the proposed edit
  through the native tool, allowing the host to present its approval interface if supported.
- Use Read-only / Ask permission mode when I require approval before edits. Never bypass the host's permission prompt or
  treat command approval as approval to modify files.
- When the host offers a native proposed-change diff, let me inspect it and approve or reject it there. Never replace
  that UI with a raw patch, Markdown code block, or full-file replacement in chat.
- Never modify source files using Python scripts, shell commands, redirections, or other indirect file-writing methods.
- If the integration cannot submit an edit for native pre-apply review, stop and explain that limitation. Do not claim a
  printed diff is approvable, and do not silently switch to editing without approval.
- After an approved edit, use Air's Review / Show Diff feature to verify the actual changes. Run tests only after
  changes are applied, and only when they cannot touch restricted paths or live services.
