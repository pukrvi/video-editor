"""Exercise exact-movie Final Cut eligibility independently of final quality."""
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from finalcut_gate import require_finalcut_approval
from quality_gate import check_review


class ExportGateTests(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.root = Path(folder.name)
        self.movie = self.root/'fixture.mp4'
        self.movie.write_bytes(b'gate test fixture')
        self.digest = hashlib.sha256(self.movie.read_bytes()).hexdigest()
        self.request = {'movie_sha256': self.digest, 'request_id': 'fixture',
                        'version': 'v01', 'reviewer_model': 'gpt-6.1-sol', 'reasoning_effort': 'high'}
        (self.root/'director_review_request.json').write_text(json.dumps(self.request))
        self.report = {**self.request, 'independent_reviewer': True, 'score': 85,
                       'scores': {'story':18, 'shot_selection':17, 'pacing':12, 'motion_design':12,
                                  'transitions':9, 'composition_legibility':9, 'ending':8},
                       'strengths':['Synthetic fixture'], 'evidence':['Synthetic fixture'],
                       'limitations':['This is not a director assessment'], 'feedback':[]}
        self.report_path = self.root/'review.json'
        self.recipe = {'version': 'v01', 'director_review': {'reasoning_effort': 'high'},
                       'finalcut_review_report': str(self.report_path)}
        self.confirmation = {'confirmed': True, 'movie_sha256': self.digest, 'user_message': 'Synthetic test approval'}

    def eligible(self):
        self.report_path.write_text(json.dumps(self.report))
        return require_finalcut_approval(self.recipe, self.movie)

    def test_85_can_export_with_exact_confirmation_and_does_not_pass_final_quality(self):
        with self.assertRaisesRegex(ValueError, 'confirmation'):
            self.eligible()
        self.recipe['finalcut_user_confirmation'] = self.confirmation
        self.assertEqual(self.eligible()['score'], 85)
        with self.assertRaisesRegex(ValueError, 'Continue relevant revisions'):
            check_review(self.report, self.movie, self.request, recipe=self.recipe)
        self.movie.write_bytes(b'changed')
        with self.assertRaisesRegex(ValueError, 'different movie'):
            self.eligible()

    def test_threshold_effort_request_and_confirmation_bindings(self):
        self.recipe['finalcut_user_confirmation'] = self.confirmation
        cases = (
            ({'score': 84, 'scores': {**self.report['scores'], 'story': 17}}, 'at least 85'),
            ({'reasoning_effort': 'medium'}, 'high effort'),
            ({'request_id': 'earlier'}, 'earlier render'),
            ({'feedback': [{'at_seconds': 1, 'severity': 'P2', 'finding': 'x', 'recommendation': 'y',
                            'status': 'unknown'}]}, 'status'),
        )
        original = self.report.copy()
        for update, message in cases:
            with self.subTest(update=update), self.assertRaisesRegex(ValueError, message):
                self.report = {**original, **update}
                self.eligible()
        self.report = original
        self.confirmation['movie_sha256'] = 'earlier'
        with self.assertRaisesRegex(ValueError, 'confirmation'):
            self.eligible()

    def test_missing_review_blocks(self):
        with self.assertRaisesRegex(ValueError, 'Final Cut deferred'):
            require_finalcut_approval({}, self.movie)


if __name__ == '__main__':
    unittest.main()
