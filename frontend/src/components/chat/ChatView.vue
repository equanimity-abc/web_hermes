<script setup>
import { computed, nextTick, ref, watch } from 'vue'
import WelcomeScreen from './WelcomeScreen.vue'
import MessageList from './MessageList.vue'
import ChatComposer from './ChatComposer.vue'

const props = defineProps({
  messages: { type: Array, required: true },
  modelValue: { type: String, default: '' },
  isLoading: { type: Boolean, default: false },
})

const emit = defineEmits([
  'update:modelValue',
  'submit',
  'stop',
  'copy',
  'edit',
  'regenerate',
  'like',
  'dislike',
])

const welcomeRef = ref(null)
const composerRef = ref(null)
const messageListRef = ref(null)

const isEmpty = computed(() => props.messages.length === 0)

const composerPlaceholder = computed(() =>
  props.isLoading ? '正在回复...' : '给 web_hermes 发送消息',
)

function focusComposer() {
  nextTick(() => {
    if (isEmpty.value) welcomeRef.value?.focus()
    else composerRef.value?.focus()
  })
}

function scrollToBottom() {
  messageListRef.value?.scrollToBottom?.()
}

watch(
  () => props.isLoading,
  (loading, wasLoading) => {
    if (wasLoading && !loading) {
      focusComposer()
      nextTick(() => composerRef.value?.autoResize?.())
    }
  },
)

defineExpose({ focusComposer, scrollToBottom })
</script>

<template>
  <main class="chat-area">
    <WelcomeScreen
      v-if="isEmpty"
      ref="welcomeRef"
      :model-value="modelValue"
      :disabled="isLoading"
      :is-loading="isLoading"
      @update:model-value="emit('update:modelValue', $event)"
      @submit="emit('submit')"
      @stop="emit('stop')"
    />

    <template v-else>
      <MessageList
        ref="messageListRef"
        :messages="messages"
        @copy="emit('copy', $event)"
        @edit="emit('edit', $event)"
        @regenerate="emit('regenerate', $event)"
        @like="emit('like', $event)"
        @dislike="emit('dislike', $event)"
      />

      <div class="input-area">
        <ChatComposer
          ref="composerRef"
          :model-value="modelValue"
          variant="normal"
          :disabled="isLoading"
          :is-loading="isLoading"
          :placeholder="composerPlaceholder"
          @update:model-value="emit('update:modelValue', $event)"
          @submit="emit('submit')"
          @stop="emit('stop')"
        />
      </div>
    </template>
  </main>
</template>
