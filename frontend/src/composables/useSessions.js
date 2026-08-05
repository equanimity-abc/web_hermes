import { computed, ref } from 'vue'
import * as sessionsApi from '@/api/sessions'
import { foldMessagesForUi } from '@/utils/foldMessages'

/**
 * Session list + current session id.
 */
export function useSessions() {
  const currentSessionId = ref(null)
  const sessionList = ref([])

  const currentSessionTitle = computed(() => {
    if (!currentSessionId.value) return '新对话'
    const s = sessionList.value.find((item) => item.id === currentSessionId.value)
    return s?.title || '新对话'
  })

  async function refreshSessionList() {
    try {
      sessionList.value = await sessionsApi.listSessions()
    } catch (e) {
      console.error('刷新会话列表失败:', e)
    }
  }

  async function loadSessionMessages(sessionId) {
    const data = await sessionsApi.fetchSession(sessionId)
    return foldMessagesForUi(data.messages || [])
  }

  async function removeSession(sessionId) {
    await sessionsApi.deleteSession(sessionId)
    sessionList.value = sessionList.value.filter((s) => s.id !== sessionId)
    await refreshSessionList()
  }

  function clearCurrentSession() {
    currentSessionId.value = null
  }

  function setCurrentSessionId(id) {
    currentSessionId.value = id
  }

  return {
    currentSessionId,
    sessionList,
    currentSessionTitle,
    refreshSessionList,
    loadSessionMessages,
    removeSession,
    clearCurrentSession,
    setCurrentSessionId,
  }
}
