from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory
import unittest

from PIL import Image, ImageDraw, ImageOps

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from photo_io import SIPS, open_photo


class PhotoIoTests(unittest.TestCase):
    @unittest.skipUnless(SIPS.is_file(), 'macOS native image tools are required')
    def test_heic_pixels_and_exif_orientation_are_read_without_changing_source(self):
        with TemporaryDirectory() as temporary:
            folder = Path(temporary)
            jpeg = folder / 'asymmetric.jpg'
            heic = folder / 'asymmetric.heic'
            image = Image.new('RGB', (160, 80), 'blue')
            ImageDraw.Draw(image).rectangle((0, 0, 49, 79), fill='red')
            exif = Image.Exif()
            exif[274] = 6
            image.save(jpeg, exif=exif)
            subprocess.run([SIPS, '-s', 'format', 'heic', jpeg, '--out', heic],
                           capture_output=True, check=True)
            original = heic.read_bytes()
            with open_photo(heic) as decoded:
                self.assertEqual(decoded.getexif()[274], 6)
                corrected = ImageOps.exif_transpose(decoded)
                self.assertEqual(corrected.size, (80, 160))
                top = corrected.getpixel((5, 5))
                bottom = corrected.getpixel((5, 150))
                self.assertGreater(top[0], top[2])
                self.assertGreater(bottom[2], bottom[0])
            self.assertEqual(heic.read_bytes(), original)
