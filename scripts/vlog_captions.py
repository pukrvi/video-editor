"""Author short, highlighted captions on the vlog picture clock."""
import math
import re
import hashlib
from pathlib import Path

from PIL import ImageFont

FACES = {
    'Voice': ('/System/Library/Fonts/Avenir Next.ttc', 2, 'Avenir Next Demi Bold',
              'AvenirNext-DemiBold', 0),
    'Hindi': ('/System/Library/Fonts/Supplemental/Devanagari Sangam MN.ttc', 1,
              'Devanagari Sangam MN', 'DevanagariSangamMN-Bold', -1),
}
HIGHLIGHT = r'{\1c&H008FDCFF&}'
WHITE = r'{\1c&H00FFFFFF&}'
STOP = set('a an the our my and of to in as on that was were is we i it from with for they but or'.split())
UNIT = re.compile(r'^(?:km|m|ft|feet|kg|g|mi|miles|seconds?|minutes?|hours?|am|pm|a\.m\.|p\.m\.)\b', re.I)


def caption_preset(recipe):
    settings = recipe.get('captions', {})
    if not isinstance(settings, dict) or settings.get('preset', 'legacy') not in ('legacy', 'avenir_highlight'):
        raise ValueError('captions.preset must be legacy or avenir_highlight')
    return settings.get('preset', 'legacy')


def font_overrides(recipe):
    settings = recipe.get('captions', {}).get('fonts', {})
    if not isinstance(settings, dict) or settings.keys() - {'latin', 'hindi'}:
        raise ValueError('captions.fonts must map latin or hindi to approved font files')
    paths = {}
    for script, value in settings.items():
        path = Path(value).expanduser()
        if not path.is_absolute() or not path.is_file() or path.suffix.lower() not in ('.ttc', '.otc', '.ttf', '.otf'):
            raise ValueError('Caption font overrides require existing absolute font paths')
        paths['Voice' if script == 'latin' else 'Hindi'] = path.resolve()
    return paths


def load_face(style, overrides, size=59):
    path, index, family, _, _ = FACES[style]
    custom = overrides.get(style)
    path = Path(custom or path)
    names = ('Avenir Next', 'Demi Bold') if style == 'Voice' else ('Devanagari Sangam MN', 'Bold')
    for i in range(32) if custom else (index,):
        try:
            font = ImageFont.truetype(str(path), size, index=i)
        except OSError:
            break
        if font.getname() == names:
            return font, {'family': family, 'face': ' '.join(names), 'face_index': i,
                          'sha256': hashlib.sha256(path.read_bytes()).hexdigest()}
    raise ValueError(f'Caption preset requires the {" ".join(names)} face')


def clean(text):
    return ' '.join(text.replace('\\', '').replace('{', '(').replace('}', ')').split())


def indivisible(left, right):
    return (
        any(c.isdecimal() for c in left) and bool(UNIT.match(right))
        or left[:1].isupper() and right[:1].isupper() and left.isalpha()
    )


def lines_for(words, font, width=750, max_words=4):
    tokens = [w['text'] for w in words]
    measure = lambda line: font.getlength(' '.join(line))
    if len(tokens) <= max_words and measure(tokens) <= width:
        return [tokens]
    options = []
    for split in range(1, len(tokens)):
        a, b = tokens[:split], tokens[split:]
        wa, wb = measure(a), measure(b)
        if len(a) <= max_words and len(b) <= max_words and max(wa, wb) <= width:
            penalty = 400 if indivisible(a[-1], b[0]) else 0
            penalty += 95 if a[-1].casefold() in STOP else 0
            options.append((abs(wa-wb)+penalty, [a, b]))
    return min(options, key=lambda option: option[0])[1] if options else None


