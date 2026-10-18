"""Native Gemini video coaching, using the same evidence and validation as NVIDIA."""
import base64
import json
import re
import random
import time
from pathlib import Path

import requests

from spincoach.visual_judge import (prepare_media,position_request_parts,parse_response,
                                   validate_positions,prompt_for,validate_report,apply_visual_report)

DEFAULT_MODEL='gemini-3.5-flash'


class GeminiFailure(Exception):
    def __init__(self,message,code='gemini_unavailable',calls=0,elapsed_s=0):
        super().__init__(message)
        self.code,self.calls,self.elapsed_s=code,calls,elapsed_s


class GeminiSession:
    """Native JSON requests with a shared deadline and safe diagnostics."""
    def __init__(self,folder,key,model=DEFAULT_MODEL,timeout_s=30,diagnostic='gemini_attempts.json'):
        if not re.fullmatch(r'gemini-[a-zA-Z0-9.\-]+',model):
            raise GeminiFailure('The configured Gemini model name is invalid.','gemini_model')
        self.folder,self.key,self.model=Path(folder),key,model
        self.timeout_s,self.diagnostic=timeout_s,diagnostic
        self.started=time.perf_counter();self.attempts=[];self.calls=0

    def failure(self,message,code='gemini_unavailable'):
        return GeminiFailure(message,code,self.calls,round(time.perf_counter()-self.started,3))

    def invoke(self,parts,tokens=3500):
        remaining=self.timeout_s-(time.perf_counter()-self.started)
        if remaining<2:
            raise self.failure('Gemini exceeded its response time budget.','gemini_timeout')
        config={'responseMimeType':'application/json','maxOutputTokens':tokens}
        if self.model.startswith('gemini-2.5'):
            config['temperature']=.3
            config['thinkingConfig']={'thinkingBudget':0}
        elif self.model.startswith('gemini-3'):
            config['thinkingConfig']={'thinkingLevel':'low'}
        try:
            for retry in range(3):
                remaining=self.timeout_s-(time.perf_counter()-self.started)
                if remaining<2:
                    raise self.failure('Gemini exceeded its response time budget.','gemini_timeout')
                self.calls+=1
                response=requests.post(f'https://generativelanguage.googleapis.com/v1beta/models/{self.model}:generateContent',
                    headers={'x-goog-api-key':self.key},
                    json={'contents':[{'role':'user','parts':parts}],'generationConfig':config},
                    timeout=(min(6,remaining*.2),remaining*.8))
                delay=2**retry+random.uniform(0,.25)
                if (response.status_code in {500,502,503,504} and retry<2
                        and self.timeout_s-(time.perf_counter()-self.started)>delay+2):
                    self.attempts.append({'status':response.status_code,'model':self.model,'retry_in_s':round(delay,3)})
                    response.close()
                    print('Coaching service: Gemini temporarily unavailable; retrying the same request...',flush=True)
                    time.sleep(delay)
                    continue
                break
            if not response.ok:
                # Never retain Google's error body, which can echo credentials or account IDs.
                self.attempts.append({'status':response.status_code,'model':self.model})
                if response.status_code==403:
                    try:
                        error=response.json().get('error',{})
                        disabled=any(d.get('reason')=='SERVICE_DISABLED' for d in error.get('details',[]) if isinstance(d,dict))
                        disabled=disabled or 'is disabled' in error.get('message','')
                    except (ValueError,TypeError):
                        disabled=False
                    raise self.failure('Gemini API is disabled in its Google Cloud project.' if disabled else
                               'Gemini access was denied for this key.',
                               'gemini_api_disabled' if disabled else 'gemini_credentials')
                if response.status_code in {400,401}:
                    raise self.failure('Gemini rejected the key or request.','gemini_credentials')
                if response.status_code==429:
                    raise self.failure('Gemini quota or rate limit was reached.','gemini_quota')
                raise self.failure(f'Gemini returned HTTP {response.status_code}.')
            raw=response.json()
            if not isinstance(raw,dict):
                raise ValueError('Invalid response envelope')
            candidate=raw.get('candidates',[{}])[0]
            if not isinstance(candidate,dict):
                raise ValueError('Invalid candidate')
            if candidate.get('finishReason')!='STOP':
                raise self.failure('Gemini returned a blocked or incomplete assessment.','gemini_response_invalid')
            text=''.join(p.get('text','') for p in candidate.get('content',{}).get('parts',[]) if not p.get('thought'))
            self.attempts.append({'model':raw.get('modelVersion',self.model),'content':text.replace(self.key,'[REDACTED]'),
                             'finish_reason':candidate['finishReason'],'usage':raw.get('usageMetadata')})
            return parse_response(text),raw.get('modelVersion',self.model)
        except requests.Timeout as error:
            raise self.failure('Gemini timed out.','gemini_timeout') from error
        except requests.RequestException as error:
            raise self.failure('Gemini could not be reached.') from error
        except (ValueError,KeyError,IndexError,TypeError,AttributeError) as error:
            raise self.failure('Gemini returned an invalid assessment.','gemini_response_invalid') from error
        finally:
            (self.folder/self.diagnostic).write_text(json.dumps(self.attempts,indent=2))

