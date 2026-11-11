"""Asset-backed graphic layers, separate from spoken captions.

Explicit recipe graphics: asset (absolute), text, at, duration, x, y, width,
font_size, ink. Geometry is pixels; text_box is optional normalized x/y/w/h
within the alpha-trimmed artwork. Placement is an editorial decision; this
module does not infer face clearance. Input artwork and clean movies stay intact.
"""
import hashlib
import json
import math
import random
import shutil
import subprocess
from pathlib import Path

from PIL import Image, ImageColor, ImageDraw, ImageFont

FONT = '/System/Library/Fonts/Supplemental/Arial Bold.ttf'


def _number(value, name, minimum=0):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value < minimum:
        raise ValueError(f'{name} must be finite and >= {minimum}')
    return float(value)


def _geometry(recipe):
    width = _number(recipe['width'], 'width', 1)
    height = _number(recipe['height'], 'height', 1)
    fps = _number(recipe['fps'], 'fps', 1)
    if any(v != int(v) for v in (width, height, fps)):
        raise ValueError('width, height and fps must be integers')
    if 'blocks' in recipe:
        total_frames = sum(round((_number(b['out'], 'out') - _number(b['in'], 'in')) * fps) for b in recipe['blocks'])
        if any(b['out'] <= b['in'] for b in recipe['blocks']):
            raise ValueError('Invalid block duration')
    else:
        total_frames = round(_number(recipe['duration'], 'duration', 1 / fps) * fps)
    if total_frames <= 0:
        raise ValueError('Empty timeline')
    return int(width), int(height), int(fps), total_frames


def _wrap(text, draw, font, width):
    """Preserve explicit newlines; wrap at words, never silently truncate."""
    lines = []
    for paragraph in text.split('\n'):
        line = ''
        for word in paragraph.split():
            if draw.textbbox((0, 0), word, font=font)[2] > width:
                raise ValueError('Graphic text overflow: a word exceeds the text box')
            trial = f'{line} {word}'.strip()
            if line and draw.textbbox((0, 0), trial, font=font)[2] > width:
                lines.append(line)
                line = word
            else:
                line = trial
        lines.append(line)
    return '\n'.join(lines)


def _safe_output(path, sources=()):
    path = Path(path)
    for part in (path, *path.parents):
        system_alias = str(part) in ('/var', '/tmp') and str(part.resolve()) == '/private' + str(part)
        if part.is_symlink() and not system_alias:
            raise ValueError('Graphic output cannot use symlinks')
    if path.exists() and path.is_file():
        for source in sources:
            if path.samefile(source):
                raise ValueError('Graphic output aliases an input')
    return path


def _transition_window(recipe, spec, start, count, fps):
    if not spec.get('chapter_change'):
        raise ValueError('Sweep transitions require an authored chapter_change=true')
    if count < 4 or count > 24:
        raise ValueError('Sweep transition must last 4 to 24 frames')
    if spec.get('direction', 'left_to_right') not in ('left_to_right', 'right_to_left'):
        raise ValueError('Sweep direction must be left_to_right or right_to_left')
    cut = round(_number(spec['cut_at'], 'cut_at') * fps)
    segments = []
    for block in recipe.get('blocks', []):
        pictures = block.get('pictures')
        if not pictures:
            raise ValueError('Sweep validation requires authored picture cuts')
        block_frames = round((block['out'] - block['in']) * fps)
        spans = [round(_number(p['duration'], 'picture duration', 1 / fps) * fps) for p in pictures]
        if any(n <= 0 for n in spans) or sum(spans) != block_frames:
            raise ValueError('Picture spans disagree with block frame clock')
        segments.extend(spans)
    cursor = 0
    for left, right in zip(segments, segments[1:]):
        cursor += left
        if cursor == cut:
            if abs((start + (count - 1) / 2) - cut) > 1:
                raise ValueError('Sweep must be centered on its actual cut within one frame')
            if start < cut - left or start + count > cut + right:
                raise ValueError('Sweep lacks adjacent shot handles')
            return cut
    raise ValueError('Sweep cut_at does not identify an actual picture cut')


