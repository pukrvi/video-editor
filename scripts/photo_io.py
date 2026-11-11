"""Read original photographs with a macOS fallback for HEIC and HEIF."""
from pathlib import Path
import subprocess
from tempfile import TemporaryDirectory

from PIL import Image, UnidentifiedImageError


HEIF_EXTENSIONS = {'.heic', '.heif'}
PHOTO_EXTENSIONS = {'.jpg', '.jpeg', '.png', *HEIF_EXTENSIONS}
HEIF_BRANDS = {b'heic', b'heix', b'hevc', b'hevx', b'heim', b'heis', b'hevm', b'hevs', b'mif1', b'msf1'}
SIPS = Path('/usr/bin/sips')


def open_photo(path):
    path = Path(path).resolve()
    try:
        return Image.open(path, formats=('JPEG', 'PNG'))
    except UnidentifiedImageError:
        if path.suffix.lower() not in HEIF_EXTENSIONS or not SIPS.is_file():
            raise
    with path.open('rb') as source:
        header = source.read(64)
    if header[4:8] != b'ftyp' or (header[8:12] not in HEIF_BRANDS
                                 and not any(header[i:i+4] in HEIF_BRANDS for i in range(16, len(header), 4))):
        raise ValueError(f'Expected a HEIF file: {path.name}')
    with TemporaryDirectory(prefix='video-editor-photo-') as folder:
        converted = Path(folder) / 'photo.png'
        try:
            result = subprocess.run([SIPS, '-s', 'format', 'png', path, '--out', converted],
                                    capture_output=True, text=True, timeout=90)
        except subprocess.TimeoutExpired as error:
            raise ValueError(f'HEIF decoding timed out: {path.name}') from error
        if result.returncode != 0 or not converted.is_file():
            raise ValueError(f'Could not decode HEIF photo: {path.name}')
        with Image.open(converted, formats=('PNG',)) as image:
            return image.copy()
