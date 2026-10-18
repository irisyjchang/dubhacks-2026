"""Compute confidence-filtered pose metrics and request a coaching analysis.

Run .video-venv/bin/python analyze_spin.py --call-model
The API key is read from NVIDIA_API_KEY or an un-echoed terminal prompt.
No key is written to the request, report, or source.
"""
from __future__ import annotations

import argparse
import getpass
import json
import os
import time
import datetime
from pathlib import Path

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np
import requests

ROOT = Path(__file__).resolve().parent
OUT = ROOT / 'outputs/spin_analysis'
MODEL = 'meta/muse-glimmer-30b'
THRESHOLD = .65
SOURCES = [
    'https://developers.google.com/edge/mediapipe/solutions/vision/pose_landmarker/python',
    'https://www.isu.org/en/figure-skating-rules/figure-skating-rule/handbooks-single-and-pair-skating',
    'https://build.nvidia.com/meta/muse-glimmer-30b?section=deploy',
]
SYSTEM = """You are an evidence-conscious figure-skating technique analyst giving useful coaching feedback to an adult viewer. You receive MediaPipe coordinates and calculated metrics, NOT video or images. Do not claim to have watched the performance. No model training or fine-tuning has been performed; this is a prompted inference experiment.

Assess what this specific recording supports. Separate measured observations, tentative technique interpretations, and general coaching suggestions. Be constructive and specific. Provide an overall qualitative assessment of how well the spin appears to have been performed, while explaining which important quality factors remain unassessable. If evidence cannot support an overall quality grade, say so plainly, but still identify the clearest supported positives and useful things to review.

Evidence rules:
- All angles are MediaPipe estimates. Image-plane angles are perspective-dependent; monocular world coordinates are inferred, not motion-capture ground truth. Coordinate y is camera/image down, not a calibrated gravity direction. Camera pans, tilts, and distance changes affect apparent motion.
- Visibility and presence scores are not accuracy guarantees. Missing or low-confidence data are not skater errors. The 65% threshold is a developer choice, not a validated accuracy cutoff.
- Never identify the supporting leg just by taking the smaller knee angle. Anatomical left/right labels can swap during occlusion. Do not infer exact anatomical asymmetry or an injury risk.
- Do not infer revolutions, RPM, acceleration, ice travel/centering, blade edge, one-foot support, foot contact, balance loss, falls, exact sit-position legality, GOE, competition level, or an official score. These were not reliably measured. No timestamps define a manually verified entry/hold/exit segmentation. You can describe changes over recorded time without declaring a phase boundary.
- Knee angle alone does not establish a legal sit spin. A crouch-like body configuration is only suggestive. Forward torso inclination can be intentional in a sit position; do not treat nonvertical torso as an automatic mistake.
- Differences between early and late joint angles can reflect intended transitions, changing viewpoint, occlusion, or tracking errors. Do not automatically call their variability wobble or poor control.
- Every performance-specific claim needs a supplied timestamp or metric. Do not invent norms, measurements, desired exact angles, or citations. Distinguish a general practice cue from a correction demonstrated to be necessary here.

Use these coaching dimensions as a review framework: position clarity/compactness, maintaining the intended shape, controlled changes of position, rotation quality, centering, entry and exit. Mark unavailable dimensions unassessable. ISU handbooks distinguish technical identification and judging, but this experiment cannot make either official call.

Return a concise Markdown report (~600 words maximum):
1. Overall take (plain language; confidence; no numerical score).
2. What the coordinates support: 2-4 timestamped findings, with strengths where supported.
3. Up to 3 practical review priorities: observation, implication if confirmed on video, and one general practice cue. If a fault is unproven, make the priority a review question, not a diagnosis.
4. A compact table of 4-6 useful supplied measurements and their limitations.
5. What this model test can and cannot establish. State that training performance, coaching validity, and benchmark accuracy were not evaluated in this single run.
"""


