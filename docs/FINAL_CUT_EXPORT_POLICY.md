# Final Cut export policy

Source: explicit user workflow corrections on 7 November 2026. This replaces the former requirement to create/import a timeline for every early draft.

1. Early cuts produce the versioned movie, review player, caption sidecars where relevant, QA and independent director review. Set `finalcut_export` to false. Record Final Cut as `deferred_by_user`.
2. Preserve the recipe, prepared picture and title media, any saved composites, narration and mix, source ranges, captions and render manifest. The export uses these saved inputs without rerendering the movie.
3. Before creating XML, obtain an independent director assessment of the **exact current movie scoring at least 85/100**. The report and review request must match the current movie hash and run; use the required reviewer profile and complete rubric.
4. After that assessment, obtain **explicit user confirmation for that version's Final Cut export**. A score, a general editing request, a maintenance task or elapsed time is not confirmation. Store the report path and the actual user confirmation with the movie hash in the recipe. Ask only when the qualifying cut is concrete and the user wants the timeline stage.
5. `scripts/finalcut_gate.py` checks eligibility before XML creation. Run `./video-editor WORKFLOW export-finalcut --recipe RECIPE`. Existing recipes can use `scripts/pipeline.py export-finalcut --recipe RECIPE`. A reconstruction without a complete saved media identity needs a fresh render and review before export.
6. The exporter checks local media references, frame-rational timing and the installed Final Cut schema when available. It writes the XML and `finalcut_export_checks.json` with the movie, XML and referenced media hashes, along with the editability of that export. The static checks and actual Final Cut observations have separate records. The interchange keeps primary shots as `asset-clip` and connected layers as explicit `audio` and `video` elements.

The 85 threshold is timeline eligibility, separate from the controller's final-quality gate and user approval of the video. A deliberately shared working first cut may still have unresolved checks and an unpassed quality gate; label it accordingly. A user request to stop is honored regardless of score. Learning/documentation maintenance does not resume editing or timeline work.

## What the timeline exposes

- Prepared shots are separate clips that can be moved and trimmed within their saved media. Crop, grade, speed and effects prepared inside a shot are baked. The saved recipe governs rebuilding those treatments from the sources.
- Reel titles and transitions are connected video clips with baked animation. New narrated renders with graphics, transitions or photo compositions save their composed picture. The exporter connects the composed windows over the clean shots. Each window contains the underlying picture and the baked graphics, so disabling it reveals the clean spine. Older narrated reconstructions with only prepared-shot hashes export the clean shots and report that fallback.
- A narrated cut can export separate normalized narration and processed music clips if the saved PCM stems reproduce the aligned mix within two 24-bit sample steps. Narration may include both native speech and voiceover. A render without matching separate stems uses the reviewed mix as one audio clip.
- The narrated export keeps the ASS and SRT files alongside the project. ASS preserves authored styling and timing. SRT carries plain text and timing. Styled captions appear in the reviewed movie. The XML does not create native captions.

## Record an in-app check

Open the intended library and import the exported XML. Open the populated project and check the canvas, frame rate, duration, linked media, connected layers, picture playback and audio playback. Record any sample points and limits in the observations. If captions are imported separately, check their timing, formatting and editability in the app and record what you observe.

```sh
./video-editor WORKFLOW record-finalcut-verification --recipe RECIPE --evidence LOCAL_JSON
```

The local evidence object must contain `movie_sha256`, `xml_sha256`, `project_name`, `app_version`, `library`, `observations` and a `checks` object. After observing the project, set `populated_project`, `timeline_geometry`, `picture_playback`, `connected_audio` and `audio_playback` in `checks`. Set `connected_video` when the static report lists connected picture layers. All required checks must be true to record verification.

The command checks the observations against the current movie, XML, project and local media from the static report. It saves `finalcut_app_verification.json` for that import. A receipt applies only to the recorded movie and XML hashes and the checked media. Keep the evidence and library local.

A saved app receipt is historical evidence. Its movie, XML and linked-media hashes must still match; `check_finalcut.app_verification_current(recipe)` rechecks them and the review request. Re-export marks prior observations superseded. Export destinations must be files distinct from recipe and review inputs.
