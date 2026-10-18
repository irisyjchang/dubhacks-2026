"""One whole-clip multimodal coaching assessment, grounded in sampled evidence.

Model confidence is self-reported, not a calibrated probability or official call.
The measured evidence and the model's visual interpretation remain separate.
"""
from __future__ import annotations

import base64
import hashlib
import json
from pathlib import Path
import re
import subprocess
import time

import requests

from spincoach.isu_rules import phase_rules
from spincoach.kinematics import format_response
from spincoach.errors import CoachingServiceError,ProcessingFailure
from spincoach.concise_report import REVIEW_INSTRUCTIONS,validate_review

DEFAULT_MODEL = 'nvidia/nemotron-3.5-super-vl-120b-a12b'
FALLBACK_MODEL = 'google/diffusiongemma-26b-a4b-it'
DETAILED_ONLY = {'SPIN-REVOLUTIONS','SPIN-MISSING','SPIN-TOUCH','JUMP-TAKEOFF','SPIN-POSITION','SPIN-EXIT'}
VERDICTS = {'strength':'Looks good','needs_work':'Needs work','limited_view':'Limited view'}


def prepare_media(folder,result,data):
    """Full-rink video for context plus multiple close views of each phase.

    The crops follow the tracked person; only the uncropped video can supply
    rink context. Neither is used to measure ice-relative centering or RPM.
    """
    import cv2
    import imageio_ffmpeg
    import numpy as np
    folder=Path(folder)
    destination=folder/'judge_video.mp4'
    subprocess.run([imageio_ffmpeg.get_ffmpeg_exe(),'-hide_banner','-loglevel','error','-y',
        '-i',str(folder/'input.mp4'),'-an','-vf',
        'scale=w=720:h=720:force_original_aspect_ratio=decrease:force_divisible_by=2',
        '-c:v','libx264','-preset','veryfast','-crf','26','-pix_fmt','yuv420p',
        '-movflags','+faststart',str(destination)],check=True)
    manifest=[];tiles=[]
    cap=cv2.VideoCapture(str(folder/'input.mp4'))
    try:
        for phase in result['element_analysis']['phases']:
            a,b=phase['time_s']
            # Four views per phase include entry/exit context and body rotation.
            indices=sorted({min(len(data['frames'])-1,max(0,int((a+(b-a)*u)*data['fps'])))
                            for u in [.08,.33,.60,.88]})
            for index in indices:
                record=data['frames'][index]
                t=record['timestamp_ms']/1000
                if not a<=t<b:
                    continue
                cap.set(cv2.CAP_PROP_POS_FRAMES,index)
                ok,frame=cap.read()
                if not ok:
                    continue
                height,width=frame.shape[:2]
                bbox=record.get('bbox_xywh_px')
                if bbox:
                    x,y,w,h=bbox
                    crop=frame[max(0,int(y-.25*h)):min(height,int(y+1.5*h)),
                               max(0,int(x-.45*w)):min(width,int(x+1.45*w))]
                    if not crop.size:
                        crop=frame
                else:
                    crop=frame
                tile=np.full((384,288,3),24,np.uint8)
                h,w=crop.shape[:2];scale=min(276/w,342/h)
                resized=cv2.resize(crop,(max(1,round(w*scale)),max(1,round(h*scale))))
                h,w=resized.shape[:2];x=(288-w)//2
                tile[38:38+h,x:x+w]=resized
                frame_id=f'f{len(manifest):03d}'
                cv2.putText(tile,f'{frame_id}  {t:.2f}s  {phase["id"]}',(8,25),
                            cv2.FONT_HERSHEY_SIMPLEX,.55,(255,255,255),1,cv2.LINE_AA)
                manifest.append({'id':frame_id,'time_s':round(t,3),'phase_id':phase['id']})
                cv2.imwrite(str(folder/f'judge_{frame_id}.jpg'),tile,[cv2.IMWRITE_JPEG_QUALITY,90])
                tiles.append(tile)
    finally:
        cap.release()
    if not tiles:
        raise ValueError('No video frames could be read for visual coaching.')
    # One contact sheet is supported even on endpoints accepting one image.
    while len(tiles)%4:
        tiles.append(np.full_like(tiles[0],24))
    sheet=np.concatenate([np.concatenate(tiles[i:i+4],axis=1) for i in range(0,len(tiles),4)],axis=0)
    image_path=folder/'judge_frames.jpg'
    cv2.imwrite(str(image_path),sheet,[cv2.IMWRITE_JPEG_QUALITY,88])
    media={'video':destination.name,'contact_sheet':image_path.name,'frames':manifest,
           'input_sha256':hashlib.sha256((folder/'input.mp4').read_bytes()).hexdigest(),
           'description':'Uncropped full-clip video and timestamped tracked-person close-ups; crops are not centering evidence.'}
    (folder/'judge_media.json').write_text(json.dumps(media,indent=2))
    return media


