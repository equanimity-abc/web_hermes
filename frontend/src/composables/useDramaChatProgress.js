/**
 * Cross-view / cross-session drama produce progress.
 * Survives chat↔drama switches and session switches; backed by sessionStorage.
 */
import { computed, reactive } from 'vue'

const STORAGE_KEY = 'drama-chat-progress-v1'
const activePolls = new Set()

const store = reactive({
  /** @type {Record<string, object>} */
  jobs: {},
})

function persist() {
  try {
    if (typeof sessionStorage === 'undefined') return
    sessionStorage.setItem(STORAGE_KEY, JSON.stringify(store.jobs))
  } catch {
    /* private mode / quota */
  }
}

export function hydrateDramaChatProgress() {
  try {
    if (typeof sessionStorage === 'undefined') return
    const raw = sessionStorage.getItem(STORAGE_KEY)
    if (!raw) return
    const parsed = JSON.parse(raw)
    if (!parsed || typeof parsed !== 'object') return
    for (const [id, row] of Object.entries(parsed)) {
      if (!id || !row || typeof row !== 'object') continue
      store.jobs[id] = row
    }
  } catch {
    /* ignore */
  }
}

hydrateDramaChatProgress()

export function isDramaJobPolling(jobId) {
  return activePolls.has(String(jobId || ''))
}

export function markDramaJobPolling(jobId, on) {
  const id = String(jobId || '')
  if (!id) return
  if (on) activePolls.add(id)
  else activePolls.delete(id)
}

export function upsertDramaChatJob(jobId, patch = {}) {
  const id = String(jobId || '').trim()
  if (!id) return null
  const prev = store.jobs[id] || { jobId: id }
  const next = {
    ...prev,
    ...patch,
    jobId: id,
    updatedAt: Date.now(),
  }
  store.jobs[id] = next
  persist()
  return next
}

export function getDramaChatJob(jobId) {
  return store.jobs[String(jobId || '')] || null
}

export function clearDramaChatJob(jobId) {
  const id = String(jobId || '')
  if (!id || !store.jobs[id]) return
  delete store.jobs[id]
  persist()
}

export function listDramaChatJobs() {
  return Object.values(store.jobs).sort((a, b) => (b.updatedAt || 0) - (a.updatedAt || 0))
}

export function activeDramaChatJobs() {
  return listDramaChatJobs().filter((j) => j.state === 'running' || j.state === 'pending')
}

const RECENT_ERROR_MS = 5 * 60 * 1000

export function useDramaChatProgress() {
  const activeJobs = computed(() => activeDramaChatJobs())
  const primary = computed(() => {
    if (activeJobs.value[0]) return activeJobs.value[0]
    // Keep a recent error visible so the global banner can show failure across views.
    return (
      listDramaChatJobs().find(
        (j) => j.state === 'error' && Date.now() - (j.updatedAt || 0) < RECENT_ERROR_MS,
      ) || null
    )
  })
  const hasActive = computed(() => activeJobs.value.length > 0)
  return {
    store,
    activeJobs,
    primary,
    hasActive,
    upsertDramaChatJob,
    clearDramaChatJob,
    getDramaChatJob,
    listDramaChatJobs,
  }
}

/** In-memory session → messages so chat↔session switches keep live dramaJob. */
const sessionMessageCache = new Map()

export function stashSessionMessages(sessionId, messages) {
  const key = String(sessionId || '') || '__draft__'
  if (!Array.isArray(messages)) return
  sessionMessageCache.set(key, messages)
}

export function takeSessionMessages(sessionId) {
  const key = String(sessionId || '') || '__draft__'
  return sessionMessageCache.get(key) || null
}

export function peekSessionMessages(sessionId) {
  return takeSessionMessages(sessionId)
}

export function clearSessionMessageCache(sessionId) {
  if (sessionId == null) {
    sessionMessageCache.clear()
    return
  }
  sessionMessageCache.delete(String(sessionId || '') || '__draft__')
}
