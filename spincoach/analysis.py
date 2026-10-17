"""Measurements and transparent coaching rules. No network or language model."""
from __future__ import annotations

import numpy as np

RULES_VERSION = '0.2.0'


def angle(a, b, c):
    u, v = np.asarray(a)-b, np.asarray(c)-b
    norm = np.linalg.norm(u)*np.linalg.norm(v)
    if norm < 1e-8:
        return None
    return float(np.degrees(np.arccos(np.clip(u@v/norm, -1, 1))))


def describe(values):
    good = np.array([v for v in values if v is not None and np.isfinite(v)], float)
    if not len(good):
        return {'samples': 0, 'median': None, 'q25': None, 'q75': None}
    return {'samples': len(good), 'median': round(float(np.median(good)), 3),
            'q25': round(float(np.percentile(good,25)),3),
            'q75': round(float(np.percentile(good,75)),3)}


def measure(frame):
    row = {'frame_id': frame['frame_id'], 'time_s': frame['timestamp_ms']/1000,
           'left_knee_deg': None, 'right_knee_deg': None,
           'height_proxy': None, 'body_joints_accepted': 0,
           'silhouette_aspect':frame.get('silhouette_aspect'),'flexion_evidence_deg':None}
    p = frame['landmarks']
    if not p:
        return row
    xy = np.array([[j['x_px'],j['y_px']] for j in p],float)
    q = np.array([min(j['visibility'],j['presence']) for j in p])
    row['body_joints_accepted'] = int(sum(q[11:] >= .65))
    for side,ids in [('left',[23,25,27]),('right',[24,26,28])]:
        if min(q[ids]) >= .65 and np.isfinite(xy[ids]).all():
            row[side+'_knee_deg'] = angle(*xy[ids])
    accepted=[row[k] for k in ['left_knee_deg','right_knee_deg'] if row[k] is not None]
    row['flexion_evidence_deg']=min(accepted) if accepted else None
    # This is a screen-space posture proxy, not support-foot identification.
    # Both ankles must have some visibility: taking a lone lifted foot would
    # falsely label an upright one-leg position as a crouch.
    if min(q[[11,12,23,24]]) >= .65 and min(q[[27,28]]) >= .20:
        shoulder = xy[[11,12]].mean(axis=0)
        hip = xy[[23,24]].mean(axis=0)
        torso = np.linalg.norm(shoulder-hip)
        if torso >= 8:
            ratio = (max(xy[27,1],xy[28,1])-hip[1])/torso
            if 0 < ratio < 4:
                row['height_proxy'] = float(ratio)
    return row


def rolling_median(rows, key, radius=6):
    out = []
    for i in range(len(rows)):
        window = rows[max(0,i-radius):min(len(rows),i+radius+1)]
        good = [r[key] for r in window if r.get(key) is not None]
        # Do not bridge long gaps or claim a trend from isolated estimates.
        out.append(float(np.median(good)) if len(good) >= max(3,len(window)*.4) else None)
    return out


def intervals(mask):
    result = []
    start = None
    for i, active in enumerate(list(mask)+[False]):
        if active and start is None:
            start = i
        elif not active and start is not None:
            result.append((start,i))
            start = None
    return result


def close_short_gaps(mask, max_gap):
    result = list(mask)
    for start,end in intervals([not x for x in mask]):
        if start > 0 and end < len(mask) and end-start <= max_gap:
            result[start:end] = [True]*(end-start)
    return result


