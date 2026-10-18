import io
import json
import tempfile
import time
import unittest
from unittest.mock import patch
from pathlib import Path

from webapp import create_app


class UploadTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.calls = []

        def runner(source, destination, key, update):
            self.calls.append((source, destination, key))
            update('Tracking test video')
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
        self.assertEqual(self.calls[1][2], '')
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

    def test_index_describes_the_api(self):
        response = self.client.get('/')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json['upload'], 'POST /api/jobs')
        self.assertNotIn('server-secret', json.dumps(response.json))

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
        def broken(source, destination, key, update):
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
