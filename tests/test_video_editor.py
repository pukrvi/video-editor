import json
from pathlib import Path
import shutil
import subprocess
import sys
from tempfile import TemporaryDirectory
import unittest


ROOT = Path(__file__).resolve().parents[1]


class VideoEditorTest(unittest.TestCase):
    def setUp(self):
        temporary = TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        workspace = Path(temporary.name).resolve()
        self.checkout = workspace / 'editor'
        self.checkout.mkdir()
        self.album = workspace / 'Test album'
        self.album.mkdir()
        for folder in ('examples', 'templates'):
            shutil.copytree(ROOT / folder, self.checkout / folder)
        shutil.copy2(ROOT / 'video-editor', self.checkout / 'video-editor')
        scripts = self.checkout / 'scripts'
        scripts.mkdir()
        for name in ('media_library.py', 'pipeline_paths.py'):
            shutil.copy2(ROOT / 'scripts' / name, scripts / name)
        for name in ('pipeline.py', 'build_review.py'):
            (scripts / name).write_text('import json, sys\nprint(json.dumps(sys.argv))\n')

    def invoke(self, *args, check=True):
        return subprocess.run([sys.executable, self.checkout / 'video-editor', *args],
                              cwd=self.album, text=True, capture_output=True, check=check)

    def create(self, profile):
        result = self.invoke(profile, 'init', '--album', self.album, '--slug', profile, '--name', 'Test title')
        return tuple(map(Path, result.stdout.splitlines()))

    def test_all_profiles_initialize_and_route(self):
        profiles = {
            'personal-reel': ('music_reel', (1080, 1920), None),
            'personal-vlog': ('narrated_vlog', (1080, 1920), 'avenir_highlight'),
            'commercial-youtube': ('narrated_vlog', (1920, 1080), 'legacy'),
        }
        for profile, (mode, geometry, captions) in profiles.items():
            with self.subTest(profile=profile):
                self.assertEqual(self.invoke(profile, '--help').returncode, 0)
                recipe_path, brief_path = self.create(profile)
                self.assertEqual(recipe_path, self.checkout/'config'/profile/'v01'/'recipe.json')
                self.assertTrue(brief_path.is_file())
                recipe = json.loads(recipe_path.read_text())
                self.assertEqual(recipe['workflow'], profile)
                if profile=='personal-vlog': self.assertTrue(recipe['editorial_required'])
                self.assertEqual(recipe['mode'], mode)
                self.assertEqual((recipe['width'], recipe['height']), geometry)
                self.assertEqual(recipe['output_dir'], str((self.checkout/'exports'/profile/'v01').resolve()))
                if mode == 'music_reel':
                    self.assertEqual(recipe['media_library'], self.album.name)
                    self.assertTrue((self.checkout/recipe['public_review']).is_file())
                else:
                    self.assertEqual(recipe['blocks'], [])
                    self.assertEqual(recipe['captions']['preset'], captions)
                    self.assertNotIn('music_bed', recipe)
                for operation in ('render', 'qa'):
                    lines = self.invoke(profile, operation, '--recipe', recipe_path).stdout.splitlines()
                    dispatch = [json.loads(line) for line in lines]
                    self.assertEqual(dispatch[0][1:], [operation, '--recipe', str(recipe_path.resolve())])
                    self.assertEqual(len(dispatch), 2 if operation == 'qa' and mode == 'music_reel' else 1)
                    if len(dispatch) == 2:
                        self.assertEqual(dispatch[1][1:], ['--recipe', str(recipe_path.resolve()), '--local-only'])

    def test_revisions_keep_the_prior_edit_and_remove_its_export_approval(self):
        original_path, brief_path = self.create('personal-reel')
        recipe = json.loads(original_path.read_text())
        recipe.update(finalcut_review_report='old-report.json', finalcut_user_confirmation={'confirmed': True})
        original_path.write_text(json.dumps(recipe))
        brief_path.write_text('Keep the original brief.\n')
        review_path = self.checkout/recipe['public_review']
        review_path.write_text(json.dumps({'approved_windows': {'S01': 'screened'}}))
        result = self.invoke('personal-reel', 'revise', '--recipe', original_path, '--version', 'v02')
        copy_path, copy_brief = map(Path, result.stdout.splitlines())
        revision = json.loads(copy_path.read_text())
        self.assertEqual(copy_brief.read_text(), brief_path.read_text())
        self.assertEqual(revision['version'], 'v02')
        self.assertNotEqual(revision['output_dir'], recipe['output_dir'])
        self.assertNotEqual(revision['public_review'], recipe['public_review'])
        self.assertEqual((self.checkout/revision['public_review']).read_text(), review_path.read_text())
        self.assertFalse(revision['finalcut_export'])
        self.assertNotIn('finalcut_review_report', revision)
        self.assertNotIn('finalcut_user_confirmation', revision)
        self.assertEqual(json.loads(original_path.read_text()), recipe)
        duplicate = self.invoke('personal-reel', 'revise', '--recipe', original_path,
                                '--version', 'v02', check=False)
        self.assertNotEqual(duplicate.returncode, 0)
        self.assertEqual(json.loads(copy_path.read_text()), revision)

    def test_declared_narrated_profiles_cannot_cross_dispatch(self):
        commercial, _ = self.create('commercial-youtube')
        result = self.invoke('personal-vlog', 'render', '--recipe', commercial, check=False)
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(result.stdout, '')
