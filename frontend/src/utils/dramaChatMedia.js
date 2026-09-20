import {
  clearDramaChatJob,
  getDramaChatJob,
  isDramaJobPolling,
  markDramaJobPolling,
  upsertDramaChatJob,
} from '@/composables/useDramaChatProgress'

const VIDEO_ACTIONS = new Set(['export_timeline', 'mix_episode', 'produce_episode', 'create_from_premise'])
const TERMINAL_JOB = new Set(['done', 'error', 'cancelled'])

function isVideoUrl(url) {
  const u = String(url || '')
  return /\.mp4(\?|$)/i.test(u) || (u.includes('/api/workspace/file') && /\.mp4/i.test(u))
}

function dramaVideoTitle(action, slug, episode, { multi = false } = {}) {
  const showEp = multi && episode != null && episode !== ''
  const ep = showEp ? `第${episode}集` : ''
  if (action === 'export_timeline') return `${ep} 成片`.trim() || '漫剧成片'
  if (action === 'produce_episode') return `${ep} 完整成片`.trim() || '完整成片'
  if (action === 'create_from_premise') return `${ep} 一键成片`.trim() || '一键成片'
  if (action === 'mix_episode') return `${ep} 混音预览`.trim() || '混音预览'
  if (action === 'poll_job') return `${ep} 成片`.trim() || '漫剧成片'
  if (action === 'get') return `${ep} 已导出成片`.trim() || '已导出成片'
  const base = slug ? `${slug}` : '漫剧'
  return ep ? `${base} · ${ep}` : base
}

function sleep(ms, signal) {
  return new Promise((resolve, reject) => {
    if (signal?.aborted) {
      reject(new DOMException('Aborted', 'AbortError'))
      return
    }
    const t = setTimeout(resolve, ms)
    const onAbort = () => {
      clearTimeout(t)
      reject(new DOMException('Aborted', 'AbortError'))
    }
    signal?.addEventListener('abort', onAbort, { once: true })
  })
}

function dramaUiSnapshot(message, extra = {}) {
  const job = { ...(message?.dramaJob || {}), ...extra }
  return {
    state: String(job.state || ''),
    line: String(job.line || ''),
    pct: job.pct == null || Number.isNaN(Number(job.pct)) ? null : Number(job.pct),
    current: job.current ?? null,
    total: job.total ?? null,
    finished: job.finished ?? null,
    failed: job.failed ?? null,
    shot: job.shot ?? null,
    stage: job.stage || '',
    error: job.error || '',
    slug: job.slug || '',
    episode: job.episode ?? null,
    kind: job.kind || '',
    jobId: job.jobId || '',
    mediaReady: Boolean(job.mediaReady || (message?.media || []).length),
  }
}

/**
 * Write terminal tool.result (+ optional assistant text) back into session JSON.
 * Fire-and-forget safe: failures must not break the live UI.
 */
export async function persistDramaToolTerminal(message, tool, { sessionId } = {}) {
  const sid = String(sessionId || message?.sessionId || '').trim()
  const tid = String(tool?.id || '').trim()
  if (!sid || !tid || !tool) return false
  try {
    let payload
    try {
      payload = JSON.parse(tool.result || '{}')
    } catch {
      payload = { raw: String(tool.result || '') }
    }
    payload.ui = dramaUiSnapshot(message)
    tool.result = JSON.stringify(payload)
    const { patchSessionToolResult } = await import('@/api/sessions')
    await patchSessionToolResult(sid, {
      toolCallId: tid,
      content: tool.result,
      assistantContent: message?.content != null ? String(message.content) : null,
    })
    return true
  } catch {
    return false
  }
}

/**
 * Normalize job.progress into a chat-friendly progress object.
 */
