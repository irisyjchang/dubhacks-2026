"""User-confirmed elements, conservative motion suggestions and ISU-linked review."""
from __future__ import annotations

import math

import numpy as np


ELEMENTS = {
    'unknown':{'label':'Not sure / general skating','family':'unknown',
               'checks':['Describe visible body positions only.','Do not assume that skating across the rink is a spin or jump.']},
    'spin':{'label':'Spin — type unconfirmed','family':'spin',
            'checks':['Review the chosen arm/free-leg shape in matching orientations.','Distinguish intentional position changes from an intended hold.']},
    'upright_spin':{'label':'Upright spin','family':'spin',
                    'checks':['Review the intended tall body shape and chosen arm/free-leg position.','Do not demand straight arms or a particular free-leg variation.']},
    'sit_spin':{'label':'Sit spin','family':'spin',
                'checks':['Look for a sustained lowered posture with visible knee flexion.','Review depth and the chosen free-leg/arm shape during an intended hold.','A compact silhouette does not verify legal sit depth.']},
    'camel_spin':{'label':'Camel spin','family':'spin',
                  'checks':['Review the forward torso and extended free-leg line from clear side views.','Do not demand an upright torso or pull an intentionally extended free leg inward.']},
    'jump':{'label':'Jump — type unconfirmed','family':'jump',
            'checks':['Review preparation, takeoff, flight and landing only where identifiable.','Review visible knee/hip bending and arm coordination around the marked events.','Do not identify blade edges, supporting foot or rotation count from these pose summaries.']},
    'waltz_jump':{'label':'Waltz jump','family':'jump',
                  'checks':['Review preparation and the transition to the user-marked flight interval.','Review visible body organization and knee flexion around the marked landing.','The selected label does not verify takeoff edge, jump rotation or a correct landing.']},
}
RUBRIC_STATUS = 'Selected ISU 2026–27 singles criteria with explicit evidence limits; not official scoring.'


def validate_markers(element,markers,duration):
    if element not in ELEMENTS:
        raise ValueError('Choose a supported element or Not sure.')
    if not isinstance(markers,dict):
        raise ValueError('Phase markers must be an object.')
    family=ELEMENTS[element]['family']
    allowed={'takeoff_s','landing_s'} if family=='jump' else {'hold_start_s','hold_end_s'} if family=='spin' else set()
    if set(markers)-allowed:
        raise ValueError('These phase markers do not match the selected element.')
    if not markers:
        return {}
    if set(markers)!=allowed:
        raise ValueError('Provide both phase times, or leave both blank.')
    try:
        parsed={key:float(value) for key,value in markers.items()}
    except (ValueError,TypeError):
        raise ValueError('Phase times must be numbers in seconds.')
    ordered=['takeoff_s','landing_s'] if family=='jump' else ['hold_start_s','hold_end_s']
    a,b=(parsed[key] for key in ordered)
    if not all(math.isfinite(v) for v in [a,b]) or not 0<=a<b<=duration:
        raise ValueError('Phase times must be ordered and inside the video duration.')
    return parsed


def motion_suggestion(data,result):
    """Suggest a broad family only; shoulder sign changes are not a trained classifier."""
    signs=[]
    for frame in data['frames']:
        p=frame.get('landmarks',[])
        if not p or any(min(p[i]['visibility'],p[i]['presence'])<.75 for i in [11,12,23,24]):
            continue
        shoulder=np.array([(p[11]['x_px']+p[12]['x_px'])/2,(p[11]['y_px']+p[12]['y_px'])/2])
        hip=np.array([(p[23]['x_px']+p[24]['x_px'])/2,(p[23]['y_px']+p[24]['y_px'])/2])
        torso=float(np.linalg.norm(shoulder-hip))
        if torso<8:
            continue
        shoulder_dx=(p[12]['x_px']-p[11]['x_px'])/torso
        hip_dx=(p[24]['x_px']-p[23]['x_px'])/torso
        if abs(shoulder_dx)>.2 and abs(hip_dx)>.12 and shoulder_dx*hip_dx>0:
            signs.append((frame['timestamp_ms']/1000,1 if shoulder_dx>0 else -1))
    changes=[]
    previous=None
    for time_s,sign in signs:
        if previous is None:
            previous=(time_s,sign)
        elif sign!=previous[1] and time_s-previous[0]>.18:
            changes.append(time_s)
            previous=(time_s,sign)
    coverage=result.get('tracking',{}).get('pose_coverage_pct',0)
    low=result.get('lowered_segment')
    candidate='unknown'
    reason='No reliable element suggestion. Please choose the movement you intended.'
    if coverage>=75 and len(changes)>=3 and result['duration_s']>=2:
        candidate='sit_spin' if low and low['duration_s']>=1 else 'spin'
        reason=('Repeated changes in projected shoulder/hip orientation suggest a spin'+
                (' with a sustained lower-position candidate.' if candidate=='sit_spin' else '.'))
    return {'element':candidate,'label':ELEMENTS[candidate]['label'],'reason':reason,
            'method':'experimental pose-sequence heuristic','confidence':'unverified',
            'requires_confirmation':True,'orientation_changes':len(changes),
            'limitations':'This is not a trained jump/spin recognizer. Jumps and ambiguous clips require user selection.'}


