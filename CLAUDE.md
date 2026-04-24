# Claude working notes for this repo

## Commit rules

- **Do NOT add `Co-Authored-By: Claude …` trailers to commit messages.** All
  commits are authored by the human; AI assistance stays out of git
  metadata. This is a hard rule — no exceptions, no "one-off it's fine"
  reasoning. If a default or hook would normally add the trailer,
  suppress it.
- Do not add "Generated with Claude Code" footers or similar AI-author
  hints either.
- Never force-push to `master` without an explicit human confirmation in
  the same turn.
- Never skip hooks (`--no-verify`) or bypass signing unless the human
  explicitly asks for it that turn.
