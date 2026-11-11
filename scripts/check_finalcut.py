"""Offline checks for this pipeline's Final Cut interchange contract.

These catch the observed export pattern; successful app import is a separate check.
"""
import argparse
import json
from fractions import Fraction
from pathlib import Path
from urllib.parse import unquote, urlparse
import xml.etree.ElementTree as ET

from pipeline_paths import ROOT, timeline_path


def require(condition, message):
    if not condition:
        raise ValueError(message)


def seconds(value):
    require(value and value.endswith('s'), f'Invalid time: {value}')
    return Fraction(value[:-1])


def check_timeline(xml_path, recipe):
    doc = ET.parse(xml_path).getroot()
    require(not doc.findall('.//asset-clip/asset-clip'), 'Crash regression: use explicit audio/video nodes for connected layers')
    assets = {asset.attrib['id']: asset for asset in doc.findall('./resources/asset')}
    for rep in doc.findall('.//media-rep'):
        uri = urlparse(rep.attrib['src'])
        require(uri.scheme == 'file' and uri.netloc in ('', 'localhost'), 'Expected local interchange media')
        require(Path(unquote(uri.path)).is_file(), f'Missing media: {uri.path}')
    seq = doc.find('.//project/sequence')
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
    for clip, shot in zip(clips, recipe['shots']):
        require(clip.attrib['ref'] in assets, 'Missing main-shot asset')
        require(seconds(clip.attrib['offset']) == Fraction(shot['start_frame'], fps), 'Main-shot offset differs from recipe')
        require(seconds(clip.attrib['duration']) == Fraction(shot['frames'], fps), 'Main-shot duration differs from recipe')
    audio = seq.findall('./spine/asset-clip/audio')
    role = 'dialogue' if 'blocks' in recipe else 'music'
    require(len(audio) == 1 and audio[0].attrib['ref'] in assets, 'Expected one connected audio mix')
    require(audio[0].attrib.get('role') == role, f'Expected a connected {role} role')
    require(seconds(audio[0].attrib['duration']) == duration, 'Audio must match the frame-rational timeline duration')
    require(seconds(audio[0].attrib['offset']) == 0, 'Audio must begin on the first frame')
    titles = []
    for parent in clips:
        for child in parent.findall('./video'):
            require(child.attrib['ref'] in assets, 'Missing connected video asset')
            start = seconds(parent.attrib['offset']) + seconds(child.attrib['offset'])
            titles.append((child.attrib.get('name'), start, seconds(child.attrib['duration'])))
    expected = [(title['headline'], Fraction(round(title['start'] * fps), fps),
                 Fraction(round(title['end'] * fps) - round(title['start'] * fps), fps))
                for title in recipe['titles']]
    expected += [(item['id'], Fraction(item['cut_frame']-item['duration_frames']//2, fps), Fraction(item['duration_frames'], fps))
                 for item in recipe.get('transitions', [])]
    require(sorted(titles) == sorted(expected), 'Connected overlay text/timing differs from recipe')
    return {'status': 'statically_checked', 'main_shots': len(clips), 'title_overlays': len(recipe['titles']),
            'transition_overlays': len(recipe.get('transitions', [])),
            f'{role}_seconds': float(seconds(audio[0].attrib['duration'])),
            'app_import': 'Separate in-app verification required for this export'}


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
