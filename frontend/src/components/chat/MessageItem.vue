<script setup>
import { computed } from 'vue'
import { renderMarkdown } from '@/utils/markdown'
import ToolCard from './ToolCard.vue'
import DramaVideoCard from './DramaVideoCard.vue'
import DramaProgressStatusBar from '@/components/drama/DramaProgressStatusBar.vue'

const props = defineProps({
  message: { type: Object, required: true },
  index: { type: Number, required: true },
})

const emit = defineEmits(['copy', 'edit', 'regenerate', 'like', 'dislike', 'open-drama', 'refresh-drama', 'resume-drama'])

const htmlContent = computed(() => {
  const html = renderMarkdown(props.message.content)
  if (props.message.isStreaming) {
    return html + '<span class="typing-cursor">▊</span>'
  }
  return html
})

const toolCalls = computed(() => props.message.toolCalls || [])
const mediaItems = computed(() => props.message.media || [])
const dramaJob = computed(() => props.message.dramaJob || null)
const dramaJobList = computed(() => {
  const list = props.message.dramaJobs
  const rows = Array.isArray(list) && list.length ? list : dramaJob.value ? [dramaJob.value] : []
  const hasActive = rows.some((j) => j?.state === 'running' || j?.state === 'pending')
  // 续跑进行中时只展示进行中的条，不叠旧失败条
  if (hasActive) {
    return rows.filter((j) => j?.state === 'running' || j?.state === 'pending')
  }
  return rows
})
const showDramaProgress = computed(() => dramaJobList.value.some((j) => shouldShowJob(j)))

function shouldShowJob(j) {
  if (!j) return false
  return (
    j.state === 'running' ||
    j.state === 'pending' ||
    j.state === 'error' ||
    j.state === 'timeout' ||
    j.state === 'idle' ||
    (j.state === 'done' && j.line)
  )
}

function jobPct(j) {
  const p = j?.pct
  if (p == null || Number.isNaN(Number(p))) {
    if (j?.state === 'running' || j?.state === 'pending') return 8
    if (j?.state === 'done') return 100
    return 0
  }
  return Math.max(0, Math.min(100, Number(p)))
}

function jobTitle(j) {
  const ep = j?.episode != null ? `第 ${j.episode} 集` : ''
  const label = j?.label || ep
  const s = j?.state
  let head = '成片进行中'
  if (s === 'error') head = '渲染失败'
  else if (s === 'done') head = '成片完成'
  else if (s === 'idle') head = '历史任务'
  return label ? `${head} · ${label}` : head
}

function jobStatus(j) {
  const s = j?.state
  if (s === 'pending') return 'running'
  if (s === 'idle') return 'idle'
  if (s === 'timeout') return 'running' // 历史态：仍按进行中展示
  return s || 'idle'
}

function jobMessage(j) {
  const line = j?.line || ''
  if (j?.state === 'error' && j.shot != null) {
    return `${line}${line ? ' · ' : ''}问题镜头：第 ${j.shot} 镜`
  }
  return line || '就绪'
}

function canRefreshJob(j) {
  if (!j?.jobId) return false
  if (j.refreshing || j.resuming) return false
  return j.canRefresh || j.state === 'idle' || j.state === 'error'
}

function canResumeJob(j) {
  if (!j) return false
  if (j.refreshing || j.resuming) return false
  if (j.state === 'running' || j.state === 'pending') return false
  if (j.state === 'done' && j.mediaReady) return false
  return j.canResume || j.state === 'error' || j.state === 'timeout' || j.state === 'idle'
}

const showStatus = computed(
  () =>
    Boolean(
      (props.message.isStreaming && props.message.status) ||
        (dramaJob.value &&
          (dramaJob.value.state === 'running' || dramaJob.value.state === 'pending') &&
          props.message.status),
    ),
)
const showMarkdown = computed(() => {
  if (props.message.content) return true
  return Boolean(props.message.isStreaming && !showStatus.value)
})
</script>

