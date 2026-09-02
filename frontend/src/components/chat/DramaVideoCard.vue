<script setup>
const props = defineProps({
  item: {
    type: Object,
    required: true,
  },
})

const emit = defineEmits(['open-drama'])

function onOpen() {
  emit('open-drama', {
    slug: props.item.slug,
    episode: props.item.episode,
  })
}
</script>

<template>
  <div class="drama-video-card">
    <div class="drama-video-card-head">
      <strong>{{ item.title || '漫剧成片' }}</strong>
      <span v-if="item.slug" class="drama-video-card-meta">
        {{ item.slug }}
        <template v-if="item.episode != null"> · EP{{ String(item.episode).padStart(2, '0') }}</template>
      </span>
    </div>
    <video
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
