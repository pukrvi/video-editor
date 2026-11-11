"""Create one unified SDR library: HDR conversions plus links to existing SDR.

Original dimensions, frame rate and audio are retained. No originals are altered.
PQ/HLG is linearized, tone-mapped, converted to Rec.709, then encoded as H.264.
"""
from pathlib import Path
import argparse, concurrent.futures as cf, os, hashlib
from functools import partial
from tempfile import TemporaryDirectory
from pipeline import ROOT,album_media,load,save,command,probe,require,stamp
from media_library import library_root, catalog_dir
from pipeline_paths import guard_output_tree,safe_component
from quality_gate import sha256_file
TONE_MAP='zscale=t=linear:npl=100,format=gbrpf32le,zscale=p=bt709,tonemap=tonemap=hable:desat=2:peak=10,zscale=t=bt709:m=bt709:r=limited:dither=error_diffusion,format=yuv420p'
def convert(m,album):
    hdr=m.get('color_transfer') in ('smpte2084','arib-std-b67')
    src=album_media(album,m['file'])
    album=album.resolve()
    raw=album/'RAW Videos'
    source_parent=src.relative_to(raw if src.is_relative_to(raw) else album).parent
    out=album/'SDR Videos'/source_parent/(src.stem+('_SDR.mp4' if hdr else src.suffix))
    writable=(out.name,) if hdr or not out.is_symlink() else ()
    guard_output_tree(out.parent, (src,), writable=writable).mkdir(parents=True,exist_ok=True)
    info={'source':m['file'],'standardized':str(out.relative_to(album)),'original_transfer':m.get('color_transfer'),'converted':hdr,'source_key':m['key']}
    if hdr:
        key=safe_component(m['key'],'media cache key')
        media_id=safe_component(m['id'],'media ID')
        cache=ROOT/'cache'
        marker=cache/f'sdr_{key}.json'
        render_log=cache/f'sdr_{media_id}.log'
        decode_log=cache/f'sdr_{media_id}_decode.log'
        guard_output_tree(cache,(src,),writable=(marker.name,render_log.name,decode_log.name)).mkdir(parents=True,exist_ok=True)
        expected=hashlib.sha256((m['key']+TONE_MAP).encode()).hexdigest()
        original=next(s for s in probe(src)['streams'] if s['codec_type']=='video')
        def verify(candidate):
            v=next(s for s in probe(candidate)['streams'] if s['codec_type']=='video')
            require(all(v.get(field)=='bt709' for field in ('color_transfer','color_primaries','color_space')),
                    'SDR conversion lacks complete Rec.709 tags')
            require(all(v[field]==original[field] for field in ('width','height','avg_frame_rate','nb_frames')),
                    'SDR conversion changed the source geometry or frame clock')
            command(['ffmpeg','-v','error','-xerror','-protocol_whitelist','file','-i',candidate,
                     '-map','0:v:0','-map','0:a?','-f','null','-'],decode_log)
            return v
        marked=load(marker) if marker.exists() else {}
        if out.is_file() and marked.get('recipe_hash')==expected and marked.get('movie_sha256')==sha256_file(out):
            v=verify(out)
        else:
            with TemporaryDirectory(prefix='.sdr-',dir=out.parent) as scratch:
                candidate=Path(scratch)/out.name
                command(['ffmpeg','-v','error','-threads','3','-protocol_whitelist','file','-i',src,
                    '-map','0:v:0','-map','0:a?','-vf',TONE_MAP,
                    '-c:v','libx264','-preset','fast','-crf','17','-threads','3','-pix_fmt','yuv420p',
                    '-color_primaries','bt709','-color_trc','bt709','-colorspace','bt709','-color_range','tv',
                    '-c:a','copy','-map_metadata','-1','-movflags','+faststart','-n',candidate],render_log)
                v=verify(candidate)
                digest=sha256_file(candidate)
                candidate.replace(out)
            save(marker,{'recipe_hash':expected,'movie_sha256':digest})
        info['verified']={'width':v['width'],'height':v['height'],'fps':v['avg_frame_rate'],'frames':v['nb_frames'],'transfer':v['color_transfer'],'primaries':v['color_primaries'],'matrix':v['color_space'],'codec':v['codec_name']}
    else:
        if out.is_symlink():
            require(out.resolve()==src, f'SDR link points away from the original: {out}')
        elif out.exists():
            require(out.is_file() and sha256_file(out)==sha256_file(src), f'SDR path has different content: {out}')
        else:
            out.symlink_to(os.path.relpath(src,out.parent))
    return info
def main():
    ap=argparse.ArgumentParser()
    ap.add_argument('--library', help='Sibling album name in the shared trip folder')
    ap.add_argument('--public-review', help='Skip source files excluded by a review record')
    args=ap.parse_args()
    album=library_root(args.library)
    catalog=catalog_dir(args.library)
    sdr=album/'SDR Videos'
    guard_output_tree(sdr,writable=('SDR_CONVERSION_REPORT.json','README.txt'))
    guard_output_tree(catalog,writable=('sdr_manifest.json',))
    sdr.mkdir(exist_ok=True)
    media=[m for m in load(catalog/'media.json') if not m['photo']]
    blocked=set(load(ROOT/args.public_review).get('excluded_files', [])) if args.public_review else set()
    excluded=[m['file'] for m in media if m['file'] in blocked]
    media=[m for m in media if m['file'] not in blocked]
    with cf.ThreadPoolExecutor(max_workers=2) as pool: rows=list(pool.map(partial(convert,album=album),media))
    report={'created':stamp(),'total_videos':len(rows),'excluded_by_review':excluded,'already_sdr':sum(not x['converted'] for x in rows),'hdr_converted':sum(x['converted'] for x in rows),'method':TONE_MAP,'audio':'Copied unchanged','originals':'Untouched','files':rows}
    save(catalog/'sdr_manifest.json',report);save(sdr/'SDR_CONVERSION_REPORT.json',report)
    (sdr/'README.txt').write_text('Unified SDR library\n\nFiles ending _SDR.mp4 are HDR-to-SDR conversions. Other videos are links to existing SDR originals in this album. Keep the folder in place. Originals were never changed.\n\nHDR conversions retain the original resolution, frame count, frame rate and audio. Output colour: Rec.709 SDR. Detailed checks: SDR_CONVERSION_REPORT.json.\n')
    print(f"{report['hdr_converted']} HDR conversions verified; {report['already_sdr']} SDR originals linked in {sdr}")
if __name__=='__main__': main()