def position_request_parts(phase,media,folder):
    """Shared phase close-up panel and perception prompt for model providers."""
    import cv2
    import numpy as np
    available=[f for f in media['frames'] if f['phase_id']==phase['id']]
    tiles=[cv2.imread(str(Path(folder)/f"judge_{f['id']}.jpg")) for f in available]
    if not tiles or any(t is None for t in tiles):
        raise ValueError('The phase close-ups could not be read.')
    while len(tiles)<4:
        tiles.append(np.full_like(tiles[0],24))
    # An independent 2x2 panel per phase avoids mixing earlier and later
    # poses, and gives each body more visual resolution than the overview.
    panel=np.concatenate([np.concatenate(tiles[:2],axis=1),np.concatenate(tiles[2:4],axis=1)],axis=0)
    panel_path=Path(folder)/f"judge_position_{phase['id']}.jpg"
    cv2.imwrite(str(panel_path),panel,[cv2.IMWRITE_JPEG_QUALITY,92])
    prompt='''Describe ONLY visible body positions in these four images of the SAME time interval. Read top-left, top-right, bottom-left, bottom-right. This is a perception task, NOT coaching. Do not infer an exit, smoothness, balance or a fault. First inspect the raised knee: is it bent with its foot near the body, or straight with its foot stretched away? A leg bent with the knee lifted near hip height is folded_front, not extended_back. Arms by a folded leg are close_front, not spread sideways. Do not invent a conventional skating narrative.
Return only JSON: {"positions":[{"phase_id":"COPY SUPPLIED ID","frame_ids":["COPY ALL SUPPLIED FRAME IDS"],"free_leg_shape":"folded_front or extended_front or extended_back or mixed or obscured","arm_shape":"close_front or reaching_forward or open_sideways or mixed or obscured","body_height":"low or upright or mixed","sit_depth":"appears_at_or_below_parallel or appears_above_parallel or unclear or not_sit","description":"one precise sentence about legs, feet and arms without advice"}]}. Only this phase. sit_depth refers to the apparent skating THIGH relative to ice, not torso angle. Use unclear if hidden. If shapes change, report mixed. Frames: '''+json.dumps(available,separators=(',',':'))
    parts=[{'type':'image_url','image_url':{'url':'data:image/jpeg;base64,'+base64.b64encode(panel_path.read_bytes()).decode()}},
           {'type':'text','text':prompt}]
    return available,prompt,parts


