"""Timed video captions derived from, and traceable to, the coaching report."""
import re
import unicodedata


def plain_text(text):
    return unicodedata.normalize('NFKD', text.replace('—', '-').replace('–', '-')
                                 .replace('“', '"').replace('”', '"').replace('’', "'")).encode('ascii', 'ignore').decode()


def caption_timeline(coaching, summaries=None):
    """Use model caption fields when present; otherwise extract its first advice sentence.

    Optional two-line editorial summaries are recorded separately from the verbatim
    model response. Never fill missing model intervals with invented advice.
    """
    captions=[]
    for section in (coaching or {}).get('sections', []):
        start,end=section['time_s']
        content=section['content']
        custom=(summaries or {}).get(start)
        match=re.search(r'^Caption:\s*(.+)', content, re.M)
        advice=re.search(r'^Advice:\s*(.*?)(?=\n\s*\w+:|\Z)',content,re.M|re.S)
        if custom:
            lines=[plain_text(line) for line in custom]
            method='assistant summary of model advice and cue'
        elif match and '|' in match.group(1):
            lines=[plain_text(line.strip()) for line in match.group(1).split('|',1)]
            method='model caption'
        elif advice:
            lines=[plain_text(re.split(r'(?<=[.!?])\s+',advice.group(1).strip())[0])]
            method='first sentence of model advice, wrapped for video'
        else:
            continue
        captions.append({'start_s':start,'end_s':end,'lines':lines,
                         'method':method,'source_text':content,'phase_name':section.get('phase_name')})
    return {'source':'coaching_assessment.json','model':(coaching or {}).get('model'),
            'captions':captions}


def active_caption(timeline,time_s):
    return next((c for c in timeline['captions'] if c['start_s']<=time_s<c['end_s']),None)