def prepare_graphics(recipe, out, protected_sources=()):
    """Validate every layer, then save RGBA PNG composites and a manifest.

    Returns list of dicts with path, asset, at/duration (frame rounded),
    start_frame, frames, x/y/width/height and entrance/exit/slide_px.
    No files are written if any layer fails validation.
    """
    if not recipe.get('graphics') and not recipe.get('transitions'):
        return []
    width, height, fps, total_frames = _geometry(recipe)
    pending = []
    _safe_output(Path(out) / 'graphics')
    specs = list(recipe.get('graphics', [])) + [dict(t, motion='sweep') for t in recipe.get('transitions', [])]
    sources = list(protected_sources) + [Path(s["asset"]).expanduser() for s in specs] + [Path(s.get("font", FONT)) for s in specs]
    for index, spec in enumerate(specs):
        asset = Path(spec['asset']).expanduser()
        if not asset.is_absolute() or not asset.is_file():
            raise ValueError('Graphic asset must be an existing absolute path')
        if 'Personal Content' in asset.resolve().parts:
            raise ValueError('Personal Content assets are excluded')
        start = round(_number(spec['at'], 'at') * fps)
        count = round(_number(spec['duration'], 'duration', 1 / fps) * fps)
        if count < 3 or start + count > total_frames:
            raise ValueError('Graphic time outside timeline or too short for transparent endpoints')
        motion = spec.get('motion', 'overlay')
        if motion not in ('overlay', 'sweep'):
            raise ValueError('Graphic motion must be overlay or sweep')
        cut = _transition_window(recipe, spec, start, count, fps) if motion == 'sweep' else None
        x = 0 if motion == 'sweep' else _number(spec['x'], 'x')
        y = _number(spec['y'], 'y')
        target_width = round(_number(spec['width'], 'graphic width', 1))
        size = _number(spec.get('font_size', 40) if motion == 'sweep' else spec['font_size'], 'font_size', 1)
        if size != int(size):
            raise ValueError('font_size must be an integer')
        text = spec.get('text', '') if motion == 'sweep' else spec['text']
        if not isinstance(text, str):
            raise ValueError('Graphic text must be a string')
        ink = ImageColor.getcolor(spec.get('ink', '#181818') if motion == 'sweep' else spec['ink'], 'RGBA')
        with Image.open(asset, formats=['PNG', 'JPEG', 'WEBP', 'GIF', 'TIFF', 'BMP', 'AVIF']) as original:
            art = original.convert('RGBA')
        bounds = art.getchannel('A').getbbox()
        if bounds is None:
            raise ValueError('Graphic asset is fully transparent')
        art = art.crop(bounds)  # Alpha alone defines the crop: preserve all artwork.
        target_height = max(1, round(art.height * target_width / art.width))
        art = art.resize((target_width, target_height), Image.Resampling.LANCZOS)
        slide = 0 if motion == 'sweep' else _number(spec.get('slide_px', 18), 'slide_px')
        jitter, seed, easing = _motion_options(spec)
        if motion == 'sweep' and jitter:
            raise ValueError('Sweep transitions cannot jitter')
        if ((motion != 'sweep' and (x < jitter or x + target_width + jitter > width)) or
                y < jitter + (slide * .101 if easing == 'overshoot' else 0) or
                y + target_height + slide + jitter > height):
            raise ValueError('Graphic or its animation exceeds the frame bounds')
        box = spec.get('text_box', [.16, .22, .68, .56])
        if not isinstance(box, (list, tuple)) or len(box) != 4:
            raise ValueError('text_box must be normalized [x,y,width,height]')
        left, top, bw, bh = [_number(v, 'text_box') for v in box]
        if bw <= 0 or bh <= 0 or left + bw > 1 or top + bh > 1:
            raise ValueError('text_box outside artwork bounds')
        rect = (round(left * target_width), round(top * target_height),
                round(bw * target_width), round(bh * target_height))
        font = ImageFont.truetype(str(spec.get('font', FONT)), int(size))
        draw = ImageDraw.Draw(art)
        spacing = max(1, round(size * .14))
        wrapped = _wrap(text, draw, font, rect[2])
        bbox = draw.multiline_textbbox((0, 0), wrapped, font=font, spacing=spacing, align='center')
        tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
        if tw > rect[2] or th > rect[3]:
            raise ValueError('Graphic text overflow: reduce font_size, shorten text or enlarge text_box')
        if text:
            draw.multiline_text((rect[0] + (rect[2] - tw) / 2 - bbox[0],
                                 rect[1] + (rect[3] - th) / 2 - bbox[1]),
                                wrapped, font=font, fill=ink, spacing=spacing, align='center')
        entrance = 1 if motion == 'sweep' else round(_number(spec.get('entrance', .23), 'entrance', 1 / fps) * fps)
        exit_frames = 1 if motion == 'sweep' else round(_number(spec.get('exit', .20), 'exit', 1 / fps) * fps)
        if entrance + exit_frames > count - 1:
            raise ValueError('Graphic animation leaves no hold interval')
        key = hashlib.sha256(b'vlog-graphics-2' + asset.read_bytes() + json.dumps(spec, sort_keys=True).encode() +
                             repr((width, height, fps, bounds)).encode() + Path(spec.get('font', FONT)).read_bytes()).hexdigest()[:20]
        target = _safe_output(Path(out) / 'graphics' / f'{index:03d}_{key}.png', sources)
        record = dict(path=str(target.absolute()), asset=str(asset.resolve()), at=start / fps,
                      duration=count / fps, start_frame=start, frames=count, x=x, y=y,
                      width=target_width, height=target_height, entrance=entrance / fps,
                      exit=exit_frames / fps, slide_px=slide, alpha_crop=list(bounds),
                      text=wrapped, text_box=list(box), motion=motion, cut_frame=cut,
                      direction=spec.get('direction', 'left_to_right'), canvas_width=width, jitter_px=jitter, seed=seed, easing=easing, z=_number(spec.get('z', 0), 'z', -1000000))
        pending.append((art, target, record))
    manifest = _safe_output(Path(out) / 'graphics' / 'manifest.json', sources)
    for art, target, _ in pending:
        target.parent.mkdir(parents=True, exist_ok=True)
        _safe_output(target, sources)
        art.save(target)
    _safe_output(manifest, sources)
    manifest.write_text(json.dumps([r for _, _, r in pending], indent=2) + '\n')
    return [r for _, _, r in pending]


