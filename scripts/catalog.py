"""Read-only media inventory and cached visual review sheets."""
import concurrent.futures as cf
import argparse, json, subprocess, hashlib
from pathlib import Path
from PIL import Image, ImageOps, ImageDraw, ImageFont

from media_library import ROOT, library_root, catalog_dir
from photo_io import PHOTO_EXTENSIONS, open_photo
from pipeline_paths import guard_output_tree

FONT = '/System/Library/Fonts/Supplemental/Arial.ttf'
VIDEO_EXTENSIONS = {'.mp4', '.mov', '.m4v'}
def run(args):
    return subprocess.run(args, check=True, capture_output=True).stdout
def inspect(item):
    i,p,album = item
    stat=p.stat(); key=hashlib.sha256(f'{p}:{stat.st_size}:{stat.st_mtime_ns}'.encode()).hexdigest()[:16]
    cache=ROOT/'cache'
    guard_output_tree(cache,(p,),writable=(f'{key}.json',*(f'{key}_{n}.jpg' for n in range(3))))
    if p.suffix.lower() in PHOTO_EXTENSIONS:
        out=cache/f'{key}_0.jpg'
        with open_photo(p) as image:
            oriented=ImageOps.exif_transpose(image)
            width,height=oriented.size
            if not out.exists():
                oriented.thumbnail((320,240),Image.Resampling.LANCZOS)
                oriented.convert('RGB').save(out,quality=90)
        return {'id':f'P{i:03d}','file':str(p.relative_to(album)),'duration':0,'width':width,'height':height,
                'rotation':0,'fps':None,'color_transfer':None,'key':key,'photo':True,'audio':False,
                'review_frames':[str(out.relative_to(ROOT))],'review_times':[0]}
    meta=cache/f'{key}.json'
    if meta.exists(): d=json.loads(meta.read_text())
    else:
        d=json.loads(run(['ffprobe','-v','error','-protocol_whitelist','file','-show_format','-show_streams','-of','json',str(p)]))
        meta.write_text(json.dumps(d))
    v=next(s for s in d['streams'] if s['codec_type']=='video')
    dur=float(d['format'].get('duration',v.get('duration',0)))
    rot=next((s.get('rotation',0) for s in v.get('side_data_list',[]) if 'rotation' in s),0)
    w,h=v['width'],v['height']
    if abs(rot)%180==90: w,h=h,w
    row={'id':f'V{i:03d}','file':str(p.relative_to(album)), 'duration':dur,'width':w,'height':h,'rotation':rot,'fps':v.get('avg_frame_rate'),'color_transfer':v.get('color_transfer'),'key':key,'photo':False,'audio':any(s['codec_type']=='audio' for s in d['streams'])}
    times=[max(.05,dur*f) for f in (.16,.50,.82)]
    frames=[]
    for n,t in enumerate(times):
        out=ROOT/'cache'/f'{key}_{n}.jpg'
        if not out.exists():
            args=['ffmpeg','-v','error','-threads','1','-ss',str(t)]
            args+=['-protocol_whitelist','file','-i',str(p),'-map','0:v:0','-frames:v','1','-vf','scale=320:240:force_original_aspect_ratio=decrease','-threads','1','-y',str(out)]
            run(args)
        frames.append(str(out.relative_to(ROOT)))
    row['review_frames']=frames; row['review_times']=times
    return row
def main():
    ap=argparse.ArgumentParser()
    ap.add_argument('--library', help='Sibling album name in the shared trip folder')
    args=ap.parse_args()
    album=library_root(args.library).resolve()
    folders=[album/name for name in ('RAW Videos','Photos') if (album/name).is_dir()]
    if not folders:
        folders=[album]
    private_folders={'SDR Videos','Edit_Workspace','Personal Content'}
    paths=sorted(p for folder in folders if not folder.is_symlink() for p in folder.rglob('*')
                 if p.suffix.lower() in VIDEO_EXTENSIONS | PHOTO_EXTENSIONS
                 and p.is_file() and not p.is_symlink() and p.resolve().is_relative_to(album)
                 and not p.resolve().is_relative_to(ROOT)
                 and not private_folders.intersection(p.relative_to(album).parts))
    catalog=catalog_dir(args.library)
    guard_output_tree(catalog,writable=('media.json',)).mkdir(parents=True,exist_ok=True)
    guard_output_tree(ROOT/'cache').mkdir(parents=True,exist_ok=True)
    review=ROOT/'review'/args.library if args.library else ROOT/'review'
    vids=[p for p in paths if p.suffix.lower() in VIDEO_EXTENSIONS]
    pics=[p for p in paths if p.suffix.lower() in PHOTO_EXTENSIONS]
    names=[f'{label}_{start//16+1:02d}.jpg' for label, group in (('videos',vids),('photos',pics))
           for start in range(0,len(group),16)]
    guard_output_tree(review,writable=names).mkdir(parents=True,exist_ok=True)
    previous=catalog/'media.json'
    old={r['file']:int(r['id'][1:]) for r in json.loads(previous.read_text())} if previous.exists() else {}
    items=[]
    for group in (vids,pics):
        next_id=max((old.get(str(p.relative_to(album)),0) for p in group),default=0)+1
        for p in group:
            key=str(p.relative_to(album));identifier=old.get(key)
            if identifier is None: identifier=next_id;next_id+=1
            items.append((identifier,p,album))
    with cf.ThreadPoolExecutor(max_workers=6) as pool:
        rows=list(pool.map(inspect,items))
    previous.write_text(json.dumps(rows,indent=2))
    font=ImageFont.truetype(FONT,17)
    for kind in (False,True):
        group=[r for r in rows if r['photo']==kind]
        for start in range(0,len(group),16):
            batch=group[start:start+16]
            sheet=Image.new('RGB',(1280, len(batch)*142),(22,22,22)); draw=ImageDraw.Draw(sheet)
            for j,r in enumerate(batch):
                label=f"{r['id']} | {Path(r['file']).name} | {r['duration']:.1f}s | {r['width']}x{r['height']}"
                draw.text((8,j*142+3),label,font=font,fill='white')
                for n,f in enumerate(r['review_frames']):
                    im=Image.open(ROOT/f); im.thumbnail((390,114))
                    sheet.paste(im,(n*420+int((390-im.width)/2),j*142+27))
            sheet.save(review/f'{"photos" if kind else "videos"}_{start//16+1:02d}.jpg',quality=86)
    print(json.dumps({'videos':len(vids),'photos':len(pics),'minutes':round(sum(r['duration'] for r in rows)/60,1),'review_sheets':str(review)}))
if __name__=='__main__': main()
