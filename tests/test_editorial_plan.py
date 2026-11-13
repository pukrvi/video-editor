import copy
import sys
import unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'scripts'))
from editorial_plan import audit, require_plan


def recipe():
    return {'fps':30, 'editorial_required':True, 'blocks':[{
        'in':0,'out':4, 'selection_evidence':'Compared wide and close view; close view shows the action.',
        'picture_cues':[{'at':2,'subject':'stream'}],
        'pictures':[
            {'file':'walk.mp4','in':0,'duration':2,'moment':'walk','subjects':['walking'],'purpose':'Establish approach','end_reason':'Arrives at water'},
            {'file':'stream.mp4','in':0,'duration':2,'moment':'water','subjects':['stream'],'purpose':'Show the spoken subject','end_reason':'Complete sip'}]}]}


class EditorialPlanTest(unittest.TestCase):
    def test_cue_at_cut_uses_new_picture_and_rejects_mismatch(self):
        r=recipe(); self.assertEqual(require_plan(r)['status'],'plan_consistent')
        r['blocks'][0]['picture_cues'][0]['at']=1.9
        self.assertIn('cue_mismatch',[x['code'] for x in audit(r)['findings']])
        with self.assertRaises(ValueError): require_plan(r)

    def test_same_source_adjacent_nonoverlapping_windows_are_not_repeats(self):
        r=recipe(); a,b=r['blocks'][0]['pictures'];b.update(file=a['file'],moment=a['moment'],**{'in':2})
        self.assertFalse(audit(r)['findings'])
        b['in']=1
        self.assertIn('repeated_source',[x['code'] for x in audit(r)['findings']])
        b['repeat_reason']='Explicitly requested replay of the stumble';self.assertFalse(audit(r)['findings'])

    def test_long_native_dialogue_preserved_broll_needs_reason(self):
        r=recipe(); r['blocks'][0]['pictures'][1]['duration']=8
        self.assertIn('long_hold',[x['code'] for x in audit(r)['findings']])
        r['blocks'][0]['audio_role']='native';self.assertFalse(audit(r)['findings'])

    def test_missing_decisions_and_invalid_cues_do_not_pass(self):
        r=recipe(); r['blocks'][0]['pictures'][0].pop('end_reason')
        with self.assertRaises(ValueError): require_plan(r)
        for at in (float('nan'),True,-1,4):
            r=recipe();r['blocks'][0]['picture_cues'][0]['at']=at
            self.assertIn('invalid_cue',[x['code'] for x in audit(r)['findings']])
        r=recipe();r['blocks'][0]['pictures'][1]['subjects']=None
        with self.assertRaises(ValueError):require_plan(r)

    def test_legacy_recipes_are_explicitly_unverified(self):
        r={'fps':30,'blocks':[{'in':0,'out':2,'pictures':[{'file':'one.jpg','duration':2}]}]}
        self.assertEqual(require_plan(r)['status'],'legacy_unverified')

    def test_fractional_cues_stay_on_the_containing_frame(self):
        r=recipe();r['blocks'][0]['picture_cues']=[{'at':1.99,'subject':'walking'},{'at':3.99,'subject':'stream'}]
        self.assertFalse(require_plan(r)['findings'])

    def test_legacy_numeric_strings_and_composed_subjects(self):
        r=recipe();r['blocks'][0]['pictures'][0].update(speed='1.0',**{'in':'0'})
        self.assertFalse(require_plan(r)['findings'])
        r['photo_compositions']=[{'at':2,'duration':2}]
        with self.assertRaises(ValueError):require_plan(r)
        r['photo_compositions'][0]['subjects']=['group']
        with self.assertRaises(ValueError):require_plan(r)
        r['blocks'][0]['picture_cues'][0]['subject']='group'
        self.assertFalse(require_plan(r)['findings'])
