"""Animated three-image contact-sheet composition; originals are read only."""
from pathlib import Path
import subprocess
import math
from PIL import Image, ImageOps, ImageFilter, ImageDraw


def ease(t):
    t=max(0.,min(1.,t)); return 1-(1-t)**3


def prepare(paths, width, height, layout='legacy', animation=None):
    W,H=width,height; s=W/1080
    photos=[ImageOps.exif_transpose(Image.open(p)).convert('RGB') for p in paths]
    bg=ImageOps.fit(photos[0],(W,H),method=Image.Resampling.LANCZOS).filter(ImageFilter.GaussianBlur(35*s))
    bg=Image.blend(bg,Image.new('RGB',(W,H),(14,24,23)),.72).convert('RGBA')
    sprites=[]
    limits=((850,640),(445,650),(445,650)) if layout=='legacy' else ((605,1000),(648,1000),(518,1000))
    if layout=='people_clear':
        limits=((605,1000),(648,1000),(470,1000))
    if layout=='food':
        limits=((900,680),(460,760),(480,800))
    for photo,angle,limit in zip(photos,(-2,2,-2),limits):
        edge=max(1,round((12 if layout=='legacy' else 7)*s)); bottom=round((27 if layout=='legacy' else 12)*s)
        fit=ImageOps.contain(photo,(round(limit[0]*s),round(limit[1]*s)),Image.Resampling.LANCZOS)
        # Size the mat to the actual image, so portraits never acquire large
        # empty side panels. The entire original frame remains in the print.
        w=fit.width+2*edge; h=fit.height+edge+bottom
        card=Image.new('RGBA',(w,h),(247,243,232,255))
        card.paste(fit,(edge,edge))
        # Shadows and borders are part of each movable-looking print.
        shadow=Image.new('RGBA',(w+round(36*s),h+round(36*s)))
        d=ImageDraw.Draw(shadow); d.rectangle((round(18*s),round(21*s),w+round(18*s),h+round(21*s)),fill=(0,0,0,100))
        shadow=shadow.filter(ImageFilter.GaussianBlur(10*s)); shadow.alpha_composite(card,(0,0))
        rest=shadow.rotate(angle,resample=Image.Resampling.BICUBIC,expand=True)
        sprites.append({'base':shadow,'angle':angle,'rest_size':rest.size} if animation is not None else rest)
    return bg,sprites


def frame(bg,sprites,n,fps,layout='legacy',animation=None):
    if layout in ('people','people_clear','food'): return people_frame(bg,sprites,n,fps,layout,animation)
    W,H=bg.size; s=W/1080; canvas=bg.copy()
    # Separate arrivals produce a legible overlapping stack, not a static grid.
    anchors=[(95,155),(55,845),(535,965)]
    for i,(sprite,(x,y)) in enumerate(zip(sprites,anchors)):
        p=ease((n-i*round(.20*fps)+1)/max(1,round(.55*fps)))
        if p<=0: continue
        dx=(-1 if i!=1 else 1)*(1-p)*210*s
        dy=(1-p)*90*s
        layer,cx,cy=swing_sprite(sprite,n,fps,i,animation)
        dx+=cx; dy+=cy
        if p<1: layer.putalpha(layer.getchannel('A').point(lambda a:round(a*p)))
        canvas.alpha_composite(layer,(round(x*s+dx),round(y*s+dy)))
    if animation: draw_doodles(canvas,n,fps,animation)
    return canvas.convert('RGB')


def people_frame(bg,sprites,n,fps,layout='people',animation=None):
    W,H=bg.size; s=W/1080
    # A shared camera push begins only after all three independently settle.
    arrived=round(.22*fps)*2+8
    push=1+min(.022,max(0,(n-arrived)/max(1,1.8*fps))*.022)
    canvas=bg.copy()
    anchors=[(245,175),(55,600),(480,930)]
    if layout=='people_clear':
        anchors=[(245,70),(35,500),(540,1110)]
    if layout=='food':
        anchors=[(60,125),(65,850),(530,950)]
    for i,(sprite,(x,y)) in enumerate(zip(sprites,anchors)):
        t=(n-i*round(.22*fps)+1)/8
        if t<=0: continue
        t=min(1,t)
        # Standard ease-out-back arrives with a small overshoot in eight frames.
        c=1.25; p=1+(c+1)*(t-1)**3+c*(t-1)**2
        dx=(-1 if i!=1 else 1)*(1-p)*185*s
        dy=(1-p)*105*s
        layer,cx,cy=swing_sprite(sprite,n,fps,i,animation)
        dx+=cx; dy+=cy
        opacity=min(1,t*4)
        if opacity<1: layer.putalpha(layer.getchannel('A').point(lambda a:round(a*opacity)))
        canvas.alpha_composite(layer,(round(x*s+dx),round(y*s+dy)))
    if animation: draw_doodles(canvas,n,fps,animation)
    if push>1:
        # One high-quality resample, with no additional movement between cards.
        enlarged=canvas.resize((round(W*push),round(H*push)),Image.Resampling.LANCZOS)
        left=(enlarged.width-W)//2; top=(enlarged.height-H)//2
        canvas=enlarged.crop((left,top,left+W,top+H))
    return canvas.convert('RGB')


