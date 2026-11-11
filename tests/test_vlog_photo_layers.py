"""Photo panel mechanics and a short real overlay fixture, not creative approval."""
import copy
import hashlib
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from PIL import Image, ImageDraw
sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'scripts'))
from vlog_photo_layers import fit_image, prepare_photo_layers


class PhotoLayerEval(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.root = Path(self.tmp.name).resolve()
        self.photo = self.root/'photo.png'
        image = Image.new('RGBA', (120, 60), (220, 10, 30, 255))
        ImageDraw.Draw(image).rectangle((0, 0, 20, 59), fill=(10, 230, 20, 255))
        image.save(self.photo)
        self.r = {'width': 320, 'height': 568, 'fps': 30, 'duration': 2,
                  'photo_compositions': [{'at': 0, 'duration': 2, 'photos': [
                      {'file': str(self.photo), 'x': 40, 'y': 70, 'width': 240, 'height': 130,
                       'rotation': -3, 'border': 3, 'shadow': 2, 'slide_px': 8, 'z': 1},
                      {'file': str(self.photo), 'x': 50, 'y': 290, 'width': 220, 'height': 130,
                       'rotation': 3, 'border': 3, 'shadow': 2, 'delay': .2, 'slide_px': 8, 'z': 2}]}]}

    def tearDown(self): self.tmp.cleanup()

    def test_contain_preserves_edges_cover_uses_explicit_focus(self):
        image = Image.open(self.photo).convert('RGBA')
        whole = fit_image(image, (60,60), 'contain')
        self.assertEqual(whole.size, (60,30))
        self.assertGreater(whole.getpixel((0,15))[1], 200)
        left = fit_image(image,(60,60),'cover',[0,.5])
        right = fit_image(image,(60,60),'cover',[1,.5])
        self.assertGreater(left.getpixel((5,30))[1],200)
        self.assertLess(right.getpixel((5,30))[1],50)
        for focus in ([2,.5],[-.1,.5],[float('nan'),0],[0]):
            with self.assertRaises(ValueError): fit_image(image,(60,60),'cover',focus)

    def test_two_independent_panels_timing_alpha_and_source_preserved(self):
        before = hashlib.sha256(self.photo.read_bytes()).hexdigest()
        layers = prepare_photo_layers(self.r,self.root/'out')
        self.assertEqual(len(layers),2)
        self.assertEqual([g['at'] for g in layers],[0,.2])
        self.assertEqual([g['frames'] for g in layers],[60,54])
        for layer in layers:
            with Image.open(layer['path']) as image:
                self.assertEqual(image.mode,'RGBA')
                self.assertEqual(image.getpixel((0,0))[3],0)
                self.assertGreater(image.getchannel('A').getextrema()[1],250)
        self.assertEqual(hashlib.sha256(self.photo.read_bytes()).hexdigest(),before)

    def test_original_alpha_holes_remain_transparent(self):
        image = Image.new('RGBA',(80,80))
        draw = ImageDraw.Draw(image); draw.ellipse((0,0,79,79),fill='red')
        draw.rectangle((35,35,45,45),fill=(0,0,0,0)); image.save(self.photo)
        r = copy.deepcopy(self.r)
        for p in r['photo_compositions'][0]['photos']:
            p.update(width=80,height=80,rotation=0,border=0,radius=0,shadow=0,slide_px=0)
        layers = prepare_photo_layers(r,self.root/'alpha')
        with Image.open(layers[0]['path']) as panel:
            self.assertEqual(panel.getpixel((0,0))[3],0)
            self.assertEqual(panel.getpixel((40,40))[3],0)
            self.assertEqual(panel.getpixel((20,40))[3],255)

    def test_exif_orientation_applied_without_rewriting_original(self):
        source = self.root/'oriented.jpg'; image = Image.new('RGB',(80,40),'blue')
        exif = Image.Exif(); exif[274] = 6; image.save(source,exif=exif)
        before = source.read_bytes(); r = copy.deepcopy(self.r)
        for p in r['photo_compositions'][0]['photos']:
            p.update(file=str(source),width=100,height=100,rotation=0,border=0,radius=0,shadow=0,slide_px=0)
        layers=prepare_photo_layers(r,self.root/'exif')
        self.assertEqual((layers[0]['width'],layers[0]['height']),(50,100))
        self.assertEqual(source.read_bytes(),before)

    def test_three_photos_supplied_art_and_z_order(self):
        r = copy.deepcopy(self.r); comp = r['photo_compositions'][0]
        comp['photos'].append({**comp['photos'][0],'x':70,'y':210,'width':180,'height':80,'z':3})
        comp['background']={'kind':'blur','photo':0,'slide_px':0}
        comp['artwork']=[{'file':str(self.photo),'x':80,'y':460,'width':100,'height':50,'slide_px':0,'z':5}]
        layers=prepare_photo_layers(r,self.root/'stack')
        self.assertEqual([g['z'] for g in layers],[-100,1,2,3,5])
        self.assertEqual((layers[0]['width'],layers[0]['height']),(320,568))
        # Supplied transparent art is also supported as the background.
        comp['background']={'kind':'art','file':str(self.photo),'slide_px':0}
        self.assertEqual(len(prepare_photo_layers(r,self.root/'art')),5)

    def test_reject_bad_layout_and_original_alias_before_writing(self):
        mutations = [lambda c:c['photos'].pop(),
                     lambda c:c['photos'][0].update(x=0,rotation=20),
                     lambda c:c['photos'][1].update(delay=1.95),
                     lambda c:c['photos'][0].update(focus=[2,0]),
                     lambda c:c['photos'][0].update(jitter_px=3),
                     lambda c:c.update(duration=3)]
        for i,change in enumerate(mutations):
            r=copy.deepcopy(self.r); change(r['photo_compositions'][0]); out=self.root/f'bad{i}'
            with self.assertRaises(ValueError):prepare_photo_layers(r,out)
            self.assertFalse(out.exists())
        out=self.root/'linked'; out.symlink_to(self.root,target_is_directory=True)
        with self.assertRaises(ValueError):prepare_photo_layers(self.r,out)

    @unittest.skipUnless(shutil.which('ffmpeg') and shutil.which('ffprobe'),'Real FFmpeg overlay fixture')
    def test_short_real_graphics_integration(self):
        from vlog_graphics import apply_graphics
        out=self.root/'render'; out.mkdir()
        clean=out/'clean.mp4'
        subprocess.run(['ffmpeg','-v','error','-f','lavfi','-i','color=c=black:s=320x568:r=30:d=2',
                        '-map','0:v:0','-c:v','libx264','-pix_fmt','yuv420p','-n',str(clean)],check=True,capture_output=True,timeout=30)
        layers=prepare_photo_layers(self.r,out)
        movie=apply_graphics(clean,self.r,out,prepared_layers=layers)
        info=json.loads(subprocess.check_output(['ffprobe','-v','error','-show_streams','-of','json',str(movie)]))
        self.assertEqual(int(info['streams'][0]['nb_frames']),60)
        # A settled panel is visible while the known black base remains outside.
        png=subprocess.check_output(['ffmpeg','-v','error','-ss','1','-i',str(movie),'-frames:v','1','-f','image2pipe','-c:v','png','-'])
        import io
        frame=Image.open(io.BytesIO(png)).convert('RGB')
        self.assertGreater(frame.getpixel((160,130))[0],100)
        self.assertLess(max(frame.getpixel((0,0))),10)


if __name__=='__main__':unittest.main()
