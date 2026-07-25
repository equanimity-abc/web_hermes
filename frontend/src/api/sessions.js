/**
 * Session REST helpers. Extend here when P1 list/persist APIs land.
 */

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

/** Placeholder until backend exposes GET /api/sessions */
export async function listSessions() {
  return []
}
