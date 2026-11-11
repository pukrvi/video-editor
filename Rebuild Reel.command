#!/bin/zsh
set -e
cd "$(dirname "$0")"
mode=$(.venv/bin/python -c 'import sys; sys.path.insert(0, "scripts"); from pipeline import ROOT, current_recipe, load; from pipeline_paths import recipe_mode; print(recipe_mode(load(ROOT / current_recipe())))')
if [[ "$mode" == "narrated_vlog" ]]; then
  .venv/bin/python scripts/pipeline.py render
  .venv/bin/python scripts/pipeline.py qa
  page=$(.venv/bin/python -c 'import sys; sys.path.insert(0, "scripts"); from pipeline import ROOT, current_recipe, load; from pipeline_paths import movie_path; print(movie_path(load(ROOT / current_recipe())).parent / "Review Vlog.html")')
  open "$page"
  .venv/bin/python scripts/quality_gate.py
  exit
fi
settings=$(.venv/bin/python -c 'import json; from pathlib import Path; s=json.loads(Path("CURRENT_EDIT.json").read_text()); r=json.loads(Path(s["recipe"]).read_text()); print(r.get("media_library", "")); print(r.get("public_review", ""))')
album=$(printf '%s\n' "$settings" | sed -n '1p')
review=$(printf '%s\n' "$settings" | sed -n '2p')
library_args=()
review_args=()
if [[ -n "$album" ]]; then library_args=(--library "$album"); fi
if [[ -n "$album" && -n "$review" ]]; then review_args=(--public-review "$review"); fi
.venv/bin/python scripts/catalog.py "${library_args[@]}"
.venv/bin/python scripts/standardize_sdr.py "${library_args[@]}" "${review_args[@]}"
.venv/bin/python scripts/pipeline.py render
.venv/bin/python scripts/pipeline.py qa
.venv/bin/python scripts/build_review.py
.venv/bin/python scripts/review_motion.py
open "Review Reel.html"
.venv/bin/python scripts/quality_gate.py
