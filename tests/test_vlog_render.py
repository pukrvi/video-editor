"""Meaningful timing/layout regressions for the narration-first path."""
import sys,tempfile,unittest
from unittest.mock import patch
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from vlog_render import frames, phrases, subtitles, guard_paths, validate
class VlogEval(unittest.TestCase):
 def test_word_mapping_under_broll_and_nonzero_in(self):
  r={'blocks':[{'in':10,'out':12,'words':[{'text':'Snow','start':10.2,'end':10.7},{'text':'here.','start':11,'end':11.5}],'pictures':[{'file':'different.jpg','duration':2}]}]}
  with tempfile.TemporaryDirectory() as d:
   subtitles(r,Path(d));ass=(Path(d)/'captions.ass').read_text();srt=(Path(d)/'captions.srt').read_text()
   self.assertIn('0:00:00.20,0:00:00.70',ass);self.assertIn('00:00:00,200 --> 00:00:01,500',srt)
   # No highlight is held across the .7..1.0 speech gap.
   gap=[x for x in ass.splitlines() if '0:00:00.70,0:00:01.00' in x][0];self.assertNotIn('&H0078DDFF&',gap)
 def test_hindi_survives_and_ass_tags_are_escaped(self):
  r={'blocks':[{'in':0,'out':1,'words':[{'text':'बर्फ {x}','start':0,'end':.9}]}]}
  with tempfile.TemporaryDirectory() as d:
   subtitles(r,Path(d));s=(Path(d)/'captions.ass').read_text();self.assertIn('बर्फ (x)',s)
 def test_long_phrase_wrap_budget(self):
  w=[{'text':'mountains','start':i,'end':i+.5} for i in range(12)]
  for p in phrases(w):self.assertLessEqual(len(' '.join(x['text'] for x in p)),60)
 def test_duration_clock(self):
  self.assertEqual(frames(.1)+frames(.2),frames(.3))
 def test_multiblock_narration_mapping_independent_of_picture_cuts(self):
  import json
  r={'blocks':[{'in':10,'out':12.04,'words':[{'text':'first','start':10.1,'end':10.5}],
                'pictures':[{'file':'a.jpg','duration':1},{'file':'b.jpg','duration':1.0333333333}]},
               {'in':20,'out':21,'words':[{'text':'second','start':20.2,'end':20.6}],
                'pictures':[{'file':'c.jpg','duration':1}]}]}
  with tempfile.TemporaryDirectory() as d:
   subtitles(r,Path(d));words=json.loads((Path(d)/'timeline_words.json').read_text())
   self.assertAlmostEqual(words[0]['start'],.1)
   self.assertAlmostEqual(words[1]['start'],61/30+.2)
   self.assertAlmostEqual(words[1]['end'],61/30+.6)
 def test_guard_rejects_unsafe_output_and_source_traversal(self):
  with tempfile.TemporaryDirectory() as d:
   root=Path(d);album=root/'album';album.mkdir();outside=root/'elsewhere';outside.mkdir()
   original=album/'clip.mp4';original.write_bytes(b'untouched')
   r={'album':str(album),'output_dir':str(album),'project_slug':'trek','version':'v1',
      'blocks':[{'audio':'clip.mp4','pictures':[{'file':'clip.mp4'}]}]}
   with self.assertRaises(ValueError):guard_paths(r)
   r['output_dir']=str(outside);r['project_slug']='../clip'
   with self.assertRaises(ValueError):guard_paths(r)
   r['project_slug']='trek';r['blocks'][0]['pictures'][0]['file']='../elsewhere/clip.mp4'
   with self.assertRaises(ValueError):guard_paths(r)
   r['blocks'][0]['pictures'][0]['file']='clip.mp4'
   guard_paths(r)
   self.assertEqual(original.read_bytes(),b'untouched')
 def test_guard_resolves_symlink_to_album(self):
  with tempfile.TemporaryDirectory() as d:
   root=Path(d);album=root/'album';album.mkdir();link=root/'link';link.symlink_to(album,target_is_directory=True)
   r={'album':str(album),'output_dir':str(link),'project_slug':'trek','version':'v1',
      'blocks':[{'audio':'clip.mp4','pictures':[{'file':'clip.mp4'}]}]}
   with self.assertRaises(ValueError):guard_paths(r)
 def test_video_stream_not_container_duration(self):
  with tempfile.TemporaryDirectory() as d:
   root=Path(d);(root/'clip.mp4').write_bytes(b'fixture')
   metadata={'format':{'duration':'0.952018'},'streams':[{'codec_type':'audio','duration':'0.952018'},{'codec_type':'video','duration':'0.866667'}]}
   r={'fps':30,'width':1080,'height':1920,'blocks':[{'audio':'clip.mp4','in':0,'out':.9,'pictures':[{'file':'clip.mp4','in':0,'duration':.9}]}]}
   with patch('vlog_render.probe',return_value=metadata):
    with self.assertRaises(ValueError):validate(r,root)
    r['blocks'][0]['out']=.8;r['blocks'][0]['pictures'][0]['duration']=.8
    self.assertAlmostEqual(validate(r,root),.8)
if __name__=='__main__':unittest.main()

class ExistingOutputPreservationEval(unittest.TestCase):
 def test_existing_output_links_cannot_overwrite_original(self):
  import os
  from vlog_render import guard_paths
  with tempfile.TemporaryDirectory() as d:
   root=Path(d);album=root/'album';album.mkdir();original=album/'original.mp4';original.write_bytes(b'ORIGINAL')
   out=root/'output';out.mkdir()
   r={'album':str(album),'output_dir':str(out),'version':'v01','project_slug':'Safe','blocks':[{'audio':'original.mp4','pictures':[]}]}
   dest=out/'recipe.json';dest.symlink_to(original)
   with self.assertRaises(ValueError):guard_paths(r)
   dest.unlink();os.link(original,dest)
   with self.assertRaises(ValueError):guard_paths(r)
   self.assertEqual(original.read_bytes(),b'ORIGINAL')

class SentenceReadabilityEval(unittest.TestCase):
 def test_clauses_and_spoken_units_remain_readable(self):
  cases=['We are actually leading our group.','Our group has just started climbing.','let me show you guys around.','It is 8:00 a.m.','we are at 10900 feet.']
  for text in cases:
   ws=[{'text':t,'start':i*.22,'end':i*.22+.18} for i,t in enumerate(text.split())]
   self.assertEqual(len(list(phrases(ws))),1,text)
