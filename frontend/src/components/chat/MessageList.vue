<script setup>
import { onBeforeUnmount, onMounted, ref } from 'vue'
import MessageItem from './MessageItem.vue'
import { copyText } from '@/utils/clipboard'

defineProps({
  messages: { type: Array, required: true },
})

const emit = defineEmits(['copy', 'edit', 'regenerate', 'like', 'dislike'])

const containerRef = ref(null)

function onDelegatedClick(e) {
  const btn = e.target.closest('.code-copy-btn')
  if (!btn) return
  const codeId = btn.getAttribute('data-code')
  if (!codeId) return
  const codeEl = document.getElementById(codeId)
  if (!codeEl) return
  const text = codeEl.textContent || ''
  copyText(text).then((ok) => {
    if (!ok) return
    const orig = btn.innerHTML
    btn.innerHTML = '✓'
    setTimeout(() => {
      btn.innerHTML = orig
    }, 1500)
  })
}

onMounted(() => {
  containerRef.value?.addEventListener('click', onDelegatedClick)
})

onBeforeUnmount(() => {
  containerRef.value?.removeEventListener('click', onDelegatedClick)
})

function scrollToBottom() {
  const el = containerRef.value
  if (el) el.scrollTop = el.scrollHeight
}

defineExpose({ scrollToBottom, containerRef })
</script>

<template>
  <div ref="containerRef" class="messages-container">
    <MessageItem
      v-for="(msg, index) in messages"
      :key="index"
      :message="msg"
      :index="index"
      @copy="emit('copy', $event)"
      @edit="emit('edit', $event)"
      @regenerate="emit('regenerate', $event)"
      @like="emit('like', $event)"
      @dislike="emit('dislike', $event)"
    />
  </div>
</template>
