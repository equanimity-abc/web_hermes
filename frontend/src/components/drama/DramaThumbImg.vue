<script setup>
import { ref, watch } from 'vue'

const props = defineProps({
  src: { type: String, default: '' },
  alt: { type: String, default: '' },
  imgClass: { type: String, default: '' },
  loading: { type: String, default: 'lazy' },
  fetchpriority: { type: String, default: 'auto' },
})

const broken = ref(false)
const fallbackSrc = ref('')

watch(
  () => props.src,
  () => {
    broken.value = false
    fallbackSrc.value = ''
  },
)

function onError() {
  if (broken.value) return
  const raw = String(props.src || '')
  // 缩略图失败时去掉 size= 回退原图
  if (/[?&]size=\d+/.test(raw)) {
    fallbackSrc.value = raw.replace(/([?&])size=\d+/g, '$1').replace(/\?&/, '?').replace(/[?&]$/, '')
    broken.value = true
    return
  }
  broken.value = true
}
</script>

<template>
  <img
    v-if="src && (!broken || fallbackSrc)"
    :src="fallbackSrc || src"
    :alt="alt"
    :class="imgClass"
    :loading="loading"
    :fetchpriority="fetchpriority"
    decoding="async"
    @error="onError"
  />
  <span v-else-if="src && broken" class="drama-thumb-broken">图加载失败</span>
</template>
