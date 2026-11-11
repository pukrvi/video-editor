"""Run the example vlog through the public dispatcher on synthetic media."""
import hashlib
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parents[1]


def fixture(root):
    album = root/'album'; album.mkdir()
    out = root/"render's [preview], v01"
    assets = root/'assets'; assets.mkdir()
    ffmpeg = ['ffmpeg', '-v', 'error']
    subprocess.run(ffmpeg+['-f','lavfi','-i','testsrc2=s=360x640:r=30:d=2.2',
                           '-f','lavfi','-i','sine=frequency=440:sample_rate=48000:duration=2.2',
                           '-map','0:v:0','-map','1:a:0','-c:v','libx264','-c:a','aac','-n',str(album/'walk.mp4')],check=True)
    for path, frequency, duration in ((album/'narration.wav',620,2),(assets/'music.wav',997,6)):
        subprocess.run(ffmpeg+['-f','lavfi','-i',f'sine=frequency={frequency}:sample_rate=48000:duration={duration}',
                               '-map','0:a:0','-c:a','pcm_s24le','-n',str(path)],check=True)
    for name, color in (('view.jpg','#304e53'),('photo_a.jpg','#184fbc'),('photo_b.jpg','#dd7525')):
        Image.new('RGB',(360,480),color).save(album/name)
    mark=Image.new('RGBA',(80,60)); ImageDraw.Draw(mark).polygon([(5,5),(74,31),(20,56)],fill='#ff02a2')
    mark.save(assets/'mark.png')
    spec=(ROOT/'examples'/'vlog_recipe.json').read_text()
    spec=spec.replace('/path/to/album/Edit_Workspace/exports/v01',str(out))
    spec=spec.replace('/path/to/album',str(album)).replace('/path/to/',str(assets)+'/')
    recipe=root/'recipe.json'; recipe.write_text(spec)
    return recipe,out,[*album.iterdir(),*assets.iterdir()]


def dispatch(action, recipe, workflow='personal-vlog', check=True):
    return subprocess.run([sys.executable,str(ROOT/'video-editor'),workflow,action,'--recipe',str(recipe)],
                          cwd=ROOT,check=check,capture_output=True,text=True,timeout=120)


@unittest.skipUnless(shutil.which('ffmpeg') and Path('/System/Library/Fonts/Avenir Next.ttc').exists()
                     and Path('/System/Library/Fonts/Supplemental/Devanagari Sangam MN.ttc').exists(),
                     'Native FFmpeg and approved local fonts are required')
