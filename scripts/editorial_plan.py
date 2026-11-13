"""Cheap pre-render checks of authored story decisions; never semantic approval."""
import math
from pathlib import Path


def audit(recipe):
    fps = recipe['fps']
    required = recipe.get('editorial_required', False)
    findings, shots, seen = [], [], {}
    cursor = 0
    def finding(code, at, message):
        findings.append(dict(code=code, at_seconds=at/fps, finding=message))
    for bi, block in enumerate(recipe['blocks']):
        block_start = cursor
        for pi, picture in enumerate(block['pictures']):
            count = round(picture['duration']*fps)
            shot = dict(block=bi, picture=pi, start_frame=cursor, end_frame=cursor+count,
                        file=picture['file'], moment=picture.get('moment'), subjects=picture.get('subjects', []))
            shots.append(shot)
            if required:
                for key in ('moment', 'purpose', 'end_reason'):
                    if not isinstance(picture.get(key), str) or not picture[key].strip():
                        finding('missing_decision', cursor, f'Picture {bi}:{pi} needs {key}')
                if not isinstance(shot['subjects'], list) or not shot['subjects'] or not all(isinstance(s,str) and s.strip() for s in shot['subjects']):
                    finding('missing_subjects', cursor, f'Picture {bi}:{pi} needs visible subjects')
                if count > 6*fps and block.get('audio_role') not in ('native', 'native_dialogue') and not picture.get('hold_reason'):
                    finding('long_hold', cursor, f'Picture {bi}:{pi}: explain the action/payoff supporting a hold over six seconds')
            moment = picture.get('moment')
            if isinstance(moment, str) and moment in seen and seen[moment] != cursor and not picture.get('repeat_reason'):
                finding('repeated_moment', cursor, f'{moment}: nonadjacent reuse needs a distinct story payoff')
            if isinstance(moment, str): seen[moment] = cursor+count
            source = str((Path(recipe.get('album', '.'))/picture['file']).resolve())
            start = float(picture.get('in', 0)); end = start+picture['duration']*float(picture.get('speed',1))
            for prev in shots[:-1]:
                if prev['source'] == source and min(end,prev['source_end'])-max(start,prev['source_start']) > 1/fps and not picture.get('repeat_reason'):
                    finding('repeated_source', cursor, f'Picture {bi}:{pi} reuses a selected source window; inspect before approving')
                    break
            shot.update(source=source, source_start=start, source_end=end)
            cursor += count
        cues = block.get('picture_cues')
        if required and cues is None:
            finding('missing_cue_map', block_start, f'Block {bi}: provide picture_cues (empty only for speech without concrete visual cues)')
        if cues is not None and (not isinstance(cues,list) or not all(isinstance(c,dict) for c in cues)):
            raise ValueError('picture_cues must be a list of objects')
        for cue in cues or []:
            at = cue.get('at'); subject = cue.get('subject')
            if type(at) not in (int,float) or not math.isfinite(at) or not 0 <= at < (cursor-block_start)/fps or not isinstance(subject,str) or not subject.strip():
                finding('invalid_cue', block_start, f'Block {bi}: cue needs block-relative at and subject'); continue
            frame = block_start+math.floor(at*fps)
            visible = [s for s in shots if s['block']==bi and s['start_frame'] <= frame < s['end_frame']]
            compositions = [c for c in recipe.get('photo_compositions',[]) if round(c['at']*fps) <= frame < round(c['at']*fps)+round(c['duration']*fps)]
            if compositions:
                # Declare what is visible in the final composite, including any exposed base picture.
                visible = compositions
            if not any(isinstance(s.get('subjects'),list) and subject in s['subjects'] for s in visible):
                finding('cue_mismatch', frame, f'Block {bi}: {subject!r} is not declared on the picture at the spoken cue')
        if required and not block.get('selection_evidence'):
            finding('missing_selection', block_start, f'Block {bi}: record inspected alternatives and why these sources won')
    return dict(status='needs_decisions' if findings else ('plan_consistent' if required else 'legacy_unverified'),
                required=required, findings=findings, shots=shots,
                limitation='Checks authored metadata and timing only. Actual subjects, best-source choice, full actions, crops, motion and listening require render review.')


def require_plan(recipe):
    result = audit(recipe)
    if result['required'] and result['findings']:
        detail = '; '.join(f"{f['at_seconds']:.2f}s {f['finding']}" for f in result['findings'][:8])
        raise ValueError('Editorial plan incomplete: '+detail)
    return result
