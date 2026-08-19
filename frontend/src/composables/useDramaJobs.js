import { computed, onUnmounted, ref } from 'vue'
import * as dramaApi from '@/api/drama'

const TERMINAL = new Set(['done', 'error', 'cancelled'])

export function useDramaJobs({ onTerminal } = {}) {
  const jobs = ref([])
  const polling = ref(false)
  let pollTimer = 0

  const activeJobs = computed(() =>
    (jobs.value || []).filter((j) => j.status === 'pending' || j.status === 'running'),
  )

  function upsertJob(job) {
    if (!job?.job_id) return
    const list = [...(jobs.value || [])]
    const idx = list.findIndex((j) => j.job_id === job.job_id)
    if (idx >= 0) list[idx] = { ...list[idx], ...job }
    else list.unshift(job)
    jobs.value = list
  }

  async function refreshJobs(slug) {
    try {
      const data = await dramaApi.listJobs({ slug, active: false, limit: 30 })
      jobs.value = data.jobs || []
    } catch {
      /* keep last known jobs */
    }
  }

  function startPolling(slug) {
    stopPolling()
    polling.value = true
    const tick = async () => {
      const prev = new Map((jobs.value || []).map((j) => [j.job_id, j.status]))
      await refreshJobs(slug)
      for (const job of jobs.value || []) {
        const before = prev.get(job.job_id)
        if (before && before !== job.status && TERMINAL.has(job.status)) {
          onTerminal?.(job)
        }
      }
      if (activeJobs.value.length) {
        pollTimer = window.setTimeout(tick, 1500)
      } else {
        polling.value = false
      }
    }
    void tick()
  }

  function stopPolling() {
    polling.value = false
    window.clearTimeout(pollTimer)
  }

  async function trackJob(job, slug) {
    upsertJob(job)
    startPolling(slug)
    return job
  }

  async function cancelJob(jobId) {
    const job = await dramaApi.cancelJob(jobId)
    upsertJob(job)
    return job
  }

  async function retryJob(jobId, slug) {
    const job = await dramaApi.retryJob(jobId)
    return trackJob(job, slug)
  }

  onUnmounted(stopPolling)

  return {
    jobs,
    activeJobs,
    polling,
    refreshJobs,
    trackJob,
    cancelJob,
    retryJob,
    stopPolling,
  }
}
