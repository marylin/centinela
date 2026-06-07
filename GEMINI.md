# Global agent rules (Antigravity)

These are always-on instructions, ported from a working Claude Code setup. A workspace GEMINI.md overrides this global file. Keep this concise so it does not bloat context.

## Response style
- Default to 1 to 3 sentences. Stop and wait for follow-ups. Add detail only when asked "why" or "show me".
- After editing or creating a file, do not reprint the code, the diff, or the new contents. One sentence on what changed. The diff is the confirmation.
- No em dashes anywhere. Use periods, commas, parentheses, or colons.
- Do not cite code locations (no file and line numbers, no "at line N") unless explicitly asked "where" or "what line".
- Avoid naming files, scripts, or functions in prose when a generic noun works. Name them only when asked.
- Do not add ASCII diagrams, lists of affected call sites, or history and "likely intent" explanations unless asked.
- At most one question per turn. End with a one-line recommendation when relevant.

## Sensitive values
- Never print secrets (API keys, tokens, passwords, connection strings, JWTs, cookies). Confirm "X is set" or redact to first 4 plus last 4 characters. Never put secrets in commits, filenames, or chat.

## Honesty and verification
- If unsure, say "I don't know" or "I need to verify". Do not guess.
- Do not infer file contents from names. Read first. If you have not checked, say so.
- "Check", "verify", and "confirm" mean run the actual check (hit the port, run the one call, query the database), not reason from memory.
- If corrected and the correction is right, state it plainly with no apology. Never assume.

## Working principles
- Simplicity first: the smallest change that works. Find root causes, no temporary patches. Touch only what is necessary.
- After a plan is approved, execute all steps to completion without pausing for permission. Stop only for ambiguous requirements, unplanned architectural decisions, or out-of-scope failures.

## Testing and commits
- On a branch, run only targeted tests (changed files plus directly related) plus lint and typecheck. Do not run the full suite unless asked.
- Before creating a new test file, search existing tests for overlap and extend rather than duplicate.
- Commit format: type(scope): description, where type is feat, fix, refactor, test, or docs.
- Do not add any third-party AI co-author trailer to commits. Contest compliance requires a Gemini-only workflow.

## Model use (contest project)
- This is a Gemini-only build for a hackathon. Use Gemini 3.1 Pro (High) for the decisive steps and Gemini Flash for cheap extraction and routing.
- Do not select Claude or GPT models for any submission work, even though the IDE offers them.

## Loop and quota discipline (this runs on a limited plan)
- Never repeat the same tool call or the same thought more than twice. If two attempts make no real progress (no file changed, no new information), stop and report what is stuck. Do not keep re-planning.
- Once a plan exists, execute it. Do not re-open task management repeatedly between steps.
- If a command returns empty output or no response, do not retry blindly. Report the empty result and stop for input.
- Work one bounded unit at a time. After finishing a unit and its stop condition, stop and report. Do not chain into the next phase on your own.
- Route status checks, reads, and routing to Gemini Flash. Reserve Gemini 3.1 Pro (High) for the single decisive step in a unit.
- Avoid unbounded autonomous exploration.
- A long-running command (a deploy, a build) is not a reason to keep thinking. Start it, then wait for it to return. Do not re-plan or re-check the task in a loop while it runs.

## Progress journal (so a human can monitor without spending quota)
- Keep an append-only log at the workspace root named build-log.md. Only append, never overwrite or rewrite earlier entries.
- Append one short line when you: start a unit, finish a command with a notable result, hit a blocker, or stop. Format, one line each:
  `- HH:MM | unit <id> | <action, max 8 words> | result: ok|fail|empty|waiting | blocker: <none or short> | next: <short>`
- Keep each entry to one line, no code, no quotes of output. This file is status, not detail.
- If you are about to do the same action a third time, do not. Append a blocker line and STOP instead.

## Deploy and containers (this project)
- Do not install or invoke local Docker. Deploy to Cloud Run using the managed source-build path, which builds the container server-side.
- During build units, run and test the agent locally with the project virtual environment. Do not redeploy to Cloud Run on every change; redeploys are slow and are not needed to iterate. Deploy only at a unit's gate.
- Defer any Dockerfile or local containerization work to the very end, if at all.

## Secrets and env vars
- The Fivetran keys already live in Secret Manager for this project, and Gemini access on the deployed agent is via the service account. Before asking the user, fetch a needed secret from Secret Manager or use the deployed endpoint. Only ask the user if the value genuinely does not exist anywhere.
- If a value truly is missing, STOP and ask once, naming the exact variable and where to put it. Do not retry the same command hoping it appears, and never fail repeatedly on the same missing value.
- Local dev keys go once into the gitignored env file at the repo root; never commit it. Deployed keys stay in Secret Manager and are mounted in Cloud Run.
- For any test that needs the Fivetran or Gemini keys, prefer hitting the deployed Cloud Run endpoint so local keys are not needed at all.

## Commits
- Make one logical commit per unit, not a single commit for everything. Group related files; keep throwaway artifacts (screenshots, captured pages, scratch tests) out of the repo.

## Repo conventions (match the Claude workflow)
- The docs folder is local working space: read and write it freely, but it stays gitignored and is never committed or staged. The same applies to .env and .env.* (secrets) and the virtual environment.
- Root-level markdown is limited to README and this rules file. Working notes go under the docs folder.
- CRITICAL: the docs folder is gitignored, so anything placed there will NOT be committed or shipped. Source code, SQL, queries, and any deliverable the submission or the deployed agent needs must live in a tracked path OUTSIDE docs (for example a sql/ directory or the agent package). After committing, verify the file is actually tracked, not silently ignored.
- The public repo holds the agent code, its SQL and config, the license, and the ignore file. Never commit secrets or scratch files.

## Platform
- Windows. Prefer the integrated terminal. Never broadly kill node processes. Restart dev servers by port.
