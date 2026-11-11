# Motion overlays

Recipe `titles` retain the existing static styles. For an animated, movable Final Cut layer, set `style` to `motion_editorial`, `motion_marker`, or `motion_closure`. Each still requires `headline`, `start`, `end`, and `y`. Times are seconds, rounded to output-frame boundaries. Coordinates and `size` are designed at 1080 pixels wide and scale with the output width; `x` defaults to a left margin. Choose placement after inspecting the shot.

- `motion_editorial`: headline, optional `kicker`, and a drawing rule.
- `motion_marker`: compact uppercase headline and drawing rule; optional `ticks` (0–12).
- `motion_closure`: headline and optional staggered `line2`, optional `kicker`, and drawing rule.

Optional parameters: `x`, `size`, `font` (local font path), `font_index`, `ink` and `accent` (RGBA arrays), `enter_frames`, and `exit_frames`. Text and accent default to warm white and muted gold. Set entry and exit durations to suit the shot; the layer ends with a transparent frame. Animated overlays are ProRes 4444 alpha movies, rather than still images. Final Cut can move, trim, or disable each connected layer; change the text in the recipe and rebuild.

Optional `transitions` are independent overlays above titles, for example:

```json
{"id":"arrival_sweep", "preset":"diagonal_sweep", "cut_frame":240, "duration_frames":12, "color":"#F3DFBE"}
```

Available presets are `diagonal_sweep` and `light_leak`. A transition is centered on an actual cut. Use an even duration of at least four frames that fits inside the two adjacent shots. Each transition exports as a separate movable connected video layer. Check the picture and text beneath it, then open the project in Final Cut to verify playback and transparency.

## Kinetic styles and photo stacks

`kinetic_open` adds a staggered, masked letter reveal and a large outlined echo. `contour_marker` draws illustrative contour curves above a location label; these are decorative and do not depict a surveyed route. `kinetic_closure` reveals the headline and optional `line2` in staggered rows and holds them. They use the same title fields as the earlier styles. Inspect the moving text over the actual footage for placement and legibility.

For a collage, make a photo shot with `photo_layout: "stack"` and a `photo_stack` array of exactly two full companion catalogue metadata objects (with `id`, `file`, and `key`); the shot's normal photo is the first of three. The three photos enter in sequence as tilted overlapping prints and remain on screen. The stack is baked into the prepared shot in Final Cut. Each photo must be screened, and the complete three-photo shot must be visually reviewed and fingerprinted before the final render. Check all three against the rest of the edit for repeated photographs.

`field_note` is a smaller secondary chapter label with an animated open corner and masked headline reveal; it accepts the same `x`, `y`, `size`, `kicker`, color, and timing fields. Its default size is 55 at 1080-wide output. Position it against the actual shot and keep it clear of faces and action.

## Scene-aware styles (Krabi refinement)

`ridge_trace` draws a single recipe-supplied silhouette directly over the picture, then a leader and one-line name with a soft local dark scrim. It requires `ridge_points: [[x,y], ...]`, normalized to the output frame, not the source image. `ridge_keyframes: [{"frame":0,"dx":0,"dy":0,"scale":1}, ...]` optionally follows camera motion: frame is title-relative; normalized dx/dy and scale interpolate linearly, scaling about frame center. Inspect the ridge against the actual moving picture. Set a separate title per shot. `leader_points` optionally supplies a normalized leader path using the same transform; otherwise the last ridge point connects to the stationary label. `ridge_draw_frames` (18), `leader_frames` (7), `label_delay_frames` (21) and `line_width` (4) control timing/stroke. Standard x/y/size control the label; no kicker is rendered.

`pan_label` uses a pan-directed horizontal masked name reveal with brief travel and a retracting bracket. Set `pan_direction` to `left` or `right`; defaults: `reveal_frames:12`, `travel:36`, `bracket_hold_frames:5`, `bracket_retract_frames:8`, `size:68`. The name stays fixed after its short arrival. It has a modest offset shadow and no outline or kicker.

For larger `kinetic_open` typography, explicitly set `outline_gap` (42 is a useful starting point). This positions the outlined echo above the actual filled glyph height, keeping both words separate; omitted preserves the original layout.

For the new people-priority photo composition, set shot `photo_stack_layout: "people"` (renderer passes `layout="people"`). Source order remains marlin, lookout, market. Cards occupy roughly 56%, 60%, and 48% of output width, with tight native-aspect borders and overlap. They stagger by 0.22s, overshoot and settle within eight frames, then receive a shared subtle push. Keep the slot long enough for a 1.1s+ established hold. The default `legacy` layout preserves earlier stack rendering.

## Playful live/freeze memories

Shot `playful_focus` opts into a baked personal-memory treatment; other shots use their normal rendering. Example:

```json
{"freeze_frame":18,"hold_frames":11,"zoom":1.10,"focus":[0.52,0.42],"subject":[0.52,0.42],"doodles":"portrait","seed":0}
```

