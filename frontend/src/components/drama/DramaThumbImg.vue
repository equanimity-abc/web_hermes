<script setup>
defineProps({
  src: { type: String, default: '' },
  alt: { type: String, default: '' },
  imgClass: { type: String, default: '' },
  loading: { type: String, default: 'lazy' },
  fetchpriority: { type: String, default: 'auto' },
})
</script>

<template>
  <img
    v-if="src"
    :src="src"
    :alt="alt"
    :class="imgClass"
    :loading="loading"
    :fetchpriority="fetchpriority"
    decoding="async"
  />
</template>
