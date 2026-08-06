/**
 * Chat streaming client (P4 contract).
 *
 * Flow:
 *   1. POST /api/chat/start → { stream_id, session_id }
 *   2. GET  /api/chat/stream/{stream_id} → SSE until done|error|cancelled
 *   3. POST /api/chat/cancel { stream_id } → terminal event is cancelled (not done)
 *
 * Unified SSE: `event: <type>` + JSON `data` with matching `type` field.
 */

export class SessionBusyError extends Error {
  constructor(detail) {
    super('会话正在生成中，请先停止或等待完成')
    this.name = 'SessionBusyError'
    this.detail = detail
  }
}

export async function startChat({ sessionId, message }) {
  const response = await fetch('/api/chat/start', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ session_id: sessionId, message }),
  })

  if (response.status === 409) {
    let detail = null
    try {
      const body = await response.json()
      detail = body.detail || body
    } catch {
      /* ignore */
    }
    throw new SessionBusyError(detail)
  }

  if (!response.ok) {
    const errText = await response.text()
    throw new Error(`HTTP ${response.status}: ${errText}`)
  }

  return response.json()
}

export async function cancelChat(streamId) {
  const response = await fetch('/api/chat/cancel', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ stream_id: streamId }),
  })
  if (!response.ok) {
    const errText = await response.text()
    throw new Error(`HTTP ${response.status}: ${errText}`)
  }
  return response.json()
}

export async function respondApproval({ streamId, approvalId, decision }) {
  const response = await fetch('/api/chat/approval/respond', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      stream_id: streamId,
      approval_id: approvalId,
      decision,
    }),
  })
  if (!response.ok) {
    const errText = await response.text()
    throw new Error(`HTTP ${response.status}: ${errText}`)
  }
  return response.json()
}

export async function uploadWorkspaceFile(file, { subdir = '' } = {}) {
  const form = new FormData()
  form.append('file', file)
  if (subdir) form.append('subdir', subdir)
  const response = await fetch('/api/workspace/upload', {
    method: 'POST',
    body: form,
  })
  if (!response.ok) {
    const errText = await response.text()
    throw new Error(`HTTP ${response.status}: ${errText}`)
  }
  return response.json()
}

/**
 * Connect (or reconnect) to a stream and dispatch typed events.
 * Resolves when a terminal event arrives (done / error / cancelled),
 * or rejects on network failure / abort.
 */
export async function connectStream(
  streamId,
  {
    onMeta,
    onToken,
    onStatus,
    onTool,
    onToolResult,
    onApproval,
    onDone,
    onError,
    onCancelled,
  } = {},
  { signal } = {},
) {
  const response = await fetch(`/api/chat/stream/${streamId}`, {
    method: 'GET',
    headers: { Accept: 'text/event-stream' },
    signal,
  })

  if (!response.ok) {
    const errText = await response.text()
    throw new Error(`HTTP ${response.status}: ${errText}`)
  }

  const reader = response.body.getReader()
  const decoder = new TextDecoder()
  let buffer = ''
  let sseEvent = ''
  let sseData = ''
  let terminal = null

  const dispatch = (eventName, raw) => {
    let parsed
    try {
      parsed = JSON.parse(raw)
    } catch {
      if (raw) onToken?.(raw)
      return null
    }

    const type = parsed.type || eventName || ''

    if (type === 'meta') {
      onMeta?.(parsed)
      return null
    }
    if (type === 'token') {
      onToken?.(parsed.text || '')
      return null
    }
    if (type === 'status') {
      onStatus?.(parsed.text || '')
      return null
    }
    if (type === 'tool') {
      onTool?.(parsed)
      onStatus?.(parsed.name ? `正在调用工具：${parsed.name}` : '正在调用工具…')
      return null
    }
    if (type === 'approval') {
      onApproval?.(parsed)
      onStatus?.(parsed.name ? `等待审批：${parsed.name}` : '等待审批…')
      return null
    }
    if (type === 'tool_result') {
      onToolResult?.(parsed)
      return null
    }
    if (type === 'done') {
      onDone?.(parsed)
      return 'done'
    }
    if (type === 'cancelled') {
      onCancelled?.(parsed)
      return 'cancelled'
    }
    if (type === 'error') {
      onError?.(parsed.message || 'unknown error')
      return 'error'
    }
    // Legacy: bare {session_id} without type
    if (parsed.session_id && !parsed.type) {
      onMeta?.({ type: 'meta', session_id: parsed.session_id, stream_id: streamId })
      return null
    }
    return null
  }

  while (true) {
    const { done, value } = await reader.read()
    if (done) break

    buffer += decoder.decode(value, { stream: true })
    const lines = buffer.split('\n')
    buffer = lines.pop() || ''

    for (const line of lines) {
      const cleanLine = line.replace(/\r$/, '')

      if (cleanLine.startsWith('event:')) {
        sseEvent = cleanLine.slice(6).trim()
        continue
      }

      if (cleanLine === '') {
        if (!sseData) {
          sseEvent = ''
          continue
        }
        terminal = dispatch(sseEvent, sseData)
        sseData = ''
        sseEvent = ''
        if (terminal) {
          try {
            reader.cancel()
          } catch {
            /* ignore */
          }
          return terminal
        }
      } else if (cleanLine.startsWith('data:')) {
        if (sseData) sseData += '\n'
        sseData += cleanLine.slice(5).replace(/^ /, '')
      }
    }
  }

  return terminal || 'done'
}

/**
 * High-level: start a turn and consume its stream.
 * Returns { streamId, sessionId, terminal }.
 */
export async function streamChat(
  { sessionId, message },
  handlers = {},
  { signal } = {},
) {
  const started = await startChat({ sessionId, message })
  handlers.onMeta?.({
    type: 'meta',
    session_id: started.session_id,
    stream_id: started.stream_id,
  })
  const terminal = await connectStream(started.stream_id, handlers, { signal })
  return {
    streamId: started.stream_id,
    sessionId: started.session_id,
    terminal,
  }
}