def generate_gemini_report(result,folder,key,model=DEFAULT_MODEL,timeout_s=30):
    folder=Path(folder)
    session=GeminiSession(folder,key,model,timeout_s)
    invoke,fail=session.invoke,session.failure
    started=session.started
    data=json.loads((folder/'landmarks.json').read_text())
    media=prepare_media(folder,result,data)
    positions=[]
    for phase in result['element_analysis']['phases']:
        available,position_prompt,openai_parts=position_request_parts(phase,media,folder)
        image_url=openai_parts[0]['image_url']['url']
        obj,_=invoke([{'inlineData':{'mimeType':'image/jpeg','data':image_url.split(',',1)[1]}},
                      {'text':position_prompt}],1000)
        try:
            readings=obj.get('positions')
            validate_positions(readings,{'element_analysis':{'phases':[phase]}},available)
        except (ValueError,KeyError,TypeError) as error:
            raise fail('Gemini returned invalid body-position readings.','gemini_response_invalid') from error
        positions.extend(readings)
    (folder/'gemini_positions.json').write_text(json.dumps(positions,indent=2))
    prompt=prompt_for(result,media,positions)
    (folder/'gemini_prompt.txt').write_text(prompt)
    video=folder/media['video']
    parts=[]
    # Keep inline requests well below Google's request-size limit.
    if video.stat().st_size<12*1024*1024:
        parts.append({'inlineData':{'mimeType':'video/mp4','data':base64.b64encode(video.read_bytes()).decode()}})
    parts.extend([{'inlineData':{'mimeType':'image/jpeg','data':base64.b64encode((folder/media['contact_sheet']).read_bytes()).decode()}},
                  {'text':prompt}])
    validated=None
    for attempt in range(2):
        obj,returned_model=invoke(parts)
        try:
            validated=validate_report(obj,result,media,positions)
            break
        except (ValueError,KeyError,TypeError) as error:
            if attempt:
                raise fail('Gemini could not produce a valid coaching assessment.','gemini_response_invalid') from error
            parts[-1]={'text':prompt+'\nCorrect the previous response problem: '+str(error)}
    sections=apply_visual_report(validated,result,media,returned_model,provider='Gemini')
    return {'generator':'Gemini whole-clip visual coaching','provider':'Gemini','primary_provider':'Gemini',
            'model':returned_model,'model_returned':returned_model,'requested_model':model,'fallback_used':False,
            'status':'completed','api_calls':session.calls,'gemini_api_calls':session.calls,'nvidia_api_calls':0,
            'elapsed_s':round(time.perf_counter()-started,3),'media':media,
            'input_mode':'whole video and timestamped close-ups' if len(parts)==3 else 'timestamped close-ups; video exceeds inline limit',
            'position_readings':positions,'model_assessment':validated,'sections':sections,
            'summary':result['element_analysis']['summary'],'errors':[],
            'content':'\n\n'.join(s['content'] for s in sections),
            'source':'video, sampled close-ups and MediaPipe measurements'}
