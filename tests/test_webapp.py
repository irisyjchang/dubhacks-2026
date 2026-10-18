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
        self.published = []

        def runner(source, destination, key, update):
            self.calls.append((source, destination, key))
            update('Tracking test video')
            (destination / 'feedback.mp4').write_bytes(b'0123456789')
            (destination / 'feedback.mov').write_bytes(b'annotated-mov')
            (destination / 'coaching_report.md').write_text('Full report: <script>not HTML</script>')
            (destination / 'analysis.json').write_text(json.dumps({'timing_s': {'total': 1}}))
            (destination / 'coaching_assessment.json').write_text(json.dumps({
                'generator': 'NVIDIA language model' if key else 'local coaching narrative',
                'status': 'completed', 'model': 'test-model' if key else None}))

        self.app = create_app(self.folder.name, api_key='server-secret', runner=runner,
                              feedback_publisher=self.published.append)
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
            if job['status'] == 'failed' or (job['status'] == 'completed' and job.get('feedback_sync') in {'saved', 'failed'}):
                return job
            time.sleep(.01)
        self.fail('Job did not finish')

    def test_upload_report_range_requests_and_isolation(self):
        first = self.finish(self.upload(name='../../clip.mov'))
        second = self.finish(self.upload(mode='local'))
        self.assertEqual(first['status'], 'completed')
        self.assertEqual(first['feedback_sync'], 'saved')
        self.assertEqual(self.published[0]['feedback']['report'], first['report'])
        self.assertEqual(self.published[0]['sourceId'], first['id'])
        self.assertEqual(self.published[0]['videoName'], 'clip.mov')
        self.assertNotIn('server-secret', json.dumps(self.published))
        self.assertNotIn('upload.mov', json.dumps(self.published))
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
        movie = self.client.get(first['files']['feedback.mov'])
        self.assertEqual(movie.status_code, 200)
        self.assertEqual(movie.mimetype, 'video/quicktime')
        self.assertEqual(movie.data, b'annotated-mov')
        movie.close()
        retry = self.client.post(f"/api/jobs/{first['id']}/coach")
        self.assertEqual(retry.json['feedback_sync'], 'saved')
        self.assertEqual(self.published[-1]['sourceId'], first['id'])
        self.assertEqual(self.client.post('/api/jobs/unknown/coach').status_code, 409)
        self.assertEqual(self.client.get(f"/api/jobs/{first['id']}/files/process.log").status_code, 404)
        self.assertEqual(self.client.get('/api/jobs/nonexistent').status_code, 404)

    def test_imessage_upload_key_reuses_job_and_history_entry(self):
        def submit():
            return self.client.post('/api/jobs',
                headers={'Idempotency-Key': 'sp-' + 'a' * 64},
                data={'video': (io.BytesIO(b'video'), 'phone.mov'), 'mode': 'nvidia'})
        first = self.finish(submit())
        second = self.finish(submit())
        self.assertEqual(first['id'], second['id'])
        self.assertEqual(len(self.calls), 1)
        self.assertEqual(len(self.published), 1)

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

    def test_coach_outage_preserves_completed_report_and_supports_retry(self):
        self.app.extensions['spin_pool'].shutdown(wait=True)
        calls = []
        def publisher(payload):
            calls.append(payload)
            if len(calls) == 1:
                raise ConnectionError('private error detail')
        # Reuse the test runner's output with a publisher that first fails.
        def runner(source, destination, key, update):
            (destination / 'feedback.mp4').write_bytes(b'video')
            (destination / 'coaching_report.md').write_text('Review the arm position at 2s.')
            (destination / 'analysis.json').write_text('{}')
            (destination / 'coaching_assessment.json').write_text('{"status":"local"}')
        self.app = create_app(self.folder.name, api_key='server-secret', runner=runner, feedback_publisher=publisher)
        self.client = self.app.test_client()
        job = self.finish(self.upload())
        self.assertEqual(job['status'], 'completed')
        self.assertEqual(job['feedback_sync'], 'failed')
        self.assertNotIn('private error detail', json.dumps(job))
        result = self.client.post(f"/api/jobs/{job['id']}/coach")
        self.assertEqual(result.json['feedback_sync'], 'saved')
        self.assertEqual(calls[0], calls[1])

    def test_feedback_timeline_survives_without_in_memory_upload_jobs(self):
        feedback_id = 'a' * 64
        requested = []
        def reader(path):
            requested.append(path)
            if path == 'messaging':
                return {'ready': True, 'number': '+16285027257', 'goal': 'Soft forward reach'}
            if path == 'timeline/' + feedback_id:
                return {'id': feedback_id, 'videoName': 'past-spin.mov', 'feedback': {'report': 'Preserve the soft reach at 6s.'}}
            return {'items': [{'id': feedback_id, 'videoName': 'past-spin.mov'}], 'nextCursor': 'next-page'}
        app = create_app(self.folder.name, feedback_reader=reader)
        try:
            client = app.test_client()
            self.assertFalse(app.extensions['spin_jobs'])
            self.assertEqual(client.get('/api/feedback').json['items'][0]['videoName'], 'past-spin.mov')
            self.assertIn('6s', client.get('/api/feedback/' + feedback_id).json['feedback']['report'])
            self.assertEqual(client.get('/api/feedback?before=next-page').status_code, 200)
            self.assertEqual(requested[-1], 'timeline?before=next-page')
            self.assertEqual(client.get('/api/feedback/not-valid').status_code, 404)
            self.assertEqual(client.get('/api/feedback?before=%21%21').status_code, 400)
            self.assertIn(b'Your feedback timeline', client.get('/coaching-tools').data)
            self.assertEqual(client.get('/api/text-coach').json['number'], '+16285027257')
        finally:
            app.extensions['spin_pool'].shutdown(wait=True)

    def test_group_preview_proxies_only_valid_local_rooms(self):
        calls = []
        def reader(path, payload=None):
            calls.append((path, payload))
            return {'rooms': []} if payload is None else {'replied': False}
        app = create_app(self.folder.name, feedback_reader=reader)
        try:
            client = app.test_client()
            room_id = '12345678-1234-1234-1234-123456789012'
            self.assertEqual(client.get('/api/coach/rooms').json, {'rooms': []})
            self.assertEqual(client.post('/api/coach/rooms', json={'name': 'Preview'}).status_code, 200)
            message = {'id': 'message', 'role': 'coach', 'text': 'Preserve forward reach.'}
            response = client.post(f'/api/coach/rooms/{room_id}/messages', json=message)
            self.assertFalse(response.json['replied'])
            self.assertEqual(calls[-1], (f'rooms/{room_id}/messages', message))
            self.assertEqual(client.get('/api/coach/rooms/invalid').status_code, 404)
            self.assertEqual(client.post('/api/coach/rooms', json=[]).status_code, 400)
            self.assertEqual(client.post('/api/coach/rooms', json={}, headers={'Origin': 'https://foreign.test'}).status_code, 403)
            self.assertIn(b'Skating group + AI', client.get('/coaching-tools').data)
        finally:
            app.extensions['spin_pool'].shutdown(wait=True)
