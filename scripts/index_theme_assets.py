#!/usr/bin/env python3
"""Index explicitly allowed static artwork without entering personal folders.

Private paths and generated previews belong in the trip workspace, never in the
reusable checkout. Alpha bounds are half-open pixels; boxes refer to EXIF-oriented
pixels. Keywords come from filenames and are search hints, not visual labels.
"""
import argparse
import hashlib
import json
import re
from pathlib import Path

from PIL import Image, ImageDraw, ImageOps

CATEGORIES = ('Badges', 'Callouts', 'Cards', 'Character', 'Icons', 'Lower Thirds',
              'Mobile BG', 'Stickers', 'Title', 'Video Background')
EXTENSIONS = {'.png', '.jpg', '.jpeg', '.webp', '.tif', '.tiff'}


def inspect_image(path):
    with Image.open(path) as source:
        image = ImageOps.exif_transpose(source).convert('RGBA')
        alpha = image.getchannel('A')
        bounds = alpha.getbbox()
        extrema = alpha.getextrema()
        return {'width': image.width, 'height': image.height,
                'alpha_bounds': list(bounds) if bounds else None,
                'alpha_extrema': list(extrema), 'fully_opaque': extrema == (255, 255),
                'empty_alpha': bounds is None,
                'artwork_aspect': (bounds[2]-bounds[0])/(bounds[3]-bounds[1]) if bounds else None,
                'canvas_aspect': image.width/image.height}


def index_assets(root, categories):
    root = Path(root).expanduser().resolve(strict=True)
    if not categories or any(c not in CATEGORIES for c in categories):
        raise ValueError('Choose explicit supported artwork categories')
    records, errors = [], []
    for category in categories:
        directory = root/category
        if directory.is_symlink():
            raise ValueError('Asset category cannot be a symlink')
        if not directory.is_dir():
            continue
        # Do not traverse arbitrary directories or symlinks. This pack is flat.
        for path in sorted(directory.iterdir()):
            if path.is_symlink() or not path.is_file() or path.suffix.lower() not in EXTENSIONS:
                continue
            try:
                info = inspect_image(path)
                digest = hashlib.sha256(path.read_bytes()).hexdigest()
                records.append({'id': digest[:16], 'sha256': digest, 'category': category,
                                'filename': path.name, 'path': str(path),
                                'bytes': path.stat().st_size,
                                'keywords': list(dict.fromkeys(re.findall(r'[a-z0-9]+', path.stem.lower()))),
                                **info})
            except (OSError, ValueError) as exc:
                errors.append({'path': str(path), 'error': str(exc)})
    return {'schema': 1, 'root': str(root), 'categories': list(categories),
            'scope': 'Flat explicitly allowed category directories; no recursive scan; filename keywords only',
            'assets': records, 'errors': errors}


def write_sheets(index, output, page_size=30):
    output.mkdir(parents=True, exist_ok=True)
    for offset in range(0, len(index['assets']), page_size):
        page = index['assets'][offset:offset+page_size]
        canvas = Image.new('RGB', (1200, 6*190), '#d7d8d9')
        draw = ImageDraw.Draw(canvas)
        for pos, asset in enumerate(page):
            x, y = (pos%5)*240, (pos//5)*190
            for cy in range(y, y+140, 14):
                for cx in range(x, x+240, 14):
                    draw.rectangle((cx, cy, cx+13, cy+13), fill='#b9bcc0' if ((cx-x)//14+(cy-y)//14)%2 else '#e0e1e2')
            with Image.open(asset['path']) as source:
                art = ImageOps.exif_transpose(source).convert('RGBA')
                if asset['alpha_bounds']:
                    art = art.crop(asset['alpha_bounds'])
                art.thumbnail((228, 130), Image.Resampling.LANCZOS)
                canvas.paste(art, (x+(240-art.width)//2, y+(140-art.height)//2), art)
            label = f"{offset+pos+1:03} {asset['category']}\n{asset['filename']}"
            # Only preview labels are shortened; full filenames remain in JSON.
            draw.text((x+4, y+142), label[:85], fill='#111111')
            asset['sheet'] = f'sheet_{offset//page_size+1:03}.jpg'
            asset['sheet_slot'] = pos+1
        canvas.save(output/f'sheet_{offset//page_size+1:03}.jpg', quality=90)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', required=True, type=Path)
    parser.add_argument('--output', required=True, type=Path, help='New directory outside the asset library')
    parser.add_argument('--categories', nargs='+', choices=CATEGORIES, required=True)
    args = parser.parse_args()
    root = args.root.expanduser().resolve(strict=True)
    output = args.output.expanduser().absolute()
    if output.is_symlink() or any(x.is_symlink() for x in output.parents):
        raise ValueError('Output cannot use symlinks')
    if output.resolve().is_relative_to(root) or root.is_relative_to(output.resolve()):
        raise ValueError('Output must be outside and must not contain the asset library')
    if output.exists():
        raise ValueError('Use a new output directory to preserve previous indexes')
    index = index_assets(root, args.categories)
    output.mkdir(parents=True)
    write_sheets(index, output)
    (output/'index.json').write_text(json.dumps(index, indent=2)+'\n')
    print(json.dumps({'assets': len(index['assets']), 'errors': len(index['errors']), 'index': str(output/'index.json')}))


if __name__ == '__main__':
    main()
