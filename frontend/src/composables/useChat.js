import { nextTick, ref } from 'vue'
import { streamChat } from '@/api/chat'

/**
 * Conversation messages + streaming send loop.
 *
 * @param {{
 *   getSessionId: () => string|null,
 *   setSessionId: (id: string) => void,
 *   scrollToBottom?: () => void,
 * }} deps
 */
export function useChat(deps) {
  const messages = ref([])
  const userInput = ref('')
  const isLoading = ref(false)

  function scrollToBottom() {
    deps.scrollToBottom?.()
  }

  function resetConversation() {
    messages.value = []
    userInput.value = ''
  }

  function setMessages(list) {
    messages.value = list
  }

  async function sendMessage() {
    const content = userInput.value.trim()
    if (!content || isLoading.value) return

    messages.value.push({ role: 'user', content, isStreaming: false })
    userInput.value = ''
    isLoading.value = true
    messages.value.push({ role: 'assistant', content: '', isStreaming: true })
    await nextTick()
    scrollToBottom()

    try {
      await streamChat(
        { sessionId: deps.getSessionId(), message: content },
        {
          onSessionId(id) {
            if (!deps.getSessionId()) {
              deps.setSessionId(id)
            }
          },
          onToken(text) {
            const last = messages.value[messages.value.length - 1]
            if (last?.role === 'assistant') {
              last.content += text
              nextTick(() => scrollToBottom())
            }
          },
        },
      )
      const last = messages.value[messages.value.length - 1]
      if (last?.role === 'assistant') last.isStreaming = false
    } catch (e) {
      const last = messages.value[messages.value.length - 1]
      if (last?.role === 'assistant') {
        last.content = `❌ 错误: ${e.message}`
        last.isStreaming = false
      }
    } finally {
      isLoading.value = false
    }
  }

  function editMessage(index) {
    const msg = messages.value[index]
    if (!msg) return
    userInput.value = msg.content
    messages.value.splice(index, 1)
  }

  async function regenerateResponse(index) {
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
    resetConversation,
    setMessages,
    sendMessage,
    editMessage,
    regenerateResponse,
    toggleLike,
    toggleDislike,
  }
}