export function formatDramaJobProgress(job) {
  const p = job?.progress || {}
  const status = String(job?.status || '')
  const current = Math.max(0, Number(p.current) || 0)
  const total = Math.max(0, Number(p.total) || 0)
  const finished = Math.max(0, Number(p.finished) || 0)
  const failed = Math.max(0, Number(p.failed) || 0)
  const ok = Math.max(0, Number(p.ok) || current || 0)
  // 进度按「已结束镜数」计，避免失败后仍显示 0%
  const doneN = Math.max(finished, ok + failed)
  const pct =
    status === 'done'
      ? 100
      : total > 0
        ? Math.min(99, Math.round((doneN / total) * 100))
        : null
  const shot = p.shot != null && p.shot !== '' ? Number(p.shot) || p.shot : null
  const stage = String(p.stage || '')
  const message = String(p.message || '').trim()
  const windingDown =
    status === 'running' && failed > 0 && (message.includes('加速收尾') || doneN < total)
  const parts = []
  if (pct != null) parts.push(`${pct}%`)
  if (total > 0) {
    if (doneN > 0) parts.push(`已结束 ${doneN}/${total} 镜`)
    if (ok > 0) parts.push(`成功 ${ok}`)
    if (failed > 0) parts.push(`失败 ${failed}`)
    if (doneN === 0) parts.push(`进行中 0/${total} 镜`)
  }
  if (shot != null) parts.push(`第 ${shot} 镜`)
  if (stage && stage !== 'shot' && stage !== 'done') parts.push(stage)
  if (message) parts.push(message)
  let head = '成片生成中'
  if (status === 'pending') head = '成片任务排队中'
  else if (windingDown) head = '已有失败，加速收尾中'
  else if (status === 'error') head = '成片失败'
  else if (status === 'done') head = '成片完成'
  const line =
    parts.length > 0
      ? `${head} · ${parts.join(' · ')}`
      : status === 'pending'
        ? '成片任务排队中…'
        : '成片生成中，请稍候…'
  return {
    line,
    pct,
    current: ok,
    total,
    finished: doneN,
    failed,
    shot,
    stage,
    message,
    status,
  }
}

/**
 * Turn raw job.error into a clean chat message.
 * Prefer backend structured text (集 / 步骤 / 细分 / 原因); never add「下一步」tips.
 */
export function humanizeDramaJobError(error, { episode, progress, slug } = {}) {
  const raw = String(error || '成片任务失败').trim()
  const ep = episode != null && episode !== '' ? Number(episode) : null

  if (/超过\s*\d+\s*分钟|停止轮询|等待超时|已停止前台等待/i.test(raw)) {
    return ep != null
      ? `第${ep}集：后台任务仍在处理或已结束`
      : '后台任务仍在处理或已结束'
  }

  // 后端已按「集 → 步骤 → 细分 → 原因」排版时直接展示
  if (/^第\s*\d+\s*集/.test(raw) || /^步骤：/m.test(raw) || /^第\d+集\s*·/.test(raw)) {
    return raw
  }

  const shotFromReason =
    raw.match(/第\s*(\d+)\s*镜/) ||
    raw.match(/Shot\s*(\d+)/i) ||
    (progress?.shot != null ? [null, String(progress.shot)] : null)
  const shotN = shotFromReason ? shotFromReason[1] : null

  const lines = []
  if (ep != null && shotN != null) {
    lines.push(`第${ep}集 · Shot ${shotN}`)
  } else if (ep != null) {
    lines.push(`第${ep}集渲染失败`)
  } else {
    lines.push('成片渲染失败')
  }
  lines.push(`原因：${raw}`)
  return lines.join('\n')
}

/**
 * Parse tiktok_drama tool JSON and return chat video attachment(s), if any.
 */
