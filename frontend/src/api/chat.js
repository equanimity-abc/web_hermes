/**
 * Stream a chat turn via SSE (POST /api/chat/stream).
 *
 * Wire protocol:
 * - plain text data → token
 * - JSON {session_id} → session binding
 * - JSON {type:"token", text} → token
 * - JSON {type:"status"|"tool"|...} → meta (not appended as chat text)
 */

export async function streamChat(
  { sessionId, message },
  { onSessionId, onToken, onStatus, onTool } = {},
) {
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
  let streamError = null

  while (true) {
    const { done, value } = await reader.read()
    if (done) break

    buffer += decoder.decode(value, { stream: true })
    const lines = buffer.split('\n')
    buffer = lines.pop() || ''

    for (const line of lines) {
      const cleanLine = line.replace(/\r$/, '')

      if (cleanLine.startsWith('event:')) {
        // tracked implicitly via JSON type / done
        continue
      }

      if (cleanLine === '') {
        if (!sseData) continue
        try {
          const parsed = JSON.parse(sseData)
          if (parsed.session_id && !parsed.type) {
            onSessionId?.(parsed.session_id)
            sseData = ''
            continue
          }
          if (parsed.type === 'token' && parsed.text != null) {
            onToken?.(parsed.text)
            sseData = ''
            continue
          }
          if (parsed.type === 'status') {
            onStatus?.(parsed.text || '')
            sseData = ''
            continue
          }
          if (parsed.type === 'tool') {
            onTool?.(parsed)
            onStatus?.(parsed.name ? `正在调用工具：${parsed.name}` : '正在调用工具…')
            sseData = ''
            continue
          }
          if (parsed.type === 'tool_result' || parsed.type === 'final') {
            sseData = ''
            continue
          }
          // Unknown JSON — do not dump into the transcript
          sseData = ''
          continue
        } catch {
          onToken?.(sseData)
        }
        sseData = ''
      } else if (cleanLine.startsWith('data:')) {
        if (sseData) sseData += '\n'
        const payload = cleanLine.slice(5).replace(/^ /, '')
        // sse-starlette error events still use data:
        sseData += payload
      }
    }
  }

  if (streamError) throw new Error(streamError)
}
