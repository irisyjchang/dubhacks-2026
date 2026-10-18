"""Try Gemini first, then reuse the established NVIDIA pipeline on failure."""
import json
import time
from pathlib import Path

from spincoach.gemini_judge import generate_gemini_report,GeminiFailure,DEFAULT_MODEL as GEMINI_MODEL
from spincoach.visual_judge import generate_visual_report,DEFAULT_MODEL as NVIDIA_MODEL
from spincoach.errors import ProcessingFailure


def generate_coaching_report(result,folder,nvidia_key=None,gemini_key=None,
                             nvidia_model=NVIDIA_MODEL,gemini_model=GEMINI_MODEL,timeout_s=75):
    started=time.perf_counter();failure=None
    (Path(folder)/'provider_fallback.json').unlink(missing_ok=True)
    if gemini_key:
        print('Coaching service: trying Gemini first...',flush=True)
        try:
            return generate_gemini_report(result,folder,gemini_key,gemini_model,
                                          min(30,timeout_s*.5) if nvidia_key else timeout_s)
        except GeminiFailure as error:
            failure=error
            (Path(folder)/'provider_fallback.json').write_text(json.dumps({
                'primary_provider':'Gemini','code':error.code,'reason':str(error),
                'api_calls':error.calls,'elapsed_s':error.elapsed_s},indent=2))
            if not nvidia_key:
                raise ProcessingFailure(str(error)+' No NVIDIA fallback key is configured.',error.code,True) from error
            print('Coaching service: '+str(error)+' Using NVIDIA fallback...',flush=True)
    remaining=timeout_s-(time.perf_counter()-started)
    if remaining<2:
        raise ProcessingFailure('Coaching exceeded its time budget. Retry using saved tracking.','coaching_timeout',True)
    report=generate_visual_report(result,folder,nvidia_key,nvidia_model,remaining)
    report['provider']='NVIDIA'
    report['primary_provider']='Gemini' if gemini_key else 'NVIDIA'
    report['nvidia_api_calls']=report['api_calls']
    report['gemini_api_calls']=failure.calls if failure else 0
    report['api_calls']+=report['gemini_api_calls']
    report['elapsed_s']=round(time.perf_counter()-started,3)
    if failure:
        report.update(fallback_used=True,fallback_from='Gemini',
                      fallback_reason=str(failure),fallback_code=failure.code)
    return report
