"""Perceptron whole-person anchors, with explicitly labelled short interpolation.

Contract: https://docs.perceptron.inc/perceptron-mk1.5/capabilities/video-tracking
Chat boxes use a 0–1000 grid, independently scaled to the prepared video axes.
"""
from __future__ import annotations

import base64
import bisect
import json
import math
import re
import time
import xml.etree.ElementTree as ET
from pathlib import Path

import cv2
import numpy as np
import requests

MODEL = 'perceptron-mk1.5'
MAX_GAP_S = .8
PROMPT = '''Track only the main foreground figure skater performing the element,
not spectators or background skaters. Return exactly one complete
<track mention="main_skater" asset_idx="0"> with timestamped children like
<point_box t="0.0 seconds"> (x1,y1) (x2,y2) </point_box>.
Coordinates normalized to 0–1000, top-left and bottom-right. Enclose the ENTIRE
person including head, outstretched hands, feet and skates. Give a box every
0.25 seconds from first to last visible frame, including first and last frames.
Maintain the same identity. Do not invent positions during occlusion or off-screen.
Return only the track markup, no explanation.'''


def parse_track(text, width, height, last_time_s):
    """Reject partial, ambiguous, wrong-asset or invalid geometry responses."""
    text = text.strip()
    if text.startswith('```') and text.endswith('```'):
        text = text.split('\n', 1)[1].rsplit('```', 1)[0].strip()
    root = ET.fromstring(text)
    if root.tag not in {'track','collection'} or root.attrib.get('asset_idx', '0') != '0':
        raise ValueError('Expected one track on the supplied video')
    # Live Mk1.5 sometimes emits a single-object collection of timestamped,
    # geometry-bearing <track> leaves instead of point_box children. Normalize
    # only this narrow, unambiguous variant; do not merge separate object tracks.
    leaf_tag = 'point_box'
    if root.tag == 'collection':
        if len(root)==1 and root[0].tag=='track' and len(root[0]):
            child=root[0]
            if child.attrib.get('asset_idx','0')!='0':
                raise ValueError('Wrong track asset')
            root=child
        else:
            leaf_tag = 'track'
    mentions={child.attrib['mention'] for child in root if child.attrib.get('mention')}
    if len(mentions)>1:
        raise ValueError('Multiple object identities in track')
    anchors = []
    for child in root:
        if child.tag != leaf_tag or child.attrib.get('asset_idx', '0') != '0':
            raise ValueError('Expected timestamped boxes on video 0')
        stamp = re.fullmatch(r'\s*(\d+(?:\.\d+)?)\s*(?:seconds?|s)?\s*', child.attrib.get('t', ''))
        coords = re.fullmatch(r'\s*\(\s*([\d.]+)\s*,\s*([\d.]+)\s*\)\s*\(\s*([\d.]+)\s*,\s*([\d.]+)\s*\)\s*', child.text or '')
        if stamp is None or coords is None or len(child):
            raise ValueError('Invalid track observation')
        t = float(stamp[1])
        x1,y1,x2,y2 = map(float, coords.groups())
        if not all(math.isfinite(v) for v in [t,x1,y1,x2,y2]):
            raise ValueError('Non-finite track observation')
        if not (0 <= x1 < x2 <= 1000 and 0 <= y1 < y2 <= 1000 and 0 <= t <= last_time_s + .04):
            raise ValueError('Track observation outside video bounds')
        anchors.append({'time_s': min(t,last_time_s),
                        'bbox_xywh_px': [x1*width/1000,y1*height/1000,
                                         (x2-x1)*width/1000,(y2-y1)*height/1000]})
    anchors.sort(key=lambda a:a['time_s'])
    if len(anchors) < 2 or any(b['time_s'] <= a['time_s'] for a,b in zip(anchors,anchors[1:])):
        raise ValueError('Expected distinct ordered waypoints')
    return anchors


def box_at(track, time_s):
    """No extrapolation or filling long visibility gaps; report every box's origin."""
    anchors = track.get('anchors', [])
    if not anchors:
        return None
    times = [a['time_s'] for a in anchors]
    i = bisect.bisect_left(times,time_s)
    # Associate a model waypoint with its nearest native frame (at most half a frame).
    tolerance = .501 / track['fps']
    for j in (i, i-1):
        if 0 <= j < len(times) and abs(times[j]-time_s) <= tolerance:
            return {**anchors[j], 'source':'perceptron', 'anchor_time_s':times[j]}
    if not 0 < i < len(times) or times[i]-times[i-1] > MAX_GAP_S:
        return None
    a,b = anchors[i-1],anchors[i]
    u = (time_s-a['time_s'])/(b['time_s']-a['time_s'])
    return {'bbox_xywh_px':[(1-u)*x+u*y for x,y in zip(a['bbox_xywh_px'],b['bbox_xywh_px'])],
            'source':'interpolated', 'anchor_times_s':[a['time_s'],b['time_s']]}


