"""Local upload harness for the existing spin-coaching pipeline."""
from __future__ import annotations

import argparse
import getpass
import json
import math
import os
import re
import signal
import subprocess
import sys
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from urllib.parse import urlsplit, urlencode
from urllib.error import HTTPError

from flask import Flask, jsonify, render_template, request, send_file
from spincoach.feedback_sync import feedback_payload, publish_feedback, read_feedback

ROOT = Path(__file__).resolve().parent
ARTIFACTS = {'feedback.mp4', 'feedback.mov', 'coaching_report.md', 'coaching_assessment.json',
             'report.md', 'analysis.json', 'video_captions.json', 'kinematics.json'}
EXTENSIONS = {'.mov', '.mp4', '.m4v', '.webm', '.avi'}


def run_pipeline(source, destination, key, update, *, imported_backend=False):
    """Run each clip in its own process; credentials stay in its environment."""
    import cv2
    cap = cv2.VideoCapture(str(source))
    try:
        fps, count = cap.get(cv2.CAP_PROP_FPS), cap.get(cv2.CAP_PROP_FRAME_COUNT)
        if not cap.isOpened() or not math.isfinite(fps) or fps <= 0 or not math.isfinite(count) or count <= 0:
            raise ValueError('This file could not be read as a video.')
        if count / fps > 30:
            raise ValueError('Use a clip of 30 seconds or less for this test.')
    finally:
        cap.release()
    script = ROOT / 'backend' / 'coaching' / 'run_spin_coach.py' if imported_backend else ROOT / 'run_spin_coach.py'
    command = [sys.executable, str(script), '--input', str(source),
               '--output', str(destination)]
    if imported_backend:
        # No movement has been confirmed in iMessage: use the backend's general
        # skating review instead of silently guessing a technical element.
        command += ['--element', 'unknown', '--model', str(ROOT / 'backend' / 'convert' / 'models' / 'pose_landmarker_heavy.task')]
    env = os.environ.copy()
    env.pop('NVIDIA_API_KEY', None)
    env['MPLBACKEND'] = 'Agg'
    if key:
        command.append('--nvidia-report')
        env['NVIDIA_API_KEY'] = key
    process = subprocess.Popen(command, cwd=ROOT, env=env, stdout=subprocess.PIPE,
                               stderr=subprocess.STDOUT, text=True, start_new_session=True)
    expired = threading.Event()

    def stop():
        expired.set()
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass

    timer = threading.Timer(360, stop)
    timer.start()
    logs = []
    try:
        for line in process.stdout:
            safe = line.replace(key, '[REDACTED]') if key else line
            logs.append(safe)
            if line.startswith(('Preparing video', 'Tracking the main', 'Generating the coaching', 'Timeline ', 'Rendering evidence')):
                update(safe.strip())
        code = process.wait()
    finally:
        timer.cancel()
        process.stdout.close()
        if process.poll() is None:
            stop()
            process.wait()
        (destination / 'process.log').write_text(''.join(logs))
    if expired.is_set():
        raise ValueError('Processing exceeded the six-minute test limit. Try a shorter clip.')
    if code:
        raise ValueError('Video processing failed. Details are in this job\'s local process.log.')


def run_imported_backend(source, destination, key, update):
    run_pipeline(source, destination, key, update, imported_backend=True)
    update('Preparing your annotated MOV for iMessage...')
    import imageio_ffmpeg
    output = destination / 'feedback.mov'
    temporary = destination / 'feedback.pending.mov'
    subprocess.run([imageio_ffmpeg.get_ffmpeg_exe(), '-hide_banner', '-loglevel', 'error', '-y',
                    '-i', str(destination / 'feedback.mp4'), '-map', '0:v:0', '-map', '0:a?',
                    '-c', 'copy', '-movflags', '+faststart', '-f', 'mov', str(temporary)],
                   check=True, timeout=90, capture_output=True)
    if not temporary.is_file() or not temporary.stat().st_size:
        raise ValueError('Backend did not produce a readable MOV video.')
    temporary.replace(output)


