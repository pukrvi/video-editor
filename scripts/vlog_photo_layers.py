"""Prepare independent RGBA photo panels for vlog_graphics.apply_graphics.

Recipes contain photo_compositions with at/duration, two to four photos and
optional background/artwork layers. Photos use explicit x/y/width/height pixels,
fit='contain' (whole original) or 'cover' with normalized focus=[x,y]. Rotation,
rounded masking, border and shadow are baked into each panel; arrivals, exits
and subtle independent motion stay as separate graphic layer records. Originals
are read-only. No face generation, subject inference or documentary fabrication.
"""
import hashlib
import json
import math
from pathlib import Path

from PIL import Image, ImageChops, ImageColor, ImageDraw, ImageFilter, ImageOps
from photo_io import PHOTO_EXTENSIONS, open_photo


def _num(value, name, low=None, high=None):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError(f'{name} must be a finite number')
    if low is not None and value < low or high is not None and value > high:
        raise ValueError(f'{name} outside permitted bounds')
    return float(value)


def _source(value):
    path = Path(value).expanduser()
    if not path.is_absolute() or not path.is_file():
        raise ValueError('Photo/art source must be an existing absolute path')
    path = path.resolve()
    if 'Personal Content' in path.parts:
        raise ValueError('Personal Content assets are excluded')
    return path


def _load(path):
    reader = (open_photo(path) if path.suffix.lower() in PHOTO_EXTENSIONS else
              Image.open(path, formats=['PNG', 'JPEG', 'WEBP', 'GIF', 'TIFF', 'BMP', 'AVIF']))
    with reader as image:
        return ImageOps.exif_transpose(image).convert('RGBA')


def fit_image(image, size, fit='contain', focus=(.5, .5)):
    """Return RGBA; explicit focus is a source-image focal point for cover."""
    if fit not in ('contain', 'cover'):
        raise ValueError('fit must be contain or cover')
    if not isinstance(focus, (list, tuple)) or len(focus) != 2:
        raise ValueError('focus must be normalized [x,y]')
    fx, fy = [_num(v, 'focus', 0, 1) for v in focus]
    width, height = size
    if min(width, height) < 1:
        raise ValueError('Empty photo size')
    image = image.convert('RGBA')
    if fit == 'contain':
        return ImageOps.contain(image, size, Image.Resampling.LANCZOS)
    scale = max(width/image.width, height/image.height)
    grown = image.resize((max(width, round(image.width*scale)), max(height, round(image.height*scale))), Image.Resampling.LANCZOS)
    left = min(grown.width-width, max(0, round(fx*grown.width-width/2)))
    top = min(grown.height-height, max(0, round(fy*grown.height-height/2)))
    return grown.crop((left, top, left+width, top+height))


