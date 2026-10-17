"""Track the main skater with MediaPipe and export a video and landmark JSON.

Run: .video-venv/bin/python mediapipe_skater.py
"""
from __future__ import annotations

import argparse
import json
import subprocess
from pathlib import Path

import cv2
import imageio_ffmpeg
import mediapipe as mp
import numpy as np
from mediapipe.tasks import python
from mediapipe.tasks.python import vision

ROOT = Path(__file__).resolve().parent
NAMES = [
    'nose', 'left_eye_inner', 'left_eye', 'left_eye_outer', 'right_eye_inner',
    'right_eye', 'right_eye_outer', 'left_ear', 'right_ear', 'mouth_left',
    'mouth_right', 'left_shoulder', 'right_shoulder', 'left_elbow',
    'right_elbow', 'left_wrist', 'right_wrist', 'left_pinky', 'right_pinky',
    'left_index', 'right_index', 'left_thumb', 'right_thumb', 'left_hip',
    'right_hip', 'left_knee', 'right_knee', 'left_ankle', 'right_ankle',
    'left_heel', 'right_heel', 'left_foot_index', 'right_foot_index',
]
LINKS = [
    (0,1),(1,2),(2,3),(3,7),(0,4),(4,5),(5,6),(6,8),(9,10),
    (11,12),(11,13),(13,15),(15,17),(15,19),(15,21),(17,19),
    (12,14),(14,16),(16,18),(16,20),(16,22),(18,20),
    (11,23),(12,24),(23,24),(23,25),(24,26),(25,27),(26,28),
    (27,29),(28,30),(29,31),(30,32),(27,31),(28,32),
]


def geometry(landmarks):
    points = np.array([[p.x, p.y] for p in landmarks])
    visible = np.array([p.visibility >= .3 for p in landmarks])
    good = points[visible & np.isfinite(points).all(axis=1)]
    if len(good) < 6:
        return None
    lo, hi = good.min(axis=0), good.max(axis=0)
    center = points[[11,12,23,24]].mean(axis=0)
    return lo, hi, center, float(np.prod(np.maximum(hi-lo, .001)))


def select_pose(result, previous):
    candidates = []
    for idx, landmarks in enumerate(result.pose_landmarks):
        shape = geometry(landmarks)
        if shape is None:
            continue
        lo, hi, center, area = shape
        # The foreground skater is the largest person. Temporal proximity
        # keeps the selected identity stable as other skaters pass behind.
        score = area
        if previous is not None:
            distance = np.linalg.norm(center-previous)
            score *= np.exp(-4 * distance)
        candidates.append((score, idx, shape))
    return max(candidates, key=lambda item: item[0]) if candidates else None


