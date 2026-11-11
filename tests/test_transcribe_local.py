import array, importlib.util, json, os, shutil, tempfile, unittest, wave, sys, types
from pathlib import Path
from unittest.mock import patch

MODULE = str(Path(__file__).resolve().parents[1]/'scripts/transcribe_local.py')
sys.path.insert(0,str(Path(MODULE).parent))
spec = importlib.util.spec_from_file_location('transcribe_local', MODULE)
m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)

class Evaluation(unittest.TestCase):
    def segment(self, text, start, end, probability=0.8):
        return {'text': text, 'offsets': {'from': start, 'to': end}, 'tokens': [{'text': text, 'p': probability}]}
    def test_silence_and_wind_energy(self):
        with tempfile.TemporaryDirectory() as td:
            p=Path(td)/'a.wav'
            def save(v):
                with wave.open(str(p),'wb') as f:
                    f.setparams((1,2,16000,0,'NONE','not compressed')); f.writeframes(array.array('h', v).tobytes())
            save([0]*1000); self.assertTrue(m.effectively_silent(p))
            save([0]*999+[10]); self.assertFalse(m.effectively_silent(p))
    def test_repeat_low_confidence_and_time_flags(self):
        s=[self.segment(x,i*1000,(i+1)*1000,.2) for i,x in enumerate(['Thank','you','Thank','you','Thank','you'])]
        flags=m.flags_for(s,3)
        self.assertIn('repeated_phrase_possible_hallucination', flags)
        self.assertIn('low_token_confidence', flags)
        self.assertIn('timestamp_beyond_source', flags)
        self.assertIn('imprecise_word_timestamps', m.flags_for([self.segment('x',2000,1000)],5))
    def test_nonmonotonic_timestamps_are_flagged(self):
        segments=[self.segment('a',2000,2500),self.segment('b',1000,1500)]
        self.assertIn('nonmonotonic_timestamps',m.flags_for(segments,3))
    def test_common_stock_phrase_flag(self):
        self.assertIn('stock_phrase_possible_hallucination', m.flags_for([self.segment('Thank you for watching!',0,2000)],3))
    def test_hindi_preserved_in_utf8(self):
        data={'segments':[self.segment('नमस्ते दुनिया',0,1000)]}
        with tempfile.TemporaryDirectory() as td:
            p=Path(td)/'out.json'; m.atomic(p,data)
            self.assertEqual(json.loads(p.read_text())['segments'][0]['text'], 'नमस्ते दुनिया')
    def test_fingerprint_changes_with_source(self):
        with tempfile.TemporaryDirectory() as td:
            p=Path(td)/'x'; p.write_bytes(b'first'); a=m.fingerprint(p)
            p.write_bytes(b'second'); self.assertNotEqual(a,m.fingerprint(p))
    def test_actual_cache_invalidates_on_source_change(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td); lib=root/'album'; lib.mkdir(); work=root/'work'; model=root/'model'; model.write_bytes(b'm')
            source=lib/'source.mp4'; source.write_bytes(b'one')
            def fake_run(cmd):
                self.assertEqual(cmd[0], 'ffprobe')
                return types.SimpleNamespace(stdout=json.dumps({'format': {'duration': '3'}, 'streams': []}))
            argv=['transcribe', '--library',str(lib),'--workspace',str(work),'--model',str(model)]
            with patch.object(sys,'argv',argv), patch.object(m,'run',fake_run):
                m.main(); first=json.loads((work/'transcripts/progress.json').read_text())
                m.main(); second=json.loads((work/'transcripts/progress.json').read_text())
                source.write_bytes(b'two'); m.main(); third=json.loads((work/'transcripts/progress.json').read_text())
            self.assertEqual((first['completed'], second['cached'], third['completed']), (1,1,1))
    def test_chunk_detection_offsets_and_normalized_words(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td); lib=root/'album'; lib.mkdir(); work=root/'work'; model=root/'model'; model.write_bytes(b'm')
            (lib/'clip.mp4').write_bytes(b'video')
            def fake_run(cmd):
                if cmd[0]=='ffprobe':
                    return types.SimpleNamespace(stdout=json.dumps({'format':{'duration':'2'},'streams':[{'codec_type':'audio'}]}))
                if cmd[0]=='ffmpeg':
                    p=Path(cmd[-1]); duration=1.5 if '-ss' in cmd else 2
                    with wave.open(str(p),'wb') as f:
                        f.setparams((1,2,16000,0,'NONE','not compressed')); f.writeframes(array.array('h',[100]*int(duration*16000)).tobytes())
                else:
                    p=Path(cmd[cmd.index('-of')+1]+'.json')
                    end = 2000 if 'chunk-1.wav' in cmd[cmd.index('-f')+1] else 500
                    p.write_text(json.dumps({'result':{'language':'hi'},'transcription':[self.segment('नमस्ते',0,end)]},ensure_ascii=False))
                return types.SimpleNamespace(stdout='')
            argv=['transcribe','--library',str(lib),'--workspace',str(work),'--model',str(model),'--whisper','fake-whisper','--chunk-seconds','1.5']
            with patch.object(sys,'argv',argv), patch.object(m,'run',fake_run): m.main()
            record=next(json.loads(p.read_text()) for p in (work/'transcripts').glob('clip-*.json'))
            self.assertEqual([c['detected_language'] for c in record['language_chunks']],['hi','hi'])
            self.assertEqual([w['start_seconds'] for w in record['words']],[0,1.5])
            self.assertIn('language_and_code_switch_require_listening',record['review_flags'])
            self.assertIn('timestamp_beyond_chunk',record['review_flags'])
    def test_dtw_grouping_boundaries_and_special_tokens(self):
        segments=[{'tokens':[{'text':'[_BEG_]','t_dtw':-1},{'text':' So','t_dtw':100},
                 {'text':',','t_dtw':110},{'text':' दुनिया','t_dtw':140},
                 {'text':' earlier','t_dtw':130},{'text':' late','t_dtw':900}]}]
        words,flags=m.normalize_dtw(segments,3)
        self.assertEqual([w['text'] for w in words],['So,','दुनिया'])
        self.assertEqual([w['start_seconds'] for w in words],[1,1.4])
        self.assertTrue(all(0<=w['start_seconds']<=w['end_seconds']<=3 for w in words))
        self.assertIn('dtw_nonmonotonic',flags); self.assertIn('dtw_outside_source',flags)
        self.assertIn('dtw_word_ends_are_estimates_listen_to_source',flags)
    def test_dtw_missing_timestamps_are_never_invented(self):
        words,flags=m.normalize_dtw([{'tokens':[{'text':' word','t_dtw':-1}]}],3)
        self.assertEqual(words,[]); self.assertIn('dtw_no_valid_tokens',flags)
    def test_missing_language_is_not_invented(self):
        raw={'result':{}}
        self.assertIsNone(raw.get('result',{}).get('language'))
    @unittest.skipUnless(shutil.which('ffmpeg') and shutil.which('ffprobe'), 'Local FFmpeg tools required')
    def test_audio_only_source_and_two_ranges_keep_distinct_cached_clocks(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td); lib=root/'album'; lib.mkdir(); work=root/'work'
            model=root/'model'; model.write_bytes(b'fixture')
            source=lib/'narration.wav'
            with wave.open(str(source),'wb') as writer:
                writer.setparams((1,2,16000,0,'NONE','not compressed'))
                writer.writeframes(array.array('h',[100]*16000).tobytes())
            original=source.read_bytes()
            run_local=m.run
            frame_counts=[]
            def run(cmd):
                if cmd[0] != 'fake-whisper':
                    return run_local(cmd)
                with wave.open(cmd[cmd.index('-f')+1],'rb') as clip:
                    frame_counts.append(clip.getnframes())
                output=Path(cmd[cmd.index('-of')+1]+'.json')
                output.write_text(json.dumps({'result':{'language':'hi'},
                    'transcription':[self.segment('नमस्ते',100,180)]},ensure_ascii=False))
                return types.SimpleNamespace(stdout='')
            argv=['transcribe','--library',str(lib),'--workspace',str(work),'--model',str(model),
                  '--whisper','fake-whisper','--source',source.name,'--window',source.name,'.1','.35',
                  '--window',source.name,'.6','.95']
            with patch.object(sys,'argv',argv), patch.object(m,'run',run):
                self.assertFalse(m.main())
                self.assertFalse(m.main())
            self.assertEqual(source.read_bytes(),original)
            self.assertCountEqual(frame_counts,[16000,4000,5600])
            records=[json.loads(p.read_text()) for p in (work/'transcripts').glob('narration-*.json')]
            self.assertEqual(len(records),3)
            windows={r['source_window']['in']:r for r in records if 'source_window' in r}
            self.assertEqual(set(windows),{.1,.6})
            for r in windows.values():
                self.assertEqual(r['timestamp_basis'],'window_relative')
                self.assertEqual(r['words'][0]['start_seconds'],.1)
                self.assertEqual(r['source']['sha256'],m.fingerprint(source))
            self.assertEqual(json.loads((work/'transcripts/progress.json').read_text())['cached'],3)

if __name__=='__main__':unittest.main(verbosity=2)
