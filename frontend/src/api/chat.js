/**
 * Stream a chat turn via SSE (POST /api/chat/stream).
 *
 * @param {{ sessionId: string|null, message: string }} params
 * @param {{
 *   onSessionId?: (id: string) => void,
 *   onToken?: (text: string) => void,
 * }} handlers
 */
export async function streamChat({ sessionId, message }, { onSessionId, onToken } = {}) {
  const response = await fetch('/api/chat/stream', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ session_id: sessionId, message }),
  })

  if (!response.ok) {
    const errText = await response.text()
    throw new Error(`HTTP ${response.status}: ${errText}`)
  }

  const reader = response.body.getReader()
  const decoder = new TextDecoder()
  let buffer = ''
  let sseData = ''

  while (true) {
    const { done, value } = await reader.read()
    if (done) break

    buffer += decoder.decode(value, { stream: true })
    const lines = buffer.split('\n')
    buffer = lines.pop() || ''

    for (const line of lines) {
      const cleanLine = line.replace(/\r$/, '')

      if (cleanLine === '') {
        if (!sseData) continue
        try {
          const parsed = JSON.parse(sseData)
          if (parsed.session_id) {
            onSessionId?.(parsed.session_id)
            sseData = ''
            continue
          }
        } catch {
          /* plain text token chunk */
        }
        onToken?.(sseData)
        sseData = ''
      } else if (cleanLine.startsWith('data:')) {
        if (sseData) sseData += '\n'
        sseData += cleanLine.slice(5).replace(/^ /, '')
      }
    }
  }
}
