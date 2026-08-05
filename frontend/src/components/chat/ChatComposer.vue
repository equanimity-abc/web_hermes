<script setup>
import { nextTick, ref, watch } from 'vue'

const props = defineProps({
  modelValue: { type: String, default: '' },
  disabled: { type: Boolean, default: false },
  isLoading: { type: Boolean, default: false },
  placeholder: { type: String, default: '给 web_hermes 发送消息' },
  /** 'welcome' | 'normal' */
  variant: { type: String, default: 'normal' },
})

const emit = defineEmits(['update:modelValue', 'submit', 'stop'])

const textareaRef = ref(null)

function onInput(e) {
  emit('update:modelValue', e.target.value)
  autoResize()
}

function autoResize() {
  const el = textareaRef.value
  if (!el) return
  el.style.height = 'auto'
  el.style.height = Math.min(el.scrollHeight, props.variant === 'welcome' ? 360 : 200) + 'px'
}

function focus() {
  nextTick(() => textareaRef.value?.focus())
}

watch(
  () => props.modelValue,
  (val) => {
    if (!val) {
      nextTick(() => {
        if (textareaRef.value) textareaRef.value.style.height = 'auto'
      })
    }
  },
)

defineExpose({ focus, autoResize })
</script>

<template>
  <div :class="variant === 'welcome' ? 'composer--welcome' : 'composer--normal'">
    <div class="input-box-wrapper">
      <textarea
        ref="textareaRef"
        class="input-box"
        :value="modelValue"
        :placeholder="placeholder"
        :disabled="disabled || isLoading"
        rows="1"
        @input="onInput"
        @keydown.enter.exact.prevent="!isLoading && emit('submit')"
      />
    </div>
    <div class="input-actions">
      <button
        v-if="isLoading"
        type="button"
        class="btn-stop"
        title="停止生成"
        @click="emit('stop')"
      >
        <svg width="14" height="14" viewBox="0 0 14 14" fill="none" aria-hidden="true">
          <rect x="2" y="2" width="10" height="10" rx="1.5" fill="currentColor" />
        </svg>
      </button>
      <button
        v-else
        type="button"
        class="btn-send"
        :class="{ 'has-content': modelValue.trim() }"
        :disabled="!modelValue.trim() || disabled"
        @click="emit('submit')"
      >
        <svg width="18" height="18" viewBox="0 0 18 18" fill="none">
          <path
            d="M9 16V4M4 9l5-5 5 5"
            stroke="currentColor"
            stroke-width="2"
            stroke-linecap="round"
            stroke-linejoin="round"
          />
        </svg>
      </button>
    </div>
  </div>
</template>
