/**
 * Fold raw OpenAI-style session messages into UI messages.
 * Attaches toolCalls onto the final assistant text turn.
 */
export function foldMessagesForUi(rawMessages = []) {
  const out = []
  let pendingTools = []

  for (const m of rawMessages) {
    if (m.role === 'system') continue

    if (m.role === 'user') {
      pendingTools = []
      out.push({
        role: 'user',
        content: m.content || '',
        isStreaming: false,
      })
      continue
    }

    if (m.role === 'assistant' && Array.isArray(m.tool_calls) && m.tool_calls.length) {
      pendingTools = m.tool_calls.map((tc) => {
        const fn = tc.function || {}
        return {
          id: tc.id || '',
          name: fn.name || '',
          arguments: fn.arguments || '',
          result: '',
          status: 'done',
        }
      })
      continue
    }

    if (m.role === 'tool') {
      const hit = pendingTools.find((t) => t.id === m.tool_call_id)
      if (hit) {
        hit.result = m.content || ''
        try {
          const parsed = JSON.parse(hit.result)
          if (parsed && parsed.error) hit.status = 'error'
        } catch {
          /* plain text result */
        }
      }
      continue
    }

    if (m.role === 'assistant') {
      const content = String(m.content || '')
      if (!content.trim() && pendingTools.length === 0) continue
      out.push({
        role: 'assistant',
        content,
        toolCalls: pendingTools.length ? pendingTools : undefined,
        isStreaming: false,
        liked: !!m.liked,
        disliked: !!m.disliked,
      })
      pendingTools = []
    }
  }

  return out
}