def read_positions(result,media,folder,key,model,timeout_s,request_stats=None):
    """Separate perception from coaching to avoid a conventional spin story.

    Individual crops retain more body detail than a downsampled contact sheet.
    These are still model observations, not manually verified ground truth.
    """
    import cv2
    import numpy as np
    chosen=[];positions=[];records=[];started=time.perf_counter()
    for phase in result['element_analysis']['phases']:
        available,prompt,parts=position_request_parts(phase,media,folder)
        chosen.extend(available)
        payload={'model':model,'messages':[{'role':'user','content':parts}],
                 'temperature':.2,'max_tokens':650,'stream':False}
        if model.startswith('moonshotai/'):
            payload['chat_template_kwargs']={'thinking':False}
        if model.startswith('nvidia/nemotron-3.5'):
            payload.update(reasoning_effort='none',chat_template_kwargs={'enable_thinking':False})
        remaining=timeout_s-(time.perf_counter()-started)
        if remaining<2:
            raise CoachingServiceError(timeout=True)
        for attempt in range(2):
            remaining=timeout_s-(time.perf_counter()-started)
            if remaining<2:
                raise CoachingServiceError(timeout=True)
            if attempt:
                payload['model']=FALLBACK_MODEL
                payload.pop('reasoning_effort',None)
                payload['chat_template_kwargs']={'enable_thinking':False}
                print('Coaching service: retrying position reading with the fallback model...',flush=True)
            if request_stats is not None:
                request_stats['calls']+=1
            try:
                response=requests.post('https://integrate.api.nvidia.com/v1/chat/completions',
                    headers={'Authorization':'Bearer '+key,'Accept':'application/json'},json=payload,
                    timeout=(min(6,remaining*.2),min(18,remaining*.8)))
            except (requests.Timeout,requests.ConnectionError) as error:
                if not attempt:
                    continue
                raise CoachingServiceError(timeout=True) from error
            with response:
                if not response.ok:
                    if not attempt and response.status_code in {404,429,500,502,503,504}:
                        continue
                    raise CoachingServiceError(response.status_code)
                raw=response.json()
                break
        choice=raw['choices'][0]
        record={'model':payload['model'],'content':choice['message'].get('content',''),
                'finish_reason':choice.get('finish_reason'),'usage':raw.get('usage'),
                'frames':available,'prompt':prompt,'description':'Separate model perception, not human-verified observations.'}
        records.append(record)
        (Path(folder)/'judge_positions.json').write_text(json.dumps(records,indent=2))
        if choice.get('finish_reason')!='stop':
            raise ProcessingFailure('NVIDIA returned an incomplete position reading. Your tracking is saved; retry the report.',
                                    'coaching_response_invalid',True)
        try:
            readings=parse_response(record['content']).get('positions')
            validate_positions(readings,{'element_analysis':{'phases':[phase]}},available)
        except (ValueError,TypeError,KeyError) as error:
            raise ProcessingFailure('NVIDIA returned an invalid position reading. Your tracking is saved; retry the report.',
                                    'coaching_response_invalid',True) from error
        positions.extend(readings)
    validate_positions(positions,result,chosen)
    return positions


def validate_positions(positions,result,frames):
    phase_ids={p['id'] for p in result['element_analysis']['phases']}
    if not isinstance(positions,list) or len(positions)!=len(phase_ids) or {p.get('phase_id') for p in positions if isinstance(p,dict)}!=phase_ids:
        raise ValueError('Position readings must cover every phase once.')
    for row in positions:
        available={f['id'] for f in frames if f['phase_id']==row['phase_id']}
        if not isinstance(row.get('frame_ids'),list) or set(row['frame_ids'])!=available:
            raise ValueError('Position readings must use the supplied frames for their phase.')
        allowed={'free_leg_shape':{'folded_front','extended_front','extended_back','mixed','obscured'},
                 'arm_shape':{'close_front','reaching_forward','open_sideways','mixed','obscured'},
                 'body_height':{'low','upright','mixed'},
                 'sit_depth':{'appears_at_or_below_parallel','appears_above_parallel','unclear','not_sit'}}
        if any(row.get(field) not in values for field,values in allowed.items()) or not isinstance(row.get('description'),str):
            raise ValueError('Position readings must use the requested shape categories and a description.')


