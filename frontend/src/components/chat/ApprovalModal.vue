<script setup>
import { computed } from 'vue'

const props = defineProps({
  approval: {
    type: Object,
    default: null,
    // { approval_id, stream_id, name, arguments, tool_call_id, reason }
  },
  busy: { type: Boolean, default: false },
})

const emit = defineEmits(['approve', 'deny'])

const previewArgs = computed(() => {
  const raw = props.approval?.arguments || ''
  try {
    return JSON.stringify(JSON.parse(raw), null, 2)
  } catch {
    return String(raw)
  }
})

const toolLabel = computed(() => props.approval?.name || '未知工具')
</script>

<template>
  <div v-if="approval" class="approval-overlay" role="dialog" aria-modal="true">
    <div class="approval-modal">
      <div class="approval-title">需要确认</div>
      <p class="approval-desc">
        Agent 请求执行危险工具 <code>{{ toolLabel }}</code>。批准后才会真正执行。
      </p>
      <div class="approval-section">
        <div class="approval-label">参数</div>
        <pre class="approval-pre">{{ previewArgs }}</pre>
      </div>
      <div class="approval-actions">
        <button
          type="button"
          class="approval-btn deny"
          :disabled="busy"
          @click="emit('deny')"
        >
          拒绝
        </button>
        <button
          type="button"
          class="approval-btn approve"
          :disabled="busy"
          @click="emit('approve')"
        >
          批准执行
        </button>
      </div>
    </div>
  </div>
</template>