export function extractDramaVideosFromToolResult(resultRaw) {
  if (!resultRaw) return []
  let data
  try {
    data = JSON.parse(resultRaw)
  } catch {
    return []
  }
  if (!data || data.ok === false || data.error) return []

  const action = String(data.action || '')
  const slug = String(data.slug || '')
  const items = []
  const seen = new Set()

  const seriesCount = Number(data.series?.episode_count || data.create?.episode_count || 0)
  const multi =
    seriesCount > 1 ||
    (Array.isArray(data.episodes) && data.episodes.filter((e) => e?.play_url).length > 1)

  const push = (playUrl, episode, titleAction = action) => {
    if (!playUrl || !isVideoUrl(playUrl) || seen.has(playUrl)) return
    seen.add(playUrl)
    items.push({
      type: 'video',
      url: playUrl,
      slug,
      episode: episode != null && episode !== '' ? Number(episode) : null,
      title: dramaVideoTitle(titleAction, slug, episode, { multi }),
      action: titleAction || action,
    })
  }

  if (Array.isArray(data.episodes)) {
    for (const ep of data.episodes) {
      if (!ep) continue
      push(ep.play_url || '', ep.episode ?? ep.n, action || 'create_from_premise')
    }
  }

  if (action === 'poll_job') {
    if (data.status !== 'done') return items
    const inner = data.result || {}
    const playUrl = inner.play_url || data.play_url || ''
    const kind = String(data.kind || inner.kind || '')
    if (
      playUrl ||
      ['export', 'render_episode', 'produce_episode', 'create_from_premise'].includes(kind)
    ) {
      push(playUrl, inner.episode ?? data.episode ?? null, action)
    }
    return items
  }

  if (VIDEO_ACTIONS.has(action) || action === 'get') {
    push(data.play_url || '', data.episode ?? null, action)
  }

  return items
}

/**
 * Parse tiktok_drama tool JSON and return a chat video attachment, if any.
 */
export function extractDramaVideoFromToolResult(resultRaw) {
  return extractDramaVideosFromToolResult(resultRaw)[0] || null
}

export function attachDramaMedia(message, media) {
  if (!message || !media?.url) return
  if (!message.media) message.media = []
  if (message.media.some((m) => m.url === media.url)) return
  message.media.push(media)
}

/** Attach failed scene/video previews from job.progress.failure_media */
export function attachDramaFailureMedia(message, jobOrProgress) {
  const progress = jobOrProgress?.progress || jobOrProgress || {}
  const rows = progress.failure_media || progress.media || jobOrProgress?.failure_media || []
  if (!Array.isArray(rows)) return
  for (const row of rows) {
    if (!row?.url) continue
    attachDramaMedia(message, {
      ...row,
      type: row.type || 'video',
      failPreview: true,
      title: row.title || '失败预览',
    })
  }
}

export function enrichMessageWithDramaMedia(message) {
  if (!message || message.role !== 'assistant') return
  for (const tool of message.toolCalls || []) {
    for (const media of extractDramaVideosFromToolResult(tool.result)) {
      attachDramaMedia(message, media)
    }
  }
}

function parseToolJson(raw) {
  try {
    return JSON.parse(raw || '')
  } catch {
    return null
  }
}

function setMessageDramaJob(message, patch) {
  if (!message) return
  const incoming = { ...(patch || {}) }
  const jobId = String(incoming.jobId || message.dramaJob?.jobId || '').trim()
  if (jobId) incoming.jobId = jobId

  // Per-job list so multiple background tasks keep their own progress/error
  if (!Array.isArray(message.dramaJobs)) message.dramaJobs = []
  if (jobId) {
    const idx = message.dramaJobs.findIndex((j) => String(j.jobId || '') === jobId)
    const merged = { ...(idx >= 0 ? message.dramaJobs[idx] : {}), ...incoming, jobId }
    const state = String(merged.state || '')
    if (state === 'error') {
      merged.canRefresh = incoming.canRefresh !== false
      merged.canResume = incoming.canResume !== false
    } else if (state === 'done') {
      merged.canRefresh = false
      merged.canResume = false
    } else if (state === 'running' || state === 'pending') {
      merged.canRefresh = false
      merged.canResume = false
    }
    if (idx >= 0) message.dramaJobs.splice(idx, 1, merged)
    else message.dramaJobs.push(merged)

    if (state === 'done') {
      upsertDramaChatJob(jobId, { ...merged, state: 'done' })
      clearDramaChatJob(jobId)
    } else if (state === 'error' || state === 'timeout' || state === 'running' || state === 'pending') {
      upsertDramaChatJob(jobId, {
        ...merged,
        sessionId: message.sessionId || merged.sessionId || '',
      })
    }
  } else {
    message.dramaJob = { ...(message.dramaJob || {}), ...incoming }
  }

  // Primary pointer: prefer an active job, else latest error, else latest entry
  const jobs = message.dramaJobs || []
  const active = [...jobs].reverse().find((j) => j.state === 'running' || j.state === 'pending')
  const failed = [...jobs].reverse().find((j) => j.state === 'error' || j.state === 'timeout')
  message.dramaJob = active || failed || (jobs.length ? jobs[jobs.length - 1] : { ...(message.dramaJob || {}), ...incoming })
}

