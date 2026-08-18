<script setup>
import { computed, ref } from 'vue'

const props = defineProps({
  project: { type: Object, default: null },
  episode: { type: Object, default: null },
  episodeN: { type: [Number, null], default: null },
  episodes: { type: Array, default: () => [] },
  shots: { type: Array, default: () => [] },
  selectedN: { type: [Number, null], default: null },
  selected: { type: Object, default: null },
  draft: { type: Object, required: true },
  dirty: { type: Boolean, default: false },
  saving: { type: Boolean, default: false },
  rendering: { type: Boolean, default: false },
  error: { type: String, default: '' },
  notice: { type: String, default: '' },
  bust: { type: Number, default: 0 },
})

const emit = defineEmits([
  'open-episode',
  'select-shot',
  'save',
  'rerender',
  'rerender-layer',
  'toggle-lock',
  'save-episode',
])

const previewMode = ref('shot')
const cameras = computed(() => props.episode?.cameras || props.project?.cameras || [])
const layerRows = [
  { id: 'scene', label: '画面' },
  { id: 'overlay', label: '字幕' },
  { id: 'voice', label: '配音' },
  { id: 'clip', label: '成片' },
  { id: 'assemble', label: '整集' },
]

function isLocked(layer) {
  return (props.selected?.locked || []).includes(layer)
}

function isDirtyLayer(layer) {
  return (props.selected?.dirty || []).includes(layer)
}

const previewUrl = computed(() => {
  let url = ''
  if (previewMode.value === 'episode') url = props.episode?.play_url || ''
  else {
    const shot = props.selected
    url = shot?.files?.clip?.url || shot?.files?.scene?.url || shot?.preview_url || ''
  }
  if (!url) return ''
  return `${url}${url.includes('?') ? '&' : '?'}_=${props.bust || 0}`
})

const previewKind = computed(() => {
  const url = previewUrl.value
  if (!url) return 'empty'
  if (url.includes('.mp4')) return 'video'
  return 'image'
})

function statusLabel(shot) {
  if ((shot.dirty || []).length) return '脏'
  if (shot.status === 'rendered') return '已渲'
  return shot.status || '待做'
}
</script>

