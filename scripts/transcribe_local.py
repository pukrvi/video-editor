#!/usr/bin/env python3
"""Offline, resumable source-audio transcription using whisper.cpp.

Outputs contain unreviewed recognition, never verified quotations. Timestamp and
hallucination flags identify results requiring listening; silence and music can
still produce confident-looking text. No audio is sent to a remote service.
"""
import argparse, concurrent.futures, hashlib, json, math, re, subprocess, sys, tempfile, wave, array
from pathlib import Path
from fractions import Fraction

from pipeline_paths import guard_output_tree

ENGINE_VERSION = 2

def effectively_silent(path):
    # Only skip near-digital silence; noisy wind still goes through recognition.
    peak = 0
    with wave.open(str(path), 'rb') as f:
        while True:
            b = f.readframes(65536)
            if not b: break
            samples = array.array('h', b)
            if sys.byteorder != 'little': samples.byteswap()
            peak = max(peak, max(map(abs, samples), default=0))
            if peak > 4: return False
    return True

EXTENSIONS = {'.mp4', '.mov', '.m4v', '.avi', '.mkv'}
AUDIO_EXTENSIONS = {'.aac', '.aif', '.aiff', '.caf', '.flac', '.m4a', '.mp3', '.ogg', '.opus', '.wav'}

def run(cmd):
    return subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, errors='replace', check=True, timeout=300)

def fingerprint(path):
    h = hashlib.sha256()
    with path.open('rb') as f:
        for b in iter(lambda: f.read(1024 * 1024), b''):
            h.update(b)
    return h.hexdigest()

def atomic(path, data):
    with tempfile.TemporaryDirectory(dir=path.parent) as temp:
        tmp = Path(temp)/path.name
        tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2) + '\n')
        tmp.replace(path)

def probe(path):
    try:
        data = json.loads(run(['ffprobe','-v','error','-protocol_whitelist','file','-show_entries',
                               'format=duration:stream=codec_type,duration,duration_ts,time_base','-of','json',str(path)]).stdout)
        duration = float(data.get('format', {}).get('duration', 0))
        audio = next((s for s in data.get('streams', []) if s.get('codec_type') == 'audio'), None)
        audio_duration = duration
        if audio and audio.get('duration') not in (None, 'N/A'):
            audio_duration = float(audio['duration'])
        elif audio and audio.get('duration_ts') is not None:
            audio_duration = float(Fraction(audio['time_base'])*audio['duration_ts'])
        return path, duration, audio_duration if audio else None, None
    except Exception as e:
        return path, 0, None, str(e)


def selected_jobs(library, workspace, sources, windows):
    def source_path(value):
        path = (library/Path(value).expanduser()).resolve()
        if (not path.is_file() or not path.is_relative_to(library) or path.is_relative_to(workspace)
                or 'Personal Content' in path.parts or path.suffix.lower() not in EXTENSIONS | AUDIO_EXTENSIONS):
            raise ValueError(f'Source must be permitted audio or video under the library: {value}')
        return path

    jobs = [(source_path(value), None) for value in sources]
    for value, start, stop in windows:
        a, z = float(start), float(stop)
        if not (math.isfinite(a) and math.isfinite(z) and 0 <= a < z):
            raise ValueError('Selected source window needs finite START and END in seconds')
        a, z = round(a, 6), round(z, 6)
        if z-a < 1/16000:
            raise ValueError('Selected source window is shorter than one extracted sample')
        jobs.append((source_path(value), (a,z)))
    return list(dict.fromkeys(jobs))

