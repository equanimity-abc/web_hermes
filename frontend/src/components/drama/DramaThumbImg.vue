<script setup>
import { ref, watch } from 'vue'

const props = defineProps({
  src: { type: String, default: '' },
  alt: { type: String, default: '' },
  imgClass: { type: String, default: '' },
  loading: { type: String, default: 'lazy' },
  fetchpriority: { type: String, default: 'auto' },
})

const shown = ref('')

watch(
  () => props.src,
  (next) => {
    if (!next) {
      shown.value = ''
      return
    }
    if (next === shown.value) return
    const img = new Image()
    img.decoding = 'async'
    const commit = () => {
      shown.value = next
    }
    img.onload = commit
    img.onerror = commit
    img.src = next
    if (img.complete) commit()
  },
  { immediate: true },
)
</script>

<template>
  <img
    v-if="shown"
    :src="shown"
    :alt="alt"
    :class="imgClass"
    :loading="loading"
    :fetchpriority="fetchpriority"
    decoding="async"
  />
</template>
