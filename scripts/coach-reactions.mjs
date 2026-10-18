// Deliberately narrow: do not celebrate an unresolved problem or a question.
export function acknowledgementReaction(text) {
  const value = text.trim().replace(/^(?:@?ai|@?coach\s+ai)\b[:,]?\s*/i, '')
  return /^(?:thanks(?: a lot| so much)?|thank you(?: so much)?|ty|that (?:helped|worked|fixed it|solved it)|it works now|problem solved)(?:[\s,!.]*(?:that (?:helped|worked|fixed it|solved it)|you helped|that makes sense|i get it now|i understand now|so much))?[\s!.🙏👍]*$/i.test(value)
    ? { kind: 'like' } : null
}
