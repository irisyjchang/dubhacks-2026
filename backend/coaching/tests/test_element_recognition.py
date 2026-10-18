import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock,patch

import requests

from spincoach.element_recognition import identify_element,validate_identification,recognition_prompt
from spincoach.gemini_judge import GeminiFailure


class ElementRecognitionTests(unittest.TestCase):
    def fixture(self,folder):
        p=Path(folder);(p/'video.mp4').write_bytes(b'video');(p/'frames.jpg').write_bytes(b'frames')
        return {'video':'video.mp4','contact_sheet':'frames.jpg','frames':[], 'input_sha256':'test-hash'}

    def local(self):
        return {'element':'spin','label':'Spin','reason':'Local rotation changes.',
                'method':'experimental pose-sequence heuristic','confidence':'unverified','requires_confirmation':True}

    def answer(self,element='sit_spin'):
        return {'element':element,'confidence':'high','reason':'Repeated rotation in a sustained low posture.',
                'evidence':[{'time_s':1.5,'observation':'Low posture during repeated rotations.'}]}

    def test_gemini_primary_sends_native_video_and_records_actual_model(self):
        with tempfile.TemporaryDirectory() as folder:
            media=self.fixture(folder)
            response=Mock(ok=True,json=lambda:{'modelVersion':'gemini-returned',
                'candidates':[{'finishReason':'STOP','content':{'parts':[{'text':json.dumps(self.answer())}]}}]})
            with patch('spincoach.element_recognition.prepare_recognition_media',return_value=media), \
                 patch('spincoach.gemini_judge.requests.post',return_value=response) as post:
                suggestion=identify_element(folder,{}, {'duration_s':7},self.local(),'gemini-secret','nvidia-secret')
            self.assertEqual(post.call_count,1)
            self.assertEqual(post.call_args.kwargs['headers'],{'x-goog-api-key':'gemini-secret'})
            parts=post.call_args.kwargs['json']['contents'][0]['parts']
            self.assertEqual(parts[0]['inlineData']['mimeType'],'video/mp4')
            self.assertEqual(parts[0]['videoMetadata'],{'fps':5})
            self.assertEqual(suggestion['element'],'sit_spin')
            self.assertEqual(suggestion['model'],'gemini-returned')
            self.assertEqual(suggestion['nvidia_api_calls'],0)
            self.assertTrue(suggestion['requires_confirmation'])
            self.assertFalse(suggestion['fallback_used'])
            self.assertNotIn('gemini-secret',(Path(folder)/'element_identification.json').read_text())

    def test_gemini_failure_uses_nvidia_video_with_separate_credentials_and_counts(self):
        with tempfile.TemporaryDirectory() as folder:
            media=self.fixture(folder)
            session=Mock(calls=2);session.invoke.side_effect=GeminiFailure('Unavailable',calls=2)
            response=Mock(ok=True,json=lambda:{'model':'nvidia-returned','choices':[
                {'finish_reason':'stop','message':{'content':json.dumps(self.answer())}}]})
            response.__enter__=Mock(return_value=response);response.__exit__=Mock(return_value=False)
            with patch('spincoach.element_recognition.prepare_recognition_media',return_value=media), \
                 patch('spincoach.element_recognition.GeminiSession',return_value=session), \
                 patch('spincoach.element_recognition.requests.post',return_value=response) as post:
                suggestion=identify_element(folder,{}, {'duration_s':7},self.local(),'gemini-secret','nvidia-secret')
            self.assertEqual(suggestion['provider'],'NVIDIA')
            self.assertEqual(suggestion['primary_provider'],'Gemini')
            self.assertEqual(suggestion['model'],'nvidia-returned')
            self.assertEqual(suggestion['api_calls'],3)
            self.assertEqual(suggestion['gemini_api_calls'],2)
            self.assertEqual(post.call_args.kwargs['headers']['Authorization'],'Bearer nvidia-secret')
            self.assertEqual(post.call_args.kwargs['json']['messages'][0]['content'][0]['type'],'video_url')
            self.assertTrue(suggestion['fallback_used'])

    def test_rejected_video_uses_disclosed_frames_and_both_failures_keep_manual_option(self):
        for success in [True,False]:
            with tempfile.TemporaryDirectory() as folder:
                media=self.fixture(folder)
                session=Mock(calls=1);session.invoke.side_effect=GeminiFailure('Unavailable')
                response=Mock(ok=True,json=lambda:{'model':'nvidia-returned','choices':[
                    {'finish_reason':'stop','message':{'content':json.dumps(self.answer())}}]})
                response.__enter__=Mock(return_value=response);response.__exit__=Mock(return_value=False)
                sent=[]
                def post(url,**kwargs):
                    sent.append(json.loads(json.dumps(kwargs['json'])))
                    if len(sent)==1 or not success:raise requests.Timeout('secret')
                    return response
                with patch('spincoach.element_recognition.prepare_recognition_media',return_value=media), \
                     patch('spincoach.element_recognition.GeminiSession',return_value=session), \
                     patch('spincoach.element_recognition.requests.post',side_effect=post):
                    suggestion=identify_element(folder,{}, {'duration_s':7},self.local(),'gemini-secret','nvidia-secret')
                self.assertEqual(suggestion['api_calls'],3)
                self.assertFalse(any(p['type']=='video_url' for p in sent[1]['messages'][0]['content']))
                self.assertEqual(suggestion['provider'],'NVIDIA' if success else 'Local')
                self.assertIn('frame sequence' if success else 'pose sequence',suggestion['input_mode'])
                self.assertTrue(suggestion['requires_confirmation'])

    def test_invalid_gemini_label_falls_back_instead_of_passing_through(self):
        with tempfile.TemporaryDirectory() as folder:
            media=self.fixture(folder);session=Mock(calls=1)
            session.invoke.return_value=(self.answer('quad_lutz'),'gemini-returned')
            with patch('spincoach.element_recognition.prepare_recognition_media',return_value=media), \
                 patch('spincoach.element_recognition.GeminiSession',return_value=session):
                suggestion=identify_element(folder,{}, {'duration_s':7},self.local(),'gemini-secret')
            self.assertEqual(suggestion['provider'],'Local');self.assertEqual(suggestion['element'],'spin')
            self.assertTrue(suggestion['fallback_used'])

    def test_local_only_never_prepares_remote_media_or_calls_services(self):
        with tempfile.TemporaryDirectory() as folder, \
             patch('spincoach.element_recognition.prepare_recognition_media') as media, \
             patch('spincoach.element_recognition.GeminiSession') as gemini, \
             patch('spincoach.element_recognition.requests.post') as post:
            suggestion=identify_element(folder,{}, {'duration_s':7},self.local())
            self.assertEqual(suggestion['provider'],'Local');self.assertEqual(suggestion['api_calls'],0)
            media.assert_not_called();gemini.assert_not_called();post.assert_not_called()

    def test_general_skating_is_supported_and_bad_evidence_is_rejected(self):
        obj=self.answer('unknown')
        self.assertEqual(validate_identification(obj,7)['element'],'unknown')
        for time_s in [-1,7,100,float('nan'),True,'1.5']:
            obj=self.answer();obj['evidence'][0]['time_s']=time_s
            with self.assertRaises(ValueError):validate_identification(obj,7)
        obj=self.answer();obj['confidence']='100%'
        with self.assertRaises(ValueError):validate_identification(obj,7)
        self.assertIn('Gliding',recognition_prompt(7))

    def test_subsecond_clip_requires_manual_selection_without_guessing_or_api_calls(self):
        with tempfile.TemporaryDirectory() as folder, \
             patch('spincoach.element_recognition.prepare_recognition_media') as media, \
             patch('spincoach.element_recognition.GeminiSession') as gemini, \
             patch('spincoach.element_recognition.requests.post') as post:
            suggestion=identify_element(folder,{}, {'duration_s':.9},self.local(),'gemini-secret','nvidia-secret')
            self.assertEqual(suggestion['element'],'unknown')
            self.assertEqual(suggestion['api_calls'],0)
            self.assertTrue(suggestion['requires_confirmation'])
            self.assertIn('shorter than one second',suggestion['reason'])
            media.assert_not_called();gemini.assert_not_called();post.assert_not_called()


