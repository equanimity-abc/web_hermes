<script setup>
import { computed, nextTick, ref, watch } from 'vue'
import ChatComposer from '@/components/chat/ChatComposer.vue'

const props = defineProps({
  messages: { type: Array, default: () => [] },
  loading: { type: Boolean, default: false },
  disabled: { type: Boolean, default: false },
  characterName: { type: String, default: '' },
  title: { type: String, default: '调整定妆图' },
  hint: {
    type: String,
    default: '通过对话随时修改三视图描述，系统将自动更新设定并重新生成定妆图。',
  },
  placeholder: {
    type: String,
    default: '描述想调整的内容，例如：头发改成长卷发、服装换成红色旗袍…',
  },
  disabledPlaceholder: { type: String, default: '参考图已锁定，解锁后可调整' },
  pendingLabel: { type: String, default: '正在生成…' },
})

const emit = defineEmits(['send'])

const input = ref('')
const listRef = ref(null)
const composerRef = ref(null)

const subtitle = computed(() => props.characterName)

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
  nextTick(() => composerRef.value?.autoResize?.())
}

watch(
  () => props.messages.length,
  () => scrollToBottom(),
)

watch(
  () => props.loading,
  (loading, wasLoading) => {
    if (wasLoading && !loading) {
      nextTick(() => composerRef.value?.focus?.())
    }
  },
)

defineExpose({ scrollToBottom })
</script>

<template>
  <div class="drama-cast-chat">
    <header class="drama-cast-chat-head">
      <h4>{{ title }}</h4>
      <span v-if="subtitle" class="drama-cast-chat-sub">{{ subtitle }}</span>
    </header>
    <div ref="listRef" class="drama-cast-chat-messages">
      <p v-if="!messages.length" class="drama-cast-chat-hint">
        {{ hint }}
      </p>
      <div
        v-for="(msg, idx) in messages"
        :key="idx"
        class="drama-cast-chat-msg"
        :class="msg.role"
      >
        <div class="drama-cast-chat-bubble">{{ msg.content }}</div>
      </div>
      <div v-if="loading" class="drama-cast-chat-msg assistant">
        <div class="drama-cast-chat-bubble drama-cast-chat-bubble--pending">{{ pendingLabel }}</div>
      </div>
    </div>
    <div class="drama-cast-chat-input">
      <ChatComposer
        ref="composerRef"
        v-model="input"
        variant="normal"
        :disabled="disabled || loading"
        :is-loading="loading"
        :placeholder="disabled ? disabledPlaceholder : placeholder"
        @submit="onSubmit"
      />
    </div>
  </div>
</template>