`freeze_frame` is relative to the prepared shot after speed/fps conversion, with zero-based frames. `hold_frames` includes that first frozen frame: output 18–28 displays source frame 18, and output 29 resumes at source frame 19. Total shot length stays fixed and less source footage is consumed. A reversible camera push focuses around normalized output `focus`. The push eases out as live action resumes. Faces are never regenerated.

`subject` places loose pencil curves beside the head and a curved heart/sparkle above it. `doodles` accepts `portrait`, `couple` (heart centered), or `celebrate` (extra curved rays). Set `doodle_scale` to adjust the frame around the subject. `doodle_start_frame` defaults to freeze_frame; `doodle_step_frames` defaults to 2, with each stroke drawing over 5 frames. `stroke_width` defaults to 4 at 1080 wide. `ink` and `pencil` accept RGBA colors. `seed` keeps the small hand-drawn wobble stable. An explicit `paths` array of polylines in normalized output coordinates overrides generated shapes for precise reviewed placement. Check actual moving images for faces and important details.

For an ordinary photograph with drawings only, set `drawing_only:true`, `doodle_start_frame:0`, and optionally `zoom:1.02`. The prepared still follows the normal photo layout before this treatment; no source is replaced and no freeze mapping is applied.

## Handwritten notes and opening placement

`sketch_label` uses the installed Bradley Hand Bold face, a staggered write-on, a curved double pencil underline and a small sparkle. `sketch_ridge` keeps the normalized `ridge_points` and interpolated `ridge_keyframes` of `ridge_trace`, with the same draw/leader/delay fields; its label uses the handwritten system and a narrow offset pencil shadow rather than a broad scrim. Both accept normal x/y/size, headline, start/end, font/font_index and ink/accent fields. Match their placement to the moving scene. A size around 68–80 at 1080 wide is a useful phone-readable starting point for short labels. They display one line and ignore kicker/line2.

Optional fields: `sketch_draw_frames` (14), `underline_width` (1080-based length; defaults to 82% of name width), `doodle_accent` (`sparkle`, `heart`, or `none`), `pencil` (dark shadow RGBA), `line_width` (4). Default warm ink is `[255,246,218,255]`; dark pencil is `[67,49,38,210]`. `sketch_open` is also available with a larger 165 default size and a 12-frame entry, but the current playful opening deliberately retains `kinetic_open` by user direction.

`kinetic_open` accepts `left_rule:false` to remove only its vertical edge rule. `kicker_position:"lower_right"` places the kicker below and right-aligned to the filled word, revealing after the main entry. The filled word and outlined echo retain their original positions. `kicker_delay_frames` optionally overrides the delay (default enter_frames). Omitted fields preserve legacy rendering.

## Gentle photo swing and pencil accents

Optional shot `photo_stack_animation` is passed as `animation` after `layout` to `photo_stack.prepare`, `frame`, and `render`. Example:

```json
{"swing_degrees":1.4,"swing_period_seconds":3.0,"doodles":"food"}
```

Use `doodles:"food"` for the `food` layout (burger and stars) and `doodles:"travel"` for `people_clear` (paper plane, curved trail, heart and stars). These placements were inspected in the actual Krabi compositions at 540×960: accents occupy the background gaps and leave the photo contents unobstructed. Keep matching the layout and preset; inspect again if photos or layout change.

The cards rotate directly from their unrotated prepared bases, around fixed resting centers with independent phases, in addition to their original tilts. `swing_degrees` is clamped to 0–2, and `swing_period_seconds` defaults to 3.0. Entry anchors, margins, arrival timing and the shared camera push remain unchanged. Doodles draw on after the arrivals and pulse subtly. `doodle_start_frame` optionally overrides their first frame; `doodle_ink` and `doodle_pencil` accept RGBA overrides. Omit `photo_stack_animation` to preserve the previous rendering exactly.

## Adopted reference and final correction controls

Read [the quality baseline](../REEL_QUALITY_BASELINE.md) before designing the next reel. The reusable style settings are in `examples/motion_presets.json`. Preserve the general craft standard while choosing positions and timing for the new footage.

For `sketch_ridge`, set `leader_join:"underline"` to connect the default leader to the underline’s left endpoint below the lettering. The final Krabi example uses `leader_frames:10`. Inspect the draw phase, settled state and tracked ridge in the composited movie. A source-space point must be projected through the same crop and zoom as the picture.

For a beat hold that runs through a following cut, choose `hold_frames` so the source stays held through the last frame of the shot. The opening Krabi slots use `freeze_frame:18` and `hold_frames:19`. If a live restart is intended, leave enough output frames for the resumed action and verify its musical timing.

Set the recipe’s music `fade_out` to2.0 for the adopted two-second ending fade. The renderer applies it relative to the actual reel duration. Include the parameter explicitly in new recipes because the compatibility default for older recipes is0.65 seconds. Verify the final music envelope and record listening separately.

Run `scripts/review_motion.py --recipe config/reel_v01.json` with the pipeline Python environment to collect the current movie’s event samples. Read its hash-bound manifest and inspect the frames before marking motion checks complete. A new render requires evidence for that new movie identity.
