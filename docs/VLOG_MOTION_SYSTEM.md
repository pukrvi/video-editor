# Narrated-vlog motion system

This system separates heard speech, verified information, personal notes and photographs. It uses source artwork as individually controlled layers; it does not place a complete screenshot of an asset board over the film. Original artwork, original trip media and the clean movie stay intact. A theme descriptor is a proposed design until its actual composited windows have been reviewed.

The current [narrated style](../EDITING_PREFERENCES.md) governs duration, story and audio. Keep claims in graphics tied to the local fact ledger and preserve complete actions and reactions.

## 1. Inventory and provenance

Use `scripts/index_theme_assets.py` with explicit `--root`, new `--output` and `--categories`. Supported category names are deliberately allowlisted. The indexer scans only files directly within those named categories. It never recurses into the library, never accepts `Personal Content`, and skips symlinks. Layout-guide boards and premade phrases can be indexed but are not automatically eligible graphics.

```sh
python3 scripts/index_theme_assets.py --root "$ASSET_LIBRARY" \
  --output "$TRIP_WORKSPACE/catalog/theme_assets_v1" \
  --categories Title Cards Callouts Icons 'Lower Thirds' 'Mobile BG' 'Video Background'
```

The output directory must be new and outside the source library. Keep its JSON, paths, previews and private theme descriptor in the trip workspace. Only the reusable code, tests and this document belong in the reusable checkout.

Each record contains SHA256, dimensions after EXIF orientation, half-open pixel `alpha_bounds=[left,top,right,bottom]`, alpha extrema, `fully_opaque`, `empty_alpha`, artwork/canvas aspect ratios and filename keywords. Any alpha greater than zero counts as artwork, including faint shadows. RGB and fully opaque RGBA images use the entire canvas. Empty alpha has `alpha_bounds=null` and `artwork_aspect=null`; it cannot serve as a visible layer. Keywords are search hints, not visually verified descriptions. Contact sheets show alpha-cropped artwork over a checkerboard, accompanied by JSON-linked slots. Do not interpret JPG white backgrounds as transparency.

## 2. Theme descriptor and coordinate spaces

Private descriptor schema version 1:

| Field | Meaning and constraints |
|---|---|
| `schema`, `name`, `status` | Integer version, theme name and actual review state. |
| `reference_canvas` | Positive integer `[width,height]`, normally `[1080,1920]`. |
| `palette` | Named explicit colors; no random per-shot recoloring. |
| `typography` | Separate `subtitle`, `info`, `chapter`, `joy` roles: actual font path, size at reference width, ink, purpose. |
| `safe_regions` | Normalized canvas `[x,y,width,height]` starting regions and subtitle reservation. These do not certify face clearance. |
| `families` | Named editorial/joy/weather presets, with real entry, exit, hold and supported motion parameters. |
| `elements` | Role-keyed asset definitions with path, SHA256, alpha bounds/aspect, family, text/photo boxes and inspection evidence. |
| `motion_contract` | Seed, limits, photo-fit rule, transition rule, decorative density and audio requirement. |
| `implementation_boundary` | Exact implemented renderer controls, proposed controls and missing checks. |

**Asset boxes** `text_box` and `photo_box` are normalized `[x,y,width,height]` **within alpha-cropped artwork**, not the original file canvas and not the video. All values must be finite and nonnegative; width/height must be positive; right/bottom must not exceed 1. Photo and text boxes describe separately inspected content areas. Do not let a broad default text box obscure tape, stars, folded corners or paper clips. A box validated numerically still needs pixel inspection.

**Canvas boxes** use the output picture's normalized coordinates. Layer `x,y,width` are pixels at the actual output dimensions in the current renderer. Compute the layer's height from the cropped artwork aspect, then scale the chosen asset box inside it. Font sizes scale with output width. Never distort the artwork to force an arbitrary rectangle.

Example element, deliberately without a private path:

```json
{
  "family": "editorial",
  "asset": "ABSOLUTE_PRIVATE_ASSET_PATH",
  "sha256": "SOURCE_SHA256",
  "alpha_bounds": [8, 0, 3230, 453],
  "text_box": [0.16, 0.25, 0.69, 0.48],
  "photo_box": null,
  "box_space": "normalized alpha-cropped artwork; x,y,width,height"
}
```

## 3. Three related motion families

All families share paper texture, warm cream/charcoal, controlled yellow/blue/pink accents and the same typographic hierarchy. They differ in energy because they serve different story beats.

| Family | Purpose | Entry / exit | Established hold | Motion |
|---|---|---|---|---|
| Editorial | Journey setup, day change, factual cost/route strip | 0.28s / 0.20s | ≥1.6s, typically total 2.1–4.5s | 20px reference-width eased travel; settle and stay still. |
| Joy | Uno, dogs, tea, shared snow memories | 0.32s / 0.20s | ≥1.5s, typically total 2.1–3.5s | Small fixed single overshoot; deterministic 1.2px smooth sine drift; no per-frame random shake. |
| Weather | Worsening conditions, difficulty, truthful decisions | 0.20s / 0.16s | ≥2.0s, typically total 2.5–4.5s | 8px eased travel, no bounce or jitter; black paper only where it protects legibility. |

These are design presets, not proof that every renderer implements every control. Clamp jitter to at most 2px at 1080 width, photo swing to 0.8 degrees and slow shared photo push to 1.025×. Use a fixed recorded seed; sample continuous low-frequency motion rather than calling randomness per frame. Do not jitter subtitles, weather information, faces or footage. A seed must reproduce identical pixels for identical inputs/settings.

No more than one decorative label or icon should compete with the main footage at a time. A sticker after every shot is not a motion system. Notes should add one human observation or useful fact, not repeat speech. Hold a label long enough to read, then remove it before the next shot changes its meaning. Overlay entry must not conceal the setup of a fall, first dog jump or a reveal.

