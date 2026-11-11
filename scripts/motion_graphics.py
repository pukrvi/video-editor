"""Frame-based, transparent editorial titles for the reel and Final Cut.

Use style motion_editorial, motion_marker or motion_closure in recipe titles.
The generated ProRes 4444 movie has exactly the rounded title interval's frames.
"""
from __future__ import annotations
import math
import subprocess
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont, ImageFilter

STYLES = {'motion_editorial', 'motion_marker', 'motion_closure', 'kinetic_open', 'contour_marker', 'kinetic_closure', 'field_note', 'ridge_trace', 'pan_label', 'sketch_open', 'sketch_label', 'sketch_ridge'}
DEFAULT_FONT = '/System/Library/Fonts/Supplemental/DIN Condensed Bold.ttf'
SMALL_FONT = '/System/Library/Fonts/Supplemental/Arial Bold.ttf'

def ease(t):
    t = max(0., min(1., t))
    return 1 - (1-t)**3

def font_fit(text, path, size, max_width, index=0):
    while size > 12:
        f = ImageFont.truetype(path, size, index=index)
        if f.getlength(text) <= max_width:
            return f
        size -= 2
    return f

def put_text(canvas, text, font, x, y, color, opacity=1, tracking=0):
    """Place by visible top edge; leave alpha straight for FFmpeg."""
    layer = Image.new('RGBA', canvas.size)
    draw = ImageDraw.Draw(layer)
    cursor = x
    top = draw.textbbox((0, 0), text, font=font)[1]
    for char in text:
        draw.text((cursor, y-top), char, font=font, fill=color)
        cursor += draw.textlength(char, font=font) + tracking
    if opacity < 1:
        layer.putalpha(layer.getchannel('A').point(lambda p: round(p*opacity)))
    canvas.alpha_composite(layer)

def partial_line(draw, points, progress, fill, width):
    """Draw by arc length, so irregular sampled silhouettes reveal uniformly."""
    if progress <= 0 or len(points) < 2:
        return
    lengths=[math.dist(a,b) for a,b in zip(points,points[1:])]
    remaining=sum(lengths)*min(1,progress); visible=[points[0]]
    for a,b,length in zip(points,points[1:],lengths):
        if remaining >= length:
            visible.append(b); remaining-=length
        else:
            q=remaining/length if length else 0
            visible.append((a[0]+(b[0]-a[0])*q,a[1]+(b[1]-a[1])*q)); break
    if len(visible)>1: draw.line(visible,fill=fill,width=width,joint='curve')