def swing_sprite(sprite,n,fps,index,animation):
    if not isinstance(sprite,dict): return sprite.copy(),0,0
    amplitude=max(0,min(2,float((animation or {}).get('swing_degrees',1.4))))
    period=max(.6,float((animation or {}).get('swing_period_seconds',3)))
    age=max(0,n-index*round(.22*fps)-7)/fps
    angle=sprite['angle']+amplitude*ease(age/.38)*math.sin(age/period*2*math.pi+index*1.35)
    layer=sprite['base'].rotate(angle,resample=Image.Resampling.BICUBIC,expand=True)
    rw,rh=sprite['rest_size']
    # Rotation changes the bounding box, never the print's resting center.
    return layer,(rw-layer.width)/2,(rh-layer.height)/2


def doodle_paths(kind):
    def star(cx,cy,r):
        return [(cx,cy-r),(cx+r*.24,cy-r*.18),(cx+r,cy),(cx+r*.24,cy+r*.18),(cx,cy+r),(cx-r*.24,cy+r*.18),(cx-r,cy),(cx-r*.24,cy-r*.18),(cx,cy-r)]
    if kind=='food':
        # Inspected negative space below the two drink prints; no food is covered.
        cx,cy=245,1705
        bun=[(cx+68*math.cos(t),cy-8-42*math.sin(t)) for t in [i/40*math.pi for i in range(41)]]
        return [bun,[(cx-68,cy-8),(cx+68,cy-8)],
                [(cx-65+i*130/50,cy+9+4*math.sin(i/50*math.pi*6)) for i in range(51)],
                [(cx-64,cy+23),(cx-58,cy+43),(cx+55,cy+43),(cx+65,cy+23),(cx-64,cy+23)],
                [(cx-31,cy-27),(cx-26,cy-30)],[(cx+1,cy-35),(cx+6,cy-37)],[(cx+30,cy-24),(cx+35,cy-27)],
                star(795,1760,30),star(970,895,19)]
    if kind=='travel':
        # Upper-right gap beside the lookout and lower-left gap beside market.
        plane=[(880,758),(1000,715),(962,817),(937,780),(880,758),(946,766),(1000,715),(937,780),(932,805),(946,790)]
        trail=[(905+35*math.sin(i/50*math.pi*1.2),835+i*1.3) for i in range(51)]
        cx,cy=280,1665
        heart=[]
        for i in range(81):
            t=i/80*math.pi*2
            heart.append((cx+3*16*math.sin(t)**3,cy-3*(13*math.cos(t)-5*math.cos(2*t)-2*math.cos(3*t)-math.cos(4*t))))
        return [plane,trail,star(145,210,27),heart,star(430,1800,22)]
    return []


def draw_doodles(canvas,n,fps,animation):
    W,H=canvas.size; s=W/1080
    start=int(animation.get('doodle_start_frame',round(.44*fps)+8))
    kind=animation.get('doodles'); paths=doodle_paths(kind)
    ink=tuple(animation.get('doodle_ink',[255,246,218,240])); pencil=tuple(animation.get('doodle_pencil',[67,49,38,205]))
    overlay=Image.new('RGBA',canvas.size); d=ImageDraw.Draw(overlay)
    for i,path in enumerate(paths):
        # Complete related burger strokes together before the accent stars arrive.
        delay=i*2 if kind=='food' else i*3
        p=ease((n-start-delay+1)/7)
        if p<=0: continue
        visible=path[:max(2,round(len(path)*p))]
        pulse=.94+.06*math.sin((n/fps)*2*math.pi/2.7+i*.9)
        pts=[(x*s,y*s) for x,y in visible]
        for dx,dy,color,width in [(1.6,2.2,pencil,5),(0,0,ink,3)]:
            d.line([(x+dx*s,y+dy*s) for x,y in pts],fill=(*color[:3],round(color[3]*pulse)),width=max(1,round(width*s)),joint='curve')
    canvas.alpha_composite(overlay)


def render(paths,out,frames,fps,width,height,grade,ffmpeg='ffmpeg',layout='legacy',animation=None):
    if len(paths)!=3: raise ValueError('A photo stack requires exactly three photos')
    bg,sprites=prepare(paths,width,height,layout,animation)
    out=Path(out); partial=out.with_suffix('.partial.mp4')
    vf=f"eq=brightness={grade['brightness']}:saturation={grade['saturation']}:contrast={grade['contrast']},setsar=1,format=yuv420p"
    args=[str(ffmpeg),'-v','error','-f','rawvideo','-pix_fmt','rgb24','-s',f'{width}x{height}','-r',str(fps),'-i','pipe:0','-map','0:v:0','-frames:v',str(frames),'-an','-vf',vf,'-c:v','libx264','-preset','fast','-crf','17','-threads','2','-pix_fmt','yuv420p','-color_primaries','bt709','-color_trc','bt709','-colorspace','bt709','-video_track_timescale','30000','-movflags','+faststart','-y',str(partial)]
    p=subprocess.Popen(args,stdin=subprocess.PIPE,stderr=subprocess.PIPE)
    try:
        for n in range(frames): p.stdin.write(frame(bg,sprites,n,fps,layout,animation).tobytes())
        p.stdin.close(); err=p.stderr.read().decode(errors='replace')
        if p.wait(): raise RuntimeError('Photo stack encoding failed: '+err)
        partial.replace(out)
    except BaseException:
        p.kill(); p.wait(); partial.unlink(missing_ok=True); raise
    return out