def phases_for(result,element,markers):
    duration=result['duration_s'];family=ELEMENTS[element]['family']
    phases=[];events=[]
    def add(start,end,name,source):
        if end-start>.001:
            phases.append({'id':f'p{len(phases)}','time_s':[start,end],'name':name,'source':source})
    if family=='jump' and markers:
        takeoff,landing=markers['takeoff_s'],markers['landing_s']
        add(0,takeoff,'Preparation','user-marked boundaries')
        add(takeoff,landing,'Flight (user marked)','user-marked boundaries')
        add(landing,duration,'Landing / recovery (user marked)','user-marked boundaries')
        events=[{'name':'Takeoff','time_s':takeoff,'source':'user marked'},
                {'name':'Landing','time_s':landing,'source':'user marked'}]
    elif family=='spin' and (markers or (element=='sit_spin' and result.get('lowered_segment'))):
        low=result.get('lowered_segment') or {}
        a=markers.get('hold_start_s',low.get('start_s',0));b=markers.get('hold_end_s',low.get('end_s',duration))
        source='user-marked boundaries' if markers else 'lowered-posture heuristic; boundaries unverified'
        add(0,a,'Entry / approach',source)
        add(a,b,'Intended hold' if markers else 'Lower-position candidate',source)
        add(b,duration,'Later position / transition',source)
    else:
        name='Jump sequence — phase boundaries uncertain' if family=='jump' else 'Spin sequence — phase boundaries uncertain' if family=='spin' else 'Skating sequence — element uncertain'
        add(0,duration,name,'unresolved; no fabricated takeoff, flight or exit')
    return phases,events


def apply_element(result,data,element,markers=None):
    from spincoach.kinematics import build_kinematics
    from spincoach.isu_rules import assess_rules
    markers=validate_markers(element,markers or {},result['duration_s'])
    phases,events=phases_for(result,element,markers)
    result['element_analysis']={'element':element,**ELEMENTS[element], 'selection_source':'user confirmed',
        'rubric_status':RUBRIC_STATUS,'markers':markers,'phases':phases,'events':events,
        'suggestion':result.get('element_suggestion',motion_suggestion(data,result))}
    for row in result['frames']:
        row['element_phase']=next((p['name'] for p in phases if p['time_s'][0]<=row['time_s']<p['time_s'][1]),'Uncertain')
    result['phase_kinematics']=build_kinematics(data,result,intervals=phases)
    findings=[]
    def finding(kind,text,phase,evidence,rule_refs=None):
        findings.append({'id':f'F{len(findings)+1}','kind':kind,'text':text,'phase_id':phase,
                         'evidence':evidence,'rule_refs':rule_refs or [],
                         'status':'review point' if kind=='review' else 'insufficient evidence' if kind=='uncertain' else 'supported geometric observation'})
    low=result.get('lowered_segment')
    if element=='sit_spin' and low:
        phase=next((p for p in phases if p['time_s'][0]<=low['start_s']<p['time_s'][1]),phases[0])
        finding('positive','You established a sustained lower-body shape.',phase['id'],{'lowered_segment':low,'limitation':'This does not verify the ISU sit position or counted revolutions.'},['SPIN-SIT'])
    for phase,window in zip(phases,result['phase_kinematics']['windows']):
        for card in window['cards']:
            comparison=card.get('similar_view_comparison')
            if ELEMENTS[element]['family']=='spin' and comparison and comparison['pairs']>=3 and comparison['median_absolute_delta']>=15 and 'knee' in card['metric']:
                if phase['name'] in {'Intended hold','Lower-position candidate'}:
                    finding('review','If holding one shape, check changes in knee bend through the hold.',phase['id'],card,
                            ['SPIN-SIT'] if element=='sit_spin' else ['SPIN-CAMEL'] if element=='camel_spin' else ['SPIN-UPRIGHT'] if element=='upright_spin' else [])
    if not any(f['kind']=='positive' for f in findings):
        finding('uncertain','No confident strength identified from this view.',phases[0]['id'],{'reason':'No validated element-specific positive is supported by the available geometry.'})
    if not any(f['kind']=='review' for f in findings):
        spin_checks={
            'sit_spin':'No clear error is confirmed; check skating-thigh depth and free-boot clearance through the hold.',
            'upright_spin':'No clear error is confirmed; review the skating-leg shape through the hold.',
            'camel_spin':'No clear error is confirmed; check free-knee height in clear side views.',
        }
        text=('Confirm the element before changing your technique.' if element=='unknown' else
              'Mark takeoff and landing to review the jump phases.' if ELEMENTS[element]['family']=='jump' and not markers else
              spin_checks.get(element,'No clear error is confirmed; review the intended body shape in clear views.'))
        phase=next((p for p in phases if p['name'] in {'Intended hold','Lower-position candidate'}),phases[0])
        refs={'sit_spin':['SPIN-SIT','SPIN-TOUCH'],'camel_spin':['SPIN-CAMEL'],'upright_spin':['SPIN-UPRIGHT']}.get(element,[])
        finding('review',text,phase['id'],{'reason':'Insufficient evidence for a specific technique fault.'},refs)
    result['element_analysis']['findings']=findings
    result['element_analysis']['isu_assessment']=assess_rules(element,ELEMENTS[element]['family'],phases,result['phase_kinematics']['windows'],findings)
    good=next((f for f in findings if f['kind']=='positive'),findings[0])
    review=next(f for f in findings if f['kind']=='review')
    result['element_analysis']['summary']={'good':good['text'],'improve':review['text'],
        'good_evidence_ids':[good['id']],'improve_evidence_ids':[review['id']],
        'issue_label':'Review','source':'local evidence checks; no official technique score',
        'line':f"Good: {good['text']} Review: {review['text']}"}
    result['headline']=result['element_analysis']['summary']['line']
    return result
