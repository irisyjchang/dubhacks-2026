"""Generate separate, grounded model critiques for each second, then assemble them."""
from __future__ import annotations

import base64
import concurrent.futures
import hashlib
import json
import re
import time
import threading
from pathlib import Path

import requests
from spincoach.kinematics import NOTE, format_response, response_problems, label, coaching_focus


def generate_timeline(result,folder,key,model,timeout_s):
    from spincoach.narrative import compact_evidence,prepare_visual_evidence
    folder=Path(folder)
    started=time.perf_counter()
    data=json.loads((folder/'landmarks.json').read_text())
    evidence=compact_evidence(result,data)
    panels=prepare_visual_evidence(folder,result,data)
    notes={}
    path=folder/'visual_notes.json'
    if path.is_file():
        raw=json.loads(path.read_text())
        source=Path(result.get('original_source',result.get('source','')))
        if source.is_file() and raw.get('source_sha256')==hashlib.sha256(source.read_bytes()).hexdigest():
            notes={int(n['time_s'][0]):n for n in raw['notes']}
    prompts=[]
    request_folder=folder/'timeline_requests'
    request_folder.mkdir(exist_ok=True)
    calls=0
    calls_lock=threading.Lock()

    def invoke(payload):
        nonlocal calls
        begin=time.perf_counter()
        for attempt in range(5):
            remaining=timeout_s-(time.perf_counter()-started)
            if remaining<=0:
                raise TimeoutError('Timeline report deadline reached')
            with calls_lock:
                calls+=1
            with requests.post('https://integrate.api.nvidia.com/v1/chat/completions',
                headers={'Authorization':'Bearer '+key,'Accept':'application/json'},json=payload,
                timeout=(min(8,remaining*.2),min(30,remaining*.8))) as response:
                if response.status_code==429 and attempt<4:
                    try:
                        pause=float(response.headers.get('Retry-After',2**(attempt+1)))
                    except ValueError:
                        pause=2**(attempt+1)
                    pause=min(max(1,pause),16,remaining*.5)
                    time.sleep(pause)
                    continue
                if not response.ok:
                    raise RuntimeError(f'HTTP {response.status_code}: '+response.text[:500].replace(key,'[REDACTED]'))
                obj=response.json()
                break
        choice=obj['choices'][0]
        if choice.get('finish_reason')!='stop':
            raise RuntimeError('Model response did not complete: '+str(choice.get('finish_reason')))
        content=choice['message'].get('content','').strip()
        if not content:
            raise RuntimeError('Empty model response')
        return {'content':content,'elapsed_s':round(time.perf_counter()-begin,3),
                'model_returned':obj.get('model'),'request_id':obj.get('id'),
                'usage':obj.get('usage'),'finish_reason':choice.get('finish_reason')}

    def one_second(index):
        window=evidence['time_windows'][index]
        panel=next((p for p in panels if int(p['time_interval_s'][0])==index),None)
        quantitative=window['quantitative']
        facts={'time_s':window['time_s'],'reviewed_positions':notes.get(index),
               'measurement_cards':[{'joint':label(c['metric']),'median_deg':c['median'],
                    'middle_half_range_deg':[c['p25'],c['p75']],'middle_half_width_deg':c['iqr_width'],
                    'measurement_availability':{'accepted_frames':c['accepted_frames'],'total_frames':c['total_frames'],'percent':c['coverage_pct']},
                    'similar_view_comparison':c['similar_view_comparison'],'geometry_note':c['geometry_note']}
                    for c in quantitative['cards']],
               'detected_phases':list({row['phase'] for row in result['frames'] if window['time_s'][0]<=row['time_s']<window['time_s'][1]}),
               'coaching_focus':coaching_focus(quantitative),
               'foot_relationships':{k:v for k,v in quantitative['metrics'].items()
                                     if any(word in k for word in ['ankle_height','toe_']) and v['usable_for_feedback']},
               'measurement_limits':NOTE,
               'context':'The same skater rotates between these two still views. Supporting-leg identity, blade contact/pressure and intended spin variation are not measured.'}
        prompt='''Write a DATA-DRIVEN figure-skating coaching note for ONLY this time interval, 100–150 words in the first three fields. Use measured geometry to choose advice, rather than inventing a fault from the picture. Reviewed positions, if supplied, are visible facts. Give four labelled fields:
Observation: describe actual legs AND arms; cite TWO supplied measured medians with the exact joint names and numbers, if two cards are available. Explain their geometry in plain language. If no reliable cards, state the measurement gap.
Advice: link ONE practical review target to a named measured metric and its range/coverage or similar-view comparison. Explain what to try IF the skater intended to hold the same position. If the elbow is already comparatively straight, do not ask for extra extension. A bend is not an error, asymmetry is not automatically wrong, and a spread across rotating views is not proven inconsistency. Positive feedback may describe a narrow observed range, without calling it perfect technique. When no fault is supported, say that and give a specific check instead.
Cue: one simple mental picture and its concrete meaning, preserving the chosen body shape.
Caption: two short lines separated by |, at most fifty characters each. First is a check; second is your short mental cue. The video will replace the first line with an exact measured angle.

CRITICAL NUMBERS RULE: Only quote numeric values copied from the supplied measurement cards. The program validates numbers against computed facts and adds the full evidence block. Write joint names and medians naturally in your sentences, e.g. "Your right elbow median is [the supplied number] degrees, so it is comparatively extended." Do not use placeholders. No invented target angles, scores or deductions. An internal joint angle closer to straight does not mean better skating. Ratios are torso lengths, not metres. Do not call an image-plane range wobble or collapsing. Similar projected views do not prove an identical intended position. No numeric improvement targets: no expert reference is supplied here.
Advice must cite a named measured median too. The middle-half range contains the middle half of accepted values, NOT all frames. Measurement availability is usable-frame coverage, NOT the fraction within that angle range and NOT evidence of stability. Do not claim all frames are within the middle-half range. Low availability is missing data, not a technique problem. "Torso lean" includes camera tilt; do not infer lateral versus forward lean, or insist on an upright torso. A wide range across different orientations is not a reason to reduce movement. If no comparable-view evidence or intended-position reference supports a fault, give a conditional check without claiming something was wrong. Don't demand elbow symmetry when the arm positions may intentionally differ.
MOST IMPORTANT FOR ADVICE: Follow the supplied coaching_focus instruction. Explain the measured spread or already-extended joint and one concrete review/practice action. Never say a median "falls within" its own middle-half range; that is a tautology and provides no coaching value. Never infer muscle tension. Never justify a steady pose from high measurement availability.
No speed/RPM, blade edges, pressure, strength, tension, balance diagnoses, guaranteed improvement, or continuous-motion claims. Do not lock any joint or demand full extension. If arms reach forward, preserve that reach. If a leg is tucked, do not describe it stretched behind. Do not declare an exit from the spin or assign a supporting foot from MediaPipe L/R labels alone. No generic "wings then tuck then exit" story. Keep it specific to the supplied measured evidence.
Facts: '''+json.dumps(facts,separators=(',',':'))
        parts=[{'type':'text','text':prompt}]
        if panel:
            encoded=base64.b64encode((folder/panel['path']).read_bytes()).decode('ascii')
            parts.append({'type':'image_url','image_url':{'url':'data:image/jpeg;base64,'+encoded}})
        payload={'model':model,'messages':[{'role':'user','content':parts}],
            'temperature':.15,'max_tokens':550,'stream':False,
            'chat_template_kwargs':({'thinking':False} if model.startswith('moonshotai/') else {'enable_thinking':False})}
        (request_folder/f'second_{index:02d}.json').write_text(json.dumps(payload,indent=2))
        response=invoke(payload)
        (request_folder/f'second_{index:02d}_response.json').write_text(json.dumps(response,indent=2))
        problems=response_problems(response['content'],quantitative)
        if problems:
            payload['messages'][0]['content'][0]['text']+='\nRewrite all four fields, correcting these validation problems: '+' '.join(problems)
            (request_folder/f'second_{index:02d}_retry.json').write_text(json.dumps(payload,indent=2))
            response=invoke(payload)
            (request_folder/f'second_{index:02d}_retry_response.json').write_text(json.dumps(response,indent=2))
            response['retried']=True
            problems=response_problems(response['content'],quantitative)
        if problems:
            raise RuntimeError('Model evidence validation failed: '+' '.join(problems))
        response['raw_content']=response['content']
        response['content']=format_response(response['raw_content'],quantitative)
        response['measurement_cards']=quantitative['cards']
        response['formatting']='Raw model text retained; numbers validated against supplied cards; measurement tokens and evidence block filled locally from MediaPipe geometry.'
        response['time_s']=window['time_s']
        return index,response,prompt

    responses={}
    errors=[]
    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
        futures={pool.submit(one_second,i):i for i in range(len(evidence['time_windows']))}
        for future in concurrent.futures.as_completed(futures):
            i=futures[future]
            try:
                index,response,prompt=future.result()
                responses[index]=response
                prompts.append((index,prompt))
                print(f'Timeline {i}–{min(i+1,result["duration_s"]):g}s complete',flush=True)
            except Exception as error:
                errors.append({'second':i,'error':str(error).replace(key,'[REDACTED]')})
    lines=[]
    for i,window in enumerate(evidence['time_windows']):
        a,b=window['time_s']
        section=responses[i]['content'] if i in responses else format_response(
            'Observation: Model assessment unavailable for this interval.\nAdvice: Review the computed measurements; no model technique judgment was produced.\nCue: Not generated.',window['quantitative'])
        lines.extend([f'### {a:g}–{b:g} seconds','',section,''])
    content='\n'.join(lines)
    provenance={'generator':'NVIDIA language model','model':model,'model_returned':model,
        'status':'completed' if not errors else 'partial','elapsed_s':round(time.perf_counter()-started,3),
        'source':'analysis.json','api_calls':calls,
        'input_mode':'confidence-filtered numerical measurement cards with ranges/coverage, projected-view comparisons, timestamped crops, and optional reviewed notes',
        'measurement_method':NOTE,
        'reviewer_visual_notes_used':bool(notes),'frame_pairs':panels,
        'sections':[responses[i] for i in sorted(responses)],'errors':errors,
        'finish_reason':'stop' if not errors else None,'content':content}
    (folder/'coaching_assessment.json').write_text(json.dumps(provenance,indent=2))
    (folder/'coaching_request.json').unlink(missing_ok=True)
    (folder/'coaching_prompt.txt').write_text('\n\n'.join(f'=== {i} seconds ===\n{p}' for i,p in sorted(prompts)))
    (folder/'coaching_report.md').write_text('# Second-by-second spin coaching\n\n'+NOTE+'\n\n'
        'Measured evidence and numeric substitutions below are calculated locally. Coaching interpretation comes from the NVIDIA model; raw model responses are retained separately.\n\n'+content+
        '\n---\nModel-generated hackathon prototype interpretation, not an official judging score. '
        'Still frames do not verify blade edges, pressure, or motion smoothness.\n\n'
        +('Inputs include assistant-reviewed position notes in [visual_notes.json](visual_notes.json), separate from automated measurements.\n\n' if notes else '')+
        f'Model: `{model}`. Report generation: {provenance["elapsed_s"]} seconds.\n\n'
        '[Video](feedback.mp4) · [Measurements](report.md) · [Raw model sections](coaching_assessment.json)\n')
    return provenance
