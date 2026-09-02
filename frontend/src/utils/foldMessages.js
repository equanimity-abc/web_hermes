/**
 * Fold raw OpenAI-style session messages into UI messages.
 * Attaches toolCalls onto the final assistant text turn.
 */
import { enrichMessageWithDramaMedia } from '@/utils/dramaChatMedia'

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
      const msg = {
        role: 'assistant',
        content,
        toolCalls: pendingTools.length ? pendingTools : undefined,
        isStreaming: false,
        liked: !!m.liked,
        disliked: !!m.disliked,
      }
      enrichMessageWithDramaMedia(msg)
      out.push(msg)
      pendingTools = []
    }
  }

  // Incomplete turn: tool_calls already persisted but final assistant text not yet.
  if (pendingTools.length) {
    for (const t of pendingTools) {
      if (!t.result) t.status = 'running'
    }
    const running = pendingTools.some((t) => t.status === 'running')
    const msg = {
      role: 'assistant',
      content: '',
      toolCalls: pendingTools,
      isStreaming: running,
      status: running ? '成片生成中，请稍候…完成后会自动出现在对话里' : '',
    }
    enrichMessageWithDramaMedia(msg)
    out.push(msg)
  }

  return out
}
