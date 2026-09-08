/**
 * Session REST helpers.
 */

export async function listSessions() {
  const resp = await fetch('/api/sessions')
  if (!resp.ok) {
    throw new Error(`加载会话列表失败: HTTP ${resp.status}`)
  }
  const data = await resp.json()
  return data.sessions || []
}

export async function fetchSession(sessionId) {
  const resp = await fetch(`/api/sessions/${sessionId}`)
  if (!resp.ok) {
    throw new Error(`加载会话失败: HTTP ${resp.status}`)
  }
  return resp.json()
}

export async function deleteSession(sessionId) {
  const resp = await fetch(`/api/sessions/${sessionId}`, { method: 'DELETE' })
  if (!resp.ok) {
    throw new Error(`删除会话失败: HTTP ${resp.status}`)
  }
}

/**
 * Persist async drama tool terminal state into the session transcript.
 */
export async function patchSessionToolResult(sessionId, { toolCallId, content, assistantContent } = {}) {
  const sid = String(sessionId || '').trim()
  const tid = String(toolCallId || '').trim()
  if (!sid || !tid) return null
  const resp = await fetch(`/api/sessions/${encodeURIComponent(sid)}/tool-results`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      tool_call_id: tid,
      content: String(content ?? ''),
      assistant_content: assistantContent == null ? null : String(assistantContent),
    }),
  })
  if (!resp.ok) {
    const detail = await resp.text().catch(() => '')
    throw new Error(detail || `写回会话失败: HTTP ${resp.status}`)
  }
  return resp.json()
}
