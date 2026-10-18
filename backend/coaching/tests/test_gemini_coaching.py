import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock,patch

import requests

from spincoach.gemini_judge import generate_gemini_report,GeminiFailure
from spincoach.coaching import generate_coaching_report
from spincoach.errors import ProcessingFailure
import test_visual_judge as visual_fixtures


class GeminiCoachingTests(unittest.TestCase):
    def test_native_video_recovers_503_and_uses_gemini_for_positions_and_coaching(self):
        result,media,obj=visual_fixtures.VisualJudgeTests().fixture();sent=[]
        def inputs(phase,media,folder):
            available=[f for f in media['frames'] if f['phase_id']==phase['id']]
            return available,'position:'+phase['id'],[{'image_url':{'url':'data:image/jpeg;base64,aW1hZ2U='}}]
        def post(url,**kwargs):
            sent.append(kwargs['json'])
            self.assertIn('gemini-3.5-flash:generateContent',url)
            self.assertEqual(kwargs['headers'],{'x-goog-api-key':'gemini-secret'})
            if len(sent)==1:
                return Mock(ok=False,status_code=503)
            payload=kwargs['json'];prompt=payload['contents'][0]['parts'][-1]['text']
            if prompt.startswith('position:'):
                phase=prompt.split(':')[1]
                body={'positions':[{'phase_id':phase,'frame_ids':[f['id'] for f in media['frames'] if f['phase_id']==phase],
                    'free_leg_shape':'extended_front','arm_shape':'reaching_forward','body_height':'mixed',
                    'sit_depth':'unclear','description':'The free leg extends forward with forward-reaching arms.'}]}
            else:
                body=obj
            return Mock(ok=True,status_code=200,json=lambda:{'modelVersion':'gemini-3.5-flash-test',
                'candidates':[{'finishReason':'STOP','content':{'parts':[{'text':json.dumps(body)}]}}]})
        with tempfile.TemporaryDirectory() as folder:
            p=Path(folder);(p/'landmarks.json').write_text('{}')
            (p/media['video']).write_bytes(b'actual-video-data');(p/media['contact_sheet']).write_bytes(b'image')
            with patch('spincoach.gemini_judge.prepare_media',return_value=media), \
                 patch('spincoach.gemini_judge.position_request_parts',side_effect=inputs), \
                 patch('spincoach.gemini_judge.requests.post',side_effect=post), \
                 patch('spincoach.gemini_judge.time.sleep') as sleep:
                report=generate_gemini_report(result,folder,'gemini-secret')
            self.assertEqual(report['api_calls'],5)
            self.assertEqual(sleep.call_count,1)
            self.assertEqual(report['provider'],'Gemini')
            self.assertEqual(report['nvidia_api_calls'],0)
            self.assertEqual(report['model_returned'],'gemini-3.5-flash-test')
            self.assertEqual(report['model'],report['model_returned'])
            self.assertEqual(result['element_analysis']['visual_model'],report['model_returned'])
            self.assertEqual(result['element_analysis']['visual_provider'],'Gemini')
            self.assertIn('Gemini',report['summary']['source'])
            config=sent[-1]['generationConfig']
            self.assertEqual(config['thinkingConfig'],{'thinkingLevel':'low'})
            self.assertEqual(config['responseMimeType'],'application/json')
            self.assertEqual(sent[-1]['contents'][0]['parts'][0]['inlineData']['mimeType'],'video/mp4')
            self.assertNotIn('gemini-secret',(p/'gemini_attempts.json').read_text())

    def test_repeated_503_is_bounded_and_auth_errors_are_not_retried(self):
        result,media,obj=visual_fixtures.VisualJudgeTests().fixture()
        for status,expected in [(503,3),(403,1),(429,1)]:
            with tempfile.TemporaryDirectory() as folder:
                (Path(folder)/'landmarks.json').write_text('{}')
                response=Mock(ok=False,status_code=status,json=lambda:{'error':{'message':'Denied'}})
                with patch('spincoach.gemini_judge.prepare_media',return_value=media), \
                     patch('spincoach.gemini_judge.position_request_parts',return_value=([], 'prompt',[{'image_url':{'url':'data:image/jpeg;base64,aW1hZ2U='}}])), \
                     patch('spincoach.gemini_judge.time.sleep'), \
                     patch('spincoach.gemini_judge.requests.post',return_value=response) as post:
                    with self.assertRaises(GeminiFailure) as caught:
                        generate_gemini_report(result,folder,'gemini-secret')
                self.assertEqual(post.call_count,expected)
                self.assertEqual(caught.exception.calls,expected)

    def test_disabled_api_is_safe_and_has_no_pointless_retries(self):
        result,media,obj=visual_fixtures.VisualJudgeTests().fixture()
        response=Mock(ok=False,status_code=403,json=lambda:{'error':{'message':'is disabled gemini-secret',
            'details':[{'reason':'SERVICE_DISABLED'}]}})
        with tempfile.TemporaryDirectory() as folder:
            p=Path(folder);(p/'landmarks.json').write_text('{}')
            with patch('spincoach.gemini_judge.prepare_media',return_value=media), \
                 patch('spincoach.gemini_judge.position_request_parts',return_value=([], 'prompt',[{'image_url':{'url':'data:image/jpeg;base64,aW1hZ2U='}}])), \
                 patch('spincoach.gemini_judge.requests.post',return_value=response) as post:
                with self.assertRaises(GeminiFailure) as caught:
                    generate_gemini_report(result,folder,'gemini-secret')
            self.assertEqual(caught.exception.code,'gemini_api_disabled')
            self.assertEqual(post.call_count,1)
            self.assertNotIn('gemini-secret',str(caught.exception)+(p/'gemini_attempts.json').read_text())

    def test_nvidia_fallback_keeps_its_key_model_and_actual_call_counts(self):
        with tempfile.TemporaryDirectory() as folder, \
             patch('spincoach.coaching.generate_gemini_report',side_effect=GeminiFailure('Gemini API is disabled.','gemini_api_disabled',1,.1)), \
             patch('spincoach.coaching.generate_visual_report',return_value={'api_calls':3,'model':'nvidia-test','fallback_used':False}) as nvidia:
            report=generate_coaching_report({},folder,'nvidia-secret','gemini-secret')
            self.assertEqual(nvidia.call_args.args[2],'nvidia-secret')
            self.assertLessEqual(nvidia.call_args.args[4],75)
            self.assertEqual(report['provider'],'NVIDIA')
            self.assertEqual(report['model'],'nvidia-test')
            self.assertEqual(report['primary_provider'],'Gemini')
            self.assertEqual(report['fallback_from'],'Gemini')
            self.assertEqual(report['api_calls'],4)
            self.assertEqual(report['gemini_api_calls'],1)
            self.assertEqual(report['nvidia_api_calls'],3)

    def test_success_never_calls_nvidia_and_no_key_means_no_silent_local_grade(self):
        with tempfile.TemporaryDirectory() as folder, \
             patch('spincoach.coaching.generate_gemini_report',return_value={'provider':'Gemini','model':'gemini-test'}) as gemini, \
             patch('spincoach.coaching.generate_visual_report') as nvidia:
            (Path(folder)/'provider_fallback.json').write_text('{"reason":"previous attempt"}')
            report=generate_coaching_report({},folder,'nvidia-secret','gemini-secret')
            self.assertEqual(report['provider'],'Gemini');nvidia.assert_not_called()
            self.assertFalse((Path(folder)/'provider_fallback.json').exists())
            gemini.side_effect=GeminiFailure('Gemini quota reached.','gemini_quota',1,.1)
            with self.assertRaises(ProcessingFailure):
                generate_coaching_report({},folder,None,'gemini-secret')
            nvidia.assert_not_called()

    def test_timeout_and_incomplete_answer_cannot_appear_as_completed_reports(self):
        result,media,obj=visual_fixtures.VisualJudgeTests().fixture()
        for answer in [requests.Timeout('gemini-secret'),Mock(ok=True,json=lambda:{'candidates':[{'finishReason':'MAX_TOKENS'}]})]:
            with tempfile.TemporaryDirectory() as folder:
                (Path(folder)/'landmarks.json').write_text('{}')
                with patch('spincoach.gemini_judge.prepare_media',return_value=media), \
                     patch('spincoach.gemini_judge.position_request_parts',return_value=([], 'prompt',[{'image_url':{'url':'data:image/jpeg;base64,aW1hZ2U='}}])), \
                     patch('spincoach.gemini_judge.requests.post') as post:
                    if isinstance(answer,Exception):post.side_effect=answer
                    else:post.return_value=answer
                    with self.assertRaises(GeminiFailure) as caught:
                        generate_gemini_report(result,folder,'gemini-secret')
                self.assertNotIn('gemini-secret',str(caught.exception))
                self.assertFalse((Path(folder)/'coaching_report.md').exists())