def request_track(video, key, output, timeout_s=60):
    """One request plus one bounded format retry; keep remote failures nonfatal."""
    cap = cv2.VideoCapture(str(video))
    width,height = int(cap.get(3)),int(cap.get(4))
    fps,count = cap.get(5),int(cap.get(7))
    cap.release()
    track = {'provider':'Perceptron', 'model':MODEL, 'status':'fallback',
             'width':width,'height':height,'fps':fps,'frame_count':count,
             'anchors':[], 'api_calls':0,
             'interpolation':'Linear between same-track anchors at most 0.8 seconds apart; no long-gap filling or extrapolation.'}
    started = time.perf_counter()
    payload = {'model':MODEL, 'messages':[{'role':'user','content':[
        {'type':'video_url','video_url':{'url':'data:video/mp4;base64,'+base64.b64encode(Path(video).read_bytes()).decode()}},
        {'type':'text','text':PROMPT+f' Last source-frame timestamp: {(count-1)/fps:.3f} seconds. Never use timestamps beyond this.'}]}],
        'vision_config':{'annotation_format':'box'}, 'reasoning_effort':'low', 'max_completion_tokens':8192}
    for attempt in range(2):
        remaining=timeout_s-(time.perf_counter()-started)
        if remaining<=1:
            break
        try:
            track['api_calls']+=1
            response = requests.post('https://api.perceptron.inc/v1/chat/completions',
                headers={'Authorization':'Bearer '+key},json=payload,timeout=(min(10,remaining),remaining))
            if not response.ok:
                track['warning'] = f'Perceptron returned HTTP {response.status_code}; showing local pose-derived boxes instead.'
                break
            choice = response.json()['choices'][0]
            # Keep key-free diagnostics locally, outside the public artifact list.
            raw=choice['message'].get('content') or ''
            Path(output).with_name(f'perceptron_response_{attempt+1}.txt').write_text(raw.replace(key,'[REDACTED]'))
            if choice.get('finish_reason') != 'stop' or choice['message'].get('tool_calls'):
                raise ValueError('Incomplete tracking response')
            anchors = parse_track(raw,width,height,(count-1)/fps)
            track.update(status='completed',anchors=anchors)
            track.pop('warning',None)
            break
        except requests.Timeout:
            track['warning'] = 'Perceptron timed out; showing local pose-derived boxes instead.'
            break
        except requests.RequestException:
            track['warning'] = 'Perceptron could not be reached; showing local pose-derived boxes instead.'
            break
        except (ValueError,KeyError,IndexError,TypeError,ET.ParseError):
            track['warning'] = 'Perceptron returned invalid boxes; showing local pose-derived boxes instead.'
            payload['messages'][0]['content'][1]['text']+=' The previous response failed format validation. Use exactly one <track> containing <point_box t="N seconds">(x1,y1) (x2,y2)</point_box> elements, ordered valid boxes in 0–1000, and increasing in-range timestamps. No prose or other tags.'
    track['elapsed_s'] = round(time.perf_counter()-started,3)
    Path(output).write_text(json.dumps(track,indent=2))
    return track


def select_tracked_pose(result, previous, observation, width, height):
    """Match joints to the API target; avoid selecting a distant background person."""
    from mediapipe_skater import geometry,select_pose
    if not observation:
        return select_pose(result,previous)
    x,y,w,h = observation['bbox_xywh_px']
    candidates=[]
    for i,points in enumerate(result.pose_landmarks):
        shape = geometry(points)
        if shape is None:
            continue
        lo,hi,center,area = shape
        cx,cy = center*np.array([width,height])
        if not (x <= cx <= x+w and y <= cy <= y+h):
            continue
        visible=[p for p in points if min(p.visibility,p.presence)>=.35]
        inside=sum(x<=p.x*width<=x+w and y<=p.y*height<=y+h for p in visible)/max(1,len(visible))
        if inside < .5:
            continue
        score=inside - .1*math.hypot((cx-x-w/2)/w,(cy-y-h/2)/h)
        candidates.append((score,i,(lo,hi,center,area)))
    return max(candidates,key=lambda candidate:candidate[0]) if candidates else None


def refine_box(box, landmarks, width, height):
    """Include confidently matched hands/skates missed between sparse anchors.

    The input box remains the identity gate, and original model anchors stay
    untouched in the export. This enclosing box is a local fusion, not API output.
    """
    points=[p for p in landmarks if min(p['visibility'],p['presence'])>=.65
            and math.isfinite(p['x_px']) and math.isfinite(p['y_px'])
            and 0<=p['x_px']<width and 0<=p['y_px']<height]
    if not points:
        return list(box)
    x,y,w,h=box
    x1=max(0,min(x,min(p['x_px'] for p in points)-6))
    y1=max(0,min(y,min(p['y_px'] for p in points)-6))
    x2=min(width,max(x+w,max(p['x_px'] for p in points)+6))
    y2=min(height,max(y+h,max(p['y_px'] for p in points)+6))
    return [x1,y1,x2-x1,y2-y1]


def save_dense_track(track, data, output):
    records=[{'frame_id':f['frame_id'],'timestamp_ms':f['timestamp_ms'],
              'bbox_xywh_px':f.get('person_bbox_xywh_px'),
              'source':f.get('person_bbox_source'),
              'evidence':f.get('person_bbox_evidence')} for f in data['frames']]
    summary={k:v for k,v in track.items() if k!='anchors'}
    summary['model_anchor_count']=len(track.get('anchors',[]))
    summary['frames_with_box']=sum(r['bbox_xywh_px'] is not None for r in records)
    summary['frame_sources']={source:sum(r['source']==source for r in records)
                              for source in ['perceptron','interpolated','fused','mediapipe']}
    Path(output).write_text(json.dumps({**summary,'anchors':track.get('anchors',[]),'frames':records},indent=2))
    return summary
