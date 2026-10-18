export async function answer(history, instructions = 'You are a helpful AI assistant chatting over iMessage. Keep replies concise and conversational.') {
  const response = await fetch('https://api.openai.com/v1/responses', {
    method: 'POST',
    headers: {
      Authorization: `Bearer ${process.env.OPENAI_API_KEY}`,
      'Content-Type': 'application/json',
    },
    body: JSON.stringify({
      model: process.env.OPENAI_MODEL || 'gpt-4.1-mini',
      instructions,
      input: history,
      max_output_tokens: 500,
      store: false,
    }),
    signal: AbortSignal.timeout(45000),
  })
  if (!response.ok) throw new Error(`OpenAI returned HTTP ${response.status}`)
  const data = await response.json()
  const text = (data.output || []).flatMap(item => item.content || [])
    .filter(item => item.type === 'output_text').map(item => item.text).join('\n')
  if (!text) throw new Error('OpenAI returned no text')
  return text
}

