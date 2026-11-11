"""Build frame-numbered review sheets for the actual rendered motion sequences."""
import argparse
import re

from PIL import Image, ImageDraw, ImageFont

from pipeline import ROOT, command, current_recipe, load, reel_review_dir, require, save
from pipeline_paths import guard_output_tree, movie_path
from quality_gate import sha256_file


def build(recipe):
    movie = movie_path(recipe)
    digest = sha256_file(movie)
    request = load(movie.parent/'director_review_request.json')
    require(request['movie_sha256'] == digest, 'Movie does not match the current review request')
    folder = reel_review_dir(recipe) / f"output_{recipe['version']}" / f"motion_{digest[:10]}"
    frames_folder = folder / 'frames'
    fps = recipe['fps']
    total = round(recipe['duration'] * fps)
    groups = []

    for title in recipe['titles']:
        start, end = (round(title[key] * fps) for key in ('start', 'end'))
        groups.append((title['headline'], [
            start - 1, start + 2, start + 7, start + 14,
            (start + end) // 2, end - 7, end - 2, end,
        ]))
    for transition in recipe.get('transitions', []):
        cut = transition['cut_frame']
        start = cut - transition['duration_frames'] // 2
        end = start + transition['duration_frames']
        groups.append((transition['id'], [
            start - 1, start, start + 2, cut - 1, cut, cut + 2, end - 1, end,
        ]))
    for shot in recipe['shots']:
        start = shot['start_frame']
        count = shot['frames']
        if shot.get('photo_layout') == 'stack':
            groups.append((shot['id'] + ' photo collage', [
                start + min(offset, count - 1)
                for offset in (0, 5, 11, 18, 27, count // 2, count - 15, count - 1)
            ]))
        focus = shot.get('playful_focus')
        if focus:
            freeze = focus.get('freeze_frame', 18)
            hold = focus.get('hold_frames', 11)
            groups.append((shot['id'] + ' pencil focus', [
                start + min(max(0, offset), count - 1)
                for offset in (0, freeze - 1, freeze, freeze + 4,
                               freeze + hold // 2, freeze + hold - 1,
                               freeze + hold, count - 1)
            ]))

    groups = [(name, sorted({n for n in numbers if 0 <= n < total}))
              for name, numbers in groups]
    selected = sorted({n for _, numbers in groups for n in numbers})
    if not selected:
        return None
    sheet_names = [f"{i:02d}_{re.sub(r'[^A-Za-z0-9]+', '_', name).strip('_')}.jpg"
                   for i, (name, _) in enumerate(groups)]
    guard_output_tree(folder, (movie,), writable=('frames', 'review_manifest.json', *sheet_names))
    frames_folder.mkdir(parents=True, exist_ok=True)
    expression = '+'.join(f'eq(n,{n})' for n in selected)
    command([
        'ffmpeg', '-v', 'error', '-i', movie, '-map', '0:v:0',
        '-vf', f"select='{expression}',scale=180:320",
        '-fps_mode', 'vfr', '-q:v', '2', '-y', frames_folder / '%04d.jpg',
    ])
    mapping = {n: frames_folder / f'{i + 1:04d}.jpg'
               for i, n in enumerate(selected)}
    font = ImageFont.truetype('/System/Library/Fonts/Supplemental/Arial.ttf', 14)
    records = []
    for i, (name, numbers) in enumerate(groups):
        sheet = Image.new('RGB', (720, 710), (18, 20, 21))
        draw = ImageDraw.Draw(sheet)
        draw.text((6, 3), name, font=font, fill='white')
        for j, number in enumerate(numbers):
            x, y = j % 4 * 180, j // 4 * 342 + 24
            draw.text((x + 4, y), f'F{number:04d} / {number / fps:.3f}s',
                      font=font, fill='white')
            with Image.open(mapping[number]) as frame:
                sheet.paste(frame, (x, y + 18))
        output = folder / sheet_names[i]
        sheet.save(output, quality=94)
        records.append({'name': name, 'output_frames': numbers,
                        'sheet': str(output.relative_to(ROOT))})
    manifest = folder / 'review_manifest.json'
    require(sha256_file(movie) == digest, 'Movie changed during motion review sampling')
    save(manifest, {
        'movie_sha256': digest, 'request_id': request['request_id'], 'recipe': recipe['version'],
        'coverage': 'Selected output frames only. Audio listening is separate.',
        'groups': records,
    })
    print(manifest)
    return manifest


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--recipe', default=current_recipe())
    args = parser.parse_args()
    build(load(ROOT / args.recipe))
