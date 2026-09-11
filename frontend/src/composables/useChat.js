import { nextTick, ref } from 'vue'
import {
  cancelChat,
  respondApproval,
  SessionBusyError,
  streamChat,
  uploadWorkspaceFile,
} from '@/api/chat'
import * as dramaApi from '@/api/drama'
import {
  attachDramaMedia,
  awaitPendingDramaVideos,
  enrichMessageWithDramaMedia,
  extractDramaVideoFromToolResult,
} from '@/utils/dramaChatMedia'
import { stashSessionMessages } from '@/composables/useDramaChatProgress'

/**
 * Conversation messages + streaming send loop (P4/P5: cancel + approval).
 *
 * @param {{
 *   getSessionId: () => string|null,
 *   setSessionId: (id: string) => void,
 *   scrollToBottom?: () => void,
 *   onTurnComplete?: () => void | Promise<void>,
 * }} deps
 */
export function useChat(deps) {
  const messages = ref([])
  const userInput = ref('')
  const isLoading = ref(false)
  const statusText = ref('')
  const activeStreamId = ref(null)
  const pendingApproval = ref(null)
  const approvalBusy = ref(false)

  let abortController = null

  function scrollToBottom() {
    deps.scrollToBottom?.()
  }

  function lastAssistant() {
    const last = messages.value[messages.value.length - 1]
    return last?.role === 'assistant' ? last : null
  }

  function ensureToolCalls(msg) {
    if (!msg.toolCalls) msg.toolCalls = []
    return msg.toolCalls
  }

  function finishAssistant(opts = {}) {
    const last = lastAssistant()
    if (!last) return
    last.isStreaming = false
    // Keep progress/error status visible when a drama job failed or is still informative.
    const dramaState = String(last.dramaJob?.state || '')
    if (dramaState === 'error') {
      last.status = last.dramaJob?.line || last.status || ''
    } else if (dramaState === 'done') {
      last.status = ''
    } else if (opts.cancelled && dramaState === 'idle') {
      last.status = last.dramaJob?.line || '已停止'
    } else if (!opts.keepStatus) {
      last.status = ''
    }
    if (opts.cancelled && !last.content) {
      last.content = '（已停止生成）'
      last.cancelled = true
    } else if (opts.cancelled) {
      last.cancelled = true
    }
    if (last.toolCalls) {
      last.toolCalls.forEach((t) => {
        if (t.status === 'error' || t.status === 'denied' || t.status === 'cancelled') return
        if (t.status === 'running' || t.status === 'awaiting_approval') {
          t.status = opts.cancelled ? 'cancelled' : 'done'
        }
      })
    }
  }

  function resetConversation() {
    messages.value = []
    userInput.value = ''
    statusText.value = ''
    activeStreamId.value = null
    pendingApproval.value = null
    approvalBusy.value = false
  }

  function setMessages(list) {
    messages.value = list
  }

  function collectActiveDramaJobIds(msg) {
    const ids = new Set()
    const push = (id) => {
      const s = String(id || '').trim()
      if (s) ids.add(s)
    }
    push(msg?.dramaJob?.jobId)
    for (const j of msg?.dramaJobs || []) push(j?.jobId)
    for (const tool of msg?.toolCalls || []) {
      if (String(tool?.name || '') !== 'tiktok_drama') continue
      try {
        const data = JSON.parse(tool.result || '')
        if (!data?.job_id) continue
        // 成片轮询阶段 tool 可能已是 done，但 job 仍在跑
        if (data.play_url || data.status === 'done') continue
        push(data.job_id)
      } catch {
        /* ignore */
      }
    }
    return [...ids]
  }

  function stopGeneration() {
    const sid = activeStreamId.value
    const last = lastAssistant()
    const dramaJobIds = collectActiveDramaJobIds(last)
    pendingApproval.value = null

    // 1) 立刻打断本地等待（SSE / 成片轮询 / 续跑）
    try {
      abortController?.abort()
    } catch {
      /* ignore */
    }

    // 2) 立刻解锁输入框与停止按钮，不等后端
    isLoading.value = false
    statusText.value = ''
    if (last) {
      last.isStreaming = false
      if (last.dramaJob && ['running', 'pending', 'error'].includes(String(last.dramaJob.state || ''))) {
        last.dramaJob = {
          ...last.dramaJob,
          state: 'idle',
          line: '已停止',
          resuming: false,
          refreshing: false,
          canResume: true,
          canRefresh: Boolean(last.dramaJob.jobId),
        }
        last.dramaJobs = [last.dramaJob]
        last.status = '已停止'
      } else if (!last.content) {
        last.status = ''
      }
    }
    activeStreamId.value = null

    // 3) 后台取消：聊天流 + 漫剧任务（不 await，避免按钮像卡住）
    if (sid) {
      const cancelAbort = new AbortController()
      const timer = setTimeout(() => cancelAbort.abort(), 2500)
      cancelChat(sid, cancelAbort.signal)
        .catch((e) => console.error('cancel chat failed:', e))
        .finally(() => clearTimeout(timer))
    }
    for (const jobId of dramaJobIds) {
      dramaApi.cancelJob(jobId).catch((e) => console.error('cancel drama job failed:', e))
    }
  }

  async function decideApproval(decision) {
    const pending = pendingApproval.value
    if (!pending || approvalBusy.value) return
    approvalBusy.value = true
    try {
      await respondApproval({
        streamId: pending.stream_id || activeStreamId.value,
        approvalId: pending.approval_id,
        decision,
      })
      const last = lastAssistant()
      const hit = last?.toolCalls?.find(
        (t) => t.id && t.id === pending.tool_call_id,
      )
      if (hit) {
        hit.status = decision === 'approved' ? 'running' : 'denied'
      }
      pendingApproval.value = null
    } catch (e) {
      console.error('approval respond failed:', e)
    } finally {
      approvalBusy.value = false
    }
  }

  async function uploadFile(file) {
    if (!file || isLoading.value) return null
    const meta = await uploadWorkspaceFile(file)
    const path = meta.path || file.name
    const note = `已上传到 workspace：\`${path}\``
    if (userInput.value.trim()) {
      userInput.value = `${userInput.value.trim()}\n${note}`
    } else {
      userInput.value = note
    }
    return meta
  }

  async function sendMessage() {
    const content = userInput.value.trim()
    if (!content || isLoading.value) return

    messages.value.push({ role: 'user', content, isStreaming: false })
    userInput.value = ''
    isLoading.value = true
    statusText.value = ''
    pendingApproval.value = null
    messages.value.push({
      role: 'assistant',
      content: '',
      toolCalls: [],
      isStreaming: true,
      status: '',
    })
    stashCurrent(deps.getSessionId?.() || '')
    await nextTick()
    scrollToBottom()

    abortController = new AbortController()
    let terminal = null

    try {
      const result = await streamChat(
        { sessionId: deps.getSessionId(), message: content },
        {
          onMeta(meta) {
            if (meta.stream_id) activeStreamId.value = meta.stream_id
            if (meta.session_id && !deps.getSessionId()) {
              deps.setSessionId(meta.session_id)
            }
          },
          onToken(text) {
            statusText.value = ''
            const last = lastAssistant()
            if (last) {
              last.status = ''
              last.content += text
              nextTick(() => scrollToBottom())
            }
          },
          onStatus(text) {
            statusText.value = text || ''
            const last = lastAssistant()
            if (last?.isStreaming) {
              last.status = text || ''
              nextTick(() => scrollToBottom())
            }
          },
          onTool(evt) {
            const last = lastAssistant()
            if (!last) return
            const list = ensureToolCalls(last)
            list.push({
              id: evt.tool_call_id || `tmp-${list.length}`,
              name: evt.name || '',
              arguments: evt.arguments || '',
              result: '',
              status: 'running',
            })
            if (String(evt.name || '') === 'tiktok_drama') {
              last.status = '成片流水线运行中，完成后会自动显示视频…'
              statusText.value = last.status
            }
            nextTick(() => scrollToBottom())
          },
          onApproval(evt) {
            pendingApproval.value = evt
            const last = lastAssistant()
            if (!last?.toolCalls) return
            const hit =
              last.toolCalls.find((t) => t.id && t.id === evt.tool_call_id) ||
              last.toolCalls.find((t) => t.name === evt.name && t.status === 'running')
            if (hit) hit.status = 'awaiting_approval'
            nextTick(() => scrollToBottom())
          },
          onToolResult(evt) {
            pendingApproval.value = null
            const last = lastAssistant()
            if (!last?.toolCalls) return
            const hit =
              last.toolCalls.find((t) => t.id && t.id === evt.tool_call_id) ||
              last.toolCalls.find(
                (t) =>
                  t.name === evt.name &&
                  (t.status === 'running' || t.status === 'awaiting_approval'),
              )
            if (!hit) return
            hit.result = evt.content || ''
            if (evt.denied) {
              hit.status = 'denied'
            } else {
              hit.status = 'done'
              try {
                const parsed = JSON.parse(hit.result)
                if (parsed && parsed.error) hit.status = 'error'
                else if (parsed && parsed.job_id && !parsed.play_url) {
                  // 后台成片：工具先返回 job_id，前端继续轮询，卡片保持「运行中」
                  hit.status = 'running'
                  last.status = '成片已提交后台，正在等待进度…'
                  statusText.value = last.status
                } else {
                  const media = extractDramaVideoFromToolResult(hit.result)
                  if (media) attachDramaMedia(last, media)
                }
              } catch {
                /* ignore */
              }
            }
            nextTick(() => scrollToBottom())
          },
          onDone() {
            terminal = 'done'
          },
          onCancelled() {
            terminal = 'cancelled'
          },
          onError(message) {
            terminal = 'error'
            const last = lastAssistant()
            if (last) {
              last.content = `❌ 错误: ${message}`
            }
          },
        },
        { signal: abortController.signal },
      )
      if (result?.sessionId && !deps.getSessionId()) {
        deps.setSessionId(result.sessionId)
      }
      if (!terminal) terminal = result?.terminal || 'done'
    } catch (e) {
      if (e?.name === 'AbortError') {
        terminal = terminal || 'cancelled'
      } else if (e instanceof SessionBusyError) {
        const last = lastAssistant()
        if (last) {
          last.content = `❌ ${e.message}`
          last.isStreaming = false
        }
        terminal = 'error'
      } else {
        const last = lastAssistant()
        if (last) {
          last.content = `❌ 错误: ${e.message}`
        }
        terminal = 'error'
      }
    } finally {
      // 成片未就绪时继续等待后台 job；用户已点停止则不再等待
      const stopped = Boolean(abortController?.signal?.aborted) || terminal === 'cancelled'
      if (!stopped) {
        const last = lastAssistant()
        if (last) {
          try {
            enrichMessageWithDramaMedia(last)
            const hasVideo = (last.media || []).some((m) => m?.url)
            const hadDramaTool = (last.toolCalls || []).some(
              (t) => String(t.name || '') === 'tiktok_drama',
            )
            const toolNeedsWait = (last.toolCalls || []).some((t) => {
              if (String(t.name || '') !== 'tiktok_drama') return false
              try {
                const data = JSON.parse(t.result || '')
                return Boolean(data?.job_id) || (data?.ok === false && data?.error)
              } catch {
                return false
              }
            })
            if (hadDramaTool && (!hasVideo || toolNeedsWait)) {
              last.isStreaming = true
              last.status = '成片生成中，请稍候…进度会实时更新，失败也会直接显示原因'
              statusText.value = last.status
              isLoading.value = true
              const waitResult = await awaitPendingDramaVideos(last, {
                signal: abortController?.signal,
                sessionId: deps.getSessionId?.() || '',
                onStatus: (text) => {
                  statusText.value = text || ''
                  last.status = text || ''
                  nextTick(() => scrollToBottom())
                },
              })
              enrichMessageWithDramaMedia(last)
              if (waitResult && waitResult.ok === false && waitResult.error) {
                last.content = waitResult.error
                last.status = waitResult.error
                statusText.value = waitResult.error
              } else if ((last.media || []).some((m) => m?.url)) {
                last.status = ''
                statusText.value = ''
              }
              nextTick(() => scrollToBottom())
            }
          } catch (e) {
            if (e?.name !== 'AbortError') {
              console.error('await drama video failed:', e)
              const lastErr = lastAssistant()
              if (lastErr) {
                const msg = `❌ 成片等待失败：${e.message || e}`
                lastErr.content = msg
                lastErr.status = msg
                lastErr.dramaJob = {
                  ...(lastErr.dramaJob || {}),
                  state: 'error',
                  line: msg,
                  error: String(e.message || e),
                }
              }
            } else {
              terminal = 'cancelled'
            }
          }
        }
      }
      finishAssistant({ cancelled: terminal === 'cancelled' || Boolean(abortController?.signal?.aborted) })
      isLoading.value = false
      // Keep error statusText briefly visible via message.status / dramaJob panel
      if (lastAssistant()?.dramaJob?.state !== 'error') {
        statusText.value = ''
      }
      activeStreamId.value = null
      pendingApproval.value = null
      approvalBusy.value = false
      abortController = null
      try {
        await deps.onTurnComplete?.()
      } catch (e) {
        console.error('onTurnComplete failed:', e)
      }
    }
  }

  function editMessage(index) {
    const msg = messages.value[index]
    if (!msg || isLoading.value) return
    userInput.value = msg.content
    messages.value.splice(index, 1)
  }

  async function regenerateResponse(index) {
    if (isLoading.value) return
    const userMsg = messages.value
      .slice(0, index)
      .reverse()
      .find((m) => m.role === 'user')
    if (!userMsg) return
    const userContent = userMsg.content
    messages.value = messages.value.slice(0, index)
    userInput.value = userContent
    await nextTick()
    await sendMessage()
  }

  function toggleLike(index) {
    const msg = messages.value[index]
    if (!msg) return
    msg.liked = !msg.liked
    if (msg.liked) msg.disliked = false
  }

  function toggleDislike(index) {
    const msg = messages.value[index]
    if (!msg) return
    msg.disliked = !msg.disliked
    if (msg.disliked) msg.liked = false
  }

  async function resumeAfterMessagesLoad(sessionId) {
    // 历史任务：若会话未写回终态但队列已结束，静默补一次终态（不进入长时间轮询）
    const list = messages.value || []
    const sid = sessionId || deps.getSessionId?.() || ''
    try {
      const { hydrateDramaTerminalFromQueue } = await import('@/utils/dramaChatMedia')
      await hydrateDramaTerminalFromQueue(list, { sessionId: sid })
    } catch {
      /* ignore */
    }
    stashSessionMessages(sid, list)
    return false
  }

  async function refreshDramaJob(index) {
    const list = messages.value || []
    const msg = list[index]
    if (!msg || msg.role !== 'assistant') return false
    const job = msg.dramaJob
    if (!job?.jobId || job.refreshing || job.resuming) return false

    abortController = new AbortController()
    isLoading.value = true
    msg.dramaJob = {
      ...job,
      refreshing: true,
      state: job.state === 'error' ? 'error' : 'running',
      line: '正在查询任务进度…',
    }
    msg.isStreaming = true
    msg.status = '正在查询任务进度…'
    for (const tool of msg.toolCalls || []) {
      if (String(tool.name || '') !== 'tiktok_drama') continue
      if (tool.status === 'error') continue
      try {
        const data = JSON.parse(tool.result || '')
        if (data?.job_id && !data?.play_url) tool.status = 'running'
      } catch {
        /* */
      }
    }

    try {
      const had = await awaitPendingDramaVideos(msg, {
        signal: abortController.signal,
        sessionId: deps.getSessionId?.() || '',
        forcePoll: true,
        onStatus: (text) => {
          msg.status = text || msg.status || ''
          statusText.value = text || ''
        },
      })
      if (msg.dramaJob) {
        msg.dramaJob.refreshing = false
        msg.dramaJob.canRefresh =
          msg.dramaJob.state === 'error' ||
          msg.dramaJob.state === 'idle' ||
          (msg.dramaJob.state !== 'done' && !msg.media?.length)
        msg.dramaJob.canResume =
          msg.dramaJob.state === 'error' ||
          msg.dramaJob.state === 'idle' ||
          (msg.dramaJob.state !== 'done' && !msg.media?.length)
      }
      if (!msg.dramaJob || (msg.dramaJob.state !== 'running' && msg.dramaJob.state !== 'pending')) {
        msg.isStreaming = false
      }
      stashCurrent(deps.getSessionId?.() || '')
      scrollToBottom()
      return had
    } catch (e) {
      if (e?.name === 'AbortError') {
        if (msg.dramaJob) {
          msg.dramaJob.refreshing = false
          msg.dramaJob.state = 'idle'
          msg.dramaJob.line = '已停止'
          msg.dramaJob.canRefresh = true
          msg.dramaJob.canResume = true
        }
        msg.isStreaming = false
        msg.status = '已停止'
        return false
      }
      if (msg.dramaJob) {
        msg.dramaJob.refreshing = false
        msg.dramaJob.state = 'error'
        msg.dramaJob.line = e?.message || '查询失败'
        msg.dramaJob.canRefresh = true
        msg.dramaJob.canResume = true
      }
      msg.isStreaming = false
      throw e
    } finally {
      abortController = null
      isLoading.value = false
    }
  }

  async function resumeDramaJob(payload) {
    const index = typeof payload === 'number' ? payload : Number(payload?.index)
    const preferJobId = typeof payload === 'object' && payload ? String(payload.jobId || '') : ''
    const preferSlug = typeof payload === 'object' && payload ? String(payload.slug || '') : ''
    const preferEpisode =
      typeof payload === 'object' && payload ? Number(payload.episode || 0) || 0 : 0
    const preferKind = typeof payload === 'object' && payload ? String(payload.kind || '') : ''

    const list = messages.value || []
    const msg = list[index]
    if (!msg || msg.role !== 'assistant') return false
    const job = msg.dramaJob || {}
    const jobFromList = (msg.dramaJobs || []).find(
      (j) => preferJobId && String(j.jobId || '') === preferJobId,
    )
    const anchor = jobFromList || job
    if (anchor.resuming || job.resuming || anchor.refreshing || job.refreshing) return false

    let kind = preferKind || anchor.kind || job.kind || ''
    let slug = preferSlug || anchor.slug || job.slug || ''
    let episode = preferEpisode || Number(anchor.episode || job.episode || 0) || 0
    let oldJobId = preferJobId || anchor.jobId || job.jobId || ''
    let toolHit = null

    // Prefer the tool that matches the failed/selected job_id; never blindly take the first slug tool
    // (that may be an old done produce with play_url and causes「秒结束」).
    const tools = msg.toolCalls || []
    const pickFromTool = (tool) => {
      try {
        const data = JSON.parse(tool.result || '')
        if (!data?.job_id && !data?.slug) return false
        oldJobId = String(data.job_id || oldJobId || '')
        slug = String(data.slug || slug || '')
        episode = Number(data.episode || episode || 0) || episode
        kind = String(data.kind || data.action || kind || 'produce_episode')
        if (kind === 'create_from_premise') kind = 'produce_episode'
        if (kind === 'resume_produce') kind = 'produce_episode'
        toolHit = tool
        return true
      } catch {
        return false
      }
    }
    if (oldJobId) {
      for (const tool of tools) {
        if (String(tool.name || '') !== 'tiktok_drama') continue
        try {
          const data = JSON.parse(tool.result || '')
          if (String(data?.job_id || '') === oldJobId && pickFromTool(tool)) break
        } catch {
          /* */
        }
      }
    }
    if (!toolHit) {
      // Fall back: last failed / unfinished produce-like tool
      for (let i = tools.length - 1; i >= 0; i -= 1) {
        const tool = tools[i]
        if (String(tool.name || '') !== 'tiktok_drama') continue
        try {
          const data = JSON.parse(tool.result || '')
          const action = String(data?.action || data?.kind || '')
          const isProduceLike = [
            'produce_episode',
            'create_from_premise',
            'resume_produce',
            'render_episode',
            'export',
          ].includes(action)
          if (!isProduceLike && !data?.job_id) continue
          if (data?.ok === false || data?.error || data?.status === 'error' || !data?.play_url) {
            if (pickFromTool(tool)) break
          }
        } catch {
          /* */
        }
      }
    }
    if (!toolHit) {
      for (let i = tools.length - 1; i >= 0; i -= 1) {
        const tool = tools[i]
        if (String(tool.name || '') !== 'tiktok_drama') continue
        if (pickFromTool(tool)) break
      }
    }
    if (!slug && !oldJobId) return false

    abortController = new AbortController()
    const signal = abortController.signal
    isLoading.value = true
    msg.dramaJob = {
      ...anchor,
      ...job,
      resuming: true,
      refreshing: false,
      state: 'running',
      line: '正在提交续跑任务…',
      canRefresh: false,
      canResume: false,
      slug,
      episode: episode || 1,
      kind: kind || 'produce_episode',
      jobId: oldJobId || anchor.jobId || job.jobId,
    }
    msg.isStreaming = true
    msg.status = '正在继续渲染…'
    statusText.value = '正在继续渲染…'

    try {
      if (signal.aborted) throw new DOMException('Aborted', 'AbortError')
      let next
      try {
        next = await dramaApi.resumeJob({
          job_id: oldJobId,
          kind: kind || 'produce_episode',
          slug,
          episode: episode || 1,
        })
      } catch (e) {
        if (e?.name === 'AbortError' || signal.aborted) throw e
        // 旧 job 丢失时直接按项目集新建 produce
        if (!slug) throw e
        next = await dramaApi.createJob(slug, episode || 1, {
          kind: kind || 'produce_episode',
        })
      }
      if (signal.aborted) throw new DOMException('Aborted', 'AbortError')
      const newId = String(next?.job_id || '')
      if (!newId) throw new Error('续跑未返回 job_id')

      const payload = {
        ok: true,
        action: 'produce_episode',
        kind: next?.kind || kind || 'produce_episode',
        job_id: newId,
        slug: next?.slug || slug,
        episode: next?.episode || episode || 1,
        status: next?.status || 'pending',
      }
      if (toolHit) {
        toolHit.result = JSON.stringify(payload)
        toolHit.status = 'running'
      } else {
        msg.toolCalls = [
          ...(msg.toolCalls || []),
          {
            id: `resume-${newId}`,
            name: 'tiktok_drama',
            arguments: '',
            result: JSON.stringify(payload),
            status: 'running',
          },
        ]
      }
      msg.dramaJob = {
        state: 'running',
        jobId: newId,
        slug: payload.slug,
        episode: payload.episode,
        kind: payload.kind,
        line: `续跑已启动（${newId.slice(0, 8)}…），等待后台完成…`,
        resuming: false,
        canRefresh: false,
        canResume: false,
      }
      // 只保留当前续跑任务条，去掉同气泡里的旧失败条
      msg.dramaJobs = [msg.dramaJob]
      msg.content = ''
      msg.status = msg.dramaJob.line
      statusText.value = msg.dramaJob.line

      await awaitPendingDramaVideos(msg, {
        signal,
        sessionId: deps.getSessionId?.() || '',
        forcePoll: true,
        onlyJobId: newId,
        onStatus: (text) => {
          msg.status = text || msg.status || ''
          statusText.value = text || ''
        },
      })
      if (msg.dramaJob) {
        msg.dramaJob.resuming = false
        msg.dramaJob.canRefresh =
          msg.dramaJob.state === 'error' ||
          msg.dramaJob.state === 'idle' ||
          (msg.dramaJob.state !== 'done' && !msg.media?.length)
        msg.dramaJob.canResume = msg.dramaJob.canRefresh
      }
      if (!msg.dramaJob || (msg.dramaJob.state !== 'running' && msg.dramaJob.state !== 'pending')) {
        msg.isStreaming = false
      }
      stashCurrent(deps.getSessionId?.() || '')
      scrollToBottom()
      return true
    } catch (e) {
      if (e?.name === 'AbortError' || signal.aborted) {
        if (msg.dramaJob) {
          msg.dramaJob.resuming = false
          msg.dramaJob.state = 'idle'
          msg.dramaJob.line = '已停止'
          msg.dramaJob.canRefresh = true
          msg.dramaJob.canResume = true
        }
        msg.isStreaming = false
        msg.status = '已停止'
        statusText.value = ''
        return false
      }
      if (msg.dramaJob) {
        msg.dramaJob.resuming = false
        msg.dramaJob.state = 'error'
        msg.dramaJob.line = e?.message || '续跑失败'
        msg.dramaJob.canRefresh = true
        msg.dramaJob.canResume = true
      }
      msg.isStreaming = false
      throw e
    } finally {
      abortController = null
      isLoading.value = false
      if (msg.dramaJob?.state === 'running' || msg.dramaJob?.state === 'pending') {
        // 仍在跑：保持气泡 streaming，由进度条展示；全局 loading 可放下
        msg.isStreaming = true
      }
    }
  }

  function stashCurrent(sessionId) {
    stashSessionMessages(sessionId || deps.getSessionId?.() || '', messages.value || [])
  }

  return {
    messages,
    userInput,
    isLoading,
    statusText,
    activeStreamId,
    pendingApproval,
    approvalBusy,
    resetConversation,
    setMessages,
    sendMessage,
    stopGeneration,
    decideApproval,
    uploadFile,
    editMessage,
    regenerateResponse,
    toggleLike,
    toggleDislike,
    stashCurrent,
    resumeAfterMessagesLoad,
    refreshDramaJob,
    resumeDramaJob,
  }
}
