import copy
import json
import tempfile
from pathlib import Path
import unittest
from unittest.mock import patch,Mock

from spincoach.elements import apply_element
from spincoach.element_feedback import finish_element_report
from spincoach.visual_judge import (validate_report,apply_visual_report,parse_response,
                                   prompt_for,generate_visual_report,read_positions,FALLBACK_MODEL)
from spincoach.errors import CoachingServiceError
import test_kinematics as geometry_fixtures


class VisualJudgeTests(unittest.TestCase):
    def fixture(self):
        frames=[geometry_fixtures.KinematicsTests().frame(i) for i in range(60)]
        result={'duration_s':2,'tracking':{'pose_coverage_pct':100},
                'lowered_segment':{'start_s':.5,'end_s':1.5,'duration_s':1},
                'frames':[{'time_s':f['timestamp_ms']/1000,'phase':'lowered posture'} for f in frames]}
        apply_element(result,{'frames':frames},'sit_spin',{'hold_start_s':.5,'hold_end_s':1.5})
        media={'video':'judge_video.mp4','contact_sheet':'judge_frames.jpg','frames':[]}
        rows=[]
        for i,phase in enumerate(result['element_analysis']['phases']):
            a,b=phase['time_s'];ids=[f'f{i}a',f'f{i}b']
            media['frames'] += [{'id':id,'time_s':a+(b-a)*u,'phase_id':phase['id']} for id,u in zip(ids,[.2,.7])]
            code='SPIN-SIT' if i==1 else 'SPIN-ARMS'
            rows.append({'phase_id':phase['id'],'observation':'The arms reach forward and the free leg stays extended.',
                'good':'Your forward arm reach stays clear.','improve':'Keep the free-leg height more consistent.',
                'advice':'Hold the chosen free-leg height through the turn.','cue':'Free foot on a shelf',
                'caption':['Maintain free-leg height','Foot on a shelf'],'confidence':'medium',
                'evidence':[{'frame_id':id,'body_part':'legs','observation':'The free foot sits lower in this view.'} for id in ids],
                'rule_assessments':[{'rule_id':code,'verdict':'needs_work','reason':'The intended position becomes less clear.',
                                     'frame_ids':ids}]})
        obj={'overall':{'good_phase_id':'p0','improve_phase_id':'p1','review':{
            'strengths':'Your forward arm reach stays clear through the entry and hold.',
            'errors':'Your free-leg height changes through the hold, making the position less consistent.',
            'improvements':'Keep your free foot on an imaginary shelf while holding the chosen shape.',
            'score':6,'score_reason':'Clear arm shape, with inconsistent free-leg height.'}},
            'phases':rows,'limits':['Blade edges are not visible.']}
        return result,media,obj

    def test_visual_strengths_and_improvements_replace_blanket_unknown_summary(self):
        result,media,obj=self.fixture()
        validate_report(obj,result,media)
        sections=apply_visual_report(obj,result,media,'test-model')
        analysis=result['element_analysis']
        self.assertEqual(analysis['summary']['good'],obj['phases'][0]['good'])
        self.assertEqual(analysis['summary']['improve'],obj['phases'][1]['improve'])
        self.assertEqual(len(sections),3)
        self.assertTrue(all(s['visual_evidence'] for s in sections))
        self.assertIn('geometric_findings',analysis)
        check=next(c for c in analysis['isu_assessment']['checks'] if c['id']=='SPIN-SIT')
        self.assertEqual(check['status_label'],'Needs work')
        self.assertIsNone(check['applied_reduction'])
        self.assertIsNone(analysis['isu_assessment']['official_goe'])
        self.assertIn('f1a',sections[1]['visual_evidence'][0]['frame_id'])

    def test_frames_cannot_be_invented_or_borrowed_from_another_phase(self):
        for invalid in ['invented','f1a']:
            result,media,obj=self.fixture()
            obj['phases'][0]['evidence'][0]['frame_id']=invalid
            with self.assertRaises(ValueError):validate_report(obj,result,media)

    def test_visible_assessments_cannot_claim_unmeasured_turns_or_blade_calls(self):
        result,media,obj=self.fixture()
        for invalid in ['SPIN-MISSING','JUMP-LANDING','SPIN-TOUCH','MADE-UP']:
            changed=copy.deepcopy(obj)
            changed['phases'][1]['rule_assessments'][0]['rule_id']=invalid
            with self.assertRaises(ValueError):validate_report(changed,result,media)

    def test_phase_coverage_and_numeric_values_are_checked(self):
        result,media,obj=self.fixture()
        changed=copy.deepcopy(obj);changed['phases'].pop()
        with self.assertRaises(ValueError):validate_report(changed,result,media)
        changed=copy.deepcopy(obj);changed['phases'][0]['advice']='Set your knee to 1234 degrees.'
        with self.assertRaises(ValueError):validate_report(changed,result,media)
        changed=copy.deepcopy(obj);changed['phases'][0]['caption'][0]='Knee 123 degrees'
        with self.assertRaises(ValueError):validate_report(changed,result,media)

    def test_official_calls_and_low_evidence_confidence_are_not_fabricated(self):
        result,media,obj=self.fixture()
        changed=copy.deepcopy(obj);changed['phases'][1]['observation']='This is a legal sit position.'
        with self.assertRaises(ValueError):validate_report(changed,result,media)
        changed=copy.deepcopy(obj);changed['phases'][1]['evidence']=changed['phases'][1]['evidence'][:1]
        with self.assertRaises(ValueError):validate_report(changed,result,media)

    def test_prompt_uses_actual_rules_without_preassigning_uncertainty(self):
        result,media,obj=self.fixture()
        prompt=prompt_for(result,media)
        self.assertIn('skating thigh',prompt)
        self.assertIn('Make direct, specific judgments',prompt)
        self.assertNotIn('"status":"not_assessable"',prompt)
        self.assertIn('f1a',prompt)

    def test_model_summary_report_and_captions_agree(self):
        result,media,obj=self.fixture()
        sections=apply_visual_report(obj,result,media,'test-model')
        with tempfile.TemporaryDirectory() as folder:
            report=finish_element_report({'generator':'NVIDIA whole-clip visual coaching','model':'test-model','sections':sections},result,folder)
            text=(Path(folder)/'coaching_report.md').read_text()
            self.assertIn(obj['overall']['review']['strengths'],text)
            self.assertIn(obj['overall']['review']['errors'],text)
            self.assertIn('Final coaching score: 6/10',text)
            self.assertEqual(len(text.strip().split('\n\n')),4)
            self.assertNotIn('Phase source:',text)
            self.assertNotIn('Missing required revolutions —',text)
            self.assertEqual(report['phase_details'][1]['rule_refs'],['SPIN-SIT'])
            self.assertIsNone(report['element_analysis']['isu_assessment']['official_goe'])

    def test_short_review_requires_bounded_score_and_short_paragraphs(self):
        result,media,obj=self.fixture()
        for bad in [11,-1,True,7.5,'7']:
            changed=copy.deepcopy(obj);changed['overall']['review']['score']=bad
            with self.assertRaises(ValueError):validate_report(changed,result,media)
        changed=copy.deepcopy(obj);changed['overall']['review']['score']=None
        validate_report(changed,result,media)
        changed=copy.deepcopy(obj);changed['overall']['review']['strengths']='word '*51
        with self.assertRaises(ValueError):validate_report(changed,result,media)
        changed=copy.deepcopy(obj);changed['overall']['review']['errors']='Set your knee to 123 degrees.'
        with self.assertRaises(ValueError):validate_report(changed,result,media)

    def test_parse_fences_and_empty_thought_markers(self):
        self.assertEqual(parse_response('<|channel>thought\n<channel|>```json\n{"a":1}\n```'),{'a':1})
        self.assertEqual(parse_response('{"a":1}\n\n{ "a": 1 }'),{'a':1})
        with self.assertRaises(ValueError):parse_response('{"a":1}\n{"a":2}')

    def test_kimi_position_reading_uses_instant_mode_and_preserves_model(self):
        import numpy as np
        result,media,obj=self.fixture()
        result['element_analysis']['phases']=result['element_analysis']['phases'][:1]
        media['frames']=[f for f in media['frames'] if f['phase_id']=='p0']
        positions=[{'phase_id':'p0','frame_ids':[f['id'] for f in media['frames']],
                    'free_leg_shape':'extended_back','arm_shape':'open_sideways',
                    'body_height':'upright','sit_depth':'not_sit','description':'The arms open and the free leg extends back.'}]
        response=Mock(ok=True,status_code=200)
        response.__enter__=Mock(return_value=response);response.__exit__=Mock(return_value=False)
        response.json.return_value={'choices':[{'finish_reason':'stop','message':{'content':json.dumps({'positions':positions})}}]}
        with tempfile.TemporaryDirectory() as folder, \
             patch('cv2.imread',return_value=np.zeros((384,288,3),dtype=np.uint8)), \
             patch('spincoach.visual_judge.requests.post',return_value=response) as post:
            self.assertEqual(read_positions(result,media,folder,'test-secret','moonshotai/kimi-k2.6',30),positions)
            payload=post.call_args.kwargs['json']
            self.assertEqual(payload['model'],'moonshotai/kimi-k2.6')
            self.assertEqual(payload['chat_template_kwargs'],{'thinking':False})

    def test_coaching_cannot_contradict_read_leg_shape_or_demand_extra_sit_depth(self):
        result,media,obj=self.fixture()
        positions=[{'phase_id':'p1','free_leg_shape':'folded_front','arm_shape':'close_front',
                    'sit_depth':'appears_at_or_below_parallel'}]
        validate_report(obj,result,media,positions)
        changed=copy.deepcopy(obj)
        changed['phases'][1]['observation']='Your free leg is extended behind as you turn.'
        with self.assertRaises(ValueError):validate_report(changed,result,media,positions)
        changed=copy.deepcopy(obj)
        changed['phases'][1]['improve']='Deepen the sit position.'
        with self.assertRaises(ValueError):validate_report(changed,result,media,positions)

    def test_whole_clip_generation_records_video_fallback_and_model_provenance(self):
        result,media,obj=self.fixture()
        rejected=Mock(status_code=422,ok=False)
        rejected.__enter__=Mock(return_value=rejected);rejected.__exit__=Mock(return_value=False)
        success=Mock(status_code=200,ok=True)
        success.__enter__=Mock(return_value=success);success.__exit__=Mock(return_value=False)
        success.json.return_value={'model':'returned-test-model','choices':[{'finish_reason':'stop',
                    'message':{'content':json.dumps(obj)}}]}
        responses=iter([rejected,success]);sent=[]
        def invoke(*args,**kwargs):
            sent.append(copy.deepcopy(kwargs['json']))
            self.assertEqual(kwargs['headers']['Authorization'],'Bearer fake-secret')
            return next(responses)
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)
            (path/'landmarks.json').write_text('{}')
            (path/media['video']).write_bytes(b'video')
            (path/media['contact_sheet']).write_bytes(b'image')
            with patch('spincoach.visual_judge.prepare_media',return_value=media), \
                 patch('spincoach.visual_judge.read_positions',return_value=[]), \
                 patch('spincoach.visual_judge.requests.post',side_effect=invoke):
                report=generate_visual_report(result,folder,'fake-secret',model='test-model')
            self.assertEqual(report['api_calls'],2)  # actual HTTP calls; position reading is mocked
            self.assertEqual(report['model_returned'],'returned-test-model')
            self.assertIn('video media rejected',report['input_mode'])
            self.assertIn('video_url',[p['type'] for p in sent[0]['messages'][-1]['content']])
            self.assertNotIn('video_url',[p['type'] for p in sent[1]['messages'][-1]['content']])
            self.assertNotIn('fake-secret',''.join(p.read_text() for p in path.glob('*.json')))

    def test_supplemental_measurement_report_preserves_visual_provenance(self):
        from spincoach.artifacts import write_report
        result,media,obj=self.fixture()
        apply_visual_report(obj,result,media,'test-model')
        result.update(original_source='example.mov',feedback=[],tracking={
            'poses':60,'frames':60,'pose_coverage_pct':100,
            'left_knee_accepted_frames':60,'right_knee_accepted_frames':60})
        with tempfile.TemporaryDirectory() as folder:
            write_report(result,folder)
            text=(Path(folder)/'report.md').read_text()
            self.assertIn('Detailed coaching uses NVIDIA visual interpretation',text)
            self.assertEqual(json.loads((Path(folder)/'analysis.json').read_text())['headline'],result['headline'])

    def test_repeated_primary_500_uses_a_different_model_without_video(self):
        result,media,obj=self.fixture();sent=[]
        def response(status,body=None):
            r=Mock(status_code=status,ok=status==200,headers={})
            r.__enter__=Mock(return_value=r);r.__exit__=Mock(return_value=False)
            r.json.return_value=body
            return r
        success={'model':FALLBACK_MODEL,'choices':[{'finish_reason':'stop','message':{'content':json.dumps(obj)}}]}
        responses=iter([response(500),response(500),response(200,success)])
        def invoke(*args,**kwargs):
            sent.append(copy.deepcopy(kwargs['json']));return next(responses)
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder);(path/'landmarks.json').write_text('{}')
            (path/media['video']).write_bytes(b'video');(path/media['contact_sheet']).write_bytes(b'image')
            with patch('spincoach.visual_judge.prepare_media',return_value=media), \
                 patch('spincoach.visual_judge.read_positions',return_value=[]), \
                 patch('spincoach.visual_judge.time.sleep'), \
                 patch('spincoach.visual_judge.requests.post',side_effect=invoke):
                report=generate_visual_report(result,folder,'fake-secret',model='primary-model')
            self.assertEqual([p['model'] for p in sent],['primary-model','primary-model',FALLBACK_MODEL])
            self.assertNotIn('video_url',[p['type'] for p in sent[-1]['messages'][-1]['content']])
            self.assertTrue(report['fallback_used'])
            self.assertEqual(report['model'],FALLBACK_MODEL)
            self.assertEqual(result['element_analysis']['visual_model'],FALLBACK_MODEL)
            self.assertEqual(report['api_calls'],3)
            self.assertIn('model_fallback',(path/'visual_model_attempts.json').read_text())

    def test_authentication_error_is_actionable_and_does_not_change_models(self):
        error=CoachingServiceError(401)
        self.assertFalse(error.retryable)
        self.assertEqual(error.code,'nvidia_credentials')
        self.assertIn('API key',str(error))