/**
 * Keep the chat turn open until create/produce finishes (or fails with a clear error).
 * Updates message.dramaJob / message.dramaJobs for persistent per-task progress/error UI.
 * 前台一直等到后台任务终态（成功/失败/取消）；与分钟超时无关。
 */
export async function awaitPendingDramaVideos(
  message,
  {
    signal,
    onStatus,
    intervalMs = 2000,
    sessionId,
    forcePoll = false,
    onlyJobId = '',
  } = {},
) {
  if (!message || message.role !== 'assistant') {
    return { waited: false, ok: true }
  }
  if (sessionId) message.sessionId = sessionId
  const tools = message.toolCalls || []
  const wantJob = String(onlyJobId || '').trim()

  const waiters = []
  for (const tool of tools) {
    if (String(tool.name || '') !== 'tiktok_drama') continue
    if (wantJob) {
      const data = parseToolJson(tool.result)
      if (String(data?.job_id || '') !== wantJob) continue
    }
    waiters.push(
      pollOneDramaTool(message, tool, {
        signal,
        onStatus,
        intervalMs,
        sessionId,
        forcePoll,
      }),
    )
  }
  if (!waiters.length) {
    enrichMessageWithDramaMedia(message)
    return { waited: false, ok: true }
  }
  const outcomes = await Promise.all(waiters)
  enrichMessageWithDramaMedia(message)
  const errors = outcomes.filter((o) => o?.error).map((o) => o.error)
  const waited = outcomes.some((o) => o?.waited)
  const lastError = errors.length ? errors.join('\n\n') : ''
  if (lastError) {
    message.content = lastError
    onStatus?.(lastError)
  }
  return { waited, ok: !lastError, error: lastError }
}

