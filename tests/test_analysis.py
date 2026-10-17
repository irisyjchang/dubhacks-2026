import unittest
import numpy as np
from spincoach.analysis import angle,measure,analyze,close_short_gaps,rolling_median


def pose(q=1):
 p=[{'x_px':100.,'y_px':100.,'visibility':q,'presence':q} for _ in range(33)]
 for i,xy in {11:(80,50),12:(120,50),23:(80,100),24:(120,100),25:(80,160),26:(120,160),27:(80,220),28:(120,220)}.items():
  p[i].update(x_px=xy[0],y_px=xy[1])
 return {'frame_id':0,'timestamp_ms':0,'landmarks':p}


class AnalysisTests(unittest.TestCase):
 def test_known_joint_geometry(self):
  self.assertAlmostEqual(angle([0,0],np.array([1,0]),[1,1]),90)
  self.assertAlmostEqual(angle([0,0],np.array([1,0]),[2,0]),180)
  self.assertIsNone(angle([0,0],np.array([0,0]),[1,1]))

 def test_low_confidence_knee_is_not_a_skater_error(self):
  p=pose();p['landmarks'][25]['visibility']=.1
  row=measure(p)
  self.assertIsNone(row['left_knee_deg'])
  self.assertEqual(row['right_knee_deg'],180)

 def test_posture_proxy_scale_translation_invariant(self):
  a=pose();b=pose()
  for j in b['landmarks']:
   j['x_px']=j['x_px']*2+50;j['y_px']=j['y_px']*2+100
  self.assertAlmostEqual(measure(a)['height_proxy'],measure(b)['height_proxy'])

 def test_lone_lifted_ankle_does_not_classify_low_posture(self):
  p=pose();p['landmarks'][27]['visibility']=.01;p['landmarks'][28]['y_px']=110
  self.assertIsNone(measure(p)['height_proxy'])

 def test_long_tracking_gaps_not_bridged(self):
  self.assertEqual(close_short_gaps([True,False,True],1),[True,True,True])
  self.assertEqual(close_short_gaps([True,False,False,False,True],1),[True,False,False,False,True])
  rows=[{'height_proxy':None} for _ in range(15)]
  self.assertTrue(all(x is None for x in rolling_median(rows,'height_proxy')))

 def test_no_pose_does_not_invent_success_or_grade(self):
  frames=[{'frame_id':i,'timestamp_ms':round(i*1000/30),'landmarks':[]} for i in range(60)]
  result=analyze({'source':'synthetic','fps':30,'frames':frames},{})
  self.assertIsNone(result['lowered_segment'])
  self.assertIsNone(result['overall_grade'])
  self.assertFalse(any(f['kind']=='positive' for f in result['feedback']))
  self.assertEqual(result['tracking']['poses'],0)

 def test_silhouette_and_flexion_must_agree(self):
  def sequence(bend):
   frames=[]
   for i in range(180):
    f=pose();f['frame_id']=i;f['timestamp_ms']=round(i*1000/30)
    low=20<=i<150
    f['silhouette_aspect']=1.4 if low else 3.0
    if low and bend:
     for knee,ankle,x in [(25,27,80),(26,28,120)]:
      f['landmarks'][knee].update(x_px=x+40,y_px=100)
      f['landmarks'][ankle].update(x_px=x+40,y_px=150)
    frames.append(f)
   return {'source':'synthetic','fps':30,'frames':frames}
  compact_but_straight=analyze(sequence(False),{})
  self.assertIsNone(compact_but_straight['lowered_segment'])
  combined=analyze(sequence(True),{})
  self.assertIsNotNone(combined['lowered_segment'])
  self.assertLess(abs(combined['lowered_segment']['start_s']-20/30),.3)
  self.assertLess(abs(combined['lowered_segment']['end_s']-150/30),.3)
  self.assertTrue(any(f['id']=='RISE_DETECTED' for f in combined['feedback']))

if __name__=='__main__':unittest.main()
