<script setup>
import { computed } from 'vue'

const props = defineProps({
  jobs: { type: Array, default: () => [] },
})

const emit = defineEmits(['cancel', 'retry'])

const visible = computed(() => (props.jobs || []).length > 0)

function label(job) {
  const kind = job.kind || 'job'
  const ep = job.episode ? `EP${String(job.episode).padStart(2, '0')}` : ''
  return `${job.slug || ''} ${ep} · ${kind}`.trim()
}

function progressText(job) {
  const p = job.progress || {}
  if (p.message) return p.message
  if (p.total) return `${p.current || 0}/${p.total}`
  return job.status || ''
}

function statusClass(job) {
  if (job.status === 'error') return 'is-err'
  if (job.status === 'done') return 'is-ok'
  if (job.status === 'cancelled') return 'is-muted'
  return 'is-run'
}
</script>

<template>
  <aside v-if="visible" class="drama-job-bar">
    <header class="drama-job-bar-head">
      <strong>渲染任务</strong>
      <span>{{ jobs.length }} 条</span>
    </header>
    <ul class="drama-job-list">
      <li v-for="job in jobs" :key="job.job_id" class="drama-job-item" :class="statusClass(job)">
        <div class="drama-job-main">
          <span class="drama-job-title">{{ label(job) }}</span>
          <span class="drama-job-progress">{{ progressText(job) }}</span>
          <span v-if="job.error" class="drama-job-error">{{ job.error }}</span>
        </div>
        <div class="drama-job-actions">
          <button
            v-if="job.status === 'pending' || job.status === 'running'"
            type="button"
            class="btn-tiny"
            @click="emit('cancel', job.job_id)"
          >
            取消
          </button>
          <button
            v-if="job.status === 'error'"
            type="button"
            class="btn-tiny"
            @click="emit('retry', job.job_id)"
          >
            重试
          </button>
        </div>
      </li>
    </ul>
  </aside>
</template>
