"""Render the measurements, evidence frames and plain-language report."""
from __future__ import annotations

import json
import subprocess
from pathlib import Path

import cv2
import imageio_ffmpeg
import numpy as np

from mediapipe_skater import LINKS
from spincoach.captions import caption_timeline, active_caption


def annotate(frame, pose, row, analysis, caption=None):
    h,w = frame.shape[:2]
    scale = w/720
    p=pose['landmarks']
    if p:
        xy=[(round(j['x_px']),round(j['y_px'])) for j in p]
        q=[min(j['visibility'],j['presence']) for j in p]
        good=[q[i]>=.35 and 0<=xy[i][0]<w and 0<=xy[i][1]<h for i in range(33)]
        for a,b in LINKS:
            if good[a] and good[b]:
                color=(80,235,140) if min(q[a],q[b])>=.65 else (140,150,155)
                cv2.line(frame,xy[a],xy[b],(15,20,20),max(2,round(5*scale)),cv2.LINE_AA)
                cv2.line(frame,xy[a],xy[b],color,max(1,round(2*scale)),cv2.LINE_AA)
        for i in range(33):
            if good[i]:
                cv2.circle(frame,xy[i],max(2,round(4*scale)),(70,235,140) if q[i]>=.65 else (140,150,155),-1,cv2.LINE_AA)
    def band(y1,y2):
        overlay=frame.copy()
        cv2.rectangle(overlay,(0,y1),(w,y2),(23,27,33),-1)
        cv2.addWeighted(overlay,.9,frame,.1,0,frame)
    def text(s,y,size=.65,color=(235,240,243)):
        cv2.putText(frame,s,(round(22*scale),round(y)),cv2.FONT_HERSHEY_SIMPLEX,
                    size*scale,color,max(1,round(1.6*scale)),cv2.LINE_AA)
    if caption:
        band(0,round(159*scale))
        a,b=caption['start_s'],caption['end_s']
        text(f'SPIN COACH  |  {a:g}-{b:g}s  |  COACHING CUE',32*scale,.49,(125,225,190))
        lines=caption['lines']
        # Fit two lines inside the video width, including longer model sentences.
        font=.72
        while True:
            if len(lines)==1:
                words=lines[0].split()
                splits=[[' '.join(words[:i]),' '.join(words[i:])] for i in range(1,len(words))]
                fitted=min(splits,key=lambda pair:max(cv2.getTextSize(s,cv2.FONT_HERSHEY_SIMPLEX,font*scale,1)[0][0] for s in pair)) if splits else lines
            else:
                fitted=lines
            if all(cv2.getTextSize(s,cv2.FONT_HERSHEY_SIMPLEX,font*scale,max(1,round(1.6*scale)))[0][0]<=w-44*scale for s in fitted):
                break
            font*=.94
        for i,line in enumerate(fitted):
            text(line,(82+i*40)*scale,font)
    else:
        band(0,round(110*scale))
        text('SPIN COACH  |  LOCAL ANALYSIS',40*scale,.72)
        text(f"{row['time_s']:.2f}s   {row['phase'].upper()}",80*scale,.59)
    band(h-round(185*scale),h)
    y=h-150*scale
    def joint(side,name):
        v=row.get(side+'_'+name+'_deg')
        return f'{v:.0f} deg' if v is not None else 'uncertain'
    text(f"Knees: L {joint('left','knee')} / R {joint('right','knee')}",y,.58)
    cue=('Full advice: coaching_report.md' if caption else
         'Review depth through each rotation' if row['phase']=='lowered posture' else
         'Review the rise and arm/free-leg control' if row['phase']=='rise / transition' else
         'Watch the change into the intended shape' if row['phase']=='lowering / approach' else
         'Pose uncertain: avoid technique judgments')
    if analysis.get('kinematics'):
        text(f"Elbows: L {joint('left','elbow')} / R {joint('right','elbow')}",y+43*scale,.56)
        text('2D angles; L/R labels are not support/free legs.',y+85*scale,.46,(170,185,193))
    else:
        text(cue,y+43*scale,.56)
        text('Green: higher confidence. Gray: uncertain.',y+85*scale,.5,(170,185,193))
    text('Review cues, not a competition score.',y+120*scale,.5,(170,185,193))
    return frame


