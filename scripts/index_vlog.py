#!/usr/bin/env python3
"""Build a local, non-destructive visual catalogue of an album.

Usage: index_vlog.py build ALBUM CATALOG; index_vlog.py search CATALOG QUERY
Visual descriptions belong in observations.json, keyed by asset ID. Rebuilding
preserves them. Thumbnails are evidence for sampling, not a privacy clearance.
"""
import argparse, concurrent.futures, datetime, hashlib, json, re, subprocess, sys
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont, ImageOps
from photo_io import PHOTO_EXTENSIONS, open_photo
from pipeline_paths import guard_output_tree

VIDEO={'.mov','.mp4','.m4v'}
EXTS=PHOTO_EXTENSIONS | VIDEO

def capture_name(name):
    m=re.search(r'(20\d{2})[_-]?(\d\d)[_-]?(\d\d)[_ -]?(\d\d)(\d\d)(\d\d)',name)
    if m:
        try: return datetime.datetime(*map(int,m.groups())).isoformat(), 'filename'
        except ValueError: pass
    return None, None

def work(args):
    p, thumbdir = args
    with p.open('rb') as source:
        digest=hashlib.file_digest(source,'sha256').hexdigest()
    ident=digest[:16]
    d={'id':ident,'filename':p.name,'path':str(p),'sha256':digest,'bytes':p.stat().st_size, 'kind':'video' if p.suffix.lower() in VIDEO else 'photo'}
    d['captured'],d['capture_source']=capture_name(p.name)
    frames=[]
    if d['kind']=='video':
        try:
            x=json.loads(subprocess.check_output(['ffprobe','-v','error','-protocol_whitelist','file','-show_streams','-show_format','-of','json',str(p)]))
            v=next(s for s in x['streams'] if s['codec_type']=='video'); a=next((s for s in x['streams'] if s['codec_type']=='audio'),None)
            dur=float(x['format'].get('duration') or v.get('duration') or 0)
            tags=x['format'].get('tags',{}); timestamp=tags.get('creation_time') or v.get('tags',{}).get('creation_time')
            # Filename is generally camera local time; retain container UTC as independent evidence.
            d.update(duration=dur,width=v.get('width'),height=v.get('height'),codec=v.get('codec_name'),color_transfer=v.get('color_transfer'),color_primaries=v.get('color_primaries'),color_space=v.get('color_space'),hdr=(v.get('color_transfer') in ('smpte2084','arib-std-b67')) if v.get('color_transfer') not in (None,'unknown','unspecified') else None,audio=bool(a),audio_codec=a.get('codec_name') if a else None,container_creation_time=timestamp,rotation=next((s.get('rotation') for s in v.get('side_data_list',[]) if 'rotation' in s),v.get('tags',{}).get('rotate',0)))
            video_dur=float(v.get('duration') or dur)
            for i, frac in enumerate((.12,.5,.88)):
                t=max(0,min(video_dur-.05,video_dur*frac)); target=thumbdir/f'{ident}_{i}_{int(t*1000):08d}.jpg'
                if not target.exists():
                    subprocess.run(['ffmpeg','-v','error','-ss',str(t),'-protocol_whitelist','file','-i',str(p),'-map','0:v:0','-frames:v','1','-vf','scale=360:202:force_original_aspect_ratio=decrease','-q:v','4','-y',str(target)],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,check=True)

                if not target.is_file(): raise RuntimeError(f'No frame decoded at {t:.2f}s')
                frames.append({'time':round(t,2),'path':str(target)})
        except Exception as e: d['error']=str(e)
    else:
        try:
            with open_photo(p) as im:
                ex=im.getexif(); dt=ex.get(36867) or ex.get(306)
                if dt:
                    try: d['captured']=datetime.datetime.strptime(dt,'%Y:%m:%d %H:%M:%S').isoformat(); d['capture_source']='EXIF'
                    except ValueError: pass
                d.update(width=im.width,height=im.height,orientation=ex.get(274))
                target=thumbdir/f'{ident}_0.jpg'
                if not target.exists():
                    im=ImageOps.exif_transpose(im); im.thumbnail((360,202)); im.convert('RGB').save(target,quality=85)
            frames.append({'time':None,'path':str(target)})
        except Exception as e: d['error']=str(e)
    d['frames']=frames
    return d

