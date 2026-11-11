import unittest,tempfile,json,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from index_vlog import link_transcripts
class SearchLinkEval(unittest.TestCase):
 def test_stale_transcript_is_not_linked(self):
  with tempfile.TemporaryDirectory() as d:
   c=Path(d)/'catalog';t=Path(d)/'transcripts';c.mkdir();t.mkdir()
   (c/'media.json').write_text(json.dumps({'assets':[{'id':'one','filename':'clip.mp4','sha256':'new'}]}))
   (t/'stale.json').write_text(json.dumps({'source':{'relative_path':'clip.mp4','sha256':'old'},'segments':[{'text':'wrong old words'}]}))
   (t/'current.json').write_text(json.dumps({'source':{'relative_path':'clip.mp4','sha256':'new'},'segments':[{'text':'correct linked words'}]}))
   link_transcripts(c,t);r=json.loads((c/'transcripts.json').read_text())['assets']['one'];self.assertEqual(len(r),1);self.assertIn('correct',r[0]['text']);self.assertFalse(r[0]['verified_by_listening'])
if __name__=='__main__':unittest.main()
