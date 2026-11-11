# Video Editor

A local, recipe-based editor for personal music reels, personal narrated vlogs and commercial YouTube videos. The personal workflows apply the established styles on the first cut. The commercial workflow takes its direction from the episode brief and brand kit. [Editing profiles](EDITING_PREFERENCES.md) · [Five editing gates](AGENTS.md)

## Set up

Run `./Setup.command` on macOS for SDR music reels. Run `./Setup.command --narrated` for the personal vlog or commercial YouTube workflow. Use Python 3.12, FFmpeg and FFprobe. Setup checks the local tools and installs the pinned Python wheels into `.venv`. Narrated rendering needs the ASS subtitle filter. HDR tone mapping needs `zscale`. Homebrew’s standard FFmpeg can handle the SDR reel path. A capable build such as Homebrew’s `ffmpeg-full` supplies the additional filters. Local transcription is optional. [FFmpeg reference](docs/THIRD_PARTY_SKILLS.md) · [Narrated tools](docs/VLOG_WORKFLOW.md)

## Start a project

Run the matching command from the checkout. Keep the reel’s album beside the checkout. Narrated projects accept an album at an explicit path.

```sh
./video-editor personal-reel init --album ../MyTrip --slug my-trip --name 'My Trip'
./video-editor personal-vlog init --album /path/to/album --slug my-vlog --name 'My Vlog'
./video-editor commercial-youtube init --album /path/to/album --slug episode-01 --name 'Episode 01'
```

Each command creates a recipe and brief under `config/<slug>/v01/`. Fill the brief and recipe from the available sources. Movies and reconstruction files go to `exports/<slug>/<version>/`. Existing versions stay available. Run `./video-editor WORKFLOW --help` for its commands.

## Personal music reel

The starter uses a vertical 1080 × 1920, 30 fps canvas and a one-minute timeline. Set the local soundtrack, excerpt, tail fade and credits. Add consecutive shot windows with the frame counts needed for the chosen duration. Use the supplied patterns for kinetic openings, pencil labels, held poses and photo groups. The photo intake supports JPEG, PNG and HEIF using the Mac’s native image tools. [Shot example](examples/shot.json) · [Motion presets](examples/motion_presets.json) · [Motion reference](scripts/MOTION_GRAPHICS.md)

```sh
RECIPE=config/my-trip/v01/recipe.json
.venv/bin/python scripts/catalog.py --library MyTrip
.venv/bin/python scripts/standardize_sdr.py --library MyTrip --public-review config/my-trip/v01/public_review.json
./video-editor personal-reel review --recipe "$RECIPE"
./video-editor personal-reel render --recipe "$RECIPE"
./video-editor personal-reel qa --recipe "$RECIPE"
```

After `review`, inspect each full selected window and companion photo. Record its `pipeline.fingerprint` in the recipe’s local `approved_windows` map before `render`. QA creates the movie’s offline player and cover. Run `scripts/review_motion.py --recipe RECIPE` in the pipeline environment for additional samples around authored motion.

## Personal narrated vlog

Build an ordered story from inspected picture, native speech and recorded VO. The starter uses the selected active-word caption preset and vertical 1080 × 1920 at 30 fps. Add a quiet music bed when the story calls for it. Duration follows the speech and story. [Narrated tools and recipe](docs/VLOG_WORKFLOW.md)

```sh
./video-editor personal-vlog render --recipe config/my-vlog/v01/recipe.json
./video-editor personal-vlog qa --recipe config/my-vlog/v01/recipe.json
```

## Commercial YouTube video

Start from the channel promise, supplied brand and deliverables. The landscape 1920 × 1080, 30 fps starter uses neutral captions and no preset soundtrack. Use the narration engine for the picture and speech clock. Record factual evidence, commercial-use rights and sponsor requirements in the local brief where applicable. [Commercial brief template](templates/commercial-youtube-brief.md) · [Narrated recipe structure](docs/VLOG_WORKFLOW.md)

```sh
./video-editor commercial-youtube render --recipe config/episode-01/v01/recipe.json
./video-editor commercial-youtube qa --recipe config/episode-01/v01/recipe.json
```

## Review, revise and export

Each render writes a fresh independent review request. Give the reviewer the exact movie, its local brief and technical evidence. Starter recipes request GPT-6.1 Sol at high effort. Legacy recipes use medium when unspecified. A command-line render leaves the director review pending until the editing agent obtains the separate assessment. [Independent review](docs/DIRECTOR_WORKFLOW.md)

```sh
.venv/bin/python scripts/quality_gate.py --recipe RECIPE --report LOCAL_REPORT
./video-editor WORKFLOW revise --recipe RECIPE --version v02
./video-editor WORKFLOW export-finalcut --recipe RECIPE
```

`revise` copies the brief, recipe and any music-reel screening record into a fresh version. Apply feedback there and recheck changed selections. Use the [Final Cut export policy](docs/FINAL_CUT_EXPORT_POLICY.md) when a timeline is requested. Movie delivery includes the offline player and applicable caption sidecars. Keep source media, generated files, private project details, transcripts, source coordinates, rights records and review evidence local.

Existing recipes and `Rebuild Reel.command` still use `scripts/pipeline.py`. Older recipes infer the renderer from `shots` or `blocks`. Legacy relative reel output paths start at the checkout and legacy relative narrated output paths start at the invoking directory.
