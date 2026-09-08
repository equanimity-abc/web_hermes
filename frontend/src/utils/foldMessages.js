/**
 * Fold raw OpenAI-style session messages into UI messages.
 * Attaches toolCalls onto the final assistant text turn.
 */
import { enrichMessageWithDramaMedia, humanizeDramaJobError } from '@/utils/dramaChatMedia'

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
      // 历史会话：优先还原已写回的终态 ui，打开即与上次结束时一致
      for (const tool of msg.toolCalls || []) {
        try {
          const parsed = JSON.parse(tool.result || '')
          if (!parsed?.job_id && !parsed?.ui && !parsed?.play_url) continue
          const ui = parsed.ui && typeof parsed.ui === 'object' ? parsed.ui : null
          const failed =
            parsed?.ok === false ||
            !!parsed?.error ||
            parsed?.status === 'error' ||
            parsed?.status === 'cancelled' ||
            parsed?.status === 'gone' ||
            ui?.state === 'error'
          if (failed) {
            tool.status = 'error'
            const progress = parsed.progress || {}
            const line =
              (ui && ui.line) ||
              humanizeDramaJobError(parsed.error || parsed.message || '任务失败', {
                episode: parsed.episode ?? ui?.episode,
                progress: {
                  pct: ui?.pct ?? null,
                  current: progress.current ?? ui?.current,
                  total: progress.total ?? ui?.total,
                  finished: progress.finished ?? ui?.finished,
                  failed: progress.failed ?? ui?.failed,
                  shot: progress.shot ?? ui?.shot,
                },
                slug: parsed.slug || ui?.slug || '',
              })
            if (!String(msg.content || '').trim()) msg.content = line
            msg.dramaJob = {
              state: 'error',
              jobId: String(parsed.job_id || ui?.jobId || ''),
              slug: parsed.slug || ui?.slug || '',
              episode: parsed.episode ?? ui?.episode ?? 1,
              kind: parsed.kind || parsed.action || ui?.kind || 'produce_episode',
              line,
              pct: ui?.pct ?? null,
              current: ui?.current ?? progress.current ?? null,
              total: ui?.total ?? progress.total ?? null,
              finished: ui?.finished ?? progress.finished ?? null,
              failed: ui?.failed ?? progress.failed ?? null,
              shot: ui?.shot ?? progress.shot ?? null,
              error: String(parsed.error || ui?.error || ''),
              canRefresh: true,
              canResume: true,
            }
            continue
          }
          if (parsed?.play_url || ui?.state === 'done' || ui?.mediaReady) {
            tool.status = 'done'
            msg.dramaJob = {
              state: 'done',
              jobId: String(parsed.job_id || ui?.jobId || ''),
              slug: parsed.slug || ui?.slug || '',
              episode: parsed.episode ?? ui?.episode ?? 1,
              kind: parsed.kind || parsed.action || ui?.kind || 'produce_episode',
              line: (ui && ui.line) || '成片已就绪',
              pct: 100,
              mediaReady: true,
              canRefresh: false,
              canResume: false,
            }
            continue
          }
          // 尚未终态（旧数据）：展示静态提示，不自动轮询
          tool.status = tool.status === 'error' ? 'error' : 'done'
          msg.isStreaming = false
          msg.dramaJob = {
            state: 'idle',
            jobId: String(parsed.job_id || ''),
            slug: parsed.slug || '',
            episode: parsed.episode || 1,
            kind: parsed.kind || parsed.action || 'produce_episode',
            line: (ui && ui.line) || '历史任务未完成，可查询进度或继续渲染',
            pct: ui?.pct ?? null,
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
  // 重启后不自动轮询；若 tool.result 已写回终态则直接还原展示
  if (pendingTools.length) {
    let pendingJobId = ''
    let pendingSlug = ''
    let pendingEpisode = 1
    let dramaJob = undefined
    let content = ''
    for (const t of pendingTools) {
      if (!t.result) {
        t.status = 'done'
        continue
      }
      try {
        const parsed = JSON.parse(t.result || '')
        const ui = parsed.ui && typeof parsed.ui === 'object' ? parsed.ui : null
        if (parsed?.job_id) {
          pendingJobId = String(parsed.job_id)
          pendingSlug = parsed.slug || ui?.slug || pendingSlug
          pendingEpisode = parsed.episode ?? ui?.episode ?? pendingEpisode
        }
        const failed =
          parsed?.ok === false ||
          !!parsed?.error ||
          parsed?.status === 'error' ||
          parsed?.status === 'cancelled' ||
          parsed?.status === 'gone' ||
          ui?.state === 'error'
        if (failed) {
          t.status = 'error'
          const line =
            (ui && ui.line) ||
            humanizeDramaJobError(parsed.error || parsed.message || '任务失败', {
              episode: parsed.episode ?? ui?.episode,
              progress: parsed.progress || ui || {},
              slug: parsed.slug || ui?.slug || '',
            })
          content = line
          dramaJob = {
            state: 'error',
            jobId: pendingJobId,
            slug: pendingSlug,
            episode: pendingEpisode,
            kind: parsed.kind || parsed.action || ui?.kind || 'produce_episode',
            line,
            pct: ui?.pct ?? null,
            error: String(parsed.error || ui?.error || ''),
            canRefresh: true,
            canResume: true,
          }
        } else if (parsed?.play_url || ui?.state === 'done') {
          t.status = 'done'
          dramaJob = {
            state: 'done',
            jobId: pendingJobId,
            slug: pendingSlug,
            episode: pendingEpisode,
            line: (ui && ui.line) || '成片已就绪',
            pct: 100,
            mediaReady: true,
            canRefresh: false,
            canResume: false,
          }
        } else if (parsed?.job_id && !parsed?.play_url) {
          t.status = 'done'
          dramaJob = {
            state: 'idle',
            jobId: pendingJobId,
            slug: pendingSlug,
            episode: pendingEpisode,
            line: (ui && ui.line) || '历史任务未完成，可查询进度或继续渲染',
            pct: ui?.pct ?? null,
            canRefresh: true,
            canResume: true,
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
      content,
      toolCalls: pendingTools,
      isStreaming: false,
      status: '',
      dramaJob:
        dramaJob ||
        (pendingJobId
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
          : undefined),
    }
    enrichMessageWithDramaMedia(msg)
    out.push(msg)
  }

  return out
}