def angle(a, b, c):
    u, v = a-b, c-b
    denom = np.linalg.norm(u)*np.linalg.norm(v)
    return float(np.degrees(np.arccos(np.clip(np.dot(u,v)/denom,-1,1)))) if denom > 1e-8 else None


def stats(values):
    values = np.array([v for v in values if v is not None],float)
    if not len(values):
        return {'valid_samples':0}
    return {'valid_samples':len(values),'median':round(float(np.median(values)),1),
            'p10':round(float(np.percentile(values,10)),1),
            'p90':round(float(np.percentile(values,90)),1)}


def compute(data):
    rows=[]
    samples=[]
    sample_ids=[11,12,13,14,15,16,23,24,25,26,27,28]
    for frame in data['frames']:
        row={'frame_id':frame['frame_id'],'time_s':round(frame['timestamp_ms']/1000,3)}
        p=frame['landmarks'];world=frame['world_landmarks']
        row['pose_detected']=bool(p)
        if p:
            xy=np.array([[j['x_px'],j['y_px']] for j in p])
            xyz=np.array([[j['x'],j['y'],j['z']] for j in world])
            q=np.array([min(j['visibility'],j['presence']) for j in p])
            row['reliable_body_landmarks_of_22']=int(sum(q[11:]>=THRESHOLD))
            for side,ids in [('left',[23,25,27]),('right',[24,26,28])]:
                good=min(q[ids])>=THRESHOLD
                row[f'{side}_knee_min_confidence']=round(float(min(q[ids])),3)
                row[f'{side}_knee_2d_deg']=angle(*xy[ids]) if good else None
                row[f'{side}_knee_inferred_3d_deg']=angle(*xyz[ids]) if good else None
            shoulders=xy[[11,12]].mean(axis=0);hips=xy[[23,24]].mean(axis=0)
            good=min(q[[11,12,23,24]])>=THRESHOLD
            row['projected_torso_inclination_deg']=angle(shoulders,hips,hips+[0,-1]) if good else None
            if frame['frame_id']%6==0:
                samples.append({'time_s':row['time_s'],'world_joints_xyz_m_and_confidence':{
                    p[j]['name']:[round(float(xyz[j,0]),3),round(float(xyz[j,1]),3),
                                  round(float(xyz[j,2]),3),round(float(q[j]),2)] for j in sample_ids}})
        else:
            row['reliable_body_landmarks_of_22']=0
        rows.append(row)
    keys=['left_knee_2d_deg','right_knee_2d_deg','left_knee_inferred_3d_deg',
          'right_knee_inferred_3d_deg','projected_torso_inclination_deg']
    windows=[]
    for start in np.arange(0,7,.5):
        chunk=[r for r in rows if start<=r['time_s']<start+.5]
        if chunk:
            windows.append({'start_s':float(start),'end_s':min(float(start+.5),6.967),
                            'frames':len(chunk),**{key:stats([r.get(key) for r in chunk]) for key in keys}})
    summary={
        'source_file':'IMG_5943.mov','coordinate_file':'outputs/IMG_5943_mediapipe.json',
        'context':'A main skater performing a spinning sequence on ice. Video was not sent to the language model.',
        'duration_s':round(data['frame_count']/data['fps'],3),'fps':data['fps'],
        'frame_count':data['frame_count'],'frames_with_pose':data['frames_with_pose'],
        'pose_detection_coverage_pct':round(100*data['frames_with_pose']/data['frame_count'],1),
        'missing_pose_times_s':[r['time_s'] for r in rows if not r['pose_detected']],
        'joint_confidence_filter':{'minimum_visibility_and_presence':THRESHOLD,
                                 'all_joints_in_angle_must_pass':True},
        'metric_definitions':{
            'knee_2d_deg':'hip-knee-ankle internal angle in image pixels; 180=straight, smaller=more flexed; projection affected',
            'knee_inferred_3d_deg':'same angle in hip-relative estimated MediaPipe 3D; not measured 3D',
            'projected_torso_inclination_deg':'shoulder midpoint to hip midpoint vs image-up; not calibrated gravity, ice axis, or wobble',
            'p10_p90':'10th and 90th percentiles of accepted samples; not uncertainty bounds',
        },
        'overall_metrics':{key:stats([r.get(key) for r in rows]) for key in keys},
        'time_windows':windows,
        'unmeasured':['supporting_leg','revolutions','RPM','blade_edge','ice_relative_travel',
                      'foot_contact','sit_position_legality','formal_GOE','spin_level'],
        'warnings':['Viewpoint changes and camera motion are not compensated.',
                    '2D and inferred 3D disagree in some frames; occlusion and left/right swaps possible.',
                    'No reference performance, repeat trials, or calibrated skating-quality model.',
                    'Whole-clip medians blend intended position changes and should not be treated as consistency scores.'],
        'coordinate_samples_5hz':samples,
    }
    return summary,rows


