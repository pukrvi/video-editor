"""Resolve trip media independently of the shared pipeline's location."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TRIP = ROOT.parent


def library_root(library=None):
    if not library:
        # The original Phuket catalogue uses paths relative to the album.
        return TRIP / 'Phuket' if (TRIP / 'Phuket' / 'RAW Videos').is_dir() else TRIP
    if library in ('.', '..') or Path(library).name != library:
        raise ValueError(f'Expected a sibling album name: {library!r}')
    album = TRIP / library
    if not album.is_dir():
        raise FileNotFoundError(album)
    return album


def catalog_dir(library=None):
    folder = ROOT / 'catalog'
    return folder / library if library else folder
