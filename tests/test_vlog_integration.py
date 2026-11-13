"""Run the example vlog through the public dispatcher on synthetic media."""
import hashlib
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
import xml.etree.ElementTree as ET

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


def dispatch(action, recipe, workflow='personal-vlog', check=True, extra=()):
    return subprocess.run([sys.executable,str(ROOT/'video-editor'),workflow,action,'--recipe',str(recipe),*extra],
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
            self.assertFalse(list(out.glob('*.fcpxml')))
            self.assertIn('Final Cut deferred',dispatch('export-finalcut',recipe,check=False).stderr)
            report=Path(tmp)/'synthetic_director_review.json'
            report.write_text(json.dumps({**record, 'independent_reviewer': True, 'score': 85,
                'scores': {'story':18, 'shot_selection':17, 'pacing':12, 'motion_design':12,
                           'transitions':9, 'composition_legibility':9, 'ending':8},
                'strengths':['Synthetic fixture'], 'evidence':['Synthetic fixture'],
                'limitations':['Fixture for export mechanics only'], 'feedback':[]}))
            spec=json.loads(recipe.read_text())
            spec['finalcut_review_report']=str(report)
            recipe.write_text(json.dumps(spec))
            self.assertIn('User confirmation',dispatch('export-finalcut',recipe,check=False).stderr)
            spec['finalcut_user_confirmation']={
                'confirmed':True, 'movie_sha256':manifest['sha256'], 'user_message':'Synthetic test approval'}
            recipe.write_text(json.dumps(spec))
            try:
                dispatch('export-finalcut',recipe)
            except subprocess.CalledProcessError as exc:
                self.fail(exc.stdout+exc.stderr)
            xml=out/'Morning_Walk_v01.fcpxml'
            doc=ET.parse(xml)
            clips=doc.findall('.//project/sequence/spine/asset-clip')
            self.assertEqual(len(clips),3)
            composition=clips[0].find('./video')
            self.assertEqual((composition.get('offset'),composition.get('start'),composition.get('duration')),
                             ('13/10s','13/10s','5/2s'))
            self.assertEqual([clip.get('role') for clip in clips[0].findall('./audio')],['dialogue','music'])
            exported=json.loads((out/'finalcut_export_checks.json').read_text())
            self.assertEqual(exported['status'],'statically_checked')
            self.assertEqual(exported['movie_sha256'],manifest['sha256'])
            self.assertEqual(exported['xml_sha256'],hashlib.sha256(xml.read_bytes()).hexdigest())
            self.assertEqual(set(exported['caption_sidecars']),{'captions.srt','captions.ass'})
            self.assertFalse(exported['editability']['native_captions'])
            receipt=out/'finalcut_app_verification.json'
            self.assertFalse(receipt.exists())
            evidence=Path(tmp)/'synthetic_app_observations.json'
            observations={k:exported[k] for k in ('movie_sha256','xml_sha256','project_name')}
            observations.update(app_version='Fixture',library='Fixture',observations='Synthetic receipt fixture',
                                checks=dict.fromkeys(('populated_project','timeline_geometry','picture_playback',
                                                      'connected_audio','audio_playback','connected_video'),True))
            evidence.write_text(json.dumps({**observations,'xml_sha256':'earlier export'}))
            self.assertIn('exact movie, XML and project',dispatch('record-finalcut-verification',recipe,check=False,
                          extra=('--evidence',str(evidence))).stderr)
            self.assertFalse(receipt.exists())
            evidence.write_text(json.dumps(observations))
            dispatch('record-finalcut-verification',recipe,extra=('--evidence',str(evidence)))
            self.assertEqual(json.loads(receipt.read_text())['status'],'app_verified')
            self.assertEqual(hashlib.sha256(Path(manifest['movie']).read_bytes()).hexdigest(),manifest['sha256'])

            sys.path.insert(0,str(ROOT/'scripts'))
            from check_finalcut import app_verification_current
            self.assertTrue(app_verification_current(spec))
            self.assertEqual(json.loads(receipt.read_text())['media_sha256'],exported['media_sha256'])
            linked=Path(next(iter(exported['media_sha256'])))
            saved_link=linked.read_bytes();linked.write_bytes(saved_link+b'changed')
            self.assertFalse(app_verification_current(spec));linked.write_bytes(saved_link)
            # Reject destination/input collisions before either the XML or recipe changes.
            checks_path=out/'finalcut_export_checks.json';checks_bytes=checks_path.read_bytes()
            xml_bytes=xml.read_bytes()
            checks_path.write_text(json.dumps(spec));recipe_bytes=checks_path.read_bytes()
            result=dispatch('export-finalcut',checks_path,check=False)
            self.assertNotEqual(result.returncode,0)
            self.assertEqual(checks_path.read_bytes(),recipe_bytes);self.assertEqual(xml.read_bytes(),xml_bytes)
            checks_path.unlink();checks_path.mkdir()
            result=dispatch('export-finalcut',recipe,check=False)
            self.assertNotEqual(result.returncode,0);self.assertEqual(xml.read_bytes(),xml_bytes)
            checks_path.rmdir();checks_path.write_bytes(checks_bytes)

            legacy={key:value for key,value in manifest.items() if key!='timeline_layers'}
            manifest_path=out/'render_manifest.json'
            manifest_path.write_text(json.dumps(legacy))
            dispatch('export-finalcut',recipe)
            self.assertFalse(app_verification_current(spec))
            self.assertEqual(json.loads(receipt.read_text())['status'],'superseded')
            legacy_export=json.loads((out/'finalcut_export_checks.json').read_text())
            self.assertEqual(legacy_export['baked_composition_overlays'],0)
            self.assertEqual(legacy_export['audio_roles'],['dialogue'])
            self.assertIn('Legacy reconstruction',legacy_export['editability']['overlays'])
            self.assertIn('exact movie, XML and project',dispatch('record-finalcut-verification',recipe,check=False,
                          extra=('--evidence',str(evidence))).stderr)
            manifest_path.write_text(json.dumps(manifest))

            record['request_id']='different-request-for-the-same-movie'
            request.write_text(json.dumps(record))
            self.assertIn('Director review request belongs',dispatch('export-finalcut',recipe,check=False).stderr)
            for key in ('finalcut_review_report','finalcut_user_confirmation'):
                spec.pop(key)
            recipe.write_text(json.dumps(spec))
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

    def test_editorial_plan_four_photos_and_natural_sound_through_dispatcher(self):
        import numpy as np
        with tempfile.TemporaryDirectory() as tmp:
            recipe,out,_=fixture(Path(tmp));r=json.loads(recipe.read_text())
            r['editorial_required']=True
            for i,b in enumerate(r['blocks']):
                b.update(selection_evidence='Synthetic alternatives reviewed',picture_cues=[])
                for p in b['pictures']:
                    p.update(moment=f'moment-{i}',subjects=['fixture'],purpose='Test sequence',end_reason='Fixture endpoint',repeat_reason='Synthetic fixture repeats a solid color')
            r['blocks'][2].update(music_silent=True,mute=False,audio_role='natural_sound')
            comp=r['photo_compositions'][0]
            comp['photos']=[dict(file=str(Path(tmp)/'album'/name),x=x,y=y,width=300,height=380,slide_px=0,rotation=0)
                            for name,x,y in [('photo_a.jpg',120,150),('photo_b.jpg',580,550),('photo_a.jpg',120,1000),('photo_b.jpg',580,1420)]]
            comp.pop('artwork',None)
            recipe.write_text(json.dumps(r));dispatch('render',recipe)
            self.assertEqual(json.loads((out/'editorial_audit.json').read_text())['status'],'plan_consistent')
            self.assertEqual(len(json.loads((out/'photo_layers/manifest.json').read_text())),4)
            def pcm(path):
                data=subprocess.check_output(['ffmpeg','-v','error','-i',str(path),'-map','0:a:0','-f','f32le','-'])
                return np.frombuffer(data,dtype='<f4').reshape(-1,2)
            bed=pcm(out/'music_processed.wav');voice=pcm(out/'narration.wav');mix=pcm(out/'narration_with_music.wav')
            sl=slice(round(3.3*48000),round(4.7*48000))
            self.assertEqual(float(np.max(np.abs(bed[sl]))),0)
            self.assertGreater(float(np.max(np.abs(voice[sl]))),.01)
            self.assertLess(float(np.max(np.abs(mix[sl]-voice[sl]))),1e-6)
            self.assertGreater(float(np.max(np.abs(bed[48000:96000]))),.0001)
            # A mismatched concrete cue fails on the normal render entrypoint.
            r['blocks'][0]['picture_cues']=[{'at':.5,'subject':'missing'}]
            recipe.write_text(json.dumps(r))
            result=dispatch('render',recipe,check=False)
            self.assertNotEqual(result.returncode,0);self.assertIn('Editorial plan incomplete',result.stderr)
