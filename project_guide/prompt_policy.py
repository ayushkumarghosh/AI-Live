"""User-supplied adaptive prompting policy, embedded for packaged guide runs."""

ADAPTIVE_GUIDELINES = r"""
# Adaptive prompting for software work

A practical method for guiding a coding assistant through defect investigation, feature design, implementation, and verification. Developed from the Conduit tag-defect exercise and generalized for other projects.

The central rule: **choose the next prompt from the evidence returned by the previous step.** This document is a collection of templates and decision rules, not a script to paste all at once.

## 1. Responsibilities

| Participant | Responsibility |
| --- | --- |
| Operator | Attaches files, approves edits, runs terminal commands, exercises the app, and shares results. |
| Coding assistant | Inspects scoped source files, explains findings, proposes designs, edits approved files, and returns diffs. |
| Reviewer or guide | Evaluates evidence and diffs, identifies gaps, and selects the next prompt or manual check. |

One person can act as both operator and reviewer. Where multiple AI tools are permitted, a separate assistant can help review outputs. Follow the actual project's tool-use requirements.

In the workflow described here, terminal commands and browser testing belong to the operator. Every coding-assistant prompt states that it must not run commands. Ask it to **return the diff**, rather than asking it to execute `git diff`.

## 2. Prepare the environment and working agreement

Read the repository instructions before choosing setup commands. Determine what is already provided: dependencies, database, seed data, running servers, ports, and credentials. In a preconfigured Codespace, verify readiness first; installation and seeding are recovery actions only when evidence calls for them. Avoid resetting data just to repeat a test.

Record the required branch, deliverables, permitted tools, and submission procedure. Keep credentials and API keys out of prompts and shared output.

Use these working preferences in the coding assistant:

- Keep one task for a cohesive piece of work so the investigation and edits remain connected.
- Use Plan mode for investigation, design, and review; Act mode for file changes, including documentation.
- Enable checkpoints where available and inspect edits before continuing.
- Auto-approve only scoped project reads if desired; retain control over edits and command execution.
- Start with one or two relevant files per prompt. Increase the scope only when a tightly related change requires it.
- Select a capable available model. Adjust prompt scope based on demonstrated reliability rather than advertised context-window size.

Plan/Act names describe the Cline workflow used in the exercise. In another tool, explicitly request read-only analysis or scoped editing to establish the same boundary.

## 3. The adaptive loop

1. Identify the next unanswered question that affects a decision.
2. Select the smallest set of files or observations that can answer it.
3. Give one prompt with an objective, evidence, scope, output format, and stopping point.
4. Review the answer for exact source evidence, unsupported assumptions, and contradictions.
5. Correct an incomplete answer before building on it.
6. When the evidence supports a decision, record it and advance.

Do not force every result into another investigation step. If the current evidence is sufficient, move to design or implementation. Conversely, “ready to edit” in an assistant's response does not establish readiness by itself.

### How to choose the next step

| Result received | Next action |
| --- | --- |
| Exact evidence answers the question | Advance to the next unresolved boundary. |
| Plausible claim without supporting source | Ask for the exact symbol or expression in the same file. |
| Guessed path or nonexistent method | Locate the real path manually, then attach the correct file. |
| Contradiction with an earlier state | Resolve the contradiction and explicitly supersede the earlier claim. |
| Unexpected design decision | Return to Plan mode and compare the relevant options. |
| Correct scoped diff | Run the appropriate manual verification. |
| Build or runtime failure | Share the actual error and scope the next investigation to it. |
| Passing build | Continue to behavioral checks; compilation alone does not prove acceptance. |
| Passing acceptance checks | Update documentation and inspect delivery requirements. |

## 4. Context and state

Attach files using the tool's file picker or `+` button. Use `@` mentions only when they work in the environment. Identify each attachment by its repository-relative path inside the prompt, especially when filenames repeat across folders.

Reattach current files before editing when earlier attachments may be stale. Avoid attaching whole directories, generated output, dependencies, or large logs. When sharing a failure, include the command, exit result, and enough surrounding output to explain it.

End substantive investigation steps with a compact state capsule:

```text
STATE_<number>
Confirmed:
- [fact, path, and symbol]

Inference:
- [conclusion and its supporting evidence]

Decisions and constraints:
- ...

Unresolved:
- ...

Next investigation:
- [behavior or boundary to trace; do not guess filenames]
```

The capsule lives in the conversation by default. It does not create a file or guarantee permanent memory. The next prompt names the preceding state and repeats only the facts needed for the next decision.

For work spanning sessions or context compaction, explicitly choose a durable notes file and its location. Keep it short: objective, acceptance criteria, confirmed evidence, decisions, changed files, verification results, and next action. Do not silently add a memory system to a small repository task. Treat `root-causes.md` or a feature design document as a deliverable, not as an automatic dumping ground for chat history.

Use a recovery prompt when continuity is lost:

```text
Resume from the supplied state summary and attached current files.
First reconcile the summary with the actual source. Report discrepancies.
Do not repeat completed work or assume earlier attachments are current.
Do not edit files or run commands yet.
Return the verified current state and the smallest unresolved next step.
```

## 5. Defect workflow

1. Extract symptoms, expected behavior, acceptance conditions, and required deliverables.
2. Reproduce the defect manually and record the initial state.
3. Trace the failing value or operation through relevant boundaries: input, state, request, controller, persistence, response, display.
4. Prove each reported symptom separately. Related symptoms can have different causes.
5. Write the RCA before source changes when required. Explain the original behavior and cite exact files and expressions.
6. Design the smallest compatible correction, including edge cases and verification.
7. Implement one coherent change at a time.
8. Run builds and relevant behavioral checks; add regression tests when appropriate to the project and task.
9. Update the RCA with the implemented resolution and actual verification status.

Example from Conduit: a text field supplied a string, the request path forwarded it, and a spread operation appended individual characters. Separately, the popular-tags endpoint read a table that article creation never updated. The investigation needed evidence for both paths before proposing a complete fix.

## 6. Feature workflow

Feature development uses the same loop, with a requirements and design stage in place of the RCA.

1. Define the user outcome and observable acceptance criteria. Include empty, loading, error, and permission states where relevant.
2. Establish scope and non-goals. Surface consequential product choices before implementing them.
3. Inspect the closest existing feature and its conventions using small file groups.
4. Trace the data and interaction paths the new feature will extend.
5. Decide contracts: inputs, outputs, validation, persistence, access control, and compatibility where applicable.
6. Write a concise design note if the feature requires several decisions or coordinated changes.
7. Break implementation into independently reviewable increments. Each increment should have a specific observable result.
8. Edit, review, and verify each increment before extending it.
9. Exercise the complete user flow and relevant regressions; document delivery and remaining limitations.

For example, a saved-articles feature could proceed through: current article/user contracts, save/unsave behavior and permissions, persistence/API design, one working backend increment, UI integration, then empty/error/reload checks. The next prompt depends on what each step establishes.

Do not copy defect-specific restrictions into every feature task. Some features legitimately need migrations, dependencies, new files, tests, or configuration changes. Require a reason and explicit scope for each.

## 7. Prompt templates

Replace placeholders before sending. Provide only the template appropriate to the current evidence.

### A. Requirements extraction — Plan

Operator: attach the README, issue, or feature brief. Start with one document when possible.

```text
The attached document is <path>.
Our objective is <defect or feature outcome>.

Inspect only the attached document. Do not edit files, run commands,
use the browser, or inspect source code yet.

Extract:
1. Reported/current behavior and desired behavior.
2. Observable acceptance criteria.
3. Constraints, required deliverables, and required sequence.
4. Relevant project locations explicitly named in the document.
5. Questions that materially affect scope or design.

Separate stated requirements from assumptions. Do not guess filenames
or diagnose an implementation you have not inspected.
Return a concise STATE_1 with the smallest next investigation.
```

### B. Focused investigation — Plan

Operator: attach one or two verified current files.

```text
Use STATE_<n>.
Attached files: <exact paths>.
The next question is: <one concrete data-flow or behavior question>.

Inspect only these files. Do not edit, run commands, or use the browser.
Identify the exact symbols and short source expressions that answer
the question. Explain their runtime behavior and distinguish it from
declared types or intended behavior.

State what these files do not establish. Do not infer behavior in
unseen middleware, callers, or configuration.
Return STATE_<n+1> with evidence, inference, unresolved questions,
and the next behavior to investigate. Do not guess filenames.
```

### C. Correct an unsupported finding — Plan

```text
In STATE_<n>, the claim <claim> is not established by the supplied evidence.
Reinspect only <attached path> and answer <specific question>.
Give the exact enclosing symbol and relevant expression.
Explain what that expression does for <concrete input>.
Explicitly correct or retain the earlier claim with a reason.
Do not propose a fix, edit files, or run commands.
```

### D. Record RCA or design — Act

```text
Use the confirmed evidence and decisions in STATE_<n>.
Edit only <documentation path>.

For a defect: record symptoms, expected behavior, the original causal
chain, exact source locations, and unresolved limitations.
For a feature: record outcome, acceptance criteria, chosen contracts,
affected components, non-goals, and the planned increments.

Preserve the document's required structure. Label assumptions.
Record implementation and verification as pending unless performed.
Do not change source code or run commands.
Return the complete diff and identify every changed file.
```

### E. Minimal implementation design — Plan

```text
Use STATE_<n> and the attached current files: <paths>.
Do not edit files or run commands.

Propose the smallest design meeting <acceptance criteria>.
Explain the chosen boundary and why it fits existing project patterns.
Define behavior for <relevant input/error/empty cases>.
Identify exact files, imports, dependency-injection changes, and data
contracts needed. Explain any schema or dependency changes separately.

Return the implementation order, verification plan, remaining decisions,
and whether the evidence is sufficient to begin editing.
```

### F. Scoped implementation — Act

```text
Use the approved design in STATE_<n>.
Edit only these attached current files: <paths>.
Implement this increment: <specific observable result>.

Requirements:
- <exact behavior and edge cases>
- <compatibility and existing conventions>
- <required imports, registration, or integration>
- <mutation/persistence/error-handling contract where relevant>

Preserve unrelated behavior and edits. Do not expand scope to additional
files without explaining why they are necessary and stopping first.
Do not run commands, use the browser, install packages, or commit.

Return the complete diff for each changed file, a short explanation,
and any unresolved concern. Do not claim tests passed.
```

### G. Review a change — Plan

```text
Review the attached current files and supplied diff against STATE_<n>.
Do not edit files or run commands.

Check acceptance behavior, imports and integration, compatibility,
error/empty cases, mutation, and unintended scope changes.
Distinguish definite defects from optional improvements.
For each finding, cite its location, concrete consequence, and evidence.
State what requires execution to verify.
```

### H. Respond to verification failure — Plan, then Act if needed

Operator: supply the exact command, failure output, and relevant file.

```text
The operator ran <command> and observed <exit status/result>.
Relevant output:
<error output>

Use STATE_<n> and inspect only <attached file>.
Explain the failure using the actual output and source.
Identify the smallest correction and whether it affects the agreed design.
Do not edit files or run commands yet.
```

If the cause is unambiguous, such as a missing import, a narrow Act prompt can directly request that correction. Avoid an unnecessary planning round for a proven one-line fix.

### I. Update verification records — Act

```text
The operator reports these completed checks:
<commands, outcomes, manual steps, evidence filenames>

Edit only <documentation path> to record those results and the final
resolution. Replace stale pending statements. Describe original defect
behavior in the past tense and distinguish it from current behavior.
Do not claim additional checks, repair old data, or change source files.
Do not run commands. Return the complete diff.
```

## 8. Manual command and browser handoffs

Each instruction to the operator should contain the execution location, exact command or UI action, expected observation, output to share, and stopping point.

Example:

```text
Open a separate terminal at the repository root; leave dev-server tasks running.
Run: <verified repository build command>
Share the success/failure output. Do not install packages or make fixes yet.
```

Derive commands from the actual repository. A successful build verifies compilation; it does not ensure an already-running backend has loaded the latest output. Confirm watch-mode reload or restart the relevant task before acceptance testing.

For a browser test, give the operator the starting state, exact input, action, expected result, refresh/reload behavior, and screenshot requirements. Preserve the precondition that a newly introduced value is absent before testing. Use a fresh unique value for supplemental checks if earlier tests have already created the original value; still satisfy exact required acceptance data where mandated.

Record observations separately: API payload, API response, persisted state, and visible UI are different evidence. An API-only test that bypasses the form cannot establish frontend input normalization. Old malformed records can remain after a fix for new records; investigate or migrate them only when that is in scope.

## 9. Review and delivery criteria

Before delivery, verify:

- The actual changed files match the agreed scope.
- Necessary imports, module registrations, and callers are included.
- The implementation fits the project's runtime and language target.
- Relevant builds and behavior checks have observable results.
- Documentation distinguishes original causes, implemented behavior, and remaining limitations.
- Screenshots and other artifacts exist at the required location.
- The branch and submission procedure match the repository instructions.

Inspect the actual working tree when possible. Assistant-produced diffs can be incomplete or inaccurate. A `+` prefix in a unified diff is a marker, not an accidental source character. Checkpoint snapshots, generated diff text, and real repository commits are different things.

An ignored screenshot can exist on disk without appearing in Source Control. Check the submission instructions or collection script before concluding it will be included; neither its existence nor its ignored status proves delivery. Avoid force-adding files or changing ignore rules without understanding the workflow.

## 10. Lessons from the exercise

- Stronger models still need evidence boundaries. Confidence and fluent explanations do not prove the code was inspected correctly.
- Exact expressions resolved confusion faster than broad questions about “processing.”
- Asking for the next behavior was more reliable than demanding filenames from a README-only analysis.
- Runtime values must be traced; TypeScript annotations do not parse incoming JSON.
- Compatibility constraints should be included before editing, preventing avoidable configuration changes.
- Missing uniqueness constraints do not automatically justify schema work. Conversely, lookup-before-insert is not a guarantee against concurrent duplicate creation; consider concurrency when the actual requirements demand it.
- One or two files is a useful default, not a rigid rule. Keep closely coupled integration changes together when splitting them creates errors.
- Build success and manual acceptance evidence should reach the coding assistant before it updates verification documentation.
- Documentation order comes from the task: RCA before code for this assessment; design before implementation for features that need it.
- Keep the workflow adaptive. Reuse the structure of successful prompts while replacing their assumptions with current evidence.

## 11. Quick-start message for a new task

```text
We will work incrementally on <objective>.
I will attach the relevant files, run all terminal commands, perform browser
checks, and share results. You will investigate, design, and edit scoped files.

Use Plan mode for analysis and Act mode only for agreed file changes.
Each step should answer one decision-relevant question and stop for review.
Use exact source evidence, label inference, and avoid guessing filenames.
Return a compact numbered state after investigation and complete diffs after
edits. Never claim verification that has not occurred.

Start by reading only the attached <requirements document> and extracting
the outcome, acceptance criteria, constraints, and next investigation.
Do not edit files or run commands yet.
```

"""
