"""Video element suggestions: Gemini, NVIDIA vision, then disclosed local fallback."""
import base64
import hashlib
import json
import math
import subprocess
import time
from pathlib import Path

import requests

from spincoach.elements import ELEMENTS
from spincoach.gemini_judge import GeminiSession,GeminiFailure,DEFAULT_MODEL as GEMINI_MODEL
from spincoach.visual_judge import DEFAULT_MODEL as NVIDIA_MODEL,parse_response


def prepare_recognition_media(folder,data):
    """Preserve full motion and provide timestamped views of the tracked skater."""
    import cv2
    import imageio_ffmpeg
    import numpy as np
    folder=Path(folder);video=folder/'element_video.mp4'
    subprocess.run([imageio_ffmpeg.get_ffmpeg_exe(),'-hide_banner','-loglevel','error','-y',
        '-i',str(folder/'input.mp4'),'-an','-vf',
        'scale=w=720:h=720:force_original_aspect_ratio=decrease:force_divisible_by=2',
        '-c:v','libx264','-preset','veryfast','-crf','27','-pix_fmt','yuv420p',
        '-movflags','+faststart',str(video)],check=True)
    frames=data['frames'];tiles=[];manifest=[]
    cap=cv2.VideoCapture(str(folder/'input.mp4'))
    try:
        for index in sorted({round((len(frames)-1)*i/11) for i in range(12)}):
            cap.set(cv2.CAP_PROP_POS_FRAMES,index);ok,frame=cap.read()
            if not ok:continue
            record=frames[index];height,width=frame.shape[:2]
            bbox=record.get('bbox_xywh_px')
            if bbox:
                x,y,w,h=bbox
                crop=frame[max(0,int(y-.25*h)):min(height,int(y+1.4*h)),
                           max(0,int(x-.5*w)):min(width,int(x+1.5*w))]
                if crop.size:frame=crop
            tile=np.full((320,240,3),24,np.uint8)
            h,w=frame.shape[:2];scale=min(230/w,280/h)
            resized=cv2.resize(frame,(max(1,round(w*scale)),max(1,round(h*scale))))
            h,w=resized.shape[:2];left=(240-w)//2
            tile[34:34+h,left:left+w]=resized
            timestamp=round(record['timestamp_ms']/1000,3)
            cv2.putText(tile,f'{timestamp:.2f}s',(8,24),cv2.FONT_HERSHEY_SIMPLEX,.6,(255,255,255),1)
            tiles.append(tile);manifest.append({'frame_index':index,'time_s':timestamp})
    finally:
        cap.release()
    if not tiles:raise ValueError('No frames available for element recognition.')
    while len(tiles)%4:tiles.append(np.full_like(tiles[0],24))
    sheet=folder/'element_frames.jpg'
    cv2.imwrite(str(sheet),np.concatenate([np.concatenate(tiles[i:i+4],axis=1)
        for i in range(0,len(tiles),4)],axis=0),[cv2.IMWRITE_JPEG_QUALITY,88])
    return {'video':video.name,'contact_sheet':sheet.name,'frames':manifest,
            'input_sha256':hashlib.sha256((folder/'input.mp4').read_bytes()).hexdigest()}


def recognition_prompt(duration):
    return '''Identify the main tracked skater's dominant completed figure-skating movement in this clip.
Watch the full motion before choosing. The contact sheet follows the same tracked person in timestamp order.
Do not assume every clip contains a spin or jump. Gliding, lunges, spirals, setup or partial entries alone are unknown.
A spin needs repeated rotation around a supporting leg, not just a single turn. An upright spin has a tall posture;
a sit spin has a sustained low skating-leg position; a camel spin has a forward near-horizontal torso and free leg
extended behind. A jump needs a visible takeoff, airborne interval and landing. Use waltz_jump only if its forward
half-turn takeoff/landing sequence is visible; all other or uncertain jump subtypes use jump. Use spin if rotating
but the subtype is unclear. Mixed elements without one dominant movement use unknown. These are coaching labels,
not official ISU technical calls. Do not infer blade edges or exact rotation counts from obscured feet.
Return only JSON with element, confidence (high, medium or low; self-reported), reason (one short sentence),
and evidence (1-3 objects, each with time_s in seconds and observation describing visible movement at that time).
For unknown explain what is visible instead. Supported element values: '''+json.dumps(list(ELEMENTS))+f'. Clip duration: {duration:.3f} seconds.'


