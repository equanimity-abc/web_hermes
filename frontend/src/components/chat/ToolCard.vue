<script setup>
import { computed, ref } from 'vue'

const props = defineProps({
  tool: {
    type: Object,
    required: true,
    // { id, name, arguments, result, status: 'running'|'done'|'error' }
  },
})

const open = ref(false)

const previewArgs = computed(() => {
  const raw = props.tool.arguments || ''
  try {
    return JSON.stringify(JSON.parse(raw), null, 2)
  } catch {
    return String(raw)
  }
})

const previewResult = computed(() => {
  const raw = props.tool.result || ''
  try {
    return JSON.stringify(JSON.parse(raw), null, 2)
  } catch {
    return String(raw)
  }
})

const statusLabel = computed(() => {
  if (props.tool.status === 'running') return '运行中'
  if (props.tool.status === 'awaiting_approval') return '等待审批'
  if (props.tool.status === 'denied') return '已拒绝'
  if (props.tool.status === 'cancelled') return '已取消'
  if (props.tool.status === 'error') return '失败'
  return '完成'
})
</script>

<template>
  <div class="tool-card" :class="tool.status">
    <button type="button" class="tool-card-header" @click="open = !open">
      <span class="tool-card-icon">
        {{
          tool.status === 'awaiting_approval'
            ? '🛡️'
            : tool.status === 'running'
              ? '⏳'
              : '🔧'
        }}
      </span>
      <span class="tool-card-name">{{ tool.name || 'tool' }}</span>
      <span class="tool-card-status">{{ statusLabel }}</span>
      <span class="tool-card-chevron" :class="{ open }">▾</span>
    </button>
    <div v-if="open" class="tool-card-body">
      <div class="tool-card-section">
        <div class="tool-card-label">参数</div>
        <pre class="tool-card-pre">{{ previewArgs }}</pre>
      </div>
      <div v-if="tool.result != null && tool.result !== ''" class="tool-card-section">
        <div class="tool-card-label">结果</div>
        <pre class="tool-card-pre">{{ previewResult }}</pre>
      </div>
    </div>
  </div>
</template>

<style scoped>
.tool-card {
  border: 1px solid #e5e7eb;
  border-radius: 10px;
  background: #fafafa;
  margin: 0 0 10px;
  overflow: hidden;
}

.tool-card.running {
  border-color: #c7d2fe;
  background: #f5f3ff;
}

.tool-card.awaiting_approval {
  border-color: #fcd34d;
  background: #fffbeb;
}

.tool-card.denied,
.tool-card.cancelled {
  border-color: #e5e7eb;
  background: #f9fafb;
  opacity: 0.9;
}

.tool-card.error {
  border-color: #fecaca;
  background: #fef2f2;
}

.tool-card-header {
  width: 100%;
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 8px 12px;
  border: none;
  background: transparent;
  cursor: pointer;
  font-family: inherit;
  font-size: 13px;
  color: #374151;
  text-align: left;
}

.tool-card-header:hover {
  background: rgba(0, 0, 0, 0.03);
}

.tool-card-icon {
  flex-shrink: 0;
}

.tool-card-name {
  font-weight: 600;
  font-family: 'JetBrains Mono', 'Fira Code', Consolas, monospace;
  color: #4f46e5;
}

.tool-card-status {
  margin-left: auto;
  font-size: 12px;
  color: #9ca3af;
}

.tool-card-chevron {
  color: #9ca3af;
  transition: transform 0.15s;
}

.tool-card-chevron.open {
  transform: rotate(180deg);
}

.tool-card-body {
  padding: 0 12px 12px;
  border-top: 1px solid #eee;
}

.tool-card-section {
  margin-top: 10px;
}

.tool-card-label {
  font-size: 11px;
  color: #9ca3af;
  text-transform: uppercase;
  letter-spacing: 0.4px;
  margin-bottom: 4px;
}

.tool-card-pre {
  margin: 0;
  padding: 8px 10px;
  background: #1e293b;
  color: #e2e8f0;
  border-radius: 8px;
  font-size: 12px;
  line-height: 1.5;
  overflow-x: auto;
  white-space: pre-wrap;
  word-break: break-word;
  max-height: 220px;
  overflow-y: auto;
  font-family: 'JetBrains Mono', 'Fira Code', Consolas, monospace;
}
</style>
