"""Numerical evidence for coaching. These are projected angles, not judging targets."""
from __future__ import annotations

import math
import re

import numpy as np


DEFINITIONS = {
    'knee_deg':'Hip-knee-ankle internal angle; closer to 180 means straighter in the image.',
    'elbow_deg':'Shoulder-elbow-wrist internal angle; closer to 180 means straighter in the image.',
    'hip_deg':'Shoulder-hip-knee internal angle in the image.',
    'shoulder_deg':'Hip-shoulder-elbow internal angle in the image.',
    'ankle_deg':'Knee-ankle-toe internal angle in the image; not blade pitch or contact.',
    'torso_lean_from_screen_vertical_deg':'Hip-to-shoulder line relative to screen vertical; includes camera tilt.',
    'torso':'Shoulder-midpoint to hip-midpoint length in the image; normalized distances are ratios, not metres.',
}
NOTE = ('All angles are 2D image-plane estimates. Visibility/presence >= 0.65 is a filter, not a calibrated accuracy guarantee. '
        'Rotation, occlusion and camera tilt affect them. L/R are MediaPipe labels, not confirmed support/free-leg identities. '
        'No expert reference or intended spin type is supplied, so no universal ideal angles or technique deductions are assigned.')


def label(name):
    return name.removesuffix('_deg').replace('torso_lean_from_screen_vertical','torso lean from screen vertical').replace('_',' ')


def _view(frame):
    """Signed shoulder/hip vectors approximate projected view; not a 3D orientation."""
    p=frame.get('landmarks',[])
    if not p or any(not math.isfinite(p[i][key]) or p[i][key]<.65
                    for i in [11,12,23,24] for key in ['visibility','presence']):
        return None
    xy=np.array([[p[i]['x_px'],p[i]['y_px']] for i in [11,12,23,24]],float)
    torso=np.linalg.norm(xy[:2].mean(axis=0)-xy[2:].mean(axis=0))
    if torso<8 or not np.isfinite(xy).all():
        return None
    return np.concatenate([(xy[1]-xy[0])/torso,(xy[3]-xy[2])/torso])


def _comparisons(records, rows, index, metric):
    """Pair nearby, same-phase frames with similar projected torso orientation.

    Pairs are disjoint to avoid counting adjacent frames repeatedly. They are
    review candidates: the same phase/view does not prove the intended shape.
    """
    pairs=[];used=set()
    for i in index:
        a=records[i]
        if i in used or metric not in a['values'] or a['_view'] is None or rows[i].get('phase')!='lowered posture':
            continue
        options=[]
        for j,b in enumerate(records):
            dt=a['time_s']-b['time_s']
            if j in used or not .4<=dt<=2 or metric not in b['values'] or b['_view'] is None:
                continue
            if rows[i].get('phase')!=rows[j].get('phase'):
                continue
            distance=float(np.max(np.abs(a['_view']-b['_view'])))
            if distance<=.10:
                options.append((distance,j))
        if options:
            _,j=min(options)
            b=records[j]
            pairs.append({'earlier_s':b['time_s'],'later_s':a['time_s'],
                          'earlier_value':round(b['values'][metric],1),
                          'later_value':round(a['values'][metric],1),
                          'absolute_delta':round(abs(a['values'][metric]-b['values'][metric]),1)})
            used.update([i,j])
    if len(pairs)<3:
        return None
    return {'pairs':len(pairs),'median_absolute_delta':round(float(np.median([p['absolute_delta'] for p in pairs])),1),
            'example':min(pairs,key=lambda p:abs(p['absolute_delta']-np.median([x['absolute_delta'] for x in pairs]))),
            'interpretation':'Similar projected torso views in the same detected phase; intended limb shape and anatomical label continuity are not verified.'}