def prompt_for(result,media,positions=None):
    element=result['element_analysis']
    phases=[]
    for phase,window in zip(element['phases'],result['phase_kinematics']['windows']):
        references=[r for r in phase_rules(element['isu_assessment'],phase) if r['id'] not in DETAILED_ONLY]
        phases.append({**phase,'rules':[{k:r[k] for k in ['id','title','criterion']} for r in references],
                       'measurements':[c['detail'] for c in window['cards']],
                       'frames':[f for f in media['frames'] if f['phase_id']==phase['id']]})
    facts={'element':element['label'],'phases':phases,'duration_s':result['duration_s'],
           'measurement_note':'2D projected measurements; L/R are pose labels, not automatically the skating/free leg. '
                              'Treat these as evidence context, not ISU ideal angles. Use visible frames to interpret position.'}
    if positions:
        facts['position_readings']=positions
    return REVIEW_INSTRUCTIONS+'\n\n'+'''You are a figure-skating coach giving a useful hackathon assessment of the ATTACHED CLIP and close-up contact sheet. Analyze the visible skating, not the reliability checklist. Make direct, specific judgments about what was done well and what needs work. You may say "Your free leg drops during the hold" when the sequence visibly supports that; do not retreat to "review whether" for everything.
Use the full clip to understand the movement across time, and frame IDs to anchor each observation. The video service may sample frames, so do not claim frame-exact takeoff, landing or rotation. If only the contact sheet is provided, assess those sampled views without claiming continuous playback. Give each phase a concise observation covering arms, legs and feet where visible, a strength, ONE priority improvement, an actionable correction, and a short mental cue. Describe the shape that is actually present. A bent knee or elbow, asymmetric arm variation, extended free leg, or rise into another position is not automatically a mistake. A flexed skating knee is normal in gliding, entry and landing; do not call knee bend a fault or demand a straight supporting leg without visible phase-specific evidence of a control problem. Forward torso lean is normal in many sit positions; do not call it excessive or demand lifting the chest without visible supporting evidence of a specific position problem. Do not demand tucking an intentionally extended leg or extending an intentionally folded leg. Apply only the supplied ISU criterion relevant to that phase. Do not demand extra elbow straightness or identical arms. Do not invent faults to fill a quota; if no fault is visible, give a useful next practice goal.
Do not automatically call the final interval an exit. Treat a user-marked hold as the intended hold, not proof of a legal position. Position changes can be deliberate. A torso-lean angle cannot establish skating-thigh depth. Assess apparent sit depth visually from clear side views, with a short qualifier only if needed. Do not claim a boot touches the ice from proximity. Do not assign supporting-foot L/R unless clearly visible.
The separate position_readings identify the actual visible shape from larger individual crops. Keep your observations and captions consistent with them. If the leg is folded in front, do not describe or prescribe an extension behind. If sit_depth appears_at_or_below_parallel, do not tell the skater to deepen the sit: focus on preserving that depth, the visible free-leg/arm shape or an appropriate next practice goal. Do not claim that preparation before a marked hold is an excessive delay. Do not tell the skater to prolong a hold merely because they deliberately change position. Address the skater as "you".
Before the intended hold, an upright entry or a free-leg swing can be deliberate preparation: do not demand remaining in a low sit throughout the approach. Assess visible coordination instead. An ordinary position change is not an exit or a timing fault merely because the clip ends.
Reserve uncertainty for the SPECIFIC obscured detail; do not repeat "unconfirmed", "unverified", "not assessable", "cannot determine" or generic requests for a clearer view in every paragraph. Your confidence describes your visual opinion, not certainty. No official GOE, competition scores or levels, precise blade edges, exact turn counts/RPM, muscle tension, or invented ideal angles. Do not infer travel from the following crops or speed from image displacement. Use simple, direct coaching language. No numerical values in the summary, good, improve or captions. Detailed observations may quote only supplied measured values; numbers are optional, not required. Say what you see, why it matters, and what to change.

Return ONLY JSON with this structure (no markdown). Cover EVERY supplied phase once. Copy phase_id and frame IDs exactly. Use 2 distinct evidence frames per phase when available. good and improve must each be one short sentence of at most 150 characters, suitable for the top summary; other text fields at most 45 words. Write about 250 words total for three phases. For a needs_work verdict name a visible shortcoming and a correction; for strength name a visible positive. The rule is a reference for a VISUAL COACHING OPINION, never a formal rule pass/fail. You may leave rule_assessments empty if no provided criterion fits.
{"overall":{"good_phase_id":"p1","improve_phase_id":"p1","review":{"strengths":"what you did right","errors":"the main visible problem","improvements":"one practical correction","score":7,"score_reason":"short reason for the coaching rating"}},"phases":[{"phase_id":"p0","observation":"specific visible arm, leg and foot positions","good":"what was done well","improve":"the priority improvement, or next practice goal","advice":"how to make that improvement","cue":"short mental image","caption":["short coaching action","short cue"],"confidence":"high or medium or low","evidence":[{"frame_id":"f000","body_part":"arms or legs or feet or whole_body","observation":"visible support for the judgment"}],"rule_assessments":[{"rule_id":"exact supplied rule ID","verdict":"strength or needs_work or limited_view","reason":"visible finding tied to the criterion","frame_ids":["f000"]}]}],"limits":["one short specific detail that cannot be judged, only if relevant"]}
Facts: '''+json.dumps(facts,separators=(',',':'))


