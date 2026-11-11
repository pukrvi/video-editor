"""Build an offline video review page and cover from the current render."""
import argparse
import hashlib
import html
import json
import os
import re
from pathlib import Path
from tempfile import TemporaryDirectory
from urllib.parse import quote

from PIL import Image

from pipeline import ROOT, command, current_recipe, load, reel_frame_count, require, title_png
from pipeline_paths import guard_output_tree, movie_path, recipe_mode


def relative_link(path, folder):
    return html.escape(quote(os.path.relpath(path, folder)), quote=True)


def build(recipe, *, root_copy=True):
    require(recipe_mode(recipe) == 'music_reel', 'Use pipeline.py qa for the narrated review player')
    movie = movie_path(recipe)
    outdir = guard_output_tree(movie.parent, writable=('Cover.jpg', 'Review Reel.html'))
    if root_copy:
        guard_output_tree(ROOT, writable=('Review Reel.html',))
    cover = outdir/'Cover.jpg'
    use_render = recipe.get('cover_from_movie', False)
    cover_source = movie if use_render else outdir/'picture_clean.mp4'
    require(movie.is_file(), 'Render the movie before building the review player')
    duration = reel_frame_count(recipe) / recipe['fps']
    cover_time = recipe.get('cover_time', min(1.1, duration/2))
    require(0 <= cover_time < duration, 'Cover time must be inside the movie')
    with TemporaryDirectory(prefix='.cover-', dir=outdir) as folder:
        frame = Path(folder)/'frame.jpg'
        command(['ffmpeg','-v','error','-ss',cover_time,'-i',cover_source,
                 '-map','0:v:0','-frames:v','1','-q:v','2','-y',frame])
        if use_render:
            frame.replace(cover)
        else:
            title = recipe.get('cover_title', {'headline':recipe.get('destination', 'TRAVEL').upper(),
                                             'kicker':'', 'y':recipe['height']//6, 'size':recipe['height']//9})
            overlay = title_png(title, 99, Path(folder), recipe['width'], recipe['height'])
            with Image.open(frame) as background, Image.open(overlay) as graphic:
                composite = Image.alpha_composite(background.convert('RGBA'), graphic.convert('RGBA')).convert('RGB')
            composite.save(frame, quality=95)
            frame.replace(cover)
    destination = recipe.get('destination', 'Travel')
    perspective = recipe.get('perspective', 'Editor')
    version = recipe['version']
    data = json.dumps({
        'destination':destination, 'version':version, 'perspective':perspective,
        'shots':[{key:shot[key] for key in ('id', 'start_frame', 'frames', 'note')} for shot in recipe['shots']],
        'duration':duration, 'fps':recipe['fps'],
        'recipe_sha256':hashlib.sha256(json.dumps(recipe, sort_keys=True).encode()).hexdigest(),
    }, ensure_ascii=False).replace('<','\\u003c')
    page='''<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>__TITLE__</title>
<style>*{box-sizing:border-box}body{margin:0;background:#151715;color:#f6f0e7;font:16px/1.5 system-ui,sans-serif}main{max-width:1120px;margin:auto;padding:36px 24px}h1{font-size:clamp(32px,5vw,54px);letter-spacing:-2px;line-height:1.05;margin:12px 0}p{color:#c3c7bc}small,.eyebrow{color:#b9c7a9;font-size:13px;letter-spacing:1px}.layout{display:grid;grid-template-columns:minmax(280px,400px) 1fr;gap:48px;margin-top:30px}video{display:block;width:100%;max-height:78vh;background:#080a08;border:1px solid #44493e}button,input,select,textarea{font:inherit;border:1px solid #575c50;border-radius:5px;padding:10px 12px;background:#252a23;color:#f6f0e7}button{cursor:pointer}button.primary{background:#d1e5b4;color:#16200e;font-weight:650}button:hover{border-color:#d1e5b4}label{display:block;margin:14px 0 5px}textarea{display:block;width:100%;min-height:95px}input{width:100px}.row{display:flex;gap:10px;align-items:center;flex-wrap:wrap}.note{border-top:1px solid #42483d;padding:12px 0}.note button{padding:3px 8px;font-size:13px}a{color:#d1e5b4}details{margin-top:24px}#shot{font-size:14px;color:#b9c7a9;min-height:44px}#status{color:#d1e5b4;min-height:26px}footer{margin:35px 0 0;border-top:1px solid #42483d;padding-top:18px;font-size:14px;color:#bfc6b8}@media(max-width:720px){.layout{grid-template-columns:1fr;gap:24px}video{max-width:390px;margin:auto;max-height:72vh}main{padding:24px 18px}}</style>
<main><div class="eyebrow">__EYEBROW__</div><h1>__HEADING__</h1><div class="layout"><section><video id="video" controls playsinline preload="metadata" poster="__COVER__" src="__VIDEO__"></video><p><a href="__VIDEO__" download>Download the reel</a> · <a href="__COVER__" download>Cover image</a></p><div id="shot"></div></section><section><h2 style="margin-top:0">Leave a note</h2><p style="margin-top:0">Pause on a moment and add a note. Your notes stay in this browser until you export them.</p><div class="row"><button id="capture">Use current time</button><label for="time">Seconds</label><input id="time" type="number" min="0" max="__DURATION__" step="0.1" value="0"></div><label for="kind">What should change?</label><select id="kind"><option value="change">Change this</option><option value="keep">Keep this</option><option value="private">Remove — private</option><option value="music">Music / pacing</option><option value="framing">Framing / colour</option></select><label for="text">Your note</label><textarea id="text" placeholder="Describe the change at this moment"></textarea><div class="row" style="margin-top:12px"><button class="primary" id="add">Save note</button><button id="export">Export feedback</button></div><div id="status" role="status"></div><div id="notes"></div><details><summary>Jump to a shot</summary><div id="shots"></div></details></section></div><footer>__DURATION__ seconds · __WIDTH__ × __HEIGHT__ · __FPS__ fps · __SHOT_COUNT__ shots<br>Music — __TRACK____CREDIT_LINK__<br>This page works offline. Export feedback and share the JSON file in this chat, or simply give your notes here.</footer></main>
<script>const edit=__DATA__;const video=document.getElementById('video');const $=id=>document.getElementById(id);const key='reel-feedback-'+edit.recipe_sha256;let notes=[];try{notes=JSON.parse(localStorage.getItem(key)||'[]')}catch(e){}const clock=t=>Math.floor(t/60)+':'+String(Math.floor(t%60)).padStart(2,'0');
function show(){ $('notes').replaceChildren();notes.forEach((n,i)=>{const row=document.createElement('div');row.className='note';const jump=document.createElement('button');jump.textContent=clock(n.at)+' · '+n.kind;jump.onclick=()=>{video.currentTime=n.at;video.pause()};const text=document.createElement('div');text.textContent=n.text;const del=document.createElement('button');del.textContent='Remove note';del.onclick=()=>{notes.splice(i,1);save()};row.append(jump,text,del);$('notes').append(row)})}
function save(){localStorage.setItem(key,JSON.stringify(notes));show()}
$('capture').onclick=()=>{video.pause();$('time').value=video.currentTime.toFixed(1);$('text').focus()};$('add').onclick=()=>{const text=$('text').value.trim();const at=Number($('time').value);if(!text||!Number.isFinite(at)||at<0||at>edit.duration){$('status').textContent=`Add a note and a time from 0 to ${edit.duration} seconds.`;return}notes.push({at,kind:$('kind').value,text,created:new Date().toISOString()});notes.sort((a,b)=>a.at-b.at);save();$('text').value='';$('status').textContent='Saved locally. Export when you’re done.'};
$('export').onclick=()=>{const data={version:edit.version,perspective:edit.perspective,recipe_sha256:edit.recipe_sha256,exported:new Date().toISOString(),notes};const url=URL.createObjectURL(new Blob([JSON.stringify(data,null,2)],{type:'application/json'}));const a=document.createElement('a');a.href=url;a.download=edit.destination+'_'+edit.perspective+'_'+edit.version+'_feedback.json';a.click();setTimeout(()=>URL.revokeObjectURL(url),1000)};
video.addEventListener('timeupdate',()=>{const s=edit.shots.find(s=>video.currentTime>=s.start_frame/edit.fps&&video.currentTime<(s.start_frame+s.frames)/edit.fps);$('shot').textContent=s?s.id+' / '+s.note:''});edit.shots.forEach(s=>{const b=document.createElement('button');b.textContent=clock(s.start_frame/edit.fps)+' · '+s.note;b.style.cssText='display:block;margin-top:6px;text-align:left;width:100%';b.onclick=()=>{video.currentTime=s.start_frame/edit.fps;video.pause()};$('shots').append(b)});show();</script></html>'''
    replacements = {
        'TITLE':html.escape(f'{destination} · Review the reel'),
        'EYEBROW':html.escape(f'{destination} / {version} / {perspective}'),
        'HEADING':html.escape(recipe.get('review_heading', recipe['name'])),
        'DURATION':format(duration, '.9g'), 'FPS':str(recipe['fps']),
        'WIDTH':str(recipe['width']), 'HEIGHT':str(recipe['height']),
        'SHOT_COUNT':str(len(recipe['shots'])), 'TRACK':html.escape(recipe['music']['track']),
        'DATA':data,
    }
    credits = outdir/'MUSIC_CREDITS.txt'
    for folder in dict.fromkeys((ROOT, outdir) if root_copy else (outdir,)):
        replacements.update(VIDEO=relative_link(movie, folder), COVER=relative_link(cover, folder),
                            CREDIT_LINK=f' · <a href="{relative_link(credits, folder)}">Credits</a>' if credits.is_file() else '')
        content = re.sub(r'__([A-Z_]+?)__', lambda match: replacements[match[1]], page)
        (folder/'Review Reel.html').write_text(content)
    print((ROOT if root_copy else outdir)/'Review Reel.html')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--recipe', default=current_recipe())
    parser.add_argument('--local-only', action='store_true', help='Write the player beside the movie')
    args = parser.parse_args()
    build(load(ROOT/args.recipe), root_copy=not args.local_only)
