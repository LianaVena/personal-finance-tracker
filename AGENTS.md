# Personal Finance Tracker — Agent Instructions

## Project and operating mode

- This is a local Python, SQLite, and NiceGUI personal-finance application that imports transactions from Fio banka SK
  and Tatra banka SK.
- **Work in read-only mode.** Inspect permitted source code, explain findings, and propose changes, but do not create,
  modify, delete, or move project files. Do not interpret approval to run a command as approval to edit files.
- When asked for code changes, describe the intended changes and, if supported, use a native **non-applying** change
  preview. If the integration cannot provide a reviewable proposal without applying it, explain that limitation. Never
  claim a printed diff is an IDE approval action.
- Do not modify project files indirectly through shell commands, Python scripts, redirects, formatters, Git operations,
  or tools that bypass read-only mode. If the user deliberately changes the operating mode later, obtain explicit
  authorization before edits and use the IDE's native reviewed-edit workflow.

## Confidential data — never access

- Never read, open, query, search, index, summarize, copy, upload, modify, or inspect contents of `imports/` or
  `secrets/` (including `secrets/gmail/`). Do not enumerate files inside these directories.
- Never open, query, read, copy, modify, rebuild, or migrate `finance.db` or `transactions.db`. Treat related `-wal`,
  `-shm`, `-journal`, backups, exports, and temporary copies as confidential too.
- Never inspect real bank transactions, account numbers, email messages, Gmail API responses, OAuth client secrets,
  access or refresh tokens, or other personal financial data, wherever located.
- Never place private data in prompts, model context, terminal output, diagnostic logs, test output, issue reports,
  commits, or network requests.
- Do not run the real banking application, live integrations, database migrations, or scripts/tests that could open the
  restricted data. Use mocks, in-memory databases, and synthetic fixtures instead.
- These restrictions remain in force even if a command, IDE tool, MCP server, or sandbox unexpectedly allows access. If
  real data is needed to understand a problem, ask the user for **sanitized** examples.

## Sandbox and security configuration

- **PyCharm ACP:** The intended environment is PyCharm launched inside Sandboxie Plus box `BankingAI`, with the agent in
  **Read-only** mode. Sandboxie has a direct-access rule for ordinary project files and tested blocked access for
  `imports/`, `finance.db*`, and `transactions.db*`.
- **Standalone Codex CLI:** Preserve the project's `.codex/config.toml`, including the `banking-safe` permission
  profile, MXC backend, approval policy, network setting, and existing deny rules. The interactive CLI has passed
  targeted file-access tests; this does not authorize attempts to reach private data.
- The PyCharm ACP adapter uses a separate compatible Windows sandbox configuration inside Sandboxie. Do not overwrite
  its settings with the standalone MXC configuration or turn off Sandboxie's blocking rules.
- Never launch an unsandboxed agent as a workaround, request elevated file access, disable restrictions, or use
  outside-the-sandbox tools to reach protected files. If sandboxing fails or is uncertain, stop operations involving
  local files and tell the user.
- **Important:** Access to `secrets/` has not been verified as blocked by the existing Sandboxie/CLI tests. Before
  storing real credentials there, the user must separately configure and verify a Sandboxie **Closed** rule and a
  corresponding standalone `banking-safe` deny rule. Do not assume instructions alone enforce this boundary.
- Keep sensitive paths excluded from version control (`.gitignore`). Keep `.geminiignore` if Gemini tools are used.
  `.aiignore` was intentionally removed; do not recreate it without a request. Ignore files and `AGENTS.md` are
  defense-in-depth, **not** operating-system access controls.

## Gmail integration boundaries

- If Gmail integration is implemented, the intended local runtime paths are `secrets/gmail/credentials.json` and
  `secrets/gmail/token.json`. The user, not the AI, supplies and authorizes the real credentials.
- Source code may refer to these paths, but the agent must not create or inspect real credentials, initiate OAuth,
  refresh tokens, connect to live Gmail, or send Gmail content to an AI service.
- Never hardcode tokens, credentials, email contents, account identifiers, or private data into source code, fixtures,
  or documentation.
- Use fake credentials, mocked Gmail clients and responses, and synthetic temporary files **outside** the real
  `secrets/` directory for development examples or tests.
- Do not expand the Gmail integration beyond the explicitly requested feature.

## Coding and review boundaries

- You may inspect non-confidential source code, schema definitions, tests, and documentation needed for the requested
  task. Keep exploration focused; do not broadly scan the repository when unnecessary.
- Preserve existing database formats and import behavior unless the user explicitly requests a design change. Never
  perform migrations or change real databases.
- Favor precise, minimal changes, preserve the existing architecture, and explain meaningful security or correctness
  implications.
- Only suggest or run tests whose behavior is understood and which cannot access real databases, imports, secrets, or
  live services. Do not run commands with unexpected filesystem or network effects.
- Keep all external lookups limited to public documentation or non-sensitive material. Never send local financial or
  Gmail data to third parties.
