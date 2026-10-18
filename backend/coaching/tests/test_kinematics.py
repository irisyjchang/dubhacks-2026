import copy
import unittest

from spincoach.kinematics import build_kinematics,format_response,response_problems,coaching_focus
from spincoach.narrative import position_features


class KinematicsTests(unittest.TestCase):
    def frame(self, index=0):
        joints=[{'x_px':0.,'y_px':0.,'visibility':1.,'presence':1.} for _ in range(33)]
        points={11:(100,100),12:(140,100),13:(80,130),14:(160,130),
                15:(60,160),16:(180,160),23:(100,180),24:(140,180),
                25:(100,230),26:(140,230),27:(150,230),28:(190,230),
                29:(145,230),30:(185,230),31:(170,230),32:(210,230)}
        for i,(x,y) in points.items():
            joints[i].update(x_px=x,y_px=y)
        return {'timestamp_ms':round(index*1000/30),'landmarks':joints}

    def calculate(self, frames):
        return build_kinematics({'frames':frames}, {'duration_s':len(frames)/30,
            'frames':[{'phase':'lowered posture'} for _ in frames]})

    def test_geometry_and_confidence_gate_only_the_required_joints(self):
        frame=self.frame()
        features=position_features(frame)
        self.assertAlmostEqual(features['left_knee_deg'],90)
        self.assertAlmostEqual(features['left_elbow_deg'],180)
        self.assertAlmostEqual(features['torso_lean_from_screen_vertical_deg'],0)
        frame['landmarks'][23]['visibility']=.1
        features=position_features(frame)
        self.assertIn('left_elbow_deg',features)
        self.assertNotIn('left_knee_deg',features)
        self.assertNotIn('torso_lean_from_screen_vertical_deg',features)
        frame['landmarks'][13]['presence']=float('nan')
        self.assertNotIn('left_elbow_deg',position_features(frame))

    def test_projected_angles_are_translation_and_scale_invariant(self):
        frame=self.frame(); changed=copy.deepcopy(frame)
        for j in changed['landmarks']:
            j['x_px']=j['x_px']*2+33
            j['y_px']=j['y_px']*2+19
        self.assertEqual(position_features(frame),position_features(changed))

    def test_ranges_coverage_and_missing_data_not_reported_as_fault(self):
        frames=[self.frame(i) for i in range(45)]
        for frame in frames[:22]:
            frame['landmarks'][13]['visibility']=.1
        output=self.calculate(frames)
        first=output['windows'][0]
        knee=first['metrics']['left_knee_deg']
        self.assertEqual((knee['median'],knee['p25'],knee['p75']),(90,90,90))
        self.assertEqual(knee['coverage_pct'],100)
        elbow=first['metrics']['left_elbow_deg']
        self.assertEqual(elbow['accepted_frames'],8)
        self.assertFalse(elbow['usable_for_feedback'])
        self.assertNotIn('left_elbow_deg',[c['metric'] for c in first['cards']])
        self.assertEqual(output['windows'][-1]['time_s'],[1,1.5])
        self.assertEqual(output['windows'][-1]['metrics']['left_knee_deg']['total_frames'],15)

    def test_similar_view_comparisons_do_not_cross_detected_phase_change(self):
        frames=[self.frame(i) for i in range(60)]
        result={'duration_s':2,'frames':[{'phase':'lowered posture'} for _ in frames]}
        data={'frames':frames}
        same=build_kinematics(data,result)['windows'][1]['metrics']['left_knee_deg']['similar_view_comparison']
        self.assertIsNotNone(same)
        self.assertEqual(same['median_absolute_delta'],0)
        # A short final interval after a phase change cannot borrow the prior hold.
        result['frames']=[{'phase':'lowered posture' if i<30 else 'rise'} for i in range(60)]
        later=build_kinematics(data,result)['windows'][1]['metrics']['left_knee_deg']['similar_view_comparison']
        self.assertIsNone(later)

    def test_numeric_substitution_uses_real_values_and_retains_uncertainty(self):
        window=self.calculate([self.frame(i) for i in range(30)])['windows'][0]
        raw=('Observation: Your {M1} accompanies {M2}.\n'
             'Advice: With {M2}, no need to chase extra elbow extension; check your chosen hold.\n'
             'Cue: Carry a soft tray.\nCaption: Check the hold | Carry a soft tray')
        self.assertEqual(response_problems(raw,window),[])
        rendered=format_response(raw,window)
        self.assertIn('left knee median 90 deg',rendered)
        self.assertIn('left elbow median 180 deg',rendered)
        self.assertIn('30/30 accepted frames',rendered)
        self.assertNotIn('{M1}',rendered)
        self.assertTrue(response_problems(raw+' Target 120 degrees.',window))
        self.assertTrue(response_problems(raw.replace('{M1}','{M9}'),window))
        self.assertTrue(response_problems(raw.replace('soft tray','locked arms'),window))
        self.assertEqual(response_problems(raw.replace('soft tray','reach without locking the joint'),window),[])
        direct=('Observation: Your left knee median is 90 deg and your left elbow median is 180 deg.\n'
                'Advice: With a left elbow median of 180 deg, extra extension is not indicated.\n'
                'Cue: Carry a tray.\nCaption: Check your chosen shape | Carry a tray')
        self.assertEqual(response_problems(direct,window),[])
        self.assertTrue(response_problems(direct.replace('180 deg','120 deg'),window))
        self.assertIn('extra straightening',coaching_focus(window)['instruction'])


if __name__=='__main__':
    unittest.main()
