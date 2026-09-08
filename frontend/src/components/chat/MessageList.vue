<script setup>
import { nextTick, onBeforeUnmount, onMounted, ref } from 'vue'
import MessageItem from './MessageItem.vue'
import { copyText } from '@/utils/clipboard'

defineProps({
  messages: { type: Array, required: true },
})

const emit = defineEmits(['copy', 'edit', 'regenerate', 'like', 'dislike', 'open-drama', 'refresh-drama', 'resume-drama'])

const containerRef = ref(null)
const bottomSentinelRef = ref(null)

/** 打开历史后短时间内内容变高（图片/卡片）仍强制贴底 */
let stickUntilMs = 0
let resizeObserver = null
let mutationObserver = null

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

function applyScrollBottom() {
  const el = containerRef.value
  if (!el) return
  el.scrollTop = el.scrollHeight
  bottomSentinelRef.value?.scrollIntoView({ block: 'end', inline: 'nearest' })
}

function maybeStickBottom() {
  if (Date.now() > stickUntilMs) return
  applyScrollBottom()
}

function onMediaLoad(e) {
  const t = e.target
  if (!t || (t.tagName !== 'IMG' && t.tagName !== 'VIDEO')) return
  maybeStickBottom()
}

function scrollToBottom({ stickMs = 2800 } = {}) {
  stickUntilMs = Date.now() + Math.max(0, Number(stickMs) || 0)
  applyScrollBottom()
  requestAnimationFrame(() => {
    applyScrollBottom()
    requestAnimationFrame(applyScrollBottom)
  })
  // markdown / 异步卡片布局
  nextTick(() => {
    applyScrollBottom()
    setTimeout(applyScrollBottom, 50)
    setTimeout(applyScrollBottom, 200)
    setTimeout(applyScrollBottom, 600)
    setTimeout(applyScrollBottom, 1200)
  })
}

onMounted(() => {
  const el = containerRef.value
  if (!el) return
  el.addEventListener('click', onDelegatedClick)
  el.addEventListener('load', onMediaLoad, true)
  el.addEventListener('loadeddata', onMediaLoad, true)

  if (typeof ResizeObserver !== 'undefined') {
    resizeObserver = new ResizeObserver(() => maybeStickBottom())
    resizeObserver.observe(el)
  }
  if (typeof MutationObserver !== 'undefined') {
    mutationObserver = new MutationObserver(() => maybeStickBottom())
    mutationObserver.observe(el, {
      childList: true,
      subtree: true,
      attributes: true,
      characterData: true,
    })
  }
})

onBeforeUnmount(() => {
  const el = containerRef.value
  el?.removeEventListener('click', onDelegatedClick)
  el?.removeEventListener('load', onMediaLoad, true)
  el?.removeEventListener('loadeddata', onMediaLoad, true)
  resizeObserver?.disconnect()
  mutationObserver?.disconnect()
  resizeObserver = null
  mutationObserver = null
})

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
      @open-drama="emit('open-drama', $event)"
      @refresh-drama="emit('refresh-drama', $event)"
      @resume-drama="emit('resume-drama', $event)"
    />
    <div ref="bottomSentinelRef" class="messages-bottom-sentinel" aria-hidden="true" />
  </div>
</template>

<style scoped>
.messages-bottom-sentinel {
  width: 100%;
  height: 1px;
  pointer-events: none;
}
</style>
