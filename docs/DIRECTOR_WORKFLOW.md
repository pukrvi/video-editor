# Independent director review

The editing agent runs this for each draft and revision, including small corrections. The Python renderer prepares the request and the gate checks the report.

1. Render, run technical QA and prepare the player and visual samples. Read the movie’s `director_review_request.json` for its model, effort, hash and run ID.
2. Use one separate GPT-6.1 Sol reviewer at the effort named in the request, with `fork_turns="none"`. The recipe’s `director_review.reasoning_effort` records the current override. Legacy recipes default to medium. Record the model and effort actually used in the local run index and report. Reuse that reviewer for later passes when available.
3. Supply the generated reviewer prompt, current brief (new recipes point to it in `brief_file`), [craft checklist](../REEL_QUALITY_BASELINE.md), exact movie and matching samples. Keep controller acceptance targets out of the reviewer’s material. Ask for candid scores, timestamped findings and actual playback and listening coverage.
4. Save the original assessment locally and complete [the report schema](../templates/director_review_report.json) with the current hash and request ID. Findings require finite, nonnegative `at_seconds`, `severity` P0–P3, `finding`, `recommendation` and `status` of `open`, `resolved` or `optional`. Ask for a schema-corrected companion when needed and preserve the actual assessment.
5. Run `quality_gate.py` on the report. The internal final-quality gate requires above 90/100 and resolved major findings. Consolidate relevant revisions and obtain a fresh assessment after rendering. Honor a requested working cut or stop point and record the actual status. Follow the [Final Cut export policy](FINAL_CUT_EXPORT_POLICY.md) for a later timeline.

A standalone shell run leaves the review pending until the editing agent supplies the independent assessment. If the requested reviewer or effort is unavailable, record that limitation and leave the gate pending. User selection, quality review and export eligibility are separate decisions.
