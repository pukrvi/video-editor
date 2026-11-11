"""Opt-in live/freeze personal-memory treatment. Never edits source files."""
from __future__ import annotations
import math
import random
import subprocess
from pathlib import Path
from PIL import Image, ImageDraw


def ease(t):
    t=max(0.,min(1.,t)); return t*t*(3-2*t)


def source_frame(n,config):
    """hold_frames includes the first frozen frame; resume without source jump."""
    if config.get('drawing_only'): return n
    freeze=int(config.get('freeze_frame',18)); hold=max(1,int(config.get('hold_frames',11)))
    return n if n<freeze else (freeze if n<freeze+hold else n-hold+1)


def curve(points,count=64):
    a,b,c,d=points
    return [((1-t)**3*a[0]+3*(1-t)**2*t*b[0]+3*(1-t)*t*t*c[0]+t**3*d[0],
             (1-t)**3*a[1]+3*(1-t)**2*t*b[1]+3*(1-t)*t*t*c[1]+t**3*d[1]) for t in [i/(count-1) for i in range(count)]]


def shapes(config):
    """Normalized hand-drawn paths around a protected central face area."""
    cx,cy=config.get('subject',config.get('focus',[.5,.4])); size=config.get('doodle_scale',1)
    def at(points): return [(cx+x*size,cy+y*size) for x,y in points]
    strokes=[]
    # Loose curved pencil parentheses frame the head without crossing it.
    strokes.append(at(curve([(-.19,-.085),(-.30,-.16),(-.34,.04),(-.22,.12)])))
    strokes.append(at(curve([(.18,-.11),(.31,-.18),(.34,.015),(.23,.085)])))
    # The heart's two lobes and point are curved, rather than a font glyph.
    hx,hy=(.23,-.16) if config.get('doodles')!='couple' else (0,-.19)
    heart=curve([(hx,hy+.018),(hx-.075,hy-.027),(hx-.045,hy-.068),(hx,hy-.025)],32)
    heart+=curve([(hx,hy-.025),(hx+.045,hy-.068),(hx+.075,hy-.027),(hx,hy+.018)],32)
    strokes.append(at(heart))
    # Small wonky four-point sparkle, isolated from eyes and mouth.
    sx,sy=-.22,-.18
    strokes.append(at([(sx,sy-.038),(sx+.012,sy-.009),(sx+.049,sy),(sx+.012,sy+.009),(sx,sy+.038),(sx-.012,sy+.009),(sx-.049,sy),(sx-.012,sy-.009),(sx,sy-.038)]))
    if config.get('doodles')=='celebrate':
        for xx in [-.13,0,.13]:
            strokes.append(at(curve([(xx,-.20),(xx-.015,-.23),(xx+.02,-.25),(xx+.015,-.28)],24)))
    # Override with explicit normalized curved/polyline paths after placement review.
    return config.get('paths',strokes)


def decorate(image,n,config):
    W,H=image.size
    start=int(config.get('doodle_start_frame',config.get('freeze_frame',18)))
    freeze=int(config.get('freeze_frame',18)); hold=max(1,int(config.get('hold_frames',11)))
    # Push smoothly into the moment and ease back into live motion on release.
    if config.get('drawing_only'):
        z=1+(config.get('zoom',1)-1)*ease((n+1)/max(1,freeze+hold))
    else:
        into=ease((n-freeze+4)/max(1,hold+3))
        release=1-ease((n-freeze-hold+1)/7)
        z=1+(config.get('zoom',1.10)-1)*into*release
    fx,fy=config.get('focus',[.5,.4])
    # Crop about focus; clamp to valid picture bounds rather than adding edges.
    cropw,croph=W/z,H/z
    left=max(0,min(W-cropw,fx*W-cropw/2)); top=max(0,min(H-croph,fy*H-croph/2))
    if z>1.00001: image=image.resize((W,H),Image.Resampling.LANCZOS,box=(left,top,left+cropw,top+croph))
    overlay=Image.new('RGBA',(W,H)); d=ImageDraw.Draw(overlay)
    rng=random.Random(config.get('seed',0))
    step=max(1,int(config.get('doodle_step_frames',2)))
    ink=tuple(config.get('ink',[255,246,218,235])); pencil=tuple(config.get('pencil',[67,49,38,210]))
    end_fade=1 if config.get('drawing_only') else 1-ease((n-freeze-hold-1)/7)
    for i,path in enumerate(shapes(config)):
        p=ease((n-start-i*step+1)/5)
        if p<=0: continue
        # Fixed per-path jitter is stable over time and reads as pencil wobble.
        pts=[((x*W-left)*z+rng.uniform(-1.1,1.1)*W/1080,(y*H-top)*z+rng.uniform(-1.1,1.1)*W/1080) for x,y in path]
        count=max(2,round(len(pts)*p)); visible=pts[:count]
        width=max(1,round(config.get('stroke_width',4)*W/1080))
        for offset,color,w in [((1.7,2),pencil,width+2),((0,0),ink,width)]:
            color=(*color[:3],round(color[3]*end_fade))
            d.line([(x+offset[0]*W/1080,y+offset[1]*W/1080) for x,y in visible],fill=color,width=w,joint='curve')
    return Image.alpha_composite(image.convert('RGBA'),overlay).convert('RGB')


def render(decode_args,out,frames,fps,W,H,config,ffmpeg='ffmpeg',crf=17):
    """decode_args already includes explicit mapping, SDR grade, crop and fps."""
    out=Path(out); partial=out.with_suffix('.partial.mp4')
    freeze=int(config.get('freeze_frame',18)); hold=int(config.get('hold_frames',11))
    if freeze<0 or hold<1 or (not config.get('drawing_only') and freeze>=frames):
        raise ValueError('Invalid playful_focus freeze/hold frames')
    decoder=subprocess.Popen(decode_args,stdout=subprocess.PIPE,stderr=subprocess.PIPE)
    args=[str(ffmpeg),'-v','error','-f','rawvideo','-pix_fmt','rgb24','-s',f'{W}x{H}','-r',str(fps),'-i','pipe:0','-map','0:v:0','-frames:v',str(frames),'-an','-vf','format=yuv420p,setparams=range=limited:color_primaries=bt709:color_trc=bt709:colorspace=bt709','-c:v','libx264','-preset','fast','-crf',str(crf),'-threads','2','-pix_fmt','yuv420p','-color_primaries','bt709','-color_trc','bt709','-colorspace','bt709','-video_track_timescale','30000','-movflags','+faststart','-y',str(partial)]
    encoder=subprocess.Popen(args,stdin=subprocess.PIPE,stderr=subprocess.PIPE)
    previous=-1; picture=None; length=W*H*3
    try:
        for n in range(frames):
            wanted=source_frame(n,config)
            while previous<wanted:
                data=decoder.stdout.read(length)
                if len(data)!=length: raise RuntimeError(f'Playful decode ended early at source frame {previous+1}')
                picture=Image.frombytes('RGB',(W,H),data); previous+=1
            encoder.stdin.write(decorate(picture,n,config).tobytes())
        encoder.stdin.close(); err=encoder.stderr.read().decode(errors='replace')
        if encoder.wait(): raise RuntimeError('Playful encode failed: '+err)
        decoder.stdout.close(); derr=decoder.stderr.read().decode(errors='replace')
        if decoder.wait(): raise RuntimeError('Playful decode failed: '+derr)
        partial.replace(out)
    except BaseException:
        decoder.kill(); encoder.kill(); decoder.wait(); encoder.wait(); partial.unlink(missing_ok=True); raise
    return out
