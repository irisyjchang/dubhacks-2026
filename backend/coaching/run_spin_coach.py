"""Process one skating video locally. No account, API key, or interface required."""
import time
BOOT=time.perf_counter()

import argparse
import json
import os
import getpass
from pathlib import Path

from spincoach.analysis import analyze
from spincoach.video import prepare,extract
from spincoach.artifacts import render,plot,write_report
from spincoach.narrative import write_assessment
from spincoach.kinematics import build_kinematics
from spincoach.elements import ELEMENTS,apply_element,motion_suggestion
from spincoach.element_feedback import finish_element_report
from spincoach.person_tracking import request_track,save_dense_track
from spincoach.element_recognition import identify_element

ROOT=Path(__file__).resolve().parent


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input',type=Path,default=ROOT/'videos/IMG_5943.mov')
    parser.add_argument('--output',type=Path)
    parser.add_argument('--model',type=Path,default=ROOT/'models/pose_landmarker_heavy.task')
    parser.add_argument('--nvidia-report',action='store_true',help='Ask NVIDIA for a timestamped visual coaching report')
    parser.add_argument('--gemini-report',action='store_true',help='Try Gemini first; add --nvidia-report for NVIDIA fallback')
    parser.add_argument('--gemini-model',default='gemini-3.5-flash')
    parser.add_argument('--report-timeout',type=int,default=75,help='Maximum model request time in seconds')
    parser.add_argument('--llm-model',default='nvidia/nemotron-3.5-super-vl-120b-a12b',help='NVIDIA vision model used with --nvidia-report')
    parser.add_argument('--element',choices=list(ELEMENTS),default='unknown')
    parser.add_argument('--analyze-only',action='store_true',help='Track and suggest an element, then wait for user confirmation')
    parser.add_argument('--resume',action='store_true',help='Use the existing prepared video and measurements')
    parser.add_argument('--perceptron-track',action='store_true',help='Use PERCEPTRON_API_KEY for whole-person box tracking')
    parser.add_argument('--phase-markers',default='{}',help='JSON with optional user-marked phase times')
    args=parser.parse_args()
    if not args.input.is_file():
        parser.error(f'Input not found: {args.input}')
    if not args.model.is_file():
        parser.error('MediaPipe model missing. Run the model download command in README.md first.')
    if args.report_timeout<=0:
        parser.error('--report-timeout must be positive')
    person_key=os.getenv('PERCEPTRON_API_KEY','') if args.perceptron_track else ''
    if args.perceptron_track and not person_key and not args.resume:
        parser.error('Set PERCEPTRON_API_KEY to use --perceptron-track')
    key=(os.getenv('NVIDIA_API_KEY') or getpass.getpass('NVIDIA API key (not saved): ')) if args.nvidia_report else None
    gemini_key=(os.getenv('GEMINI_API_KEY') or getpass.getpass('Gemini API key (not saved): ')) if args.gemini_report else None
    folder=args.output or ROOT/'outputs/local_coach'/args.input.stem
    folder.mkdir(parents=True,exist_ok=True)
    if args.input.resolve().parent==folder.resolve():
        parser.error('Choose an output directory separate from the input directory.')
    timings={'imports':round(time.perf_counter()-BOOT,3)}
    t=time.perf_counter()
    prepared=folder/'input.mp4'
    if prepared.resolve()==args.input.resolve():
        parser.error('Input and prepared-video paths must differ.')
    if args.resume:
        data=json.loads((folder/'landmarks.json').read_text())
        result=json.loads((folder/'analysis.json').read_text())
        timings={**result.get('timing_s',{}),'resume_imports':timings['imports']}
        t=time.perf_counter()
    else:
        print('Preparing video...',flush=True)
        prepare(args.input,prepared)
        timings['preparation']=round(time.perf_counter()-t,3)
        person_track={'provider':'MediaPipe','status':'local','anchors':[],'api_calls':0}
        if person_key:
            print('Tracking the main skater bounding box with Perceptron...',flush=True)
            person_track=request_track(prepared,person_key,folder/'person_tracking.json')
            timings['person_tracking']=person_track['elapsed_s']
            if person_track.get('warning'):
                print(person_track['warning'],flush=True)
        t=time.perf_counter()
        print('Tracking the main skater and background motion locally...',flush=True)
        data,camera=extract(prepared,args.model,folder/'landmarks.json',person_track=person_track)
        timings['pose_and_camera']=round(time.perf_counter()-t,3)
        t=time.perf_counter()
        result=analyze(data,camera)
        result['person_tracking']=save_dense_track(person_track,data,folder/'person_tracking.json')
        result['original_source']=str(args.input)
        result['kinematics']=build_kinematics(data,result)
        result['element_suggestion']=motion_suggestion(data,result)
    (folder/'kinematics.json').write_text(json.dumps(result['kinematics'],indent=2))
    for row,measured in zip(result['frames'],result['kinematics']['frames']):
        row.update(measured['values'])
    timings['analysis']=round(time.perf_counter()-t,3)
    if not args.resume:
        print('Coaching service: identifying the movement from the video...',flush=True)
        result['element_suggestion']=identify_element(folder,data,result,result['element_suggestion'],
            gemini_key=gemini_key,nvidia_key=key,gemini_model=args.gemini_model,nvidia_model=args.llm_model)
        timings['element_identification']=result['element_suggestion']['elapsed_s']
    identification=result.get('element_suggestion',{})
    tracking_calls=result.get('person_tracking',{}).get('api_calls',0)
    identification_calls=identification.get('api_calls',0)
    result['cost']={'api_calls':tracking_calls+identification_calls,'perceptron_api_calls':tracking_calls,
                    'identification_api_calls':identification_calls,
                    'gemini_api_calls':identification.get('gemini_api_calls',0),
                    'nvidia_api_calls':identification.get('nvidia_api_calls',0),
                    'model_inference':'local CPU + remote Perceptron tracking' if tracking_calls else 'local CPU'}
    if identification_calls:
        result['cost']['model_inference']+=' + remote element identification'
    if args.analyze_only:
        result['timing_s']=timings
        (folder/'analysis.json').write_text(json.dumps(result,indent=2))
        print('Ready for element confirmation.',flush=True)
        return
    apply_element(result,data,args.element,json.loads(args.phase_markers))
    print(result['headline'],flush=True)
    t=time.perf_counter()
    result['timing_s']=timings
    t=time.perf_counter()
    print('Generating the coaching report...',flush=True)
    narrative=write_assessment(result,folder,key=key,model=args.llm_model,timeout_s=args.report_timeout,
                               gemini_key=gemini_key,gemini_model=args.gemini_model)
    narrative=finish_element_report(narrative,result,folder)
    timings['coaching_report']=round(time.perf_counter()-t,3)
    timings['total']=round(sum(value for name,value in timings.items() if name not in {'total','coaching_report','rendering'})+timings['coaching_report'],3)
    result['coaching_report']={k:v for k,v in narrative.items() if k!='content'}
    result['cost']['api_calls']+=narrative['api_calls']
    result['cost']['nvidia_api_calls']+=narrative.get('nvidia_api_calls',narrative['api_calls'] if key else 0)
    result['cost']['gemini_api_calls']+=narrative.get('gemini_api_calls',0)
    if key or gemini_key:
        result['cost']['model_inference']+=' + remote '+narrative.get('provider','NVIDIA')+' coaching'
    t=time.perf_counter()
    print('Rendering evidence and timed coaching captions...',flush=True)
    count=render(prepared,data,result,folder,coaching=narrative)
    if count!=len(result['frames']):
        raise RuntimeError('Rendered frame count does not match the analysis')
    plot(result,folder)
    timings['rendering']=round(time.perf_counter()-t,3)
    timings['total']=round(sum(value for name,value in timings.items() if name!='total'),3)
    write_report(result,folder)
    print(json.dumps({'output_directory':str(folder),'timing_s':timings,
                      'tracking':result['tracking'],'lowered_segment':result['lowered_segment']},indent=2),flush=True)


if __name__=='__main__':
    from spincoach.errors import CoachingServiceError,ProcessingFailure
    try:
        main()
    except (CoachingServiceError,ProcessingFailure) as error:
        import sys
        print('SPINCOACH_ERROR '+json.dumps({'message':str(error),'code':error.code,
                                           'retryable':error.retryable}),file=sys.stderr,flush=True)
        raise SystemExit(1)