def flags_for(segments, duration):
    flags = set()
    words = []
    previous = 0
    for s in segments:
        text = s.get('text', '').strip()
        if not text: continue
        start, end = s['offsets']['from']/1000, s['offsets']['to']/1000
        if start < previous - 0.02: flags.add('nonmonotonic_timestamps')
        previous = start
        if '\ufffd' in text: flags.add('invalid_utf8_replaced')
        words.extend(re.findall(r'\w+', text.casefold()))
        if end > duration + 0.5 or start > duration: flags.add('timestamp_beyond_source')
        if end <= start or end-start > 5: flags.add('imprecise_word_timestamps')
        for t in s.get('tokens', []):
            if not t['text'].startswith('[_') and t.get('p', 1) < .3: flags.add('low_token_confidence')
    if len(words) >= 4:
        for n in (2, 3, 4):
            phrases = [tuple(words[i:i+n]) for i in range(len(words)-n+1)]
            if phrases and max(phrases.count(p) for p in set(phrases)) >= 3:
                flags.add('repeated_phrase_possible_hallucination')
    joined = ' '.join(words)
    if any(phrase in joined for phrase in ('thank you for watching', 'thanks for watching', 'subscribe to my channel', 'sampai jumpa di video selanjutnya')):
        flags.add('stock_phrase_possible_hallucination')
    if not words: flags.add('no_recognized_words_not_proof_of_silence')
    return sorted(flags)

def normalize_dtw(segments, duration):
    """Group DTW word pieces. Ends are estimates, bounded by the next start.

    DTW times are in 10ms units. Never claim these estimates are verified.
    """
    words, flags = [], set()
    for seg in segments:
        for token in seg.get('tokens', []):
            piece = token.get('text', '')
            t = token.get('t_dtw', -1)
            if not piece or piece.startswith('[_') or t is None or t < 0: continue
            start = t / 100.0
            if start < 0 or start > duration:
                flags.add('dtw_outside_source'); continue
            if words and start < words[-1]['_last']:
                flags.add('dtw_nonmonotonic'); continue
            begins = piece[0].isspace()
            text = piece.strip()
            if not text: continue
            if begins or not words:
                words.append({'text': text, 'start_seconds': start, '_last': start})
            else:
                words[-1]['text'] += text
                words[-1]['_last'] = start
    for i, word in enumerate(words):
        next_start = words[i+1]['start_seconds'] if i+1 < len(words) else duration
        # No word is held across a long pause; the capped end is an estimate.
        word['end_seconds'] = round(min(duration, next_start, max(word['start_seconds'] + 0.2, word['_last']), word['start_seconds'] + 1.0), 3)
        word.pop('_last')
        if word['end_seconds'] <= word['start_seconds']: flags.add('dtw_zero_length_word')
    if not words: flags.add('dtw_no_valid_tokens')
    flags.add('dtw_word_ends_are_estimates_listen_to_source')
    return words, sorted(flags)

