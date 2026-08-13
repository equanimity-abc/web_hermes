<script setup>
import { computed } from 'vue'
import { renderMarkdown } from '@/utils/markdown'
import ToolCard from './ToolCard.vue'

const props = defineProps({
  message: { type: Object, required: true },
})

const emit = defineEmits(['copy'])

const htmlContent = computed(() => {
  const html = renderMarkdown(props.message.content)
  if (props.message.isStreaming) {
    return html + '<span class="typing-cursor">▊</span>'
  }
  return html
})

const toolCalls = computed(() => props.message.toolCalls || [])
const showStatusOnly = computed(
  () =>
    props.message.isStreaming &&
    !props.message.content &&
    props.message.status &&
    toolCalls.value.length === 0,
)
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
          </div>
        </div>

        <template v-else>
          <div v-if="toolCalls.length" class="tool-cards">
            <ToolCard v-for="(tool, i) in toolCalls" :key="tool.id || i" :tool="tool" />
          </div>

          <div v-if="showStatusOnly" class="stream-status">
            {{ message.status }}
            <span class="typing-cursor">▊</span>
          </div>

          <div
            v-else-if="message.content || message.isStreaming"
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
          </div>
        </template>
      </div>
    </div>
  </div>
</template>
