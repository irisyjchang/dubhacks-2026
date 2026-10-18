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
from urllib.parse import urlsplit

from flask import Flask, jsonify, render_template, request, send_file
from spincoach.elements import ELEMENTS,validate_markers
from spincoach.errors import ProcessingFailure

ROOT = Path(__file__).resolve().parent
ARTIFACTS = {'feedback.mp4', 'coaching_report.md', 'coaching_assessment.json',
             'report.md', 'analysis.json', 'video_captions.json', 'kinematics.json', 'input.mp4', 'person_tracking.json',
             'element_identification.json'}
EXTENSIONS = {'.mov', '.mp4', '.m4v', '.webm', '.avi'}


def run_pipeline(source, destination, key, update, *, element='unknown', prepare_only=False, resume=False, markers=None, perceptron_key='',gemini_key=''):
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
    command = [sys.executable, str(ROOT / 'run_spin_coach.py'), '--input', str(source),
               '--output', str(destination), '--element', element,
               '--phase-markers', json.dumps(markers or {})]
    if prepare_only:
        command.append('--analyze-only')
    if resume:
        command.append('--resume')
    env = os.environ.copy()
    env.pop('NVIDIA_API_KEY', None)
    env.pop('PERCEPTRON_API_KEY', None)
    env.pop('GEMINI_API_KEY',None)
    env['MPLBACKEND'] = 'Agg'
    if key:
        command.append('--nvidia-report')
        env['NVIDIA_API_KEY'] = key
    if perceptron_key:
        command.append('--perceptron-track')
        env['PERCEPTRON_API_KEY'] = perceptron_key
    if gemini_key:
        command.append('--gemini-report')
        env['GEMINI_API_KEY']=gemini_key
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
    failure=None
    try:
        for line in process.stdout:
            safe = line.replace(key, '[REDACTED]') if key else line
            if perceptron_key:
                safe=safe.replace(perceptron_key,'[REDACTED]')
            if gemini_key:
                safe=safe.replace(gemini_key,'[REDACTED]')
            logs.append(safe)
            if safe.startswith('SPINCOACH_ERROR '):
                try:
                    parsed=json.loads(safe.split(' ',1)[1])
                    if isinstance(parsed,dict) and isinstance(parsed.get('message'),str):
                        failure=parsed
                except (ValueError,TypeError):
                    pass
            if line.startswith(('Preparing video', 'Tracking the main', 'Generating the coaching', 'Timeline ', 'Rendering evidence','Coaching service:')):
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
        if failure:
            raise ProcessingFailure(failure['message'],failure.get('code','processing_failed'),
                                    failure.get('retryable') is True)
        raise ValueError('Video processing failed. Details are in this job\'s local process.log.')


