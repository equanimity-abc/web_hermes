<script setup>
import { ref } from 'vue'
import ChatComposer from './ChatComposer.vue'

defineProps({
  modelValue: { type: String, default: '' },
  disabled: { type: Boolean, default: false },
})

const emit = defineEmits(['update:modelValue', 'submit'])

const composerRef = ref(null)

function focus() {
  composerRef.value?.focus()
}

defineExpose({ focus })
</script>

<template>
  <div class="welcome-screen">
    <div class="welcome-brand">
      <svg width="48" height="48" viewBox="0 0 48 48" fill="none" xmlns="http://www.w3.org/2000/svg">
        <rect width="48" height="48" rx="12" fill="#4f46e5" />
        <path d="M14 16h20M14 24h20M14 32h14" stroke="#fff" stroke-width="3" stroke-linecap="round" />
      </svg>
      <h1 class="welcome-title">web_hermes</h1>
    </div>

    <div class="agent-hint">
      <p>🤖 Agent 模式已开启，我将作为智能助手逐步拆解任务、调用工具并执行操作</p>
    </div>

    <div class="welcome-input-area">
      <ChatComposer
        ref="composerRef"
        :model-value="modelValue"
        variant="welcome"
        :disabled="disabled"
        placeholder="给 web_hermes 发送消息"
        @update:model-value="emit('update:modelValue', $event)"
        @submit="emit('submit')"
      />
    </div>
  </div>
</template>
