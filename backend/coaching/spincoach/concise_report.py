"""Three short coaching paragraphs and a clearly subjective execution rating."""
import re


REVIEW_INSTRUCTIONS = '''Include overall.review with exactly three short paragraphs:
strengths (what you did right), errors (the most important visible problem), and
improvements (one practical way to improve, with a simple mental cue if useful).
Use about 25–40 words per paragraph, never over 50. Summarize the same phase
findings; do not add new faults, ideal angles, blade calls or unsupported claims.
Use plain language without numerical measurements, repeated caveats, or lists.
If no clear error is supported, say so and give a next practice goal.
Also include score: an integer from 0 to 10 for visible execution, and score_reason:
one short sentence (at most 20 words) explaining the rating using those findings.
This is a subjective hackathon coaching rating, NOT official ISU/GOE scoring.
Use this scale: 0–3 major visible execution problems, 4–6 inconsistent control,
7–8 mostly controlled with specific improvements, 9–10 consistently strong execution.
Rate the actual execution, never tracking coverage, camera quality or model confidence.
Use null for score only when too little execution is visible to rate it.
review schema: {"strengths":"...","errors":"...","improvements":"...",
"score":7,"score_reason":"..."}.'''


def validate_review(review):
    if not isinstance(review,dict):
        raise ValueError('Return overall.review with three paragraphs and a coaching rating.')
    for field in ['strengths','errors','improvements','score_reason']:
        text=review.get(field)
        cap=20 if field=='score_reason' else 50
        if not isinstance(text,str) or not text.strip() or len(text.split())>cap or '\n' in text:
            raise ValueError(f'Review {field} must be one short paragraph, at most {cap} words.')
        if re.search(r'\d|°|\bGOE\b|\b(?:legal|illegal) (?:spin|position|sit|camel)|\block(?:ed|ing)? (?:your |the )?(?:knees?|elbows?)',text,re.I):
            raise ValueError('Keep review paragraphs qualitative, without official calls or locked-joint advice.')
    score=review.get('score')
    if 'score' not in review or (score is not None and (type(score) is not int or not 0<=score<=10)):
        raise ValueError('Coaching score must be an integer from 0 to 10, or null if execution cannot be rated.')
    return review


def legacy_review(report,element):
    """Compact existing/local findings without fabricating a numerical grade."""
    def shorten(text,limit=45):
        words=' '.join(text.split()).split()
        return ' '.join(words[:limit])+('…' if len(words)>limit else '')
    summary=element['summary']
    sections=report.get('sections',[])
    advice=[]
    for section in sections:
        match=re.search(r'^Advice:\s*(.+)',section.get('raw_content',''),re.M)
        if match and match[1] not in advice:
            advice.append(match[1])
    return {'strengths':shorten(summary['good']), 'errors':shorten(summary['improve']),
            'improvements':shorten(' '.join(advice[:2]) or 'Practice the highlighted correction and review the same position on your next attempt.'),
            'score':None, 'score_reason':'This saved assessment has no model execution rating.'}


def format_review(review):
    score=f"{review['score']}/10" if review['score'] is not None else 'Not rated'
    return '\n\n'.join([
        'What went well: '+review['strengths'].strip(),
        'What needs work: '+review['errors'].strip(),
        'How to improve: '+review['improvements'].strip(),
        f"Final coaching score: {score}. {review['score_reason'].strip()} "
        '(Prototype coaching assessment; not an official ISU score.)'])+'\n'