def validate_identification(obj,duration):
    if not isinstance(obj,dict) or obj.get('element') not in ELEMENTS:
        raise ValueError('Unsupported element label')
    if obj.get('confidence') not in {'high','medium','low'}:
        raise ValueError('Missing confidence')
    reason=obj.get('reason');evidence=obj.get('evidence')
    if not isinstance(reason,str) or not 5<=len(reason.strip())<=700:
        raise ValueError('Missing short reason')
    if not isinstance(evidence,list) or not 1<=len(evidence)<=3:
        raise ValueError('Missing timestamped evidence')
    cleaned=[]
    for item in evidence:
        if not isinstance(item,dict):raise ValueError('Invalid evidence')
        t=item.get('time_s');observation=item.get('observation')
        if (isinstance(t,bool) or not isinstance(t,(int,float)) or not math.isfinite(t)
                or not 0<=t<duration or not isinstance(observation,str) or not 5<=len(observation.strip())<=700):
            raise ValueError('Invalid timestamp or observation')
        cleaned.append({'time_s':round(t,3),'observation':observation.strip()})
    element=obj['element']
    return {'element':element,'label':ELEMENTS[element]['label'],'confidence':obj['confidence'],
            'reason':reason.strip(),'evidence':cleaned,'requires_confirmation':True,
            'limitations':'Model confidence is self-reported; confirm or correct the suggestion.'}


