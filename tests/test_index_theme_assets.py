import importlib.util
from pathlib import Path
import tempfile
import unittest
from PIL import Image

spec = importlib.util.spec_from_file_location('index_theme_assets', Path(__file__).resolve().parents[1]/'scripts/index_theme_assets.py')
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class AlphaBoundsTests(unittest.TestCase):
    def inspect(self, image):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)/'asset.png'
            image.save(path)
            return module.inspect_image(path)

    def test_fully_opaque_rgb_uses_whole_canvas(self):
        result = self.inspect(Image.new('RGB', (8, 4), 'white'))
        self.assertEqual(result['alpha_bounds'], [0, 0, 8, 4])
        self.assertTrue(result['fully_opaque'])
        self.assertEqual(result['artwork_aspect'], 2)

    def test_fully_opaque_rgba_keeps_border_pixels(self):
        result = self.inspect(Image.new('RGBA', (7, 3), (20, 40, 60, 255)))
        self.assertEqual(result['alpha_bounds'], [0, 0, 7, 3])
        self.assertTrue(result['fully_opaque'])
        self.assertFalse(result['empty_alpha'])

    def test_empty_alpha_has_no_artwork(self):
        result = self.inspect(Image.new('RGBA', (8, 4), (120, 10, 20, 0)))
        self.assertIsNone(result['alpha_bounds'])
        self.assertIsNone(result['artwork_aspect'])
        self.assertTrue(result['empty_alpha'])

    def test_faint_edge_is_preserved(self):
        image = Image.new('RGBA', (8, 6))
        image.putpixel((2, 1), (255, 255, 255, 1))
        image.putpixel((5, 4), (0, 0, 0, 255))
        result = self.inspect(image)
        self.assertEqual(result['alpha_bounds'], [2, 1, 6, 5])
        self.assertEqual(result['artwork_aspect'], 1)

    def test_private_and_nested_directories_are_never_scanned(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for name in ('Cards', 'Personal Content', 'Cards/nested'):
                (root/name).mkdir(parents=True, exist_ok=True)
                Image.new('RGB', (2, 2)).save(root/name/'test.png')
            result = module.index_assets(root, ['Cards'])
            self.assertEqual(len(result['assets']), 1)
            with self.assertRaises(ValueError):
                module.index_assets(root, ['Personal Content'])


if __name__ == '__main__':
    unittest.main()