def phrase_groups(words, font, sizes, fps, width=750):
    if sizes is not None:
        if (not isinstance(sizes, list)
                or any(type(n) is not int or not 1 <= n <= 8 for n in sizes)
                or sum(sizes) != len(words)):
            raise ValueError('caption_phrase_sizes must cover the visible words exactly')
        start = 0
        result = []
        for size in sizes:
            result.append(words[start:start+size])
            start += size
        return result

    # Score natural breaks without extending one cue across a long quiet gap.
    best = {len(words): (0, len(words))}
    for i in reversed(range(len(words))):
        options = []
        for end in range(i+1, min(i+6, len(words))+1):
            group = words[i:end]
            duration = (group[-1]['end']-group[0]['start'])/fps
            gaps = [(b['start']-a['end'])/fps for a, b in zip(group, group[1:])]
            if duration > 3.25 or max(gaps, default=0) > .88:
                break
            if any(w['text'].endswith(('.', '?', '!', '…', '।')) and not UNIT.match(w['text'])
                   for w in group[:-1]):
                break
            if (end not in best or not lines_for(group, font, width)
                    or end < len(words) and words[end]['start'] == group[-1]['start']):
                continue
            last = group[-1]['text']
            cost = 3.25 + .14*(len(group)-4)**2 + 4*(len(group)==1)
            cost += 1.9*(last.casefold() in STOP)
            cost -= .75*last.endswith(('.', '?', '!', ',', '…', '।'))
            cost += sum(max(0, gap-.25)*3.2 for gap in gaps)
            if end < len(words) and indivisible(last, words[end]['text']):
                cost += 12
            options.append((cost+best[end][0], end))
        if options:
            best[i] = min(options, key=lambda option: option[0])
    if 0 not in best:
        raise ValueError('Caption contains text that cannot fit within two lines')
    groups, start = [], 0
    while start < len(words):
        end = best[start][1]
        groups.append(words[start:end])
        start = end
    return groups


def speech_words(block, offset, fps, count):
    result = []
    previous = -math.inf
    for item in block.get('words', []):
        a, z = item['start'], item['end']
        if not (math.isfinite(a) and math.isfinite(z) and previous <= a < z):
            raise ValueError('Caption words require finite and ordered source times')
        previous = a
        if a >= block['out'] or z <= block['in']:
            continue
        a = min(count-1, max(0, round((a-block['in'])*fps)))
        z = min(count, round((z-block['in'])*fps))
        if text := clean(item['text']):
            result.append({'text': text, 'start': offset+a, 'end': offset+max(a, z)})
    return result


def clock(frame, fps, srt=False):
    # Floor to centiseconds so libass changes state on the selected video frame.
    cs = frame*100//fps
    hour, rest = divmod(cs, 360000)
    minute, rest = divmod(rest, 6000)
    second, cs = divmod(rest, 100)
    return (f'{hour:02}:{minute:02}:{second:02},{cs:02}0' if srt
            else f'{hour}:{minute:02}:{second:02}.{cs:02}')


