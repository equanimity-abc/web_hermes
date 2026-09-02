import { nextTick, ref } from 'vue'
import {
  cancelChat,
  respondApproval,
  SessionBusyError,
  streamChat,
  uploadWorkspaceFile,
} from '@/api/chat'
import { attachDramaMedia, awaitPendingDramaVideos, enrichMessageWithDramaMedia, extractDramaVideoFromToolResult } from '@/utils/dramaChatMedia'

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
    last.status = ''
    if (opts.cancelled && !last.content) {
      last.content = '（已停止生成）'
      last.cancelled = true
    } else if (opts.cancelled) {
      last.cancelled = true
    }
    if (last.toolCalls) {
      last.toolCalls.forEach((t) => {
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

  async function stopGeneration() {
    const sid = activeStreamId.value
    pendingApproval.value = null
    // 1) 立即中断本地 SSE 读取，让界面先「停」下来，不等后端。
    abortController?.abort()
    // 2) 尽力通知后端停止；加超时保护，避免因后端忙而再次卡住。
    if (sid) {
      const cancelAbort = new AbortController()
      const timer = setTimeout(() => cancelAbort.abort(), 3000)
      try {
        await cancelChat(sid, cancelAbort.signal)
      } catch (e) {
        console.error('cancel failed:', e)
      } finally {
        clearTimeout(timer)
      }
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
                else {
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
      // 成片未就绪时继续等待，不要提前结束 loading
      if (terminal !== 'cancelled') {
        const last = lastAssistant()
        if (last) {
          try {
            enrichMessageWithDramaMedia(last)
            const hasVideo = (last.media || []).some((m) => m?.url)
            const hadDramaTool = (last.toolCalls || []).some(
              (t) => String(t.name || '') === 'tiktok_drama',
            )
            if (hadDramaTool && !hasVideo) {
              last.status = '成片生成中，请稍候…完成后会自动出现在对话里'
              statusText.value = last.status
              await awaitPendingDramaVideos(last, {
                signal: abortController?.signal,
                onStatus: (text) => {
                  statusText.value = text || ''
                  last.status = text || ''
                  nextTick(() => scrollToBottom())
                },
              })
            }
            enrichMessageWithDramaMedia(last)
            if ((last.media || []).some((m) => m?.url)) {
              last.status = ''
              nextTick(() => scrollToBottom())
            }
          } catch (e) {
            if (e?.name !== 'AbortError') {
              console.error('await drama video failed:', e)
            }
          }
        }
      }
      finishAssistant({ cancelled: terminal === 'cancelled' })
      isLoading.value = false
      statusText.value = ''
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
  }
}
