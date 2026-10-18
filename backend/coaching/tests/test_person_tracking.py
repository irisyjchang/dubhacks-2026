import io
import json
import tempfile
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock,patch

import numpy as np
import requests

from spincoach.person_tracking import parse_track,box_at,request_track,select_tracked_pose,refine_box
from webapp import create_app


class PersonTrackingTests(unittest.TestCase):
    def test_coordinate_axes_and_actual_provider_variant(self):
        standard='<track asset_idx="0"><point_box t="0 seconds">(100,200) (500,800)</point_box><point_box t="0.5 seconds">(200,200) (600,800)</point_box></track>'
        actual='<collection mention="main_skater"><track t="0 seconds">(100,200) (500,800)</track><track t="0.5 seconds">(200,200) (600,800)</track></collection>'
        anchors=parse_track(standard,720,1280,1)
        self.assertEqual(anchors,parse_track(actual,720,1280,1))
        self.assertEqual(anchors[0]['bbox_xywh_px'],[72,256,288,768])

    def test_rejects_wrong_asset_reversed_boxes_and_ambiguous_identities(self):
        standard='<track asset_idx="0"><point_box t="0">(100,200) (500,800)</point_box><point_box t="0.5">(200,200) (600,800)</point_box></track>'
        for invalid in [standard.replace('asset_idx="0"','asset_idx="1"'),
                        standard.replace('(100,200) (500,800)','(600,200) (500,800)'),
                        standard.replace('t="0.5"','t="9"'),
                        standard.replace('t="0.5"','t="0"'),
                        '<collection mention="two people">'+standard+standard+'</collection>']:
            with self.assertRaises(ValueError):
                parse_track(invalid,720,1280,1)

    def test_interpolation_provenance_and_visibility_gaps(self):
        anchors=[{'time_s':t,'bbox_xywh_px':[100*t,0,100,200]} for t in [0,.5,2]]
        track={'anchors':anchors,'fps':30}
        self.assertEqual(box_at(track,.25)['bbox_xywh_px'],[25,0,100,200])
        self.assertEqual(box_at(track,.25)['source'],'interpolated')
        self.assertEqual(box_at(track,.5)['source'],'perceptron')
        self.assertIsNone(box_at(track,1))
        self.assertIsNone(box_at(track,-.1))
        self.assertIsNone(box_at(track,2.1))

    def test_api_box_selects_main_pose_even_if_background_pose_is_larger(self):
        def person(cx,cy,size):
            return [SimpleNamespace(x=cx+((i%3)-1)*size,y=cy+((i%4)-1)*size,
                                    visibility=.99,presence=.99) for i in range(33)]
        result=SimpleNamespace(pose_landmarks=[person(.2,.2,.15),person(.7,.5,.05)])
        observation={'bbox_xywh_px':[550,350,300,300]}
        selected=select_tracked_pose(result,None,observation,1000,1000)
        self.assertEqual(selected[1],1)
        self.assertIsNone(select_tracked_pose(result,None,{'bbox_xywh_px':[900,900,90,90]},1000,1000))

    def test_refinement_includes_extended_hand_but_ignores_uncertain_outlier(self):
        hand={'x_px':50,'y_px':150,'visibility':.99,'presence':.99}
        bad={'x_px':0,'y_px':0,'visibility':.1,'presence':.9}
        original=[100,100,100,200]
        refined=refine_box(original,[hand,bad],1000,1000)
        self.assertEqual(refined,[44,100,156,200])
        self.assertEqual(original,[100,100,100,200])

    def test_timeout_and_error_body_do_not_leak_credentials(self):
        with tempfile.TemporaryDirectory() as folder:
            video=Path(folder)/'input.mp4';video.write_bytes(b'video')
            output=Path(folder)/'boxes.json'
            cap=Mock();cap.get.side_effect=lambda p:{3:720,4:1280,5:30,7:100}[p]
            for response in [Mock(ok=False,status_code=401,text='private-key'),requests.Timeout('private-key')]:
                with patch('spincoach.person_tracking.cv2.VideoCapture',return_value=cap),patch('spincoach.person_tracking.requests.post') as post:
                    if isinstance(response,Exception):post.side_effect=response
                    else:post.return_value=response
                    result=request_track(video,'private-key',output)
                self.assertEqual(result['status'],'fallback')
                self.assertNotIn('private-key',output.read_text())
                self.assertEqual(result['anchors'],[])

    def test_invalid_markup_gets_one_format_retry_and_keeps_safe_diagnostics(self):
        good='<track mention="main skater"><point_box t="0">(100,200) (500,800)</point_box><point_box t="0.5">(200,200) (600,800)</point_box></track>'
        def response(text):
            return Mock(ok=True,json=lambda:{'choices':[{'finish_reason':'stop','message':{'content':text}}]})
        with tempfile.TemporaryDirectory() as folder:
            video=Path(folder)/'input.mp4';video.write_bytes(b'video')
            cap=Mock();cap.get.side_effect=lambda p:{3:720,4:1280,5:30,7:100}[p]
            with patch('spincoach.person_tracking.cv2.VideoCapture',return_value=cap),patch('spincoach.person_tracking.requests.post',side_effect=[response('invalid private-key'),response(good)]) as post:
                result=request_track(video,'private-key',Path(folder)/'boxes.json')
            self.assertEqual(result['status'],'completed')
            self.assertEqual(result['api_calls'],2)
            self.assertEqual(post.call_count,2)
            self.assertNotIn('warning',result)
            self.assertNotIn('private-key',(Path(folder)/'perceptron_response_1.txt').read_text())

    def test_server_key_is_opt_in_private_and_disabled_for_local_mode(self):
        calls=[]
        def runner(source,destination,key,update,**options):
            calls.append(options['perceptron_key'])
            raise ValueError('Service failed '+options['perceptron_key'])
        with tempfile.TemporaryDirectory() as folder:
            app=create_app(folder,api_key='nvidia-test',perceptron_key='person-secret',runner=runner)
            try:
                client=app.test_client()
                page=client.get('/').text
                self.assertNotIn('person-secret',page)
                for mode,enabled,expected in [('nvidia','on','person-secret'),('nvidia','',''),('local','on','')]:
                    r=client.post('/api/jobs',data={'video':(io.BytesIO(b'video'),'clip.mov'),
                        'mode':mode,'perceptron_track':enabled})
                    for _ in range(100):
                        job=client.get(r.json['status_url']).json
                        if job['status']=='failed':break
                        time.sleep(.01)
                    self.assertEqual(calls[-1],expected)
                    self.assertNotIn('person-secret',json.dumps(job))
            finally:
                app.extensions['spin_pool'].shutdown(wait=True)


if __name__=='__main__':
    unittest.main()
