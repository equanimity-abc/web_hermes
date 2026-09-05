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

  async function waitForJob(job, slug, { timeoutMs = 15 * 60 * 1000 } = {}) {
    if (!job?.job_id) return job
    await trackJob(job, slug)
    if (TERMINAL.has(job.status)) return job
    const started = Date.now()
    while (Date.now() - started < timeoutMs) {
      await new Promise((r) => setTimeout(r, 1200))
      let latest = (jobs.value || []).find((j) => j.job_id === job.job_id)
      if (!latest || !TERMINAL.has(latest.status)) {
        try {
          latest = await dramaApi.getJob(job.job_id)
          upsertJob(latest)
        } catch (err) {
          const status = Number(err?.status || 0)
          if (status === 404 || /404|not found|找不到/i.test(String(err?.message || ''))) {
            const gone = {
              ...(latest || job),
              job_id: job.job_id,
              status: 'error',
              error: `后台任务已失效（${job.job_id}），可能因服务重启丢失`,
            }
            upsertJob(gone)
            return gone
          }
          /* keep polling on transient errors */
        }
      }
      if (latest && TERMINAL.has(latest.status)) {
        if (slug) startPolling(slug)
        return latest
      }
    }
    throw new Error(`任务超时：${job.job_id}`)
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
    waitForJob,
    cancelJob,
    retryJob,
    stopPolling,
  }
}
