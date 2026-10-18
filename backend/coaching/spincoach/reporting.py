"""Short readable coaching reports; full evidence remains in the JSON artifacts."""
import re

from spincoach.kinematics import label, references_card


def concise_report(coaching, windows=None):
    sections={section['time_s'][0]:section for section in coaching.get('sections',[])}
    if windows is None:
        windows=[{'time_s':s['time_s'],'cards':s.get('measurement_cards',[])}
                 for s in coaching.get('sections',[])]
    lines=['# Spin coaching','']
    for window in windows:
        start,end=window['time_s']
        section=sections.get(start)
        if not section:
            lines.append(f'- **{start:g}–{end:g}s:** Model feedback unavailable for this interval.')
            continue
        match=re.search(r'^Advice:\s*(.*?)(?=\n\s*\w+:|\Z)',section['content'],re.M|re.S)
        advice=' '.join(match.group(1).split()) if match else ''
        sentences=re.split(r'(?<=[.!?])\s+',advice)
        # Extract a complete action sentence, preserving any conditional wording.
        action=next((s for s in sentences if re.search(r'\b(?:if|try|check|focus|practice|rehearse|preserv\w*)\b',s,re.I)),sentences[0])
        cards=section.get('measurement_cards',window.get('cards',[]))
        card=next((c for c in cards if references_card(advice,c,allow_range=True)),None)
        measured=''
        if card and not references_card(action,card,allow_range=True):
            name=label(card['metric']).replace(' from screen vertical','').capitalize()
            if card.get('iqr_width',0)>=20:
                measured=f"{name} {card['p25']:g}–{card['p75']:g}° (middle 50%). "
            else:
                measured=f"{name} median {card['median']:g}°. "
        lines.append(f'- **{start:g}–{end:g}s:** {measured}{action or "Not enough evidence for a technique correction."}')
    lines.extend(['','2D estimates; prototype coaching, not an official score.',
                  '', '[Detailed measurements](analysis.json) · [Video](feedback.mp4)',''])
    return '\n'.join(lines)