async function pollOneDramaTool(
  message,
  tool,
  { signal, onStatus, intervalMs, sessionId, forcePoll },
) {
  const data = parseToolJson(tool.result)
  if (!data) return { waited: false }

  // Tool already failed synchronously — surface it (手动查询时可强制再 poll).
  if (!forcePoll && (data.ok === false || data.error)) {
    const errText = humanizeDramaJobError(data.error || data.message || '成片失败', {
      episode: data.episode,
      slug: data.slug,
    })
    tool.status = 'error'
    setMessageDramaJob(message, {
      state: 'error',
      jobId: data.job_id ? String(data.job_id) : undefined,
      error: String(data.error || data.message || ''),
      line: errText,
      pct: null,
      canRefresh: !!data.job_id,
      episode: data.episode,
      slug: data.slug || '',
      kind: data.action || data.kind || '',
    })
    onStatus?.(errText)
    await persistDramaToolTerminal(message, tool, { sessionId })
    return { waited: true, error: errText }
  }

  if (forcePoll && data.job_id && (data.ok === false || data.error || data.status === 'error')) {
    const cleaned = { ...data }
    delete cleaned.error
    delete cleaned.ok
    cleaned.status = 'pending'
    tool.result = JSON.stringify(cleaned)
    tool.status = 'running'
    Object.assign(data, cleaned)
    delete data.error
    delete data.ok
  }

  const action = String(data.action || '')
  const queuedEpisode = Number(data.episode || 1) || 1
  const needCount = data.job_id
    ? 1
    : Math.max(
        1,
        Number(data.series?.episode_count || data.create?.episode_count || 0) ||
          (Array.isArray(data.episodes) ? data.episodes.filter((e) => e?.play_url).length : 0) ||
          (data.play_url ? 1 : 0) ||
          1,
      )

  if (extractDramaVideosFromToolResult(tool.result).length >= needCount) {
    // 显式续跑/强制 poll：即使旧结果已有 play_url，也要等新 job 终态，避免「秒结束」
    if (!forcePoll || !data.job_id) {
      for (const media of extractDramaVideosFromToolResult(tool.result)) {
        attachDramaMedia(message, media)
      }
      setMessageDramaJob(message, {
        state: 'done',
        pct: 100,
        line: '成片已就绪',
        jobId: data.job_id ? String(data.job_id) : undefined,
        episode: queuedEpisode,
        slug: data.slug || '',
      })
      return { waited: false }
    }
  }

  const needsVideo =
    VIDEO_ACTIONS.has(action) ||
    (action === 'poll_job' &&
      ['export', 'render_episode', 'produce_episode', 'create_from_premise', 'resume_produce'].includes(
        String(data.kind || ''),
      ))
  if (!needsVideo && !data.job_id) return { waited: false }

  tool.status = 'running'
  let slug = String(data.slug || '')
  let jobId = String(data.job_id || '')
  const pollJobId = jobId
  const ready = new Map()
  let lastProgress = formatDramaJobProgress({ status: 'pending', progress: {} })
  const jobLabel = `EP${String(queuedEpisode).padStart(2, '0')}`

  const publishProgress = (extra = {}) => {
    setMessageDramaJob(message, {
      state: 'running',
      jobId: pollJobId || jobId || undefined,
      slug,
      episode: queuedEpisode,
      kind: action || data.kind || '',
      label: jobLabel,
      ...lastProgress,
      ...extra,
    })
    const line = extra.line || lastProgress.line
    onStatus?.(needCount > 1 ? `${jobLabel} · ${line}` : line)
  }

  // Another awaiter already polling this job — follow until terminal (do not end early).
  if (pollJobId && isDramaJobPolling(pollJobId)) {
    publishProgress({ line: lastProgress.line || '成片生成中（共享进度）…' })
    while (true) {
      if (signal?.aborted) throw new DOMException('Aborted', 'AbortError')
      const stored = getDramaChatJob(pollJobId)
      if (stored) {
        lastProgress = {
          line: stored.line || lastProgress.line,
          pct: stored.pct,
          current: stored.current,
          total: stored.total,
          finished: stored.finished,
          failed: stored.failed,
          shot: stored.shot,
          stage: stored.stage,
          message: stored.message,
          status: stored.state,
        }
        publishProgress({
          state: stored.state,
          error: stored.error || '',
          line: stored.line || lastProgress.line,
        })
        if (TERMINAL_JOB.has(String(stored.state || ''))) {
          if (stored.state === 'error' || stored.state === 'cancelled') {
            tool.status = 'error'
            return { waited: true, error: stored.line || stored.error || '成片失败' }
          }
          break
        }
      }
      try {
        const { getJob } = await import('@/api/drama')
        const job = await getJob(pollJobId)
        lastProgress = formatDramaJobProgress(job)
        if (TERMINAL_JOB.has(String(job?.status || ''))) {
          if (job.status === 'error' || job.status === 'cancelled') {
            const terminalError = humanizeDramaJobError(job.error || `任务${job.status}`, {
              episode: queuedEpisode,
              progress: lastProgress,
              slug: slug || job?.slug || '',
            })
            tool.status = 'error'
            tool.result = JSON.stringify({
              ...(data || {}),
              ok: false,
              error: job.error || terminalError,
              status: job.status,
              progress: job.progress || {},
              failure_media: job.progress?.failure_media || [],
            })
            attachDramaFailureMedia(message, job)
            setMessageDramaJob(message, {
              state: 'error',
              jobId: pollJobId,
              line: terminalError,
              error: job.error || '',
              episode: queuedEpisode,
              slug: slug || job?.slug || '',
              ...lastProgress,
            })
            await persistDramaToolTerminal(message, tool, { sessionId })
            return { waited: true, error: terminalError }
          }
          break
        }
        publishProgress()
      } catch {
        /* keep following */
      }
      await sleep(intervalMs, signal)
    }
  }

  publishProgress()
  if (pollJobId) markDramaJobPolling(pollJobId, true)
  let terminalError = ''
  let sawJobDone = false
  let postDonePolls = 0
  try {
    while (true) {
      if (signal?.aborted) throw new DOMException('Aborted', 'AbortError')

      if (jobId) {
        try {
          const { getJob } = await import('@/api/drama')
          const job = await getJob(jobId)
          lastProgress = formatDramaJobProgress(job)
          setMessageDramaJob(message, {
            state: TERMINAL_JOB.has(String(job?.status || ''))
              ? String(job.status)
              : 'running',
            jobId,
            slug: slug || job?.slug || '',
            episode: queuedEpisode,
            kind: action || data.kind || '',
            label: jobLabel,
            error: job?.error || '',
            ...lastProgress,
          })
          onStatus?.(
            needCount > 1 ? `${jobLabel} · ${lastProgress.line}` : lastProgress.line,
          )

          if (TERMINAL_JOB.has(String(job?.status || ''))) {
            if (job.status === 'error' || job.status === 'cancelled') {
              terminalError = humanizeDramaJobError(job.error || `任务${job.status}`, {
                episode: queuedEpisode,
                progress: lastProgress,
                slug: slug || job?.slug || '',
              })
              tool.status = 'error'
              tool.result = JSON.stringify({
                ...(data || {}),
                ok: false,
                error: job.error || terminalError,
                status: job.status,
                progress: job.progress || {},
                failure_media: job.progress?.failure_media || [],
              })
              attachDramaFailureMedia(message, job)
              setMessageDramaJob(message, {
                state: 'error',
                jobId,
                line: terminalError,
                error: job.error || '',
                episode: queuedEpisode,
                slug: slug || job?.slug || '',
                ...lastProgress,
              })
              onStatus?.(terminalError)
              await persistDramaToolTerminal(message, tool, { sessionId })
              jobId = ''
              break
            }
            const inner = job.result || {}
            const playUrl = inner.play_url || job.play_url || ''
            slug = slug || String(inner.slug || job.slug || '')
            const epNo = Number(inner.episode ?? data.episode ?? queuedEpisode)
            if (playUrl && isVideoUrl(playUrl)) ready.set(epNo, playUrl)
            sawJobDone = true
            jobId = ''
          }
        } catch (err) {
          const status = Number(err?.status || 0)
          if (status === 404 || /404|not found|找不到/i.test(String(err?.message || ''))) {
            terminalError = `后台任务已失效（${pollJobId || jobId}），可能因服务重启丢失，请重新发起渲染`
            tool.status = 'error'
            tool.result = JSON.stringify({
              ...(data || {}),
              ok: false,
              error: terminalError,
              status: 'gone',
              job_id: pollJobId || jobId,
            })
            setMessageDramaJob(message, {
              state: 'error',
              jobId: pollJobId || jobId,
              line: terminalError,
              error: terminalError,
              episode: queuedEpisode,
              pct: lastProgress.pct || 0,
            })
            onStatus?.(terminalError)
            await persistDramaToolTerminal(message, tool, { sessionId })
            jobId = ''
            break
          }
        }
      }

      if (slug && !terminalError) {
        try {
          const { getEpisode } = await import('@/api/drama')
          const eps = data.job_id
            ? [queuedEpisode]
            : Array.from({ length: needCount }, (_, i) => i + 1)
          for (const ep of eps) {
            if (ready.has(ep)) continue
            const info = await getEpisode(slug, ep)
            const playUrl = info?.play_url || ''
            if (playUrl && isVideoUrl(playUrl)) ready.set(ep, playUrl)
          }
          if (ready.size) {
            onStatus?.(
              needCount > 1
                ? `${jobLabel} 成片进度 ${ready.size}/${needCount}…`
                : '成片已就绪，正在载入预览…',
            )
          }
        } catch {
          /* keep polling */
        }
      }

      if (terminalError) break

      if (ready.size >= needCount) {
        const episodes = [...ready.entries()]
          .sort((a, b) => a[0] - b[0])
          .map(([episode, play_url]) => ({ episode, play_url }))
        tool.status = 'done'
        tool.result = JSON.stringify({
          ok: true,
          action: action || 'create_from_premise',
          slug,
          episode: episodes[0]?.episode || queuedEpisode,
          play_url: episodes[0]?.play_url || '',
          series: data.series || { episode_count: needCount },
          episodes,
          job_id: pollJobId || undefined,
        })
        for (const ep of episodes) {
          attachDramaMedia(message, {
            type: 'video',
            url: ep.play_url,
            slug,
            episode: ep.episode,
            title: dramaVideoTitle(action || 'produce_episode', slug, ep.episode, {
              multi: needCount > 1,
            }),
            action: action || 'produce_episode',
          })
        }
        setMessageDramaJob(message, {
          state: 'done',
          pct: 100,
          line: '成片已就绪',
          error: '',
          mediaReady: true,
          jobId: pollJobId || undefined,
          episode: queuedEpisode,
          slug,
        })
        onStatus?.('')
        await persistDramaToolTerminal(message, tool, { sessionId })
        break
      }

      // 任务已终态但暂无 play_url：再等几轮拉 episode，然后收尾
      if (sawJobDone && !jobId) {
        postDonePolls += 1
        if (postDonePolls >= 20) {
          tool.status = 'done'
          tool.result = JSON.stringify({
            ...(data || {}),
            ok: true,
            status: 'done',
            slug,
            episode: queuedEpisode,
            job_id: pollJobId || undefined,
          })
          setMessageDramaJob(message, {
            state: 'done',
            pct: 100,
            line: '后台任务已结束',
            error: '',
            jobId: pollJobId || undefined,
            episode: queuedEpisode,
            slug,
          })
          await persistDramaToolTerminal(message, tool, { sessionId })
          break
        }
      }

      await sleep(intervalMs, signal)
    }

    if (terminalError) {
      return { waited: true, error: terminalError }
    }
    return { waited: true }
  } finally {
    if (pollJobId) markDramaJobPolling(pollJobId, false)
  }
}