def build_kinematics(data,result):
    from spincoach.narrative import position_features
    records=[{'time_s':f['timestamp_ms']/1000,'values':position_features(f),'_view':_view(f)} for f in data['frames']]
    rows=result['frames']
    windows=[]
    for second in range(max(1,math.ceil(result['duration_s']))):
        index=[i for i,r in enumerate(records) if second<=r['time_s']<second+1]
        stats={}
        for metric in sorted({k for i in index for k in records[i]['values']}):
            values=[records[i]['values'][metric] for i in index if records[i]['values'].get(metric) is not None
                    and np.isfinite(records[i]['values'][metric])]
            if not values:
                continue
            deg=metric.endswith('_deg');precision=1 if deg else 3
            coverage=100*len(values)/max(1,len(index))
            stats[metric]={'median':round(float(np.median(values)),precision),
                'p25':round(float(np.percentile(values,25)),precision),
                'p75':round(float(np.percentile(values,75)),precision),
                'accepted_frames':len(values),'total_frames':len(index),'coverage_pct':round(coverage,1),
                'unit':'deg' if deg else 'torso lengths',
                'usable_for_feedback':len(values)>=max(4,math.ceil(len(index)*.5)),
                'similar_view_comparison':_comparisons(records,rows,index,metric) if deg and len(values)>=4 else None}
            stats[metric]['iqr_width']=round(stats[metric]['p75']-stats[metric]['p25'],precision)
        # Give the model a small set spanning legs, arms and upper-body posture.
        choices=[]
        for names in [['left_knee_deg','right_knee_deg'],['left_elbow_deg','right_elbow_deg'],
                      ['torso_lean_from_screen_vertical_deg'],['left_hip_deg','right_hip_deg'],
                      ['left_ankle_deg','right_ankle_deg']]:
            good=[m for m in names if stats.get(m,{}).get('usable_for_feedback')]
            if good:
                choices.append(max(good,key=lambda m:stats[m]['accepted_frames']))
        cards=[]
        for number,metric in enumerate(choices,1):
            stat=stats[metric]
            text=f"{label(metric)} median {stat['median']:g} deg"
            detail=(f"{text}; middle 50% {stat['p25']:g}-{stat['p75']:g} deg; "
                    f"{stat['accepted_frames']}/{stat['total_frames']} accepted frames ({stat['coverage_pct']:g}%)")
            cards.append({'id':f'M{number}','metric':metric,'token':'{M'+str(number)+'}',
                          'short_text':text,'detail':detail,**stat})
            if 'elbow' in metric:
                cards[-1]['geometry_note']=('The projected elbow is relatively extended; asking for extra straightness is not justified by this median.'
                    if stat['median']>=155 else 'The projected elbow is bent. Bent arms can be intentional; this is not a fault without an intended-position reference.')
            elif 'torso_lean' in metric:
                cards[-1]['geometry_note']='Lean is relative to screen vertical, not the ice; it cannot establish forward versus lateral lean or balance.'
            else:
                cards[-1]['geometry_note']='This describes joint geometry only. No supporting-leg identity, ideal target or technique fault is established.'
        windows.append({'time_s':[second,min(second+1,result['duration_s'])],
                        'frame_count':len(index),'metrics':stats,'cards':cards})
    return {'version':'1.0','method':'confidence-filtered 2D joint geometry',
            'definitions':DEFINITIONS,'limitations':NOTE,
            'comparison_policy':'Within-clip repeatability checks, never a best-technique baseline. Similar projected views can still have different intended shapes.',
            'windows':windows,'frames':[{'time_s':r['time_s'],'values':r['values']} for r in records]}


def references_card(text,card,allow_range=False):
    if card['token'] in text:
        return True
    name=label(card['metric']).replace(' from screen vertical','')
    # A direct numeric citation must name this metric and quote its median.
    name_pattern=re.escape(name).replace(r'\ from\ screen\ vertical',r'\ from\ (?:the\ )?screen\ vertical')
    names=bool(re.search(name_pattern,text,re.I))
    if 'torso lean' in name:
        names=bool(re.search(r'torso lean',text,re.I))
    values=[card['median']]
    if allow_range:
        values.extend([card['p25'],card['p75'],card.get('iqr_width',card['p75']-card['p25'])])
    return names and any(abs(float(value)-real)<=.51 for real in values
                        for value in re.findall(r'(?<![\w.])-?\d+(?:\.\d+)?',text))


def coaching_focus(window):
    cards=window['cards']
    if not cards:
        return {'instruction':'No reliable measured correction is available. Ask for a clearer full-body recording.'}
    variable=[c for c in cards if ('knee' in c['metric'] or 'hip' in c['metric'])
              and c['coverage_pct']>=70 and c['iqr_width']>=20]
    extended=[c for c in cards if 'elbow' in c['metric'] and c['median']>=155]
    if variable:
        card=max(variable,key=lambda c:c['iqr_width'])
        instruction=('Discuss this measured middle-half spread, not whether the median falls inside its own range. '
                     'Ask whether this was a deliberate position change. If an unchanged hold was intended, '
                     'suggest reviewing knee/hip height in comparable body orientations and rehearsing the chosen bend through the turn. '
                     'Do not call the spread a confirmed fault or prescribe the observed range as an ideal target.')
    elif extended:
        card=max(extended,key=lambda c:c['coverage_pct'])
        instruction=('This elbow is already relatively extended. Explicitly say that extra straightening is not supported. '
                     'For an intended hold, suggest preserving the chosen reach with a soft elbow and checking matching views. '
                     'Do not infer tension, claim collapse, or demand symmetry.')
    else:
        card=max(cards,key=lambda c:c['coverage_pct'])
        instruction=('No clear measured fault is established. Discuss the measurement with its limitations. '
                     'For an intended hold, give a specific body-position check, not a guaranteed correction. '
                     'If limb coverage is incomplete, prioritize verifying those limbs in a clear view before changing technique.')
    return {'metric':label(card['metric']),'median_deg':card['median'],
            'middle_half_width_deg':card['iqr_width'],'instruction':instruction,
            'selection_policy':'Review prioritization only; the range threshold is not a fault/quality cutoff.'}