def draw(frame, record):
    h, w = frame.shape[:2]
    scale = w / 1080
    if record['landmarks']:
        points = record['landmarks']
        xy = [(round(p['x_px']), round(p['y_px'])) for p in points]
        valid = [p['visibility'] >= .35 and p['presence'] >= .35 and
                 0 <= p['x_px'] < w and 0 <= p['y_px'] < h for p in points]
        for a,b in LINKS:
            if valid[a] and valid[b]:
                color = (80,240,120) if 'left' in NAMES[b] else (255,205,65)
                cv2.line(frame, xy[a], xy[b], (25,25,25), max(3,round(8*scale)), cv2.LINE_AA)
                cv2.line(frame, xy[a], xy[b], color, max(2,round(4*scale)), cv2.LINE_AA)
        for i,p in enumerate(points):
            if valid[i]:
                cv2.circle(frame, xy[i], max(3,round(6*scale)), (20,20,20), -1, cv2.LINE_AA)
                color = (80,240,120) if 'left' in NAMES[i] else (255,205,65)
                cv2.circle(frame, xy[i], max(2,round(4*scale)), color, -1, cv2.LINE_AA)
        x,y,bw,bh = record['bbox_xywh_px']
        cv2.rectangle(frame,(round(x),round(y)),(round(x+bw),round(y+bh)),(80,240,120),max(1,round(2*scale)),cv2.LINE_AA)
    overlay = frame.copy()
    cv2.rectangle(overlay,(0,0),(w,round(125*scale)),(20,24,28),-1)
    cv2.addWeighted(overlay,.78,frame,.22,0,frame)
    font = cv2.FONT_HERSHEY_SIMPLEX
    cv2.putText(frame,'MEDIAPIPE  /  MAIN SKATER',(round(28*scale),round(47*scale)),font,.9*scale,(245,245,245),max(1,round(2*scale)),cv2.LINE_AA)
    visible = sum(p['visibility'] >= .35 for p in record['landmarks'])
    label = f"{record['timestamp_ms']/1000:.2f}s   |   {visible}/33 visible points" if record['landmarks'] else f"{record['timestamp_ms']/1000:.2f}s   |   Pose not detected"
    cv2.putText(frame,label,(round(28*scale),round(91*scale)),font,.68*scale,(190,205,210),max(1,round(2*scale)),cv2.LINE_AA)
    return frame


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input',type=Path,default=ROOT/'outputs/IMG_5943_input.mp4')
    parser.add_argument('--output',type=Path,default=ROOT/'outputs/IMG_5943_mediapipe.mp4')
    parser.add_argument('--model',type=Path,default=ROOT/'models/pose_landmarker_heavy.task')
    args = parser.parse_args()
    args.output.parent.mkdir(parents=True,exist_ok=True)
    cap = cv2.VideoCapture(str(args.input))
    if not cap.isOpened():
        raise RuntimeError(f'Cannot open {args.input}')
    w,h = int(cap.get(3)),int(cap.get(4))
    fps = cap.get(cv2.CAP_PROP_FPS)
    count = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    silent = args.output.with_name(args.output.stem+'_silent.mp4')
    ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()
    encoder = subprocess.Popen([ffmpeg,'-hide_banner','-loglevel','error','-y',
        '-f','rawvideo','-pix_fmt','bgr24','-s',f'{w}x{h}','-r',str(fps),
        '-i','pipe:0','-an','-c:v','libx264','-preset','fast','-crf','18',
        '-pix_fmt','yuv420p','-movflags','+faststart',str(silent)],stdin=subprocess.PIPE)
    options = vision.PoseLandmarkerOptions(
        base_options=python.BaseOptions(model_asset_path=str(args.model)),
        running_mode=vision.RunningMode.VIDEO,num_poses=4,
        min_pose_detection_confidence=.35,min_pose_presence_confidence=.35,
        min_tracking_confidence=.45)
    records=[]
    previous=None
    missing=0
    try:
        with vision.PoseLandmarker.create_from_options(options) as model:
            while True:
                ok,frame=cap.read()
                if not ok:
                    break
                index=len(records)
                stamp=round(index*1000/fps)
                rgb=np.ascontiguousarray(cv2.cvtColor(frame,cv2.COLOR_BGR2RGB))
                result=model.detect_for_video(mp.Image(image_format=mp.ImageFormat.SRGB,data=rgb),stamp)
                selected=select_pose(result,previous)
                record={'frame_id':index,'timestamp_ms':stamp,'track_id':1,
                        'landmarks':[],'world_landmarks':[],'bbox_xywh_px':None}
                if selected is not None:
                    _,idx,(lo,hi,center,area)=selected
                    previous=center
                    missing=0
                    for j,p in enumerate(result.pose_landmarks[idx]):
                        record['landmarks'].append({'id':j,'name':NAMES[j],
                            'x':p.x,'y':p.y,'z':p.z,'x_px':p.x*w,'y_px':p.y*h,
                            'visibility':p.visibility,'presence':p.presence})
                    for j,p in enumerate(result.pose_world_landmarks[idx]):
                        record['world_landmarks'].append({'id':j,'name':NAMES[j],
                            'x':p.x,'y':p.y,'z':p.z,'visibility':p.visibility})
                    lo=np.maximum([0,0],lo*[w,h]-25)
                    hi=np.minimum([w-1,h-1],hi*[w,h]+25)
                    record['bbox_xywh_px']=[float(lo[0]),float(lo[1]),float(hi[0]-lo[0]),float(hi[1]-lo[1])]
                else:
                    missing+=1
                    if missing>15:
                        previous=None
                records.append(record)
                annotated=draw(frame,record)
                encoder.stdin.write(annotated.tobytes())
                if index%30==0:
                    print(f'Processed {index+1}/{count} frames; pose: {selected is not None}',flush=True)
    finally:
        cap.release()
        encoder.stdin.close()
        code=encoder.wait()
    if code:
        raise RuntimeError(f'Video encoder failed: {code}')
    subprocess.run([ffmpeg,'-hide_banner','-loglevel','error','-y','-i',str(silent),
        '-i',str(args.input),'-map','0:v:0','-map','1:a?','-c:v','copy',
        '-c:a','aac','-shortest','-movflags','+faststart',str(args.output)],check=True)
    silent.unlink()
    detected=sum(bool(r['landmarks']) for r in records)
    data={'source':str(args.input),'model':'MediaPipe Pose Landmarker Heavy',
          'width':w,'height':h,'fps':fps,'frame_count':len(records),
          'frames_with_pose':detected,'world_coordinates':'meters, hip-relative',
          'bbox_source':'extent of visible MediaPipe landmarks plus 25px padding',
          'frames':records}
    args.output.with_suffix('.json').write_text(json.dumps(data,indent=2))
    print(f'Done: {detected}/{len(records)} frames have poses. Video: {args.output}',flush=True)


if __name__=='__main__':
    main()