export function findPendingDramaJobIds(message) {
  const ids = []
  for (const tool of message?.toolCalls || []) {
    if (String(tool.name || '') !== 'tiktok_drama') continue
    if (tool.status === 'error') continue
    try {
      const data = JSON.parse(tool.result || '')
      if (data?.ok === false) continue
      if (data?.status === 'gone' || data?.status === 'error' || data?.status === 'cancelled') continue
      if (data?.ui?.state === 'done' || data?.ui?.state === 'error') continue
      if (data?.job_id && !data?.play_url) ids.push(String(data.job_id))
    } catch {
      /* */
    }
  }
  return ids
}

/**
 * One-shot hydrate for history: if session still says「未完成」但队列已有终态，写回并展示。
 * Does not start a long poll loop.
 */
export async function hydrateDramaTerminalFromQueue(messages, { sessionId } = {}) {
  let any = false
  for (const message of messages || []) {
    if (message?.role !== 'assistant') continue
    for (const tool of message.toolCalls || []) {
      if (String(tool.name || '') !== 'tiktok_drama') continue
      let data
      try {
        data = JSON.parse(tool.result || '')
      } catch {
        continue
      }
      if (!data?.job_id) continue
      if (data.play_url || data.ui?.state === 'done' || data.ui?.state === 'error') continue
      if (data.ok === false && data.error && data.ui) continue
      try {
        const { getJob } = await import('@/api/drama')
        const job = await getJob(String(data.job_id))
        const status = String(job?.status || '')
        if (!TERMINAL_JOB.has(status)) continue
        const progress = formatDramaJobProgress(job)
        const ep = Number(job?.episode || data.episode || 1) || 1
        if (status === 'done') {
          const inner = job.result || {}
          const playUrl = inner.play_url || job.play_url || ''
          const slug = String(inner.slug || job.slug || data.slug || '')
          tool.status = 'done'
          tool.result = JSON.stringify({
            ...data,
            ok: true,
            status: 'done',
            slug,
            episode: ep,
            play_url: playUrl || data.play_url || '',
            progress: job.progress || {},
          })
          if (playUrl && isVideoUrl(playUrl)) {
            attachDramaMedia(message, {
              type: 'video',
              url: playUrl,
              slug,
              episode: ep,
              title: dramaVideoTitle(data.action || 'produce_episode', slug, ep),
              action: data.action || 'produce_episode',
            })
          }
          setMessageDramaJob(message, {
            state: 'done',
            jobId: String(data.job_id),
            slug,
            episode: ep,
            pct: 100,
            line: '成片已就绪',
            mediaReady: Boolean(playUrl),
            error: '',
          })
          if (!String(message.content || '').trim()) message.content = '成片已就绪'
        } else {
          const line = humanizeDramaJobError(job.error || `任务${status}`, {
            episode: ep,
            progress,
            slug: job?.slug || data.slug || '',
          })
          tool.status = 'error'
          tool.result = JSON.stringify({
            ...data,
            ok: false,
            status,
            error: job.error || line,
            progress: job.progress || {},
            failure_media: job.progress?.failure_media || [],
          })
          attachDramaFailureMedia(message, job)
          setMessageDramaJob(message, {
            state: 'error',
            jobId: String(data.job_id),
            slug: job?.slug || data.slug || '',
            episode: ep,
            line,
            error: job.error || '',
            ...progress,
          })
          message.content = line
        }
        await persistDramaToolTerminal(message, tool, { sessionId })
        any = true
      } catch {
        /* queue gone / network — keep folded idle prompt */
      }
    }
    enrichMessageWithDramaMedia(message)
  }
  return any
}