def create_app(output_root=None, api_key=None, runner=run_pipeline, perceptron_key=None,gemini_key=None):
    app = Flask(__name__)
    app.config['MAX_CONTENT_LENGTH'] = 200 * 1024 * 1024
    root = Path(output_root or ROOT / 'outputs' / 'web_jobs').resolve()
    root.mkdir(parents=True, exist_ok=True)
    server_key = api_key or os.environ.get('NVIDIA_API_KEY', '')
    server_person_key = perceptron_key or os.environ.get('PERCEPTRON_API_KEY','')
    server_gemini_key = gemini_key or os.environ.get('GEMINI_API_KEY','')
    tracker_keys = {}  # Private worker credentials, never included in public jobs.
    gemini_keys = {}
    jobs, pending, retry_context, lock = {}, {}, {}, threading.Lock()
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

    def process_job(job_id, source, destination, key, element='auto', prepare_only=True, markers=None):
        started = time.perf_counter()
        update_job(job_id, status='processing', stage='Checking video...',error=None,error_code=None,can_retry=False)
        try:
            runner(source, destination, key, lambda text: update_job(job_id, stage=text),
                   element='unknown' if element=='auto' else element,
                   prepare_only=prepare_only,resume=not prepare_only,markers=markers,
                   perceptron_key=tracker_keys.get(job_id,''),gemini_key=gemini_keys.get(job_id,''))
            if prepare_only:
                analysis=json.loads((destination / 'analysis.json').read_text())
                suggestion=analysis.get('element_suggestion',{'element':'unknown','label':ELEMENTS['unknown']['label'],
                    'reason':'Please select the movement you intended.','confidence':'unverified'})
                with lock:
                    pending[job_id]=(source,destination,key)
                    jobs[job_id].update(status='needs_confirmation',stage='Confirm the element',
                        suggestion=suggestion,selected_element=suggestion['element'] if element=='auto' else element,
                        duration_s=analysis['duration_s'],
                        preview_url=f'/api/jobs/{job_id}/files/input.mp4',
                        preparation_s=round(time.perf_counter()-started,2))
                return
            report = json.loads((destination / 'coaching_assessment.json').read_text())
            analysis = json.loads((destination / 'analysis.json').read_text())
            if not (destination / 'feedback.mp4').is_file():
                raise ValueError('Processing did not create the feedback video.')
            partial = report.get('status') == 'partial'
            update_job(job_id, status='completed', stage='Ready',
                       report=(destination / 'coaching_report.md').read_text(),
                       generator=report.get('generator'), model=report.get('model'),provider=report.get('provider','NVIDIA' if report.get('model') else 'local'),
                       primary_provider=report.get('primary_provider'),fallback_from=report.get('fallback_from'),
                       warning=('Some model intervals failed. See the report details; those video intervals have no model caption.' if partial else
                                f"{report.get('fallback_reason','Primary NVIDIA model unavailable.')} Coaching generated by {report.get('provider','NVIDIA')} ({report['model']})." if report.get('fallback_used') else None),
                       model_errors=report.get('errors', []),
                       timing_s=analysis.get('timing_s', {}),
                       person_tracking=analysis.get('person_tracking'),
                       element_analysis=report.get('element_analysis'),summary=report.get('summary'),
                       phase_details=report.get('phase_details',[]),
                       processing_s=round(time.perf_counter() - started + jobs[job_id].get('preparation_s',0), 2))
            tracker_keys.pop(job_id,None)
            gemini_keys.pop(job_id,None)
        except Exception as error:
            message = str(error).replace(key, '[REDACTED]') if key else str(error)
            if tracker_keys.get(job_id):
                message=message.replace(tracker_keys[job_id],'[REDACTED]')
            if gemini_keys.get(job_id):
                message=message.replace(gemini_keys[job_id],'[REDACTED]')
            can_retry=not prepare_only and bool(getattr(error,'retryable',False))
            if can_retry:
                with lock:
                    retry_context[job_id]=(source,destination,key,element,markers)
            update_job(job_id, status='failed', stage='Failed', error=message,
                       error_code=getattr(error,'code','processing_failed'),can_retry=can_retry,
                       processing_s=round(time.perf_counter() - started, 2))
            if not can_retry:
                tracker_keys.pop(job_id,None)
                gemini_keys.pop(job_id,None)

    @app.get('/')
    def index():
        return render_template('upload.html', key_configured=bool(server_key),elements=ELEMENTS,
                               perceptron_configured=bool(server_person_key),gemini_configured=bool(server_gemini_key))

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
        element=request.form.get('element','auto')
        if element!='auto' and element not in ELEMENTS:
            return jsonify(error='Choose a supported element or Not sure.'),400
        key = (request.form.get('api_key', '').strip() or server_key) if mode == 'nvidia' else ''
        gemini_key=server_gemini_key if mode=='nvidia' else ''
        if mode == 'nvidia' and not (key or gemini_key):
            return jsonify(error='Configure a Gemini or NVIDIA API key, or select the local-only test mode.'), 400
        use_person_tracker=mode=='nvidia' and request.form.get('perceptron_track')=='on'
        person_key=(request.form.get('perceptron_key','').strip() or server_person_key) if use_person_tracker else ''
        if use_person_tracker and not person_key:
            return jsonify(error='Enter a Perceptron key or turn off Perceptron person tracking.'),400
        job_id = uuid.uuid4().hex
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
            tracker_keys[job_id]=person_key
            gemini_keys[job_id]=gemini_key
            jobs[job_id] = {'id':job_id, 'status':'queued', 'stage':'Queued',
                            'mode':mode, 'submitted_at':time.time()}
        pool.submit(process_job, job_id, source, destination, key,element)
        return jsonify(id=job_id, status_url=f'/api/jobs/{job_id}'), 202

    @app.post('/api/jobs/<job_id>/confirm')
    def confirm(job_id):
        payload=request.get_json(silent=True) or {}
        if not isinstance(payload,dict):
            return jsonify(error='Confirmation must be a JSON object.'),400
        element=payload.get('element','unknown')
        with lock:
            job=jobs.get(job_id)
            if not job:
                return jsonify(error='Job not found.'),404
            if job['status']!='needs_confirmation' or job_id not in pending:
                return jsonify(error='This job is not waiting for confirmation.'),409
            try:
                markers=validate_markers(element,payload.get('markers',{}),job['duration_s'])
            except (ValueError,TypeError) as error:
                return jsonify(error=str(error)),400
            source,destination,key=pending.pop(job_id)
            job.update(status='queued',stage='Queued for confirmed-element feedback',confirmed_element=element)
        pool.submit(process_job,job_id,source,destination,key,element,False,markers)
        return jsonify(id=job_id,status_url=f'/api/jobs/{job_id}'),202

    @app.post('/api/jobs/<job_id>/retry')
    def retry(job_id):
        with lock:
            if job_id not in jobs:
                return jsonify(error='Job not found.'),404
            if jobs[job_id]['status']!='failed' or job_id not in retry_context:
                return jsonify(error='This job is not waiting for a report retry.'),409
            source,destination,key,element,markers=retry_context.pop(job_id)
            jobs[job_id].update(status='queued',stage='Retrying coaching with saved tracking',error=None,can_retry=False)
        pool.submit(process_job,job_id,source,destination,key,element,False,markers)
        return jsonify(id=job_id,status_url=f'/api/jobs/{job_id}'),202

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

    @app.get('/api/jobs/<job_id>/files/<filename>')
    def artifact(job_id, filename):
        with lock:
            state=jobs.get(job_id, {}).get('status')
            ready=state=='completed' or (filename=='input.mp4' and state=='needs_confirmation')
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
    parser.add_argument('--ask-perceptron-key', action='store_true', help='Read a server-side Perceptron key without saving it')
    parser.add_argument('--ask-gemini-key',action='store_true',help='Read a Gemini key without saving it; NVIDIA becomes fallback')
    parser.add_argument('--detach', action='store_true', help='Run the local test server in the background (macOS/Linux)')
    args = parser.parse_args()
    if args.detach and not hasattr(os, 'fork'):
        parser.error('--detach is supported on macOS/Linux; run without it on this platform.')
    key = getpass.getpass('NVIDIA API key (not saved): ') if args.ask_key else None
    person_key = getpass.getpass('Perceptron API key (not saved): ') if args.ask_perceptron_key else None
    gemini_key = getpass.getpass('Gemini API key (not saved): ') if args.ask_gemini_key else None
    if args.detach:
        logs = ROOT / 'outputs'
        logs.mkdir(exist_ok=True)
        pid = os.fork()
        if pid:
            print(f'Starting background server (PID {pid}) at http://127.0.0.1:{args.port}')
            print(f'Server log: {logs / "web_server.log"}')
            sys.exit(0)
        os.setsid()
        signal.signal(signal.SIGHUP, signal.SIG_IGN)
        with open(os.devnull, 'r') as incoming, (logs / 'web_server.log').open('a', buffering=1) as outgoing:
            os.dup2(incoming.fileno(), 0)
            os.dup2(outgoing.fileno(), 1)
            os.dup2(outgoing.fileno(), 2)
    create_app(api_key=key,perceptron_key=person_key,gemini_key=gemini_key).run(host='127.0.0.1', port=args.port, debug=False, threaded=True)
