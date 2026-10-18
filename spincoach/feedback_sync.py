"""Publish completed spin reports to the local MongoDB-backed text coach."""
from __future__ import annotations

import json
import os
from pathlib import Path
from urllib.parse import urlsplit
from urllib.request import Request, urlopen


def feedback_payload(folder, job_id, video_name):
    folder = Path(folder)
    analysis = json.loads((folder / 'analysis.json').read_text())
    assessment = json.loads((folder / 'coaching_assessment.json').read_text())
    report = (folder / 'coaching_report.md').read_text()
    return {
        'source': 'spincoach',
        'sourceId': job_id,
        'videoName': video_name,
        'feedback': {
            'report': report,
            'headline': analysis.get('headline', ''),
            'durationSeconds': analysis.get('duration_s'),
            'findings': [{key: item[key] for key in (
                'kind', 'title', 'start_s', 'end_s', 'confidence', 'observation',
                'interpretation', 'action', 'limitation') if key in item}
                for item in analysis.get('feedback', [])],
            'notAssessed': analysis.get('not_assessed', []),
            'provenance': {key: assessment.get(key) for key in ('generator', 'model', 'status')},
        },
    }


def publish_feedback(payload):
    url = os.environ.get('COACH_SYNC_URL', 'http://127.0.0.1:8787/api/coach/analysis')
    parsed = urlsplit(url)
    if parsed.scheme != 'http' or parsed.hostname not in {'127.0.0.1', 'localhost'}:
        raise ValueError('Coach sync requires a local HTTP endpoint.')
    body = json.dumps(payload, allow_nan=False).encode('utf-8')
    req = Request(url, data=body, headers={'Content-Type': 'application/json'}, method='POST')
    with urlopen(req, timeout=8) as response:
        if response.status != 200:
            raise ValueError('The local text coach did not save the report.')
    return True


def read_feedback(path, payload=None):
    """Read saved feedback even after the in-memory upload jobs have reset."""
    endpoint = os.environ.get('COACH_SYNC_URL', 'http://127.0.0.1:8787/api/coach/analysis')
    parsed = urlsplit(endpoint)
    if parsed.scheme != 'http' or parsed.hostname not in {'127.0.0.1', 'localhost'}:
        raise ValueError('Coach sync requires a local HTTP endpoint.')
    url = f'{parsed.scheme}://{parsed.netloc}/api/coach/{path}'
    body = None if payload is None else json.dumps(payload, allow_nan=False).encode('utf-8')
    req = Request(url, data=body, headers={'Content-Type': 'application/json'},
                  method='GET' if payload is None else 'POST')
    with urlopen(req, timeout=90 if payload is not None else 8) as response:
        return json.loads(response.read())
