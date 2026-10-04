# Codex Adapter

Use Codex's native subagent mechanism with exactly:

```text
fork_turns: none
model: gpt-6-luna
reasoning_effort: max
```

The prompt contains only the fields from `independent-review-contract.md`, requires the Reviewer to read the repository Skill itself, and forbids recursive delegation and writes.

The parent records the actual subagent dispatch parameters with the returned result; a Reviewer self-report alone does not prove fresh context or the requested model.

Do not use a same-context follow-up, a fork that inherits turns, or a different model/effort as an invisible fallback. If `gpt-6-luna` with `max` is unavailable or the fresh subagent cannot start, return independent review as `incomplete` and tell the user.