def _motion_options(spec):
    jitter = _number(spec.get('jitter_px', 0), 'jitter_px')
    if jitter > 2:
        raise ValueError('jitter_px must be <=2 to avoid distracting flicker')
    seed = spec.get('seed', 0)
    if isinstance(seed, bool) or not isinstance(seed, int):
        raise ValueError('seed must be an integer')
    easing = spec.get('easing', 'smooth')
    if easing not in ('smooth', 'overshoot'):
        raise ValueError('easing must be smooth or overshoot')
    return jitter, seed, easing


def normalize_prepared_layers(recipe, layers):
    """Validate external precomposited PNGs without alpha trimming/resampling.

    Core fields path,at,duration,x,y. Native PNG dimensions supply width/height;
    optional frame fields must agree. z controls back-to-front ordering.
    """
    width, height, fps, total_frames = _geometry(recipe)
    result = []
    for spec in layers or []:
        path = Path(spec['path'])
        if not path.is_absolute() or not path.is_file():
            raise ValueError('Prepared layer needs an absolute PNG path')
        if 'Personal Content' in path.resolve().parts:
            raise ValueError('Personal Content layers are excluded')
        with Image.open(path, formats=['PNG']) as art:
            if art.mode != 'RGBA':
                raise ValueError('Prepared layer must be an RGBA PNG')
            w, h = art.size
        start = round(_number(spec['at'], 'at') * fps)
        count = round(_number(spec['duration'], 'duration', 1 / fps) * fps)
        if count < 3 or start + count > total_frames:
            raise ValueError('Prepared layer time outside timeline')
        for key, expected in [('start_frame', start), ('frames', count), ('width', w), ('height', h)]:
            if key in spec and spec[key] != expected:
                raise ValueError(f'Prepared layer {key} disagrees with native geometry or frame clock')
        x, y = _number(spec['x'], 'x'), _number(spec['y'], 'y')
        slide = _number(spec.get('slide_px', 18), 'slide_px')
        jitter, seed, easing = _motion_options(spec)
        swing = _number(spec.get('swing_degrees', 0), 'swing_degrees')
        if swing > 6:
            raise ValueError('swing_degrees must be <=6')
        if swing:
            with Image.open(path, formats=['PNG']) as art:
                bounds = art.getchannel('A').getbbox()
            if bounds is None:
                raise ValueError('A swinging layer must have visible artwork')
            rx = max(w/2-bounds[0], bounds[2]-w/2)
            ry = max(h/2-bounds[1], bounds[3]-h/2)
            turn = math.sin(math.radians(swing))
            if rx+ry*turn+1>w/2 or ry+rx*turn+1>h/2:
                raise ValueError('Swing exceeds the prepared sprite padding')
        if (x < jitter or x + w + jitter > width or
                y < jitter + (slide * .101 if easing == 'overshoot' else 0) or
                y + h + slide + jitter > height):
            raise ValueError('Prepared layer or animation exceeds frame bounds')
        entrance = round(_number(spec.get('entrance', .23), 'entrance', 1 / fps) * fps)
        exit_frames = round(_number(spec.get('exit', .20), 'exit', 1 / fps) * fps)
        if entrance + exit_frames > count - 1:
            raise ValueError('Prepared layer animation leaves no hold interval')
        result.append(dict(spec, path=str(path), at=start / fps, duration=count / fps,
                           start_frame=start, frames=count, width=w, height=h, x=x, y=y,
                           slide_px=slide, jitter_px=jitter, seed=seed, easing=easing,
                           entrance=entrance / fps, exit=exit_frames / fps, z=_number(spec.get('z', 0), 'z', -1000000)))
    return result


