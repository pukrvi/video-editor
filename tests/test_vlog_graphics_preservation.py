import unittest,tempfile,sys,os
from pathlib import Path
from PIL import Image
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from vlog_graphics import prepare_graphics,_safe_output
class Preservation(unittest.TestCase):
 def test_ancestor_symlink(self):
  with tempfile.TemporaryDirectory() as d:
   p=Path(d);(p/'real').mkdir();(p/'jump').symlink_to(p/'real',target_is_directory=True)
   with self.assertRaises(ValueError):_safe_output(p/'jump'/'nested'/'file.png')
 def test_cross_layer_hardlink(self):
  with tempfile.TemporaryDirectory() as d:
   p=Path(d);a=p/'a.png';b=p/'b.png';Image.new('RGBA',(100,60),'red').save(a);Image.new('RGBA',(100,60),'blue').save(b)
   def spec(x):return dict(asset=str(x),at=0,duration=2,x=20,y=20,width=150,text='',font_size=24,ink='#ffffff')
   r=dict(width=320,height=640,fps=30,duration=2,graphics=[spec(a),spec(b)])
   layers=prepare_graphics(r,p/'out');target=Path(layers[0]['path']);target.unlink();os.link(b,target);before=b.read_bytes()
   with self.assertRaises(ValueError):prepare_graphics(r,p/'out')
   self.assertEqual(before,b.read_bytes())