async function refreshStaleProduceJob(message, tool, data) {
  const action = String(data?.action || data?.kind || '')
  if (action !== 'produce_episode' && action !== 'create_from_premise') return false
  const slug = String(data?.slug || '').trim()
  if (!slug) return false
  const episode = Number(data?.episode ?? 1) || 1
  try {
    const { listJobs } = await import('@/api/drama')
    const res = await listJobs({ slug, active: false, limit: 50 })
    const jobs = (res?.jobs || []).filter(
      (j) => String(j.kind || '') === 'produce_episode' && Number(j.episode || 0) === episode,
    )
    if (!jobs.length) return false
    const latest = jobs[0]
    if (latest.status !== 'done') return false
    const playUrl = latest.result?.play_url || ''
    tool.status = 'done'
    tool.result = JSON.stringify({
      ...data,
      job_id: latest.job_id,
      ok: true,
      status: 'done',
      slug,
      episode,
      play_url: playUrl,
      progress: latest.progress || {},
    })
    if (playUrl && isVideoUrl(playUrl)) {
      attachDramaMedia(message, {
        type: 'video',
        url: playUrl,
        slug,
        episode,
        title: dramaVideoTitle(action, slug, episode),
        action,
      })
    }
    setMessageDramaJob(message, {
      state: 'done',
      jobId: String(latest.job_id),
      slug,
      episode,
      pct: 100,
      line: '成片已就绪',
      mediaReady: Boolean(playUrl),
      error: '',
    })
    if (!String(message.content || '').trim()) message.content = '成片已就绪'
    await persistDramaToolTerminal(message, tool, { sessionId: message.sessionId })
    return true
  } catch {
    return false
  }
}

