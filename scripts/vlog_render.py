"""Narration-first video renderer. Explicit album/workspace, immutable originals.
Recipe: blocks with audio file/in/out, words in source seconds, pictures with file/in/duration.
Pictures may differ from narration. All times are rounded onto a shared integer output clock.
"""
import argparse, hashlib, json, subprocess, html, concurrent.futures, math, shutil, tempfile, wave
from pathlib import Path
from fractions import Fraction
import numpy as np
from PIL import Image, ImageOps, ImageFilter, ImageFont
from photo_io import PHOTO_EXTENSIONS, open_photo
from pipeline import command, ffmpeg_binary, save, stamp
from pipeline_paths import guard_output_tree, movie_path
from quality_gate import MODEL, REVIEW_FILES, reviewer_effort, sha256_file, write_review_request
from vlog_captions import caption_preset, font_overrides, lines_for, verify_selected_faces, write_highlighted

FONT='/System/Library/Fonts/Supplemental/Arial Bold.ttf'
VERTICAL=(1080,1920)
LANDSCAPE=(1920,1080)
LOCAL_INPUT = ['-protocol_whitelist', 'file', '-i']
RENDER_FILES = ('media', 'graphics', 'photo_layers', 'editorial_audit.json', 'recipe.json', 'captions.ass', 'captions.srt',
                'timeline_words.json', 'caption_evidence.json', 'voice_concat.txt', 'picture_concat.txt',
                'loudness_pass1.log', 'narration.wav', 'narration_with_music.wav', 'music_processed.wav',
                'MUSIC_POLICY.json', 'MUSIC_CREDITS.txt', 'MUSIC_PROVENANCE.json', 'narration_with_sfx.wav',
                'SFX_TIMELINE.json', 'clean_picture.mp4', 'graphics_movie.mp4', 'graphics.ffgraph',
                'render.log', 'render_manifest.json', 'Review Vlog.html', *REVIEW_FILES)

def frames(t,fps=30): return round(t*fps)
def digest(obj): return hashlib.sha256(json.dumps(obj,sort_keys=True).encode()).hexdigest()[:20]
def probe(path):
 return json.loads(command(['ffprobe','-v','error','-protocol_whitelist','file','-show_format','-show_streams','-of','json',path]))
def identity(path):
 s=path.stat();return [str(path.resolve()),s.st_size,s.st_mtime_ns]
def stream_duration(p,kind):
 s=next(s for s in p['streams'] if s['codec_type']==kind)
 if s.get('duration'):return float(s['duration'])
 if s.get('duration_ts') is not None:return float(Fraction(s['time_base'])*s['duration_ts'])
 return float(p['format']['duration'])

def guard_paths(r, *, recipe_path=None, writable=None):
 album=Path(r['album']).resolve(); movie=movie_path(r)
 sources=[Path(recipe_path)] if recipe_path is not None else []
 if any(c in str(movie.parent) for c in '\r\n'):
  raise ValueError('Output paths cannot contain line breaks')
 for b in r['blocks']:
  for name in [b['audio']]+[v['file'] for v in b['pictures']]:
   source=(album/name).resolve()
   if (not source.is_file() or not source.is_relative_to(album)
       or source.is_relative_to(album/'Edit_Workspace') or 'Personal Content' in source.parts):
    raise ValueError(f'Source must be a permitted original in the album: {name}')
   sources.append(source)
 for event in r.get('sfx', []): sources.append(Path(event['file']).expanduser())
 if r.get('music_bed'): sources.append(Path(r['music_bed']['file']).expanduser())
 for spec in r.get('graphics', [])+r.get('transitions', []):
  sources.append(Path(spec['asset']).expanduser())
  if spec.get('font'): sources.append(Path(spec['font']).expanduser())
 for comp in r.get('photo_compositions', []):
  for spec in comp['photos']+comp.get('artwork', [])+[comp.get('background', {})]:
   if spec.get('file'): sources.append(Path(spec['file']).expanduser())
   sources.extend(Path(mark['file']).expanduser() for mark in spec.get('artwork', []))
 if caption_preset(r)=='avenir_highlight': sources.extend(font_overrides(r).values())
 names=(*RENDER_FILES, movie.name) if writable is None else writable
 out=guard_output_tree(movie.parent, sources, album=album, writable=names)
 return album,out

def validate(r,album):
 if r['fps']!=30 or (r['width'],r['height']) not in (VERTICAL,LANDSCAPE):
  raise ValueError('Narrated videos require 1080×1920 or 1920×1080 at 30 fps')
 if not r['blocks']: raise ValueError('Empty story')
 for b in r['blocks']:
  if not (math.isfinite(b['in']) and math.isfinite(b['out']) and 0<=b['in']<b['out']):
   raise ValueError('Invalid narration bounds')
  d=round((b['out']-b['in'])*30)/30
  if d<=0: raise ValueError('Narration block shorter than one output frame')
  if not b.get('mute',False):
   p=probe(album/b['audio'])
   if not any(s['codec_type']=='audio' for s in p['streams']): raise ValueError('Missing narration')
   if b['out']>stream_duration(p,'audio')+.02: raise ValueError('Narration exceeds source audio duration')
  prev=b['in']
  for w in b.get('words',[]):
   if not b['in']-.06<=w['start']<w['end']<=b['out']+.06: raise ValueError('Word outside selected narration')
   if w['start']<prev-.06: raise ValueError('Nonmonotonic words')
   prev=w['start']
  for v in b['pictures']:
   if not (album/v['file']).is_file() or not math.isfinite(v['duration']) or frames(v['duration'])<=0:
    raise ValueError('Missing picture or invalid picture duration')
   speed=float(v.get('speed',1))
   if not .25<=speed<=8: raise ValueError('Picture speed outside supported range')
   for key in ('crop_x','crop_y'):
    if not 0<=float(v.get(key,.5))<=1: raise ValueError(f'{key} must be within [0, 1]')
   start=float(v.get('in',0))
   if not math.isfinite(start) or start<0: raise ValueError('Invalid picture source offset')
   if Path(v['file']).suffix.lower() not in PHOTO_EXTENSIONS:
    p=probe(album/v['file'])
    if start+v['duration']*speed>stream_duration(p,'video')+.015:
     raise ValueError('Picture exceeds source video duration')
  if sum(frames(v['duration']) for v in b['pictures'])!=frames(d):
   raise ValueError('Picture/audio duration mismatch')
 return sum(frames(b['out']-b['in']) for b in r['blocks'])/30

