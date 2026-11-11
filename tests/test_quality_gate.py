"""Regression checks for absent, stale and incomplete director acceptance."""
import copy
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from quality_gate import check_review, write_review_request


class DirectorGateTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.movie = self.root / 'synthetic-test.mp4'
        self.movie.write_bytes(b'synthetic unit-test artifact, not a video')
        self.report = {
            'request_id': 'synthetic-request-1',
            'movie_sha256': hashlib.sha256(self.movie.read_bytes()).hexdigest(),
            'reviewer_model': 'gpt-6.1-sol',
            'reasoning_effort': 'medium',
            'independent_reviewer': True,
            'score': 91,
            'scores': {'story': 19, 'shot_selection': 19, 'pacing': 13,
                       'motion_design': 14, 'transitions': 9,
                       'composition_legibility': 9, 'ending': 8},
            'strengths': ['Synthetic test assessment'],
            'feedback': [],
            'evidence': ['Unit-test fixture only'],
            'limitations': ['No actual director judgment is represented by this fixture'],
        }
        self.request = {'request_id': 'synthetic-request-1',
                        'movie_sha256': self.report['movie_sha256']}

    def test_current_complete_assessment_passes(self):
        self.assertEqual(check_review(self.report, self.movie, self.request)['score'], 91)

    def test_score_at_boundary_requires_another_pass(self):
        self.report['scores']['story'] -= 1
        self.report['score'] = 90
        with self.assertRaisesRegex(ValueError, 'Continue relevant revisions'):
            check_review(self.report, self.movie, self.request)

    def test_changed_movie_invalidates_the_review(self):
        self.movie.write_bytes(b'a changed artifact')
        with self.assertRaisesRegex(ValueError, 'different movie'):
            check_review(self.report, self.movie, self.request)

    def test_same_movie_from_an_earlier_render_is_rejected(self):
        self.request['request_id'] = 'synthetic-request-2'
        with self.assertRaisesRegex(ValueError, 'earlier render request'):
            check_review(self.report, self.movie, self.request)

    def test_major_open_finding_blocks_acceptance(self):
        self.report['feedback'] = [{'at_seconds': 2.1, 'severity': 'P1',
                                   'finding': 'A stroke covers the face',
                                   'recommendation': 'Move the stroke into clear space',
                                   'status': 'open'}]
        with self.assertRaisesRegex(ValueError, 'major director findings'):
            check_review(self.report, self.movie, self.request)

    def test_incorrect_rubric_total_is_rejected(self):
        self.report['score'] = 99
        with self.assertRaisesRegex(ValueError, 'equal the seven'):
            check_review(self.report, self.movie, self.request)

    def test_missing_independence_and_evidence_are_rejected(self):
        for field, value in [('independent_reviewer', 'false'), ('evidence', [])]:
            with self.subTest(field=field):
                report = copy.deepcopy(self.report)
                report[field] = value
                with self.assertRaises(ValueError):
                    check_review(report, self.movie, self.request)

    def test_malformed_finding_times_and_statuses_are_rejected(self):
        valid = {'at_seconds': 1, 'severity': 'P3', 'finding': 'Adjust the leader',
                 'recommendation': 'Move its endpoint', 'status': 'optional'}
        for value in (float('nan'), float('inf'), -1, True, '1'):
            with self.subTest(value=value), self.assertRaisesRegex(ValueError, 'finite'):
                check_review({**self.report, 'feedback': [{**valid, 'at_seconds': value}]}, self.movie, self.request)
        with self.assertRaisesRegex(ValueError, 'status'):
            check_review({**self.report, 'feedback': [{**valid, 'status': 'unverified'}]}, self.movie, self.request)

    def test_high_effort_is_required_in_current_assessment(self):
        request = {**self.request, 'reasoning_effort': 'high', 'version': 'v01'}
        recipe = {'version': 'v01', 'blocks': [], 'director_review': {'reasoning_effort': 'high'}}
        with self.assertRaisesRegex(ValueError, 'high effort'):
            check_review(self.report, self.movie, request, recipe=recipe)
        report = {**self.report, 'reasoning_effort': 'high'}
        self.assertEqual(check_review(report, self.movie, request, recipe=recipe)['reasoning_effort'], 'high')

    def test_new_request_clears_old_acceptance_and_omits_target(self):
        (self.root / 'templates').mkdir()
        (self.root / 'templates/director_review_prompt.md').write_text(
            'Review {{MOVIE}} {{SHA256}} {{VERSION}} with {{MODEL}} at {{EFFORT}} candidly.'
        )
        previous = self.root / 'director_review_checks.json'
        previous.write_text('{"status":"director_review_passed"}')
        request = write_review_request({'version': 'reel_v02', 'director_review': {'reasoning_effort': 'high'}}, self.movie, self.root)
        self.assertFalse(previous.exists())
        self.assertEqual(request['status'], 'awaiting_independent_director_review')
        saved = json.loads((self.root / 'director_review_request.json').read_text())
        self.assertEqual(saved['movie_sha256'], self.report['movie_sha256'])
        self.assertNotIn('target', saved)
        self.assertEqual(
            (self.root / 'director_review_prompt.md').read_text(),
            f"Review {self.movie} {self.report['movie_sha256']} reel_v02 with gpt-6.1-sol at high candidly.",
        )


if __name__ == '__main__':
    unittest.main()
