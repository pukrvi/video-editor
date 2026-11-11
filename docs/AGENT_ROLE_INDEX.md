# Agent roles and handoffs

Choose actual concurrency from available slots; queue roles instead of spawning idle agents. Build workers use the user-selected model/effort. Record explicit reviewer-effort overrides in the trip run index. Fresh independent reviewers receive artifact, brief and evidence limits, not controller targets.

| Role | Inputs | Required output | Boundary |
|---|---|---|---|
| media_intake | New media inventory, hashes, capture context, duplicate/original matching; screen recording vs shared album | catalogue delta + source-quality evidence | Wait for stable completed downloads; preserve originals |
| footage_story | Catalogue, user testimony, inspected complete-action candidates | ranked source windows + short/long story map | Current brief and verified trip facts |
| transcription | New speech sources; local bilingual models and identity cache | word/segment transcripts + uncertainty flags | Listen to consequential claims; no ASR factual authority |
| theme_motion | User theme artwork, safe-area descriptors, designed motion rules | indexed assets + motion recipes + contact sheets | Exclude unrelated personal library; original art unchanged |
| photo_layers | Reviewed photographs, explicit crop/focus/mask and layer positions | RGBA layers + source-to-crop mapping + render samples | Protect faces/gestures; preserve EXIF orientation; no generated faces |
| audio | Source narration, optional music/SFX, voiceover timeline | selected speech mix + timing/level tests | Protect speech and use attributable source sound |
| voiceover_editor | Assembled story and explicit factual gaps | short recording scripts mapped to exact beats | User records; no invented experience, pending takes explicit |
| motion_reviewer | Rendered entrance/hold/exit/transition/photo evidence with exact hashes | independent motion critique + failure cases | Review actual outputs; no passed claim from tests alone |
| audio_facts_reviewer | Final mix, transcripts, testimony and fact provenance | speech/music checks + factual mismatch report | Record listening coverage and use the local fact ledger |
| director | Exact short/long movie, current brief, user feedback, schema template | candid independent scored review for each exact movie | No inherited controller context/target; never inflate score; user approval distinct |
| integration_reviewer | Changed code and actual eval outputs | independent regression/risk review | No commit until requested; no protected-source mutation |

## Run registry

Before dispatch, record role, model, effort, exact owned paths, dependencies, output paths and status in a local AGENT_RUN_INDEX.json. On handoff, save artifact identity and what remains unverified. Reuse completed outputs by identity, not stale filenames; when users rename sources reconcile hashes. Keep private paths/media and run-specific state outside the reusable repository.

## Integration order

1. While new media downloads, finish independent theme/audio/photo capabilities and their bounded tests.
2. Once source files are stable, index only additions/changes and identify higher-quality duplicates.
3. Build short and long versions from shared source decisions, with separate timing/narration recipes.
4. Review actual output independently for motion, sound/facts and direction, using the current run effort override.
5. Correct findings, re-render only affected versions and bind new review evidence to new movie hashes. Final Cut follows its separate export gate.