def plot(rows):
    plt.rcParams.update({'font.size':10,'axes.spines.top':False,'axes.spines.right':False})
    fig,axes=plt.subplots(3,1,figsize=(11,8),sharex=True,layout='constrained')
    t=[r['time_s'] for r in rows]
    for side,color in [('left','#0d9488'),('right','#e87925')]:
        axes[0].plot(t,[r.get(f'{side}_knee_2d_deg') for r in rows],label=f'{side.title()} knee',color=color,lw=1.5)
        axes[1].plot(t,[r.get(f'{side}_knee_inferred_3d_deg') for r in rows],color=color,lw=1.5)
    axes[0].set(ylabel='Image-plane angle (degrees)',ylim=(0,190),title='Hip–knee–ankle angles: smaller means a deeper bend')
    axes[0].legend(loc='upper right')
    axes[1].set(ylabel='Inferred 3D angle (degrees)',ylim=(0,190),title='MediaPipe inferred 3D — compare cautiously with the image-plane estimate')
    axes[2].plot(t,[r['reliable_body_landmarks_of_22'] for r in rows],color='#45556c')
    axes[2].set(ylabel='Reliable body joints / 22',xlabel='Time in recording (seconds)',ylim=(0,23),title='Tracking confidence: both visibility and presence must be at least 0.65')
    for ax in axes:
        ax.grid(alpha=.2)
    fig.suptitle('Skater pose measurements • gaps are rejected estimates, not skating errors',fontsize=13)
    fig.savefig(OUT/'pose_metrics.png',dpi=160)
    plt.close(fig)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--call-model',action='store_true')
    parser.add_argument('--stream',action='store_true',help='Stream output and measure first-token and total latency')
    args=parser.parse_args()
    OUT.mkdir(parents=True,exist_ok=True)
    data=json.loads((ROOT/'outputs/IMG_5943_mediapipe.json').read_text())
    summary,rows=compute(data)
    (OUT/'metrics.json').write_text(json.dumps(summary,indent=2))
    (OUT/'per_frame_metrics.json').write_text(json.dumps(rows,indent=2))
    (OUT/'coach_system_prompt.md').write_text(SYSTEM)
    plot(rows)
    payload={'model':MODEL,'messages':[{'role':'system','content':SYSTEM},
        {'role':'user','content':'Analyze how well this spin was performed from the following coordinate-derived evidence. Prioritize useful honest feedback over an invented score.\n'+json.dumps(summary)}],
        'temperature':.2,'top_p':.95,'max_tokens':8192,'stream':args.stream}
    (OUT/'model_request.json').write_text(json.dumps(payload,indent=2))
    print('Metrics ready:',json.dumps(summary['overall_metrics']),flush=True)
    if not args.call_model:
        return
    key=os.environ.get('NVIDIA_API_KEY') or getpass.getpass('NVIDIA API key (not saved): ')
    start=time.monotonic()
    started_at=datetime.datetime.now(datetime.timezone.utc).isoformat()
    print('Starting timed NVIDIA request at '+started_at,flush=True)
    response=requests.post('https://integrate.api.nvidia.com/v1/chat/completions',
        headers={'Authorization':'Bearer '+key,'Content-Type':'application/json'},
        json=payload,timeout=(30,300),stream=args.stream)
    headers_s=round(time.monotonic()-start,3)
    print(f'HTTP {response.status_code} headers received after {headers_s:.3f}s',flush=True)
    if not response.ok:
        print(f'NVIDIA returned HTTP {response.status_code}: {response.text[:1500].replace(key,"[REDACTED]")}',flush=True)
        raise SystemExit(1)
    first_token_s=None
    first_answer_s=None
    if args.stream:
        content_parts=[]
        result={}
        finish_reason=None
        completed=False
        for line in response.iter_lines(chunk_size=1,decode_unicode=True):
            if not line or not line.startswith('data:'):
                continue
            event=line[5:].strip()
            if event=='[DONE]':
                completed=True
                break
            chunk=json.loads(event)
            if chunk.get('error'):
                raise RuntimeError('Streaming API error: '+json.dumps(chunk['error']))
            result.update({k:v for k,v in chunk.items() if k in ['id','model','usage'] and v is not None})
            for part in chunk.get('choices',[]):
                delta=part.get('delta',{})
                if first_token_s is None and (delta.get('content') or delta.get('reasoning_content') or delta.get('reasoning')):
                    first_token_s=round(time.monotonic()-start,3)
                    print(f'First generated token after {first_token_s:.3f}s',flush=True)
                if delta.get('content'):
                    if first_answer_s is None:
                        first_answer_s=round(time.monotonic()-start,3)
                        print(f'First answer token after {first_answer_s:.3f}s',flush=True)
                    content_parts.append(delta['content'])
                if part.get('finish_reason'):
                    finish_reason=part['finish_reason']
        if not completed and finish_reason is None:
            raise RuntimeError('Response stream ended before completion')
        content=''.join(content_parts)
        choice={'finish_reason':finish_reason}
    else:
        result=response.json()
        choice=result['choices'][0]
        content=choice['message'].get('content') or ''
    audit={'model_requested':MODEL,'model_returned':result.get('model'),'id':result.get('id'),
           'elapsed_s':round(time.monotonic()-start,2),'finish_reason':choice.get('finish_reason'),
           'usage':result.get('usage'),'content':content,
           'temperature':.2,'input':'coordinates and derived metrics only; no video or images'}
    audit.update({'started_at_utc':started_at,'http_headers_s':headers_s,
                  'first_generated_token_s':first_token_s,'first_answer_token_s':first_answer_s,
                  'stream':args.stream,'timing_scope':'HTTP request start through full response; excludes metric computation and key entry'})
    (OUT/'model_response.json').write_text(json.dumps(audit,indent=2))
    if not content.strip():
        raise RuntimeError('Model returned no visible answer; inspect model_response.json')
    (OUT/'model_coaching_report.md').write_text(
        '# Figure-skating spin analysis\n\n'
        f'Model: `{MODEL}` via NVIDIA. Source: `IMG_5943.mov`. '
        'Single coordinate-only inference; no fine-tuning.\n\n'+content+
        '\n\n---\n\nSupporting artifacts: [metrics](metrics.json), [measurement chart](pose_metrics.png), '
        '[system prompt](coach_system_prompt.md), [exact request](model_request.json), '
        '[response metadata](model_response.json).\n\nDocumentation:\n'+
        '\n'.join('- '+url for url in SOURCES)+'\n')
    print(f'Report saved. Finish reason: {audit["finish_reason"]}; elapsed: {audit["elapsed_s"]}s',flush=True)
    print(content,flush=True)


if __name__=='__main__':
    main()