def escape(t): return t.replace('\\','').replace('{','(').replace('}',')').replace('\n',' ')
def at(t):
 cs=round(t*100);return f'{cs//360000}:{cs//6000%60:02}:{cs//100%60:02}.{cs%100:02}'
def phrases(words):
 group=[]
 for w in words:
  if group and (len(group)>=12 or len(' '.join(x['text'] for x in group+[w]))>60 or w['end']-group[0]['start']>6.0):
   yield group;group=[]
  group.append(w)
  if w['text'].strip().endswith(('.', '?', '!', ';')):yield group;group=[]
 if group:yield group

def subtitles(r,out,evidence=None):
 width,height=r.get('width',1080),r.get('height',1920)
 landscape=(width,height)==LANDSCAPE
 voice_size,card_size,note_size=(54,56,48) if landscape else (64,62,56)
 voice_margin=144 if landscape else 340
 header=f'''[Script Info]
ScriptType: v4.00+
PlayResX: {width}
PlayResY: {height}
WrapStyle: 0
[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Voice,Arial,{voice_size},&H00FFFFFF,&H00FFFFFF,&H00181512,&H00181512,-1,0,0,0,100,100,0,0,3,16,0,2,90,150,{voice_margin},1
Style: Card,Arial,{card_size},&H00FFFFFF,&H00FFFFFF,&H00181512,&H00181512,-1,0,0,0,100,100,0,0,3,22,0,5,120,120,0,1
Style: Note,Arial,{note_size},&H00181512,&H00181512,&H00E8F5FF,&H00E8F5FF,-1,0,0,0,100,100,0,0,3,16,0,7,90,100,230,1
[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
'''
 preset=caption_preset(r)
 events=[];notes=[];plain=[];offset=0; mapped=[]
 for b in r['blocks']:
  words=[]
  for w in b.get('words',[]) if preset=='legacy' else []:
   a=max(offset,offset+w['start']-b['in']);z=min(offset+(b['out']-b['in']),offset+w['end']-b['in'])
   if z>a: words.append({'text':w['text'].strip(),'start':a,'end':z})
  mapped.extend(words)
  groups=list(phrases(words))
  if groups: font=ImageFont.truetype(FONT,voice_size)
  if landscape:
   pos=r'{\an8\pos(960,120)\q2}' if b.get('captions_top') else r'{\an2\pos(960,936)\q2}'
  else:
   pos=r'{\an8\pos(510,280)}' if b.get('captions_top') else ''
  for gi,g in enumerate(groups):
   line_break=None
   textwords=[w['text'] for w in g]
   if landscape:
    lines=lines_for(g,font,1320,12)
    if lines is None: raise ValueError('Landscape caption exceeds two lines or the width limit')
    if len(lines)==2: line_break=len(lines[0])
   elif font.getlength(' '.join(textwords))>810 and len(g)>1:
    line_break=min(range(1,len(g)),key=lambda k:max(font.getlength(' '.join(textwords[:k])),font.getlength(' '.join(textwords[k:]))))
   next_start=groups[gi+1][0]['start'] if gi+1<len(groups) else offset+(b['out']-b['in'])
   display_end=min(next_start,offset+(b['out']-b['in']),max(g[-1]['end'],g[0]['start']+.75))
   if landscape and frames(display_end)<=frames(g[0]['start']): continue
   plain_text=' '.join(textwords)
   if landscape and line_break: plain_text=' '.join(textwords[:line_break])+'\n'+' '.join(textwords[line_break:])
   plain.append((g[0]['start'],display_end,plain_text))
   # Keep phrase stable; highlight only the active word, never fill a silence gap.
   word_bounds=[x[k] for x in g for k in ('start','end')]
   if landscape: word_bounds=[time for time in word_bounds if g[0]['start']<time<display_end]
   bounds=sorted(set([g[0]['start'],display_end]+word_bounds))
   for a,z in zip(bounds,bounds[1:]):
    mid=(a+z)/2;bits=[]
    for w in g:
     c='&H0078DDFF&' if w['start']<=mid<w['end'] else '&H00FFFFFF&'
     bits.append('{\\1c'+c+'}'+escape(w['text']))
    if frames(z)>frames(a): events.append(f'Dialogue: 1,{at(a)},{at(z)},Voice,,0,0,0,,'+pos+ ((' '.join(bits[:line_break])+r'\N'+' '.join(bits[line_break:])) if line_break else ' '.join(bits)))
  for note in b.get('notes',[]):
   a=offset+note.get('at',0);z=min(offset+b['out']-b['in'],a+note.get('duration',3))
   style='Card' if note.get('kind')=='card' else 'Note'
   y=float(note.get('y',height/2 if landscape else 930))
   if not (math.isfinite(a) and math.isfinite(z) and 0<=y<=height and offset<=a<z):
    raise ValueError('Caption note has invalid timing or position')
   if style=='Card':
    center=width//2 if landscape else 510
    motion=fr'{{\fad(200,240)\an5\pos({center},{y})}}'
   else:
    motion=r'{\fad(160,180)\move(65,158,90,118,0,180)}' if landscape else r'{\fad(160,180)\move(65,270,90,230,0,180)}'
   text=escape(note['text']).replace('|',r'\N')
   notes.append(f'Dialogue: 2,{at(a)},{at(z)},{style},,0,0,0,,'+motion+text)
  offset+=frames(b['out']-b['in'])/30
 if preset=='avenir_highlight':
  ass,mapped,report=write_highlighted(r,out,header,notes)
  save(out/'timeline_words.json',mapped)
  if evidence is not None: evidence.update(report)
  return ass
 if evidence is not None: evidence['preset']=preset
 (out/'captions.ass').write_text(header+'\n'.join(events+notes)+'\n')
 def srt(t):return at(t).replace('.',',').split(':',1)[0].zfill(2)+':'+at(t).split(':',1)[1].replace('.',',')+'0'
 (out/'captions.srt').write_text('\n\n'.join(f'{i+1}\n{srt(a)} --> {srt(z)}\n{t}' for i,(a,z,t) in enumerate(plain))+'\n')
 save(out/'timeline_words.json',mapped)
 return out/'captions.ass'

