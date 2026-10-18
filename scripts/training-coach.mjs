export const SMS_HELP = 'Your skate coach: LATEST - review your video; PROGRESS - compare attempts; PLAN - next practice; GOAL <focus> - remember a goal; DONE <note> - log practice; COACH <note> - add your human coach\'s advice; CHECKIN <note> - how practice felt; TIMELINE - recent feedback; SHARE - a summary to show your coach. START enables new-report texts; STOP pauses texts.'

export function smsText(text) {
  const plain = text.replace(/\*\*/g, '').replace(/[“”]/g, '"').replace(/[‘’]/g, "'")
    .replace(/[–—]/g, '-').replace(/°/g, ' deg').replace(/•/g, '-').trim()
  if (plain.length <= 1100) return plain
  const cut = plain.slice(0, 1030)
  const boundary = Math.max(cut.lastIndexOf('. '), cut.lastIndexOf('\n'))
  return `${cut.slice(0, boundary > 600 ? boundary + 1 : 1030).trim()}\nAsk about one point for more detail.`
}

export async function trainingCommand(question, { database, instructions, feedback, complete, eventId }) {
  const input = question.trim().replace(/^\//, '')
  const command = input.toLowerCase()
  if (['help', '?'].includes(command)) return SMS_HELP
  const natural = input.replace(/^my goal is\s+/i, 'goal ')
    .replace(/^i practi[cs]ed\s+/i, 'done ')
    .replace(/^my coach said\s+/i, 'coach ')
    .replace(/^i(?: am|'m) feeling\s+/i, 'checkin ')
  const entry = /^(goal|done|coach|checkin)\s+([\s\S]+)$/i.exec(natural)
  if (entry) {
    const kind = entry[1].toLowerCase()
    const text = entry[2].trim().slice(0, 1500)
    if (kind === 'goal') await database.setAthlete({ goal: text })
    await database.note(kind, text, eventId, feedback?.id)
    if (kind === 'goal') return `Goal saved: ${text}\nI'll use this focus in your next plan and video review. Text PLAN for a practice session.`
    if (kind === 'coach') return `Saved your human coach's note: ${text}\nI'll keep it alongside the video evidence when advising you.`
    if (kind === 'done') return `Practice logged: ${text}\nThat's a practice check-in, not a measured performance change. Upload your next attempt and we can review what changed.`
    if (feedback) return complete([{ role: 'user', content: question }], `${instructions}\nThis feeling check-in has been saved: ${text}. Acknowledge it naturally, tie one manageable next step to the actual report or saved goal, and invite the user's preference. Do not turn a feeling into a technical fault.`)
    return `I'll keep that in mind: ${text}. Would encouragement or a smaller practice goal help most right now?`
  }
  if (['goal', 'done', 'coach', 'checkin'].includes(command)) return `Text ${command.toUpperCase()} followed by a short note. Example: GOAL keep my arm reach consistent.`
  if (['timeline', 'history', 'my timeline'].includes(command)) {
    const reports = await database.recentFeedback(5)
    if (!reports.length) return 'Your feedback timeline is empty. Analyze a clip first, then we can track your practice.'
    return 'Your recent feedback (newest first):\n' + [...reports].reverse().map((report, i) =>
      `${i + 1}. ${new Date(report.savedAt).toLocaleDateString('en-US', { timeZone: 'America/Los_Angeles' })} - ${report.videoName}: ${report.feedback.headline || 'Coaching report saved.'}`).join('\n')
  }
  if (!feedback) return null
  if (/^(progress|compare|compare my attempts|how (have i|am i) improved|my progress)\??$/.test(command)) {
    const reports = await database.recentFeedback(2)
    if (reports.length < 2) return `I have one saved report (${feedback.videoName}). I need another attempt of the same movement before judging changes. Your current report is a starting point, not proof of improvement.`
    return complete([{ role: 'user', content: 'Compare my last two attempts. Separate observed changes, repeated review priorities, and what is uncertain. If these are different movements or recording conditions, say a direct improvement claim is not justified.' }],
      `${instructions}\nFull reports for this comparison, oldest first: ${JSON.stringify(reports)}`)
  }
  if (/^(plan|practice plan|make (me )?a (practice )?plan|what should i practi[cs]e)\??$/.test(command)) {
    // Two independent roles inspect the same evidence. The final coach synthesizes
    // their findings; role output is advice, never new measured facts.
    const reviews = await Promise.allSettled([
      complete([{ role: 'user', content: 'As the evidence reviewer, identify one supported strength and one review priority from the current report, with timestamps. Name limitations and avoid inventing technique faults. Under 120 words.' }], instructions),
      complete([{ role: 'user', content: 'As the practice planner, propose a short session matching the saved goal, human coach notes, practice check-ins, and actual report. Respect the intended skating position; do not invent ideal angles. Offer one cue and one observable self-check. Under 120 words.' }], instructions),
    ])
    const notes = reviews.map((result, index) => ({ role: index === 0 ? 'evidence reviewer' : 'practice planner',
      advice: result.status === 'fulfilled' ? result.value : 'Unavailable; use original evidence only.' }))
    return complete([{ role: 'user', content: `Give me a short practice plan: one focus, a simple drill, one cue, and what to check in my next video. End by inviting DONE with a practice note. Specialist suggestions (not measurements): ${JSON.stringify(notes)}` }], instructions)
  }
  if (['share', 'coach summary'].includes(command)) {
    return complete([{ role: 'user', content: 'Write a concise first-person summary I can copy to my human coach. Include the recording name, one timestamped observation, my saved goal, and one specific question for coach review. Do not send it to anyone or imply a coach approved it.' }], instructions)
  }
  return null
}

export function reportNotification(analysis, profile) {
  const priority = analysis.feedback.findings?.find(item => item.kind === 'review')
  return smsText(`New feedback: ${analysis.videoName}. ${analysis.feedback.headline || 'Your skating report is ready.'}${priority?.action ? `\nNext review: ${priority.action}` : ''}${profile.goal ? `\nYour focus: ${profile.goal}` : ''}\nWant to work on this together? Text PLAN, or tell me how the attempt felt.`)
}
