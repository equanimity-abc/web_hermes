<script setup>
import { computed } from 'vue'

const props = defineProps({
  item: {
    type: Object,
    required: true,
  },
})

const emit = defineEmits(['open-drama'])

const isImage = computed(() => {
  const t = String(props.item?.type || '').toLowerCase()
  if (t === 'image' || t === 'img' || t === 'scene') return true
  const url = String(props.item?.url || '')
  return /\.(png|jpe?g|webp|gif)(\?|$)/i.test(url)
})

const isAudio = computed(() => {
  const t = String(props.item?.type || '').toLowerCase()
  if (t === 'audio' || t === 'voice') return true
  const url = String(props.item?.url || '')
  return /\.(mp3|wav|m4a|aac)(\?|$)/i.test(url)
})

function onOpen() {
  emit('open-drama', {
    slug: props.item.slug,
    episode: props.item.episode,
  })
}
</script>

<template>
  <div class="drama-video-card" :class="{ 'is-fail-preview': item.failPreview }">
    <div class="drama-video-card-head">
      <strong>{{ item.title || (isImage ? '失败画面' : isAudio ? '失败音频' : '失败视频') }}</strong>
      <span v-if="item.slug" class="drama-video-card-meta">
        {{ item.slug }}
        <template v-if="item.episode != null"> · EP{{ String(item.episode).padStart(2, '0') }}</template>
        <template v-if="item.shot != null"> · Shot {{ item.shot }}</template>
      </span>
    </div>
    <img
      v-if="isImage"
      class="drama-video-card-player drama-video-card-image"
      :src="item.url"
      :alt="item.title || '失败画面'"
    />
    <audio
      v-else-if="isAudio"
      class="drama-video-card-audio"
      controls
      preload="metadata"
      :src="item.url"
    />
    <video
      v-else
      class="drama-video-card-player"
      controls
      preload="metadata"
      playsinline
      :src="item.url"
    />
    <div class="drama-video-card-actions">
      <button
        v-if="item.slug"
        type="button"
        class="btn-ghost btn-sm drama-video-card-open"
        @click="onOpen"
      >
        去漫剧工作台修改
      </button>
      <a class="drama-video-card-link" :href="item.url" target="_blank" rel="noopener">新标签页打开</a>
    </div>
  </div>
</template>
