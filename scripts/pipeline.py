"""Reusable local reel renderer. Originals are never modified or uploaded."""
from __future__ import annotations
import argparse, concurrent.futures as cf, datetime, hashlib, json, math, subprocess, sys, shutil
from fractions import Fraction
from functools import lru_cache
from pathlib import Path
from tempfile import TemporaryDirectory
import xml.etree.ElementTree as ET
from PIL import Image, ImageOps, ImageDraw, ImageFont, ImageFilter
import numpy as np
from check_finalcut import check_timeline
import motion_graphics
import transition_graphics
import photo_stack
from photo_io import open_photo
import playful_motion
from quality_gate import MODEL, REVIEW_FILES, sha256_file, reviewer_effort, write_review_request
from pipeline_paths import guard_output_tree, movie_path, recipe_mode, safe_component, timeline_path

from media_library import ROOT, TRIP, library_root, catalog_dir
SCRIPT_VERSION='1.1.0'
FULL_FFMPEG = Path('/opt/homebrew/opt/ffmpeg-full/bin')


@lru_cache(maxsize=None)
def ffmpeg_binary(*required_filters):
    candidates = [path for path in (shutil.which('ffmpeg'), FULL_FFMPEG/'ffmpeg') if path and Path(path).is_file()]
    for path in candidates:
        if not required_filters:
            return str(path)
        listing = subprocess.run([path, '-hide_banner', '-filters'], capture_output=True, text=True)
        available = {fields[1] for line in listing.stdout.splitlines()
                     if len(fields := line.split()) >= 3}
        if listing.returncode == 0 and all(name in available for name in required_filters):
            return str(path)
    need = ', '.join(required_filters)
    raise RuntimeError(f'FFmpeg needs the following filters: {need}. Install ffmpeg-full or use a capable build.'
                       if need else 'FFmpeg was not found. Run Setup.command.')


def current_recipe():
    p=ROOT/'CURRENT_EDIT.json'
    return load(p)['recipe'] if p.exists() else 'config/reel_v01.json'
def command(args,log=None):
    args=list(args)
    if args[0] == 'ffmpeg':
        needs_zscale = any(flag in ('-vf', '-filter_complex') and 'zscale=' in str(value)
                           for flag, value in zip(args, args[1:]))
        args[0] = ffmpeg_binary('zscale') if needs_zscale else ffmpeg_binary()
    if args[0] == 'ffprobe' and shutil.which('ffprobe') is None and (FULL_FFMPEG/'ffprobe').is_file():
        args[0] = FULL_FFMPEG/'ffprobe'
    r=subprocess.run([str(x) for x in args],capture_output=True,text=True)
    if log: Path(log).write_text(r.stdout+r.stderr)
    if r.returncode: raise RuntimeError(f'Command failed: {args[0]}\n{r.stderr[-3500:]}')
    return r.stdout+r.stderr
def load(p): return json.loads(Path(p).read_text())
def save(p,d): Path(p).write_text(json.dumps(d,indent=2,ensure_ascii=False)+'\n')
def stamp(): return datetime.datetime.now(datetime.timezone.utc).isoformat()
def rational(n,d=30):
    f=Fraction(n,d); return f'{f.numerator}/{f.denominator}s'
def fingerprint(shot,meta,dimensions):
    return hashlib.sha256(json.dumps([SCRIPT_VERSION,shot,meta['key'],dimensions],sort_keys=True).encode()).hexdigest()[:20]
def recipe_hash(recipe):
    return hashlib.sha256(json.dumps(recipe, sort_keys=True).encode()).hexdigest()
def probe(p): return json.loads(command(['ffprobe','-v','error','-protocol_whitelist','file','-show_format','-show_streams','-of','json',p]))
def album_media(album, name):
    source = (album / name).resolve()
    if not source.is_relative_to(album.resolve()) or not source.is_file():
        raise ValueError(f'Missing or outside-album media: {name}')
    return source

def source_path(meta,library=None):
    album=library_root(library)
    manifest=catalog_dir(library)/'sdr_manifest.json'
    if manifest.exists():
        match=next((x for x in load(manifest)['files'] if x['source']==meta['file'] and x['source_key']==meta['key']),None)
        if match and (album/match['standardized']).exists(): return album_media(album,match['standardized']),match['converted']
    return album_media(album,meta['file']),False

def normalized_photo(meta,library=None):
    key = safe_component(meta['key'], 'photo cache key')
    out=ROOT/'cache'/f'{key}_oriented.png'
    if not out.exists():
        with open_photo(album_media(library_root(library),meta['file'])) as image:
            ImageOps.exif_transpose(image).convert('RGB').save(out)
    return out
