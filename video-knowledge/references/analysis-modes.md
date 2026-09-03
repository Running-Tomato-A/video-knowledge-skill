# Analysis Modes

All modes share the evidence protocol. The selected mode changes emphasis and the user's completion condition, not the underlying facts.

## Intent routing

| User outcome | Primary mode |
|---|---|
| “Help me understand, organize, remember, or connect this” | Absorb |
| “Is this true, credible, or worth adopting?” | Judge |
| “How does this change or help my project?” | Apply |

If the request is ambiguous, ask the single A/B/C question in `SKILL.md`. Do not ask the user to choose a mode when natural language already establishes the outcome.

## Internal analysis brief

Before acquiring or judging the source, translate a sufficiently detailed natural-language request into a compact internal brief. This is an analysis control, not a second user prompt and not a separate deliverable.

Capture only what is needed to complete the user's intended result:

1. **Primary mode and outcome**: what understanding, belief decision, or project decision should become possible.
2. **User-provided hypotheses or doubts**: rewrite them as neutral propositions to test, not conclusions to confirm.
3. **Questions to resolve**: normally three to seven non-overlapping questions that jointly answer the outcome.
4. **Evidence standard**: choose source hierarchy and verification depth proportional to the domain and consequence. For example, health claims may require systematic reviews, human studies, and authoritative medical guidance; historical anecdotes may require first-person or archival sources.
5. **Boundaries**: what not to infer, personalize, imitate, or expand into without further authority.
6. **Completion condition**: what the user should be able to understand, decide, or do when the report is finished.

Preserve the user's altitude and wording where useful. Do not invent adjacent goals, turn curiosity into a project action, or make the brief longer merely because the user supplied many details. When several questions are really one evidence chain, merge them. When the request is already clear, synthesize silently and proceed; do not force confirmation. Record the brief concisely in `analysis-完整底稿.md` so later review can distinguish an analysis failure from a misunderstood request.

## Shared five layers

1. **Faithful reconstruction**: problem, claims, examples, source statements, and relevant visuals.
2. **Structural reconstruction**: claim–evidence–assumption–reasoning–conclusion.
3. **Critical judgment**: reliability, gaps, boundaries, and failure conditions.
4. **Knowledge integration**: supplement, correction, conflict, or new example relative to specified context.
5. **Continued use**: a decision, follow-up question, knowledge link, or project action.

## Standalone comprehension gate

Assume the reader may not have watched the video. Before judging or applying it, make the source understandable as one connected argument.

- Open the concise report with a short narrative that explains what question the creator addresses, how the explanation progresses, and where it ends. Preserve causal and sequential links instead of replacing the main thread with isolated tables or categories.
- Use tables to summarize after the narrative is clear; do not make the reader reconstruct the video's thesis by joining rows from several sections.
- Define source-specific labels, stages, numbers, ratios, and shorthand at first mention. Never write a bare ratio such as `50/40/10`; state what each number represents and which stage it belongs to.
- Translate unfamiliar English terms into the user's language on first use. Retain the original term in parentheses only when it helps source tracing; do not require the reader to know marketing or technical jargon.
- A polished layout does not count as successful reconstruction if a reader who skipped the video still has only a fragmented or partial understanding.

## Absorb mode

### Completion condition

The user can understand and revisit the content without rewatching the entire video, and can see how it relates to specified prior knowledge.

### Emphasis

- Faithful reconstruction: high
- Structural reconstruction: high
- Critical judgment: medium
- Knowledge integration: high
- Continued use: medium

### Concise report

1. What problem the video addresses and its one-paragraph conclusion.
2. Reconstructed argument or method.
3. Key evidence and examples with timestamps.
4. Reliable parts, gaps, and boundaries.
5. Connection to the user-specified knowledge or project.
6. User judgment area: agree, disagree, or pending—left for the user unless already stated.

Optional continuation: offer to connect the result to one specified knowledge-base note.

## Judge mode

### Completion condition

The user can choose to accept, reject, or continue verifying the important claims, and understands what evidence would change the conclusion.

### Emphasis

- Faithful reconstruction: high
- Structural reconstruction: medium
- Critical judgment: highest
- Knowledge integration: medium
- Continued use: high

### Concise report

1. Verdict stated with calibrated language, not a forced true/false label.
2. Claim matrix: each important claim, internal evidence, external evidence, and status.
3. Strongly supported parts.
4. Partially supported or self-reported parts.
5. Unverified or conflicted parts.
6. Counting and definition boundaries that could inflate the claim.
7. What new evidence would change the judgment.
8. How the user can safely understand, adopt, or repeat the claim.

For a person or story, judge individual claims rather than assigning one truth score to the whole person. For trending topics, detect same-source rewrites before calling evidence independent.

Optional continuation: when such a claim exists, ask whether to verify the single unresolved claim that would most materially change the verdict. Do not replace this with a generic “any other questions?” prompt.

## Apply mode

### Completion condition

The user can make a concrete project decision or perform one bounded next action without copying the creator's surface form.

### Emphasis

- Faithful reconstruction: high
- Structural reconstruction: medium
- Critical judgment: high
- Knowledge integration: highest
- Continued use: highest

### Concise report

1. The user's target outcome and the relevant video conclusion.
2. Transferable mechanism—not wording, personality, or branding.
3. Conditions required for transfer.
4. Conflicts, risks, and parts that should not be copied.
5. How the source supplements, corrects, or conflicts with the named project.
6. One minimum action or project modification.

When the user has not provided project context, complete the source analysis first and offer one optional connection step. Separate a generally transferable mechanism from a personalized action. Do not assume the user already has a certain number of posts, customers, metrics, products, or a stable account; do not prescribe project-specific ratios, thresholds, or schedules without a stated baseline. Instead, name the minimum missing context needed to design that action. Do not scan an entire workspace by default.

Label a source–project conflict only after the source's stance is resolved. A proposition the creator quotes, criticizes, rejects, or poses hypothetically is not the creator's position and cannot be used as a conflict merely because its words appear in the transcript.

Optional continuation: offer to turn the conclusion into one minimum project action or bounded file change.

## Mixed requests

- Absorb + Judge: use Judge if the final outcome is belief or adoption; keep enough structure to understand the source.
- Absorb + Apply: use Apply; the shared evidence layer provides the necessary understanding.
- Judge + Apply: use Apply with targeted claim verification before recommending transfer.
- Three modes requested without priority: ask which result matters most rather than generating three complete reports.

## Output discipline

- The concise report should foreground the selected mode, not mechanically fill every possible heading.
- Allocate attention by impact on the user's primary question. Put peripheral but interesting claims in the evidence document or omit them unless they materially change the result.
- Put full timestamps, frames, source comparison, and processing caveats in the evidence document.
- End with the result the user asked for, not generic advice or a long list of possible next steps.

## Continued discussion

The initial report is a durable starting point, not the end of the relationship with the source.

- **Clarify**: explain a claim, example, term, or reasoning step from the existing artifacts.
- **Challenge**: revisit a disputed statement, timestamp, frame, source, or inference and revise when evidence changes.
- **Expand**: bring in external knowledge while clearly separating it from the video's content.
- **Connect**: compare the video with another source, prior note, or project without rewriting the original report unless requested.

Use source-grounded language such as “the video states,” “external evidence supports,” and “my inference is.” If the user wants casual discussion, respond conversationally while preserving those boundaries. Do not rerun the entire pipeline unless the source changed or required evidence is missing.