def scene_frame(title,W,H,index,frames,fps):
    im=Image.new('RGBA',(W,H)); s=W/1080
    fade=max(0,min(1,(frames-1-index)/max(1,int(title.get('exit_frames',8)))))
    ink=tuple(title.get('ink',[255,250,240,255])); accent=tuple(title.get('accent',[239,198,133,255]))
    def col(c,a=1): return (*c[:3],round(c[3]*fade*a))
    x=round(title.get('x',90)*s); y=round(title['y']*s)
    name=title['headline'].upper()
    f=font_fit(name,title.get('font',SMALL_FONT),round(title.get('size',68)*s),W-x-round(70*s),title.get('font_index',0))
    h=f.getbbox(name)[3]-f.getbbox(name)[1]; tw=round(f.getlength(name))
    d=ImageDraw.Draw(im)
    if title['style']=='ridge_trace':
        points=title.get('ridge_points',[])
        if len(points)<2 or any(len(p)!=2 or not all(0<=v<=1 for v in p) for p in points):
            raise ValueError('ridge_trace requires at least two normalized ridge_points')
        keys=sorted(title.get('ridge_keyframes',[{'frame':0}]),key=lambda k:k['frame'])
        a=keys[0]; b=keys[-1]
        if index<=keys[0]['frame']: b=a
        elif index>=keys[-1]['frame']: a=b
        else:
            for lo,hi in zip(keys,keys[1:]):
                if lo['frame']<=index<=hi['frame']: a,b=lo,hi; break
        q=(index-a['frame'])/max(1,b['frame']-a['frame'])
        def interp(key,default): return a.get(key,default)+(b.get(key,default)-a.get(key,default))*q
        dx,dy,z=interp('dx',0),interp('dy',0),interp('scale',1)
        def project(p): return (((p[0]-.5)*z+.5+dx)*W,((p[1]-.5)*z+.5+dy)*H)
        ridge=[project(p) for p in points]
        drawframes=max(1,title.get('ridge_draw_frames',18)); lp=ease((index+1-drawframes)/max(1,title.get('leader_frames',7)))
        partial_line(d,ridge,(index+1)/drawframes,col(accent),max(1,round(title.get('line_width',4)*s)))
        # The leader's landscape anchor follows the ridge; the label stays readable.
        leader=[project(p) for p in title['leader_points']] if title.get('leader_points') else [ridge[-1],(x-round(18*s),y+h/2),(x,y+h/2)]
        partial_line(d,leader,lp,col(accent),max(1,round(3*s)))
        label=ease((index+1-title.get('label_delay_frames',drawframes+3))/8)
        scrim=Image.new('RGBA',(W,H)); sd=ImageDraw.Draw(scrim)
        sd.rounded_rectangle((x-22*s,y-17*s,x+tw+22*s,y+h+20*s),radius=12*s,
                             fill=(7,19,22,round(title.get('scrim_alpha',150)*label*fade)))
        scrim=scrim.filter(ImageFilter.GaussianBlur(title.get('scrim_blur',12)*s)); im.alpha_composite(scrim)
        put_text(im,name,f,x,y,ink,label*fade)
    else:
        reveal=max(1,title.get('reveal_frames',12)); p=ease((index+1)/reveal)
        direction=-1 if title.get('pan_direction','left')=='left' else 1
        tx=x-round(direction*(1-p)*title.get('travel',36)*s)
        text=Image.new('RGBA',(W,H)); td=ImageDraw.Draw(text); top=f.getbbox(name)[1]
        td.text((tx+2*s,y-top+3*s),name,font=f,fill=(0,0,0,round(155*fade)))
        td.text((tx,y-top),name,font=f,fill=col(ink))
        # A narrow horizontal aperture widens with the pan-directed name reveal.
        mask=Image.new('L',(W,H)); md=ImageDraw.Draw(mask)
        if direction<0: bounds=(x+tw*(1-p),y-8*s,x+tw+10*s,y+h+12*s)
        else: bounds=(x-10*s,y-8*s,x+tw*p,y+h+12*s)
        md.rectangle(bounds,fill=255)
        text.putalpha(Image.composite(text.getchannel('A'),Image.new('L',(W,H)),mask)); im.alpha_composite(text)
        retract=ease((index+1-reveal-title.get('bracket_hold_frames',5))/max(1,title.get('bracket_retract_frames',8)))
        d=ImageDraw.Draw(im); length=(1-retract)*p
        bx=x-20*s if direction>0 else x+tw+20*s
        d.line((bx,y-12*s,bx,y-12*s+(h+24*s)*length),fill=col(accent),width=max(1,round(3*s)))
        d.line((bx,y-12*s,bx+direction*50*s*length,y-12*s),fill=col(accent),width=max(1,round(3*s)))
    return im