def parse_response(content):
    # Some Gemma deployments leave empty thought-channel markers in content.
    content=content.rsplit('<channel|>',1)[-1].strip()
    content=re.sub(r'^```(?:json)?\s*|\s*```$','',content).strip()
    # Some responses repeat the same complete JSON once in the final channel.
    # Accept identical copies only; conflicting or trailing content stays invalid.
    decoder=json.JSONDecoder()
    obj,end=decoder.raw_decode(content)
    tail=content[end:].strip()
    while tail:
        duplicate,end=decoder.raw_decode(tail)
        if duplicate!=obj:
            raise ValueError('Conflicting JSON objects in the model response.')
        tail=tail[end:].strip()
    if not isinstance(obj,dict):
        raise ValueError('The visual report must be a JSON object.')
    return obj


def validate_report(obj,result,media,positions=None):
    """Check traceable references and structure, never manufacture confidence."""
    element=result['element_analysis']
    phase_map={p['id']:p for p in element['phases']}
    frames={f['id']:f for f in media['frames']}
    rows=obj.get('phases')
    if not isinstance(rows,list) or len(rows)!=len(phase_map) or {r.get('phase_id') for r in rows if isinstance(r,dict)}!=set(phase_map):
        raise ValueError('Return each supplied phase exactly once.')
    for row in rows:
        phase=phase_map[row['phase_id']]
        for field in ['observation','good','improve','advice','cue']:
            if not isinstance(row.get(field),str) or not row[field].strip() or len(row[field])>900:
                raise ValueError('Every phase needs a short nonempty '+field+'.')
        for field in ['good','improve']:
            if len(row[field])>180 or re.search(r'\d|°',row[field]):
                raise ValueError('Good and improve must be short qualitative sentences without numbers.')
        if row.get('confidence') not in {'high','medium','low'}:
            raise ValueError('Confidence must be high, medium or low.')
        caption=row.get('caption')
        if not isinstance(caption,list) or len(caption)!=2 or any(not isinstance(s,str) or not s.strip() or len(s)>60 or re.search(r'\d|°|\|',s) for s in caption):
            raise ValueError('Use exactly two short qualitative caption lines without numbers or separators.')
        evidence=row.get('evidence')
        if not isinstance(evidence,list) or not evidence:
            raise ValueError('Every phase needs visible evidence with valid frame IDs.')
        for entry in evidence:
            if not isinstance(entry,dict) or entry.get('frame_id') not in frames or frames[entry['frame_id']]['phase_id']!=phase['id']:
                raise ValueError('Evidence frame IDs must belong to the assessed phase.')
            # Normalize harmless anatomical aliases without rewriting any
            # actual observation or confidence claim.
            aliases={'free_leg':'legs','skating_leg':'legs','leg':'legs','foot':'feet',
                     'arm':'arms','torso':'whole_body','body':'whole_body','upper_body':'whole_body'}
            entry['body_part']=aliases.get(entry.get('body_part'),entry.get('body_part'))
            if entry.get('body_part') not in {'arms','legs','feet','whole_body'} or not isinstance(entry.get('observation'),str) or not entry['observation'].strip():
                raise ValueError('Evidence needs a body part and a visible observation.')
        available={f['id'] for f in media['frames'] if f['phase_id']==phase['id']}
        if len({e['frame_id'] for e in evidence})<min(2,len(available)):
            raise ValueError('Use two distinct evidence frames per phase when available.')
        allowed={r['id'] for r in phase_rules(element['isu_assessment'],phase)}-DETAILED_ONLY
        if not isinstance(row.get('rule_assessments'),list):
            raise ValueError('Provide rule_assessments as a list.')
        for rule in row['rule_assessments']:
            if not isinstance(rule,dict) or rule.get('rule_id') not in allowed or rule.get('verdict') not in VERDICTS:
                raise ValueError('Only assess a supplied phase-relevant visual rule using the allowed verdicts.')
            if not isinstance(rule.get('reason'),str) or not rule['reason'].strip():
                raise ValueError('Each rule judgment needs a visible reason.')
            if not isinstance(rule.get('frame_ids'),list) or not rule['frame_ids'] or not set(rule['frame_ids'])<=available:
                raise ValueError('Rule evidence must reference this phase\'s frames.')
        # Validate numbers in prose only against this phase's actual supplied
        # measurements; reference IDs are structural, not measured values.
        window=next(w for p,w in zip(element['phases'],result['phase_kinematics']['windows']) if p['id']==phase['id'])
        allowed_numbers=[c[k] for c in window['cards'] for k in ['median','p25','p75','iqr_width','accepted_frames','total_frames','coverage_pct']]
        prose=' '.join([row[f] for f in ['observation','advice','cue']]+[e['observation'] for e in evidence]+[r['reason'] for r in row['rule_assessments']])
        position=next((p for p in positions or [] if p['phase_id']==phase['id']),None)
        description=' '.join([row[f] for f in ['observation','good','improve','advice','cue']]+row['caption']+[e['observation'] for e in evidence])
        if position:
            if position['free_leg_shape']=='folded_front' and re.search(r'(?:free (?:leg|foot).{0,55}(?:extend|stretch).{0,25}behind|(?:extend|stretch).{0,25}(?:free leg|free foot).{0,20}behind)',description,re.I):
                raise ValueError('The free leg is folded in front in this phase; do not describe or prescribe extension behind.')
            if position['sit_depth']=='appears_at_or_below_parallel' and re.search(r'deepen|hips? (?:further |even )?lower|lower (?:the |your )?hips? (?:further|more)|(?:does not|doesn.t|not clearly) reach parallel',description,re.I):
                raise ValueError('The sit already appears at or below parallel; preserve its depth rather than demanding a deeper position.')
            if position['arm_shape']=='close_front' and re.search(r'arms.{0,30}(?:open(?:ing)?|spread|extend(?:ed)?) (?:out|wide|side)',row['observation'],re.I):
                raise ValueError('The arms are close to the front; do not describe them opening sideways.')
        nums=[float(n) for n in re.findall(r'(?<![\w.])-?\d+(?:\.\d+)?',prose.replace('–',' '))]
        if any(not any(abs(n-x)<=.51 for x in allowed_numbers) for n in nums):
            raise ValueError('Do not invent numerical targets or measurements; use the supplied measurements or qualitative descriptions.')
        if re.search(r'\b(?:GOE|deduction|penalty|score|level)\s*(?::|of|is|=)?\s*[+−-]?\d|\b(?:legal|illegal|valid|invalid) (?:sit|camel|upright|spin)|\b(?:passes|fails|violates|satisfies) (?:the |this )?(?:ISU|rule|criterion)|\b(?:lock|locking|locked) (?:your |the )?(?:knee|elbow|ankle|joint)',prose,re.I):
            raise ValueError('Give visual coaching, not official scores, legal-position verdicts or locked-joint instructions.')
    overall=obj.get('overall',{})
    if not isinstance(overall,dict) or any(overall.get(k) not in phase_map for k in ['good_phase_id','improve_phase_id']):
        raise ValueError('Select valid good_phase_id and improve_phase_id for the overall summary.')
    validate_review(overall.get('review'))
    if not isinstance(obj.get('limits',[]),list) or any(not isinstance(x,str) or len(x)>300 for x in obj.get('limits',[])):
        raise ValueError('Limits must be a short list of strings.')
    return obj


