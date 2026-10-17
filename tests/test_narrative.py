import json
import tempfile
import unittest
from pathlib import Path

from spincoach.narrative import write_assessment,compact_evidence,position_features


class NarrativeTests(unittest.TestCase):
    def result(self):
        return {'source':'example.mov','duration_s':7,'tracking':{},'feedback':[],
                'lowered_segment':{'start_s':2.1,'end_s':5.8,'duration_s':3.7},'frames':[]}

    def test_local_report_has_paragraphs_and_honest_provenance(self):
        with tempfile.TemporaryDirectory() as name:
            result=write_assessment(self.result(),name)
            self.assertEqual(result['api_calls'],0)
            self.assertIsNone(result['model'])
            self.assertEqual(len(result['content'].split('\n\n')),4)
            self.assertTrue((Path(name)/'coaching_report.md').is_file())
            saved=json.loads((Path(name)/'coaching_assessment.json').read_text())
            self.assertEqual(saved['generator'],'local coaching narrative')

    def test_prompt_input_is_summary_not_full_pose_dump(self):
        result=self.result()
        result['frames']=[{'time_s':0,'left_knee_deg':90,'right_knee_deg':None,
                           'private_unused_blob':'do not include'}]
        evidence=compact_evidence(result)
        text=json.dumps(evidence)
        self.assertNotIn('private_unused_blob',text)
        self.assertEqual(evidence['time_windows'][0]['knees']['left']['accepted_samples'],1)
        self.assertEqual(len(evidence['time_windows']),7)
        self.assertEqual(evidence['time_windows'][-1]['time_s'],[6,7])

    def pose(self):
        joints=[{'x_px':0,'y_px':0,'visibility':1,'presence':1} for _ in range(33)]
        for idx,xy in {11:(0,0),12:(20,0),23:(0,40),24:(20,40),
                       13:(0,20),15:(20,20),14:(20,20),16:(40,20),
                       27:(0,80),29:(0,80),31:(10,80)}.items():
            joints[idx].update(x_px=xy[0],y_px=xy[1])
        return {'landmarks':joints}

    def test_arm_metrics_preserve_geometry_and_gate_obscured_wrist(self):
        frame=self.pose();out=position_features(frame)
        self.assertAlmostEqual(out['left_elbow_deg'],90)
        self.assertAlmostEqual(out['left_wrist_height_above_shoulder_torso'],-.5)
        frame['landmarks'][15]['visibility']=.1
        out=position_features(frame)
        self.assertNotIn('left_elbow_deg',out)
        self.assertIn('right_elbow_deg',out)

    def test_foot_direction_requires_reliable_toe_and_heel(self):
        frame=self.pose();out=position_features(frame)
        self.assertAlmostEqual(out['left_toe_dx_from_heel_torso'],.25)
        self.assertEqual(out['left_toe_dy_from_heel_torso'],0)
        frame['landmarks'][31]['presence']=.1
        self.assertNotIn('left_toe_dx_from_heel_torso',position_features(frame))

    def test_review_notes_from_another_video_are_not_sent(self):
        with tempfile.TemporaryDirectory() as name:
            folder=Path(name);clip=folder/'example.mov';clip.write_bytes(b'this clip')
            (folder/'visual_notes.json').write_text(json.dumps({'source_sha256':'wrong',
                'notes':['WRONG_SUBJECT_OBSERVATION']}))
            result=self.result();result['original_source']=str(clip)
            provenance=write_assessment(result,folder)
            self.assertIn('reviewer_notes_ignored',provenance)
            self.assertNotIn('WRONG_SUBJECT_OBSERVATION',(folder/'coaching_prompt.txt').read_text())


if __name__=='__main__':unittest.main()