def sketch_frame(title,W,H,index,frames,fps):
    """Handwritten travel notes, isolated from the cinematic title system."""
    im=Image.new('RGBA',(W,H)); s=W/1080
    style=title['style']; opening=style=='sketch_open'
    x=round(title.get('x',80)*s); y=round(title['y']*s)
    fade=max(0,min(1,(frames-1-index)/max(1,int(title.get('exit_frames',6))))) if frames>1 else 1
    ink=tuple(title.get('ink',[255,246,218,255])); pencil=tuple(title.get('pencil',[67,49,38,210]))
    accent=tuple(title.get('accent',ink))
    def col(c,a=1): return (*c[:3],round(c[3]*fade*a))
    name=title['headline']
    path=title.get('font','/System/Library/Fonts/Supplemental/Bradley Hand Bold.ttf')
    f=font_fit(name,path,round(title.get('size',165 if opening else 76)*s),W-x-round(70*s),title.get('font_index',0))
    box=f.getbbox(name); h=box[3]-box[1]; tw=f.getlength(name)
    start=0
    def stroke(points,p,width=4,opacity=1):
        d=ImageDraw.Draw(im)
        # A narrow dark-paper offset provides local contrast without a halo.
        offset=[(xx+1.6*s,yy+2.2*s) for xx,yy in points]
        partial_line(d,offset,p,col(pencil,opacity),max(1,round((width+1)*s)))
        partial_line(d,points,p,col(accent,opacity),max(1,round(width*s)))
    if style=='sketch_ridge':
        points=title.get('ridge_points',[])
        if len(points)<2 or any(len(p)!=2 or not all(0<=v<=1 for v in p) for p in points):
            raise ValueError('sketch_ridge requires normalized ridge_points')
        keys=sorted(title.get('ridge_keyframes',[{'frame':0}]),key=lambda k:k['frame'])
        a=keys[0]; b=keys[-1]
        if index<=a['frame']: b=a
        elif index>=b['frame']: a=b
        else:
            for lo,hi in zip(keys,keys[1:]):
                if lo['frame']<=index<=hi['frame']: a,b=lo,hi; break
        q=(index-a['frame'])/max(1,b['frame']-a['frame'])
        def interp(key,default): return a.get(key,default)+(b.get(key,default)-a.get(key,default))*q
        dx,dy,z=interp('dx',0),interp('dy',0),interp('scale',1)
        def project(p): return (((p[0]-.5)*z+.5+dx)*W,((p[1]-.5)*z+.5+dy)*H)
        ridge=[project(p) for p in points]
        drawframes=max(1,int(title.get('ridge_draw_frames',18)))
        stroke(ridge,(index+1)/drawframes,title.get('line_width',4))
        if title.get('leader_points'): leader=[project(p) for p in title['leader_points']]
        else:
            ax,ay=ridge[-1]
            bx,by=(x,y+h+18*s) if title.get('leader_join')=='underline' else (x-12*s,y+h*.45)
            leader=[]
            for k in range(51):
                t=k/50
                leader.append(((1-t)*ax+t*bx+math.sin(t*math.pi)*15*s,(1-t)*ay+t*by-math.sin(t*math.pi)*22*s))
        stroke(leader,ease((index+1-drawframes)/max(1,title.get('leader_frames',7))),3)
        start=title.get('label_delay_frames',drawframes+3)
    drawframes=max(1,int(title.get('sketch_draw_frames',12 if opening else 14)))
    # Staggered horizontal write-on retains the shape of actual handwritten glyphs.
    text=Image.new('RGBA',(W,H)); td=ImageDraw.Draw(text); cursor=x
    for k,char in enumerate(name):
        width=f.getlength(char)
        delay=k*drawframes/max(1,len(name))*0.72
        p=ease((index+1-start-delay)/max(3,drawframes*.35))
        glyph=Image.new('RGBA',(W,H)); gd=ImageDraw.Draw(glyph)
        gd.text((cursor+1.5*s,y-box[1]+2.5*s),char,font=f,fill=col(pencil,p))
        gd.text((cursor,y-box[1]),char,font=f,fill=col(ink,p))
        mask=Image.new('L',(W,H)); ImageDraw.Draw(mask).rectangle((cursor-3*s,y-8*s,cursor+(width+5*s)*p,y+h+8*s),fill=255)
        glyph.putalpha(Image.composite(glyph.getchannel('A'),Image.new('L',(W,H)),mask)); text.alpha_composite(glyph)
        cursor+=width
    im.alpha_composite(text)
    # A long slightly bowed pencil sweep, with a shorter second finishing stroke.
    uw=min(tw,title.get('underline_width',tw/s*.82)*s)
    uy=y+h+18*s
    pts=[(x+uw*i/70,uy+math.sin(i/70*math.pi)*8*s+math.sin(i/70*math.pi*3.7)*1.1*s) for i in range(71)]
    p=ease((index+1-start-drawframes*.5)/max(1,drawframes*.7))
    stroke(pts,p,title.get('line_width',4))
    stroke([(x+uw*.60+uw*.35*i/35,uy+13*s-math.sin(i/35*math.pi)*3*s) for i in range(36)],ease((index+1-start-drawframes)/7),2,.75)
    kind=title.get('doodle_accent','sparkle')
    ax=min(W-40*s,x+tw+24*s); ay=y-12*s
    if kind=='heart':
        # Parametric heart, independent of a decorative font glyph.
        pts=[]
        for i in range(81):
            t=i/80*math.pi*2
            pts.append((ax+16*math.sin(t)**3*s,ay-(13*math.cos(t)-5*math.cos(2*t)-2*math.cos(3*t)-math.cos(4*t))*s))
    elif kind=='sparkle':
        pts=[(ax,ay-20*s),(ax+5*s,ay-4*s),(ax+20*s,ay),(ax+5*s,ay+4*s),(ax,ay+20*s),(ax-5*s,ay+4*s),(ax-20*s,ay),(ax-5*s,ay-4*s),(ax,ay-20*s)]
    else: pts=[]
    if pts: stroke(pts,ease((index+1-start-drawframes*.8)/8),3)
    return im


