<script setup>
  defineProps({
    message: { type: String, default: '' },
  })
</script>

<template>
  <transition name="toast-fade">
    <div v-if="message" class="copy-toast">{{ message }}</div>
  </transition>
</template>