def build_highlighted(recipe):
    fps = recipe.get('fps', 30)
    landscape = recipe.get('width') == 1920
    size, width = (54, 1050) if landscape else (59, 750)
    styles = {}
    overrides = font_overrides(recipe)
    phrases, events, mapped = [], [], []
    offset = 0
    for block in recipe['blocks']:
        count = round((block['out']-block['in'])*fps)
        words = speech_words(block, offset, fps, count)
        mapped.extend({**w, 'start': w['start']/fps, 'end': w['end']/fps} for w in words)
        if not words:
            if block.get('caption_phrase_sizes') not in (None, []):
                raise ValueError('caption_phrase_sizes must cover the visible words exactly')
            offset += count
            continue
        style = 'Hindi' if any(re.search(r'[\u0900-\u097f]', w['text']) for w in words) else 'Voice'
        if style not in styles:
            styles[style] = load_face(style, overrides, size)
        font, _ = styles[style]
        groups = phrase_groups(words, font, block.get('caption_phrase_sizes'), fps, width)
        lead = round(.043*fps)
        # Word bounds can overlap in ASR data. The later word takes over at its
        # start, so the earlier word does not reappear when the later one ends.
        for i, w in enumerate(words):
            next_word = words[i+1]['start'] if i+1 < len(words) else offset+count
            w['active_end'] = min(w['end'], next_word, w['start']+round(.72*fps))
        for index, group in enumerate(groups):
            start = max(offset, group[0]['start']-lead)
            following_start = (groups[index+1][0]['start']-lead
                               if index+1 < len(groups) else offset+count)
            stop = min(offset+count, following_start,
                       max(group[-1]['end']+round(.23*fps), start+round(.53*fps)))
            if start >= stop:
                raise ValueError('Caption phrase boundaries overlap on the output frame clock')
            lines = lines_for(group, font, width)
            if lines is None:
                raise ValueError('Authored caption phrase exceeds two lines or the width limit')
            phrases.append({'start_frame': start, 'end_frame': stop, 'style': style,
                            'lines': [' '.join(line) for line in lines],
                            'widths': [round(font.getlength(' '.join(line)), 2) for line in lines]})
            bounds = {start, stop}
            for word in group:
                bounds.update(min(stop, max(start, word[edge])) for edge in ('start', 'active_end'))
            ordered = sorted(bounds)
            if landscape:
                pos = r'{\an8\pos(960,120)\q2}' if block.get('captions_top') else r'{\an2\pos(960,936)\q2}'
            else:
                pos = r'{\an8\pos(504,280)\q2}' if block.get('captions_top') else r'{\an2\pos(504,1460)\q2}'
            for a, z in zip(ordered, ordered[1:]):
                active = next((i for i, w in enumerate(group) if w['start'] <= a < w['active_end']), None)
                tokens = [(HIGHLIGHT+word['text']+WHITE) if i == active else word['text']
                          for i, word in enumerate(group)]
                first = len(lines[0])
                content = ' '.join(tokens[:first])
                if len(lines) == 2:
                    content += r'\N' + ' '.join(tokens[first:])
                events.append(f'Dialogue: 1,{clock(a,fps)},{clock(z,fps)},{style},,0,0,0,,{pos}{content}')
        offset += count
    return events, phrases, mapped, {name: evidence for name, (_, evidence) in styles.items()}


def write_highlighted(recipe, out, header, note_events):
    fps = recipe.get('fps', 30)
    events, phrases, mapped, faces = build_highlighted(recipe)
    landscape = recipe.get('width') == 1920
    size, margin = (54, 144) if landscape else (59, 460)
    style_lines = ''.join(
        f'Style: {name},{family},{size},&H00FFFFFF,&H00FFFFFF,&H00201A15,&H7F1B1714,'
        f'{bold},0,0,0,100,100,0,0,1,3.4,1.1,2,120,190,{margin},1\n'
        for name, (_, _, family, _, bold) in FACES.items()
    )
    header = re.sub(r'^Style: Voice,.*\n', lambda _: style_lines, header, flags=re.MULTILINE)
    header = header.replace('WrapStyle: 0', 'WrapStyle: 2\nScaledBorderAndShadow: yes\nYCbCr Matrix: TV.709')
    ass = out/'captions.ass'
    ass.write_text(header+'\n'.join(events+note_events)+'\n')
    (out/'captions.srt').write_text('\n\n'.join(
        f"{i}\n{clock(p['start_frame'],fps,True)} --> {clock(p['end_frame'],fps,True)}\n"
        + '\n'.join(p['lines']) for i, p in enumerate(phrases, 1)
    )+'\n')
    return ass, mapped, {'preset': 'avenir_highlight', 'phrases': phrases, 'measurement_faces': faces}


def verify_selected_faces(evidence, ffmpeg_log):
    selections = sorted({line.partition('fontselect: ')[2] for line in ffmpeg_log.splitlines()
                         if 'fontselect: ' in line})
    for style in {p['style'] for p in evidence['phrases']}:
        _, _, family, postscript, _ = FACES[style]
        relevant = [line for line in selections if line.startswith(f'({family},')]
        if not relevant or any(postscript not in line.partition(' -> ')[2] for line in relevant):
            raise ValueError(f'libass did not consistently resolve the {family} caption face: {relevant}')
    evidence['libass_font_selection'] = selections
