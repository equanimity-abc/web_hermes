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

/**
 * Normalize job.progress into a chat-friendly progress object.
 */
export function formatDramaJobProgress(job) {
  const p = job?.progress || {}
  const current = Math.max(0, Number(p.current) || 0)
  const total = Math.max(0, Number(p.total) || 0)
  const pct =
    total > 0 ? Math.min(100, Math.round((current / total) * 100)) : job?.status === 'done' ? 100 : null
  const shot = p.shot != null && p.shot !== '' ? Number(p.shot) || p.shot : null
  const stage = String(p.stage || '')
  const message = String(p.message || '').trim()
  const parts = []
  if (pct != null) parts.push(`${pct}%`)
  if (total > 0) parts.push(`${current}/${total} 镜`)
  if (shot != null) parts.push(`第 ${shot} 镜`)
  if (stage && stage !== 'shot' && stage !== 'done') parts.push(stage)
  if (message) parts.push(message)
  const line =
    parts.length > 0
      ? `成片生成中 · ${parts.join(' · ')}`
      : job?.status === 'pending'
        ? '成片任务排队中…'
        : '成片生成中，请稍候…'
  return {
    line,
    pct,
    current,
    total,
    shot,
    stage,
    message,
    status: String(job?.status || ''),
  }
}

/**
 * Turn raw job.error into an actionable chat message.
 */
export function humanizeDramaJobError(error, { episode, progress, slug } = {}) {
  const raw = String(error || '成片任务失败').trim()
  const ep = episode != null && episode !== '' ? Number(episode) : null
  const shot = progress?.shot
  const pct = progress?.pct
  const current = progress?.current
  const total = progress?.total

  const progressBits = []
  if (pct != null) progressBits.push(`${pct}%`)
  if (total > 0) progressBits.push(`已完成 ${current}/${total} 镜`)
  if (shot != null) progressBits.push(`卡在第 ${shot} 镜`)

  let reason = raw
  let tip = ''
  if (/缺少本镜画面/.test(raw)) {
    tip =
      '请打开漫剧工作台 →「画面」页为该镜生成并锁定候选图，再重新渲染。'
  } else if (/身份验收|定妆|identity/i.test(raw)) {
    tip =
      '请打开漫剧工作台 →「角色」页生成并锁定定妆图，然后对该镜头或整集重新渲染。'
  } else if (/缺少可用模型 Key|ARK_API_KEY|专业档缺少/i.test(raw)) {
    tip = '请在设置里配置对应模型 API Key 后重试。'
  } else if (/QC 硬闸|响度/i.test(raw)) {
    tip = '可在工作台查看 QC 详情；工作台允许强制导出，对话 Agent 不会强制放行。'
  } else if (/真 I2V|Ken Burns|mock/i.test(raw)) {
    tip = '请检查 Seedance/I2V 密钥与配额后重试该镜。'
  }

  const lines = [
    ep != null ? `❌ 第 ${ep} 集渲染失败` : '❌ 成片渲染失败',
    progressBits.length ? `进度：${progressBits.join(' · ')}` : null,
    `原因：${reason}`,
    tip ? `下一步：${tip}` : null,
    slug ? `项目：${slug}` : null,
  ].filter(Boolean)
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
  message.dramaJob = { ...(message.dramaJob || {}), ...patch }
  const jobId = String(message.dramaJob.jobId || patch.jobId || '').trim()
  if (!jobId) return
  const state = String(message.dramaJob.state || '')
  if (state === 'done') {
    // Keep brief done record then drop so banner disappears.
    upsertDramaChatJob(jobId, { ...message.dramaJob, state: 'done' })
    clearDramaChatJob(jobId)
    return
  }
  upsertDramaChatJob(jobId, {
    ...message.dramaJob,
    sessionId: message.sessionId || message.dramaJob.sessionId || '',
  })
}

/**
 * Keep the chat turn open until create/produce finishes (or fails with a clear error).
 * Updates message.dramaJob for persistent progress/error UI.
 */
