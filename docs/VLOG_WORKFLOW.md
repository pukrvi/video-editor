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

Use `music_bed.mix_policy: quiet_bed` for a continuous quiet bed when the brief calls for it. Author any offset or cue handoff against the output clock. Set its negative `speech_attenuation_db` separately from the track target level. Older recipes retain the `speech_free` default or explicit `legacy_duck` behavior. Inspect the measured processed stem and final mix.

The [motion recipe reference](VLOG_MOTION_SYSTEM.md) describes authored title, photo and contour layers. Attach art in photo-local coordinates to follow the card. Use composition-level art for fixed canvas accents. Inspect both types at render size.

The output folder contains the movie, ASS, SRT, mapped words, offline player and saved reconstruction inputs. Run [independent review](DIRECTOR_WORKFLOW.md) on the exact rendered movie. Use the [Final Cut policy](FINAL_CUT_EXPORT_POLICY.md) for any later timeline.
