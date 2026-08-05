import { nextTick, ref } from 'vue'
import { cancelChat, SessionBusyError, streamChat } from '@/api/chat'

/**
 * Conversation messages + streaming send loop (P4: start/reconnect/cancel).
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
        if (t.status === 'running') t.status = opts.cancelled ? 'cancelled' : 'done'
      })
    }
  }

  function resetConversation() {
    messages.value = []
    userInput.value = ''
    statusText.value = ''
    activeStreamId.value = null
  }

  function setMessages(list) {
    messages.value = list
  }

  async function stopGeneration() {
    const sid = activeStreamId.value
    if (!sid) {
      abortController?.abort()
      return
    }
    try {
      await cancelChat(sid)
    } catch (e) {
      console.error('cancel failed:', e)
    }
    abortController?.abort()
  }

  async function sendMessage() {
    const content = userInput.value.trim()
    if (!content || isLoading.value) return

    messages.value.push({ role: 'user', content, isStreaming: false })
    userInput.value = ''
    isLoading.value = true
    statusText.value = ''
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
            nextTick(() => scrollToBottom())
          },
          onToolResult(evt) {
            const last = lastAssistant()
            if (!last?.toolCalls) return
            const hit =
              last.toolCalls.find((t) => t.id && t.id === evt.tool_call_id) ||
              last.toolCalls.find((t) => t.name === evt.name && t.status === 'running')
            if (!hit) return
            hit.result = evt.content || ''
            hit.status = 'done'
            try {
              const parsed = JSON.parse(hit.result)
              if (parsed && parsed.error) hit.status = 'error'
            } catch {
              /* ignore */
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
        // Remove the optimistic user+assistant pair's empty assistant if busy
        // Keep user message visible with error on assistant.
        terminal = 'error'
      } else {
        const last = lastAssistant()
        if (last) {
          last.content = `❌ 错误: ${e.message}`
        }
        terminal = 'error'
      }
    } finally {
      finishAssistant({ cancelled: terminal === 'cancelled' })
      isLoading.value = false
      statusText.value = ''
      activeStreamId.value = null
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
    resetConversation,
    setMessages,
    sendMessage,
    stopGeneration,
    editMessage,
    regenerateResponse,
    toggleLike,
    toggleDislike,
  }
}