export async function resumeDramaProgressForMessages(messages, opts = {}) {
  let any = false
  for (const message of messages || []) {
    if (message?.role !== 'assistant') continue
    const ids = findPendingDramaJobIds(message)
    if (!ids.length && message.dramaJob?.state !== 'running' && message.dramaJob?.state !== 'pending') {
      continue
    }
    for (const tool of message.toolCalls || []) {
      if (String(tool.name || '') !== 'tiktok_drama') continue
      try {
        const data = JSON.parse(tool.result || '')
        if (data?.ok === false || data?.status === 'gone' || data?.status === 'error') {
          // 历史失败但可能已在工作台续跑成功：查最新 job 覆盖为成功，避免残留「分镜失败」
          await refreshStaleProduceJob(message, tool, data)
          continue
        }
        if (data?.job_id && !data?.play_url) {
          tool.status = tool.status === 'error' ? 'error' : 'running'
          if (!message.dramaJob) {
            message.dramaJob = {
              state: 'running',
              jobId: String(data.job_id),
              slug: data.slug || '',
              episode: data.episode || 1,
              line: '成片生成中，正在恢复进度…',
            }
          }
        }
      } catch {
        /* */
      }
    }
    any = true
    await awaitPendingDramaVideos(message, opts)
  }
  return any
}
