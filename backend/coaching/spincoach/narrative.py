"""Readable prototype coaching reports, with an optional bounded NVIDIA rewrite."""
from __future__ import annotations

import json
import hashlib
import math
from pathlib import Path


def local_assessment(result):
    """A short disclosed local assessment; no API-generated text is claimed."""
    segment=result.get('lowered_segment')
    if not segment:
        return ('A sustained low-position hold could not be identified reliably. Camera view and occlusion may explain this.\n\n'
                'Review whether the skating knee, free leg and arms retain your intended shape in comparable views.\n\n'
                'Next attempt: film the full body from a fixed position before changing technique based on these estimates.')
    start,end=segment['start_s'],segment['end_s']
    return '\n\n'.join([
        f'A lower-posture candidate is detected at {start:.1f}–{end:.1f}s, lasting {segment["duration_s"]:.1f}s.',
        'If holding one shape was intended, compare knee bend and free-leg height in matching body orientations.',
        f'Around {end:.1f}s, review how the arms and free leg coordinate with the posture change.',
        'Next attempt: rehearse a repeatable shape and film from a fixed spot. These measurements do not establish an official score.'
    ])


PROMPT = '''Act as an attentive figure-skating coach reviewing one spin for a hackathon prototype. Give useful, position-specific feedback in second person. You receive timestamped pose summaries and, when available, pairs of raw video crops with timestamps. The crops show the same skater at different orientations; they are not continuous playback.

Write an overall impression in 2–3 sentences, then one short section per approximately one-second interval in the supplied timeline (e.g. "0–1 s — settle the entry"). Cover every interval including the final partial second. Within each section use 3–5 connected sentences addressing:
1. Feet and legs: the visible skating-knee bend, where the free knee/foot sits relative to the body, whether the visible leg shape looks intentional, and a practical improvement if warranted.
2. Arms and upper body: arm reach, elbow bend, wrist/hand height, shoulder/torso organization, and how they coordinate with that leg position or transition.
3. One short mental image/cue the skater can think during that second, with a concrete meaning. Examples only: "free foot on a shelf" for holding a chosen free-foot height, "carry a round tray" for maintaining the chosen arm shape, "ride an elevator" for a gradual rise. Choose images that fit the actual visible position; do not force these examples or turn every section into unrelated metaphors. Explain the cue briefly.

Be specific about what looks good and what could be improved. Distinguish "in this crop your arm is..." from "try..." advice. Do not label a posture a mistake merely because it differs from another second: position changes and bent free-leg variations may be intentional. If the free leg is deliberately tucked, do not automatically demand that it straighten. Forward torso lean can be correct in a sit position; do not demand an upright torso throughout. If a limb is obscured, say so briefly and emphasize the visible parts. Avoid repeating identical advice in each interval.

Use the supplied timestamps and relative positions; quote few numerical angles. Never infer a blade edge, toe-pick engagement, exact pressure distribution, foot-to-ice contact, physical strength, injury risk, exact rotation count, RPM, legal sit depth, official GOE or formal judging score. Do not call angle fluctuations wobble or uneven weight without visible corroboration: viewpoint, rotation and tracking errors affect them. Do not call a transition jerky or abrupt from sparse still frames alone. Only name the left/right supporting foot if it is visually unambiguous; otherwise use "skating leg" and "free leg" with uncertainty when needed.

Visual grounding matters more than a conventional story of how a spin should finish. The final frame may still show an upright spin with a tucked/crossed free leg and closed arms; do not automatically describe an extended leg behind or open arms because the clip is ending. Describe the image that is actually supplied. A forward free-leg shape and a tucked free-leg shape are different: do not prescribe pulling a forward free foot to the hip merely to make it "compact". Do not infer elbow tension, strength, or edge quality from stills. Do not prescribe either a horizontal torso or a fully upright torso as a universal sit-spin correction. A hidden/cropped hand is not necessarily a lowered or asymmetric arm. When uncertain, use a useful observation-check and a cue that does not assume the unverified fault.

Cues must preserve the chosen position. When arms are reaching forward, "carry a tray in front" should mean maintaining that reach, not squeezing them to the chest. Do not tell the skater to tuck the free leg during a deliberate forward extension. Avoid "lock the ankle", "lock the arms", "rigid core", "every limb as close as possible", and maximizing speed as blanket instructions. Prefer soft, organized positions, chosen free-foot height, and coordinated changes. Call the final interval a rise/upright position when the crops still show spinning; do not claim a completed exit.

Finish with the two most useful priorities and a simple short mental rehearsal for the next attempt. Aim for 650–850 words, accessible coaching language, timestamped sections and no tables. Keep one short prototype caveat at the end rather than burying the critique in disclaimers. No images means coordinate-only interpretation; do not pretend images or continuous motion were observed.
Evidence:
'''


