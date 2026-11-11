"""Music exclusion mechanics; synthetic fixtures establish PCM, not heard quality."""
import array
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from vlog_render import music_protection, mix_music_bed


def recipe():
    return {'music_bed': {}, 'blocks': [
        {'in': 0, 'out': 1, 'mute': True},
        {'in': 10, 'out': 12, 'words': [
            {'start': 10.1, 'end': 10.4}, {'start': 11.6, 'end': 11.9}]},
        {'in': 0, 'out': 1, 'mute': True},
        {'in': 20, 'out': 21},  # missing transcript must remain protected
        {'in': 0, 'out': 3, 'speech_free': True},
    ]}


class SpeechFreeMusicEval(unittest.TestCase):
    def test_full_blocks_and_word_gaps_protected_on_output_clock(self):
        result = music_protection(recipe())
        self.assertEqual(result['mix_policy'], 'speech_free')
        self.assertEqual(result['protected_intervals'], [[.8, 3.2], [3.8, 5.2]])
        self.assertEqual(result['duration'], 8)
        self.assertIn('not listened', result['notes'])

    def test_provenance_policy_url_is_not_a_mix_mode(self):
        r = recipe(); r['music_bed']['policy'] = 'https://ncs.io/usage-policy'
        self.assertEqual(music_protection(r)['mix_policy'], 'speech_free')
        self.assertEqual(r['music_bed']['policy'], 'https://ncs.io/usage-policy')

    def test_explicit_music_protected_mute_blocks_remain_quiet(self):
        r = recipe(); r['blocks'][2]['music_protected'] = True
        self.assertEqual(music_protection(r)['protected_intervals'], [[.8, 5.2]])

    def test_clamp_merge_and_frame_clock(self):
        r = {'blocks': [{'in': 10, 'out': 11.04}, {'in': 20, 'out': 21}]}
        result = music_protection(r)
        self.assertEqual(result['protected_intervals'], [[0, 61/30]])

    def test_invalid_policy_and_unsafe_parameters_rejected(self):
        for bed in ({'mix_policy': 'duck'}, {'speech_margin': 0},
                    {'speech_margin': float('nan')}, {'speech_fade': 0},
                    {'speech_fade': float('inf')}):
            r = recipe(); r['music_bed'] = bed
            with self.assertRaises(ValueError): music_protection(r)
        r = recipe(); r['blocks'][1]['speech_free'] = True
        with self.assertRaises(ValueError): music_protection(r)

    def test_legacy_duck_requires_explicit_name(self):
        r = recipe(); r['music_bed']['mix_policy'] = 'legacy_duck'
        self.assertEqual(music_protection(r)['mix_policy'], 'legacy_duck')

    @unittest.skipUnless(shutil.which('ffmpeg'), 'FFmpeg required for real PCM fixture')
    def test_real_pcm_music_zero_in_speech_and_audible_elsewhere(self):
        def run(args):
            return subprocess.run(['ffmpeg', '-v', 'error', *map(str, args)],
                                  check=True, capture_output=True, timeout=40).stdout
        def samples(path):
            result = array.array('i')
            result.frombytes(run(['-i', path, '-map', '0:a:0', '-f', 's32le', '-']))
            if sys.byteorder != 'little': result.byteswap()
            return result
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); voice = root/'voice.wav'; music = root/'bed.wav'
            mix = root/'mix.wav'
            # Deliberately continuous source tone: any source mute or nonlinear
            # mix processing in the protected intervals makes this test fail.
            for freq, path in ((440, voice), (997, music)):
                run(['-f', 'lavfi', '-i', f'sine=frequency={freq}:sample_rate=48000:duration=8',
                     '-map', '0:a:0', '-ac', '2', '-c:a', 'pcm_s24le', '-n', path])
            evidence = mix_music_bed(recipe(), voice, music, mix)
            original, mixed = samples(voice), samples(mix)
            self.assertEqual(len(original), len(mixed))
            delta = [b-a for a,b in zip(original, mixed)]
            for start, end in evidence['protected_intervals']:
                lo = round(start*48000)*2; hi = round(end*48000)*2
                self.assertEqual(max(map(abs, delta[lo:hi])), 0,
                                 'Nonzero music or altered source inside speech protection')
            for start, end in ((.4,.6), (3.45,3.55), (5.6,5.8), (6.2,6.4)):
                lo = round(start*48000)*2; hi = round(end*48000)*2
                rms = (sum((v/2**31)**2 for v in delta[lo:hi])/(hi-lo))**.5
                self.assertGreater(rms, .001, 'Music missing in a speech-free interval')
            # Includes the long unspoken gap between words inside the first block.
            self.assertEqual(max(map(abs, delta[round(1.5*48000)*2:round(2.5*48000)*2])), 0)


class TimedSfxEval(unittest.TestCase):
    def test_source_output_and_gain_bounds(self):
        from unittest.mock import patch
        from vlog_render import sfx_events
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp)/'effect.wav'; source.write_bytes(b'fixture')
            base = {'file': str(source), 'in': .1, 'duration': .2, 'at': .5, 'gain_db': -12}
            r = {'blocks': [{'in': 0, 'out': 1}], 'sfx': [base]}
            metadata = {'streams': [{'codec_type': 'audio', 'duration': '0.4'}]}
            with patch('vlog_render.probe', return_value=metadata):
                self.assertEqual(sfx_events(r)[0]['at'], .5)
                for changes in ({'in': .3}, {'duration': 0}, {'at': .9},
                                {'at': -.1}, {'gain_db': 1}, {'gain_db': float('nan')}):
                    r['sfx'] = [{**base, **changes}]
                    with self.assertRaises(ValueError): sfx_events(r)

    @unittest.skipUnless(shutil.which('ffmpeg'), 'FFmpeg required for timed SFX fixture')
    def test_effect_exact_window_gain_and_unchanged_voice_elsewhere(self):
        from vlog_render import mix_sfx
        def run(args):
            return subprocess.run(['ffmpeg', '-v', 'error', *map(str, args)],
                                  check=True, capture_output=True, timeout=40).stdout
        def samples(path):
            values = array.array('i')
            values.frombytes(run(['-i', path, '-map', '0:a:0', '-f', 's32le', '-']))
            if sys.byteorder != 'little': values.byteswap()
            return values
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); voice = root/'voice.wav'; effect = root/'effect.wav'
            mixed = root/'mixed.wav'
            for freq, path in ((440, voice), (997, effect)):
                run(['-f', 'lavfi', '-i', f'sine=frequency={freq}:sample_rate=48000:duration=1',
                     '-map', '0:a:0', '-ac', '2', '-c:a', 'pcm_s24le', '-n', path])
            r = {'blocks': [{'in': 0, 'out': 1}], 'sfx': [
                {'file': str(effect), 'in': .1, 'duration': .2, 'at': .5, 'gain_db': -6}]}
            report = mix_sfx(r, voice, mixed)
            a,b,e = samples(voice),samples(mixed),samples(effect)
            self.assertEqual(len(a),len(b))
            start,end = 24000*2,33600*2
            delta = [y-x for x,y in zip(a,b)]
            self.assertEqual(max(map(abs,delta[:start]+delta[end:])),0)
            self.assertGreater(max(map(abs,delta[start:end])),1000000)
            expected = e[4800*2:14400*2]
            gain = 10**(-6/20)
            self.assertLess(max(abs(v-x*gain) for v,x in zip(delta[start:end],expected)),512)
            self.assertIn('listening', report['notes'])


if __name__ == '__main__': unittest.main()