class RecognitionPipelineTests(unittest.TestCase):
    def test_inspection_has_keys_and_resume_reuses_identification_without_double_counting(self):
        import run_spin_coach as pipeline
        with tempfile.TemporaryDirectory() as folder:
            p=Path(folder);source=p/'source.mov';source.write_bytes(b'video')
            model=p/'model.task';model.write_bytes(b'model');destination=p/'result'
            suggestion={'element':'sit_spin','label':'Sit spin','method':'video model','provider':'NVIDIA',
                        'api_calls':2,'gemini_api_calls':1,'nvidia_api_calls':1,'elapsed_s':4}
            args=['run_spin_coach.py','--input',str(source),'--output',str(destination),'--model',str(model),
                  '--analyze-only','--gemini-report','--nvidia-report']
            with patch.dict('os.environ',{'GEMINI_API_KEY':'gemini-private','NVIDIA_API_KEY':'nvidia-private'}), \
                 patch.object(pipeline,'prepare'), \
                 patch.object(pipeline,'extract',return_value=({'frames':[]},{})), \
                 patch.object(pipeline,'analyze',return_value={'duration_s':7,'frames':[]}), \
                 patch.object(pipeline,'save_dense_track',return_value={'api_calls':1}), \
                 patch.object(pipeline,'build_kinematics',return_value={'frames':[]}), \
                 patch.object(pipeline,'motion_suggestion',return_value={}), \
                 patch.object(pipeline,'identify_element',return_value=suggestion) as identify, \
                 patch.object(pipeline,'write_assessment') as coaching, \
                 patch('sys.argv',args):
                pipeline.main()
                identify.assert_called_once()
                self.assertEqual(identify.call_args.kwargs['gemini_key'],'gemini-private')
                self.assertEqual(identify.call_args.kwargs['nvidia_key'],'nvidia-private')
                # Save the tracked data normally produced by extract, then resume.
                (destination/'landmarks.json').write_text('{"frames":[]}')
                with patch('sys.argv',args+['--resume']):pipeline.main()
                identify.assert_called_once();coaching.assert_not_called()
            saved=json.loads((destination/'analysis.json').read_text())
            self.assertEqual(saved['cost']['api_calls'],3)
            self.assertEqual(saved['cost']['identification_api_calls'],2)
            self.assertEqual(saved['cost']['gemini_api_calls'],1)
            self.assertEqual(saved['cost']['nvidia_api_calls'],1)
            self.assertEqual(saved['element_suggestion'],suggestion)


if __name__=='__main__':unittest.main()