<template>
  <div class="message-wrapper" :class="message.role">
    <div class="message-inner">
      <div class="message-avatar">
        <div v-if="message.role === 'user'" class="avatar-user">👤</div>
        <svg
          v-else
          class="avatar-ai"
          viewBox="0 0 24 24"
          fill="none"
          xmlns="http://www.w3.org/2000/svg"
        >
          <rect width="24" height="24" rx="6" fill="#4f46e5" />
          <path d="M7 8h10M7 12h10M7 16h7" stroke="#fff" stroke-width="2" stroke-linecap="round" />
        </svg>
      </div>

      <div class="message-body">
        <div v-if="message.role === 'user'" class="user-bubble-wrapper">
          <div class="user-bubble">{{ message.content }}</div>
          <div class="bubble-actions">
            <button type="button" class="bubble-action-btn" title="复制" @click="emit('copy', message.content)">
              <svg width="14" height="14" viewBox="0 0 14 14" fill="none">
                <rect x="3" y="3" width="8" height="8" rx="1" stroke="currentColor" stroke-width="1.2" />
                <path d="M5 1h7a1 1 0 011 1v7" stroke="currentColor" stroke-width="1.2" stroke-linecap="round" />
              </svg>
            </button>
            <button type="button" class="bubble-action-btn" title="编辑" @click="emit('edit', index)">
              <svg width="14" height="14" viewBox="0 0 14 14" fill="none">
                <path
                  d="M10 2l2 2L5 11H3V9l7-7z"
                  stroke="currentColor"
                  stroke-width="1.2"
                  stroke-linejoin="round"
                />
              </svg>
            </button>
          </div>
        </div>

        <template v-else>
          <div v-if="toolCalls.length" class="tool-cards">
            <ToolCard v-for="(tool, i) in toolCalls" :key="tool.id || i" :tool="tool" />
          </div>

          <div v-if="showDramaProgress" class="drama-chat-jobs">
            <div
              v-for="(job, ji) in dramaJobList.filter(shouldShowJob)"
              :key="job.jobId || ji"
              class="drama-chat-job-row"
            >
              <DramaProgressStatusBar
                class="drama-chat-job-bar-wrap"
                :pct="jobPct(job)"
                :status="jobStatus(job)"
                :title="jobTitle(job)"
                :message="jobMessage(job)"
              />
              <button
                v-if="canResumeJob(job)"
                type="button"
                class="drama-refresh-btn drama-resume-btn"
                :disabled="!!job.resuming || !!job.refreshing"
                  @click="emit('resume-drama', { index, jobId: job.jobId, slug: job.slug, episode: job.episode, kind: job.kind })"
              >
                {{ job.resuming ? '续跑中…' : '继续渲染' }}
              </button>
              <button
                v-if="canRefreshJob(job)"
                type="button"
                class="drama-refresh-btn"
                :disabled="!!job.refreshing || !!job.resuming"
                @click="emit('refresh-drama', index)"
              >
                {{ job.refreshing ? '查询中…' : '查询进度' }}
              </button>
            </div>
          </div>

          <div v-if="mediaItems.length" class="chat-media-cards">
            <DramaVideoCard
              v-for="(item, i) in mediaItems"
              :key="item.url || i"
              :item="item"
              @open-drama="emit('open-drama', $event)"
            />
          </div>

          <div v-if="showStatus" class="stream-status">
            {{ message.status }}
            <span class="typing-cursor">▊</span>
          </div>

          <div
            v-if="message.content && (!message.isStreaming || dramaJob?.state === 'error')"
            class="markdown-body"
            :class="message.isStreaming ? 'streaming-text' : 'ai-text'"
            v-html="htmlContent"
          />
          <div
            v-else-if="showMarkdown && !showStatus"
            class="markdown-body"
            :class="message.isStreaming ? 'streaming-text' : 'ai-text'"
            v-html="htmlContent"
          />

          <div v-if="!message.isStreaming && message.content" class="ai-actions">
            <button type="button" class="ai-action-btn" title="复制" @click="emit('copy', message.content)">
              <svg width="15" height="15" viewBox="0 0 15 15" fill="none">
                <rect x="3.5" y="3.5" width="8" height="8" rx="1" stroke="currentColor" stroke-width="1.2" />
                <path d="M5.5 1.5h7a1 1 0 011 1v7" stroke="currentColor" stroke-width="1.2" stroke-linecap="round" />
              </svg>
            </button>
            <button type="button" class="ai-action-btn" title="重新生成" @click="emit('regenerate', index)">
              <svg width="15" height="15" viewBox="0 0 15 15" fill="none">
                <path d="M2.5 7.5a5 5 0 019.5-2" stroke="currentColor" stroke-width="1.2" stroke-linecap="round" />
                <path d="M12.5 7.5a5 5 0 01-9.5 2" stroke="currentColor" stroke-width="1.2" stroke-linecap="round" />
                <path
                  d="M10 3l2-1.5L13.5 5"
                  stroke="currentColor"
                  stroke-width="1.2"
                  stroke-linecap="round"
                  stroke-linejoin="round"
                />
              </svg>
            </button>
            <button
              type="button"
              class="ai-action-btn"
              :class="{ active: message.liked }"
              title="喜欢"
              @click="emit('like', index)"
            >
              <svg width="15" height="15" viewBox="0 0 15 15" fill="none">
                <path
                  d="M7.5 12l-4.2-4.2c-.8-.8-.8-2 0-2.8.8-.8 2-.8 2.8 0l1.4 1.4 1.4-1.4c.8-.8 2-.8 2.8 0 .8.8.8 2 0 2.8L7.5 12z"
                  stroke="currentColor"
                  stroke-width="1.2"
                  stroke-linejoin="round"
                />
              </svg>
            </button>
            <button
              type="button"
              class="ai-action-btn"
              :class="{ active: message.disliked }"
              title="不喜欢"
              @click="emit('dislike', index)"
            >
              <svg width="15" height="15" viewBox="0 0 15 15" fill="none">
                <path
                  d="M7.5 3l4.2 4.2c.8.8.8 2 0 2.8-.8.8-2 .8-2.8 0L7.5 8.6 6.1 10c-.8.8-2 .8-2.8 0-.8-.8-.8-2 0-2.8L7.5 3z"
                  stroke="currentColor"
                  stroke-width="1.2"
                  stroke-linejoin="round"
                />
              </svg>
            </button>
            <button type="button" class="ai-action-btn" title="分享" @click="emit('copy', message.content)">
              <svg width="15" height="15" viewBox="0 0 15 15" fill="none">
                <circle cx="3" cy="7.5" r="2" stroke="currentColor" stroke-width="1.2" />
                <circle cx="12" cy="3" r="2" stroke="currentColor" stroke-width="1.2" />
                <circle cx="12" cy="12" r="2" stroke="currentColor" stroke-width="1.2" />
                <path d="M4.8 6.5l5.6-2.8M4.8 8.5l5.6 2.8" stroke="currentColor" stroke-width="1.2" />
              </svg>
            </button>
          </div>
        </template>
      </div>
    </div>
  </div>
</template>

<style scoped>
.drama-chat-jobs {
  display: flex;
  flex-direction: column;
  gap: 8px;
  margin: 0 0 10px;
  max-width: 640px;
}

.drama-chat-job-row {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-wrap: wrap;
}

.drama-chat-job-bar-wrap {
  margin: 0;
  flex: 1;
  min-width: 240px;
  max-width: 520px;
}

.drama-refresh-btn {
  flex-shrink: 0;
  height: 32px;
  padding: 0 12px;
  border-radius: 8px;
  border: 1px solid #c7d2fe;
  background: #eef2ff;
  color: #4338ca;
  font-size: 12px;
  cursor: pointer;
}

.drama-refresh-btn:hover:not(:disabled) {
  background: #e0e7ff;
}

.drama-refresh-btn:disabled {
  opacity: 0.65;
  cursor: default;
}

.drama-resume-btn {
  border-color: #86efac;
  background: #ecfdf5;
  color: #047857;
}

.drama-resume-btn:hover:not(:disabled) {
  background: #d1fae5;
}
</style>
