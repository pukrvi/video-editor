# Reusable technical lessons

Use the [five gates](AGENTS.md) and keep exact trip evidence in its local workspace. When a failure is fixed, retain the failing input, the scoped correction, the verified result and any remaining limits.

## Sources and editorial evidence

- Catalogue named albums incrementally. Preserve stable source IDs, original paths, exact hashes, exclusions and provenance. A filename clock, EXIF, UTC container time and GPS may disagree. Tie a nearby video to a photo’s location through time and visible context. Keep exact coordinates and personal records local.
- Use stream bounds rather than container length to select picture and audio. Preserve complete actions and inspect endpoints. A short sample or search hit helps locate footage. Screen the full intended windows for privacy and review the final composite.
- Cache by source identity, selected range, frame count and processing settings. Reuse a derivative only after checking that those match and that its contents decode. Preserve originals and earlier versions. Stage new movies before replacing a playable candidate. Guard writable outputs against symlinks, hardlinks and aliases to selected media, music, fonts or art.
- EXIF-orient and crop full-resolution photos, then resample once. Keep nested source paths unique when building SDR copies. Tone-map PQ or HLG pixels and verify output primaries, transfer, geometry, frame count, rate and audio preservation. Media container extensions alone do not establish codec or color.
- For a bounded revision, locate the old shot using its exact frame interval. Save a new recipe. Compare unchanged prepared inputs when practical and inspect the changed cut’s entry and exit. Retain matching source-window fingerprints only.

## Speech, picture and mix

- The local multilingual index and ASR retain original language, content hashes, warnings and source-relative timing. Link transcripts only when source hashes match. Keep raw automatic recognition and alternate or corrected candidates. Near-silence can hallucinate words; flags for silence, repeats, language errors and invalid times require bounded review. Chunked recognition and DTW need separate evaluation. The tested Whisper large-v3 DTW build required flash attention disabled.
- Preserve the dry file and exact chosen take range. Map its source samples to the output clock and record manual word-clock corrections. Check genuine adlibs, consonants at trim boundaries, names, punctuation and spoken units by listening. Keep picture ranges independent of voice trimming. Use exact-length silence for intentionally muted blocks.
- Build ASS and SRT from the same cue windows. Fit at the target resolution and inspect the actual FFmpeg/libass font selection, weight and native shaping. A measurement library may succeed with a font that libass silently substitutes. Check cues on moving footage and protect graphic and caption space at entry, hold and exit.
- Measure the isolated processed music bed across both speech roles and check short-window levels, transitions and tail fade. Track target LUFS, attenuation in dB, stem RMS in dBFS and encoded true peak in dBTP separately. Verify the final AAC and record listening coverage. Keep the track’s source, credits and license evidence with the edit.
- Put prepared picture, captions and animated overlays on the same integer output-frame clock. A concat boundary can round by a frame. Check cut and transparent endpoints in the actual movie. Transform attached lettering, leader junctions and photo art with their parent. Animate independent photos from their original prepared sprites.

## Final Cut import recovery

Final Cut Pro 12.4 crashed in `FFXMLImporter(AssetClipImport) addAssetClip:toObject:parentFormatID:` after importing XML that passed its installed DTD. The event existed without a populated project. The working export keeps spine shots as `asset-clip`, connects music using `audio`, and connects titles/transitions using `video`. Both connected types changed in the successful fix. Preserve the representation and the prepared media. Animated transparent overlays use ProRes 4444.

Follow the [export policy](docs/FINAL_CUT_EXPORT_POLICY.md). Verify local media references, frame-rational durations and installed DTD separately from app behavior. For app verification open the exact populated project and check picture, connected layers, waveform and playback. If an import fails, inspect the fresh diagnostic report and `asiBacktraces` for the attempted path and timestamp, preserve the failing XML, and retry only after a specific correction. Recheck actual chooser and app state after a UI-control error.

## Review and reuse

Store exact movie identity, request ID, version and actual review status. Technical decode, native-size samples, subjective listening, ASR correctness, the director’s judgment, user approval and Final Cut app verification are distinct evidence. Run unit checks and a short normal-path fixture before promoting an implementation. Mocked ASR checks cover mechanics. Recognition quality needs listened source evidence. Keep private samples, reports, credentials and trip metadata out of repository history.
