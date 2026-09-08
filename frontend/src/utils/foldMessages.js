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
          else if (
            parsed &&
            parsed.job_id &&
            !parsed.play_url &&
            parsed.ok !== false &&
            parsed.status !== 'gone' &&
            parsed.status !== 'error' &&
            parsed.status !== 'cancelled'
          ) {
            // 历史加载不标 running，避免 UI 误以为仍在自动轮询
            hit.status = 'done'
          }
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
      // 历史会话：未完成/失败任务只展示，不自动轮询；需用户点「查询进度」
      for (const tool of msg.toolCalls || []) {
        try {
          const parsed = JSON.parse(tool.result || '')
          if (!parsed?.job_id) continue
          const failed =
            parsed?.ok === false ||
            !!parsed?.error ||
            parsed?.status === 'error' ||
            parsed?.status === 'cancelled' ||
            parsed?.status === 'gone'
          if (failed) {
            tool.status = 'error'
            msg.dramaJob = {
              state: 'error',
              jobId: String(parsed.job_id),
              slug: parsed.slug || '',
              episode: parsed.episode || 1,
              kind: parsed.kind || parsed.action || 'produce_episode',
              line: String(parsed.error || parsed.message || '任务失败'),
              canRefresh: true,
              canResume: true,
            }
            continue
          }
          if (parsed?.play_url) continue
          tool.status = tool.status === 'error' ? 'error' : 'done'
          msg.isStreaming = false
          msg.dramaJob = {
            state: 'idle',
            jobId: String(parsed.job_id),
            slug: parsed.slug || '',
            episode: parsed.episode || 1,
            kind: parsed.kind || parsed.action || 'produce_episode',
            line: '历史任务未完成，可查询进度或继续渲染',
            canRefresh: true,
            canResume: true,
          }
        } catch {
          /* ignore */
        }
      }
      enrichMessageWithDramaMedia(msg)
      out.push(msg)
      pendingTools = []
    }
  }

  // Incomplete turn: tool_calls already persisted but final assistant text not yet.
  // 重启后不自动轮询，留给手动「查询进度」
  if (pendingTools.length) {
    let pendingJobId = ''
    let pendingSlug = ''
    let pendingEpisode = 1
    for (const t of pendingTools) {
      if (!t.result) {
        t.status = 'done'
        continue
      }
      try {
        const parsed = JSON.parse(t.result || '')
        if (parsed?.job_id && !parsed?.play_url) {
          pendingJobId = String(parsed.job_id)
          pendingSlug = parsed.slug || pendingSlug
          pendingEpisode = parsed.episode || pendingEpisode
          if (parsed?.ok === false || parsed?.error || parsed?.status === 'error') {
            t.status = 'error'
          } else {
            t.status = 'done'
          }
        } else if (t.status === 'running') {
          t.status = 'done'
        }
      } catch {
        if (t.status === 'running') t.status = 'done'
      }
    }
    const msg = {
      role: 'assistant',
      content: '',
      toolCalls: pendingTools,
      isStreaming: false,
      status: '',
      dramaJob: pendingJobId
        ? {
            state: pendingTools.some((t) => t.status === 'error') ? 'error' : 'idle',
            jobId: pendingJobId,
            slug: pendingSlug,
            episode: pendingEpisode,
            line: pendingTools.some((t) => t.status === 'error')
              ? '历史任务失败，可点「继续渲染」'
              : '历史任务未完成，可查询进度或继续渲染',
            canRefresh: true,
            canResume: true,
          }
        : undefined,
    }
    enrichMessageWithDramaMedia(msg)
    out.push(msg)
  }

  return out
}
