"""Small, versioned ISU reference set, not a complete rule engine or score sheet.

Criteria are paraphrases. Page numbers refer to PDF pages (also printed pages).
Keep observations, applicability and official calls separate: no measured joint
angle in this prototype is an ISU pass/fail threshold.
"""
from copy import deepcopy
import re

BASE = 'https://isu-d8g8b4b7ece7aphs.a03.azurefd.net/isudamcontainer/CMS/Corporate-Site/Sports-Rules/Figure-Skating-Rules/Handbooks-Single-%26-Pair-Skating/'
SOURCES = {
    'judges': {'title':'Referees and Judges Handbook 2026–27', 'edition':'19 May 2026',
               'url':BASE+'Handbook-for-Referees-and-Judges-2026-27-1779278300-9402.pdf'},
    'technical': {'title':'Singles Technical Panel Handbook 2026–27', 'edition':'15 July 2026',
                  'url':BASE+'TP-HandbookSingles-26-27-15-July-2026-1784641784-3364.pdf'},
}


def rule(code, title, criterion, source, page, scope, evidence_needed, cue,
         conditional_reduction=None):
    return dict(id=code, title=title, criterion=criterion, source=source, page=page,
                url=SOURCES[source]['url']+f'#page={page}', scope=scope,
                evidence_needed=evidence_needed, cue=cue,
                conditional_reduction=conditional_reduction)


RULES = [
    rule('SPIN-SIT','Sit basic position',
         'The skating thigh must reach at least parallel to the ice.', 'technical',14,['sit_spin'],
         'Identify the skating leg and ice plane; inspect a clear side view during the hold.',
         'Check skating-thigh depth during the hold.'),
    rule('SPIN-CAMEL','Camel basic position',
         'The free leg extends backward with its knee above hip level; listed upright variations are exceptions.',
         'technical',14,['camel_spin'],
         'Identify the free leg and view its knee relative to the hip and ice plane.',
         'Review the free-knee height in a clear side view.'),
    rule('SPIN-UPRIGHT','Upright basic position',
         'The skating leg is extended or slightly bent, excluding camel positions.',
         'technical',14,['upright_spin'],
         'Identify the skating leg; torso verticality and straight elbows are not the definition.',
         'Review the skating-leg shape; preserve your chosen arm variation.'),
    rule('SPIN-POSITION','Position quality',
         'An excessive delay reaching a basic position can incur a position-quality reduction.',
         'judges',10,['spin'],
         'Continuous entry footage and a confirmed intended basic position; elapsed seconds alone do not establish excessive delay.',
         'Review how clearly you establish the intended basic position.',[-3,-1]),
    rule('SPIN-REVOLUTIONS','Revolutions in a basic position',
         'A counted position requires two uninterrupted revolutions; required element totals depend on context.',
         'technical',14,['spin'],
         'Verified complete revolutions in each basic position, exact spin subtype and program requirements.',
         'Check complete turns in the intended position.'),
    rule('SPIN-MISSING','Missing required revolutions',
         'Missing one or two required turns reduces GOE by one to two; three or more by three to four.',
         'judges',8,['spin'],
         'Verified turn count and applicable required minimum. Clip length and shoulder sign changes are not turn counts.',
         'Count the hold only after the position is established.'),
    rule('SPIN-TOUCH','Free-foot contact in a sit-side variation',
         'A boot near the ice is insufficient evidence of touchdown; assess actual tracing/contact and weight transfer.',
         'judges',9,['sit_spin'],
         'Visible boot contact/tracing and weight-transfer context; ankle coordinates cannot verify these.',
         'Check that the free boot clears the ice in the chosen variation.',[-3,-1]),
    rule('SPIN-EXIT','Difficult exit quality',
         'A mistake or loss of balance in a difficult exit may incur a poor-exit reduction.',
         'judges',9,['spin'],
         'A visible, identified difficult exit with a confirmed mistake; the clip ending does not establish an exit.',
         'Review control through the visible exit.',[-3,-1]),
    rule('SPIN-ARMS','Arm variation and overall quality',
         'The quality example considers clear positions and creative arm movement among positive qualities, alongside errors.',
         'judges',11,['spin'],
         'Continuous footage of position quality; do not infer speed, musical timing or centering from two crops.',
         'Keep the intended arm shape clear; straight or symmetric arms are not mandatory.'),
    rule('JUMP-LANDING','Weak landing',
         'A weak landing, including the specified hop or incorrect landing edge, can incur a reduction.',
         'judges',5,['jump'],
         'Continuous landing footage, identified landing contact/edge and relevant jump context.',
         'Review control through landing and recovery.',[-3,-1]),
    rule('JUMP-TAKEOFF','Poor takeoff',
         'Unclear takeoff, whole-blade use instead of toe-pick, or free-foot assistance on a Salchow can incur a reduction.',
         'judges',6,['jump'],
         'Identified jump subtype and close blade/contact footage; do not apply toe-pick requirements to an edge jump.',
         'Review the intended takeoff with a clear view of the blade.',[-4,-2]),
]

