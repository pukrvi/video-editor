"""Frame-accurate transparent transition overlays for picture cuts.

A transition spans an even number of frames, centered on ``cut_frame``.
The generated clip is a connected overlay; it does not move or replace shots.
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
from pathlib import Path

import numpy as np

PRESETS = {'diagonal_sweep', 'light_leak'}


def _rgb(value, default):
    if value is None:
        value = default
    if not isinstance(value, str) or not re.fullmatch(r'#[0-9a-fA-F]{6}', value):
        raise ValueError('color must be a hex string such as #147C80')
    return np.array([int(value[i:i + 2], 16) for i in (1, 3, 5)], dtype=np.float32)


def _smoothstep(edge0, edge1, value):
    t = np.clip((value - edge0) / (edge1 - edge0), 0, 1)
    return t * t * (3 - 2 * t)


def render_transition(transition: dict, output_path: Path, fps=30, width=1080, height=1920, command_path='ffmpeg') -> dict:
    """Encode a ProRes 4444 alpha movie. Output is exactly duration_frames long.

    The first and final frames are transparent; the sweep is fully opaque on
    the cut frame. A light leak is an atmospheric pulse and does not hide a cut.
    """
    preset = transition.get('preset')
    if preset not in PRESETS:
        raise ValueError(f'Unknown transition preset: {preset!r}')
    count, cut = transition.get('duration_frames'), transition.get('cut_frame')
    if isinstance(count, bool) or not isinstance(count, int) or count < 4 or count % 2:
        raise ValueError('duration_frames must be an even integer of at least 4')
    if isinstance(cut, bool) or not isinstance(cut, int) or cut < count // 2:
        raise ValueError('cut_frame must leave room for the first half of the transition')
    if fps <= 0 or width <= 0 or height <= 0:
        raise ValueError('fps and dimensions must be positive')
    color = _rgb(transition.get('color'), '#137E80' if preset == 'diagonal_sweep' else '#FFB373')
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    partial = output_path.with_name(output_path.stem + '.partial.mov')
    if partial.exists():
        raise FileExistsError(f'Refusing to overwrite temporary file: {partial}')
    x = np.linspace(0, 1, width, dtype=np.float32)[None, :]
    y = np.linspace(0, 1, height, dtype=np.float32)[:, None]
    diagonal = (x + .30 * y) / 1.30
    rgba = np.empty((height, width, 4), dtype=np.uint8)
    args = [str(command_path), '-v', 'error', '-f', 'rawvideo', '-pix_fmt', 'rgba',
            '-s', f'{width}x{height}', '-r', str(fps), '-i', 'pipe:0',
            '-frames:v', str(count), '-an', '-c:v', 'prores_ks', '-profile:v', '4444',
            '-pix_fmt', 'yuva444p10le', '-alpha_bits', '16', '-qscale:v', '12',
            '-threads', '2', '-y', str(partial)]
    proc = subprocess.Popen(args, stdin=subprocess.PIPE, stderr=subprocess.PIPE)
    try:
        half = count // 2
        for i in range(count):
            # Piecewise interpolation puts the peak exactly on the cut frame,
            # with both endpoint frames transparent even for short transitions.
            phase = i / half if i <= half else (count - 1 - i) / (count - 1 - half)
            if preset == 'diagonal_sweep':
                center = -0.9 + 1.4 * (i / half) if i <= half else .5 + 1.4 * ((i - half) / (count - 1 - half))
                distance = np.abs(diagonal - center)
                alpha = 1 - _smoothstep(.65, .80, distance)
                # A narrow highlight travels with the leading diagonal edge.
                glint = np.exp(-((distance - .61) / .045) ** 2) * .20
                shading = np.clip(.90 + .10 * (1 - y) + glint, 0, 1.15)
                rgb = np.clip(color[None, None, :] * shading[:, :, None], 0, 255)
            else:
                envelope = np.sin(np.pi * .5 * phase) ** 2
                # A broad, moving glow, strongest at the edge and fading smoothly.
                cx = -.08 + .22 * (i / (count - 1))
                glow = np.exp(-(((x - cx) / .58) ** 2 + ((y - .26) / .95) ** 2) * 1.2)
                alpha = .55 * envelope * glow
                warm = np.clip(.80 + .20 * (1 - y) + np.zeros_like(x), 0, 1)
                rgb = color[None, None, :] * warm[:, :, None]
            rgba[:, :, :3] = rgb.astype(np.uint8)
            rgba[:, :, 3] = np.rint(np.clip(alpha, 0, 1) * 255).astype(np.uint8)
            proc.stdin.write(rgba.tobytes())
        proc.stdin.close()
        err = proc.stderr.read().decode(errors='replace')
        if proc.wait():
            raise RuntimeError('Transition encoding failed: ' + err)
        partial.replace(output_path)
    except BaseException:
        if proc.poll() is None:
            proc.kill()
        proc.wait()
        partial.unlink(missing_ok=True)
        raise
    return {'path': str(output_path), 'start_frame': cut - half, 'duration_frames': count,
            'cut_frame': cut, 'preset': preset}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--preset', choices=sorted(PRESETS), required=True)
    parser.add_argument('--cut-frame', type=int, required=True)
    parser.add_argument('--duration-frames', type=int, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--color')
    parser.add_argument('--fps', type=int, default=30)
    parser.add_argument('--width', type=int, default=1080)
    parser.add_argument('--height', type=int, default=1920)
    parser.add_argument('--ffmpeg', default='ffmpeg')
    a = parser.parse_args()
    print(json.dumps(render_transition(vars(a) | {'cut_frame': a.cut_frame, 'duration_frames': a.duration_frames},
                                       a.output, a.fps, a.width, a.height, a.ffmpeg), indent=2))