def graphics_filter(layers, fps):
    """Filter graph for base input 0 and looped PNG inputs 1..N.

    First and last visible overlay frames have zero alpha. Seeded sine motion
    is smooth, bounded, reproducible and optional, never random frame flicker.
    """
    parts = ['[0:v]setpts=PTS-STARTPTS,format=yuv420p[base0]']
    for i, g in enumerate(layers):
        end = g['at'] + g['duration']
        fade_out = g['duration'] - 1 / fps - g['exit']
        phase = random.Random(g.get('seed', 0)).uniform(0, 2 * math.pi)
        swing = g.get('swing_degrees', 0)
        rotation = (f"rotate='{math.radians(swing)}*sin(2*PI*.67*t+{phase})':fillcolor=none,"
                    if swing else '')
        parts.append(f"[{i+1}:v]format=rgba,trim=end_frame={g['frames']},setpts=N/({fps}*TB),"
                     +rotation+
                     f"fade=t=in:st=0:d={g['entrance']:.9f}:alpha=1,"
                     f"fade=t=out:st={fade_out:.9f}:d={g['exit']:.9f}:alpha=1,"
                     f"setpts=PTS+{g['at']:.9f}/TB[layer{i}]")
        u = f"min(1,max(0,(t-{g['at']})/{g['entrance']}))"
        v = f"min(1,max(0,(t-({end-1/fps-g['exit']}))/{g['exit']}))"
        enter = (f"(-2.70158*pow(({u})-1,3)-1.70158*pow(({u})-1,2))"
                 if g.get('easing') == 'overshoot' else f"(1-pow({u},2)*(3-2*({u})))")
        leave = f"(pow({v},2)*(3-2*({v})))"
        amplitude = g.get('jitter_px', 0)
        jx = f"{amplitude}*(.6*sin(2*PI*.73*(t-{g['at']})+{phase})+.4*sin(2*PI*1.3*(t-{g['at']})+{phase}))"
        jy = f"{amplitude}*(.6*sin(2*PI*.61*(t-{g['at']})+{phase})+.4*sin(2*PI*1.1*(t-{g['at']})+{phase}))"
        motion = f"{g['y']}+{g['slide_px']}*({enter}+{leave})+({jy})"
        horizontal = f"{g['x']}+({jx})"
        if g.get('motion') == 'sweep':
            progress = f"min(1,max(0,(t-{g['at']})/({g['duration']-1/fps})))"
            eased = f"pow({progress},2)*(3-2*({progress}))"
            travel = g['canvas_width'] + g['width']
            horizontal = (f"-{g['width']}+{travel}*({eased})" if g['direction'] == 'left_to_right'
                          else f"{g['canvas_width']}-{travel}*({eased})")
            motion = str(g['y'])
        parts.append(f"[base{i}][layer{i}]overlay=x='{horizontal}':y='{motion}':"
                     f"enable='gte(t,{g['at']})*lt(t,{end})':eof_action=pass:repeatlast=0"
                     f"[base{i+1}]")
    parts.append(f'[base{len(layers)}]format=yuv420p[vout]')
    return ';\n'.join(parts)