def create_app(output_root=None, api_key=None, runner=run_pipeline, feedback_publisher=publish_feedback, feedback_reader=read_feedback):
    app = Flask(__name__)
    app.config['MAX_CONTENT_LENGTH'] = 200 * 1024 * 1024
    root = Path(output_root or ROOT / 'outputs' / 'web_jobs').resolve()
    root.mkdir(parents=True, exist_ok=True)
    server_key = api_key or os.environ.get('NVIDIA_API_KEY', '')
    jobs, lock = {}, threading.Lock()
    pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix='spin-video')
    app.extensions['spin_jobs'] = jobs
    app.extensions['spin_pool'] = pool

    @app.before_request
    def local_requests_only():
        if request.host.split(':')[0] not in {'localhost', '127.0.0.1'}:
            return jsonify(error='This test server accepts localhost requests only.'), 403
        if request.method == 'POST' and request.headers.get('Origin'):
            if urlsplit(request.headers['Origin']).netloc != request.host:
                return jsonify(error='Upload from the local test page.'), 403

    @app.errorhandler(413)
    def too_large(error):
        return jsonify(error='Upload a video smaller than 200 MB.'), 413

    def update_job(job_id, **changes):
        with lock:
            jobs[job_id].update(changes)

    def sync_feedback(job_id, destination):
        update_job(job_id, feedback_sync='syncing', feedback_sync_error=None)
        try:
            with lock:
                video_name = jobs[job_id]['video_name']
            feedback_publisher(feedback_payload(destination, job_id, video_name))
            update_job(job_id, feedback_sync='saved')
        except Exception:
            # A coach outage must not discard an otherwise successful video analysis.
            update_job(job_id, feedback_sync='failed', feedback_sync_error=
                       'Report not shared with your text coach. Start npm run photon and retry sharing.')

    def process_job(job_id, source, destination, key):
        started = time.perf_counter()
        update_job(job_id, status='processing', stage='Checking video...')
        try:
            runner(source, destination, key, lambda text: update_job(job_id, stage=text))
            report = json.loads((destination / 'coaching_assessment.json').read_text())
            analysis = json.loads((destination / 'analysis.json').read_text())
            if not (destination / 'feedback.mp4').is_file():
                raise ValueError('Processing did not create the feedback video.')
            partial = report.get('status') == 'partial'
            update_job(job_id, status='completed', stage='Ready',
                       report=(destination / 'coaching_report.md').read_text(),
                       generator=report.get('generator'), model=report.get('model'),
                       warning=('Some model intervals failed. See the report details; those video intervals have no model caption.' if partial else None),
                       model_errors=report.get('errors', []),
                       timing_s=analysis.get('timing_s', {}),
                       processing_s=round(time.perf_counter() - started, 2))
            sync_feedback(job_id, destination)
        except Exception as error:
            message = str(error).replace(key, '[REDACTED]') if key else str(error)
            update_job(job_id, status='failed', stage='Failed', error=message,
                       processing_s=round(time.perf_counter() - started, 2))

    @app.get('/')
    def index():
        return render_template('upload.html', key_configured=bool(server_key))

    @app.get('/coaching-tools')
    def coaching_tools():
        return render_template('coach-tools.html', key_configured=bool(server_key))

    @app.post('/api/jobs')
    def upload():
        video = request.files.get('video')
        if not video or not video.filename:
            return jsonify(error='Choose a video to upload.'), 400
        suffix = Path(video.filename).suffix.lower()
        if suffix not in EXTENSIONS:
            return jsonify(error='Use MOV, MP4, M4V, WebM, or AVI.'), 400
        mode = request.form.get('mode', 'nvidia')
        if mode not in {'nvidia', 'local'}:
            return jsonify(error='Unknown analysis mode.'), 400
        key = (request.form.get('api_key', '').strip() or server_key) if mode == 'nvidia' else ''
        if mode == 'nvidia' and not key:
            return jsonify(error='Enter your NVIDIA API key, or select the local-only test mode.'), 400
        upload_key = request.headers.get('Idempotency-Key', '')
        if upload_key and not re.fullmatch(r'[a-zA-Z0-9_-]{1,128}', upload_key):
            return jsonify(error='Invalid upload key.'), 400
        job_id = uuid.uuid5(uuid.NAMESPACE_URL, 'imessage:' + upload_key).hex if upload_key else uuid.uuid4().hex
        with lock:
            if job_id in jobs:
                return jsonify(id=job_id, status_url=f'/api/jobs/{job_id}'), 202
        job_root = root / job_id
        source = job_root / ('upload' + suffix)
        destination = job_root / 'result'
        destination.mkdir(parents=True)
        video.save(source)
        if not source.stat().st_size:
            source.unlink()
            destination.rmdir()
            job_root.rmdir()
            return jsonify(error='The uploaded file was empty.'), 400
        with lock:
            jobs[job_id] = {'id':job_id, 'status':'queued', 'stage':'Queued',
                            'mode':mode, 'submitted_at':time.time(),
                            'video_name':Path(video.filename.replace('\\', '/')).name[:300],
                            'feedback_sync':'pending'}
        pool.submit(process_job, job_id, source, destination, key)
        return jsonify(id=job_id, status_url=f'/api/jobs/{job_id}'), 202

    @app.get('/api/feedback')
    @app.get('/api/feedback/<feedback_id>')
    def feedback_history(feedback_id=None):
        if feedback_id is not None and not re.fullmatch(r'[a-f0-9]{64}', feedback_id):
            return jsonify(error='Feedback not found.'), 404
        cursor = request.args.get('before', '')
        if len(cursor) > 500 or (cursor and not re.fullmatch(r'[A-Za-z0-9_-]+', cursor)):
            return jsonify(error='Invalid timeline cursor.'), 400
        path = f'timeline/{feedback_id}' if feedback_id else 'timeline' + ('?' + urlencode({'before':cursor}) if cursor else '')
        try:
            return jsonify(feedback_reader(path))
        except HTTPError as error:
            code = error.code if error.code in {400, 404} else 503
            return jsonify(error='Feedback not found.' if code == 404 else 'Could not load feedback history.'), code
        except Exception:
            return jsonify(error='Feedback history is unavailable. Check that the text coach is running.'), 503

    @app.get('/api/text-coach')
    def text_coach_status():
        try:
            return jsonify(feedback_reader('messaging'))
        except Exception:
            return jsonify(error='Text coach is temporarily unavailable.'), 503

    @app.route('/api/coach/rooms', methods=['GET', 'POST'])
    @app.route('/api/coach/rooms/<room_id>', methods=['GET'])
    @app.route('/api/coach/rooms/<room_id>/messages', methods=['POST'])
    def coaching_room(room_id=None):
        if room_id is not None and not re.fullmatch(r'[a-f0-9-]{36}', room_id):
            return jsonify(error='Room not found.'), 404
        path = 'rooms' + (f'/{room_id}' if room_id else '')
        if request.method == 'POST' and room_id:
            path += '/messages'
        try:
            if request.method == 'POST':
                if request.content_length and request.content_length > 16000:
                    return jsonify(error='Message too large.'), 413
                payload = request.get_json(silent=True)
                if not isinstance(payload, dict):
                    return jsonify(error='Invalid message.'), 400
                return jsonify(feedback_reader(path, payload))
            return jsonify(feedback_reader(path))
        except HTTPError as error:
            return jsonify(error='Could not load or update this group.'), error.code if error.code in {400, 404} else 503
        except Exception:
            return jsonify(error='Group coach unavailable. Check the local coach service and retry.'), 503

    @app.get('/api/jobs/<job_id>')
    def status(job_id):
        with lock:
            job = dict(jobs[job_id]) if job_id in jobs else None
        if job is None:
            return jsonify(error='Job not found. Jobs reset when the test server restarts.'), 404
        job['elapsed_s'] = round(time.time() - job['submitted_at'], 1)
        if job['status'] == 'completed':
            job['files'] = {name:f'/api/jobs/{job_id}/files/{name}' for name in ARTIFACTS
                            if (root / job_id / 'result' / name).is_file()}
        return jsonify(job)

    @app.post('/api/jobs/<job_id>/coach')
    def share_feedback(job_id):
        with lock:
            ready = jobs.get(job_id, {}).get('status') == 'completed'
        if not ready:
            return jsonify(error='Complete the analysis before sharing feedback.'), 409
        sync_feedback(job_id, root / job_id / 'result')
        with lock:
            job = jobs[job_id]
            return jsonify(feedback_sync=job['feedback_sync'], error=job.get('feedback_sync_error'))

    @app.get('/api/jobs/<job_id>/files/<filename>')
    def artifact(job_id, filename):
        with lock:
            ready = jobs.get(job_id, {}).get('status') == 'completed'
        if not ready or filename not in ARTIFACTS or not re.fullmatch(r'[0-9a-f]{32}', job_id):
            return jsonify(error='File not found.'), 404
        path = root / job_id / 'result' / filename
        if not path.is_file():
            return jsonify(error='File not found.'), 404
        return send_file(path, conditional=True,
                         as_attachment=request.args.get('download') == '1', download_name=filename)

    return app


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--port', type=int, default=8000)
    parser.add_argument('--ask-key', action='store_true', help='Read a server-side NVIDIA key without saving it')
    parser.add_argument('--backend', action='store_true', help='Use the imported backend coaching pipeline and produce a MOV')
    args = parser.parse_args()
    key = getpass.getpass('NVIDIA API key (not saved): ') if args.ask_key else None
    create_app(api_key=key, runner=run_imported_backend if args.backend else run_pipeline,
               output_root=ROOT / 'outputs' / 'imessage_jobs' if args.backend else None).run(
                   host='127.0.0.1', port=args.port, debug=False, threaded=True)