def render(video, data, analysis, folder, coaching=None, summaries=None):
    folder=Path(folder)
    timeline=caption_timeline(coaching,summaries)
    output=folder/'feedback.mp4'
    silent=folder/'feedback_silent.mp4'
    w,h=data['width'],data['height']
    fps=data['fps']
    ff=imageio_ffmpeg.get_ffmpeg_exe()
    encoder=subprocess.Popen([ff,'-hide_banner','-loglevel','error','-y','-f','rawvideo',
        '-pix_fmt','bgr24','-s',f'{w}x{h}','-r',str(fps),'-i','pipe:0','-an',
        '-c:v','libx264','-preset','veryfast','-crf','19','-pix_fmt','yuv420p',
        '-movflags','+faststart',str(silent)],stdin=subprocess.PIPE)
    cap=cv2.VideoCapture(str(video))
    segment=analysis['lowered_segment']
    duration=analysis['duration_s']
    times=[duration*.1,duration*.25,duration*.4,duration*.55,duration*.75,duration*.94]
    if segment:
        a,b=segment['start_s'],segment['end_s']
        times=[max(.1,a-.4),a,(a+b)/2,b,min(duration-.1,b+.4),duration*.94]
    chosen={min(len(data['frames'])-1,round(t*fps)):i for i,t in enumerate(times)}
    previews={}
    evidence_paths=set()
    count=0
    try:
        for idx,(pose,row) in enumerate(zip(data['frames'],analysis['frames'])):
            ok,frame=cap.read()
            if not ok:
                raise RuntimeError('Video ended before its pose records')
            annotated=annotate(frame,pose,row,analysis,active_caption(timeline,row['time_s']))
            if idx in chosen:
                path=folder/f"evidence_{row['time_s']:.2f}s.jpg"
                cv2.imwrite(str(path),annotated)
                evidence_paths.add(path)
                previews[chosen[idx]]=(row['time_s'],annotated.copy())
            encoder.stdin.write(annotated.tobytes())
            count+=1
    finally:
        cap.release()
        encoder.stdin.close()
        code=encoder.wait()
    if code:
        raise RuntimeError('Video encoder failed')
    subprocess.run([ff,'-hide_banner','-loglevel','error','-y','-i',str(silent),'-i',str(video),
        '-map','0:v:0','-map','1:a?','-c:v','copy','-c:a','aac','-shortest',
        '-movflags','+faststart',str(output)],check=True)
    silent.unlink()
    (folder/'video_captions.json').write_text(json.dumps(timeline,indent=2))
    if previews:
        tiles=[cv2.resize(previews[k][1],(240,round(h*240/w))) for k in sorted(previews)]
        cv2.imwrite(str(folder/'evidence.jpg'),np.concatenate(tiles,axis=1))
    for previous in folder.glob('evidence_*s.jpg'):
        if previous not in evidence_paths:
            previous.unlink()
    return count


def plot(analysis, folder):
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    rows=analysis['frames']
    t=[r['time_s'] for r in rows]
    fig,axes=plt.subplots(3,1,figsize=(10,7),sharex=True,layout='constrained')
    for side,color in [('left','#0d9488'),('right','#e87925')]:
        axes[0].plot(t,[r[side+'_knee_deg'] for r in rows],lw=1.3,label=side.title(),color=color)
    axes[0].set(ylabel='Knee angle (degrees)',ylim=(0,190),title='Image-plane knee flexion: smaller means more bent')
    axes[0].legend()
    axes[1].plot(t,[r['silhouette_aspect'] for r in rows],'.',alpha=.35,color='#64748b',markersize=3,label='Silhouette samples')
    axes[1].plot(t,[r['smoothed_silhouette_aspect'] for r in rows],color='#0d9488',lw=1.5,label='Local median')
    axes[1].set(ylabel='Silhouette height / width',title='Compactness cue combined with visible knee flexion; not legal sit depth')
    axes[1].legend()
    axes[2].plot(t,[r['body_joints_accepted'] for r in rows],color='#64748b')
    axes[2].set(ylabel='Accepted body joints / 22',xlabel='Time (seconds)',ylim=(0,23),title='Tracking quality: gaps and rejected joints are not skating faults')
    seg=analysis['lowered_segment']
    for ax in axes:
        ax.grid(alpha=.15)
        ax.spines[['top','right']].set_visible(False)
        if seg:
            ax.axvspan(seg['start_s'],seg['end_s'],color='#10b981',alpha=.1)
    fig.suptitle('Spin review: measurements and the detected lower-position interval',fontsize=13)
    fig.savefig(Path(folder)/'measurements.png',dpi=150)
    plt.close(fig)