def apply_visual_report(obj,result,media,model,provider="NVIDIA"):
    """Make the summary, rules, phase report and captions share one assessment."""
    element=result['element_analysis']
    rows={r['phase_id']:r for r in obj['phases']}
    frames={f['id']:f for f in media['frames']}
    findings=[];sections=[]
    for phase,window in zip(element['phases'],result['phase_kinematics']['windows']):
        row=rows[phase['id']]
        evidence=[{**e,'time_s':frames[e['frame_id']]['time_s']} for e in row['evidence']]
        for kind,field in [('positive','good'),('review','improve')]:
            findings.append({'id':f"V-{phase['id']}-{field}",'kind':kind,'phase_id':phase['id'],
                             'text':row[field],'evidence':evidence,'confidence':row['confidence'],
                             'status':'model visual coaching opinion','model':model,
                             'rule_refs':[r['rule_id'] for r in row['rule_assessments']]})
        raw='Observation: '+row['observation']+'\nGood: '+row['good']+'\nImprove: '+row['improve']+'\nAdvice: '+row['advice']+'\nCue: '+row['cue']
        for rule in row['rule_assessments']:
            raw+='\nRule: '+rule['rule_id']
        raw+='\nCaption: '+' | '.join(row['caption'])
        sections.append({'time_s':phase['time_s'],'phase_id':phase['id'],'phase_name':phase['name'],
                         'raw_content':raw,'content':format_response(raw,window,numeric_caption=False),
                         'measurement_cards':window['cards'],'visual_evidence':evidence,
                         'visual_confidence':row['confidence'],'rule_assessments':row['rule_assessments']})
    good_phase=obj['overall']['good_phase_id'];improve_phase=obj['overall']['improve_phase_id']
    good=rows[good_phase]['good'];improve=rows[improve_phase]['improve']
    summary={'good':good,'improve':improve,'line':f'Good: {good} Improve: {improve}',
             'good_evidence_ids':[f'V-{good_phase}-good'],'improve_evidence_ids':[f'V-{improve_phase}-improve'],
             'issue_label':'Improve','source':provider+' whole-clip visual coaching',
             'confidence_note':'Model confidence is an estimate, not a calibrated probability.'}
    element['geometric_findings']=element['findings']
    element['findings']=findings; element['summary']=summary
    element['visual_limits']=obj.get('limits',[])
    element['visual_model']=model
    element['visual_provider']=provider
    element['coaching_review']=obj['overall']['review']
    result['headline']=summary['line']
    for check in element['isu_assessment']['checks']:
        opinions=[{**rule,'phase_id':row['phase_id'],'confidence':row['confidence']}
                  for row in obj['phases'] for rule in row['rule_assessments'] if rule['rule_id']==check['id']]
        if opinions:
            chosen=next((o for o in opinions if o['verdict']=='needs_work'),
                        next((o for o in opinions if o['verdict']=='strength'),opinions[0]))
            check['geometry_status']=check['status']
            check['status']='visual_'+chosen['verdict']
            check['explanation']=chosen['reason']
            check['visual_opinions']=opinions
            check['finding_ids']=[f['id'] for f in findings if check['id'] in f['rule_refs']]
            check['status_label']=VERDICTS[chosen['verdict']]
    return sections


