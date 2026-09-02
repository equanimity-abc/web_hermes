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
      push(
        playUrl,
        inner.episode ?? data.episode ?? null,
        action,
      )
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

/**
 * Keep the chat turn open until create/produce finishes and play_url is ready.
 */
export async function awaitPendingDramaVideos(
  message,
  {
    signal,
    onStatus,
    timeoutMs = 45 * 60 * 1000,
    intervalMs = 2000,
  } = {},
) {
  if (!message || message.role !== 'assistant') return false
  const tools = message.toolCalls || []
  let waited = false

  for (const tool of tools) {
    if (String(tool.name || '') !== 'tiktok_drama') continue

    const data = parseToolJson(tool.result)
    if (!data || data.ok === false || data.error) continue

    const action = String(data.action || '')
    const expected = Math.max(
      1,
      Number(data.series?.episode_count || data.create?.episode_count || 0) ||
        (Array.isArray(data.episodes) ? data.episodes.filter((e) => e?.play_url).length : 0) ||
        (data.play_url ? 1 : 0) ||
        1,
    )
    // Prefer declared series size when present.
    const seriesCount = Number(data.series?.episode_count || data.create?.episode_count || 0)
    const needCount = seriesCount > 0 ? seriesCount : expected

    if (extractDramaVideosFromToolResult(tool.result).length >= needCount) {
      for (const media of extractDramaVideosFromToolResult(tool.result)) {
        attachDramaMedia(message, media)
      }
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
    const ready = new Map()

    onStatus?.(needCount > 1 ? `成片生成中（共 ${needCount} 集），请稍候…` : '成片生成中，请稍候…')

    while (Date.now() - started < timeoutMs) {
      if (signal?.aborted) throw new DOMException('Aborted', 'AbortError')

      if (jobId) {
        try {
          const { getJob } = await import('@/api/drama')
          const job = await getJob(jobId)
          const progress = job?.progress || {}
          if (progress.message) onStatus?.(`成片生成中：${progress.message}`)
          else if (job?.status === 'running' || job?.status === 'pending') {
            onStatus?.(
              needCount > 1 ? `成片生成中（共 ${needCount} 集），请稍候…` : '成片生成中，请稍候…',
            )
          }
          if (TERMINAL_JOB.has(String(job?.status || ''))) {
            if (job.status === 'error') {
              tool.status = 'error'
              tool.result = JSON.stringify({
                ...(data || {}),
                error: job.error || '成片任务失败',
                status: 'error',
              })
              break
            }
            const inner = job.result || {}
            const playUrl = inner.play_url || job.play_url || ''
            slug = slug || String(inner.slug || job.slug || '')
            const epNo = Number(inner.episode ?? data.episode ?? 1)
            if (playUrl && isVideoUrl(playUrl)) ready.set(epNo, playUrl)
            jobId = ''
          }
        } catch {
          /* keep polling */
        }
      }

      if (slug) {
        try {
          const { getEpisode } = await import('@/api/drama')
          for (let ep = 1; ep <= needCount; ep += 1) {
            if (ready.has(ep)) continue
            const info = await getEpisode(slug, ep)
            const playUrl = info?.play_url || ''
            if (playUrl && isVideoUrl(playUrl)) ready.set(ep, playUrl)
          }
          if (ready.size) {
            onStatus?.(
              needCount > 1 ? `成片进度 ${ready.size}/${needCount}…` : '成片已就绪，正在载入预览…',
            )
          }
        } catch {
          /* keep polling */
        }
      }

      if (ready.size >= needCount) {
        const episodes = [...ready.entries()]
          .sort((a, b) => a[0] - b[0])
          .map(([episode, play_url]) => ({ episode, play_url }))
        tool.status = 'done'
        tool.result = JSON.stringify({
          ok: true,
          action: action || 'create_from_premise',
          slug,
          episode: episodes[0]?.episode || 1,
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
        onStatus?.('')
        break
      }

      await sleep(intervalMs, signal)
    }

    if (!extractDramaVideoFromToolResult(tool.result) && tool.status === 'running') {
      tool.status = 'error'
      onStatus?.('成片等待超时，请稍后在漫剧工作台查看或重试')
    }
  }

  enrichMessageWithDramaMedia(message)
  return waited
}
