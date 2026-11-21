# Working with Claude (collab mailbox)

The user runs Codex and Claude in separate terminals. Claude plans and reviews. Codex implements. Claude has a small token budget, so keep everything you send it short.

## Mailbox (`.collab/`, gitignored)
- `.collab/to-codex.md`: the latest message from Claude to you. It gets overwritten each time.
- `.collab/to-claude.md`: your reply to Claude. Overwrite it; don't append.
- `.collab/log.md`: append-only history. Append each message you send. Never read it unless asked.

## Headless runs (the usual case)
Claude usually runs you with `codex exec` through a runner script. Your final message is saved to `.collab/to-claude.md` automatically, so don't write that file yourself. Just make your final message follow the reply format below.

## When the user says "check inbox" in an interactive session
1. Read `.collab/to-codex.md` and do the task as written. Respect its scope and its "don't touch" list.
2. Run the tests it lists.
3. Overwrite `.collab/to-claude.md` with this format, max ~150 words:

```
# from: codex | re: <id> | status: done | blocked | question
## Summary
<2-4 bullets: what you did>
## Files changed
<paths only>
## Tests
<exact summary line(s), e.g. "31 passed" / "pass 2 fail 0">
## Open issues / questions
<or "none">
```
4. Append the same block to `.collab/log.md`.
5. Tell the user: "Reply written. Tell Claude to check inbox."

Don't paste file contents or full diffs into the reply. Claude reads `git diff` itself. Don't commit unless the message asks you to.
