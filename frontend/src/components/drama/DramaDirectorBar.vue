<script setup>
defineProps({
  hasScript: { type: Boolean, default: false },
  hasShots: { type: Boolean, default: false },
  dirtyCount: { type: Number, default: 0 },
  busy: { type: Boolean, default: false },
})

defineEmits(['generate-script', 'produce-episode', 'rerender-dirty'])
</script>

<template>
  <div class="drama-director-bar" role="toolbar" aria-label="导演快捷操作">
    <button
      type="button"
      class="btn-ghost btn-sm"
      :disabled="busy"
      title="根据梗概生成或打开剧本台"
      @click="$emit('generate-script')"
    >
      生成剧本
    </button>
    <button
      type="button"
      class="btn-primary btn-sm"
      :disabled="busy || !hasScript"
      title="已有剧本时一键 HQ 成片"
      @click="$emit('produce-episode')"
    >
      一键成片
    </button>
    <button
      type="button"
      class="btn-ghost btn-sm"
      :disabled="busy || dirtyCount < 1"
      :title="dirtyCount ? `重渲 ${dirtyCount} 个脏/失败镜` : '暂无脏镜'"
      @click="$emit('rerender-dirty')"
    >
      导出错镜{{ dirtyCount ? ` (${dirtyCount})` : '' }}
    </button>
  </div>
</template>