def kinetic_frame(title,W,H,index,frames,fps):
    """A second visual system, isolated from the original title presets."""
    im=Image.new('RGBA',(W,H)); d=ImageDraw.Draw(im); s=W/1080
    x=round(title.get('x',80)*s); y=round(title['y']*s)
    enter=max(1,int(title.get('enter_frames',round(.8*fps))))
    exit_=max(1,int(title.get('exit_frames',round(.25*fps))))
    fade=max(0.,min(1.,(frames-1-index)/exit_)) if frames>1 else 1.
    p=ease((index+1)/enter); ink=tuple(title.get('ink',[255,250,240,255])); accent=tuple(title.get('accent',[239,198,133,255]))
    def col(c,a=1): return (*c[:3],round(c[3]*fade*a))
    small=ImageFont.truetype(SMALL_FONT,max(12,round(25*s)))
    name=title['headline']; style=title['style']; maxw=W-x-round(70*s)
    if style=='field_note':
        # A small open-corner frame and a masked sideways type reveal.
        f=font_fit(name.upper(),title.get('font',SMALL_FONT),round(title.get('size',55)*s),maxw-round(35*s),title.get('font_index',0))
        h=f.getbbox(name.upper())[3]-f.getbbox(name.upper())[1]
        boxw=min(maxw,round(f.getlength(name.upper())+60*s)); top=y
        d.line((x,top,x+round(boxw*p),top),fill=col(accent),width=max(1,round(3*s)))
        d.line((x,top,x,top+round((h+65*s)*p)),fill=col(accent),width=max(1,round(3*s)))
        text_y=top+round(23*s)
        layer=Image.new('RGBA',(W,H)); ld=ImageDraw.Draw(layer)
        bb=ld.textbbox((0,0),name.upper(),font=f)
        ld.text((x+round(20*s)-(1-p)*round(55*s),text_y-bb[1]),name.upper(),font=f,fill=col(ink,p),
                stroke_width=max(1,round(2*s)),stroke_fill=col((12,22,20,150),p))
        mask=Image.new('L',(W,H)); ImageDraw.Draw(mask).rectangle((x+round(16*s),text_y,x+boxw,text_y+h+round(5*s)),fill=255)
        layer.putalpha(Image.composite(layer.getchannel('A'),Image.new('L',(W,H)),mask)); im.alpha_composite(layer)
        if title.get('kicker'):
            put_text(im,title['kicker'].upper(),small,x+round(20*s),text_y+h+round(16*s),accent,ease((index-enter*.25)/enter)*fade,round(1*s))
        return im
    if style=='contour_marker':
        # Stylized, illustrative topographic arcs: no claim of measured geography.
        for k in range(6):
            pts=[]
            for i in range(81):
                xx=i/80; px=x+round(xx*min(maxw,610*s))
                yy=y+round((k*17+16*math.sin(xx*math.pi*2.1+k*.48)+12*math.sin(xx*math.pi*4.2+k*.3))*s)
                pts.append((px,yy))
            count=max(2,round(len(pts)*ease((index+1-k*2)/enter)))
            d.line(pts[:count],fill=col(accent,.85),width=max(1,round(3*s)))
        text_y=y+round(150*s)
        f=font_fit(name.upper(),title.get('font',DEFAULT_FONT),round(title.get('size',78)*s),maxw,title.get('font_index',0))
        put_text(im,name.upper(),f,x,text_y,ink,ease((index+1-enter*.25)/enter)*fade)
        d.line((x,text_y+round(88*s),x+round(240*s*p),text_y+round(88*s)),fill=col(accent),width=max(1,round(3*s)))
        if title.get('kicker'): put_text(im,title['kicker'].upper(),small,x,text_y+round(110*s),accent,p*fade,round(1*s))
        return im
    # Restrict type to a fixed horizontal window while letters rise into view.
    size=round(title.get('size',190 if style=='kinetic_open' else 145)*s)
    path=title.get('font',DEFAULT_FONT); fi=title.get('font_index',0)
    if style=='kinetic_open':
        # A large outline echoes the destination, while a numbered edge and
        # fine rules make the composition visible before the filled type lands.
        outline=font_fit(name,path,round(size*1.55),maxw,fi)
        ob=outline.getbbox(name)
        outline_h=ob[3]-ob[1]
        outline_y=y-outline_h-round(title['outline_gap']*s) if 'outline_gap' in title else y-round(140*s)
        d.text((x,outline_y-ob[1]),name,font=outline,fill=(0,0,0,0),stroke_width=max(1,round(3*s)),stroke_fill=col(accent,.60*p))
        if title.get('left_rule',True):
            d.line((x-round(20*s),y-round(100*s),x-round(20*s),y+round(220*s)),fill=col(accent,.65*p),width=max(1,round(2*s)))
        for tick in range(5):
            xx=x+round(tick*22*s)
            d.line((xx,y-round(24*s),xx,y-round((31 if tick%2==0 else 28)*s)),fill=col(accent,p),width=max(1,round(2*s)))
    lower_kicker=style=='kinetic_open' and title.get('kicker_position')=='lower_right'
    if title.get('kicker') and not lower_kicker:
        put_text(im,title['kicker'].upper(),small,x,y,accent,p*fade,round(1.2*s))
    ty=y+(round(45*s) if title.get('kicker') else 0)
    texts=[name]+([title['line2']] if title.get('line2') else [])
    for j,text in enumerate(texts):
        f=font_fit(text,path,size,maxw,fi); h=f.getbbox(text)[3]-f.getbbox(text)[1]
        top=ty+j*round(size*.91)
        # Individual glyphs enter with a controlled cascade beneath a crop.
        layer=Image.new('RGBA',(W,H)); ld=ImageDraw.Draw(layer); cursor=x
        baseline=ld.textbbox((0,0),text,font=f)[1]
        for k,c in enumerate(text):
            q=ease((index+1-j*enter*.3-k*1.15)/max(1,enter*.65))
            ld.text((cursor,top-baseline+(1-q)*h),c,font=f,fill=col(ink,q))
            cursor+=ld.textlength(c,font=f)
        clip=Image.new('L',(W,H)); ImageDraw.Draw(clip).rectangle((x,top,W,top+h+round(5*s)),fill=255)
        layer.putalpha(Image.composite(layer.getchannel('A'),Image.new('L',(W,H)),clip)); im.alpha_composite(layer)
    if lower_kicker and title.get('kicker'):
        mainfont=font_fit(name,path,size,maxw,fi)
        mainh=mainfont.getbbox(name)[3]-mainfont.getbbox(name)[1]
        kicker=title['kicker'].upper(); tracking=round(1.2*s)
        kickerw=small.getlength(kicker)+max(0,len(kicker)-1)*tracking
        kx=x+mainfont.getlength(name)-kickerw
        kp=ease((index+1-title.get('kicker_delay_frames',enter))/max(1,enter*.3))
        put_text(im,kicker,small,kx,ty+mainh+round(18*s),accent,kp*fade,tracking)
    d=ImageDraw.Draw(im); line_y=ty+len(texts)*round(size*.91)+round(12*s)
    d.rectangle((x,line_y,x+round(320*s*p),line_y+max(1,round(4*s))),fill=col(accent))
    d.rectangle((x,line_y+round(16*s),x+round(45*s),line_y+round(22*s)),fill=col(accent,p))
    return im

