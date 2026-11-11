"""Probe/decode/loudness checks and bounded output sheets for a saved vlog recipe."""
import argparse,json
from pathlib import Path
from PIL import Image,ImageDraw,ImageFont
from pipeline import command,save,stamp
from pipeline_paths import movie_path
from quality_gate import MODEL, reviewer_effort, sha256_file
from vlog_render import LOCAL_INPUT, guard_paths, verify_movie

def review(recipe_path):
 recipe_path=Path(recipe_path);r=json.loads(recipe_path.read_text());movie=movie_path(r)
 duration=sum(round((b['out']-b['in'])*r['fps']) for b in r['blocks'])/r['fps']
 sheets=[f'review_sheet_{i+1:02}.jpg' for i in range(int(duration/30)+1)]
 names=('decode_check.log','audio_check.log','review_frames','Cover.jpg','qa_report.json',*sheets)
 _,out=guard_paths(r,recipe_path=recipe_path,writable=names)
 saved_recipe=out/'recipe.json'; manifest=json.loads((out/'render_manifest.json').read_text())
 recipe_sha=sha256_file(saved_recipe)
 if manifest['recipe_sha256']!=recipe_sha or json.loads(saved_recipe.read_text())!={**r,'duration':duration}:
  raise ValueError('Recipe has changed since this render. Render again before QA.')
 request_path=out/'director_review_request.json'
 request=json.loads(request_path.read_text()); movie_sha=sha256_file(movie)
 if (request['movie_sha256']!=movie_sha or manifest['sha256']!=movie_sha
     or Path(request['movie']).resolve()!=movie.resolve() or Path(manifest['movie']).resolve()!=movie.resolve()
     or not request['request_id'] or request['request_id']!=manifest['request_id']
     or request['reviewer_model']!=MODEL or request['reasoning_effort']!=reviewer_effort(r)
     or request['version']!=r['version']):
  raise ValueError('Director review request belongs to another movie')
 checks=verify_movie(r,movie,out/'decode_check.log',out/'audio_check.log')
 frames=out/'review_frames';frames.mkdir(exist_ok=True)
 for old in frames.glob('*.jpg'): old.unlink()
 tw,th=(320,180) if r['width']>r['height'] else (180,320)
 columns=3 if tw>th else 6
 row_height=th+26
 command(['ffmpeg','-v','error',*LOCAL_INPUT,movie,'-map','0:v:0','-vf',f'fps=1,scale={tw}:{th}','-q:v','3','-y',frames/'%04d.jpg'])
 files=sorted(frames.glob('*.jpg'));font=ImageFont.truetype('/System/Library/Fonts/Supplemental/Arial.ttf',16)
 for start in range(0,len(files),30):
  batch=files[start:start+30]
  rows=(len(batch)+columns-1)//columns
  im=Image.new('RGB',(columns*tw,rows*row_height),(22,22,22));draw=ImageDraw.Draw(im)
  for j,f in enumerate(batch):
   x=j%columns*tw;y=j//columns*row_height
   with Image.open(f,formats=['JPEG']) as thumb: im.paste(thumb,(x,y+26))
   draw.text((x+5,y+3),f'{start+j+.5:.1f}s',fill='white',font=font)
  im.save(out/f'review_sheet_{start//30+1:02}.jpg',quality=92)
 command(['ffmpeg','-v','error','-ss',str(min(1,duration/2)),*LOCAL_INPUT,movie,'-map','0:v:0','-frames:v','1','-y',out/'Cover.jpg'])
 if (sha256_file(movie)!=movie_sha or json.loads(request_path.read_text())!=request
     or sha256_file(saved_recipe)!=recipe_sha):
  raise ValueError('Movie, recipe or director review request changed during QA')
 save(out/'qa_report.json',{'checked':stamp(),'movie_sha256':movie_sha,'recipe_sha256':recipe_sha,'request_id':request['request_id'],'technical':checks,'decode':'pass','visual':'pending; samples at 1-second cadence only','transcript_accuracy':'unverified; source listening required','finalcut':'deferred until independent score >=85 and explicit user confirmation','director_review':'pending'})
 print(json.dumps(checks,indent=2))
if __name__=='__main__':
 p=argparse.ArgumentParser(description=__doc__);p.add_argument('recipe',type=Path);review(p.parse_args().recipe)
