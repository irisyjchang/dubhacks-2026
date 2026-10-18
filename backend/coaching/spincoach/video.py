"""Video preparation, local pose inference and background camera-motion estimates."""
from __future__ import annotations

import json
import math
import subprocess
from pathlib import Path

import cv2
import imageio_ffmpeg
import mediapipe as mp
import numpy as np
from mediapipe.tasks import python
from mediapipe.tasks.python import vision

from mediapipe_skater import NAMES
from spincoach.person_tracking import box_at,select_tracked_pose,refine_box


def prepare(source, destination):
    subprocess.run([imageio_ffmpeg.get_ffmpeg_exe(),'-hide_banner','-loglevel','error','-y',
        '-i',str(source),'-map','0:v:0','-map','0:a?',
        '-vf','scale=w=1280:h=1280:force_original_aspect_ratio=decrease:force_divisible_by=2',
        '-c:v','libx264','-preset','veryfast','-crf','19','-pix_fmt','yuv420p',
        '-c:a','aac','-movflags','+faststart',str(destination)],check=True)


class CameraMotion:
    def __init__(self):
        self.previous = None
        self.previous_box = None
        self.translation = []
        self.rotations = []
        self.inlier_ratios = []
        self.attempted = 0

    def update(self, frame, bbox):
        scale = 384/frame.shape[1]
        small = cv2.resize(frame,(384,round(frame.shape[0]*scale)))
        gray = cv2.cvtColor(small,cv2.COLOR_BGR2GRAY)
        if self.previous is not None:
            self.attempted += 1
            mask = np.full_like(gray,255)
            if self.previous_box:
                x,y,w,h = [v*scale for v in self.previous_box]
                cv2.rectangle(mask,(max(0,int(x-w*.3)),max(0,int(y-h*.3))),
                    (min(gray.shape[1],int(x+w*1.3)),min(gray.shape[0],int(y+h*1.3))),0,-1)
            points = cv2.goodFeaturesToTrack(self.previous,maxCorners=160,qualityLevel=.02,minDistance=7,mask=mask)
            if points is not None and len(points) >= 15:
                target,status,error = cv2.calcOpticalFlowPyrLK(self.previous,gray,points,None,
                    winSize=(21,21),maxLevel=3)
                if target is not None:
                    valid = status[:,0].astype(bool) & (error[:,0] < 25)
                    if valid.sum() >= 12:
                        affine,inliers = cv2.estimateAffinePartial2D(points[valid],target[valid],
                            method=cv2.RANSAC,ransacReprojThreshold=2,maxIters=500)
                        if affine is not None and inliers is not None and inliers.mean() >= .55:
                            self.translation.append(float(np.linalg.norm(affine[:,2])/384))
                            self.rotations.append(abs(math.degrees(math.atan2(affine[1,0],affine[0,0]))))
                            self.inlier_ratios.append(float(inliers.mean()))
        self.previous,self.previous_box = gray,bbox

    def summary(self):
        return {'attempted_pairs':self.attempted,'accepted_pairs':len(self.translation),
                'estimated_motion_frame_widths':round(sum(self.translation),3),
                'total_abs_rotation_deg':round(sum(self.rotations),2),
                'median_inlier_ratio':round(float(np.median(self.inlier_ratios)),3) if self.inlier_ratios else None,
                'meaning':'sum of background affine motion magnitudes; camera-motion indicator, not skater travel'}


def extract(video, model_path, output, person_track=None):
    cap = cv2.VideoCapture(str(video))
    if not cap.isOpened():
        raise RuntimeError(f'Cannot decode {video}')
    w,h = int(cap.get(3)),int(cap.get(4))
    fps = cap.get(cv2.CAP_PROP_FPS)
    frames=[]
    previous=None
    missing=0
    camera=CameraMotion()
    opts = vision.PoseLandmarkerOptions(base_options=python.BaseOptions(model_asset_path=str(model_path)),
        running_mode=vision.RunningMode.VIDEO,num_poses=4,min_pose_detection_confidence=.35,
        min_pose_presence_confidence=.35,min_tracking_confidence=.45,output_segmentation_masks=True)
    try:
        with vision.PoseLandmarker.create_from_options(opts) as model:
            while True:
                ok,frame=cap.read()
                if not ok:
                    break
                idx=len(frames)
                stamp=round(idx*1000/fps)
                result=model.detect_for_video(mp.Image(image_format=mp.ImageFormat.SRGB,
                    data=np.ascontiguousarray(cv2.cvtColor(frame,cv2.COLOR_BGR2RGB))),stamp)
                observation=box_at(person_track,idx/fps) if person_track else None
                chosen=select_tracked_pose(result,previous,observation,w,h)
                record={'frame_id':idx,'timestamp_ms':stamp,'track_id':1,'landmarks':[],
                        'world_landmarks':[],'bbox_xywh_px':None,'silhouette_aspect':None,
                        'person_bbox_xywh_px':observation['bbox_xywh_px'] if observation else None,
                        'person_bbox_source':observation['source'] if observation else None}
                if observation:
                    record['person_bbox_evidence']={k:v for k,v in observation.items()
                                                    if k not in {'time_s'}}
                if chosen:
                    _,person,(lo,hi,previous,area)=chosen
                    missing=0
                    for j,p in enumerate(result.pose_landmarks[person]):
                        record['landmarks'].append({'id':j,'name':NAMES[j],'x':p.x,'y':p.y,'z':p.z,
                            'x_px':p.x*w,'y_px':p.y*h,'visibility':p.visibility,'presence':p.presence})
                    for j,p in enumerate(result.pose_world_landmarks[person]):
                        record['world_landmarks'].append({'id':j,'name':NAMES[j],'x':p.x,'y':p.y,
                                                         'z':p.z,'visibility':p.visibility})
                    lo=np.maximum([0,0],lo*[w,h]-20)
                    hi=np.minimum([w-1,h-1],hi*[w,h]+20)
                    record['bbox_xywh_px']=[float(lo[0]),float(lo[1]),float(hi[0]-lo[0]),float(hi[1]-lo[1])]
                    if not observation:
                        record['person_bbox_xywh_px']=record['bbox_xywh_px']
                        record['person_bbox_source']='mediapipe'
                    else:
                        refined=refine_box(observation['bbox_xywh_px'],record['landmarks'],w,h)
                        if any(abs(a-b)>1 for a,b in zip(refined,observation['bbox_xywh_px'])):
                            record['person_bbox_xywh_px']=refined
                            record['person_bbox_source']='fused'
                    if result.segmentation_masks:
                        mask=np.squeeze(result.segmentation_masks[person].numpy_view())
                        ys,xs=np.where(mask>.6)
                        if len(xs)>100:
                            x0,x1=np.percentile(xs,[1,99]);y0,y1=np.percentile(ys,[1,99])
                            if x1-x0>8:
                                record['silhouette_aspect']=float((y1-y0)/(x1-x0))
                else:
                    missing+=1
                    if missing>15:
                        previous=None
                camera.update(frame,record['person_bbox_xywh_px'])
                frames.append(record)
    finally:
        cap.release()
    if not frames:
        raise RuntimeError('The input has no decodable frames')
    data={'source':str(video),'width':w,'height':h,'fps':fps,'frame_count':len(frames),
          'frames_with_pose':sum(bool(r['landmarks']) for r in frames),
          'model':'MediaPipe Pose Landmarker Heavy','frames':frames}
    Path(output).write_text(json.dumps(data,separators=(',',':')))
    return data,camera.summary()
