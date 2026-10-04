# Independent Review Contract

Read this file only after `github-pr-review` classifies a PR as high risk or the user explicitly requests an independent review.

## Parent input

Pass only:

- repository owner and name;
- Pull Request number;
- expected full head SHA;
- linked Issue identifier when already verified;
- matched risk categories;
- instruction to read the trusted base-branch `AGENTS.md` and `github-pr-review` Skill.

Do not pass implementation conversation, the implementation Agent's explanation, suspected findings, or a requested verdict.

## Reviewer duties

- Use `role: independent-reviewer` in a fresh context with no parent history.
- Independently retrieve the Issue, approved Spec, PR metadata, complete diff, relevant full files, code context, comments, and available CI evidence.
- Bind all conclusions to the requested full head SHA.
- Apply the Skill's `Confirmed` / `Uncertain` / `Rejected` verification and finding fields.
- Return Analyze results only. Do not edit files, Commit, Push, comment, Approve, Reject, Merge, modify Issues/PRs, or start another Reviewer.
- If the current PR head differs from the requested SHA, return `stale` and stop forming findings.

## Output

Return:

```text
role: independent-reviewer
repository: owner/name
pull_request: number
reviewed_head_sha: full SHA
status: complete | stale | incomplete
routing: fresh_context, model and reasoning effort actually used
risk_matches: list
findings: confirmed findings in the parent Skill format
evidence_limitations: missing or incomplete evidence
```

`complete` requires a fresh context, matching full SHA, and all mandatory evidence available or explicitly bounded. Missing identifiers, inherited context, tool failure, truncated critical evidence, or inability to verify the head produces `incomplete`, not “未发现需要报告的问题”.

When there are no confirmed findings, `findings` must contain the exact conclusion “未发现需要报告的问题”; an empty field is not a clean result.

## Parent validation

The parent checks repository, PR number, verified Issue, full SHA, risk matches, actual adapter dispatch metadata, status, finding schema, and evidence limitations. It then shows the complete proposed review to the user. Only a later explicit user instruction bound to that draft and SHA can enter the existing `Post` flow.
