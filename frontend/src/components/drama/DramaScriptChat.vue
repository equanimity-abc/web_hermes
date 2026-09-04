<script setup>
import { computed, nextTick, ref, watch } from 'vue'

const props = defineProps({
  messages: { type: Array, default: () => [] },
  loading: { type: Boolean, default: false },
  disabled: { type: Boolean, default: false },
  hint: {
    type: String,
    default: '用一句话描述故事即可生成剧本；已有剧本时可继续对话修改。',
  },
  placeholder: {
    type: String,
    default: '例如：豪门养女重生复仇，共1集60秒…',
  },
  pendingLabel: { type: String, default: '正在生成 / 修改剧本…' },
})

const emit = defineEmits(['send'])

const input = ref('')
const listRef = ref(null)
const inputRef = ref(null)

const canSend = computed(() => Boolean(input.value.trim()) && !props.loading && !props.disabled)

function scrollToBottom() {
  nextTick(() => {
    const el = listRef.value
    if (el) el.scrollTop = el.scrollHeight
  })
}

function onSubmit() {
  const text = input.value.trim()
  if (!text || props.loading || props.disabled) return
  emit('send', text)
  input.value = ''
  nextTick(() => inputRef.value?.focus?.())
}

function onKeydown(e) {
  if (e.key === 'Enter' && !e.shiftKey) {
    e.preventDefault()
    onSubmit()
  }
}

watch(
  () => props.messages.length,
  () => scrollToBottom(),
)

watch(
  () => props.loading,
  (loading, wasLoading) => {
    if (wasLoading && !loading) {
      nextTick(() => inputRef.value?.focus?.())
    }
  },
)

defineExpose({ scrollToBottom })
</script>

<template>
  <div class="drama-script-chat">
    <div ref="listRef" class="drama-script-chat-messages">
      <p v-if="!messages.length" class="drama-script-chat-hint">{{ hint }}</p>
      <div
        v-for="(msg, idx) in messages"
        :key="idx"
        class="drama-script-chat-msg"
        :class="msg.role"
      >
        <div class="drama-script-chat-bubble">{{ msg.content }}</div>
      </div>
      <div v-if="loading" class="drama-script-chat-msg assistant">
        <div class="drama-script-chat-bubble drama-script-chat-bubble--pending">{{ pendingLabel }}</div>
      </div>
    </div>
    <div class="drama-script-chat-input">
      <textarea
        ref="inputRef"
        v-model="input"
        class="drama-script-chat-textarea"
        rows="3"
        :disabled="disabled || loading"
        :placeholder="disabled ? '请先打开或创建漫剧项目' : placeholder"
        @keydown="onKeydown"
      />
      <button
        type="button"
        class="btn-primary btn-sm drama-script-chat-send"
        :disabled="!canSend"
        @click="onSubmit"
      >
        {{ loading ? '处理中…' : '发送' }}
      </button>
    </div>
  </div>
</template>
