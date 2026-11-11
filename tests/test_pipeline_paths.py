"""Check mode defaults and original-source protection with assertions disabled."""
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

SCRIPTS = Path(__file__).resolve().parents[1] / 'scripts'
sys.path.insert(0, str(SCRIPTS))
from pipeline_paths import guard_output_tree, movie_path, recipe_mode, timeline_path


class PipelinePathTests(unittest.TestCase):
    def test_modes_and_paths_resolve_without_perspective(self):
        reel = {'version': 'v01', 'shots': [], 'output_dir': 'exports/custom'}
        root = Path('/pipeline')
        self.assertEqual(movie_path(reel, root), root/'exports/custom/Reel_v01_1080x1920.mp4')
        vlog = {'version': 'v02', 'mode': 'narrated_vlog', 'blocks': [],
                'project_slug': 'Sample', 'width': 360, 'height': 640}
        movie = movie_path(vlog, root)
        self.assertEqual(movie, root/'exports/v02/Sample_v02_360x640.mp4')
        self.assertEqual(timeline_path(vlog, movie), root/'exports/v02/Sample_v02.fcpxml')
        with self.assertRaisesRegex(ValueError, 'Recipe mode'):
            recipe_mode({**vlog, 'mode': 'music_reel'})
        with self.assertRaisesRegex(ValueError, 'Unsafe'):
            movie_path({**reel, 'version': '../v01'}, root)

    def test_output_rejects_nested_source_and_aliases_even_under_optimization(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            album = base/'Album'
            source = album/'nested'/'original.wav'
            source.parent.mkdir(parents=True)
            source.write_bytes(b'dry source')
            output = album/'Edit_Workspace'/'v01'
            output.mkdir(parents=True)
            (output/'layers').symlink_to(source.parent, target_is_directory=True)
            with self.assertRaisesRegex(ValueError, 'symlink'):
                guard_output_tree(output, (source,), album=album, writable=('layers/result.wav',))
            with self.assertRaisesRegex(ValueError, 'contain or replace'):
                guard_output_tree(album, (source,), album=album)
            with self.assertRaisesRegex(ValueError, 'inside the output'):
                guard_output_tree(output, (output/'nested/input.wav',), album=album)
            target = output/'processed.wav'
            target.hardlink_to(source)
            result = subprocess.run([sys.executable, '-O', '-c',
                                     'import sys; sys.path.insert(0, sys.argv[1]); '
                                     'from pipeline_paths import guard_output_tree; '
                                     'guard_output_tree(sys.argv[2], (sys.argv[3],), writable=("processed.wav",))',
                                     str(SCRIPTS), str(output), str(source)], capture_output=True, text=True)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn('without hardlinks', result.stderr)
            self.assertEqual(source.read_bytes(), b'dry source')


if __name__ == '__main__':
    unittest.main()
