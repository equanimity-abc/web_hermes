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
  scriptDraft: { type: String, default: '' },
  scriptImpact: { type: Object, default: null },
  boardMode: { type: String, default: 'shots' },
})

const emit = defineEmits([
  'open-episode',
  'select-shot',
  'save',
  'rerender',
  'rerender-layer',
  'toggle-lock',
  'save-episode',
  'update:scriptDraft',
  'update:boardMode',
  'preview-script',
  'save-script',
  'rerender-dirty',
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

const shotFrozen = computed(() => isLocked('shot'))
const scriptDirty = computed(() => (props.scriptDraft || '') !== (props.episode?.script || ''))
const dirtyShotCount = computed(
  () => (props.shots || []).filter((s) => (s.dirty || []).length).length,
)

function impactFor(n) {
  return (props.scriptImpact?.shots || []).find((item) => item.n === n) || null
}

function shotFlag(shot) {
  const locked = shot.locked || []
  const impact = impactFor(shot.n)
  if (locked.includes('shot') || impact?.frozen) return '整锁'
  if (impact?.changed?.length) return '将改'
  if ((shot.dirty || []).length) return '脏'
  if (locked.length) return '锁'
  return statusLabel(shot)
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
        <div class="drama-board-tabs">
          <button
            type="button"
            :class="{ active: boardMode === 'shots' }"
            @click="emit('update:boardMode', 'shots')"
          >
            分镜
          </button>
          <button
            type="button"
            :class="{ active: boardMode === 'script' }"
            @click="emit('update:boardMode', 'script')"
          >
            剧本
          </button>
        </div>
        <h2>{{ boardMode === 'script' ? '受影响镜头' : '分镜' }}</h2>
        <button
          v-for="shot in shots"
          :key="shot.n"
          type="button"
          class="drama-shot-item"
          :class="{
            active: shot.n === selectedN,
            dirty: (shot.dirty || []).length || impactFor(shot.n)?.changed?.length,
            frozen: (shot.locked || []).includes('shot'),
          }"
          @click="emit('select-shot', shot.n)"
        >
          <span class="drama-shot-n">{{ shot.n }}</span>
          <span class="drama-shot-body">
            <strong>Shot {{ shot.n }}</strong>
            <em>{{ shot.画面 || '（无画面描述）' }}</em>
          </span>
          <span class="drama-shot-flag">{{ shotFlag(shot) }}</span>
        </button>
        <p v-if="!shots.length" class="drama-empty-hint">
          还没有 shots.json。请先在对话里 parse_shots 或 render_episode。
        </p>
      </section>

      <section v-if="boardMode === 'script'" class="drama-script">
        <textarea
          :value="scriptDraft"
          spellcheck="false"
          placeholder="# EP01 标题&#10;- 时长: 45s&#10;- 钩子:&#10;- 悬念:&#10;&#10;## 分镜&#10;### Shot 1 (0-3s)"
          @input="emit('update:scriptDraft', $event.target.value)"
        />
        <p v-if="scriptDirty" class="drama-empty-hint">剧本有未保存改动。输入时会提示影响哪些镜头。</p>
        <p v-if="scriptImpact?.summary" class="drama-impact-summary">{{ scriptImpact.summary }}</p>
        <ul v-if="scriptImpact?.shots?.length" class="drama-impact-list">
          <li v-for="item in scriptImpact.shots" :key="item.n">
            Shot {{ item.n }}
            <template v-if="item.frozen">：已锁整镜，未改</template>
            <template v-else-if="item.changed?.length">：{{ item.changed.join('、') }}</template>
            <template v-else>：无改动</template>
          </li>
        </ul>
      </section>

      <section v-else class="drama-preview">
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
        <h2>{{ boardMode === 'script' ? '剧本操作' : '检查器' }}</h2>
        <div v-if="boardMode === 'script'" class="drama-actions drama-actions--script">
          <button type="button" class="btn-ghost" :disabled="saving || rendering" @click="emit('preview-script')">
            {{ saving ? '预览中…' : '预览影响' }}
          </button>
          <button
            type="button"
            class="btn-primary"
            :disabled="saving || rendering || !scriptDraft.trim()"
            @click="emit('save-script')"
          >
            {{ saving ? '保存中…' : '保存剧本' }}
          </button>
          <button
            type="button"
            class="btn-ghost"
            :disabled="rendering || saving || !dirtyShotCount"
            @click="emit('rerender-dirty')"
          >
            {{ rendering ? '重渲中…' : `重渲脏镜${dirtyShotCount ? ` (${dirtyShotCount})` : ''}` }}
          </button>
        </div>
        <template v-if="selected">
          <div class="drama-freeze">
            <button
              type="button"
              class="btn-tiny"
              :disabled="saving || rendering"
              @click="emit('toggle-lock', 'shot')"
            >
              {{ shotFrozen ? '解锁整镜' : '锁定整镜' }}
            </button>
            <span>{{ shotFrozen ? '保存剧本时不会覆盖这一镜' : '锁住后改剧本不会动这一镜' }}</span>
          </div>
          <label>
            画面
            <textarea v-model="draft.画面" rows="3" :disabled="shotFrozen || isLocked('scene')" />
          </label>
          <label>
            对白
            <textarea v-model="draft.对白" rows="3" :disabled="shotFrozen" />
          </label>
          <label>
            字幕
            <textarea v-model="draft.字幕" rows="2" :disabled="shotFrozen || isLocked('overlay')" />
          </label>
          <label>
            运镜
            <select v-model="draft.camera" :disabled="shotFrozen || isLocked('clip')">
              <option v-for="cam in cameras" :key="cam" :value="cam">{{ cam }}</option>
            </select>
          </label>
          <label>
            时长（秒）
            <input
              v-model.number="draft.duration"
              type="number"
              min="0.2"
              step="0.1"
              :disabled="shotFrozen || isLocked('clip')"
            />
          </label>
          <template v-if="boardMode === 'shots'">
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
        </template>
        <p v-else class="drama-empty-hint">
          {{ boardMode === 'script' ? '可先保存剧本生成分镜，再选镜头锁定整镜。' : '选择左侧一个镜头。' }}
        </p>
      </section>
    </div>

    <div v-else class="drama-idle">
      <h2>分镜台</h2>
      <p>从左侧打开一个漫剧项目。分镜页改对白和运镜；剧本页改结局悬念，已锁整镜不会被覆盖。</p>
    </div>
  </main>
</template>