def apply_graphics(clean_movie, recipe, out, prepared_layers=None):
    """Create a new graphics_movie.mp4; retain source audio without remixing.

    Empty graphics returns clean_movie without re-encoding. FFmpeg uses the
    binary on PATH, with the local Homebrew build as a fallback.
    """
    clean_movie = Path(clean_movie).resolve()
    if not recipe.get('graphics') and not recipe.get('transitions') and not prepared_layers:
        return clean_movie
    width, height, fps, total_frames = _geometry(recipe)
    from pipeline import ffmpeg_binary
    ffmpeg = ffmpeg_binary()
    ffprobe = str(Path(ffmpeg).with_name('ffprobe'))
    if not Path(ffprobe).is_file():
        ffprobe = shutil.which('ffprobe')
    info = json.loads(subprocess.check_output([ffprobe, '-v', 'error', '-protocol_whitelist', 'file', '-select_streams', 'v:0',
                      '-show_streams', '-of', 'json', str(clean_movie)]))['streams'][0]
    rate = info.get('avg_frame_rate', '0/1').split('/')
    if (info['width'], info['height']) != (width, height) or abs(int(rate[0]) / int(rate[1]) - fps) > .001:
        raise ValueError('Clean movie geometry/frame rate does not match recipe')
    if int(info.get('nb_frames', -1)) != total_frames:
        raise ValueError('Clean movie frame count does not match recipe')
    external = normalize_prepared_layers(recipe, prepared_layers)
    sources = [clean_movie] + [Path(s['asset']) for s in list(recipe.get('graphics', [])) + list(recipe.get('transitions', []))] + [Path(s['path']) for s in external]
    dst = _safe_output(Path(out) / 'graphics_movie.mp4', sources)
    graph = _safe_output(Path(out) / 'graphics.ffgraph', sources)
    layers = prepare_graphics(recipe, out, protected_sources=sources) + external
    layers.sort(key=lambda layer: _number(layer.get('z', 0), 'z', -1000000))
    Path(out).mkdir(parents=True, exist_ok=True)
    graph.write_text(graphics_filter(layers, fps))
    args = [str(ffmpeg), '-v', 'error', '-y', '-filter_complex_threads', '1', '-protocol_whitelist', 'file', '-i', str(clean_movie)]
    for layer in layers:
        args.extend(['-loop', '1', '-framerate', str(fps), '-protocol_whitelist', 'file', '-i', layer['path']])
    args.extend(['-filter_complex', graph.read_text(), '-map', '[vout]', '-map', '0:a?',
                 '-frames:v', str(total_frames), '-c:v', 'libx264', '-crf', '17', '-preset', 'fast',
                 '-c:a', 'copy', '-movflags', '+faststart', str(dst)])
    subprocess.run(args, check=True)
    return dst
