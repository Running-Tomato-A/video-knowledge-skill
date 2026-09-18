# Evidence Protocol

Use this protocol for every mode. The goal is analysis-grade accuracy: no error or attribution mistake that changes the conclusion. Publication-grade verbatim accuracy requires targeted human or source review and is not the default promise.

## 1. Acquire and identify

- Extract a stable source URL or work ID from shared text.
- If the user says the source is already saved, search local downloads and prior outputs by work ID, title, author, and source metadata before using the network.
- Verify that the located video matches author, title, work ID, and duration. Delete or replace nothing merely because a match is uncertain.
- If a platform adapter fails, use one justified fallback at a time. Stop after one evidence-based retry and report the blocker.
- Do not access private, paid, authenticated, or restricted content without explicit authorization.

## 2. Preflight internally

Inspect:

- duration, resolution, audio presence, and language;
- native or burned-in subtitles;
- single speaker, main speaker plus questions, balanced dialogue, or frequent overlap;
- whether visuals carry claims that the transcript cannot recover;
- whether a transcript or frames already exist.

Use a short probe before expensive processing when source quality is uncertain. Do not turn normal preflight into a user questionnaire.

## 3. Transcribe and correct

- Preserve timestamped raw output separately from corrected notes.
- Use title, author, domain terms, and visible captions to improve proper nouns.
- Prioritize corrections that can alter the conclusion: names, products, organizations, dates, numbers, money, rankings, technical terms, negation, and causal verbs.
- Do not silently turn approximate language into exact quotes.
- If the source has multiple speakers, label only high-confidence turns. Use `speaker unknown` or `speaker pending confirmation` instead of guessing.
- Backchannels such as “yes,” “right,” and interruptions need no speaker label unless attribution changes the argument.

### Attribution and stance gate

For every statement that can materially change the conclusion, identify both the **proposition owner** and the source's **stance** toward it. A person voicing a sentence may be endorsing it, quoting someone else, reporting it, rejecting it, posing it hypothetically, or leaving it unresolved.

- Do not infer stance from one ASR segment or one burned-caption frame when the proposition spans adjacent segments. Expand backward through the attribution cue and forward through the response or resolution until the grammatical and argumentative scope is complete.
- Treat reported speech, conditionals, negation, contrast, rhetorical questions, and sarcasm as scope-sensitive. If the complete local context still does not resolve the stance, label it `stance unresolved` and do not use it as the creator's claim.
- For a conclusion-changing statement, preserve the stance in the corrected transcript or claim matrix—for example `creator endorses`, `creator rejects`, `quoted third-party view`, or `hypothetical`—rather than recording only the words spoken.

## 4. Select visual evidence

- Use duration-adaptive sparse frames only for the initial visual survey. They help classify the source; they are not the final evidence quota.
- Classify visuals as **negligible** (static talking head or audio with one unchanged image), **supplementary** (occasional captions or illustrations), or **essential** (screen operations, products, charts, documents, demonstrations, changing slides, or footage used as evidence).
- Do not infer the final frame count from duration alone. A long static talk may need very few frames, while a short interface tutorial or audio track with many changing source images may need substantially more.
- When visuals are supplementary or essential, reopen the retained media after transcript review and extract additional frames at the exact claim, transition, screen state, chart, or document timestamp. For audio with changing still images, retain every distinct image that materially changes the argument rather than sampling an arbitrary fixed number.
- Choose frames because the analysis cites them, not because a fixed interval produced them.
- Prefer frames showing claims, charts, product interfaces, contracts, event names, speaker identity, or subtitle corrections.
- Describe only what is visibly present. A frame of a speaker saying an event happened is evidence of the statement, not visual evidence that the event occurred. Do not name or caption it as event footage unless the event is actually visible.
- A mid-sentence subtitle frame is evidence only for the visible fragment, not for the complete proposition or the creator's stance. Cite the surrounding transcript and, when useful, a consecutive frame sequence.
- Use transcript cues such as “look here” or “as shown” to target additional frames.
- Keep uncited contact sheets and probe frames as temporary artifacts, not formal deliverables.

## 5. Reconstruct before judging

Represent the source as:

```text
question → claims → evidence/examples → assumptions → reasoning → conclusion/advice
```

Separate:

- checkable source facts;
- the creator's claims or opinions;
- the analyst's inference;
- the user's stated judgment.

Never manufacture the user's agreement.

## 6. Verify only what matters

- Browse when a factual claim materially affects the selected goal, when information may have changed, or when precise attribution is needed.
- Prefer primary and authoritative sources. Use secondary sources to locate evidence or add context, not to multiply confidence by repetition.
- Open every page cited in the final documents and verify that the page itself supports the nearby claim. If a page is inaccessible, mark it inaccessible and do not use a search snippet as the sole support.
- For trending stories, compare publication dates and trace whether many articles repeat one original interview.
- Treat AI-generated rewrites, copied press releases, and circular citations as one evidence family.
- Audit ambiguous counting words such as product, user, order, revenue, income, download, and customer before comparing numbers.

For judgment, use these statuses when helpful:

- **Confirmed**: direct primary evidence or multiple genuinely independent strong sources.
- **Supported**: consistent external evidence, but not complete proof.
- **Self-reported**: stated by the subject or creator without independent confirmation.
- **Unverified**: evidence is absent or insufficient.
- **Conflicted**: credible sources or source segments disagree.

“Not found” does not mean “proved false.” State what evidence would change the current assessment.

## 7. Write traceable outputs

`source.md` should record source identity, local path, media properties, and processing method. Keep `analysis_date` separate from `source_date`; do not use an ambiguous `date` field for both.

`transcript.md` should index chapters, important claims, high-confidence speaker turns, and conclusion-changing corrections. Keep raw SRT/TXT separately when available.

`analysis.md` should be the useful decision document, not a transcript rewrite. Aim for a 3–5 minute read unless the user requests otherwise.

`analysis-完整底稿.md` should contain the evidence matrix, timestamps, cited frames, external sources, assumptions, uncertainty, and workflow notes needed for audit or follow-up.

## 8. Failure behavior

- No source, audio, captions, or usable frames: explain the missing evidence and stop.
- Partial transcript: identify the missing span and do not generalize across it.
- Unclear speakers: preserve unknown labels and avoid quote-level attribution.
- External claim cannot be verified: retain it as self-reported or unverified.
- A generated report is fluent but not traceable: treat the run as failed and repair the evidence links before delivery.
- A creator's stance was inferred from an incomplete quotation window: treat every downstream judgment that depends on it as failed, reopen the complete span, and propagate the correction through source, transcript index, concise report, evidence report, and metadata conclusions.
