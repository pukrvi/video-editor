"""Resolve the two recipe formats and guard generated output paths."""
import re
import stat
from pathlib import Path

from media_library import ROOT


def safe_component(value, name):
    if not isinstance(value, str) or not re.fullmatch(r'[A-Za-z0-9_-]+', value):
        raise ValueError(f'Unsafe {name}: expected letters, digits, underscores or hyphens')
    return value


def recipe_mode(recipe):
    if ('blocks' in recipe) == ('shots' in recipe):
        raise ValueError('Recipe must contain exactly one of blocks or shots')
    inferred = 'narrated_vlog' if 'blocks' in recipe else 'music_reel'
    if recipe.get('mode', inferred) != inferred:
        raise ValueError('Recipe mode must match its blocks (narrated_vlog) or shots (music_reel)')
    return inferred


def movie_path(recipe, root=ROOT):
    mode = recipe_mode(recipe)
    version = safe_component(recipe['version'], 'version')
    slug = recipe.get('project_slug')
    if not slug:
        perspective = recipe.get('perspective')
        slug = f'Phuket_{perspective}' if perspective else 'Vlog' if mode == 'narrated_vlog' else 'Reel'
    safe_component(slug, 'project_slug')
    width, height = (recipe.get(key, default) for key, default in (('width', 1080), ('height', 1920)))
    if any(type(value) is not int or value <= 0 for value in (width, height)):
        raise ValueError('Movie width and height must be positive integers')
    output_dir = recipe.get('output_dir')
    if output_dir:
        out = Path(output_dir).absolute() if mode == 'narrated_vlog' else Path(root) / output_dir
    else:
        out = Path(root) / 'exports' / version
    return out / f'{slug}_{version}_{width}x{height}.mp4'


def timeline_path(recipe, movie=None):
    if movie is None:
        movie = movie_path(recipe)
    suffix = f"_{recipe.get('width', 1080)}x{recipe.get('height', 1920)}.mp4"
    if not movie.name.endswith(suffix):
        raise ValueError('Final Cut output must use the matching movie geometry')
    return movie.with_name(movie.name.removesuffix(suffix) + '.fcpxml')


def _reject_symlink(path):
    if path.is_symlink():
        system_alias = str(path) in ('/var', '/tmp') and str(path.resolve()) == '/private' + str(path)
        if not system_alias:
            raise ValueError(f'Generated output cannot use a symlink: {path}')


def guard_output_tree(output_dir, inputs=(), *, album=None, writable=()):
    """Check existing destinations before writing, leaving unrelated output siblings alone."""
    original_path = Path(output_dir).absolute()
    for part in (original_path, *original_path.parents):
        _reject_symlink(part)
    out = original_path.resolve()
    if out.exists() and not out.is_dir():
        raise ValueError(f'Output must be a directory: {out}')
    if album is not None:
        album = Path(album).resolve()
        if album.is_relative_to(out):
            raise ValueError('Output cannot contain or replace the source album')
        if out.is_relative_to(album) and not out.is_relative_to(album / 'Edit_Workspace'):
            raise ValueError('Inside an album, outputs belong under Edit_Workspace')
    if any(Path(source).resolve().is_relative_to(out) for source in inputs):
        raise ValueError('An input is inside the output directory')

    for name in writable:
        relative = Path(name)
        if relative.is_absolute() or not relative.parts or '..' in relative.parts:
            raise ValueError(f'Expected a relative generated output path: {name}')
        target = out / relative
        for parent in target.parents:
            if parent == out:
                break
            _reject_symlink(parent)
        for path in (target, *target.rglob('*')):
            _reject_symlink(path)
            try:
                info = path.lstat()
            except FileNotFoundError:
                continue
            if stat.S_ISDIR(info.st_mode):
                continue
            if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
                raise ValueError(f'Generated output must be a regular file without hardlinks: {path}')
    return out