## 4. Speech, information and safe placement

Subtitles are faithful heard words in a stable sans-serif, with a narrow dark backing when required by snow/forest contrast. They do not use scrapbook assets or oscillation. Information strips use a smaller regular sans-serif and explicit factual wording. Chapter names use a larger bold face. Personal notes may use the supplied handwritten role if readable at phone size. Keep each role visually distinct.

At 1080×1920, the theme starts with a 7% horizontal margin, reserves approximately y=76–89% for subtitles, and proposes chapters near y=11–31%. These are candidate zones, not automatic safe placements. Inspect the complete crop/zoom/motion of faces, mouths, hands, trekking poles, dogs, feet, gear, signs and distant scenery. Move or omit a graphic on a collision; shrinking all text is not a solution. Account for the full entrance, overshoot, jitter and exit envelope. Preserve safe space at both transparent endpoints.

A reading hold is separate from active-word highlighting. Do not keep a spoken word lit during a pause. Do not stack a chapter, cost card and speech caption over one talking face. New information cards can appear over appropriate B-roll while original speech continues on its original clock.

## 5. Layered photographs and backgrounds

Use a vertically designed full-screen background at its intended aspect; preserve its borders. Landscape boards labelled as layout guides must not be stretched into portrait. A source JPG is an opaque background unless a separate mask is deliberately made and reviewed.

Compose photographs as independent layers over the background. Use EXIF-oriented full-resolution sources and resample once. Default `fit=contain` within the inspected `photo_box`: retain faces and meaningful landscape rather than filling a hole by cutting off a person. If cover is necessary, record the actual crop rectangle and inspect it against the original. Artwork and photograph may have different entrance times, but background should establish first; photo arrives 0.10–0.18s later; a short note may follow after another 0.15s. Maintain at least 1.5s of readable established composition. Do not make every photo a mini-card nested inside several other frames.

Photo swing/push, if implemented, belongs to the photo/card group so borders and picture do not drift apart. Swing rotates once from an unrotated prepared source at each frame. Keep tilt and full motion within canvas; no face should move behind a paper corner. A photo-only memory can breathe for 3–6s when its content warrants it.

## 6. Entrances, exits and transitions

Clean cuts are the default. A paper reveal belongs at a real chapter boundary, a directional slide may echo the adjacent source movement, and weather can make a restrained direct change of tone. Do not put an opaque decorative wipe between an earned pan and its scenery. A transition must not hide a complete action's last moment. Use approximately 0.20–0.35s at a chapter change and inspect outgoing, center and incoming frames.

The existing `transition_graphics.py` presets and `motion_graphics.py` styles remain available according to `scripts/MOTION_GRAPHICS.md`. They are not automatically selected by a theme. Record transition purpose, adjacent shots, start/end frames and the exact supported parameters. Transparent start/end means alpha zero, not a black video frame.

## 7. Renderer adapter and actual support

`vlog_graphics.prepare_graphics` and `apply_graphics` accept explicit `graphics` with `asset,text,at,duration,x,y,width,font_size,ink`, optional `font,text_box,entrance,exit,slide_px`. Artwork is alpha-trimmed; text wraps within its inspected box; overflowing words/height raise an error rather than silently reducing type. Text, art and prepared layer hashes belong in the manifest. Applying graphics creates a new movie and preserves the clean movie's audio instead of remixing it.

Theme resolution is an adapter step: choose a role; verify asset SHA and alpha bounds; read its asset box; choose a per-shot reviewed canvas placement; resolve only implemented family controls; validate against the frame clock and full animation envelope; prepare the layer; record the resolved settings. A descriptor by itself does not activate jitter, photo composition, new easing or transitions. Unsupported requested controls must raise an error or remain explicitly proposed—not be silently treated as implemented.

The current overlay implementation additionally supports `easing` (`smooth` or `overshoot`), `jitter_px` in 0–2, integer `seed` and numeric `z` stacking order. Overshoot has a fixed approximately 10% offset; smooth sine frequencies are fixed at ≤1.3Hz. There is no configurable `jitter_hz` or overshoot-fraction parameter. Map the joy family to `easing=overshoot`; editorial/weather use `smooth`. `apply_graphics(..., prepared_layers=list)` accepts already-composed photo PNGs without recropping. These controls were implemented by the overlay workstream; this index/design workstream verified its own indexer tests and theme pixels, not the overlay worker's moving preview. Read the actual renderer manifest and separate preview evidence before delivery.

## 8. Evaluation and delivery contract

1. Index the explicit library subset and inspect candidate art at readable scale. Save source hashes, selected-artwork evidence and measured boxes.
2. Prepare one short representative composition per family, a photo/background composition and a subtitle-with-info collision case. Include actual source action and snow contrast.
3. Check transparent entry/exit, peak overshoot, settled hold, motion extrema, crop, font shaping and full text at output size. Test no text truncation and no face/action collision.
4. Render short moving previews and inspect them continuously. Still sheets do not establish motion smoothness, complete action endpoints or intelligibility.
5. Run meaningful alpha-bound tests and renderer tests; bind visual verdicts to the actual preview/movie hash. Different seeds/settings create new review identities.
6. Inspect the full movie independently for story rhythm, decorative density and audio. Numerical geometry and unit tests are mechanics evidence, not a design score. Evaluate the chosen music policy against the isolated stem and encoded mix.

The initial indexer tests cover opaque RGB full-canvas bounds, empty alpha, faint alpha-edge preservation and exclusion of personal/nested folders. A private theme may be pixel-inspected while composited motion and playback remain pending. Report those states separately. Final Cut export remains subject to the existing export policy.
