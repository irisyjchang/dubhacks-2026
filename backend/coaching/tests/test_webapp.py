import io
import json
import tempfile
import time
import unittest
from unittest.mock import patch
from pathlib import Path

from webapp import create_app,run_pipeline
from spincoach.errors import ProcessingFailure
from unittest.mock import Mock


class UploadTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.calls = []

        def runner(source, destination, key, update, **options):
            self.calls.append((source, destination, key, options))
            update('Tracking test video')
            if options.get('prepare_only'):
                (destination / 'input.mp4').write_bytes(b'preview')
                (destination / 'analysis.json').write_text(json.dumps({'duration_s':4,'element_suggestion':{
                    'element':'unknown','label':'Not sure','reason':'No reliable suggestion.'}}))
                return
            (destination / 'feedback.mp4').write_bytes(b'0123456789')
            (destination / 'coaching_report.md').write_text('Full report: <script>not HTML</script>')
            (destination / 'analysis.json').write_text(json.dumps({'timing_s': {'total': 1}}))
            (destination / 'coaching_assessment.json').write_text(json.dumps({
                'generator': 'NVIDIA language model' if key else 'local coaching narrative',
                'status': 'completed', 'model': 'test-model' if key else None}))

        self.app = create_app(self.folder.name, api_key='server-secret', runner=runner)
        self.client = self.app.test_client()

    def tearDown(self):
        self.app.extensions['spin_pool'].shutdown(wait=True)
        self.folder.cleanup()

    def upload(self, name='clip.mov', mode='nvidia', content=b'video'):
        return self.client.post('/api/jobs', data={'video': (io.BytesIO(content), name), 'mode': mode})

    def finish(self, response):
        self.assertEqual(response.status_code, 202)
        url = response.json['status_url']
        for _ in range(100):
            job = self.client.get(url).json
            if job['status']=='needs_confirmation':
                confirmed=self.client.post(f"/api/jobs/{job['id']}/confirm",json={'element':'unknown'})
                self.assertEqual(confirmed.status_code,202)
            if job['status'] in {'completed', 'failed'}:
                return job
            time.sleep(.01)
        self.fail('Job did not finish')

    def test_upload_report_range_requests_and_isolation(self):
        first = self.finish(self.upload(name='../../clip.mov'))
        second = self.finish(self.upload(mode='local'))
        self.assertEqual(first['status'], 'completed')
        self.assertIn('Full report:', first['report'])
        self.assertNotEqual(first['id'], second['id'])
        self.assertEqual(self.calls[0][2], 'server-secret')
        self.assertEqual(self.calls[2][2], '')
        self.assertNotIn('server-secret', json.dumps(first))
        self.assertEqual(self.calls[0][0].name, 'upload.mov')
        self.assertTrue(self.calls[0][0].is_relative_to(Path(self.folder.name).resolve()))
        video = self.client.get(first['files']['feedback.mp4'], headers={'Range': 'bytes=0-3'})
        self.assertEqual(video.status_code, 206)
        self.assertEqual(video.data, b'0123')
        video.close()
        self.assertEqual(self.client.get(f"/api/jobs/{first['id']}/files/process.log").status_code, 404)
        self.assertEqual(self.client.get('/api/jobs/nonexistent').status_code, 404)

    def test_bad_uploads_and_foreign_origins_are_rejected(self):
        self.assertEqual(self.client.post('/api/jobs').status_code, 400)
        self.assertEqual(self.upload(name='script.py').status_code, 400)
        self.assertEqual(self.upload(content=b'').status_code, 400)
        self.assertEqual(self.client.post('/api/jobs', headers={'Origin': 'https://another.test'}).status_code, 403)
        self.app.config['MAX_CONTENT_LENGTH'] = 20
        self.assertEqual(self.upload().status_code, 413)

    def test_missing_key_never_silently_uses_local_templates(self):
        with patch.dict('os.environ', {}, clear=True):
            app = create_app(self.folder.name, api_key='', runner=lambda *args: None)
        try:
            client = app.test_client()
            response = client.post('/api/jobs', data={'video': (io.BytesIO(b'video'), 'clip.mp4')})
            self.assertEqual(response.status_code, 400)
            self.assertIn('API key', response.json['error'])
        finally:
            app.extensions['spin_pool'].shutdown(wait=True)

    def test_processing_failure_is_visible_without_exposing_key(self):
        def broken(source, destination, key, update, **options):
            raise ValueError('Failure involving ' + key)
        app = create_app(self.folder.name, api_key='private-secret', runner=broken)
        try:
            client = app.test_client()
            response = client.post('/api/jobs', data={'video': (io.BytesIO(b'video'), 'clip.mp4')})
            for _ in range(100):
                job = client.get(response.json['status_url']).json
                if job['status'] == 'failed':
                    break
                time.sleep(.01)
            self.assertEqual(job['status'], 'failed')
            self.assertNotIn('private-secret', json.dumps(job))
            self.assertNotIn('files', job)
        finally:
            app.extensions['spin_pool'].shutdown(wait=True)

    def test_confirmation_is_required_and_phase_markers_are_validated(self):
        response=self.upload()
        url=response.json['status_url'];job_id=response.json['id']
        for _ in range(100):
            job=self.client.get(url).json
            if job['status']=='needs_confirmation':
                break
            time.sleep(.01)
        self.assertEqual(job['status'],'needs_confirmation')
        preview=self.client.get(job['preview_url'])
        self.assertEqual(preview.status_code,200)
        preview.close()
        self.assertEqual(self.client.get(f'/api/jobs/{job_id}/files/feedback.mp4').status_code,404)
        confirm=f'/api/jobs/{job_id}/confirm'
        for payload in [{'element':'unrecognised'}, {'element':'jump','markers':{'takeoff_s':2}},
                        {'element':'jump','markers':{'takeoff_s':3,'landing_s':2}},
                        {'element':'jump','markers':{'takeoff_s':1,'landing_s':9}},
                        {'element':'sit_spin','markers':{'takeoff_s':1,'landing_s':2}}]:
            self.assertEqual(self.client.post(confirm,json=payload).status_code,400)
        self.assertEqual(self.client.post(confirm,json={'element':'waltz_jump',
            'markers':{'takeoff_s':1,'landing_s':2}}).status_code,202)
        for _ in range(100):
            job=self.client.get(url).json
            if job['status']=='completed':
                break
            time.sleep(.01)
        self.assertEqual(job['status'],'completed')
        self.assertEqual(self.calls[-1][3]['element'],'waltz_jump')
        self.assertEqual(self.calls[-1][3]['markers'],{'takeoff_s':1.,'landing_s':2.})
        self.assertEqual(self.client.post(confirm,json={'element':'jump'}).status_code,409)

    def test_report_retry_reuses_tracking_and_keeps_credentials_private(self):
        calls=[]
        def runner(source,destination,key,update,**options):
            calls.append(options)
            if options['prepare_only']:
                (destination/'input.mp4').write_bytes(b'preview')
                (destination/'analysis.json').write_text(json.dumps({'duration_s':4}))
            elif len(calls)==2:
                raise ProcessingFailure('NVIDIA coaching returned HTTP 500.','nvidia_unavailable',True)
            else:
                (destination/'feedback.mp4').write_bytes(b'video')
                (destination/'analysis.json').write_text('{}')
                (destination/'coaching_report.md').write_text('Recovered coaching')
                (destination/'coaching_assessment.json').write_text(json.dumps({'status':'completed','model':'fallback-model'}))
        app=create_app(self.folder.name,api_key='retry-private-key',gemini_key='gemini-retry-private',runner=runner)
        try:
            client=app.test_client()
            upload=client.post('/api/jobs',data={'video':(io.BytesIO(b'video'),'clip.mov')})
            url=upload.json['status_url'];job_id=upload.json['id']
            for _ in range(100):
                job=client.get(url).json
                if job['status']=='needs_confirmation':
                    client.post(f'/api/jobs/{job_id}/confirm',json={'element':'spin'})
                if job['status']=='failed':break
                time.sleep(.01)
            self.assertTrue(job['can_retry']);self.assertEqual(job['error_code'],'nvidia_unavailable')
            self.assertNotIn('retry-private-key',json.dumps(job))
            self.assertNotIn('gemini-retry-private',json.dumps(job))
            self.assertEqual(client.post(f'/api/jobs/{job_id}/retry').status_code,202)
            for _ in range(100):
                job=client.get(url).json
                if job['status']=='completed':break
                time.sleep(.01)
            self.assertEqual(job['status'],'completed')
            self.assertEqual([c['prepare_only'] for c in calls],[True,False,False])
            self.assertTrue(calls[-1]['resume'])
            self.assertEqual([c['gemini_key'] for c in calls],['gemini-retry-private']*3)
            self.assertEqual(client.post(f'/api/jobs/{job_id}/retry').status_code,409)
        finally:
            app.extensions['spin_pool'].shutdown(wait=True)

    def test_gemini_server_key_is_private_and_local_mode_disables_it(self):
        calls=[]
        def runner(source,destination,key,update,**options):
            calls.append((key,options['gemini_key']))
            raise ValueError('Provider failed '+options['gemini_key'])
        with patch.dict('os.environ',{},clear=True):
            app=create_app(self.folder.name,api_key='',gemini_key='gemini-private',runner=runner)
        try:
            client=app.test_client()
            self.assertNotIn('gemini-private',client.get('/').text)
            for mode in ['nvidia','local']:
                upload=client.post('/api/jobs',data={'video':(io.BytesIO(b'video'),'clip.mov'),'mode':mode})
                self.assertEqual(upload.status_code,202)
                for _ in range(100):
                    job=client.get(upload.json['status_url']).json
                    if job['status']=='failed':break
                    time.sleep(.01)
                self.assertNotIn('gemini-private',json.dumps(job))
            self.assertEqual(calls,[('','gemini-private'),('','')])
        finally:
            app.extensions['spin_pool'].shutdown(wait=True)

    def test_worker_service_error_is_forwarded_instead_of_generic_video_error(self):
        cap=Mock();cap.isOpened.return_value=True;cap.get.side_effect=[30,90]
        worker=Mock();worker.stdout=io.StringIO('SPINCOACH_ERROR '+json.dumps({
            'message':'NVIDIA returned HTTP 500 for private-secret and gemini-worker-private','code':'nvidia_unavailable','retryable':True})+'\n')
        worker.wait.return_value=1;worker.poll.return_value=1
        with tempfile.TemporaryDirectory() as folder, \
             patch('cv2.VideoCapture',return_value=cap),patch('webapp.subprocess.Popen',return_value=worker) as popen:
            with self.assertRaises(ProcessingFailure) as raised:
                run_pipeline(Path('example.mov'),Path(folder),'private-secret',lambda stage:None,gemini_key='gemini-worker-private')
            self.assertIn('HTTP 500',str(raised.exception))
            self.assertNotIn('private-secret',str(raised.exception))
            self.assertNotIn('gemini-worker-private',str(raised.exception)+(Path(folder)/'process.log').read_text())
            self.assertEqual(popen.call_args.kwargs['env']['GEMINI_API_KEY'],'gemini-worker-private')
            self.assertNotIn('gemini-worker-private',repr(popen.call_args.args[0]))
            self.assertTrue(raised.exception.retryable)