def generate_visual_report(result,folder,key,model=DEFAULT_MODEL,timeout_s=75):
    folder=Path(folder);started=time.perf_counter()
    requested_model=model
    stats={'calls':0}
    data=json.loads((folder/'landmarks.json').read_text())
    media=prepare_media(folder,result,data)
    positions=read_positions(result,media,folder,key,model,max(2,timeout_s-(time.perf_counter()-started)),request_stats=stats)
    prompt=prompt_for(result,media,positions)
    (folder/'coaching_prompt.txt').write_text(prompt)
    parts=[{'type':'video_url','video_url':{'url':'data:video/mp4;base64,'+base64.b64encode((folder/media['video']).read_bytes()).decode()}},
           {'type':'image_url','image_url':{'url':'data:image/jpeg;base64,'+base64.b64encode((folder/media['contact_sheet']).read_bytes()).decode()}},
           {'type':'text','text':prompt}]
    payload={'model':model,'messages':[{'role':'system','content':'You are a precise, practical skating coach. Return the requested JSON without reasoning traces.'},
                                     {'role':'user','content':parts}],
             'temperature':.5,'max_tokens':2800,'stream':False}
    if model.startswith('moonshotai/'):
        payload['chat_template_kwargs']={'thinking':False}
    if model.startswith('nvidia/nemotron-3.5'):
        payload['reasoning_effort']='none'
        payload['chat_template_kwargs']={'enable_thinking':False}
    attempts=[];validated=None;calls=stats['calls'];input_mode='whole video, timestamped close-ups and separate phase position readings'
    service_failures=0;last_status=None
    for attempt in range(4):
        remaining=timeout_s-(time.perf_counter()-started)
        if remaining<2:
            break
        if service_failures>=2 and model!=FALLBACK_MODEL:
            attempts.append({'event':'model_fallback','from_model':model,'to_model':FALLBACK_MODEL})
            model=FALLBACK_MODEL
            payload['model']=model
            payload.pop('reasoning_effort',None)
            payload['chat_template_kwargs']={'enable_thinking':False}
            payload['temperature']=.15
            payload['max_tokens']=min(2400,1000*len(result['element_analysis']['phases']))
            payload['messages'][-1]['content']=[p for p in parts if p['type']!='video_url']
            input_mode='timestamped whole-clip frame sequence; primary model unavailable'
            print('Coaching service: primary model unavailable; using the fallback vision model...',flush=True)
        (folder/'visual_model_attempts.json').write_text(json.dumps(attempts,indent=2))
        calls+=1
        try:
            response=requests.post('https://integrate.api.nvidia.com/v1/chat/completions',
                headers={'Authorization':'Bearer '+key,'Accept':'application/json'},json=payload,
                timeout=(min(8,remaining*.2),min(40,remaining*.8)))
        except (requests.Timeout,requests.ConnectionError):
            service_failures+=1
            if attempt<3:
                had_video=any(p['type']=='video_url' for p in payload['messages'][-1]['content'])
                attempts.append({'model':model,'error':'Request timed out; retrying within the report budget.'})
                payload['messages'][-1]['content']=[p for p in parts if p['type']!='video_url']
                if had_video:
                    input_mode='timestamped whole-clip frame sequence; video request timed out'
                continue
            raise CoachingServiceError(timeout=True)
        with response:
            if not response.ok:
                service_failures+=1
                last_status=response.status_code
                attempts.append({'status':last_status,'model':model})
                (folder/'visual_model_attempts.json').write_text(json.dumps(attempts,indent=2))
            if response.status_code in {400,413,415,422,500,502,503,504} and attempt==0:
                attempts.append({'status':response.status_code,'error':'Video/mixed media request rejected; retrying with sampled frame sequence.'})
                payload['messages'][-1]['content']=[p for p in parts if p['type']!='video_url']
                input_mode='timestamped whole-clip frame sequence; video media rejected'
                continue
            if response.status_code in {404,429,500,502,503,504} and attempt<3:
                try:
                    delay=min(8,max(1,float(response.headers.get('Retry-After',3))))
                except ValueError:
                    delay=3
                attempts.append({'status':response.status_code,'error':'NVIDIA transient error; retrying within the time budget.'})
                time.sleep(min(delay,max(0,remaining-2)))
                continue
            if not response.ok:
                raise CoachingServiceError(response.status_code)
            raw=response.json()
        last_status=None
        choice=raw['choices'][0]
        content=choice['message'].get('content','')
        record={'content':content,'model_returned':raw.get('model'),'request_id':raw.get('id'),
                'usage':raw.get('usage'),'finish_reason':choice.get('finish_reason')}
        attempts.append(record)
        # Responses contain no credentials or encoded input media.
        (folder/'visual_model_attempts.json').write_text(json.dumps(attempts,indent=2))
        try:
            if choice.get('finish_reason')!='stop':
                raise ValueError('Return a complete compact JSON response; the previous one was truncated.')
            validated=validate_report(parse_response(content),result,media,positions)
            break
        except (ValueError,TypeError,KeyError) as error:
            record['validation_error']=str(error)
            payload['messages'][-1]['content'][-1]['text']=prompt+'\nCorrect the previous response problem: '+str(error)
    if validated is None:
        (folder/'visual_model_attempts.json').write_text(json.dumps(attempts,indent=2))
        if last_status:
            raise CoachingServiceError(last_status)
        raise ProcessingFailure('NVIDIA could not finish a valid coaching report within the time limit. Your tracking is saved; retry the report.',
                                'coaching_response_invalid',True)
    sections=apply_visual_report(validated,result,media,model)
    report={'generator':'NVIDIA whole-clip visual coaching','model':model,'model_returned':raw.get('model'),
            'requested_model':requested_model,'fallback_used':model!=requested_model,
            'status':'completed','api_calls':calls,'elapsed_s':round(time.perf_counter()-started,3),
            'input_mode':input_mode,'media':media,'model_assessment':validated,'sections':sections,
            'position_readings':positions,
            'summary':result['element_analysis']['summary'],'errors':[],
            'content':'\n\n'.join(s['content'] for s in sections),
            'source':'video, sampled close-ups and MediaPipe measurements',
            'confidence_note':'Visual judgments are model opinions; confidence is not calibrated. No official scores are calculated.'}
    (folder/'coaching_assessment.json').write_text(json.dumps(report,indent=2))
    return report