def _panel(image, spec, size, attached=()):
    photo = fit_image(image, size, spec.get('fit', 'contain'), spec.get('focus', [.5, .5]))
    for mark, path in attached:
        left = round(_num(mark['x'], 'attached art x', 0))
        top = round(_num(mark['y'], 'attached art y', 0))
        width = round(_num(mark['width'], 'attached art width', 1))
        height = round(_num(mark['height'], 'attached art height', 1))
        if left + width > photo.width or top + height > photo.height:
            raise ValueError('Attached artwork exceeds the fitted photo bounds')
        art = _load(path)
        if art.getchannel('A').getbbox() is None:
            raise ValueError('Attached artwork is fully transparent')
        art = art.resize((width, height), Image.Resampling.LANCZOS)
        photo.alpha_composite(art, (left, top))
    radius = round(_num(spec.get('radius', 12), 'radius', 0, min(photo.size)/2))
    mask = Image.new('L', photo.size)
    ImageDraw.Draw(mask).rounded_rectangle((0, 0, photo.width-1, photo.height-1), radius=radius, fill=255)
    # Multiplication preserves original transparent regions; replacing alpha
    # would turn transparent artwork corners into opaque black pixels.
    photo.putalpha(ImageChops.multiply(photo.getchannel('A'), mask))
    border = round(_num(spec.get('border', 7), 'border', 0, 50))
    card = Image.new('RGBA', (photo.width+2*border, photo.height+2*border))
    if border:
        stroke = ImageDraw.Draw(card)
        stroke.rounded_rectangle((0, 0, card.width-1, card.height-1), radius=radius+border,
                                 outline=ImageColor.getcolor(spec.get('border_color', '#FFF3DA'), 'RGBA'), width=border)
    card.alpha_composite(photo, (border, border))
    blur = _num(spec.get('shadow', 8), 'shadow', 0, 30)
    offset = round(_num(spec.get('shadow_offset', 5), 'shadow_offset', 0, 30))
    pad = math.ceil(blur*4)+offset+2
    canvas = Image.new('RGBA', (card.width+2*pad, card.height+2*pad))
    if blur:
        alpha = Image.new('L', canvas.size)
        alpha.paste(card.getchannel('A'), (pad+offset, pad+offset))
        alpha = alpha.filter(ImageFilter.GaussianBlur(blur)).point(lambda x: round(x*.32))
        shade = Image.new('RGBA', canvas.size, (0, 0, 0, 0)); shade.putalpha(alpha)
        canvas.alpha_composite(shade)
    canvas.alpha_composite(card, (pad, pad))
    angle = _num(spec.get('rotation', 0), 'rotation', -20, 20)
    canvas = canvas.rotate(angle, Image.Resampling.BICUBIC, expand=True)
    bounds = canvas.getchannel('A').getbbox()
    if bounds is None:
        raise ValueError('Photo panel is fully transparent')
    # Keep geometric center when trimming transparent padding after rotation.
    center = (canvas.width/2-bounds[0], canvas.height/2-bounds[1])
    sprite = canvas.crop(bounds)
    swing = _num(spec.get('swing_degrees', 0), 'swing_degrees', 0, 6)
    if swing:
        # The static tilt has already been applied. Pad for every angle of the
        # extra swing and keep the original print center as the FFmpeg pivot.
        rx = max(center[0], sprite.width-center[0]); ry = max(center[1], sprite.height-center[1])
        turn = math.sin(math.radians(swing))
        half_width = math.ceil(rx + ry*turn) + 2; half_height = math.ceil(ry + rx*turn) + 2
        padded = Image.new('RGBA', (2*half_width, 2*half_height))
        padded.alpha_composite(sprite, (round(half_width-center[0]), round(half_height-center[1])))
        return padded, (half_width, half_height)
    return sprite, center


def _safe(path, sources):
    for item in (path, *path.parents):
        if item.is_symlink(): raise ValueError('Photo outputs cannot use symlinks')
    if path.exists() and path.is_file() and any(path.samefile(s) for s in sources):
        raise ValueError('Photo output aliases an original')
    return path