def frame(title, W, H, index, frames, fps):
    if title['style'] in {'sketch_open','sketch_label','sketch_ridge'}:
        return sketch_frame(title,W,H,index,frames,fps)
    if title['style'] in {'ridge_trace','pan_label'}:
        return scene_frame(title,W,H,index,frames,fps)
    if title['style'] in {'kinetic_open','contour_marker','kinetic_closure','field_note'}:
        return kinetic_frame(title,W,H,index,frames,fps)
    im = Image.new('RGBA', (W, H))
    style = title['style']
    scale = W/1080
    x = round(title.get('x', 1080*.075)*scale); y = round(title['y']*scale)
    enter = max(1, int(title.get('enter_frames', round(.55*fps))))
    exit_ = max(1, int(title.get('exit_frames', round(.30*fps))))
    alpha = min(1., (frames-1-index)/exit_) if frames > 1 else 1.
    alpha = max(0., alpha)
    ink = tuple(title.get('ink', [255, 250, 239, 255])); accent = tuple(title.get('accent', [232, 197, 142, 255]))
    path = title.get('font', DEFAULT_FONT); fi = title.get('font_index', 0)
    headline = title['headline']
    maxw = max(30, W-x-int(W*.075))
    p = ease((index+1)/enter)
    small = ImageFont.truetype(SMALL_FONT, max(12, round((26 if style != 'motion_marker' else 28)*scale)))
    draw = ImageDraw.Draw(im)
    if style == 'motion_marker':
        line_w = int(min(maxw, 250*scale)*p)
        yy = y+int(14*scale)
        draw.line((x, yy, x+line_w, yy), fill=(*accent[:3],round(accent[3]*alpha)), width=max(1,round(3*scale)))
        opacity = ease((index-enter*.25)/max(1,enter*.7))*alpha
        f = font_fit(headline.upper(), SMALL_FONT, max(14,round(title.get('size',34)*scale)), maxw)
        put_text(im, headline.upper(), f, x, y+round(30*scale), ink, opacity, round(1.2*scale))
        ticks = max(0, min(12, int(title.get('ticks', 0))))
        if ticks:
            for i in range(ticks):
                if p >= (i+1)/ticks:
                    tx = x+round(i*15*scale); ty=y+round(83*scale)
                    draw.rectangle((tx,ty,tx+max(1,round(7*scale)),ty+max(1,round(2*scale))),fill=(*accent[:3],round(accent[3]*alpha)))
    else:
        size = max(18,round(title.get('size', 150 if style == 'motion_editorial' else 125)*scale))
        f = font_fit(headline, path, size, maxw, fi)
        kicker = title.get('kicker','')
        if kicker:
            put_text(im, kicker.upper(), small, x, y, accent, p*alpha, round(1.5*scale))
        text_y = y + (round(47*scale) if kicker else 0)
        # Eased upward travel, keeping the typography readable throughout the hold.
        put_text(im, headline, f, x, text_y+round((1-p)*38*scale), ink, p*alpha)
        bounds = f.getbbox(headline); h = bounds[3]-bounds[1]
        if style == 'motion_closure' and title.get('line2'):
            p2=ease((index+1-enter*.25)/max(1,enter*.85))
            line2=title['line2']; f2=font_fit(line2,path,size,maxw,fi)
            put_text(im,line2,f2,x,text_y+h+round(15*scale)+round((1-p2)*38*scale),ink,p2*alpha)
            h += f2.getbbox(line2)[3]-f2.getbbox(line2)[1]+round(15*scale)
        rule_y=text_y+h+round(31*scale)
        draw.line((x,rule_y,x+int(min(maxw,300*scale)*p),rule_y), fill=(*accent[:3],round(accent[3]*alpha)), width=max(1,round(3*scale)))
    return im

def render(title, index, outdir, W, H, fps, command_path='ffmpeg'):
    start=round(title['start']*fps); end=round(title['end']*fps); frames=end-start
    if frames <= 0:
        raise ValueError('Motion title must span at least one output frame')
    out=Path(outdir)/f'title_{index:02d}.mov'
    partial=out.with_name(out.stem+'.partial.mov')
    args=[str(command_path),'-v','error','-f','rawvideo','-pix_fmt','rgba','-s',f'{W}x{H}', '-r',str(fps),'-i','pipe:0','-frames:v',str(frames),'-an','-c:v','prores_ks','-profile:v','4444','-pix_fmt','yuva444p10le','-alpha_bits','16','-qscale:v','12','-threads','2','-y',str(partial)]
    process=subprocess.Popen(args,stdin=subprocess.PIPE,stderr=subprocess.PIPE)
    try:
        for n in range(frames):
            process.stdin.write(frame(title,W,H,n,frames,fps).tobytes())
        process.stdin.close()
        err=process.stderr.read().decode(errors='replace')
        if process.wait(): raise RuntimeError('Motion title encoding failed: '+err)
        partial.replace(out)
    except BaseException:
        process.kill(); process.wait(); partial.unlink(missing_ok=True)
        raise
    return out