export async function awaitPendingDramaVideos(
  message,
  {
    signal,
    onStatus,
    timeoutMs = 45 * 60 * 1000,
    intervalMs = 2000,
    sessionId,
  } = {},
) {
  if (!message || message.role !== 'assistant') {
    return { waited: false, ok: true }
  }
  if (sessionId) message.sessionId = sessionId
  const tools = message.toolCalls || []
  let waited = false
  let lastError = ''

  for (const tool of tools) {
    if (String(tool.name || '') !== 'tiktok_drama') continue

    const data = parseToolJson(tool.result)
    if (!data) continue

    // Tool already failed synchronously — surface it.
    if (data.ok === false || data.error) {
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
      })
      onStatus?.(errText)
      message.content = errText
      lastError = errText
      waited = true
      continue
    }

    const action = String(data.action || '')
    // Background produce queues the first episode; wait for that job (not all series play_urls).
    const queuedEpisode = Number(data.episode || 1) || 1
    const needCount = data.job_id ? 1 : Math.max(
      1,
      Number(data.series?.episode_count || data.create?.episode_count || 0) ||
        (Array.isArray(data.episodes) ? data.episodes.filter((e) => e?.play_url).length : 0) ||
        (data.play_url ? 1 : 0) ||
        1,
    )

    if (extractDramaVideosFromToolResult(tool.result).length >= needCount) {
      for (const media of extractDramaVideosFromToolResult(tool.result)) {
        attachDramaMedia(message, media)
      }
      setMessageDramaJob(message, { state: 'done', pct: 100, line: '成片已就绪' })
      continue
    }

    const needsVideo =
      VIDEO_ACTIONS.has(action) ||
      (action === 'poll_job' &&
        ['export', 'render_episode', 'produce_episode', 'create_from_premise'].includes(
          String(data.kind || ''),
        ))
    if (!needsVideo && !data.job_id) continue

    waited = true
    tool.status = 'running'
    const started = Date.now()
    let slug = String(data.slug || '')
    let jobId = String(data.job_id || '')
    const pollJobId = jobId
    const ready = new Map()
    let lastProgress = formatDramaJobProgress({ status: 'pending', progress: {} })

    // Another awaiter already polling this job — attach store progress and skip.
    if (pollJobId && isDramaJobPolling(pollJobId)) {
      const stored = getDramaChatJob(pollJobId)
      if (stored) {
        message.dramaJob = { ...(message.dramaJob || {}), ...stored, jobId: pollJobId }
      } else {
        setMessageDramaJob(message, {
          state: 'running',
          jobId: pollJobId,
          slug,
          episode: queuedEpisode,
          ...lastProgress,
        })
      }
      continue
    }

    setMessageDramaJob(message, {
      state: 'running',
      jobId,
      slug,
      episode: queuedEpisode,
      ...lastProgress,
    })
    onStatus?.(
      needCount > 1
        ? `成片生成中（共 ${needCount} 集），请稍候…`
        : lastProgress.line,
    )

    if (pollJobId) markDramaJobPolling(pollJobId, true)
    let terminalError = ''
    try {
      while (Date.now() - started < timeoutMs) {
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
              error: job?.error || '',
              ...lastProgress,
            })
            onStatus?.(lastProgress.line)

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
                })
                setMessageDramaJob(message, {
                  state: 'error',
                  jobId,
                  line: terminalError,
                  error: job.error || '',
                  ...lastProgress,
                })
                onStatus?.(terminalError)
                message.content = terminalError
                lastError = terminalError
                jobId = ''
                break
              }
              const inner = job.result || {}
              const playUrl = inner.play_url || job.play_url || ''
              slug = slug || String(inner.slug || job.slug || '')
              const epNo = Number(inner.episode ?? data.episode ?? queuedEpisode)
              if (playUrl && isVideoUrl(playUrl)) ready.set(epNo, playUrl)
              jobId = ''
            }
          } catch (err) {
            // 后端重启后内存 job 会丢：404 应立刻停轮询，避免刷屏。
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
                pct: lastProgress.pct || 0,
              })
              onStatus?.(terminalError)
              message.content = terminalError
              lastError = terminalError
              jobId = ''
              break
            }
            /* 其它瞬时错误：继续轮询 */
          }
        }

        if (slug && !terminalError) {
          try {
            const { getEpisode } = await import('@/api/drama')
            // When we have a background job, only require the queued episode.
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
                  ? `成片进度 ${ready.size}/${needCount}…`
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
          })
          onStatus?.('')
          break
        }

        await sleep(intervalMs, signal)
      }

      if (terminalError) {
        continue
      }

      if (!extractDramaVideoFromToolResult(tool.result) && tool.status === 'running') {
        tool.status = 'error'
        const timeoutMsg = humanizeDramaJobError('成片等待超时，请稍后在漫剧工作台查看或重试', {
          episode: queuedEpisode,
          progress: lastProgress,
          slug,
        })
        setMessageDramaJob(message, {
          state: 'error',
          jobId: pollJobId || undefined,
          line: timeoutMsg,
          error: 'timeout',
          ...lastProgress,
        })
        onStatus?.(timeoutMsg)
        message.content = timeoutMsg
        lastError = timeoutMsg
      }
    } finally {
      if (pollJobId) markDramaJobPolling(pollJobId, false)
    }
  }

  enrichMessageWithDramaMedia(message)
  return { waited, ok: !lastError, error: lastError }
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
      if (data?.job_id && !data?.play_url) ids.push(String(data.job_id))
    } catch {
      /* */
    }
  }
  return ids
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
        if (data?.ok === false || data?.status === 'gone' || data?.status === 'error') continue
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
