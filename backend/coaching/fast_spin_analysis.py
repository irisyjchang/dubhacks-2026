"""Fast coordinate-only coaching. Key stays in memory; deadline includes HTTP/generation."""
import getpass,json,time,os,signal
from pathlib import Path
import requests
OUT=Path(__file__).resolve().parent/'outputs/spin_analysis'
MODEL='nvidia/nemotron-3.5-lightning-30b-a3b'

def measured_fallback(metrics, elapsed):
 windows=metrics['time_windows']
 def med(start,side):
  return next(w[side+'_knee_2d_deg']['median'] for w in windows if w['start_s']==start)
 report=(
  '# Spin feedback from measured coordinates\n\n'
  f'NVIDIA did not complete within the deadline ({elapsed:.2f} seconds). '
  'This feedback is generated directly from the measurements, not by the language model.\n\n'
  '**Overall:** The estimates support a change into a deeper knee bend and later extension. '
  'They do not establish an overall spin-quality grade.\n\n'
  f'- At 0.5–1.0 s, accepted left-knee image-plane angles have a median of {med(.5,"left")}°. '
  f'At 3.0–3.5 s the median is {med(3,"left")}°, suggesting greater flexion.\n'
  f'- At 6.0–6.5 s, the accepted left-knee median increases to {med(6,"left")}°, '
  'consistent with extension in those samples. Supporting-leg identity is unverified.\n'
  '- Review the video around 3–5 s to check whether the intended low position stays clear through rotations. '
  'Changing angles alone do not prove wobble or poor control.\n'
  '- Review the rise near the end for a deliberate position change. A general practice cue is to '
  'establish the intended shape before changing it; these coordinates do not prove a transition fault.\n\n'
  '**Confidence:** Limited. Poses were found in 207/209 frames, but only 101 left-knee and '
  '92 right-knee frames passed the joint-confidence filter. Viewpoint, occlusion, and tracking '
  'errors affect the angles. Speed, revolutions, centering, blade edges, legal sit depth, and '
  'competition scores cannot be assessed from these measurements.\n')
 (OUT/'fast_coaching_report.md').write_text(report)
 return report

def main():
 key=os.getenv('NVIDIA_API_KEY') or getpass.getpass('NVIDIA API key (not saved): ')
 start=time.perf_counter()
 metrics=json.loads((OUT/'metrics.json').read_text())
 windows=[{'time_s':[w['start_s'],w['end_s']],'left_knee':w['left_knee_2d_deg'],'right_knee':w['right_knee_2d_deg']} for w in metrics['time_windows']]
 evidence={'duration_s':metrics['duration_s'],'pose_frames':'207/209','left_knee_valid_frames':101,'right_knee_valid_frames':92,'confidence_threshold':.65,'half_second_knee_angle_summaries':windows}
 prompt='''Give a short practical assessment of this figure-skating spin using only the supplied MediaPipe measurements. Reply in under 220 words: overall take, two supported timestamped observations, two review/practice priorities, and confidence. Smaller hip-knee-ankle angles mean deeper knee bends. These are image-plane estimates, affected by rotating viewpoint, camera motion, occlusion and possible left/right swaps. A 0.65 visibility/presence threshold is not an accuracy guarantee. No video is supplied. Never infer RPM, revolutions, centering, support leg, blade edges, falls, legal sit-position or official scores. Angle variability is not automatically wobble or a mistake. Offer useful tentative feedback; label unproven faults as questions to review, not established problems. Do not give a numerical quality score.\n'''+json.dumps(evidence,separators=(',',':'))
 payload={'model':MODEL,'messages':[{'role':'user','content':prompt}],'temperature':.2,'top_p':.9,'max_tokens':420,'stream':True,'chat_template_kwargs':{'enable_thinking':False}}
 (OUT/'fast_model_request.json').write_text(json.dumps(payload,indent=2))
 print('Requesting '+MODEL+'; hard deadline 45 seconds',flush=True)
 def deadline(*_): raise TimeoutError('45-second total deadline reached')
 signal.signal(signal.SIGALRM,deadline);signal.alarm(45)
 first=None;parts=[];finish=None;result={}
 try:
  with requests.post('https://integrate.api.nvidia.com/v1/chat/completions',headers={'Authorization':'Bearer '+key},json=payload,stream=True,timeout=(8,40)) as r:
   r.raise_for_status()
   for line in r.iter_lines(chunk_size=1):
    if not line.startswith(b'data:'):continue
    raw=line[5:].strip()
    if raw==b'[DONE]':break
    obj=json.loads(raw)
    if obj.get('error'):raise RuntimeError(str(obj['error']))
    result.update({k:obj[k] for k in ['id','model','usage'] if obj.get(k)is not None})
    for choice in obj.get('choices',[]):
     content=choice.get('delta',{}).get('content')
     if content:
      if first is None:
       first=round(time.perf_counter()-start,3);print('First answer token: '+str(first)+' seconds',flush=True)
      parts.append(content)
     finish=choice.get('finish_reason') or finish
  if not finish:raise RuntimeError('Incomplete stream')
  elapsed=round(time.perf_counter()-start,3)
  report=''.join(parts)
  if not report.strip():raise RuntimeError('Empty answer')
  record={'model':MODEL,'first_answer_token_s':first,'total_s':elapsed,'finish_reason':finish,'content':report,**result}
  (OUT/'fast_model_response.json').write_text(json.dumps(record,indent=2))
  (OUT/'fast_coaching_report.md').write_text('# Fast spin analysis\n\nModel: `'+MODEL+'`. First answer: '+str(first)+' s. Complete: '+str(elapsed)+' s.\n\n'+report+'\n\nThis is a prompted, coordinate-only experiment, not validated competition scoring.\n')
  print('Complete: '+str(elapsed)+' seconds; finish: '+str(finish)+'\n'+report,flush=True)
 except Exception as e:
  elapsed=round(time.perf_counter()-start,3)
  (OUT/'fast_model_failure.json').write_text(json.dumps({'model':MODEL,'elapsed_s':elapsed,'error':str(e).replace(key,'[REDACTED]')},indent=2))
  print('Failed after '+str(elapsed)+' seconds: '+str(e).replace(key,'[REDACTED]'),flush=True)
  signal.alarm(0)
  print(measured_fallback(metrics,elapsed),flush=True)
 finally:signal.alarm(0)
if __name__=='__main__':main()