def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--library', required=True, type=Path)
    ap.add_argument('--workspace', required=True, type=Path)
    ap.add_argument('--model', type=Path, default=Path.home()/'Library/Application Support/MacWhisper/models/ggml-large-v3.bin')
    ap.add_argument('--whisper', default='whisper-cli')
    ap.add_argument('--limit', type=int, default=0)
    ap.add_argument('--language', default='auto', help='Whisper language code or auto')
    ap.add_argument('--align', action='store_true', help='experimental large-v3 DTW alignment, disables flash attention')
    ap.add_argument('--chunk-seconds', type=float, default=0, help='independent language detection per chunk, e.g. 30; 0 detects once per source')
    ap.add_argument('--priority', action='append', default=[], help='source filename to process before the longest-first queue; repeatable')
    ap.add_argument('--prefer-prefix', action='append', default=[], help='after priorities, process these filename prefixes first')
    ap.add_argument('--source', action='append', default=[], metavar='PATH',
                    help='select a video or audio-only file under the library; repeatable')
    ap.add_argument('--window', action='append', nargs=3, default=[], metavar=('PATH','START','END'),
                    help='select a source range in seconds; repeatable')
    args = ap.parse_args()
    args.library = args.library.resolve()
    args.model = args.model.expanduser()
    if not math.isfinite(args.chunk_seconds) or args.chunk_seconds < 0: ap.error('chunk seconds must be finite and non-negative')
    settings = {'language': args.language, 'chunk_seconds': args.chunk_seconds, 'align': args.align}
    if not args.model.is_file(): ap.error('model not found: ' + str(args.model))
    workspace = args.workspace.resolve()
    try:
        if args.source or args.window:
            selections = selected_jobs(args.library,workspace,args.source,args.window)
        else:
            selections = [(p,None) for p in args.library.rglob('*') if p.is_file() and p.suffix.lower() in EXTENSIONS
                          and p.resolve().is_relative_to(args.library) and not p.resolve().is_relative_to(workspace)
                          and 'Personal Content' not in p.resolve().parts]
        paths = list(dict.fromkeys(path for path,_ in selections))
        generated = ('transcripts','audio_cache')
        if any(args.model.resolve().is_relative_to(workspace/name) for name in generated):
            raise ValueError('The model must be outside the generated transcripts and audio cache')
        workspace = guard_output_tree(args.workspace, paths, album=args.library, writable=generated)
    except (OSError,ValueError) as exc:
        ap.error(str(exc))
    out, cache = workspace/'transcripts', workspace/'audio_cache'
    out.mkdir(parents=True, exist_ok=True); cache.mkdir(parents=True, exist_ok=True)
    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
        probes = {item[0]:item[1:] for item in pool.map(probe, paths)}
    jobs = [(path,*probes[path],window) for path,window in selections]
    jobs.sort(key=lambda x: (args.priority.index(x[0].name) if x[0].name in args.priority else len(args.priority), 0 if any(x[0].name.startswith(p) for p in args.prefer_prefix) else 1, -x[1]))
    if args.limit: jobs = jobs[:args.limit]
    summary = {'total': len(jobs), 'completed': 0, 'cached': 0, 'failed': 0, 'current': None, 'ordering': 'explicit priorities, preferred prefixes, then descending duration'}
    atomic(out/'progress.json', summary)
    for path, source_duration, audio_duration, error, window in jobs:
        name = path.relative_to(args.library).as_posix()
        suffix = '' if window is None else f'\n{window[0]:.6f} {window[1]:.6f}'
        key = hashlib.sha256((name+suffix).encode()).hexdigest()[:12]
        dest = out/(path.stem + '-' + key + '.json')
        summary['current'] = name; atomic(out/'progress.json', summary)
        try:
            if error: raise RuntimeError(error)
            if window is not None and (audio_duration is None or window[1] > audio_duration+1e-6):
                raise ValueError('Selected window exceeds the source audio stream')
            duration = source_duration if window is None else window[1]-window[0]
            source_window = None if window is None else {'in':window[0],'out':window[1]}
            sha = fingerprint(path)
            model_id = {'path': str(args.model.resolve()), 'size': args.model.stat().st_size, 'mtime_ns': args.model.stat().st_mtime_ns}
            if dest.exists():
                old = json.loads(dest.read_text())
                if old.get('source', {}).get('sha256') == sha and old.get('source_window') == source_window and old.get('model') == model_id and old.get('engine_version') == ENGINE_VERSION and {**{'language':'auto','chunk_seconds':0,'align':False}, **old.get('settings', {})} == settings and old.get('status') in ('transcribed','no_audio','digital_silence'):
                    summary['cached'] += 1; atomic(out/'progress.json', summary); continue
            record = {'schema_version': 1, 'engine_version': ENGINE_VERSION, 'source': {'relative_path': name, 'sha256': sha, 'duration_seconds': source_duration}, 'model': model_id, 'backend': 'whisper.cpp', 'settings': settings, 'recognition': 'unreviewed; verify against audio', 'status': None, 'detected_language': None, 'segments': [], 'review_flags': []}
            if window is not None:
                record.update(source_window=source_window,timestamp_basis='window_relative')
            if audio_duration is None:
                record['status'] = 'no_audio'
            else:
                wav_key = sha if not suffix else hashlib.sha256((sha+suffix).encode()).hexdigest()
                wav = cache/(wav_key + '.wav')
                if not wav.exists():
                    with tempfile.TemporaryDirectory(dir=cache) as temp:
                        tmpwav = Path(temp)/'source.wav'
                        trim_in = [] if window is None else ['-ss',f'{window[0]:.6f}']
                        trim_out = [] if window is None else ['-t',f'{duration:.6f}']
                        run(['ffmpeg','-v','error','-n',*trim_in,'-protocol_whitelist','file','-i',str(path),
                             *trim_out,'-map','0:a:0','-vn','-ac','1','-ar','16000','-c:a','pcm_s16le',str(tmpwav)])
                        tmpwav.replace(wav)
                if effectively_silent(wav):
                    record['status'] = 'digital_silence'
                    record['review_flags'] = ['digital_silence_detected']
                    atomic(dest, record)
                    summary['completed'] += 1
                    print(f"{summary['completed']}/{len(jobs)} {name} DIGITAL SILENCE", flush=True)
                    atomic(out/'progress.json', summary)
                    continue
                with tempfile.TemporaryDirectory(dir=out) as td:
                    prefix = Path(td)/'whisper'
                    with wave.open(str(wav), 'rb') as wf:
                        wav_duration = wf.getnframes() / wf.getframerate()
                    step = args.chunk_seconds or max(wav_duration, 0.001)
                    starts = [i * step for i in range(max(1, int((wav_duration + step - 0.000001) // step)))]
                    chunks, segments, chunk_boundary_issue = [], [], False
                    for i, start in enumerate(starts):
                        audio = wav
                        if args.chunk_seconds:
                            audio = Path(td)/f'chunk-{i}.wav'
                            run(['ffmpeg','-v','error','-n','-ss',str(start),'-protocol_whitelist','file',
                                 '-i',str(wav),'-map','0:a:0','-t',str(step),'-c:a','pcm_s16le',str(audio)])
                        cmd = [args.whisper, '-m',str(args.model),'-f',str(audio),'-l',args.language,'-ojf','-of',str(prefix),'-np']
                        cmd += ['-dtw','large.v3','-nfa'] if args.align else ['-ml','1','-sow']
                        run(cmd)
                        raw = json.loads(prefix.with_suffix('.json').read_text(errors='replace'))
                        language = raw.get('result',{}).get('language')
                        chunks.append({'start_seconds': start, 'end_seconds': min(start + step, wav_duration), 'detected_language': language})
                        for segment in raw.get('transcription',[]):
                            if args.chunk_seconds and segment.get('offsets', {}).get('to', 0) > (min(step, wav_duration - start) + 0.5) * 1000:
                                chunk_boundary_issue = True
                            shift = round(start * 1000)
                            for item in [segment] + segment.get('tokens', []):
                                if 'offsets' in item:
                                    item['offsets']['from'] += shift
                                    item['offsets']['to'] += shift
                                # Original clock strings are chunk-relative; offsets are canonical.
                                if shift: item.pop('timestamps', None)
                                if shift and item.get('t_dtw', -1) >= 0: item['t_dtw'] += round(start * 100)
                            segment['detected_language'] = language
                            segments.append(segment)
                record['status'] = 'transcribed'
                record['detected_language'] = chunks[0]['detected_language'] if len(chunks) == 1 else None
                record['language_chunks'] = chunks
                record['segments'] = segments
                record['review_flags'] = flags_for(segments, duration)
                if args.align:
                    record['words'], dtw_flags = normalize_dtw(segments, duration)
                    record['review_flags'].extend(dtw_flags)
                else:
                    record['words'] = [{'text': s['text'].strip(), 'start_seconds': s['offsets']['from']/1000, 'end_seconds': s['offsets']['to']/1000} for s in segments if s.get('text','').strip()]
                if chunk_boundary_issue: record['review_flags'].append('timestamp_beyond_chunk')
                if args.language == 'auto': record['review_flags'].append('language_and_code_switch_require_listening')
            atomic(dest, record)
            summary['completed'] += 1
            print(f"{summary['completed']}/{len(jobs)} {name} {record['detected_language']} {' '.join(s['text'].strip() for s in record['segments'])[:300]} FLAGS={record['review_flags']}", flush=True)
        except Exception as e:
            summary['failed'] += 1
            print(f'FAILED {name}: {e}', file=sys.stderr, flush=True)
        atomic(out/'progress.json', summary)
    summary['current'] = None; atomic(out/'progress.json', summary)
    return bool(summary['failed'])
if __name__ == '__main__': sys.exit(main())
