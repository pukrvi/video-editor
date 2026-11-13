"""Offline checks for this pipeline's Final Cut interchange contract.

These catch the observed export pattern; successful app import is a separate check.
"""
import argparse
from datetime import datetime, timezone
import json
from fractions import Fraction
from pathlib import Path
from tempfile import TemporaryDirectory
from urllib.parse import unquote, urlparse
import xml.etree.ElementTree as ET

from pipeline_paths import ROOT, guard_output_tree, movie_path, timeline_path
from quality_gate import sha256_file


def require(condition, message):
    if not condition:
        raise ValueError(message)


def seconds(value):
    require(value and value.endswith('s'), f'Invalid time: {value}')
    return Fraction(value[:-1])


def asset_media(doc):
    paths = {}
    for asset in doc.findall('./resources/asset'):
        rep = asset.find("./media-rep[@kind='original-media']")
        require(rep is not None, 'Expected original-media for each asset')
        uri = urlparse(rep.attrib['src'])
        require(uri.scheme == 'file' and uri.netloc in ('', 'localhost'), 'Expected local interchange media')
        path = Path(unquote(uri.path))
        require(path.is_file(), f'Missing media: {path}')
        paths[asset.attrib['id']] = path
    return paths


def check_timeline(xml_path, recipe, *, audio_layers=None, composite=None):
    doc = ET.parse(xml_path).getroot()
    require(not doc.findall('.//asset-clip/asset-clip'), 'Crash regression: use explicit audio/video nodes for connected layers')
    assets = {asset.attrib['id']: asset for asset in doc.findall('./resources/asset')}
    paths = asset_media(doc)
    project = doc.find('.//project')
    seq = project.find('./sequence') if project is not None else None
    require(seq is not None, 'Missing project timeline')
    fps = recipe['fps']
    duration = Fraction(round(recipe['duration'] * fps), fps)
    require(seconds(seq.attrib['duration']) == duration, 'Timeline duration differs from the recipe')
    format_node = doc.find(f"./resources/format[@id='{seq.attrib['format']}']")
    require(format_node is not None and seconds(format_node.attrib['frameDuration']) == Fraction(1, fps)
            and (int(format_node.attrib['width']), int(format_node.attrib['height'])) == (recipe['width'], recipe['height']),
            'Timeline frame clock or geometry differs from the recipe')
    clips = seq.findall('./spine/asset-clip')
    require(len(clips) == len(recipe['shots']), 'Main-shot count differs from recipe')
    cursor = 0
    for clip, shot in zip(clips, recipe['shots']):
        require(clip.attrib['ref'] in assets and assets[clip.attrib['ref']].get('hasVideo') == '1',
                'Missing main-shot video asset')
        require(cursor == shot['start_frame'] and seconds(clip.attrib['offset']) == Fraction(cursor, fps),
                'Main-shot offsets must follow the frame-rational spine without gaps')
        require(seconds(clip.attrib['duration']) == Fraction(shot['frames'], fps), 'Main-shot duration differs from recipe')
        require(seconds(clip.attrib['start']) == 0 and shot['frames'] > 0, 'Invalid main-shot source range')
        cursor += shot['frames']
    require(Fraction(cursor, fps) == duration and clips, 'Main shots must fill the timeline')
    role = 'dialogue' if 'blocks' in recipe else 'music'
    expected_audio = audio_layers if audio_layers is not None else [{'role': role}]
    audio = clips[0].findall('./audio')
    require(len(audio) == len(expected_audio) == len(seq.findall('./spine/asset-clip/audio')),
            'Expected audio connected to the first shot')
    for index, (clip, expected_layer) in enumerate(zip(audio, expected_audio)):
        ref = clip.attrib['ref']
        require(ref in assets and assets[ref].get('hasAudio') == '1', 'Missing connected audio asset')
        require(clip.attrib.get('role') == expected_layer['role'] and clip.attrib.get('lane') == str(-1-index),
                'Connected audio role or lane differs from the export')
        require(seconds(clip.attrib['duration']) == duration, 'Audio must match the frame-rational timeline duration')
        require(seconds(clip.attrib['offset']) == seconds(clip.attrib['start']) == 0,
                'Audio must begin on the first frame')
        if audio_layers is not None:
            require(paths[ref] == Path(expected_layer['path']) and clip.get('name') == expected_layer['name'],
                    'Connected audio media differs from the saved reconstruction')
    titles = []
    compositions = []
    for parent in clips:
        for child in parent.findall('./video'):
            ref = child.attrib['ref']
            require(ref in assets and assets[ref].get('hasVideo') == '1', 'Missing connected video asset')
            offset = seconds(child.attrib['offset'])
            start = seconds(parent.attrib['offset']) + offset - seconds(parent.attrib['start'])
            length = seconds(child.attrib['duration'])
            require(0 <= offset < seconds(parent.attrib['duration']) and length > 0 and start + length <= duration,
                    'Connected video lies outside its parent anchor or timeline')
            if ref == 'composite':
                require(composite and paths[ref] == composite['path'] and seconds(child.attrib['start']) == start
                        and child.attrib.get('lane') == '1', 'Baked composition source range differs from the timeline')
                compositions.append((start, start + length))
            else:
                require(seconds(child.attrib['start']) == 0, 'Prepared overlay must begin on its first frame')
                titles.append((child.attrib.get('name'), start, length))
    expected = [(title['headline'], Fraction(round(title['start'] * fps), fps),
                 Fraction(round(title['end'] * fps) - round(title['start'] * fps), fps))
                for title in recipe['titles']]
    expected += [(item['id'], Fraction(item['cut_frame']-item['duration_frames']//2, fps), Fraction(item['duration_frames'], fps))
                 for item in recipe.get('transitions', [])]
    require(sorted(titles) == sorted(expected), 'Connected overlay text/timing differs from recipe')
    expected_compositions = [(Fraction(start, fps), Fraction(end, fps))
                             for start, end in composite['spans']] if composite else []
    require(compositions == expected_compositions, 'Baked composition timing differs from the recipe')
    return {'status': 'statically_checked', 'main_shots': len(clips), 'title_overlays': len(recipe['titles']),
            'transition_overlays': len(recipe.get('transitions', [])),
            'baked_composition_overlays': len(compositions), 'audio_roles': [layer['role'] for layer in expected_audio],
            f'{role}_seconds': float(duration), 'project_name': project.attrib['name'],
            'media_sha256': {str(path): sha256_file(path) for path in set(paths.values())},
            'app_import': 'Separate in-app verification required for this export'}


def record_app_verification(recipe, evidence_path):
    movie = movie_path(recipe)
    xml = timeline_path(recipe, movie)
    receipt_name = 'finalcut_app_verification.json'
    out = guard_output_tree(movie.parent, writable=(receipt_name,))
    require(Path(evidence_path).resolve() != out/receipt_name, 'Evidence input must differ from the generated receipt')
    exported = json.loads((out / 'finalcut_export_checks.json').read_text())
    evidence = json.loads(Path(evidence_path).read_text())
    require(isinstance(evidence, dict), 'App verification evidence must be a JSON object')
    identity = {'movie_sha256': sha256_file(movie), 'xml_sha256': sha256_file(xml),
                'project_name': ET.parse(xml).find('.//project').attrib['name']}
    require(exported.get('status') == 'statically_checked'
            and all(exported.get(key) == value for key, value in identity.items()),
            'Current movie or XML differs from the checked export')
    require(all(evidence.get(key) == value for key, value in identity.items()),
            'App observations must identify the exact movie, XML and project')
    media = set(asset_media(ET.parse(xml).getroot()).values())
    require({str(path): sha256_file(path) for path in media} == exported.get('media_sha256'),
            'Timeline media has changed since export')
    fields = ('app_version', 'library', 'observations')
    require(all(isinstance(evidence.get(key), str) and evidence[key].strip() for key in fields),
            'Record the Final Cut version, library and actual app observations')
    expected = ['populated_project', 'timeline_geometry', 'picture_playback', 'connected_audio', 'audio_playback']
    if any(exported[key] for key in ('title_overlays', 'transition_overlays', 'baked_composition_overlays')):
        expected.append('connected_video')
    checks = evidence.get('checks')
    require(isinstance(checks, dict) and all(checks.get(key) is True for key in expected),
            'Complete the populated project, geometry, connected layer and playback checks in Final Cut')
    receipt = {'status': 'app_verified', **identity, **{key: evidence[key] for key in fields},
               'version': exported['version'], 'request_id': exported['request_id'], 'checks': checks,
               'media_sha256': exported['media_sha256'],
               'validity': 'Observations apply only while movie, XML and every linked-media hash match this receipt.',
               'recorded_at': datetime.now(timezone.utc).isoformat()}
    with TemporaryDirectory(prefix='.finalcut-verification-', dir=out) as scratch:
        candidate = Path(scratch) / receipt_name
        candidate.write_text(json.dumps(receipt, indent=2, ensure_ascii=False) + '\n')
        candidate.replace(out / receipt_name)
    return out / receipt_name


def app_verification_current(recipe):
    """Recheck a saved observation receipt; its stored status alone is not current proof."""
    try:
        movie = movie_path(recipe); xml = timeline_path(recipe, movie)
        receipt = json.loads((movie.parent/'finalcut_app_verification.json').read_text())
        exported = json.loads((movie.parent/'finalcut_export_checks.json').read_text())
        request = json.loads((movie.parent/'director_review_request.json').read_text())
        media = asset_media(ET.parse(xml).getroot())
        return (receipt.get('status') == 'app_verified'
                and receipt.get('request_id') == exported.get('request_id') == request.get('request_id')
                and receipt.get('movie_sha256') == sha256_file(movie)
                and receipt.get('xml_sha256') == sha256_file(xml)
                and receipt.get('media_sha256') == {str(p):sha256_file(p) for p in set(media.values())})
    except (OSError, ValueError, KeyError, ET.ParseError):
        return False


if __name__ == '__main__':
    state_path = ROOT / 'CURRENT_EDIT.json'
    current = json.loads(state_path.read_text()) if state_path.is_file() else {}
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--recipe', default=current.get('recipe'))
    parser.add_argument('--xml')
    args = parser.parse_args()
    if not args.recipe:
        parser.error('Initialize the edit or supply --recipe.')
    recipe = json.loads((ROOT / args.recipe).read_text())
    xml_path = Path(args.xml) if args.xml else timeline_path(recipe)
    print(json.dumps(check_timeline(xml_path, recipe), indent=2))
