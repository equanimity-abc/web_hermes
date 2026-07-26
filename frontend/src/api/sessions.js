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