def identify_element(folder,data,result,local_suggestion,gemini_key=None,nvidia_key=None,
                     gemini_model=GEMINI_MODEL,nvidia_model=NVIDIA_MODEL,timeout_s=25):
    """One new inspection only. Confirmation/resume reuses the saved suggestion."""
    folder=Path(folder);started=time.perf_counter();failures=[]
    counts={'gemini_api_calls':0,'nvidia_api_calls':0}
    suggestion=None;provider='Local';model=None;input_mode='pose sequence';media=None
    primary='Gemini' if gemini_key else 'NVIDIA' if nvidia_key else 'Local'
    too_short=result['duration_s']<1
    if too_short:
        local_suggestion={'element':'unknown','label':ELEMENTS['unknown']['label'],'confidence':'unverified',
                          'requires_confirmation':True,'method':'clip duration check',
                          'reason':'This clip is shorter than one second. Choose the intended element or upload a longer clip for automatic identification.'}
    if (gemini_key or nvidia_key) and not too_short:
        media=prepare_recognition_media(folder,data)
        prompt=recognition_prompt(result['duration_s'])
        video=folder/media['video'];sheet=folder/media['contact_sheet']
        image64=base64.b64encode(sheet.read_bytes()).decode()
        # Limit inline payloads; disclose frame-only input if a clip exceeds it.
        video64=base64.b64encode(video.read_bytes()).decode() if video.stat().st_size<12*1024*1024 else None
        input_mode='whole video and timestamped tracked-person views' if video64 else 'timestamped tracked-person views; video exceeds inline limit'
        if gemini_key:
            session=None
            try:
                remaining=timeout_s-(time.perf_counter()-started)
                if remaining<2:raise GeminiFailure('Element identification time budget exhausted.')
                session=GeminiSession(folder,gemini_key,gemini_model,min(12,remaining) if nvidia_key else remaining,
                                      diagnostic='element_gemini_attempts.json')
                # Faster sampling helps retain brief airborne intervals and spin motion.
                parts=([{'inlineData':{'mimeType':'video/mp4','data':video64},
                         'videoMetadata':{'fps':min(5,data.get('fps',5))}}] if video64 else [])
                parts.extend([{'inlineData':{'mimeType':'image/jpeg','data':image64}},{'text':prompt}])
                obj,returned_model=session.invoke(parts,1000)
                suggestion=validate_identification(obj,result['duration_s'])
                provider,model='Gemini',returned_model
            except (GeminiFailure,ValueError,TypeError) as error:
                reason=str(error) if isinstance(error,GeminiFailure) else 'Gemini returned invalid movement evidence.'
                failures.append({'provider':'Gemini','code':getattr(error,'code','gemini_response_invalid'),
                                 'reason':reason+' '+('Trying NVIDIA.' if nvidia_key else 'Using local suggestion.')})
            finally:
                counts['gemini_api_calls']=session.calls if session else 0
        if suggestion is None and nvidia_key:
            parts=([{'type':'video_url','video_url':{'url':'data:video/mp4;base64,'+video64}}] if video64 else [])
            parts.extend([{'type':'image_url','image_url':{'url':'data:image/jpeg;base64,'+image64}},
                          {'type':'text','text':prompt}])
            payload={'model':nvidia_model,'messages':[{'role':'user','content':parts}],
                     'temperature':.2,'max_tokens':1000,'stream':False}
            if nvidia_model.startswith('nvidia/nemotron-3.5'):
                payload.update(reasoning_effort='none',chat_template_kwargs={'enable_thinking':False})
            elif nvidia_model.startswith('moonshotai/'):
                payload['chat_template_kwargs']={'thinking':False}
            for attempt in range(2):
                remaining=timeout_s-(time.perf_counter()-started)
                if remaining<2:break
                try:
                    counts['nvidia_api_calls']+=1
                    budget=remaining*(.65 if attempt==0 else .95)
                    with requests.post('https://integrate.api.nvidia.com/v1/chat/completions',
                            headers={'Authorization':'Bearer '+nvidia_key,'Accept':'application/json'},
                            json=payload,timeout=(min(4,budget*.2),budget*.8)) as response:
                        if not response.ok:raise ValueError('NVIDIA recognition request failed')
                        raw=response.json();choice=raw['choices'][0]
                        if choice.get('finish_reason')!='stop':raise ValueError('Incomplete recognition')
                        suggestion=validate_identification(parse_response(choice['message']['content']),result['duration_s'])
                        provider,model='NVIDIA',raw.get('model',nvidia_model)
                        break
                except (requests.RequestException,ValueError,KeyError,IndexError,TypeError,AttributeError):
                    if attempt==0:
                        # Existing NVIDIA endpoint sometimes rejects mixed video/image inputs.
                        payload['messages'][0]['content']=[p for p in parts if p['type']!='video_url']
                        input_mode='timestamped tracked-person frame sequence; NVIDIA video request failed'
            if suggestion is None:
                failures.append({'provider':'NVIDIA','reason':'NVIDIA recognition unavailable or invalid; using local suggestion.'})
    if suggestion is None:
        suggestion=dict(local_suggestion)
        input_mode='pose sequence'
    suggestion.update(provider=provider,model=model,primary_provider=primary,
                      requested_model=gemini_model if provider=='Gemini' else nvidia_model if provider=='NVIDIA' else None,
                      method='video model' if provider!='Local' else local_suggestion['method'],
                      input_mode=input_mode,model_confidence_is_calibrated=False,
                      fallback_used=bool(failures),fallback_reasons=failures,media=media,
                      api_calls=sum(counts.values()),elapsed_s=round(time.perf_counter()-started,3),**counts)
    # Credentials never belong in saved model outputs, even if a provider echoes one.
    safe=json.dumps(suggestion,indent=2)
    for secret in (gemini_key,nvidia_key):
        if secret:safe=safe.replace(secret,'[REDACTED]')
    suggestion=json.loads(safe)
    (folder/'element_identification.json').write_text(safe)
    return suggestion
