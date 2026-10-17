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

ROOT=Path(__file__).resolve().parent


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input',type=Path,default=ROOT/'videos/IMG_5943.mov')
    parser.add_argument('--output',type=Path)
    parser.add_argument('--model',type=Path,default=ROOT/'models/pose_landmarker_heavy.task')
    parser.add_argument('--nvidia-report',action='store_true',help='Ask NVIDIA for a timestamped visual coaching report')
    parser.add_argument('--report-timeout',type=int,default=75,help='Maximum model request time in seconds')
    parser.add_argument('--llm-model',default='google/diffusiongemma-26b-a4b-it',help='NVIDIA text model used with --nvidia-report')
    args=parser.parse_args()
    if not args.input.is_file():
        parser.error(f'Input not found: {args.input}')
    if not args.model.is_file():
        parser.error('MediaPipe model missing. Run the model download command in README.md first.')
    if args.report_timeout<=0:
        parser.error('--report-timeout must be positive')
    key=(os.getenv('NVIDIA_API_KEY') or getpass.getpass('NVIDIA API key (not saved): ')) if args.nvidia_report else None
    folder=args.output or ROOT/'outputs/local_coach'/args.input.stem
    folder.mkdir(parents=True,exist_ok=True)
    if args.input.resolve().parent==folder.resolve():
        parser.error('Choose an output directory separate from the input directory.')
    timings={'imports':round(time.perf_counter()-BOOT,3)}
    t=time.perf_counter()
    prepared=folder/'input.mp4'
    if prepared.resolve()==args.input.resolve():
        parser.error('Input and prepared-video paths must differ.')
    print('Preparing video...',flush=True)
    prepare(args.input,prepared)
    timings['preparation']=round(time.perf_counter()-t,3)
    t=time.perf_counter()
    print('Tracking the main skater and background motion locally...',flush=True)
    data,camera=extract(prepared,args.model,folder/'landmarks.json')
    timings['pose_and_camera']=round(time.perf_counter()-t,3)
    t=time.perf_counter()
    result=analyze(data,camera)
    result['original_source']=str(args.input)
    result['kinematics']=build_kinematics(data,result)
    (folder/'kinematics.json').write_text(json.dumps(result['kinematics'],indent=2))
    for row,measured in zip(result['frames'],result['kinematics']['frames']):
        row.update(measured['values'])
    timings['analysis']=round(time.perf_counter()-t,3)
    print(result['headline'],flush=True)
    t=time.perf_counter()
    result['timing_s']=timings
    result['cost']={'api_calls':0,'paid_services':False,'model_inference':'local CPU'}
    t=time.perf_counter()
    print('Generating the coaching report...',flush=True)
    narrative=write_assessment(result,folder,key=key,model=args.llm_model,timeout_s=args.report_timeout)
    timings['coaching_report']=round(time.perf_counter()-t,3)
    timings['total']=round(time.perf_counter()-BOOT,3)
    result['coaching_report']={k:v for k,v in narrative.items() if k!='content'}
    result['cost']['api_calls']=narrative['api_calls']
    t=time.perf_counter()
    print('Rendering evidence and timed coaching captions...',flush=True)
    count=render(prepared,data,result,folder,coaching=narrative)
    if count!=len(result['frames']):
        raise RuntimeError('Rendered frame count does not match the analysis')
    plot(result,folder)
    timings['rendering']=round(time.perf_counter()-t,3)
    timings['total']=round(time.perf_counter()-BOOT,3)
    write_report(result,folder)
    print(json.dumps({'output_directory':str(folder),'timing_s':timings,
                      'tracking':result['tracking'],'lowered_segment':result['lowered_segment']},indent=2),flush=True)


if __name__=='__main__':
    main()
