import { computed, ref } from 'vue'
import * as sessionsApi from '@/api/sessions'
import { foldMessagesForUi } from '@/utils/foldMessages'

/**
 * Session list + current session id.
 */
const LAST_SESSION_KEY = 'web_hermes_last_session_id'

export function useSessions() {
  const currentSessionId = ref(null)
  const sessionList = ref([])

  const currentSessionTitle = computed(() => {
    if (!currentSessionId.value) return '新对话'
    const s = sessionList.value.find((item) => item.id === currentSessionId.value)
    return s?.title || '新对话'
  })

  function readRememberedSessionId() {
    try {
      return localStorage.getItem(LAST_SESSION_KEY)
    } catch {
      return null
    }
  }

  function rememberSessionId(id) {
    try {
      if (id == null || id === '') {
        localStorage.setItem(LAST_SESSION_KEY, '__new__')
      } else {
        localStorage.setItem(LAST_SESSION_KEY, String(id))
      }
    } catch {
      /* private mode */
    }
  }

  async function refreshSessionList({ retries = 3 } = {}) {
    let lastErr = null
    for (let i = 0; i < retries; i++) {
      try {
        sessionList.value = await sessionsApi.listSessions()
        return sessionList.value
      } catch (e) {
        lastErr = e
        if (i < retries - 1) {
          await new Promise((r) => setTimeout(r, 250 * (i + 1)))
        }
      }
    }
    console.error('刷新会话列表失败:', lastErr)
    return sessionList.value
  }

  async function loadSessionMessages(sessionId) {
    const data = await sessionsApi.fetchSession(sessionId)
    return foldMessagesForUi(data.messages || [])
  }

  async function removeSession(sessionId) {
    await sessionsApi.deleteSession(sessionId)
    sessionList.value = sessionList.value.filter((s) => s.id !== sessionId)
    if (readRememberedSessionId() === String(sessionId)) {
      rememberSessionId(null)
    }
    await refreshSessionList()
  }

  function clearCurrentSession() {
    currentSessionId.value = null
    rememberSessionId(null)
  }

  function setCurrentSessionId(id) {
    currentSessionId.value = id
    if (id) rememberSessionId(id)
  }

  /** 启动时优先恢复：上次会话 > 最近一条；显式「新对话」则保持空白。 */
  function pickSessionToRestore() {
    const remembered = readRememberedSessionId()
    if (remembered === '__new__') return null
    const sessions = sessionList.value || []
    if (remembered && sessions.some((s) => s.id === remembered)) return remembered
    if (!remembered && sessions[0]?.id) return sessions[0].id
    return null
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
    rememberSessionId,
    pickSessionToRestore,
  }
}
