"""Prepare an independent director review and check it against the final movie."""
import argparse
import hashlib
import json
import math
from pathlib import Path
import uuid

from pipeline_paths import ROOT, guard_output_tree, movie_path


MODEL = 'gpt-6.1-sol'
LEGACY_EFFORT = 'medium'
EFFORTS = {'low', 'medium', 'high', 'xhigh', 'max', 'ultra'}
WEIGHTS = {
    'story': 20,
    'shot_selection': 20,
    'pacing': 15,
    'motion_design': 15,
    'transitions': 10,
    'composition_legibility': 10,
    'ending': 10,
}
REVIEW_FILES = ('director_review_checks.json', 'director_review_prompt.md', 'director_review_request.json')


def sha256_file(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def validate_effort(effort):
    if not isinstance(effort, str) or effort not in EFFORTS:
        raise ValueError('Unsupported director reasoning effort')
    return effort


def reviewer_effort(recipe):
    settings = recipe.get('director_review', {})
    if not isinstance(settings, dict):
        raise ValueError('director_review must be a JSON object')
    return validate_effort(settings.get('reasoning_effort', LEGACY_EFFORT))


def write_review_request(recipe, movie, root=ROOT):
    movie = Path(movie)
    folder = guard_output_tree(movie.parent, writable=REVIEW_FILES)
    effort = reviewer_effort(recipe)
    digest = sha256_file(movie)
    request_id = str(uuid.uuid4())
    prompt = (root / 'templates/director_review_prompt.md').read_text()
    for field, value in (('MOVIE', str(movie)), ('SHA256', digest), ('VERSION', recipe['version']),
                         ('REQUEST_ID', request_id), ('MODEL', MODEL), ('EFFORT', effort)):
        prompt = prompt.replace('{{' + field + '}}', value)
    prompt_path = folder / 'director_review_prompt.md'
    (folder / 'director_review_checks.json').unlink(missing_ok=True)
    prompt_path.write_text(prompt)
    request = {
        'status': 'awaiting_independent_director_review',
        'request_id': request_id,
        'version': recipe['version'],
        'movie': str(movie),
        'movie_sha256': digest,
        'prompt': str(prompt_path),
        'reviewer_model': MODEL,
        'reasoning_effort': effort,
    }
    (folder / 'director_review_request.json').write_text(json.dumps(request, indent=2) + '\n')
    return request


def _nonempty_text(value):
    return isinstance(value, str) and bool(value.strip())


def _number_in(value, minimum, maximum):
    return type(value) in (int, float) and minimum <= value <= maximum


def validate_review(report, movie, request, *, recipe=None):
    """Check shared identity, reviewer and report evidence before applying stage thresholds."""
    if not isinstance(report, dict) or not isinstance(request, dict):
        raise ValueError('Director request and report must be JSON objects')
    request_id = request.get('request_id')
    if not _nonempty_text(request_id) or report.get('request_id') != request_id:
        raise ValueError('Director review belongs to an earlier render request. Review this run.')
    digest = sha256_file(movie)
    if request.get('movie_sha256') != digest:
        raise ValueError('Director request belongs to a different movie. Render a fresh request.')
    if report.get('movie_sha256') != digest:
        raise ValueError('Director review belongs to a different movie. Review the current render.')
    effort = validate_effort(request.get('reasoning_effort', LEGACY_EFFORT))
    if recipe is not None and (effort != reviewer_effort(recipe)
                               or request.get('version', recipe.get('version')) != recipe.get('version')):
        raise ValueError('Director request does not match this recipe version or requested effort.')
    if (request.get('reviewer_model', MODEL) != MODEL or report.get('reviewer_model') != MODEL
            or report.get('reasoning_effort') != effort):
        raise ValueError(f'Use the requested independent GPT-6.1 Sol reviewer at {effort} effort.')
    if report.get('independent_reviewer') is not True:
        raise ValueError('The editor must obtain a separate reviewer agent’s assessment.')
    scores = report.get('scores')
    if not isinstance(scores, dict):
        raise ValueError('Include the complete seven-area rubric.')
    for area, maximum in WEIGHTS.items():
        if not _number_in(scores.get(area), 0, maximum):
            raise ValueError(f'Invalid director score for {area}.')
    total = sum(scores[area] for area in WEIGHTS)
    if not _number_in(report.get('score'), 0, 100) or report['score'] != total:
        raise ValueError('Director score must equal the seven rubric scores.')
    for field in ('evidence', 'strengths', 'limitations'):
        items = report.get(field)
        if not isinstance(items, list) or (field != 'limitations' and not items) or not all(map(_nonempty_text, items)):
            raise ValueError('Include evidence, strengths and review limitations as text lists.')
    feedback = report.get('feedback')
    if not isinstance(feedback, list):
        raise ValueError('Include the reviewer’s specific actionable feedback.')
    for item in feedback:
        if (not isinstance(item, dict) or not _nonempty_text(item.get('finding'))
                or not _nonempty_text(item.get('recommendation'))):
            raise ValueError('Each finding needs a time, description and implementable recommendation.')
        at = item.get('at_seconds')
        if not _number_in(at, 0, math.inf) or at == math.inf:
            raise ValueError('Feedback times must be finite nonnegative seconds.')
        if item.get('severity') not in ('P0', 'P1', 'P2', 'P3'):
            raise ValueError('Each finding needs a priority from P0 through P3.')
        if item.get('status') not in ('open', 'resolved', 'optional'):
            raise ValueError('Each finding needs status open, resolved or optional.')
    return {'score': total, 'movie_sha256': digest, 'request_id': request_id,
            'reviewer_model': MODEL, 'reasoning_effort': effort}


def check_review(report, movie, request, *, recipe=None):
    evidence = validate_review(report, movie, request, recipe=recipe)
    if any(item['severity'] in ('P0', 'P1') and item['status'] != 'resolved' for item in report['feedback']):
        raise ValueError('Resolve major director findings and obtain a fresh review.')
    # Controller acceptance policy. This target is excluded from reviewer prompts.
    if evidence['score'] <= 90:
        raise ValueError(f"Director returned {evidence['score']}/100. Continue relevant revisions within the requested scope.")
    return {'status': 'director_review_passed', **evidence}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--recipe')
    parser.add_argument('--report', help='JSON assessment written from the independent reviewer’s findings')
    args = parser.parse_args()
    state_path = ROOT / 'CURRENT_EDIT.json'
    state = json.loads(state_path.read_text()) if state_path.exists() else {}
    recipe_path = args.recipe or state.get('recipe')
    if not recipe_path:
        parser.error('Initialize the edit or supply --recipe.')
    try:
        recipe = json.loads((ROOT / recipe_path).read_text())
        movie = movie_path(recipe)
        report_path = Path(args.report) if args.report else ROOT / 'review/director' / f"{recipe['version']}.json"
        if not report_path.exists():
            parser.exit(2, 'Director review pending. The Codex editing agent must run the independent reviewer.\n')
        guard_output_tree(movie.parent, writable=(REVIEW_FILES[0],))
        request = json.loads((movie.parent / 'director_review_request.json').read_text())
        result = check_review(json.loads(report_path.read_text()), movie, request, recipe=recipe)
    except (ValueError, OSError, KeyError) as error:
        parser.exit(1, str(error) + '\n')
    result['report'] = str(report_path)
    (movie.parent / REVIEW_FILES[0]).write_text(json.dumps(result, indent=2) + '\n')
    if state.get('recipe') and (ROOT / state['recipe']).resolve() == (ROOT / recipe_path).resolve():
        guard_output_tree(ROOT, writable=(state_path.name,))
        state.update(status='ready_for_user_review', director_review=str(report_path), director_score=result['score'])
        state_path.write_text(json.dumps(state, indent=2, ensure_ascii=False) + '\n')
    print(json.dumps(result, indent=2))


if __name__ == '__main__':
    main()
