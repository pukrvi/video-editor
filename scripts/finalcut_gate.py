"""Require an exact-movie independent review and explicit Final Cut confirmation."""
import json
from pathlib import Path

from quality_gate import validate_review


def require_finalcut_approval(recipe, movie):
    movie = Path(movie)
    report_path = recipe.get('finalcut_review_report')
    if not report_path:
        raise ValueError('Final Cut deferred: obtain an independent director review scoring at least 85, then user confirmation.')
    report = json.loads(Path(report_path).read_text())
    request = json.loads((movie.parent / 'director_review_request.json').read_text())
    evidence = validate_review(report, movie, request, recipe=recipe)
    if evidence['score'] < 85:
        raise ValueError('Director score must be at least 85 for Final Cut export.')
    confirmation = recipe.get('finalcut_user_confirmation')
    if (not isinstance(confirmation, dict) or confirmation.get('confirmed') is not True
            or confirmation.get('movie_sha256') != evidence['movie_sha256']
            or not isinstance(confirmation.get('user_message'), str)
            or not confirmation['user_message'].strip()):
        raise ValueError('User confirmation for this reviewed version is required.')
    return {'status': 'eligible', **evidence, 'confirmation': confirmation}