<template>
  <main class="drama-studio">
    <header class="drama-top">
      <div class="drama-top-title">
        <h1>{{ project?.project?.title || '漫剧工作台' }}</h1>
        <p v-if="project?.project?.logline" class="drama-logline">{{ project.project.logline }}</p>
      </div>
      <div class="drama-eps">
        <button
          v-for="ep in episodes"
          :key="ep.n"
          type="button"
          class="drama-ep-btn"
          :class="{ active: ep.n === episodeN }"
          @click="emit('open-episode', ep.n)"
        >
          EP{{ String(ep.n).padStart(2, '0') }}
          <span class="drama-ep-meta">{{ ep.shot_count || 0 }} 镜</span>
        </button>
        <p v-if="!episodes.length" class="drama-empty-hint">这个项目还没有分集。</p>
      </div>
    </header>

    <p v-if="error" class="drama-banner drama-banner--err">{{ error }}</p>
    <p v-else-if="notice" class="drama-banner">{{ notice }}</p>

    <div v-if="episode" class="drama-board">
      <section class="drama-shots">
        <h2>分镜</h2>
        <button
          v-for="shot in shots"
          :key="shot.n"
          type="button"
          class="drama-shot-item"
          :class="{ active: shot.n === selectedN, dirty: (shot.dirty || []).length }"
          @click="emit('select-shot', shot.n)"
        >
          <span class="drama-shot-n">{{ shot.n }}</span>
          <span class="drama-shot-body">
            <strong>Shot {{ shot.n }}</strong>
            <em>{{ shot.画面 || '（无画面描述）' }}</em>
          </span>
          <span class="drama-shot-flag">
            <template v-if="(shot.locked || []).length">锁 </template>{{ statusLabel(shot) }}
          </span>
        </button>
        <p v-if="!shots.length" class="drama-empty-hint">
          还没有 shots.json。请先在对话里 parse_shots 或 render_episode。
        </p>
      </section>

      <section class="drama-preview">
        <div class="drama-preview-tabs">
          <button type="button" :class="{ active: previewMode === 'shot' }" @click="previewMode = 'shot'">
            本镜
          </button>
          <button
            type="button"
            :class="{ active: previewMode === 'episode' }"
            :disabled="!episode.play_url"
            @click="previewMode = 'episode'"
          >
            整集
          </button>
        </div>
        <div class="drama-stage">
          <video
            v-if="previewKind === 'video'"
            :key="previewUrl"
            class="drama-media"
            :src="previewUrl"
            controls
            playsinline
          />
          <img v-else-if="previewKind === 'image'" class="drama-media" :src="previewUrl" alt="镜头画面" />
          <div v-else class="drama-stage-empty">尚无成片，保存后可重渲本镜</div>
        </div>
      </section>

      <section class="drama-inspector">
        <h2>检查器</h2>
        <template v-if="selected">
          <label>
            画面
            <textarea v-model="draft.画面" rows="3" :disabled="isLocked('scene')" />
          </label>
          <label>
            对白
            <textarea v-model="draft.对白" rows="3" />
          </label>
            <label>
            字幕
            <textarea v-model="draft.字幕" rows="2" :disabled="isLocked('overlay')" />
          </label>
          <label>
            运镜
            <select v-model="draft.camera" :disabled="isLocked('clip')">
              <option v-for="cam in cameras" :key="cam" :value="cam">{{ cam }}</option>
            </select>
          </label>
          <label>
            时长（秒）
            <input v-model.number="draft.duration" type="number" min="0.2" step="0.1" :disabled="isLocked('clip')" />
          </label>
          <h3 class="drama-layers-title">分层</h3>
          <div class="drama-layers">
            <div v-for="row in layerRows" :key="row.id" class="drama-layer-row">
              <span>{{ row.label }}</span>
              <span class="drama-layer-flags">
                <em v-if="isLocked(row.id)">锁</em>
                <em v-else-if="isDirtyLayer(row.id)" class="is-dirty">脏</em>
                <em v-else>可渲</em>
              </span>
              <button
                v-if="row.id !== 'assemble'"
                type="button"
                class="btn-tiny"
                :disabled="saving || rendering"
                @click="emit('toggle-lock', row.id)"
              >
                {{ isLocked(row.id) ? '解锁' : '锁定' }}
              </button>
              <span v-else />
              <button
                type="button"
                class="btn-tiny"
                :disabled="rendering || saving || isLocked(row.id)"
                @click="emit('rerender-layer', row.id)"
              >
                {{ row.id === 'assemble' ? '重拼' : '仅重做' }}
              </button>
            </div>
          </div>
          <p v-if="(selected.dirty || []).length" class="drama-dirty">
            脏层：{{ selected.dirty.join(' / ') }}
          </p>
          <p v-if="(selected.locked || []).length" class="drama-locked">
            已锁：{{ selected.locked.join(' / ') }}（重渲不会覆盖）
          </p>
          <div class="drama-actions">
            <button type="button" class="btn-primary" :disabled="saving || !dirty" @click="emit('save')">
              {{ saving ? '保存中…' : '保存' }}
            </button>
            <button type="button" class="btn-ghost" :disabled="rendering || saving" @click="emit('rerender')">
              {{ rendering ? '重渲中…' : '重渲脏层' }}
            </button>
          </div>
        </template>
        <p v-else class="drama-empty-hint">选择左侧一个镜头。</p>
      </section>
    </div>

    <div v-else class="drama-idle">
      <h2>分镜台</h2>
      <p>从左侧打开一个漫剧项目。改对白、运镜、时长后点保存，不必经过聊天。</p>
    </div>
  </main>
</template>
