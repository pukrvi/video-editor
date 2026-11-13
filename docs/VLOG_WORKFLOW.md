# Narrated video commands and recipe

The personal vlog and commercial YouTube workflows share a narration renderer. Use the selected [editing profile](../EDITING_PREFERENCES.md). The [personal vlog example](../examples/vlog_recipe.json) shows how to author source and output timing, voice and picture ranges, captions and an optional quiet music bed. The [commercial starter](../examples/commercial_recipe.json) sets the landscape geometry and neutral captions.

```sh
.venv/bin/python scripts/index_vlog.py build /path/to/album catalog/my_vlog.json
.venv/bin/python scripts/transcribe_local.py --library /path/to/album --workspace /path/to/local/workspace --align
.venv/bin/python scripts/index_vlog.py link-transcripts catalog/my_vlog.json /path/to/local/transcripts.json
.venv/bin/python scripts/index_vlog.py search catalog/my_vlog.json 'camp arrival'
./video-editor personal-vlog render --recipe config/my-vlog/v01/recipe.json
./video-editor personal-vlog qa --recipe config/my-vlog/v01/recipe.json
```

Use a local whisper-cli build and multilingual model, then check consequential phrases against their source audio. Use repeatable `--source PATH` for selected full files, including audio-only takes, or `--window PATH START END` for bounded takes. A window’s word times are relative to the window and its source offset is recorded. Search samples guide discovery. Source hashes link the index, original and transcript.

A block aligns one selected voice range and word clock with independently timed picture ranges. The personal starter uses `captions.preset: avenir_highlight` for short bilingual phrases. `caption_phrase_sizes` can mark editorial boundaries on a block. The commercial starter uses the neutral `legacy` treatment. Check both ASS and SRT and verify the actual subtitle faces. System or locally supplied fonts stay outside Git.

Use `music_bed.mix_policy: quiet_bed` for a quiet bed when the brief calls for it. A block with `music_silent: true` overrides that bed to zero with ramps outside the protected window; its selected source audio remains. For an ambience-only moment, use an unmuted `speech_free: true` block, no speech words, and `audio_role: natural_sound`. This override supports quiet_bed and speech_free, and rejects legacy_duck. Author any offset or cue handoff against the output clock. Set its negative `speech_attenuation_db` separately from the track target level. Older recipes retain the `speech_free` default or explicit `legacy_duck` behavior. Inspect the measured processed stem and final mix.

The [motion recipe reference](VLOG_MOTION_SYSTEM.md) describes authored title, photo and contour layers. Attach art in photo-local coordinates to follow the card. Use composition-level art for fixed canvas accents. Inspect both types at render size.

The output folder contains the movie, ASS, SRT, mapped words, offline player and saved reconstruction inputs. Run [independent review](DIRECTOR_WORKFLOW.md) on the exact rendered movie. After the score and confirmation required by the [Final Cut policy](FINAL_CUT_EXPORT_POLICY.md), `export-finalcut` uses the saved shots, baked picture compositions and available audio layers. The export checks describe the editable clips and reference the caption sidecars.

## First-cut editorial checks

New `personal-vlog init` recipes set `editorial_required: true`. Before rendering, each picture supplies `moment` (stable story/action identity), `subjects` (visible cues), `purpose`, and `end_reason`. Each block supplies `selection_evidence` (which alternatives were inspected and why the chosen originals won) and `picture_cues`: `{ "at": 1.2, "subject": "stream" }`, where `at` is block-relative output seconds. When a photo composition covers a cue, give the composition `subjects` for everything visible in the final composite, including exposed base footage. An empty cue list means the speech contains no concrete picture cues; it is an editorial judgment, not automatic transcription analysis.

The normal renderer rejects missing decisions, cue/subject timing mismatches, repeated source windows or nonadjacent moments without `repeat_reason`, and B-roll holds over six seconds without `hold_reason`. Six seconds is a review trigger, not a duration cap; native dialogue is exempt. Adjacent nonoverlapping source windows remain valid. Recompute the cue map after retiming. `editorial_audit.json` records the actual frame clock for the reviewer. Older recipes remain runnable and are explicitly labeled unverified when they lack this plan.

These checks validate authored metadata, not what a model sees or hears. The reviewer must compare the actual movie with every concrete cue, selected action endpoints, rejected source alternatives, photo compositions and natural-sound windows. Review collages at entry, settled hold and exit, with captions visible. Use the full canvas; interface safety is a constraint on important content, not a reason to leave its lower portion blank.

When learning from a user's Final Cut revision, export a separate XML snapshot and compare it with the prior XML plus both exact movies. Preserve the live project. Track insertions, trims, source offsets, speed maps, reordered speech/captions and audio envelopes. Save personal examples locally; promote only reusable rules and synthetic regression tests. A user edit provides preference evidence, not blanket approval of every incidental crop, orientation or color setting.
