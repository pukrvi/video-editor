"""Bounds, text-fit and frame-clock contracts for artwork-backed layers."""
import copy
from pathlib import Path
import sys
import tempfile
import unittest

from PIL import Image
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from vlog_graphics import prepare_graphics, graphics_filter, normalize_prepared_layers, FONT


class GraphicsTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.asset = self.root / 'art.png'
        im = Image.new('RGBA', (400, 200))
        im.paste((255, 220, 50, 255), (20, 40, 380, 160))
        im.save(self.asset)
        self.recipe = dict(width=720, height=1280, fps=30, duration=3, graphics=[dict(
            asset=str(self.asset), text='Trail day', at=.3, duration=1.5,
            x=100, y=200, width=500, font_size=30, ink='#151515', font=FONT)])

    def tearDown(self):
        self.temp.cleanup()

    def test_alpha_crop_keeps_art_aspect_and_transparency(self):
        layers = prepare_graphics(self.recipe, self.root / 'out')
        layer = layers[0]
        self.assertEqual(layer['alpha_crop'], [20, 40, 380, 160])
        self.assertEqual((layer['width'], layer['height']), (500, 167))
        with Image.open(layer['path']) as im:
            self.assertEqual(im.mode, 'RGBA')
        with Image.open(self.asset) as im:
            self.assertEqual(im.size, (400, 200))
        graph = graphics_filter(layers, 30)
        self.assertIn('alpha=1', graph)
        self.assertIn('eof_action=pass:repeatlast=0', graph)
        self.assertIn('trim=end_frame=45', graph)

    def test_offscreen_including_animation_rejected_before_write(self):
        for field, value in [('x', 300), ('y', 1100), ('width', -2)]:
            with self.subTest(field=field):
                r = copy.deepcopy(self.recipe)
                r['graphics'][0][field] = value
                with self.assertRaises(ValueError):
                    prepare_graphics(r, self.root / 'bad')
                self.assertFalse((self.root / 'bad').exists())

    def test_text_overflow_word_and_multiline(self):
        for text in ['W' * 80, '\n'.join(['Trail day'] * 12)]:
            r = copy.deepcopy(self.recipe)
            r['graphics'][0]['text'] = text
            with self.assertRaisesRegex(ValueError, 'text overflow'):
                prepare_graphics(r, self.root / 'bad')

    def test_time_outside_timeline_nan_and_no_hold(self):
        for changes in [dict(at=2), dict(at=-1), dict(at=float('nan')),
                        dict(duration=.01), dict(duration=.3), dict(entrance=3)]:
            with self.subTest(changes=changes):
                r = copy.deepcopy(self.recipe)
                r['graphics'][0].update(changes)
                with self.assertRaises(ValueError):
                    prepare_graphics(r, self.root / 'bad')

    def test_invalid_text_box_and_missing_explicit_position(self):
        r = copy.deepcopy(self.recipe)
        r['graphics'][0]['text_box'] = [.9, .1, .3, .5]
        with self.assertRaises(ValueError):
            prepare_graphics(r, self.root / 'bad')
        r = copy.deepcopy(self.recipe)
        del r['graphics'][0]['x']
        with self.assertRaises(KeyError):
            prepare_graphics(r, self.root / 'bad')

    def test_external_png_keeps_transparent_padding_and_rejects_bad_clock(self):
        spec = dict(path=str(self.asset), at=.3, duration=1.5, x=100, y=200,
                    start_frame=9, frames=45, width=400, height=200, slide_px=0)
        layer = normalize_prepared_layers(self.recipe, [spec])[0]
        self.assertEqual((layer['width'], layer['height']), (400, 200))
        spec['frames'] = 44
        with self.assertRaisesRegex(ValueError, 'frame clock'):
            normalize_prepared_layers(self.recipe, [spec])

    def test_jitter_is_bounded_and_seed_reproducible(self):
        self.recipe['graphics'][0].update(jitter_px=1.2, seed=426, easing='overshoot')
        layers = prepare_graphics(self.recipe, self.root / 'good')
        graph = graphics_filter(layers, 30)
        self.assertEqual(graph, graphics_filter(layers, 30))
        layers[0]['seed'] = 427
        self.assertNotEqual(graph, graphics_filter(layers, 30))
        self.recipe['graphics'][0]['jitter_px'] = 2.1
        with self.assertRaisesRegex(ValueError, '<=2'):
            prepare_graphics(self.recipe, self.root / 'bad')
        self.recipe['graphics'][0].update(jitter_px=1, y=1)
        with self.assertRaisesRegex(ValueError, 'frame bounds'):
            prepare_graphics(self.recipe, self.root / 'bad')

    def _sweep_recipe(self):
        r = copy.deepcopy(self.recipe)
        r['graphics'] = []
        r['blocks'] = [{'in': 0, 'out': 1, 'pictures': [{'duration': 1}]},
                       {'in': 0, 'out': 2, 'pictures': [{'duration': 2}]}]
        r['transitions'] = [dict(asset=str(self.asset), at=.7, duration=.6,
                                 cut_at=1, chapter_change=True, width=500, y=300)]
        return r

    def test_sweep_crosses_only_authored_cut_with_handles(self):
        r = self._sweep_recipe()
        layers = prepare_graphics(r, self.root / 'sweep')
        self.assertEqual(layers[0]['motion'], 'sweep')
        self.assertEqual(layers[0]['cut_frame'], 30)
        self.assertEqual(layers[0]['entrance'], 1 / 30)
        graph = graphics_filter(layers, 30)
        self.assertIn("overlay=x='-500+1220*", graph)
        for update in [dict(duration=.1), dict(duration=.9), dict(cut_at=.9),
                       dict(chapter_change=False), dict(at=.1), dict(direction='down')]:
            with self.subTest(update=update):
                bad = self._sweep_recipe()
                bad['transitions'][0].update(update)
                with self.assertRaises(ValueError):
                    prepare_graphics(bad, self.root / 'bad')
        bad = self._sweep_recipe()
        bad['blocks'][0]['pictures'] = [{'duration': 28 / 30}, {'duration': 2 / 30}]
        with self.assertRaisesRegex(ValueError, 'handles'):
            prepare_graphics(bad, self.root / 'bad')

    def test_reject_output_alias_and_personal_content(self):
        folder = self.root / 'out' / 'graphics'
        folder.mkdir(parents=True)
        (folder / 'manifest.json').symlink_to(self.asset)
        with self.assertRaisesRegex(ValueError, 'symlinks'):
            prepare_graphics(self.recipe, self.root / 'out')
        personal = self.root / 'Personal Content'
        personal.mkdir()
        import shutil
        shutil.copy(self.asset, personal / 'art.png')
        self.recipe['graphics'][0]['asset'] = str(personal / 'art.png')
        with self.assertRaisesRegex(ValueError, 'excluded'):
            prepare_graphics(self.recipe, self.root / 'another')


if __name__ == '__main__':
    unittest.main()