def response_problems(content,window):
    """Validate numeric citations against the supplied computed facts."""
    cards={c['token']:c for c in window['cards']}
    problems=[]
    numeric=re.sub(r'\{M\d+\}','',content)
    allowed=[.65,50,*window['time_s']]
    angles=[]
    for card in cards.values():
        for key in ['median','p25','p75','accepted_frames','total_frames','coverage_pct']:
            allowed.append(card[key])
        allowed.append(card.get('iqr_width',card['p75']-card['p25']))
        angles.extend(card[k] for k in ['median','p25','p75'])
        angles.append(card.get('iqr_width',card['p75']-card['p25']))
        comparison=card.get('similar_view_comparison')
        if comparison:
            allowed.extend([comparison['pairs'],comparison['median_absolute_delta'],*comparison['example'].values()])
            angles.extend([comparison['median_absolute_delta'],comparison['example']['earlier_value'],comparison['example']['later_value']])
    numbers=[float(x) for x in re.findall(r'(?<![\w.])-?\d+(?:\.\d+)?',numeric.replace('–',' ').replace('—',' '))]
    if any(not any(abs(value-real)<=.51 for real in allowed) for value in numbers):
        problems.append('A numeric value is absent from the supplied measurements; copy the actual median/range, or use a measurement token.')
    degree_values=[float(x) for x in re.findall(r'(?<![\w.])(\d+(?:\.\d+)?)\s*(?:deg(?:rees?)?|°)',numeric,re.I)]
    if any(not any(abs(value-real)<=.51 for real in angles) for value in degree_values):
        problems.append('A quoted angle is absent from the supplied angle measurements.')
    tokens=set(re.findall(r'\{M\d+\}',content))
    if tokens-set(cards):
        problems.append('A measurement token does not exist in these facts.')
    if sum(references_card(content,c) for c in cards.values())<min(2,len(cards)):
        problems.append('Cite two different supplied measurement-card medians with their joint names, or use the corresponding tokens.')
    advice=re.search(r'^Advice:\s*(.*?)(?=\n\s*\w+:|\Z)',content,re.M|re.S)
    if cards and advice and not any(references_card(advice.group(1),c,allow_range=True) for c in cards.values()):
        problems.append('Link Advice to a named measured median/range/width (or token), rather than giving a generic cue.')
    if advice and re.search(r'falls?\s+within',advice.group(1),re.I):
        problems.append('Do not say the median falls within its own middle-half range; discuss the range width and a conditional practice/review action.')
    if re.search(r'\btension\b',content,re.I):
        problems.append('Muscle tension is not measured; suggest a visible position check instead.')
    if any(re.search(r'%|coverage|availability',sentence,re.I) and re.search(r'consisten|stabil|steady',sentence,re.I)
           for sentence in re.split(r'(?<=[.!?])\s+',content)):
        problems.append('Frame availability/coverage does not establish position stability; do not use it as proof of a steady hold.')
    banned=r'\block(?:ed|ing)?\b|\b(?:fully|completely)\s+(?:straighten|extend)|\b(?:ideal|optimal|perfect)\s+angle'
    for match in re.finditer(banned,content,re.I):
        prefix=content[max(0,match.start()-45):match.start()]
        if re.search(r"(?:\bwithout|\bavoid|\bnever|\bnot|\bdon't|\bno need)\s+(?:\w+\s+){0,3}$",prefix,re.I):
            continue
        problems.append('Do not lock joints, demand full extension, or invent an ideal angle.')
        break
    for field in ['Observation:','Advice:','Cue:','Caption:']:
        if field not in content:
            problems.append('Missing '+field)
    return problems


def format_response(raw,window):
    """Retain raw response separately and insert only computed measurement values."""
    content=raw
    for card in window['cards']:
        content=content.replace(card['token'],card['short_text'])
    measured='\n'.join('- '+card['detail'] for card in window['cards']) or 'Not enough reliable frames for numeric technique feedback in this interval.'
    comparisons=[]
    for card in window['cards']:
        comparison=card.get('similar_view_comparison')
        if comparison:
            example=comparison['example']
            comparisons.append(f"{label(card['metric'])}: median absolute difference {comparison['median_absolute_delta']:g} deg over {comparison['pairs']} frame pairs with similar projected views; "
                               f"example {example['earlier_s']:.2f}s ({example['earlier_value']:g} deg) versus {example['later_s']:.2f}s ({example['later_value']:g} deg).")
    if comparisons:
        measured+='\n\nRepeatability evidence (review candidates, not confirmed faults):\n'+'\n'.join('- '+s for s in comparisons)
    # Compact top line always carries a real measurement; the model supplies the cue.
    caption=re.search(r'^Caption:\s*(.+)',content,re.M)
    if window['cards'] and caption:
        advice=re.search(r'^Advice:\s*(.*?)(?=\n\s*\w+:|\Z)',raw,re.M|re.S)
        card=next((c for c in window['cards'] if advice and references_card(advice.group(1),c,allow_range=True)),window['cards'][0])
        name=label(card['metric']).replace(' from screen vertical','').capitalize()
        top=f"{name}: {card['median']:g} deg (median)"
        parts=caption.group(1).split('|',1)
        cue=parts[-1].strip()
        content=content[:caption.start(1)]+top+' | '+cue+content[caption.end(1):]
    return 'Measured evidence:\n'+measured+'\n\n'+content