def write_report(analysis, folder):
    folder=Path(folder)
    track=analysis['tracking']
    stages=analysis.get('timing_s',{})
    lines=['# Figure-skating spin review','',
        '**[Read the coaching assessment](coaching_report.md)** — overall impression, strengths, improvement priorities, and practice cues.','',analysis['headline'],'',
        f"Video: `{analysis['original_source']}` · {analysis['duration_s']:.2f} seconds · local video processing · {analysis.get('cost',{}).get('api_calls',0)} model API calls.",
        '',f"**Processing time:** {stages.get('total',0):.2f} seconds, including video preparation, pose inference, measurements, and rendering.",
        '', '## Feedback','']
    if analysis.get('latest_report_generation_s') is not None:
        lines[lines.index('## Feedback'):lines.index('## Feedback')]=[
            f"Most recent model report regeneration: {analysis['latest_report_generation_s']:.2f} seconds. The full-run timing above is from the preceding video pipeline run.",'']
    for f in analysis['feedback']:
        category={'positive':'Supported positive','review':'Review priority','recording':'Recording improvement'}[f['kind']]
        lines += [f"### {f['title']}",'',f"{category} · {f['start_s']:.2f}–{f['end_s']:.2f} s · {f['confidence']} confidence",'',
                  f['observation']+' '+f['interpretation'],'',f"**Next step:** {f['action']}",'',f"**Limit:** {f['limitation']}",'']
    lines += ['## Evidence and reliability','',
        f"Poses detected in {track['poses']}/{track['frames']} frames ({track['pose_coverage_pct']}%). "
        f"Accepted knee-angle frames: left {track['left_knee_accepted_frames']}, right {track['right_knee_accepted_frames']}.",
        '', 'The confidence filter is a prototype heuristic. Pose detection is not the same as joint accuracy. '
        'A rotating body, a moving camera, and overlapping limbs change the apparent joint angles. '
        'The green interval in the chart is a detected lower-posture candidate; it is not an official element boundary.',
        '', 'Per-frame joint geometry and per-second ranges/coverage are included under `kinematics` in [analysis.json](analysis.json). The coaching report inserts these computed values into the model assessment; it does not invent ideal joint-angle targets.',
        '', '[Watch feedback video](feedback.mp4) · [Evidence frames](evidence.jpg) · [Measurements](measurements.png) · [Structured result](analysis.json)',
        '', '![Evidence frames](evidence.jpg)','', '![Measurements](measurements.png)','',
        '## What this prototype assesses','',
        'Posture changes, visible knee flexion, a sustained lower-posture candidate, a possible rise from that posture, and tracking quality. '
        'Feedback is generated by versioned rules from measurements, without a language model.',
        '', '## What still needs an expert or a better recording','',
        'No overall numerical score is assigned. Blade edges, weight-bearing contact, legal sit depth, revolution count, RPM, '
        'and ice-relative centering are not established. The rules have not been validated against expert skating judgments.',
        '', '## Reproduce','',
        '```sh',f".video-venv/bin/python run_spin_coach.py --input {analysis['original_source']}",'```','',
        'MediaPipe documentation: https://developers.google.com/edge/mediapipe/solutions/vision/pose_landmarker/python','']
    (folder/'report.md').write_text('\n'.join(lines))
    (folder/'analysis.json').write_text(json.dumps(analysis,indent=2))