def analyze(data, camera):
    fps = data['fps']
    rows = [measure(f) for f in data['frames']]
    smooth = rolling_median(rows,'silhouette_aspect',max(2,round(fps*.2)))
    flexion = rolling_median(rows,'flexion_evidence_deg',max(2,round(fps*.2)))
    valid=[v for v in smooth if v is not None]
    baseline = float(np.percentile(valid,90)) if valid else None
    threshold = baseline*.78 if baseline is not None else None
    # Require independent silhouette compactness and visible flexion together.
    # The flexed leg is NOT assumed to be the supporting leg.
    raw_low = [v is not None and threshold is not None and v < threshold and
               k is not None and k < 110 for v,k in zip(smooth,flexion)]
    filled = close_short_gaps(raw_low,round(.5*fps))
    candidates = [(a,b) for a,b in intervals(filled) if (b-a)/fps >= .7]
    main = max(candidates,key=lambda p:p[1]-p[0]) if candidates else None
    for i,r in enumerate(rows):
        r['smoothed_silhouette_aspect'] = smooth[i]
        r['phase'] = 'posture not classified'
        if main:
            a,b = main
            r['phase'] = ('lowering / approach' if i < a else
                          'lowered posture' if i < b else 'rise / transition')
    pose_n = sum(bool(f['landmarks']) for f in data['frames'])
    coverage = pose_n/max(1,len(rows))
    knee_counts = {side:sum(r[side+'_knee_deg'] is not None for r in rows) for side in ['left','right']}
    feedback = []
    segment = None
    if main:
        a,b = main
        accepted = [r['silhouette_aspect'] for r in rows[a:b] if r['silhouette_aspect'] is not None]
        desc = describe(accepted)
        segment = {'start_s':round(a/fps,2),'end_s':round(b/fps,2),
                   'duration_s':round((b-a)/fps,2),'accepted_samples':len(accepted),
                   'frame_count':b-a,'silhouette_aspect':desc,
                   'frames_with_both_cues':sum(raw_low[a:b]),
                   'interpretation':'lowered posture candidate, not a verified sit position or rotation count'}
        feedback.append({'id':'LOW_POSITION_PRESENT','kind':'positive',
            'start_s':segment['start_s'],'end_s':segment['end_s'],'confidence':'moderate',
            'title':'A sustained lower position is detected',
            'observation':f"A compact silhouette and visible knee-flexion evidence identify a lower-position candidate from {a/fps:.2f} to {b/fps:.2f} s ({(b-a)/fps:.2f} s).",
            'interpretation':'This supports a sustained lower-position section, with short uncertain gaps merged.',
            'action':'Keep this low-position section as the reference when comparing your next attempt.',
            'evidence':{'metric':'silhouette_aspect_and_visible_flexion','silhouette_threshold':threshold,'knee_angle_max':110,'frames_with_both_cues':sum(raw_low[a:b]),'accepted_silhouette_samples':len(accepted)},
            'limitation':'A moving camera and hidden ankles affect this proxy; it does not establish legal sit depth.'})
        feedback.append({'id':'CHECK_DEPTH_THROUGH_ROTATIONS','kind':'review',
            'start_s':segment['start_s'],'end_s':segment['end_s'],'confidence':'moderate',
            'title':'Check that the intended depth lasts through each turn',
            'observation':f"A lowered section is present, but reliable knee angles are available in only {knee_counts['left']} left and {knee_counts['right']} right frames across the clip.",
            'interpretation':'The tracker cannot establish uninterrupted depth as the legs overlap.',
            'action':'Review the marked low-section frames. Check the skating thigh from the clearest side views and aim to keep the intended shape before rising.',
            'evidence':{'metric':'knee_angle_coverage','left_samples':knee_counts['left'],'right_samples':knee_counts['right']},
            'limitation':'Occlusion is a measurement issue, not evidence that you lost the position.'})
        tail = [v for v in smooth[b:] if v is not None]
        if len(tail) >= fps*.2 and desc['median'] is not None and np.median(tail) > desc['median']*1.15:
            feedback.append({'id':'RISE_DETECTED','kind':'positive',
                'start_s':round(b/fps,2),'end_s':round(len(rows)/fps,2),'confidence':'moderate',
                'title':'A rise out of the lower position is detected',
                'observation':'The body silhouette becomes taller relative to its width after the compact section.',
                'interpretation':'This is consistent with a change toward a taller position.',
                'action':'Review the transition for a deliberate rise while keeping the arms and free leg controlled; smoothness is not established by this proxy.',
                'evidence':{'metric':'silhouette_aspect','low_median':desc['median'],'later_median':round(float(np.median(tail)),3)},
                'limitation':'This does not verify balance, blade contact, or a clean exit.'})
    else:
        feedback.append({'id':'POSITION_UNCERTAIN','kind':'review','start_s':0,
            'end_s':round(len(rows)/fps,2),'confidence':'low','title':'Low-position hold could not be isolated reliably',
            'observation':'Silhouette compactness and knee-flexion evidence did not yield a sufficiently long joint interval.',
            'interpretation':'This can result from the position, camera view, or ankle occlusion.',
            'action':'Use the evidence frames to check the intended shape; record another clip with the whole body visible.',
            'evidence':{'metric':'silhouette_aspect_and_visible_flexion','accepted_samples':len(valid)},
            'limitation':'This is not a failure or invalid-spin call.'})
    camera_moving = camera.get('estimated_motion_frame_widths',0) > .12 or camera.get('total_abs_rotation_deg',0) > 5
    feedback.append({'id':'FILM_FOR_CENTERING','kind':'recording','start_s':0,
        'end_s':round(len(rows)/fps,2),'confidence':'moderate' if camera.get('accepted_pairs',0)>10 else 'low',
        'title':'Use a fixed camera to judge centering and rotation quality',
        'observation':('Background feature tracking detects camera movement.' if camera_moving else
                       'The video is not calibrated to the ice surface.'),
        'interpretation':'The skater moving across the image is not by itself proof that the spin travels.',
        'action':'For the next comparison, film from one fixed place with both skates and nearby ice markings visible.',
        'evidence':camera,'limitation':'The current pipeline does not measure blade edges, revolutions, RPM, or ice-relative centering.'})
    headline = ('A sustained low section and a rise are detected; depth consistency remains the main video-review question.'
                if main and any(f['id']=='RISE_DETECTED' for f in feedback) else
                'A lower-position section is detected; check its depth and continuity in the evidence frames.' if main else
                'Tracking supports a posture review, but a reliable low-position hold was not isolated.')
    return {'schema_version':1,'rules_version':RULES_VERSION,'analysis_method':'local MediaPipe + OpenCV + transparent rules',
            'headline':headline,'overall_grade':None,'grade_reason':'No validated quality model or expert-labelled reference set.',
            'source':data['source'],'fps':fps,'duration_s':round(len(rows)/fps,3),
            'tracking':{'frames':len(rows),'poses':pose_n,'pose_coverage_pct':round(coverage*100,1),
                        'left_knee_accepted_frames':knee_counts['left'],'right_knee_accepted_frames':knee_counts['right']},
            'lowered_segment':segment,'camera':camera,'feedback':feedback,
            'rules':{'joint_visibility_and_presence_min':.65,'ankle_visibility_for_posture_proxy_min':.20,
                     'silhouette_mask_threshold':.6,'silhouette_low_relative_to_recording_q90':.78,
                     'visible_flexion_max_deg':110,'min_lowered_interval_s':.7,
                     'maximum_gap_closed_s':.5,'thresholds_are':'prototype heuristics, not validated judging criteria'},
            'not_assessed':['official spin score or level','legal sit-position depth','support-foot identity',
                            'blade edge or ice contact','rotation count or RPM','ice-relative centering'],
            'frames':rows}