def prepare_photo_layers(recipe, out):
    """Return prepared graphics records; validate all layers before writes.

    Photo x/y/width/height define a resting box; contain fits the entire image
    within that box. Each photo can override delay, duration, entrance, exit,
    slide_px, jitter_px, seed, easing and z. Background: kind='blur' with photo
    index (default 0) or file; kind='art' with file. Background and artwork use
    the same explicit resting rectangle, defaulting to the whole canvas.
    """
    width = int(_num(recipe['width'], 'width', 1)); height = int(_num(recipe['height'], 'height', 1))
    fps = int(_num(recipe['fps'], 'fps', 1))
    if (width, height, fps) != (recipe['width'], recipe['height'], recipe['fps']):
        raise ValueError('Geometry and fps must be integers')
    total = sum(round((b['out']-b['in'])*fps) for b in recipe['blocks']) if 'blocks' in recipe else round(_num(recipe['duration'], 'duration', 1/fps)*fps)
    pending = []; sources = []
    for ci, comp in enumerate(recipe.get('photo_compositions', [])):
        photos = comp['photos']
        if len(photos) not in (2, 3, 4): raise ValueError('Photo composition needs two to four photos')
        at = _num(comp['at'], 'at', 0); duration = _num(comp['duration'], 'duration', 3/fps)
        start = round(at*fps); count = round(duration*fps)
        if start+count > total: raise ValueError('Photo composition exceeds timeline')
        paths = [_source(p['file']) for p in photos]; sources.extend(paths)
        images = [_load(path) for path in paths]
        layers = []
        background = comp.get('background')
        if background:
            if background.get('kind', 'blur') == 'blur':
                if 'file' in background:
                    bgpath = _source(background['file']); sources.append(bgpath); bg = _load(bgpath)
                else:
                    index = background.get('photo', 0)
                    if not isinstance(index, int) or not 0 <= index < len(images): raise ValueError('Invalid background photo index')
                    bg = images[index]
                bw = round(_num(background.get('width', width), 'background width', 1)); bh = round(_num(background.get('height', height), 'background height', 1))
                bg = fit_image(bg, (bw, bh), 'cover', background.get('focus', [.5, .5]))
                bg = bg.filter(ImageFilter.GaussianBlur(_num(background.get('blur', 24), 'background blur', 0, 80)))
                dim = _num(background.get('dim', .3), 'background dim', 0, 1)
                bg = Image.blend(bg, Image.new('RGBA', bg.size, (12, 18, 25, 255)), dim)
            elif background['kind'] == 'art':
                bgpath = _source(background['file']); sources.append(bgpath)
                bw = round(_num(background.get('width', width), 'background width', 1)); bh = round(_num(background.get('height', height), 'background height', 1))
                bg = fit_image(_load(bgpath), (bw, bh), background.get('fit', 'cover'), background.get('focus', [.5, .5]))
            else: raise ValueError('Background kind must be blur or art')
            spec = {**background, 'slide_px': background.get('slide_px', 0), 'z': background.get('z', -100)}
            layers.append((bg, spec, (bg.width/2, bg.height/2), 'background'))
        for pi, (spec, image) in enumerate(zip(photos, images)):
            box = (round(_num(spec['width'], 'photo width', 1)), round(_num(spec['height'], 'photo height', 1)))
            attached = [(mark, _source(mark['file'])) for mark in spec.get('artwork', [])]
            sources.extend(path for _, path in attached)
            panel, center = _panel(image, spec, box, attached)
            layers.append((panel, spec, center, f'photo{pi}'))
        for ai, spec in enumerate(comp.get('artwork', [])):
            path = _source(spec['file']); sources.append(path); image = _load(path)
            box = (round(_num(spec['width'], 'art width', 1)), round(_num(spec['height'], 'art height', 1)))
            image = fit_image(image, box, spec.get('fit', 'contain'), spec.get('focus', [.5, .5]))
            layers.append((image, spec, (image.width/2, image.height/2), f'art{ai}'))
        for image, spec, center, name in layers:
            delay = round(_num(spec.get('delay', 0), 'delay', 0)*fps)
            n = round(_num(spec.get('duration', (count-delay)/fps), 'layer duration', 3/fps)*fps)
            if n+delay > count: raise ValueError('Photo layer exceeds composition')
            enter = round(_num(spec.get('entrance', .25), 'entrance', 1/fps)*fps)
            exitn = round(_num(spec.get('exit', .2), 'exit', 1/fps)*fps)
            if enter+exitn > n-1: raise ValueError('Photo layer needs established hold after arrivals')
            x = _num(spec.get('x', 0), 'x', 0); y = _num(spec.get('y', 0), 'y', 0)
            boxw = _num(spec.get('width', image.width), 'width', 1); boxh = _num(spec.get('height', image.height), 'height', 1)
            left = round(x+boxw/2-center[0]); top = round(y+boxh/2-center[1])
            slide = _num(spec.get('slide_px', 18), 'slide_px', 0, height)
            jitter = _num(spec.get('jitter_px', 0), 'jitter_px', 0, 2)
            if min(left-jitter, top-.101*slide-jitter) < 0 or left+image.width+jitter > width or top+image.height+slide+jitter > height:
                raise ValueError('Rotated photo/artwork or its movement exceeds canvas bounds')
            seed = spec.get('seed', len(pending))
            if not isinstance(seed, int) or isinstance(seed, bool): raise ValueError('seed must be integer')
            easing = spec.get('easing', 'smooth')
            if easing not in ('smooth', 'overshoot'): raise ValueError('Invalid photo easing')
            z = _num(spec.get('z', 0), 'z')
            key = hashlib.sha256(image.tobytes()+json.dumps([ci,name,spec],sort_keys=True).encode()).hexdigest()[:20]
            path = _safe(Path(out)/'photo_layers'/f'{ci:03}_{name}_{key}.png', sources)
            record = dict(path=str(path.absolute()), at=(start+delay)/fps, duration=n/fps,
                          start_frame=start+delay, frames=n, x=left, y=top, width=image.width, height=image.height,
                          entrance=enter/fps, exit=exitn/fps, slide_px=slide, jitter_px=jitter, seed=seed, easing=easing,
                          z=z, kind='photo_panel', note='Explicit source crop/placement; no automatic face or action clearance')
            if name.startswith('photo'):
                record.update(swing_degrees=spec.get('swing_degrees', 0),
                              attached_artwork_count=len(spec.get('artwork', [])))
            pending.append((image, path, record))
    manifest = _safe(Path(out)/'photo_layers'/'manifest.json', sources)
    for _, path, _ in pending:
        _safe(path, sources)
    for image, path, record in pending:
        path.parent.mkdir(parents=True, exist_ok=True); image.save(path)
    if pending: manifest.write_text(json.dumps([p[2] for p in pending], indent=2)+'\n')
    return [p[2] for p in sorted(pending, key=lambda item: item[2]['z'])]