def position_features(frame):
    """Screen-space limb relationships, accepted only when required joints are reliable."""
    import numpy as np
    from spincoach.analysis import angle
    p=frame.get('landmarks',[])
    if not p:
        return {}
    xy=np.array([[j['x_px'],j['y_px']] for j in p])
    q=np.array([min(j['visibility'],j['presence']) if math.isfinite(j['visibility']) and math.isfinite(j['presence']) else 0 for j in p])
    shoulder=xy[[11,12]].mean(axis=0);hip=xy[[23,24]].mean(axis=0)
    torso=float(np.linalg.norm(shoulder-hip))
    normalized=min(q[[11,12,23,24]])>=.65 and np.isfinite(torso) and torso>=8
    out={}
    def joint_angle(ids):
        if not np.isfinite(q[list(ids)]).all() or min(q[list(ids)])<.65 or not np.isfinite(xy[list(ids)]).all():
            return None
        a,b,c=xy[list(ids)]
        if min(np.linalg.norm(a-b),np.linalg.norm(c-b))<3:
            return None
        return angle(a,b,c)
    for side,ids in [('left',(11,13,15,23,25,27,29,31)),('right',(12,14,16,24,26,28,30,32))]:
        s,e,w,h,k,a,heel,toe=ids
        for name,indices in [('elbow',(s,e,w)),('knee',(h,k,a)),
                             ('hip',(s,h,k)),('shoulder',(h,s,e)),('ankle',(k,a,toe))]:
            value=joint_angle(indices)
            if value is not None:
                out[side+'_'+name+'_deg']=value
        if normalized and min(q[[s,w]])>=.65:
            out[side+'_wrist_height_above_shoulder_torso']=(xy[s,1]-xy[w,1])/torso
            out[side+'_arm_reach_torso']=float(np.linalg.norm(xy[w]-xy[s])/torso)
        if normalized and min(q[[h,k,a]])>=.65:
            out[side+'_ankle_height_below_hip_torso']=(xy[a,1]-xy[h,1])/torso
            out[side+'_knee_height_below_hip_torso']=(xy[k,1]-xy[h,1])/torso
        if normalized and min(q[[a,heel,toe]])>=.65:
            out[side+'_toe_dx_from_heel_torso']=(xy[toe,0]-xy[heel,0])/torso
            out[side+'_toe_dy_from_heel_torso']=(xy[toe,1]-xy[heel,1])/torso
        if normalized and q[a]>=.65:
            out[side+'_ankle_x_from_body_torso']=(xy[a,0]-hip[0])/torso
            out[side+'_ankle_y_from_body_torso']=(xy[a,1]-hip[1])/torso
    if normalized:
        out['torso_lean_from_screen_vertical_deg']=angle(shoulder,hip,hip+np.array([0.,-1.]))
    if normalized and min(q[[15,16]])>=.65:
        out['wrist_separation_torso']=float(np.linalg.norm(xy[15]-xy[16])/torso)
    return {name:float(value) for name,value in out.items() if value is not None and np.isfinite(value)}