POLICY = ('ISU-based review of selected singles criteria, season 2026–27. This is not a complete GOE rubric. '
          'No official GOE, level, base value or program-component score is calculated. '
          'Listed reduction ranges are conditional references, never applied deductions. '
          'Unmeasured criteria are unknown, not failed or passed. Waltz jumps receive developmental coaching, not a listed-jump score.')


def assess_rules(element, family, phases, windows, findings):
    checks=[]
    for reference in RULES:
        if element not in reference['scope'] and family not in reference['scope']:
            continue
        check=deepcopy(reference)
        # Only position geometry is represented in this pipeline. None of the
        # blade/turn-count/contact/continuous quality calls are implemented.
        position=reference['id'] in {'SPIN-SIT','SPIN-CAMEL','SPIN-UPRIGHT'}
        candidates=[]
        for phase,window in zip(phases,windows):
            # A marked hold or a disclosed low-position candidate is required;
            # a preparation/transition interval must not be tested as a hold.
            if position and phase['name'] in {'Intended hold','Lower-position candidate'}:
                cards=[c for c in window['cards'] if 'knee' in c['metric'] or 'hip' in c['metric']]
                if cards:
                    candidates.append({'phase_id':phase['id'],'time_s':phase['time_s'],
                                       'measurements':[c['detail'] for c in cards]})
        check.update(status='review_candidate' if candidates else 'not_assessable',
                     evidence=candidates,
                     explanation=('Projected knee/hip geometry is available for review. It does not establish skating/free-leg identity or the ice-relative position.'
                                  if candidates else 'The pipeline has not established the required evidence: '+reference['evidence_needed']),
                     finding_ids=[f['id'] for f in findings if reference['id'] in f.get('rule_refs',[])],
                     applied_reduction=None)
        checks.append(check)
    return {'version':'isu-singles-2026-27-v1','season':'2026–27','discipline':'singles',
            'program':'unspecified','policy':POLICY,'sources':deepcopy(SOURCES),
            'checks':checks,'official_goe':None,'level':None,'base_value':None}


def phase_rules(assessment, phase):
    """Supply only applicable references; a transition is not a failed sit hold."""
    name=phase['name']
    out=[]
    for check in assessment['checks']:
        code=check['id']
        if code in {'SPIN-SIT','SPIN-CAMEL','SPIN-UPRIGHT'} and name not in {'Intended hold','Lower-position candidate'} and 'uncertain' not in name:
            continue
        if code=='SPIN-POSITION' and name=='Intended hold':
            continue
        if code=='JUMP-TAKEOFF' and 'Landing' in name:
            continue
        if code=='JUMP-LANDING' and ('Preparation' in name or 'Flight' in name):
            continue
        # Penalty ranges stay in the human-readable reference section, not in
        # the coaching prompt where they could be mistaken for measured facts.
        out.append({k:check[k] for k in ['id','title','criterion','status','explanation','evidence_needed','cue']})
    return out


def model_rule_problems(text, references):
    codes={r['id'] for r in references}
    match=re.search(r'^Rule:\s*([A-Z-]+)\s*$',text,re.M)
    problems=[]
    if codes and (not match or match[1] not in codes):
        problems.append('Add Rule: followed by one exact supplied ISU rule ID, on its own line.')
    elif match and not codes:
        problems.append('No ISU rule is applicable; omit the Rule field.')
    if re.search(r'\b(?:GOE|deduction|penalty|score|level)\s*(?::|of|is|=|would be|should be)?\s*[+−-]?\d|\b(?:legal|illegal|valid|invalid) (?:sit|camel|upright|spin)|\b(?:passes|fails|violates|satisfies) (?:the |this )?(?:ISU|rule|criterion)',text,re.I):
        problems.append('Do not assign scores, deductions, legal-position calls or rule pass/fail verdicts; their evidence is not established.')
    return problems


def rule_lines(assessment,include_unassessed=True):
    lines=['## ISU rule checks (2026–27)','',assessment['policy'],'']
    for check in assessment['checks']:
        if not include_unassessed and not check.get('visual_opinions'):
            continue
        lines.extend([f"- **{check['title']} — {check.get('status_label',check['status'].replace('_',' '))}** [{check['id']}, p. {check['page']}]({check['url']})",
                      '  '+check['criterion'], '  Evidence: '+check['explanation']])
        if check['conditional_reduction']:
            lo,hi=check['conditional_reduction']
            lines.append(f'  If the specified mistake is confirmed: reference GOE reduction {lo} to {hi}. No reduction applied here.')
    return lines+['']