def build(album,out):
    album=album.resolve()
    out=guard_output_tree(out,album=album,writable=('frames','sheets','media.json','observations.json'))
    out.mkdir(parents=True,exist_ok=True); td=out/'frames'; sd=out/'sheets'; td.mkdir(exist_ok=True); sd.mkdir(exist_ok=True)
    paths=sorted(p for p in album.iterdir() if not p.is_symlink() and p.is_file()
                 and 'Personal Content' not in p.parts and p.suffix.lower() in EXTS)
    with concurrent.futures.ThreadPoolExecutor(max_workers=6) as pool:
        data=list(pool.map(work,((p,td) for p in paths)))
    data.sort(key=lambda x:(x['captured'] or '9999',x['filename']))

    try: font=ImageFont.truetype('/System/Library/Fonts/Helvetica.ttc',16)
    except OSError: font=ImageFont.load_default()
    for start in range(0,len(data),12):
        batch=data[start:start+12]; canvas=Image.new('RGB',(1120, len(batch)*225),'#101010'); draw=ImageDraw.Draw(canvas)
        for row,d in enumerate(batch):
            y=row*225; label=f"{start+row+1:03d}  {d['filename']}  [{d['id'][:8]}]  {d.get('captured') or 'date unknown'}"
            draw.text((8,y+2),label,font=font,fill='white')
            for j,f in enumerate(d['frames']):
                try:
                    im=Image.open(f['path'],formats=['JPEG']).convert('RGB'); im.thumbnail((360,190)); x=8+j*370; canvas.paste(im,(x,y+28));
                    if f['time'] is not None: draw.text((x+4,y+172),f"{f['time']:.1f}s",font=font,fill='white',stroke_width=2,stroke_fill='black')
                except Exception: pass
            d['sheet']=f'sheets/{start//12+1:03d}.jpg'; d['sheet_row']=row+1
        canvas.save(sd/f'{start//12+1:03d}.jpg',quality=83)
    (out/'media.json').write_text(json.dumps({'schema':1,'album':str(album),'assets':data},indent=2))
    obs=out/'observations.json'
    if not obs.exists(): obs.write_text(json.dumps({'schema':1,'note':'Only observed sample frames; not a public suitability clearance.','assets':{}},indent=2))
    print(f"Indexed {len(data)} assets; {sum(bool(d.get('error')) for d in data)} errors; {len(list(sd.glob('*.jpg')))} sheets",flush=True)

def link_transcripts(out,folder):
    out=guard_output_tree(out,writable=('transcripts.json',))
    media=json.loads((out/'media.json').read_text())['assets']; by_name={x['filename']:x for x in media}; linked={}
    for path in sorted(folder.glob('*.json')):
        try: r=json.loads(path.read_text())
        except (ValueError,OSError): continue
        source=r.get('source')
        if isinstance(source,dict): name=source.get('relative_path'); sha=source.get('sha256')
        elif isinstance(source,str): name=source;sha=r.get('source_sha256')
        else: continue
        m=by_name.get(name)
        if not m or sha!=m['sha256']:continue
        segs=r.get('segments',[]);words=r.get('words',[])
        text=' '.join(w.get('text','') for w in words) if words else ' '.join(x.get('text','') for x in segs)
        candidate={'path':str(path),'status':r.get('status','alignment_candidate'),'language':r.get('detected_language',r.get('language')),'text':text,'segments':segs,'words':words,'review_flags':r.get('review_flags',r.get('flags',[])),'verified_by_listening':False}
        if 'source_window' in r:
            candidate.update(source_window=r['source_window'],timestamp_basis=r.get('timestamp_basis'))
        linked.setdefault(m['id'],[]).append(candidate)
    (out/'transcripts.json').write_text(json.dumps({'schema':1,'note':'Machine transcripts are searchable navigation, not verified quotations. Identity checked against catalogue SHA256.','assets':linked},indent=2,ensure_ascii=False))
    print(f'Linked {len(linked)} assets to source-matched transcripts')

def search(out,query):
    data=json.loads((out/'media.json').read_text())['assets']; op=out/'observations.json'; obs=json.loads(op.read_text()).get('assets',{}) if op.exists() else {}
    tp=out/'transcripts.json'; transcripts=json.loads(tp.read_text()).get('assets',{}) if tp.exists() else {}
    terms=query.lower().split()
    for d in data:
        record={**d,'observation':obs.get(d['id']),'transcript':transcripts.get(d['id'])}
        if all(t in json.dumps(record,ensure_ascii=False).lower() for t in terms): print(json.dumps(record,ensure_ascii=False))

if __name__=='__main__':
    p=argparse.ArgumentParser(); sub=p.add_subparsers(dest='command',required=True)
    b=sub.add_parser('build'); b.add_argument('album',type=Path); b.add_argument('catalog',type=Path)
    s=sub.add_parser('search'); s.add_argument('catalog',type=Path); s.add_argument('query')
    t=sub.add_parser('link-transcripts');t.add_argument('catalog',type=Path);t.add_argument('transcripts',type=Path)
    a=p.parse_args()
    if a.command=='build':build(a.album,a.catalog)
    elif a.command=='link-transcripts':link_transcripts(a.catalog,a.transcripts.resolve())
    else:search(a.catalog.resolve(),a.query)
