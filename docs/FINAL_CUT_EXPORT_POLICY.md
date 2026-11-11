# Final Cut export policy

Source: explicit user workflow corrections on 7 November 2026. This replaces the former requirement to create/import a timeline for every early draft.

1. Early cuts produce the versioned movie, review player, caption sidecars where relevant, QA and independent director review. Set `finalcut_export` to false. Record Final Cut as `deferred_by_user`.
2. Preserve the recipe, prepared picture/title media, narration or mix, source ranges, captions and render manifest. Later XML export should use those saved inputs without rerendering the movie.
3. Before creating XML, obtain an independent director assessment of the **exact current movie scoring at least 85/100**. The report and review request must match the current movie hash and run; use the required reviewer profile and complete rubric.
4. After that assessment, obtain **explicit user confirmation for that version's Final Cut export**. A score, a general editing request, a maintenance task or elapsed time is not confirmation. Store the report path and the actual user confirmation with the movie hash in the recipe. Ask only when the qualifying cut is concrete and the user wants the timeline stage.
5. `scripts/finalcut_gate.py` checks eligibility before XML creation. Run `./video-editor WORKFLOW export-finalcut --recipe RECIPE`. Existing recipes can use `scripts/pipeline.py export-finalcut --recipe RECIPE`. A reconstruction without a complete saved media identity needs a fresh render and review before export.
6. Once eligible and confirmed, run schema, media-reference and frame-rational timing checks, then verify the exact populated project in Final Cut. Distinguish exported, statically checked and app-verified states. Preserve the crash-tested explicit connected audio/video representation.

The 85 threshold is timeline eligibility, separate from the controller's final-quality gate and user approval of the video. A deliberately shared working first cut may still have unresolved checks and an unpassed quality gate; label it accordingly. A user request to stop is honored regardless of score. Learning/documentation maintenance does not resume editing or timeline work.

Current editability: prepared picture treatments are baked; the saved recipe governs rebuilding crops/grade/trim. Narration may be a flat mix. Animated captions are burnt into the movie and reconstructed from sidecars/recipe, rather than native editable animated text. Verify any later subtitle-import workflow in the actual app before claiming it works.