def compact_evidence(result,pose_data=None):
    from spincoach.kinematics import build_kinematics
    quantitative=result.get('kinematics') or (build_kinematics(pose_data,result) if pose_data else None)
    windows=[]
    frames=result['frames']
    raw_features=[(f['timestamp_ms']/1000,position_features(f)) for f in pose_data['frames']] if pose_data else []
    for second in range(max(1,math.ceil(result['duration_s']))):
        window=[r for r in frames if second<=r['time_s']<second+1]
        stats={}
        for side in ['left','right']:
            values=sorted(r[side+'_knee_deg'] for r in window if r.get(side+'_knee_deg')is not None)
            stats[side]={'accepted_samples':len(values),'median_image_angle_deg':round(values[len(values)//2]) if values else None}
        features=[f for t,f in raw_features if second<=t<second+1]
        limb_stats={}
        for name in sorted({k for f in features for k in f}):
            values=sorted(f[name] for f in features if f.get(name)is not None)
            if values:
                n=len(values);med=values[n//2] if n%2 else (values[n//2-1]+values[n//2])/2
                limb_stats[name]={'median':round(float(med),3),'accepted_samples':n}
        windows.append({'time_s':[second,min(second+1,result['duration_s'])],'knees':stats,
                        'arm_leg_foot_relationships':limb_stats,
                        'quantitative':quantitative['windows'][second] if quantitative else None})
    return {'source':result.get('original_source',result.get('source')),
            'duration_s':result['duration_s'],'lowered_posture_candidate':result.get('lowered_segment'),
            'tracking':result['tracking'],'time_windows':windows,
            'observations':[{'time_s':[f['start_s'],f['end_s']],'observation':f['observation']} for f in result['feedback']],
            'metric_definitions':{'torso':'2D shoulder-midpoint to hip-midpoint length; normalized distances change with viewpoint',
                'elbow_deg':'shoulder-elbow-wrist internal angle; 180 is straight',
                'wrist_height_above_shoulder_torso':'positive means wrist higher on screen than same-side shoulder',
                'ankle_height_below_hip_torso':'positive means ankle lower on screen than same-side hip',
                'toe_dx_dy_from_heel':'screen direction of visible foot landmarks; does not establish blade edge or ice pressure',
                'anatomical_labels':'MediaPipe left/right may swap when occluded; supporting leg is not identified by these summaries'},
            'context':'Main skater performing a spinning sequence. Position type is not formally verified. Camera moves; image angles change with viewpoint.'}


def prepare_visual_evidence(folder,result,pose_data,intervals=None):
    """Two timestamped full-body crops per second, paired to show changes of view."""
    import cv2
    import numpy as np
    folder=Path(folder)
    video=folder/'input.mp4'
    if not video.is_file() or not pose_data:
        return []
    cap=cv2.VideoCapture(str(video))
    panels=[]
    try:
        intervals=intervals if intervals is not None else [{'time_s':[s,min(s+1,result['duration_s'])]} for s in range(max(1,math.ceil(result['duration_s'])))]
        for second,interval in enumerate(intervals):
            begin,end=interval['time_s']
            times=[max(begin,min(begin+(end-begin)*offset,result['duration_s']-.05)) for offset in [.25,.75]]
            tiles=[];actual=[]
            for t in sorted(set(times)):
                idx=min(len(pose_data['frames'])-1,round(t*pose_data['fps']))
                cap.set(cv2.CAP_PROP_POS_FRAMES,idx)
                ok,frame=cap.read()
                if not ok:
                    continue
                record=pose_data['frames'][idx];h,w=frame.shape[:2]
                bbox=record.get('bbox_xywh_px')
                if bbox:
                    x,y,bw,bh=bbox
                    x0=max(0,int(x-.35*bw));x1=min(w,int(x+1.35*bw))
                    y0=max(0,int(y-.2*bh));y1=min(h,int(y+1.45*bh))
                    crop=frame[y0:y1,x0:x1]
                    if not crop.size:
                        crop=frame
                else:
                    crop=frame
                tile=np.full((640,480,3),24,np.uint8)
                ch,cw=crop.shape[:2];scale=min(456/cw,580/ch)
                resized=cv2.resize(crop,(max(1,round(cw*scale)),max(1,round(ch*scale))))
                rh,rw=resized.shape[:2];left=(480-rw)//2
                tile[48:48+rh,left:left+rw]=resized
                stamp=record['timestamp_ms']/1000
                cv2.putText(tile,f'{stamp:.2f} seconds',(18,31),cv2.FONT_HERSHEY_SIMPLEX,.7,(240,240,240),2,cv2.LINE_AA)
                tiles.append(tile);actual.append(stamp)
            if tiles:
                pair=np.concatenate(tiles,axis=1)
                path=folder/f'coaching_frames_{second:02d}.jpg'
                cv2.imwrite(str(path),pair,[cv2.IMWRITE_JPEG_QUALITY,85])
                panels.append({'path':path.name,'timestamps_s':actual,
                               'time_interval_s':[begin,end]})
    finally:
        cap.release()
    (folder/'coaching_frames.json').write_text(json.dumps(panels,indent=2))
    return panels


def write_assessment(result, folder, key=None, timeout_s=75, model='nvidia/nemotron-3.5-super-vl-120b-a12b',gemini_key=None,gemini_model='gemini-3.5-flash'):
    if result.get('element_analysis') and (key or gemini_key):
        from spincoach.coaching import generate_coaching_report
        return generate_coaching_report(result,folder,key,gemini_key,model,gemini_model,timeout_s)
    if key:
        from spincoach.timeline_report import generate_timeline
        return generate_timeline(result,folder,key,model,timeout_s)
    if result.get('element_analysis'):
        from spincoach.element_feedback import local_element_assessment
        return local_element_assessment(result)
    folder=Path(folder)
    content=local_assessment(result)
    provenance={'generator':'local coaching narrative','model':None,'api_calls':0,
                'elapsed_s':0,'status':'local','source':'analysis.json'}
    pose_path=folder/'landmarks.json'
    pose_data=json.loads(pose_path.read_text()) if pose_path.is_file() else None
    evidence=compact_evidence(result,pose_data)
    notes_path=folder/'visual_notes.json'
    notes_used=False
    if notes_path.is_file():
        notes=json.loads(notes_path.read_text())
        source=Path(result.get('original_source',result.get('source','')))
        if source.is_file() and notes.get('source_sha256')==hashlib.sha256(source.read_bytes()).hexdigest():
            evidence['reviewer_visual_observations']={k:v for k,v in notes.items() if k!='source_sha256'}
            evidence['reviewer_note_instruction']='These notes were checked against the supplied crops. Use their observed body positions for the corresponding interval. Do not replace them with a generic entry/exit story. Advice may be your own, but claimed visible positions must agree with these notes or be described as uncertain.'
            notes_used=True
        else:
            provenance['reviewer_notes_ignored']='Source-video checksum missing or different; notes may belong to another clip.'
    provenance['reviewer_visual_notes_used']=bool(notes_used and key)
    panels=prepare_visual_evidence(folder,result,pose_data) if key else []
    evidence['attached_frame_pairs']=panels
    prompt=PROMPT+json.dumps(evidence,separators=(',',':'))
    (folder/'coaching_prompt.txt').write_text(prompt)
    provenance['content']=content
    (folder/'coaching_assessment.json').write_text(json.dumps(provenance,indent=2))
    (folder/'coaching_report.md').write_text('# Spin coaching assessment\n\n'+content+
        '\n\n---\nHackathon prototype coaching interpretation; not an official judging score.\n\n'
        +(('The model received measured pose summaries and timestamped raw video crops. Still frames do not establish blade pressure, edges, or motion smoothness.\n\n' if panels else 'The model received measured pose summaries, not video frames. Its technique interpretations are unverified.\n\n') if provenance['generator']=='NVIDIA language model' else '')+
        ('Inputs also include assistant-reviewed position notes in [visual_notes.json](visual_notes.json); these notes are separate from automated measurements.\n\n' if notes_used and key else '')+
        f"Generated by: {provenance['generator']}. "+
        (f"Model request time: {provenance['elapsed_s']} seconds.\n\n" if provenance['api_calls'] else
         'No model API was called.\n\n')+
        '[Video](feedback.mp4) · [Evidence and measurements](report.md) · [Generation details](coaching_assessment.json)\n')
    return provenance