class VlogDispatcherEval(unittest.TestCase):
    def test_example_render_and_qa(self):
        with tempfile.TemporaryDirectory() as tmp:
            recipe,out,sources=fixture(Path(tmp))
            album=Path(tmp)/'album'
            if Path('/usr/bin/sips').is_file():
                heic=album/'view.heic'
                subprocess.run(['/usr/bin/sips','-s','format','heic',album/'view.jpg','--out',heic],
                               capture_output=True,check=True,timeout=30)
                recipe.write_text(recipe.read_text().replace('view.jpg','view.heic'))
                sources.append(heic)
            before={path:hashlib.sha256(path.read_bytes()).hexdigest() for path in sources}
            try:
                dispatch('render',recipe)
                dispatch('qa',recipe)
            except subprocess.CalledProcessError as exc:
                self.fail(exc.stdout+exc.stderr)
            self.assertEqual(before,{path:hashlib.sha256(path.read_bytes()).hexdigest() for path in sources})
            manifest=json.loads((out/'render_manifest.json').read_text())
            qa=json.loads((out/'qa_report.json').read_text())
            self.assertEqual(qa['movie_sha256'],manifest['sha256'])
            self.assertEqual(qa['technical']['frames'],150)
            self.assertEqual(qa['technical']['dimensions'],[1080,1920])
            self.assertEqual(qa['decode'],'pass')
            captions=json.loads((out/'caption_evidence.json').read_text())
            self.assertEqual(captions['preset'],'avenir_highlight')
            self.assertEqual(set(captions['measurement_faces']),{'Voice','Hindi'})
            self.assertTrue(any('AvenirNext-DemiBold' in line for line in captions['libass_font_selection']))
            self.assertTrue(any('DevanagariSangamMN-Bold' in line for line in captions['libass_font_selection']))
            music=json.loads((out/'MUSIC_POLICY.json').read_text())
            self.assertTrue(Path(music['processed_music_stem']).is_file())
            self.assertEqual([w['role'] for w in music['measured_speech_windows']],['native','voiceover'])
            self.assertTrue(all(-60<w['rms_dbfs']<-30 for w in music['measured_speech_windows']))
            layers=json.loads((out/'photo_layers/manifest.json').read_text())
            self.assertEqual(len(layers),3)
            self.assertEqual(layers[0]['attached_artwork_count'],1)
            self.assertEqual(layers[0]['swing_degrees'],3)
            self.assertNotIn('attached_artwork_count',layers[-1])

            request=out/'director_review_request.json'
            record=json.loads(request.read_text())
            record['request_id']='different-request-for-the-same-movie'
            request.write_text(json.dumps(record))
            stale=dispatch('qa',recipe,check=False)
            self.assertNotEqual(stale.returncode,0)
            self.assertIn('Director review request belongs',stale.stderr)

            original=Path(manifest['narration_mix'])
            original.write_bytes(original.read_bytes()+b'changed derivative')
            export=dispatch('export-finalcut',recipe,check=False)
            self.assertNotEqual(export.returncode,0)
            self.assertIn('timeline media changed',export.stderr)

    def test_commercial_landscape_render_and_qa(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp); recipe,out,sources=fixture(root)
            spec=json.loads((ROOT/'examples/commercial_recipe.json').read_text())
            personal=json.loads(recipe.read_text())
            wide=root/'album/wide.mp4'
            subprocess.run(['ffmpeg','-v','error','-f','lavfi','-i','testsrc2=s=640x360:r=30:d=2',
                            '-map','0:v:0','-c:v','libx264','-pix_fmt','yuv420p','-n',str(wide)],
                           check=True,timeout=30)
            spec.update(album=personal['album'],output_dir=str(out),blocks=personal['blocks'][:2])
            spec['blocks'][0]['pictures']=[{'file':'wide.mp4','duration':1.5}]
            spec['blocks'][0]['words']=[{'text':'M'*12,'start':.25+i*.3,'end':.45+i*.3} for i in range(4)]
            spec['blocks'][1]['pictures']=[{'file':'walk.mp4','duration':1.5}]
            spec['blocks'][1]['captions_top']=True
            recipe.write_text(json.dumps(spec))
            sources.append(wide)
            before={path:hashlib.sha256(path.read_bytes()).hexdigest() for path in sources}
            try:
                dispatch('render',recipe,'commercial-youtube')
                dispatch('qa',recipe,'commercial-youtube')
            except subprocess.CalledProcessError as exc:
                self.fail(exc.stdout+exc.stderr)
            self.assertEqual(before,{path:hashlib.sha256(path.read_bytes()).hexdigest() for path in sources})
            manifest=json.loads((out/'render_manifest.json').read_text())
            qa=json.loads((out/'qa_report.json').read_text())
            self.assertEqual(qa['request_id'],manifest['request_id'])
            self.assertEqual(qa['technical']['dimensions'],[1920,1080])
            self.assertEqual(qa['technical']['frames'],90)
            self.assertEqual(qa['technical']['transfer'],'bt709')
            with Image.open(next((out/'review_frames').glob('*.jpg'))) as thumb:
                self.assertEqual(thumb.size,(320,180))
            ass=(out/'captions.ass').read_text()
            self.assertIn('PlayResX: 1920\nPlayResY: 1080',ass)
            self.assertTrue(any(r'\pos(960,936)' in line and r'\N' in line for line in ass.splitlines()))
            self.assertIn(r'\pos(960,120)',ass)
            for picture,expected in zip(manifest['prepared_pictures'],(False,True)):
                pixels=subprocess.check_output(['ffmpeg','-v','error','-i',picture,'-frames:v','1',
                                                '-pix_fmt','rgb24','-f','rawvideo','-'],timeout=30)
                self.assertEqual(len(pixels),1920*1080*3)
                left=pixels[540*1920*3:540*1920*3+60]
                center=pixels[(540*1920+900)*3:(540*1920+920)*3]
                self.assertEqual(not any(left),expected,'Unexpected pillarbox at the left edge')
                self.assertTrue(any(center),'The picture center must stay visible')
