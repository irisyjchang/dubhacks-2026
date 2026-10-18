"""Build both levels of feedback from the same confirmed element and evidence."""
import json
from pathlib import Path

from spincoach.kinematics import format_response
from spincoach.isu_rules import phase_rules
from spincoach.concise_report import legacy_review,format_review,validate_review


def local_element_assessment(result):
    analysis=result['element_analysis'];sections=[]
    for phase,window in zip(analysis['phases'],result['phase_kinematics']['windows']):
        checks=[f['text'] for f in analysis['findings'] if f['phase_id']==phase['id']]
        review=next((f['text'] for f in analysis['findings'] if f['phase_id']==phase['id'] and f['kind']=='review'),
                    'Review the chosen arm and leg shape in clear, matching body orientations.')
        references=phase_rules(analysis['isu_assessment'],phase)
        primary=next((r for r in references if r['status']=='review_candidate'),None)
        if primary:
            review=primary['cue']+' Confirm the skating/free leg and ice plane before judging the position.'
        cue=('Hold the chosen shape clearly' if analysis['family']=='spin' else
             'Review the marked landing shape' if analysis['family']=='jump' else 'Confirm the movement first')
        raw='Observation: '+(' '.join(checks) if checks else 'The intended element is selected; this phase is a review interval, not a verified technique judgment.')+'\nAdvice: '+review+'\nCue: '+cue
        if references:
            raw+='\nRule: '+(primary or references[0])['id']
        raw+='\nCaption: '+phase['name']+' | '+cue
        sections.append({'time_s':phase['time_s'],'phase_id':phase['id'],'phase_name':phase['name'],
                         'raw_content':raw,'content':format_response(raw,window,numeric_caption=False),
                         'measurement_cards':window['cards']})
    return {'generator':'local element review','model':None,'api_calls':0,'elapsed_s':0,
            'status':'local','sections':sections,'content':'\n\n'.join(s['content'] for s in sections),
            'errors':[],'source':'analysis.json'}


def finish_element_report(report,result,folder):
    folder=Path(folder);element=result['element_analysis']
    report['element_analysis']=element
    report['summary']=element['summary']
    report['summary_source']=element['summary']['source']
    sections={s.get('phase_id'):s for s in report.get('sections',[])}
    details=[]
    for phase in element['phases']:
        section=sections.get(phase['id'])
        text=section['content'] if section else 'Model assessment unavailable. Measurements remain in analysis.json; no model judgment is substituted.'
        references=phase_rules(element['isu_assessment'],phase)
        cited=[r for r in references if 'Rule: '+r['id'] in text]
        details.append({**phase,'content':text,'rule_refs':[r['id'] for r in cited],'generator':report['generator'] if section else 'unavailable'})
    review=element.get('coaching_review') or legacy_review(report,element)
    if element.get('coaching_review'):
        validate_review(review)
    report['coaching_review']=review
    report['score_type']='subjective coaching execution rating; not official ISU scoring'
    report['phase_details']=details
    (folder/'coaching_assessment.json').write_text(json.dumps(report,indent=2))
    (folder/'coaching_report.md').write_text(format_review(review))
    return report