def picture(v,album,out,index,geometry=VERTICAL):
 width,height=geometry
 source=album/v['file'];n=frames(v['duration'])
 cache_profile='vlog-1' if geometry==VERTICAL else ['narration-landscape-1',width,height]
 key=digest([v,identity(source),cache_profile]);dst=out/f'{index:04}_{key}.mp4'
 def valid(path):
  try:
   sv=next(x for x in probe(path)['streams'] if x['codec_type']=='video')
   if int(sv['nb_frames'])!=n or (sv['width'],sv['height'])!=geometry or Fraction(sv['avg_frame_rate'])!=30:
    return False
   command(['ffmpeg','-v','error','-xerror',*LOCAL_INPUT,path,'-map','0:v:0','-f','null','-'])
   return True
  except (RuntimeError, ValueError, KeyError, StopIteration):
   return False
 if dst.exists() and valid(dst): return dst
 # Reuse immutable derivatives from earlier versions; never link an original.
 for cached in out.parent.parent.glob(f'*/media/*_{key}.mp4'):
  if cached==dst:continue
  if cached.is_file() and not cached.is_symlink() and valid(cached):
   shutil.copy2(cached,dst);return dst
 args=['ffmpeg','-v','error','-threads','2'];photo=source.suffix.lower() in PHOTO_EXTENSIONS
 if photo:
  with open_photo(source) as original:
   im=ImageOps.exif_transpose(original).convert('RGB')
  bg=ImageOps.fit(im,geometry).filter(ImageFilter.GaussianBlur(35));bg=Image.blend(bg,Image.new('RGB',bg.size,(12,18,21)),.3)
  fit=(1010,1660) if geometry==VERTICAL else geometry
  fg=ImageOps.contain(im,fit,Image.Resampling.LANCZOS);bg.paste(fg,((width-fg.width)//2,(height-fg.height)//2));still=out/f'{key}.png';bg.save(still)
  args+=['-loop','1','-framerate','30',*LOCAL_INPUT,still];vf=''
 else:
  args+=['-ss',str(v.get('in',0)),*LOCAL_INPUT,source];p=probe(source);s=next(s for s in p['streams'] if s['codec_type']=='video')
  vf=''
  if s.get('color_transfer') in ('smpte2084','arib-std-b67'):vf='zscale=t=linear:npl=100,format=gbrpf32le,tonemap=tonemap=hable:desat=0,zscale=p=bt709:t=bt709:m=bt709:r=limited,format=yuv420p,'
 vf+=f"setpts=(PTS-STARTPTS)/{float(v.get('speed',1))},"
 if geometry==LANDSCAPE:
  # Use display aspect ratio and preserve the complete frame on landscape projects.
  vf+=f'scale={width}:{height}:force_original_aspect_ratio=decrease:force_divisible_by=2:reset_sar=1:flags=lanczos,pad={width}:{height}:(ow-iw)/2:(oh-ih)/2,'
 else:
  vf+=f"scale={width}:{height}:force_original_aspect_ratio=increase:flags=lanczos,crop={width}:{height}:(iw-ow)*{float(v.get('crop_x',.5))}:(ih-oh)*{float(v.get('crop_y',.5))},"
 vf+='setsar=1,fps=30,setpts=N/(30*TB)'
 with tempfile.TemporaryDirectory(dir=out) as temp:
  candidate=Path(temp)/'picture.mp4'
  command(args+['-map','0:v:0','-vf',vf,'-frames:v',str(n),'-an','-c:v','libx264','-preset','fast','-crf','19','-threads','2','-pix_fmt','yuv420p','-color_primaries','bt709','-color_trc','bt709','-colorspace','bt709','-video_track_timescale','30000','-n',candidate])
  if not valid(candidate): raise ValueError(f'Prepared picture failed verification: {source}')
  candidate.replace(dst)
 return dst

def timeline(r,pictures,voice,out,*,composite=None,audio_stems=(),caption_sidecars=None):
 from pipeline import finalcut
 shots=[];f=0
 for i,(v,path) in enumerate(pictures):
  shots.append({'id':f'S{i+1:03}','note':v.get('note',v['file']),'frames':frames(v['duration']),'start_frame':f});f+=frames(v['duration'])
 rr={**r,'shots':shots,'titles':[],'transitions':[],'music':{'track':'Reviewed audio mix'}}
 authored_overlays=composition_spans(r)
 overlays='No picture compositions were authored.'
 if composite:
  overlays='Connected baked composition windows include the underlying picture. Disable a window to reveal the clean shots.'
 elif authored_overlays:
  overlays='Legacy reconstruction uses clean shots. Authored graphics and photo compositions are available in the reviewed movie.'
 editability={
  'picture':'Individual clean shots can be moved or trimmed within their prepared media. Crop, grade and speed are baked.',
  'overlays':overlays,
  'audio':('Normalized narration and processed music are separate synchronized clips.' if audio_stems
           else 'Dialogue, voiceover and any music or effects in the reviewed mix share one audio clip.'),
  'captions':'Styled captions are in the reviewed movie and the ASS sidecar. Plain text and timing are in the SRT sidecar.',
  'native_captions':False,
 }
 return finalcut(rr,[p for v,p in pictures],[],voice,out,reviewed_movie=movie_path(r),
                 composite=composite,audio_stems=audio_stems,caption_sidecars=caption_sidecars,editability=editability)


def composition_spans(recipe):
 """Merge overlapping windows where the saved composition covers the clean spine."""
 fps=recipe['fps']
 windows=[]
 for key in ('graphics','transitions','photo_compositions'):
  for layer in recipe.get(key,[]):
   start=frames(layer['at'],fps)
   windows.append((start,start+frames(layer['duration'],fps)))
 merged=[]
 for start,end in sorted(windows):
  if merged and start<=merged[-1][1]:
   merged[-1]=(merged[-1][0],max(end,merged[-1][1]))
  else:
   merged.append((start,end))
 return merged


def pcm24_samples(raw):
 octets=np.frombuffer(raw,dtype=np.uint8).reshape(-1,3).astype(np.int32)
 values=octets[:,0]+(octets[:,1]<<8)+(octets[:,2]<<16)
 return (values^0x800000)-0x800000


def stems_match_mix(narration,music,mix,duration):
 """Use separate clips only when their aligned PCM sum preserves the reviewed mix."""
 expected=(2,3,48000,round(duration*48000))
 with wave.open(str(narration),'rb') as voice, wave.open(str(music),'rb') as bed, wave.open(str(mix),'rb') as final:
  inputs=(voice,bed,final)
  if any((wav.getnchannels(),wav.getsampwidth(),wav.getframerate(),wav.getnframes())!=expected for wav in inputs):
   return False
  while final.tell()<expected[3]:
   speech,song,mixed=(pcm24_samples(wav.readframes(48000)) for wav in inputs)
   if np.any(np.abs(speech+song-mixed)>2):
    return False
 return True


def save_timeline_layers(r,out,composed,voice,music_evidence):
 def identity(path):
  return {'path':str(path),'sha256':sha256_file(path)}
 layers={'captions':{name:identity(out/name) for name in ('captions.ass','captions.srt')}}
 if composition_spans(r):
  layers['composite']=identity(composed)
 if music_evidence and music_evidence.get('processed_music_stem') and not r.get('sfx'):
  narration=out/'narration.wav'
  music=Path(music_evidence['processed_music_stem'])
  if stems_match_mix(narration,music,voice,r['duration']):
   layers['audio']={'narration.wav':identity(narration),'music_processed.wav':identity(music)}
 return layers


def saved_timeline_layers(r,out,manifest):
 def checked(record,name):
  path=Path(record['path']).resolve()
  if path!=out/name or not path.is_file() or record['sha256']!=sha256_file(path):
   raise ValueError(f'Saved timeline media changed or is missing: {name}')
  return path
 layers=manifest.get('timeline_layers')
 if layers is None:
  return None,[],{}
 spans=composition_spans(r)
 composite=None
 if spans:
  composite={'path':checked(layers['composite'],'graphics_movie.mp4'),'spans':spans}
 stems=[]
 if 'audio' in layers:
  for name,title,role in (('narration.wav','Normalized narration','dialogue'),
                          ('music_processed.wav','Processed music bed','music')):
   stems.append({'path':checked(layers['audio'][name],name),'name':title,'role':role})
 sidecars={}
 for name in ('captions.ass','captions.srt'):
  record=layers['captions'][name]
  sidecars[name]={**record,'path':str(checked(record,name))}
 return composite,stems,sidecars

def music_protection(r):
 """Output-clock speech spans; absent transcripts never imply speech-free audio.

 Default protection covers each complete unmuted block, including pauses between
 words. Split a verified non-speaking passage into its own block with
 speech_free=true to allow music while retaining source ambience. That explicit
 declaration is rejected if the block contains words. Word bounds can extend
 protection but never punch holes inside a continuous narration block.
 """
 bed=r.get('music_bed',{});policy=bed.get('mix_policy','speech_free')
 if policy not in ('speech_free','quiet_bed','legacy_duck'):
  raise ValueError('music_bed.mix_policy must be speech_free, quiet_bed or legacy_duck')
 margin=float(bed.get('speech_margin',.2));fade=float(bed.get('speech_fade',.34 if policy=='quiet_bed' else .15))
 if not math.isfinite(margin) or margin<.05:
  raise ValueError('speech_margin must be finite and at least 0.05 seconds')
 if not math.isfinite(fade) or fade<=0:
  raise ValueError('speech_fade must be finite and positive')
 offset=0;spans=[]; speech=[]; silent=[]
 for b in r['blocks']:
  d=frames(b['out']-b['in'])/30
  if b.get('music_silent',False): silent.append([max(0,offset-margin),offset+d+margin])
  words=b.get('words',[])
  if b.get('speech_free',False) and words:
   raise ValueError('speech_free block cannot contain timed speech words')
  if b.get('music_protected',False) or (not b.get('mute',False) and not b.get('speech_free',False)):
   a=min([offset]+[offset+w['start']-b['in'] for w in words])
   z=max([offset+d]+[offset+w['end']-b['in'] for w in words])
   spans.append([a-margin,z+margin])
   speech.append({'role':b.get('audio_role','unspecified'),'start':offset,'end':offset+d})
  offset+=d
 if silent and policy=='legacy_duck': raise ValueError('music_silent requires quiet_bed or speech_free')
 merged=[]
 for a,z in spans:
  a=max(0,a);z=min(offset,z)
  if merged and a<=merged[-1][1]:merged[-1][1]=max(z,merged[-1][1])
  else:merged.append([a,z])
 evidence={'mix_policy':policy,'speech_margin':margin,'speech_fade':fade,
         'protected_intervals':merged,'music_silent_intervals':[[a,min(z,offset)] for a,z in silent],'duration':offset,
         'notes':'Timeline-derived conservative speech protection; not listened verification. '
                 'Music alone is gated after processing; source narration is not gated. '
                 'Zero-contribution guarantee applies to the PCM mix before lossy delivery encoding.'}
 if policy=='quiet_bed':
  attenuation=float(bed.get('speech_attenuation_db',-8))
  target=float(bed.get('target_lufs',-23))
  release=float(bed.get('speech_release',.62 if 'speech_fade' not in bed else fade))
  if not -40<=attenuation<=-3 or not -55<=target<=-18:
   raise ValueError('Quiet bed requires speech_attenuation_db in [-40,-3] and target_lufs in [-55,-18]')
  if not math.isfinite(release) or release<=0: raise ValueError('speech_release must be finite and positive')
  evidence.update(speech_attenuation_db=attenuation,target_lufs=target,speech_release=release,speech_windows=speech,
                  notes='Sample-eased music attenuation around protected speech windows. '
                        'PCM stem RMS is in dBFS. Listening remains unverified.')
 elif 'source_offset' in bed or 'cues' in bed:
  raise ValueError('Music source offsets and cues require quiet_bed')
 return evidence

def music_gate_expression(evidence):
 base = _speech_gate_expression(evidence)
 silent = evidence.get('music_silent_intervals', [])
 if not silent: return base
 zero = _speech_gate_expression({**evidence, 'mix_policy':'speech_free', 'protected_intervals':silent})
 return f'({base})*({zero})'

def _speech_gate_expression(evidence):
 # aeval evaluates every sample, unlike frame-evaluated volume. Ramps finish
 # outside protected spans; exact digital zero covers both safety handles.
 fade=evidence['speech_fade'];release=evidence.get('speech_release',fade);terms=[]
 quiet=evidence['mix_policy']=='quiet_bed'
 floor=10**(evidence['speech_attenuation_db']/20) if quiet else 0
 for a,z in evidence['protected_intervals']:
  ramp=f"if(lt(t,{a:.9f}),min(1,({a:.9f}-t)/{fade}),if(lte(t,{z:.9f}),0,min(1,(t-{z:.9f})/{release})))"
  terms.append(f'{floor:.12f}+{1-floor:.12f}*(1-cos(PI*({ramp})))/2' if quiet else ramp)
 if not quiet: return '*'.join(terms) or '1'
 # The lowest envelope wins when release and attack overlap. Overlapping ramps
 # never compound below the configured plateau.
 if not terms: return '1'
 # Pairwise minimum nesting stays shallow even for long timelines.
 while len(terms)>1:
  terms=[f'min({terms[i]},{terms[i+1]})' if i+1<len(terms) else terms[i] for i in range(0,len(terms),2)]
 return terms[0]

def music_cues(bed,duration,source_duration):
 cues=bed.get('cues')
 if cues is not None and ('source_offset' in bed or not isinstance(cues,list) or not cues):
  raise ValueError('Provide a nonempty cues list or a single source_offset')
 if cues is None:
  cues=[{'in':bed.get('source_offset',0),'at':0,'duration':duration,
         'fade_in':min(.6,duration),'fade_out':min(2,duration)}]
 result=[]
 for spec in cues:
  source,at,count,attack,release=[float(spec[k]) for k in ('in','at','duration','fade_in','fade_out')]
  if (not all(math.isfinite(v) for v in (source,at,count,attack,release)) or min(source,at,attack,release)<0
      or count<1/48000 or max(attack,release)>count or at+count>duration+1e-8
      or source+count>source_duration+1e-8):
   raise ValueError('Music cue exceeds source or output bounds or has an invalid fade')
  result.append({'in':source,'at':at,'duration':count,'fade_in':attack,'fade_out':release})
 result.sort(key=lambda cue:cue['at'])
 for i,(previous,cue) in enumerate(zip(result,result[1:])):
  overlap=previous['at']+previous['duration']-cue['at']
  if (overlap>min(previous['fade_out'],cue['fade_in'])+1e-8 or
      cue['at']<=previous['at'] or (i and result[i-1]['at']+result[i-1]['duration']>cue['at']+1e-8)):
   raise ValueError('Overlapping music cues require two authored fades and no third cue')
 return result

def measure_music_windows(stem,windows):
 import numpy as np
 def dbfs(value): return round(10*math.log10(value),2) if value>0 else None
 with wave.open(str(stem),'rb') as wav:
  rate=wav.getframerate(); results=[]
  for window in windows:
   start,end=(min(wav.getnframes(),round(window[key]*rate)) for key in ('start','end'))
   wav.setpos(start); energy=0; count=0; peak=0
   while start<end:
    values=pcm24_samples(wav.readframes(min(end-start,round(.75*rate))))/2**23
    total=float(values@values); energy+=total; count+=values.size
    peak=max(peak,total/values.size)
    start+=values.size//wav.getnchannels()
   results.append({**window,'rms_dbfs':dbfs(energy/count) if count else None,
                   'loudest_local_rms_dbfs':dbfs(peak)})
 return results

def mix_quiet_bed(r,voice,music,mixed,evidence,stem):
 duration=evidence['duration']
 cues=music_cues(r['music_bed'],duration,stream_duration(probe(music),'audio'))
 graph=[]; labels=[]
 for i,cue in enumerate(cues):
  start,at,count,attack,release=[cue[k] for k in ('in','at','duration','fade_in','fade_out')]
  base=(f'[0:a:0]atrim=start={start}:duration={count},asetpts=PTS-STARTPTS,'
        f'loudnorm=I={evidence["target_lufs"]}:TP=-3:LRA=11,aresample=48000,aformat=channel_layouts=stereo')
  if attack: base+=f',afade=t=in:d={attack}:curve=hsin'
  if release: base+=f',afade=t=out:st={count-release}:d={release}:curve=hsin'
  label=f'[cue{i}]'; labels.append(label)
  graph.append(base+f',adelay={round(at*48000)}S:all=1'+label)
 gate=music_gate_expression(evidence)
 combine=''.join(labels)+f'amix=inputs={len(cues)}:normalize=0:dropout_transition=0,' if len(cues)>1 else labels[0]
 graph.append(combine+f"apad,atrim=duration={duration},aeval=exprs='val(0)*({gate})|val(1)*({gate})'[bed]")
 command(['ffmpeg','-v','error','-protocol_whitelist','file','-i',music,'-filter_complex',';'.join(graph),
          '-map','[bed]','-ar','48000','-ac','2','-c:a','pcm_s24le','-y',stem])
 command(['ffmpeg','-v','error',*LOCAL_INPUT,voice,*LOCAL_INPUT,stem,'-filter_complex',
          '[0:a:0][1:a:0]amix=inputs=2:normalize=0:duration=first:dropout_transition=0[mix]',
          '-map','[mix]','-ar','48000','-ac','2','-c:a','pcm_s24le','-y',mixed])
 evidence.update(cues=cues,processed_music_stem=str(stem),
                 measured_speech_windows=measure_music_windows(stem,evidence['speech_windows']))
 return evidence

def mix_music_bed(r,voice,music,mixed,stem=None):
 """Keep narration untouched; isolate all music processing before its gate."""
 evidence=music_protection(r);d=evidence['duration']
 if evidence['mix_policy']=='quiet_bed':
  return mix_quiet_bed(r,voice,music,mixed,evidence,stem or mixed.with_name('music_processed.wav'))
 fade_out=min(2,d);fade_in=min(.6,d)
 base=f'[1:a]atrim=duration={d},asetpts=PTS-STARTPTS,loudnorm=I=-27:TP=-3:LRA=11,afade=t=in:d={fade_in},afade=t=out:st={max(0,d-fade_out)}:d={fade_out},aresample=48000,aformat=channel_layouts=stereo'
 if evidence['mix_policy']=='legacy_duck':
  graph=base+'[bed];[0:a]asplit=2[voice][control];[bed][control]sidechaincompress=threshold=.015:ratio=10:attack=15:release=300[duck];[voice][duck]amix=inputs=2:normalize=0,alimiter=limit=.89:level=false[mix]'
 else:
  gate=music_gate_expression(evidence)
  graph=base+f",aeval=exprs='val(0)*({gate})|val(1)*({gate})'[bed];[0:a][bed]amix=inputs=2:normalize=0:duration=first:dropout_transition=0[mix]"
 command(['ffmpeg','-v','error',*LOCAL_INPUT,voice,*LOCAL_INPUT,music,'-filter_complex',graph,'-map','[mix]','-t',str(d),'-ar','48000','-ac','2','-c:a','pcm_s24le','-y',mixed])
 return evidence

def sfx_events(r):
 """Explicit editorial effects only; never infer or manufacture scene ambience."""
 d=sum(frames(b['out']-b['in']) for b in r['blocks'])/30
 events=[]
 for event in r.get('sfx',[]):
  source=Path(event['file']).expanduser().resolve()
  if not source.is_file():raise ValueError(f'Missing SFX file: {source}')
  a=float(event.get('in',0));duration=float(event['duration'])
  at=float(event['at']);gain=float(event.get('gain_db',-12))
  if not all(math.isfinite(x) for x in (a,duration,at,gain)):
   raise ValueError('SFX timing and gain must be finite')
  if a<0 or duration<=0 or at<0 or at+duration>d+1e-9:
   raise ValueError('SFX outside source/output bounds')
  if not -60<=gain<=0:raise ValueError('SFX gain_db must be between -60 and 0')
  if a+duration>stream_duration(probe(source),'audio')+.00002:
   raise ValueError('SFX exceeds source audio duration')
  events.append({'file':str(source),'in':a,'duration':duration,'at':at,
                 'gain_db':gain,'identity':identity(source)})
 return events

def mix_sfx(r,voice,mixed):
 events=sfx_events(r)
 if not events:raise ValueError('mix_sfx needs explicit events')
 args=['ffmpeg','-v','error',*LOCAL_INPUT,voice];filters=[];labels=['[0:a:0]']
 for i,event in enumerate(events,1):
  args+=[*LOCAL_INPUT,event['file']]
  # Delay in samples avoids milliseconds rounding; only the effect is trimmed.
  samples=round(event['at']*48000);label=f'sfx{i}'
  filters.append(f"[{i}:a:0]atrim=start={event['in']}:duration={event['duration']},asetpts=PTS-STARTPTS,aresample=48000,aformat=channel_layouts=stereo,volume={event['gain_db']}dB,adelay={samples}S:all=1[{label}]")
  labels.append(f'[{label}]')
 filters.append(''.join(labels)+f'amix=inputs={len(labels)}:normalize=0:duration=first:dropout_transition=0[mix]')
 command(args+['-filter_complex',';'.join(filters),'-map','[mix]','-ar','48000','-ac','2','-c:a','pcm_s24le','-y',mixed])
 return {'events':events,'notes':'Explicit editorial sound effects; no synthesized documentary ambience. '
         'Source voice is not gated; listening and final mixed peak acceptance remain unverified.'}

def verify_movie(r,movie,decode_log=None,audio_log=None):
 info=probe(movie); video=[s for s in info['streams'] if s['codec_type']=='video']; audio=[s for s in info['streams'] if s['codec_type']=='audio']
 if len(info['streams'])!=2 or len(video)!=1 or len(audio)!=1:
  raise ValueError('Expected exactly one picture and one audio stream')
 v,a=video[0],audio[0]; expected=sum(frames(b['out']-b['in'],r['fps']) for b in r['blocks'])
 checks={'duration':float(info['format']['duration']),'frames':int(v['nb_frames']),'expected_frames':expected,
         'dimensions':[v['width'],v['height']],'fps':v['avg_frame_rate'],'transfer':v.get('color_transfer'),
         'primaries':v.get('color_primaries'),'matrix':v.get('color_space'),'video':v['codec_name'],
         'pixel_format':v.get('pix_fmt'),'audio':a['codec_name'],'audio_duration':stream_duration(info,'audio')}
 if (checks['frames']!=expected or checks['dimensions']!=[r['width'],r['height']]
     or Fraction(checks['fps'])!=r['fps'] or abs(checks['duration']-expected/r['fps'])>=.08
     or abs(checks['audio_duration']-expected/r['fps'])>=.08
     or any(checks[k]!='bt709' for k in ('transfer','primaries','matrix'))
     or checks['video']!='h264' or checks['pixel_format']!='yuv420p'
     or v.get('sample_aspect_ratio')!='1:1' or checks['audio']!='aac'):
  raise ValueError('Rendered movie does not match recipe geometry, timing or stream format')
 command(['ffmpeg','-v','error','-xerror',*LOCAL_INPUT,movie,'-map','0:v:0','-map','0:a:0','-f','null','-'],decode_log)
 log=command(['ffmpeg','-v','info',*LOCAL_INPUT,movie,'-map','0:a:0','-af',
              'loudnorm=I=-16:TP=-1.5:LRA=11:print_format=json','-f','null','-'],audio_log)
 stats=json.loads(log[log.rfind('{'):log.rfind('}')+1]); checks['audio_loudness']=stats
 if not float(stats['input_tp'])<=-.4: raise ValueError('Encoded audio true peak exceeds -0.4 dBTP')
 return checks

def encode_movie(r,out,ass,composed,voice,movie,caption_evidence):
 # Keep the filter paths constant and independent of the recipe/output names.
 has_captions=any(line.startswith('Dialogue:') for line in ass.read_text().splitlines())
 ffmpeg=ffmpeg_binary('ass') if has_captions else ffmpeg_binary()
 with tempfile.TemporaryDirectory(dir=out) as temp:
  scratch=Path(temp)
  vf='setpts=N/(30*TB)'
  if has_captions:
   shutil.copyfile(ass,scratch/'captions.ass')
   vf+=',ass=filename=captions.ass'
  overrides=font_overrides(r) if has_captions and caption_evidence['preset']=='avenir_highlight' else {}
  if overrides:
   (scratch/'fonts').mkdir()
   for style,path in overrides.items(): shutil.copyfile(path,scratch/'fonts'/f'{style}{path.suffix.lower()}')
   vf+=':fontsdir=fonts'
  candidate=scratch/'movie.mp4'
  result=subprocess.run([ffmpeg,'-v','info','-xerror',*LOCAL_INPUT,str(composed),*LOCAL_INPUT,str(voice),
                         '-map','0:v:0','-map','1:a:0','-vf',vf+',setparams=color_primaries=bt709:color_trc=bt709:colorspace=bt709',
                         '-t',str(r['duration']),'-c:v','libx264',
                         '-preset','fast','-crf','19','-threads','6','-pix_fmt','yuv420p','-color_primaries','bt709',
                         '-color_trc','bt709','-colorspace','bt709','-c:a','aac','-b:a','256k','-movflags','+faststart',
                         '-map_metadata','-1','-n',str(candidate)],cwd=scratch,capture_output=True,text=True)
  (out/'render.log').write_text(result.stderr)
  if result.returncode: raise RuntimeError(result.stderr[-3500:])
  if caption_evidence['preset']=='avenir_highlight': verify_selected_faces(caption_evidence,result.stderr)
  checks=verify_movie(r,candidate)
  candidate.replace(movie)
 return checks

def render(recipe):
 r=json.loads(recipe.read_text());album,out=guard_paths(r,recipe_path=recipe)
 reviewer_effort(r)
 r['duration']=validate(r,album)
 from editorial_plan import require_plan
 editorial = require_plan(r)
 if r.get('music_bed'):music_protection(r)
 if r.get('sfx'):sfx_events(r)
 out.mkdir(parents=True,exist_ok=True);media=out/'media';media.mkdir(exist_ok=True)
 save(out/'editorial_audit.json',editorial)
 caption_evidence={};ass=subtitles(r,out,caption_evidence)
 items=[v for b in r['blocks'] for v in b['pictures']]
 geometry=(r['width'],r['height'])
 with concurrent.futures.ThreadPoolExecutor(max_workers=3) as pool:
  paths=list(pool.map(lambda z:picture(z[1],album,media,z[0],geometry),enumerate(items)))
 voices=[]
 for b in r['blocks']:
  key=digest([b['audio'],b['in'],b['out'],b.get('mute',False),identity(album/b['audio'])]);dst=media/f'voice_{key}.wav';voices.append(dst)
  if not dst.exists() and b.get('mute',False):command(['ffmpeg','-v','error','-f','lavfi','-i','anullsrc=r=48000:cl=stereo','-t',str(frames(b['out']-b['in'])/30),'-map','0:a:0','-c:a','pcm_s16le','-n',dst])
  elif not dst.exists():command(['ffmpeg','-v','error','-ss',str(b['in']),*LOCAL_INPUT,album/b['audio'],'-map','0:a:0','-vn','-af',f"atrim=duration={frames(b['out']-b['in'])/30},asetpts=PTS-STARTPTS,highpass=f=80,afade=t=in:d=0.006,afade=t=out:st={max(0,frames(b['out']-b['in'])/30-.012)}:d=0.012",'-ar','48000','-ac','2','-c:a','pcm_s16le','-n',dst])
 def cat(paths,name):
  p=out/name;p.write_text(''.join("file '"+str(x).replace("'","'\\''")+"'\n" for x in paths));return p
 voice=out/'narration.wav';raw=out/'voice_concat.txt';cat(voices,raw.name)
 measure=command(['ffmpeg','-v','info','-f','concat','-safe','0',*LOCAL_INPUT,raw,'-map','0:a:0','-af','loudnorm=I=-16:TP=-1.5:LRA=11:print_format=json','-f','null','-'],out/'loudness_pass1.log');stats=json.loads(measure[measure.rfind('{'):measure.rfind('}')+1])
 norm=f"loudnorm=I=-16:TP=-1.5:LRA=11:measured_I={stats['input_i']}:measured_TP={stats['input_tp']}:measured_LRA={stats['input_lra']}:measured_thresh={stats['input_thresh']}:offset={stats['target_offset']}:linear=true"
 filters=['-af',norm] if math.isfinite(float(stats['input_i'])) else []
 command(['ffmpeg','-v','error','-f','concat','-safe','0',*LOCAL_INPUT,raw,'-map','0:a:0',*filters,'-ar','48000','-ac','2','-c:a','pcm_s24le','-y',voice])
 music_evidence=None
 if r.get('music_bed'):
  bed=r['music_bed'];music=Path(bed['file']).expanduser()
  if not music.is_file() or not bed.get('credits'): raise ValueError('Music requires a source and credits')
  mixed=out/'narration_with_music.wav'
  music_evidence=mix_music_bed(r,voice,music,mixed);voice=mixed
  save(out/'MUSIC_POLICY.json',music_evidence)
  (out/'MUSIC_CREDITS.txt').write_text(bed['credits']+'\n');save(out/'MUSIC_PROVENANCE.json',bed)
 if r.get('sfx'):
  mixed=out/'narration_with_sfx.wav'
  save(out/'SFX_TIMELINE.json',mix_sfx(r,voice,mixed));voice=mixed
 clean=out/'clean_picture.mp4';command(['ffmpeg','-v','error','-f','concat','-safe','0',*LOCAL_INPUT,cat(paths,'picture_concat.txt'),'-map','0:v:0','-an','-c:v','copy','-y',clean])
 composed=clean
 if r.get('graphics') or r.get('transitions') or r.get('photo_compositions'):
  from vlog_graphics import apply_graphics
  from vlog_photo_layers import prepare_photo_layers
  photo_layers=prepare_photo_layers(r,out) if r.get('photo_compositions') else []
  composed=apply_graphics(clean,r,out,prepared_layers=photo_layers)
 movie=out/movie_path(r).name
 checks=encode_movie(r,out,ass,composed,voice,movie,caption_evidence)
 timeline_layers=save_timeline_layers(r,out,composed,voice,music_evidence)
 save(out/'caption_evidence.json',caption_evidence)
 save(out/'recipe.json',r)
 request=write_review_request(r,movie)
 save(out/'render_manifest.json',{'created':stamp(),'recipe':str(recipe),'recipe_sha256':sha256_file(out/'recipe.json'),
      'movie':str(movie),'duration':r['duration'],'sha256':request['movie_sha256'],'request_id':request['request_id'],
      'source_audio':any(not b.get('mute',False) for b in r['blocks']),
      'finalcut_export':'deferred; export after review and exact confirmation',
      'subtitle_editing':'ASS/SRT sidecars for caption styling and timing; the Final Cut XML does not include native captions',
      'captions':{'preset':caption_evidence['preset'],'evidence':'caption_evidence.json'},
      'music':{'policy':'MUSIC_POLICY.json','processed_stem':music_evidence.get('processed_music_stem')} if music_evidence else None,
      'technical':checks,'pictures':len(paths),'prepared_pictures':[str(p) for p in paths],'composed_picture':str(composed),
      'timeline_input_sha256':{'pictures':[sha256_file(p) for p in paths],'audio':sha256_file(voice)},
      'timeline_layers':timeline_layers,
      'graphics_manifest':str(out/'graphics'/'manifest.json') if r.get('graphics') or r.get('transitions') else None,
      'photo_layers_manifest':str(out/'photo_layers'/'manifest.json') if r.get('photo_compositions') else None,
      'narration_mix':str(voice)})
 title=html.escape(r.get('name') or r.get('project_slug') or 'Vlog')
 page=f'''<!doctype html><meta charset="utf-8"><title>{title} · {html.escape(r['version'])}</title><style>body{{background:#121518;color:#eee;font:18px system-ui;margin:30px auto;max-width:900px}}video{{height:82vh;max-width:100%}}a{{color:#ffdd78}}</style><h1>{title}</h1><video controls src="{movie.name}"></video><p>{html.escape(r['version'])} · <a href="captions.srt">Subtitles</a> · <a href="captions.ass">Editable captions</a></p>'''
 (out/'Review Vlog.html').write_text(page)
 print(movie,flush=True)

def export_finalcut(recipe):
 r=json.loads(recipe.read_text())
 movie=movie_path(r)
 out=guard_output_tree(movie.parent,album=r['album'])
 from pipeline_paths import timeline_path
 destinations={out/name for name in (timeline_path(r,movie).name,'finalcut_validation.txt','finalcut_export_checks.json','finalcut_app_verification.json')}
 for source in (recipe,r.get('finalcut_review_report')):
  if source and Path(source).resolve() in destinations: raise ValueError('Final Cut output would overwrite an input document')
 saved=out/'recipe.json';manifest=json.loads((out/'render_manifest.json').read_text());rr=json.loads(saved.read_text())
 saved_movie=movie_path(rr)
 digest=sha256_file(movie)
 if (movie.resolve()!=saved_movie.resolve() or Path(manifest['movie']).resolve()!=movie.resolve()
     or manifest['sha256']!=digest or manifest['duration']!=rr['duration']
     or manifest.get('recipe_sha256')!=sha256_file(saved)):
  raise ValueError('Saved reconstruction and rendered movie identities differ')
 approval_fields={'finalcut_review_report','finalcut_user_confirmation','finalcut_export'}
 ignored=approval_fields|{'duration'}
 if {k:v for k,v in r.items() if k not in ignored}!={k:v for k,v in rr.items() if k not in ignored}:
  raise ValueError('Current recipe differs from the saved cut. Use the matching recipe and review.')
 for key in approval_fields:
  rr.pop(key,None)
  if key in r:
   rr[key]=r[key]
 items=[v for b in rr['blocks'] for v in b['pictures']]
 paths=[Path(x).resolve() for x in manifest['prepared_pictures']]
 voice=Path(manifest.get('narration_mix',out/'narration.wav')).resolve()
 if (len(paths)!=len(items) or any(p.parent!=out/'media' or not p.is_file() for p in paths)
     or voice.parent!=out or not voice.is_file()
     or voice.name not in ('narration.wav','narration_with_music.wav','narration_with_sfx.wav')):
  raise ValueError('Saved timeline media is outside its reconstruction paths or incomplete')
 if manifest.get('timeline_input_sha256')!={'pictures':[sha256_file(p) for p in paths],'audio':sha256_file(voice)}:
  raise ValueError('Saved timeline media changed or lacks render-time hashes')
 request=json.loads((out/'director_review_request.json').read_text())
 if (Path(request.get('movie','')).resolve()!=movie.resolve()
     or request.get('movie_sha256')!=digest or request.get('request_id')!=manifest.get('request_id')
     or request.get('version')!=rr['version'] or request.get('reviewer_model')!=MODEL
     or request.get('reasoning_effort')!=reviewer_effort(rr)):
  raise ValueError('Director review request belongs to another render')
 composite,stems,sidecars=saved_timeline_layers(rr,out,manifest)
 return timeline(rr,list(zip(items,paths)),voice,out,composite=composite,audio_stems=stems,caption_sidecars=sidecars)

if __name__=='__main__':
 p=argparse.ArgumentParser(description=__doc__);p.add_argument('recipe',type=Path);p.add_argument('--export-finalcut',action='store_true',help='Recreate timeline from saved render, without rerendering video');args=p.parse_args()
 if args.export_finalcut:
  print(export_finalcut(args.recipe))
 else:render(args.recipe)