def prepared_photo(shot,recipe,meta):
    """Resample the original once; keep short stills free of zoompan softening."""
    key=fingerprint(shot,meta,[recipe['width'],recipe['height'],recipe['fps']])
    out=ROOT/'cache'/f'photo_frame_{key}.png'
    if out.exists(): return out
    im=Image.open(normalized_photo(meta,recipe.get('media_library'))).convert('RGB');W,H=recipe['width'],recipe['height']
    if shot.get('photo_layout')=='duo':
        # Two distinct full photographs on a clean contact-sheet surface.
        other=shot['photo_companion'];im2=Image.open(normalized_photo(other,recipe.get('media_library'))).convert('RGB')
        board=Image.new('RGB',(W,H),(248,242,228))
        for picture,yy in ((im,65),(im2,H//2+15)):
            fg=ImageOps.contain(picture,(W-92,H//2-94),method=Image.Resampling.LANCZOS)
            board.paste(fg,((W-fg.width)//2,yy+(H//2-94-fg.height)//2))
        im=board
    elif shot.get('photo_layout')=='print':
        back=ImageOps.fit(im,(W,H),method=Image.Resampling.LANCZOS).filter(ImageFilter.GaussianBlur(30))
        back=Image.blend(back,Image.new('RGB',(W,H),(14,17,15)),.42)
        fg=ImageOps.contain(im,(W-108,H-260),method=Image.Resampling.LANCZOS)
        fg=ImageOps.expand(fg,border=10,fill=(245,242,230));back.paste(fg,((W-fg.width)//2,(H-fg.height)//2));im=back
    else:
        iw,ih=im.size;target=W/H
        if iw/ih>target:
            cw=ih*target;left=(iw-cw)*shot['crop_x'];box=(left,0,left+cw,ih)
        else:
            ch=iw/target;top=(ih-ch)*shot['crop_y'];box=(0,top,iw,top+ch)
        im=im.resize((W,H),resample=Image.Resampling.LANCZOS,box=box)
        if shot.get('photo_sharpen',False): im=im.filter(ImageFilter.UnsharpMask(radius=.8,percent=75,threshold=3))
    im.save(out);return out
def require(condition, message):
    if not condition:
        raise ValueError(message)


def reel_frame_count(recipe):
    fps, duration = recipe['fps'], recipe['duration']
    require(type(fps) is int and fps > 0, 'FPS must be a positive integer')
    require(type(duration) in (int, float) and math.isfinite(duration) and duration > 0,
            'Duration must be finite and positive')
    return round(duration * fps)


def companion_photos(shot):
    return [*shot.get('photo_stack', []), *([shot['photo_companion']] if shot.get('photo_companion') else [])]


def reel_inputs(recipe, media):
    library = recipe.get('media_library')
    album = library_root(library)
    inputs = [ROOT / recipe['music']['file'], ROOT / recipe.get('public_review', 'config/public_review.json'),
              catalog_dir(library) / 'media.json', catalog_dir(library) / 'sdr_manifest.json']
    for shot in recipe['shots']:
        original = media[shot['media_id']]
        inputs.extend(album_media(album, item['file']) for item in [original, *companion_photos(shot)])
        if not original['photo']:
            inputs.append(source_path(original, library)[0])
    for title in [*recipe['titles'], recipe.get('cover_title', {})]:
        if title.get('font'):
            inputs.append(Path(title['font']))
    return album, inputs


def guard_reel_output(path, album, inputs, writable):
    # Legacy installations may place the pipeline itself in the album.
    if any(Path(path).resolve().is_relative_to(ROOT/folder) for folder in ('cache', 'exports', 'review')):
        album = None
    return guard_output_tree(path, inputs, album=album, writable=writable)


def validate(recipe, media, approval=False):
    fps = recipe['fps']
    expected = reel_frame_count(recipe)
    checks = load(ROOT / recipe.get('public_review', 'config/public_review.json')) if approval else {}
    blocked = set(checks.get('excluded_files', []))
    total = 0
    shot_ids = set()
    files = []
    for shot in recipe['shots']:
        ident = safe_component(shot['id'], 'shot ID')
        require(ident not in shot_ids, f'Duplicate shot ID: {ident}')
        shot_ids.add(ident)
        m = media[shot['media_id']]
        require(m['file'] == shot['file'], f'Stale media ID: {ident}')
        require(type(shot['frames']) is int and shot['frames'] > 0 and math.isfinite(shot['in']) and shot['in'] >= 0,
                f'Invalid source start or frame count: {ident}')
        require(type(shot['start_frame']) is int and shot['start_frame'] == total, f'Timeline gap at {ident}')
        require(math.isfinite(shot['speed']) and shot['speed'] > 0, f'Invalid speed: {ident}')
        require(all(math.isfinite(shot[k]) and 0 <= shot[k] <= 1 for k in ('crop_x', 'crop_y')),
                f'Invalid crop: {ident}')
        require(all(math.isfinite(shot['grade'][k]) for k in ('brightness', 'saturation', 'contrast')),
                f'Invalid grade: {ident}')
        if shot.get('photo_layout') == 'stack':
            companions = shot.get('photo_stack', [])
            require(m['photo'] and len(companions) == 2, 'Photo stack needs a primary photo and two companions')
            require(len({m['file'], *(c['file'] for c in companions)}) == 3, 'Photo stack needs three distinct photos')
        companions = companion_photos(shot)
        for companion in companions:
            item = media.get(companion['id'], {})
            require(item.get('photo') and item.get('file') == companion['file'] and item.get('key') == companion['key'],
                    'Stale companion photo metadata')
        if not m['photo']:
            source_frames = shot['frames']
            if shot.get('playful_focus'):
                source_frames = playful_motion.source_frame(shot['frames'] - 1, shot['playful_focus']) + 1
            require(shot['in'] + source_frames / fps * shot['speed'] <= m['duration'] - .015,
                    f'Source too short: {ident}')
        selected = [m['file'], *(companion['file'] for companion in companions)]
        if approval:
            for name in selected:
                require(name not in blocked, f'Excluded private file: {name}')
            key = fingerprint(shot, m, [recipe['width'], recipe['height'], fps])
            require(checks.get('approved_windows', {}).get(ident) == key, f'Needs visual public-content review: {ident}')
        files.extend(selected)
        total += shot['frames']
    require(total > 0 and total == expected, f'Shot frames total {total}; expected {expected}')
    if recipe.get('unique_sources'):
        require(len(files) == len(set(files)), 'Repeated source file in a unique-moment edit')
    for title in recipe['titles']:
        require('\n' not in title['headline'], 'Keep titles on one line')
        require(0 <= title['start'] < title['end'] <= recipe['duration'], 'Title is outside the timeline')
        require(round(title['end'] * fps) > round(title['start'] * fps), 'Title must span at least one frame')
    boundaries = {shot['start_frame']: i for i, shot in enumerate(recipe['shots']) if i}
    transition_ids = set()
    for transition in recipe.get('transitions', []):
        ident = transition['id']
        require(ident not in transition_ids, 'Transition IDs must be unique')
        transition_ids.add(ident)
        require(transition['cut_frame'] in boundaries, 'Transition must be centered on a shot cut')
        count = transition['duration_frames']
        require(type(count) is int and count >= 4 and count % 2 == 0,
                'Transition needs an even count of at least four frames')
        index = boundaries[transition['cut_frame']]
        require(count // 2 <= min(recipe['shots'][index-1]['frames'], recipe['shots'][index]['frames']),
                'Transition extends past an adjacent shot')
    music = ROOT / recipe['music']['file']
    require(music.is_file(), f'Missing music: {music}')
    require(0 <= recipe['music']['in'] <= float(probe(music)['format']['duration']) - total / fps,
            'Music excerpt is outside its source')
    return total
def review_windows(recipe,media):
    validate(recipe, media)
    movie_path(recipe)
    album, inputs = reel_inputs(recipe, media)
    dimensions = [recipe['width'], recipe['height'], recipe['fps']]
    cache_names = []
    for shot in recipe['shots']:
        meta = media[shot['media_id']]
        key = fingerprint(shot, meta, dimensions)
        cache_names.extend(f'window_{key}_{k}.jpg' for k in range(5))
        if meta['photo']:
            cache_names.append(f"{safe_component(meta['key'], 'photo cache key')}_oriented.png")
    reviewdir = reel_review_dir(recipe)
    sheets = [f"selected_{recipe['version']}_{i+1:02d}.jpg" for i in range((len(recipe['shots'])+6)//7)]
    guard_reel_output(ROOT/'cache', album, inputs, cache_names).mkdir(parents=True, exist_ok=True)
    guard_reel_output(reviewdir, album, inputs, sheets).mkdir(parents=True, exist_ok=True)
    rows=[]
    def one(shot):
        m=media[shot['media_id']]; frames=[]
        for k,part in enumerate((.02,.25,.5,.75,.98)):
            out=ROOT/'cache'/f"window_{fingerprint(shot,m,dimensions)}_{k}.jpg"
            if not out.exists():
                if m['photo']:
                    ImageOps.contain(Image.open(normalized_photo(m,recipe.get('media_library'))),(240,320)).save(out)
                else:
                    t=shot['in']+shot['frames']/recipe['fps']*shot['speed']*part
                    command(['ffmpeg','-v','error','-threads','1','-ss',t,'-protocol_whitelist','file','-i',source_path(m,recipe.get('media_library'))[0],'-map','0:v:0','-frames:v','1','-vf','scale=240:320:force_original_aspect_ratio=decrease','-threads','1','-y',out])
            frames.append(out)
        return shot,frames
    with cf.ThreadPoolExecutor(max_workers=6) as pool: rows=list(pool.map(one,recipe['shots']))
    font=ImageFont.truetype('/System/Library/Fonts/Supplemental/Arial.ttf',18)
    for start in range(0,len(rows),7):
        batch=rows[start:start+7]; sheet=Image.new('RGB',(1250,355*len(batch)),(19,19,19));d=ImageDraw.Draw(sheet)
        for j,(s,paths) in enumerate(batch):
            d.text((7,j*355+3),f"{s['id']} {s['media_id']} {s['in']:.2f}s + {s['frames']/recipe['fps']:.2f}s | {s['note']}",font=font,fill='white')
            for k,p in enumerate(paths):
                im=Image.open(p); sheet.paste(im,(k*250+(240-im.width)//2,j*355+29))
        sheet.save(reviewdir/f"selected_{recipe['version']}_{start//7+1:02d}.jpg",quality=87)
    print(f'Review sheets written to {reviewdir}. Record approval after visual inspection.')


def reel_review_dir(recipe):
    folder = ROOT/'review'
    if recipe.get('workflow') == 'personal-reel':
        folder = folder/safe_component(recipe['project_slug'], 'project_slug')/safe_component(recipe['version'], 'version')
    return folder
def title_png(title,index,outdir,W,H):
    out=outdir/f'title_{index:02d}.png'
    if title.get('style') in ('editorial','sticker'):
        base=Image.new('RGBA',(W,H));d=ImageDraw.Draw(base)
        size=title['size'];fontpath=title['font'];fontindex=title.get('font_index',0)
        while True:
            font=ImageFont.truetype(fontpath,size,index=fontindex)
            box=d.textbbox((0,0),title['headline'],font=font)
            if box[2]-box[0]<=W-180:break
            size-=2
        tw=box[2]-box[0];th=box[3]-box[1];x=title.get('x',(W-tw)//2);y=title['y']
        if title['style']=='sticker':
            d.rounded_rectangle((x-27,y-19,x+tw+27,y+th+21),radius=13,fill=tuple(title.get('paper',[240,248,153,255])))
            d.text((x-box[0],y-box[1]),title['headline'],font=font,fill=(32,44,36,255))
        else:
            d.text((x-box[0]+1,y-box[1]+3),title['headline'],font=font,fill=(20,25,20,100),stroke_width=1)
            d.text((x-box[0],y-box[1]),title['headline'],font=font,fill=tuple(title.get('ink',[255,249,229,255])))
        base.save(out);return out
    base=Image.new('RGBA',(W,H));a=np.zeros((H,W),dtype=np.uint8)
    y=title['y']; lower=max(0,y-100); upper=min(H,y+240)
    for r in range(lower,upper):
        distance=abs(r-(y+90))/max(1,(upper-lower)/2)
        a[r,:]=int(title.get('shade',75)*max(0,1-distance))
    gradient=Image.new('RGBA',(W,H),(0,0,0,0));gradient.putalpha(Image.fromarray(a));base=Image.alpha_composite(base,gradient)
    ink=Image.new('RGBA',(W,H));d=ImageDraw.Draw(ink)
    headline=title['headline']; size=title['size']
    while True:
        f=ImageFont.truetype(title.get('font','/System/Library/Fonts/Supplemental/DIN Condensed Bold.ttf'),size)
        bb=d.textbbox((0,0),headline,font=f)
        if bb[2]-bb[0]<=W-180: break
        size-=2
    def centered(text,font,yy,fill):
        b=d.textbbox((0,0),text,font=font);xx=title.get('x',(W-(b[2]-b[0]))/2)
        d.text((xx,yy-b[1]),text,font=font,fill=fill,stroke_width=1,stroke_fill=(0,0,0,60))
    kicker=title.get('kicker','')
    if kicker:centered(kicker,ImageFont.truetype('/System/Library/Fonts/Supplemental/Arial Bold.ttf',28),y,(255,237,205,255))
    centered(headline,f,y+(58 if kicker else 0),(255,255,255,255))
    shadow=Image.new('RGBA',(W,H));shadow.paste(ink,(0,3));shadow=shadow.filter(ImageFilter.GaussianBlur(4))
    # Black drop shadow follows the text alpha only.
    black=Image.new('RGBA',(W,H),(0,0,0,0));black.putalpha(shadow.getchannel('A'))
    Image.alpha_composite(Image.alpha_composite(base,black),ink).save(out)
    return out
def render_shot(shot,recipe,meta,outdir):
    key=fingerprint(shot,meta,[recipe['width'],recipe['height'],recipe['fps']])
    out=outdir/f"{shot['id']}_{key}.mp4"
    if out.exists(): return out
    W,H,fps=recipe['width'],recipe['height'],recipe['fps']
    if shot.get('photo_layout')=='stack':
        paths=[normalized_photo(m,recipe.get('media_library')) for m in [meta,*shot['photo_stack']]]
        return photo_stack.render(paths,out,shot['frames'],fps,W,H,shot['grade'],ffmpeg_binary(),
                                  layout=shot.get('photo_stack_layout','legacy'),
                                  animation=shot.get('photo_stack_animation'))
    args=['ffmpeg','-v','error','-threads','2']
    if meta['photo']: args+=['-loop','1','-framerate',str(fps),'-i',str(prepared_photo(shot,recipe,meta))]
    else:
        source,converted=source_path(meta,recipe.get('media_library'))
        args+=['-ss',str(shot['in']),'-protocol_whitelist','file','-i',str(source)]
    vf=[]
    if not meta['photo'] and meta.get('color_transfer') in ('smpte2084','arib-std-b67') and not converted:
        vf+=['zscale=t=linear:npl=100','format=gbrpf32le','tonemap=tonemap=hable:desat=0','zscale=p=bt709:t=bt709:m=bt709:r=limited','format=yuv420p']
    if shot['speed']!=1: vf+=[f"setpts=(PTS-STARTPTS)/{shot['speed']}"]
    else: vf+=['setpts=PTS-STARTPTS']
    if not meta['photo']:
        if shot.get('transpose'):
            require(shot['transpose'] in ('clock','cclock'), 'Unsupported transpose direction')
            vf += [f"transpose={shot['transpose']}"]
        vf += [f'scale={W}:{H}:force_original_aspect_ratio=increase:flags=lanczos',f"crop={W}:{H}:(iw-ow)*{shot['crop_x']}:(ih-oh)*{shot['crop_y']}"]
    grade=shot['grade']; vf+=[f"eq=brightness={grade['brightness']}:saturation={grade['saturation']}:contrast={grade['contrast']}",f'fps={fps}','setsar=1','format=yuv420p']
    if shot.get('playful_focus'):
        ffmpeg=ffmpeg_binary('zscale') if vf[0].startswith('zscale=') else ffmpeg_binary()
        args[0]=ffmpeg
        cfg=shot['playful_focus']
        needed=playful_motion.source_frame(shot['frames']-1,cfg)+1
        decode=args+['-map','0:v:0','-vf',','.join(vf),'-frames:v',str(needed),'-an','-pix_fmt','rgb24','-f','rawvideo','pipe:1']
        return playful_motion.render(decode,out,shot['frames'],fps,W,H,cfg,ffmpeg,shot.get('crf',17))
    args+=['-map','0:v:0','-vf',','.join(vf),'-frames:v',str(shot['frames']),'-an','-c:v','libx264','-preset','fast','-crf',str(shot.get('crf',17)),'-threads','2','-pix_fmt','yuv420p','-color_primaries','bt709','-color_trc','bt709','-colorspace','bt709','-video_track_timescale','30000','-movflags','+faststart','-y',str(out)]
    temp=out.with_suffix('.partial.mp4');args[-1]=str(temp)
    command(args,ROOT/'cache'/f"{shot['id']}.render.log");temp.replace(out)
    return out
def mix_music(recipe,outdir):
    out=outdir/'music.wav';duration=reel_frame_count(recipe)/recipe['fps']
    common=['ffmpeg','-v','info','-ss',str(recipe['music']['in']),'-t',str(duration),'-protocol_whitelist','file','-i',ROOT/recipe['music']['file'],'-map','0:a:0','-vn']
    fade_out=float(recipe['music'].get('fade_out',.65))
    require(0 < fade_out <= duration, 'Music fade must fit the reel')
    fade=f'afade=t=in:d=0.035,afade=t=out:st={duration-fade_out}:d={fade_out}'
    first=command(common+['-af',fade+',loudnorm=I=-14:TP=-1:LRA=9:print_format=json','-f','null','-'],ROOT/'cache/music_measure.log')
    data=json.loads(first[first.rfind('{'):first.rfind('}')+1])
    norm=f"loudnorm=I=-14:TP=-1:LRA=9:measured_I={data['input_i']}:measured_TP={data['input_tp']}:measured_LRA={data['input_lra']}:measured_thresh={data['input_thresh']}:offset={data['target_offset']}:linear=true:print_format=json"
    command(common+['-af',fade+','+norm,'-ar','48000','-ac','2','-c:a','pcm_s24le','-y',out],ROOT/'cache/music_normalize.log')
    return out
def finalcut(recipe,segments,titles,music,outdir,transitions=(), *, reviewed_movie=None):
    from finalcut_gate import require_finalcut_approval
    movie = Path(reviewed_movie) if reviewed_movie is not None else movie_path(recipe)
    require_finalcut_approval(recipe, movie)
    out = timeline_path(recipe, movie)
    require(Path(outdir).resolve() == out.parent.resolve(), 'Final Cut outputs must share the reviewed movie folder')
    require(len(segments) == len(recipe['shots']) and len(titles) == len(recipe['titles'])
            and len(transitions) == len(recipe.get('transitions', [])), 'Saved timeline media count differs from the recipe')
    guard_output_tree(outdir, writable=(out.name, 'finalcut_validation.txt', 'finalcut_export_checks.json'))
    doc=ET.Element('fcpxml',version='1.10');res=ET.SubElement(doc,'resources')
    fps=recipe['fps']; duration=rational(round(recipe['duration']*fps),fps)
    orientation='Landscape' if recipe['width']>=recipe['height'] else 'Vertical'
    ET.SubElement(res,'format',id='r1',name=f"{orientation}{recipe['width']}x{recipe['height']}p{fps}",frameDuration=rational(1,fps),width=str(recipe['width']),height=str(recipe['height']),colorSpace='1-1-1 (Rec. 709)')
    for i,(s,p) in enumerate(zip(recipe['shots'],segments)):
        a=ET.SubElement(res,'asset',id=f'v{i}',name=f"{s['id']} · {s['note']}",start='0s',duration=rational(s['frames'],fps),hasVideo='1',format='r1')
        ET.SubElement(a,'media-rep',kind='original-media',src=p.as_uri())
    a=ET.SubElement(res,'asset',id='music',name=recipe['music']['track'],start='0s',duration=duration,hasAudio='1',audioSources='1',audioChannels='2',audioRate='48000')
    ET.SubElement(a,'media-rep',kind='original-media',src=music.as_uri())
    for i,p in enumerate(titles):
        t=recipe['titles'][i]
        title_duration=rational(round(t['end']*recipe['fps'])-round(t['start']*recipe['fps']),recipe['fps']) if t.get('style') in motion_graphics.STYLES else '0s'
        a=ET.SubElement(res,'asset',id=f't{i}',name=t['headline'],start='0s',duration=title_duration,hasVideo='1',format='r1')
        ET.SubElement(a,'media-rep',kind='original-media',src=p.as_uri())
    for i,p in enumerate(transitions):
        t=recipe['transitions'][i]
        a=ET.SubElement(res,'asset',id=f'x{i}',name=t['id'],start='0s',duration=rational(t['duration_frames'],recipe['fps']),hasVideo='1',format='r1')
        ET.SubElement(a,'media-rep',kind='original-media',src=p.as_uri())
    event_kind='YouTube' if recipe.get('workflow')=='commercial-youtube' else 'Vlogs' if 'blocks' in recipe else 'Reels'
    event_name=recipe.get('destination') or recipe['name']
    audio_role='dialogue' if 'blocks' in recipe else 'music'
    lib=ET.SubElement(doc,'library');event=ET.SubElement(lib,'event',name=f"{event_name} · {event_kind}")
    project=ET.SubElement(event,'project',name=f"{recipe['name']} · {recipe['version']}")
    seq=ET.SubElement(project,'sequence',format='r1',duration=duration,tcStart='0s',tcFormat='NDF',audioLayout='stereo',audioRate='48k')
    spine=ET.SubElement(seq,'spine')
    for i,s in enumerate(recipe['shots']):
        clip=ET.SubElement(spine,'asset-clip',ref=f'v{i}',name=f"{s['id']} · {s['note']}",offset=rational(s['start_frame'],fps),start='0s',duration=rational(s['frames'],fps))
        if i==0: ET.SubElement(clip,'audio',ref='music',lane='-1',offset='0s',start='0s',duration=duration,role=audio_role)
        for j,t in enumerate(recipe['titles']):
            start=round(t['start']*fps);end=round(t['end']*fps)
            if s['start_frame']<=start<s['start_frame']+s['frames']:
                ET.SubElement(clip,'video',ref=f't{j}',lane=str(j+1),offset=rational(start-s['start_frame'],fps),start='0s',duration=rational(end-start,fps),name=t['headline'])
        for j,t in enumerate(recipe.get('transitions', [])):
            start=t['cut_frame']-t['duration_frames']//2
            if s['start_frame']<=start<s['start_frame']+s['frames']:
                ET.SubElement(clip,'video',ref=f'x{j}',lane=str(len(titles)+j+1),offset=rational(start-s['start_frame'],recipe['fps']),start='0s',duration=rational(t['duration_frames'],recipe['fps']),name=t['id'])
    # FCP 12.4 aborts on nested generic asset-clips in this export.
    # Connected layers use their explicit audio/video element types.
    require(not doc.findall('.//asset-clip/asset-clip'), 'Connected layers must use audio/video nodes')
    ET.indent(doc)
    dtd=Path('/Applications/Final Cut Pro.app/Contents/Frameworks/Interchange.framework/Versions/A/Resources/FCPXMLv1_10.dtd')
    with TemporaryDirectory(prefix='.timeline-',dir=outdir) as scratch:
        candidate=Path(scratch)/out.name
        ET.ElementTree(doc).write(candidate,encoding='utf-8',xml_declaration=True)
        if dtd.exists():
            command(['xmllint','--noout','--dtdvalid',dtd.as_uri(),candidate],outdir/'finalcut_validation.txt')
        checks=check_timeline(candidate,recipe)
        checks.update(checked=stamp(),xml_sha256=sha256_file(candidate))
        candidate.replace(out)
    save(outdir/'finalcut_export_checks.json',checks)
    return out
def render(recipe, media, *, recipe_path=None):
    total = validate(recipe, media, approval=True)
    reviewer_effort(recipe)
    output = movie_path(recipe)
    album, inputs = reel_inputs(recipe, media)
    if recipe_path is not None:
        inputs.append(recipe_path)
    outdir = guard_reel_output(output.parent, album, inputs, (
        'media', 'edit_recipe.json', 'concat.txt', 'picture_clean.mp4', 'music.wav', 'render.log',
        'render_manifest.json', 'finalcut_export_status.json', output.name, *REVIEW_FILES,
    ))
    output = outdir / output.name
    dimensions = [recipe['width'], recipe['height'], recipe['fps']]
    cache_names = ['music_measure.log', 'music_normalize.log']
    for shot in recipe['shots']:
        original = media[shot['media_id']]
        cache_names.append(f"{shot['id']}.render.log")
        if original['photo']:
            cache_names.append(f'photo_frame_{fingerprint(shot, original, dimensions)}.png')
            for photo in [original, *companion_photos(shot)]:
                key = safe_component(photo['key'], 'photo cache key')
                cache_names.append(f'{key}_oriented.png')
    guard_reel_output(ROOT/'cache', album, inputs, cache_names).mkdir(parents=True, exist_ok=True)
    state_path=ROOT/'CURRENT_EDIT.json'
    active=load(state_path) if state_path.exists() else {}
    active_recipe = ROOT/active['recipe'] if active.get('recipe') else None
    active_match = active_recipe is not None and (
        active_recipe.resolve() == (ROOT/recipe_path).resolve() if recipe_path is not None
        else active_recipe.is_file() and load(active_recipe) == recipe
    )
    if active_match:
        guard_output_tree(ROOT, writable=(state_path.name,))
        active.update(status='rendering',finalcut_import_status='not_verified_for_new_export')
        active.pop('director_review', None)
        active.pop('director_score', None)
        save(state_path,active)
    outdir.mkdir(parents=True, exist_ok=True)
    shotdir=outdir/'media';shotdir.mkdir(exist_ok=True)
    with cf.ThreadPoolExecutor(max_workers=3) as pool:
        segments=list(pool.map(lambda s:render_shot(s,recipe,media[s['media_id']],shotdir),recipe['shots']))
    lines=[]
    for segment in segments:
        path = str(segment)
        require(not any(c in path for c in ('\r', '\n')), 'Concat paths must fit on one line')
        lines.append("file '" + path.replace("'", "'\\''") + "'")
    concat=outdir/'concat.txt';concat.write_text('\n'.join(lines)+'\n')
    clean=outdir/'picture_clean.mp4'
    command(['ffmpeg','-v','error','-protocol_whitelist','file','-f','concat','-safe','0','-i',concat,'-map','0:v:0','-c','copy','-an','-movflags','+faststart','-y',clean])
    music=mix_music(recipe,outdir)
    ffmpeg=ffmpeg_binary()
    titles=[motion_graphics.render(t,i,shotdir,recipe['width'],recipe['height'],recipe['fps'],ffmpeg) if t.get('style') in motion_graphics.STYLES else title_png(t,i,shotdir,recipe['width'],recipe['height']) for i,t in enumerate(recipe['titles'])]
    transitions=[]
    for i,t in enumerate(recipe.get('transitions', [])):
        p=shotdir/f'transition_{i:02d}.mov'
        transition_graphics.render_transition(t,p,fps=recipe['fps'],width=recipe['width'],height=recipe['height'],command_path=ffmpeg)
        transitions.append(p)
    args=['ffmpeg','-v','error','-i',clean,'-i',music]
    for p in titles: args+=['-i',p]
    for p in transitions: args+=['-i',p]
    # Assign the concat picture and animated overlays the same integer frame clock.
    frame_time_base = f"1/{recipe['fps']}"
    filters = [f'[0:v:0]settb={frame_time_base},setpts=N[picture]']
    prev = 'picture'
    for i,t in enumerate(recipe['titles']):
        start_frame=round(t['start']*recipe['fps']);end_frame=round(t['end']*recipe['fps'])
        label=f'o{i}'
        if t.get('style') in motion_graphics.STYLES:
            filters.append(f'[{i+2}:v:0]settb={frame_time_base},setpts=N+{start_frame}[title{i}]')
            filters.append(f"[{prev}][title{i}]overlay=0:0:eof_action=pass:enable='gte(n,{start_frame})*lt(n,{end_frame})'[{label}]")
        else:
            filters.append(f"[{prev}][{i+2}:v:0]overlay=0:0:enable='gte(n,{start_frame})*lt(n,{end_frame})'[{label}]")
        prev=label
    for i,t in enumerate(recipe.get('transitions', [])):
        start_frame=t['cut_frame']-t['duration_frames']//2;end_frame=start_frame+t['duration_frames']
        label=f'xout{i}'
        filters.append(f'[{i+2+len(titles)}:v:0]settb={frame_time_base},setpts=N+{start_frame}[transition{i}]')
        filters.append(f"[{prev}][transition{i}]overlay=0:0:eof_action=pass:enable='gte(n,{start_frame})*lt(n,{end_frame})'[{label}]")
        prev=label
    filters.append(f'[{prev}]setparams=color_primaries=bt709:color_trc=bt709:colorspace=bt709[video]')
    args += ['-filter_complex',';'.join(filters),'-map','[video]','-map','1:a:0','-t',str(total/recipe['fps']),'-r',str(recipe['fps']),'-c:v','libx264','-preset','medium','-crf','18','-threads','6','-pix_fmt','yuv420p','-color_primaries','bt709','-color_trc','bt709','-colorspace','bt709','-c:a','aac','-b:a','320k','-ar','48000','-movflags','+faststart','-map_metadata','-1','-y']
    with TemporaryDirectory(prefix='.render-', dir=outdir) as temporary:
        partial = Path(temporary) / output.name
        command([*args, partial], outdir/'render.log')
        movie_checks(partial, recipe, total)
        command(decode_command(partial))
        prepared_sha256 = {str(path.relative_to(outdir)): sha256_file(path)
                           for path in [*segments, *titles, *transitions, music]}
        partial.replace(output)
    request = write_review_request(recipe, output)
    save(outdir/'edit_recipe.json', recipe)
    save(outdir/'finalcut_export_status.json', {'status':'deferred_by_user','recreate':'pipeline.py export-finalcut --recipe RECIPE'})
    save(outdir/'render_manifest.json',{'created':stamp(),'pipeline_version':SCRIPT_VERSION,'recipe_sha256':recipe_hash(recipe),'output':str(output),'movie_sha256':request['movie_sha256'],'request_id':request['request_id'],'segments':[str(p) for p in segments],'titles':[str(p) for p in titles],'transitions':[str(p) for p in transitions],'music':str(music),'prepared_sha256':prepared_sha256,'source_audio':False})
    if active_match:
        active.update(status='awaiting_director_review',finalcut_import_status='not_verified_for_new_export')
        save(state_path,active)
    print(output)
    if recipe.get('finalcut_export', False):
        print('Final Cut is pending review and confirmation for this new render.')
def movie_checks(movie, recipe, expected_frames):
    data = probe(movie)
    videos = [stream for stream in data['streams'] if stream['codec_type'] == 'video']
    audios = [stream for stream in data['streams'] if stream['codec_type'] == 'audio']
    require(len(data['streams']) == 2 and len(videos) == len(audios) == 1,
            'Expected exactly one video stream and one audio stream')
    video, audio = videos[0], audios[0]
    checks = {'duration': float(data['format']['duration']), 'width': video['width'], 'height': video['height'],
              'fps': video['avg_frame_rate'], 'frames': int(video['nb_frames']),
              'video_codec': video['codec_name'], 'audio_codec': audio['codec_name'],
              'color_transfer': video.get('color_transfer')}
    require((checks['width'], checks['height']) == (recipe['width'], recipe['height']),
            'Movie geometry differs from the recipe')
    require(checks['frames'] == expected_frames and Fraction(checks['fps']) == recipe['fps'],
            'Movie frame count or frame rate differs from the recipe')
    duration = expected_frames / recipe['fps']
    require(abs(checks['duration'] - duration) < .08 and abs(float(video['duration']) - duration) < .001,
            'Movie duration differs from the output frame clock')
    require((video.get('color_primaries'), video.get('color_transfer'), video.get('color_space')) == ('bt709',)*3,
            'Movie lacks Rec.709 SDR stream tags')
    return checks


def decode_command(movie):
    return ['ffmpeg','-v','error','-xerror','-i',movie,'-map','0:v:0','-map','0:a:0','-f','null','-']


def current_render_request(recipe, movie, digest, manifest):
    request = load(movie.parent/'director_review_request.json')
    require(Path(request.get('movie', '')).resolve() == movie.resolve()
            and request.get('movie_sha256') == digest == manifest.get('movie_sha256')
            and request.get('request_id') and request['request_id'] == manifest.get('request_id')
            and request.get('version') == recipe['version']
            and request.get('reviewer_model') == MODEL
            and request.get('reasoning_effort') == reviewer_effort(recipe),
            'Movie and director request do not match the current render manifest')
    return request


def qa(recipe, media, *, recipe_path=None):
    total = validate(recipe, media, approval=True)
    movie = movie_path(recipe)
    album, inputs = reel_inputs(recipe, media)
    if recipe_path is not None:
        inputs.append(recipe_path)
    outdir = guard_reel_output(movie.parent, album, inputs, (
        'decode_check.txt', 'audio_check.txt', 'black_check.txt', 'qa_report.json',
    ))
    digest = sha256_file(movie)
    manifest_path = outdir/'render_manifest.json'
    manifest = load(manifest_path)
    require(manifest.get('recipe_sha256') == recipe_hash(recipe)
            and load(outdir/'edit_recipe.json') == recipe
            and Path(manifest.get('output', '')).resolve() == movie.resolve(),
            'Recipe does not match the saved render')
    request = current_render_request(recipe, movie, digest, manifest)
    checks = movie_checks(movie, recipe, total)
    command(decode_command(movie), outdir/'decode_check.txt')
    stats = command(['ffmpeg','-v','info','-i',movie,'-map','0:a:0','-af',
                     'loudnorm=I=-14:TP=-1:LRA=9:print_format=json','-f','null','-'], outdir/'audio_check.txt')
    audio = json.loads(stats[stats.rfind('{'):stats.rfind('}')+1])
    checks['audio_loudness'] = audio
    require(math.isfinite(float(audio['input_tp'])) and float(audio['input_tp']) <= -.4, 'Invalid audio or peak too high')
    black = command(['ffmpeg','-v','info','-i',movie,'-map','0:v:0','-vf',
                     'blackdetect=d=0.04:pix_th=0.07:pic_th=0.96','-an','-f','null','-'], outdir/'black_check.txt')
    checks['black_intervals'] = [line for line in black.splitlines() if 'black_start:' in line]
    reviewdir = guard_reel_output(reel_review_dir(recipe)/f"output_{recipe['version']}"/f'qa_{digest[:10]}',
                                 album, [*inputs, movie], ('frames',))
    reviewdir.mkdir(parents=True, exist_ok=True)
    with TemporaryDirectory(prefix='.samples-', dir=reviewdir) as temporary:
        frames_dir = Path(temporary)
        command(['ffmpeg','-v','error','-i',movie,'-map','0:v:0','-vf',
                 'fps=4,scale=180:320:force_original_aspect_ratio=decrease',
                 '-q:v','3','-y',frames_dir/'frame_%04d.jpg'])
        frames = sorted(frames_dir.glob('frame_*.jpg'))
        font = ImageFont.truetype('/System/Library/Fonts/Supplemental/Arial.ttf',15)
        for start in range(0, len(frames), 30):
            batch = frames[start:start+30]
            sheet = Image.new('RGB', (1080, 5*346), (20,20,20))
            draw = ImageDraw.Draw(sheet)
            for k, path in enumerate(batch):
                xx, yy = (k%6)*180, (k//6)*346
                with Image.open(path) as frame:
                    sheet.paste(frame, (xx+(180-frame.width)//2, yy+24))
                draw.text((xx+5,yy+3), f'{(start+k)/4:.2f}s', font=font, fill='white')
            sheet.save(frames_dir/f'contact_{start//30+1:02d}.jpg', quality=90)
        frames_out = reviewdir/'frames'
        frames_out.mkdir(exist_ok=True)
        for path in frames_dir.iterdir():
            path.replace(frames_out/path.name)
    require(sha256_file(movie) == digest and load(manifest_path) == manifest
            and load(outdir/'director_review_request.json') == request,
            'Movie, manifest or director request changed during QA')
    save(outdir/'qa_report.json', {'checked':stamp(), 'technical':checks, 'movie_sha256':digest,
                                 'request_id':request['request_id'], 'review_frames':str(reviewdir/'frames'),
                                 'visual_review':'pending inspection of output contact sheets and player',
                                 'public_content_review':'Recorded source windows match the selected recipe. Source audio is muted.'})
    print(json.dumps(checks, indent=2))


def export_finalcut(recipe):
    movie = movie_path(recipe)
    outdir = movie.parent
    manifest = load(outdir/'render_manifest.json')
    saved = load(outdir/'edit_recipe.json')
    digest = sha256_file(movie)
    require(manifest['recipe_sha256'] == recipe_hash(saved) and Path(manifest['output']).resolve() == movie.resolve(),
            'Saved reconstruction does not match the movie or recipe')
    current_render_request(saved, movie, digest, manifest)
    approval_fields = {'finalcut_review_report', 'finalcut_user_confirmation', 'finalcut_export'}
    require({k: v for k, v in recipe.items() if k not in approval_fields} ==
            {k: v for k, v in saved.items() if k not in approval_fields},
            'Current recipe differs from the saved cut. Use the matching recipe and review.')
    def generated(paths):
        files = [Path(path).resolve() for path in paths]
        require(all(path.is_file() and path.is_relative_to((outdir/'media').resolve()) for path in files),
                'Saved timeline references media outside its prepared directory')
        return files
    segments = generated(manifest['segments'])
    titles = generated(manifest['titles'])
    transitions = generated(manifest.get('transitions', []))
    music = outdir/'music.wav'
    require(Path(manifest['music']).resolve() == music.resolve() and music.is_file(), 'Saved mix is missing or misplaced')
    outdir = guard_output_tree(outdir, writable=('media', 'music.wav'))
    saved_hashes = manifest.get('prepared_sha256')
    require(isinstance(saved_hashes, dict), 'Saved reconstruction lacks prepared-media hashes. Render a fresh reviewable cut.')
    for path in [*segments, *titles, *transitions, music.resolve()]:
        require(saved_hashes.get(str(path.relative_to(outdir))) == sha256_file(path),
                f'Saved reconstruction media changed: {path.name}')
    return finalcut(recipe, segments, titles, music, outdir, transitions)


def main():
    ap=argparse.ArgumentParser();ap.add_argument('action',choices=['review','render','qa','export-finalcut']);ap.add_argument('--recipe',default=current_recipe());args=ap.parse_args()
    recipe=load(ROOT/args.recipe)
    if recipe_mode(recipe) == 'narrated_vlog':
        if args.action=='render':
            from vlog_render import render as render_vlog
            render_vlog(ROOT/args.recipe)
        elif args.action=='export-finalcut':
            print(command([sys.executable,ROOT/'scripts/vlog_render.py',ROOT/args.recipe,'--export-finalcut']))
        else:
            from vlog_review import review
            review(ROOT/args.recipe)
        return
    if args.action == 'export-finalcut':
        print(export_finalcut(recipe))
        return
    library_root(recipe.get('media_library'))
    media={m['id']:m for m in load(catalog_dir(recipe.get('media_library'))/'media.json')}
    if args.action == 'render':
        render(recipe, media, recipe_path=ROOT/args.recipe)
    elif args.action == 'qa':
        qa(recipe, media, recipe_path=ROOT/args.recipe)
    else:
        review_windows(recipe, media)
if __name__=='__main__': main()
