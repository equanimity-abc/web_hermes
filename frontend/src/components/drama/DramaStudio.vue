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
  characters: { type: Array, default: () => [] },
  voices: { type: Array, default: () => [] },
  selectedCharacterId: { type: [String, null], default: null },
  selectedCharacter: { type: Object, default: null },
  charDraft: { type: Object, required: true },
  timelineOrder: { type: Array, default: () => [] },
  tlDraft: { type: Object, required: true },
  timelineItems: { type: Array, default: () => [] },
  orderedShots: { type: Array, default: () => [] },
  transitions: { type: Array, default: () => [] },
  i2vModes: { type: Array, default: () => ['off', 'auto', 'on'] },
  shotKinds: { type: Array, default: () => [] },
  shotSizes: { type: Array, default: () => [] },
  timelineDirty: { type: Boolean, default: false },
  orderDirty: { type: Boolean, default: false },
  mixDraft: { type: Object, required: true },
  mixDirty: { type: Boolean, default: false },
  mixUnlicensed: { type: Boolean, default: false },
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
  'select-character',
  'add-character',
  'save-character',
  'lock-ref',
  'upload-ref',
  'delete-character',
  'toggle-role',
  'generate-candidates',
  'choose-candidate',
  'upload-scene',
  'generate-i2v',
  'generate-lip',
  'generate-keys',
  'choose-key',
  'upload-key',
  'lock-key',
  'qc-shot',
  'qc-episode',
  'pass-episode-qc',
  'pass-shot-qc',
  'reject-shot-qc',
  'remix-loudness',
  'suggest-coverage',
  'apply-coverage',
  'dismiss-coverage',
  'lock-coverage',
  'classify-shots',
  'save-timeline-shot',
  'save-timeline-all',
  'save-timeline-order',
  'move-timeline-shot',
  'reorder-timeline',
  'export-timeline',
  'save-mix',
  'upload-bgm',
  'apply-mix',
  'clear-bgm',
])

const previewMode = ref('shot')
const refInput = ref(null)
const sceneInput = ref(null)
const keyInput = ref(null)
const bgmInput = ref(null)
const selectedKeyId = ref(null)
const dragFromN = ref(null)
const cameras = computed(() => props.episode?.cameras || props.project?.cameras || [])
const layerRows = [
  { id: 'scene', label: '画面' },
  { id: 'overlay', label: '字幕' },
  { id: 'voice', label: '配音' },
  { id: 'motion', label: '运动' },
  { id: 'lip', label: '口型' },
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
  if (shot.route?.planned_ladder === 'L3' || shot.route?.ladder === 'L3') return 'L3'
  if (shot.lip_source === 'mock' || shot.lip_source === 'http') return '口型'
  if (shot.route?.ladder === 'L0' || shot.route?.planned_ladder === 'L0') return 'L0'
  if (shot.route?.planned_ladder === 'L2') return 'L2'
  if (shot.route?.ladder === 'L1') return 'L1'
  if (shot.i2v_source === 'ai') return 'I2V'
  if (shot.i2v_source === 'fallback') return '静图'
  if (locked.includes('shot') || impact?.frozen) return '整锁'
  if (impact?.changed?.length) return '将改'
  if ((shot.dirty || []).length) return '脏'
  if ((shot.candidates || []).length) return `${shot.candidates.length}候`
  if (locked.length) return '锁'
  return statusLabel(shot)
}

const canGenerateI2v = computed(() => {
  const shot = props.selected
  if (!shot) return false
  if ((shot.route && shot.route.will_run === false) || shot.route?.ladder === 'L0') return false
  const mode = props.draft?.i2v || shot.i2v || 'auto'
  if (mode === 'off') return false
  if (mode === 'on') return true
  const locked = shot.locked || []
  return locked.includes('scene') || locked.includes('shot')
})

const kindLocked = computed(() => (props.selected?.locked || []).includes('kind') || shotFrozen.value)

const canGenerateLip = computed(() => Boolean(props.selected?.lip?.ok || props.selected?.lip?.will_run))

const canGenerateKeys = computed(() => Boolean(props.selected?.keys_gate?.ok || props.selected?.keys_gate?.will_run))

const selectedKey = computed(() => {
  const keys = props.selected?.keys || []
  return keys.find((k) => k.id === selectedKeyId.value) || keys[0] || null
})

const i2vCostLabel = computed(() => {
  const route = props.selected?.route
  const lip = props.selected?.lip
  const cost = props.episode?.cost || {}
  const cur = route?.currency || cost.currency || 'CNY'
  const shotCost = Number(route?.cost_per_shot || 0)
  const epCost = Number(cost.i2v_estimate || 0)
  const lipCost = Number(lip?.cost_per_shot || 0)
  const epLip = Number(cost.lip_estimate || 0)
  if (!route) return ''
  const planned = route.planned_ladder || route.ladder
  const cap = `${cost.expensive_shots || 0}/${cost.expensive_cap || 2} 贵镜`
  if (route.ladder === 'L0') return `${planned} 静图运镜 · 本集 I2V 估 ${cur} ${epCost}`
  const bits = [`${planned}→${route.ladder} 估 ${cur} ${shotCost}`, `本集 ${cur} ${epCost}`, cap]
  if (lip?.will_run) bits.push(`口型 ${cur} ${lipCost} / 本集 ${epLip}`)
  const keys = props.selected?.keys_gate
  if (keys?.will_run) bits.push(`关键帧 L4 ${cur} ${Number(keys.cost_per_shot || 0)}`)
  if (route.reason) bits.push(route.reason)
  return bits.join(' · ')
})

const i2vSourceLabel = computed(() => {
  const src = props.selected?.i2v_source || ''
  const lipSrc = props.selected?.lip_source || ''
  const parts = []
  if (src === 'ai') parts.push('已生成 I2V 运动')
  else if (src === 'keys') parts.push('已用稀疏关键帧补间')
  else if (src === 'fallback') parts.push('I2V 失败，已回退静图运镜')
  else parts.push('尚未生成 I2V')
  if (lipSrc === 'mock' || lipSrc === 'http') parts.push(`口型 ${lipSrc}`)
  else if (lipSrc === 'fallback') parts.push('口型失败，闭口静图')
  else if (props.selected?.lip && !props.selected.lip.ok) parts.push(props.selected.lip.reason || '本镜不开口型')
  return parts.join(' · ')
})

const identityLabel = computed(() => {
  const id = props.selected?.identity
  const hint = props.selected?.identity_hint || ''
  if (!id) return hint || '尚未抽检身份'
  const threshold = id.threshold ?? 0.65
  if (id.status === 'skipped') {
    return hint || id.hint || `身份未出分（${id.reason || 'skipped'}），不得记为通过`
  }
  const score = id.cosine == null ? '—' : Number(id.cosine).toFixed(2)
  if (id.pass) return `身份 ${score} / ${threshold} · 通过`
  return `身份 ${score} / ${threshold} · 未通过 · ${hint || id.hint || '低于 0.65，请重抽首帧（不重配音）'}`
})

const identityClass = computed(() => {
  const id = props.selected?.identity
  if (!id) return ''
  if (id.status === 'skipped') return 'drama-qc-skip'
  if (id.status === 'ok' && id.pass) return 'drama-qc-pass'
  return 'drama-qc-fail'
})

const episodeQc = computed(() => props.episode?.qc || null)

const selectedQcRow = computed(() => {
  const rows = episodeQc.value?.shots || []
  return rows.find((row) => row.n === props.selectedN) || props.selected?.qc || null
})

function qcCheckLabel(check) {
  if (!check) return '未检'
  const status = check.status || ''
  if (status === 'n/a') return '不适用'
  if (status === 'skipped') return 'skipped'
  if (status === 'ok' && check.pass) return '通过'
  if (status === 'ok') return '未通过'
  return '未检'
}

function qcCheckClass(check) {
  if (!check) return ''
  if (check.status === 'n/a') return 'drama-qc-na'
  if (check.status === 'skipped') return 'drama-qc-skip'
  if (check.status === 'ok' && check.pass) return 'drama-qc-pass'
  return 'drama-qc-fail'
}

function qcShotFlag(shot) {
  const row = (episodeQc.value?.shots || []).find((item) => item.n === shot.n)
  if (!row) return '未检'
  if (row.verdict === '通过') return '通过'
  if (String(row.block_reason || '').includes('skipped')) return 'skipped'
  return row.verdict || '待修'
}

const openSuggestions = computed(() =>
  (props.episode?.coverage?.suggestions || []).filter((item) => item.status === 'open'),
)

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

const episodePreviewUrl = computed(() => {
  const url = props.episode?.play_url || ''
  if (!url) return ''
  return `${url}${url.includes('?') ? '&' : '?'}_=${props.bust || 0}`
})

const mix = computed(() => props.episode?.mix || null)
const bgmPreviewUrl = computed(() => {
  const url = mix.value?.file?.url || ''
  if (!url) return ''
  return `${url}${url.includes('?') ? '&' : '?'}_=${props.bust || 0}`
})
const catalogTracks = computed(() => mix.value?.catalog || [])

const previewKind = computed(() => {
  const url = previewUrl.value
  if (!url) return 'empty'
  if (url.includes('.mp4')) return 'video'
  return 'image'
})

const refPreviewUrl = computed(() => {
  const url = props.selectedCharacter?.ref_url
  if (!url) return ''
  return `${url}${url.includes('?') ? '&' : '?'}_=${props.bust || 0}`
})

const boundVoice = computed(() => {
  const ids = props.draft?.角色 || []
  const first = (props.characters || []).find((c) => ids.includes(c.id))
  if (!first) return ''
  const voice = (props.voices || []).find((v) => v.id === first.voice)
  return `${first.name} · ${voice?.label || first.voice}`
})

function isRoleOn(id) {
  return (props.draft?.角色 || []).includes(id)
}

function onRefFile(ev) {
  const file = ev.target.files?.[0]
  ev.target.value = ''
  if (file) emit('upload-ref', file)
}

function onSceneFile(ev) {
  const file = ev.target.files?.[0]
  ev.target.value = ''
  if (file) emit('upload-scene', file)
}

function onKeyFile(ev) {
  const file = ev.target.files?.[0]
  ev.target.value = ''
  const kid = selectedKey.value?.id
  if (file && kid) emit('upload-key', kid, file)
}

function onBgmFile(ev) {
  const file = ev.target.files?.[0]
  ev.target.value = ''
  if (file) emit('upload-bgm', file, Boolean(props.mixDraft.license_ok))
}

function candUrl(cand) {
  const url = cand?.url || ''
  if (!url) return ''
  return `${url}${url.includes('?') ? '&' : '?'}_=${props.bust || 0}`
}

function keyUrl(key) {
  return candUrl(key)
}

function kindLabel(kind) {
  const map = {
    establishing: '定场',
    insert: '插入',
    dialogue: '对白',
    reaction: '反应',
    action: '动作',
    crowd: '群像',
    title: '标题',
  }
  return map[kind] || kind
}

function statusLabel(shot) {
  if ((shot.dirty || []).length) return '脏'
  if (shot.status === 'rendered') return '已渲'
  return shot.status || '待做'
}

function tlItem(n) {
  return props.timelineItems.find((item) => item.n === n) || null
}

function tlLabel(shot) {
  const item = tlItem(shot.n)
  const play = item?.play_duration ?? shot.duration
  const trim = Number(shot.trim_out || 0)
  const parts = [`${play}s`]
  if (trim > 0) parts.push(`-${trim}s`)
  if (shot.transition && shot.transition !== 'auto') parts.push(shot.transition)
  return parts.join(' · ')
}

function onDragStart(n) {
  dragFromN.value = n
}

function onDragOver(ev) {
  ev.preventDefault()
}

function onDrop(n) {
  if (dragFromN.value != null) emit('reorder-timeline', dragFromN.value, n)
  dragFromN.value = null
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

    <div v-if="project" class="drama-board">
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
          <button
            type="button"
            :class="{ active: boardMode === 'cast' }"
            @click="emit('update:boardMode', 'cast')"
          >
            角色
          </button>
          <button
            type="button"
            :class="{ active: boardMode === 'timeline' }"
            @click="emit('update:boardMode', 'timeline')"
          >
            时间线
          </button>
          <button
            type="button"
            :class="{ active: boardMode === 'qc' }"
            @click="emit('update:boardMode', 'qc')"
          >
            验收
          </button>
        </div>
        <h2>{{
          boardMode === 'script'
            ? '受影响镜头'
            : boardMode === 'cast'
              ? '角色卡'
              : boardMode === 'timeline'
                ? '镜序'
                : boardMode === 'qc'
                  ? '验收'
                  : '分镜'
        }}</h2>
        <template v-if="boardMode === 'cast'">
          <button
            v-for="char in characters"
            :key="char.id"
            type="button"
            class="drama-shot-item"
            :class="{ active: char.id === selectedCharacterId }"
            @click="emit('select-character', char.id)"
          >
            <span class="drama-shot-n">{{ (char.name || char.id).slice(0, 1) }}</span>
            <span class="drama-shot-body">
              <strong>{{ char.name || char.id }}</strong>
              <em>{{ char.look || '（未写外形）' }}</em>
            </span>
            <span class="drama-shot-flag">{{ char.ref_locked ? '锁图' : char.ref_exists ? '有图' : '无图' }}</span>
          </button>
          <button type="button" class="drama-shot-item drama-shot-item--add" @click="emit('add-character')">
            <span class="drama-shot-n">+</span>
            <span class="drama-shot-body"><strong>添加角色</strong></span>
          </button>
          <p v-if="!characters.length" class="drama-empty-hint">还没有角色卡。添加后写外形、绑音色，出图会按角色稳定下来。</p>
        </template>
        <template v-else-if="boardMode === 'timeline'">
          <button
            v-for="(shot, idx) in orderedShots"
            :key="shot.n"
            type="button"
            class="drama-shot-item drama-shot-item--draggable"
            :class="{ active: shot.n === selectedN }"
            draggable="true"
            @dragstart="onDragStart(shot.n)"
            @dragover="onDragOver"
            @drop="onDrop(shot.n)"
            @click="emit('select-shot', shot.n)"
          >
            <span class="drama-shot-n">{{ idx + 1 }}</span>
            <span class="drama-shot-body">
              <strong>Shot {{ shot.n }}</strong>
              <em>{{ shot.画面 || '（无画面描述）' }}</em>
            </span>
            <span class="drama-shot-flag">{{ tlLabel(shot) }}</span>
          </button>
          <p v-if="!orderedShots.length" class="drama-empty-hint">还没有可排的时间线镜头。</p>
          <p v-if="orderDirty" class="drama-empty-hint">镜序有未保存改动。</p>
        </template>
        <template v-else-if="boardMode === 'qc'">
          <button
            v-for="shot in shots"
            :key="shot.n"
            type="button"
            class="drama-shot-item"
            :class="{
              active: shot.n === selectedN,
              dirty: qcShotFlag(shot) === '待修' || qcShotFlag(shot) === 'skipped',
            }"
            @click="emit('select-shot', shot.n)"
          >
            <span class="drama-shot-n">{{ shot.n }}</span>
            <span class="drama-shot-body">
              <strong>Shot {{ shot.n }}</strong>
              <em>{{ shot.kind || shot.画面 || '（无画面描述）' }}</em>
            </span>
            <span class="drama-shot-flag">{{ qcShotFlag(shot) }}</span>
          </button>
          <p v-if="!shots.length" class="drama-empty-hint">还没有分镜可验收。</p>
        </template>
        <template v-else>
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
        <p v-else-if="boardMode === 'shots'" class="drama-empty-hint">
          <button type="button" class="btn-tiny" :disabled="saving || rendering" @click="emit('classify-shots')">
            按对白推断类型
          </button>
          <button type="button" class="btn-tiny" :disabled="saving || rendering" @click="emit('suggest-coverage')">
            导演建议
          </button>
        </p>
        <div v-if="boardMode === 'shots' && openSuggestions.length" class="drama-suggest-list">
          <article v-for="item in openSuggestions" :key="item.id" class="drama-suggest">
            <strong>{{ item.title }}</strong>
            <em>{{ item.reason }}</em>
            <div class="drama-suggest-actions">
              <button type="button" class="btn-tiny" :disabled="saving || rendering" @click="emit('apply-coverage', item.id)">
                采纳
              </button>
              <button type="button" class="btn-tiny" :disabled="saving || rendering" @click="emit('dismiss-coverage', item.id)">
                忽略
              </button>
              <button type="button" class="btn-tiny" :disabled="saving || rendering" @click="emit('lock-coverage', item.id)">
                锁定类型
              </button>
            </div>
          </article>
        </div>
        </template>
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

      <section v-else-if="boardMode === 'cast'" class="drama-preview">
        <div class="drama-stage">
          <img v-if="refPreviewUrl" class="drama-media" :src="refPreviewUrl" alt="角色参考图" />
          <div v-else class="drama-stage-empty">上传定妆图后，出图会按外形描述和配色锁定同一张脸</div>
        </div>
      </section>

      <section v-else-if="boardMode === 'qc'" class="drama-preview">
        <div class="drama-stage">
          <video
            v-if="episode?.play_url"
            :key="`${episode.play_url}-qc-${bust}`"
            class="drama-media"
            :src="episodePreviewUrl"
            controls
            playsinline
          />
          <div v-else class="drama-stage-empty">先拼整集再验收响度。单镜问题点左侧退回。</div>
        </div>
        <p class="drama-empty-hint" :class="episodeQc?.verdict === '通过' ? 'drama-qc-pass' : ''">
          整集 {{ episodeQc?.verdict || '待修' }}
          <template v-if="episodeQc?.block_reason"> · {{ episodeQc.block_reason }}</template>
        </p>
      </section>

      <section v-else-if="boardMode === 'timeline'" class="drama-preview">
        <div class="drama-preview-tabs">
          <button type="button" class="active">整集预览</button>
        </div>
        <div class="drama-stage">
          <video
            v-if="episode?.play_url"
            :key="`${episode.play_url}-${bust}`"
            class="drama-media"
            :src="episodePreviewUrl"
            controls
            playsinline
          />
          <div v-else class="drama-stage-empty">导出后在此预览整集 mp4</div>
        </div>
        <div v-if="timelineItems.length" class="drama-timeline-track">
          <span class="drama-timeline-rail-label">画面</span>
          <div
            v-for="item in timelineItems"
            :key="item.n"
            class="drama-timeline-block"
            :class="{ active: item.n === selectedN }"
            :style="{ flex: Math.max(item.play_duration || 1, 0.5) }"
            @click="emit('select-shot', item.n)"
          >
            <span>S{{ item.n }}</span>
            <em>{{ item.play_duration }}s</em>
          </div>
        </div>
        <div v-if="timelineItems.length" class="drama-timeline-track drama-timeline-track--bgm">
          <span class="drama-timeline-rail-label">BGM</span>
          <div
            class="drama-timeline-bgm"
            :class="{
              empty: !mix?.has_bgm,
              blocked: mixUnlicensed,
              licensed: mix?.has_bgm && !mixUnlicensed,
            }"
          >
            <span v-if="!mix?.has_bgm">无配乐（导出仅对白）</span>
            <span v-else-if="mixUnlicensed">{{ mix?.bgm?.title || 'BGM' }} · 无版权，禁止导出</span>
            <span v-else>{{ mix?.bgm?.title || 'BGM' }} · duck {{ mix?.bgm?.duck_db }} dB</span>
          </div>
        </div>
        <p v-if="episode?.timeline?.total_duration" class="drama-timeline-meta">
          整集约 {{ episode.timeline.total_duration }}s · BGM 只在导出/混音时叠上，不烧进各镜 clip
        </p>
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
        <div v-if="boardMode === 'shots' && selected" class="drama-candidates">
          <div class="drama-candidates-head">
            <h3>候选墙</h3>
            <div class="drama-candidates-actions">
              <button
                type="button"
                class="btn-tiny"
                :disabled="rendering || saving || shotFrozen || isLocked('scene')"
                @click="emit('generate-candidates')"
              >
                {{ rendering ? '出图中…' : '重抽 4 张' }}
              </button>
              <button
                type="button"
                class="btn-tiny"
                :disabled="rendering || saving || shotFrozen"
                @click="sceneInput?.click()"
              >
                手传覆盖
              </button>
            </div>
          </div>
          <input ref="sceneInput" class="drama-file" type="file" accept="image/*" @change="onSceneFile" />
          <p v-if="!(selected.candidates || []).length" class="drama-empty-hint">
            点「重抽 4 张」生成候选，点缩略图锁定画面（只换图，不重配音）。
          </p>
          <div v-else class="drama-candidate-grid">
            <button
              v-for="cand in selected.candidates"
              :key="cand.id"
              type="button"
              class="drama-candidate"
              :class="{ chosen: cand.chosen || selected.chosen === cand.id }"
              :disabled="rendering || saving || shotFrozen"
              @click="emit('choose-candidate', cand.id)"
            >
              <img v-if="candUrl(cand)" :src="candUrl(cand)" :alt="`候选 ${cand.id}`" />
              <span v-else class="drama-candidate-empty">无图</span>
              <em>{{ cand.id }}{{ cand.source === 'upload' ? ' · 手传' : '' }}</em>
            </button>
          </div>
        </div>
      </section>

      <section class="drama-inspector">
        <h2>{{
          boardMode === 'script'
            ? '剧本操作'
            : boardMode === 'cast'
              ? '角色卡'
              : boardMode === 'timeline'
                ? '时间线'
                : boardMode === 'qc'
                  ? '验收'
                  : '检查器'
        }}</h2>
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
        <template v-if="boardMode === 'cast'">
          <p v-if="!selectedCharacter" class="drama-empty-hint">左侧添加或选择一个角色。</p>
          <template v-else>
            <label>
              名字
              <input v-model="charDraft.name" type="text" />
            </label>
            <label>
              id
              <input v-model="charDraft.id" type="text" :disabled="Boolean(selectedCharacterId)" />
            </label>
            <label>
              外形（写入每镜 prompt）
              <textarea v-model="charDraft.look" rows="3" placeholder="金箍、火眼金睛、虎皮裙、如意金箍棒…" />
            </label>
            <label>
              配色
              <input v-model="charDraft.colors" type="text" placeholder="金、赤、青绿" />
            </label>
            <label>
              别名（对白匹配）
              <input v-model="charDraft.aliases" type="text" placeholder="悟空、齐天大圣" />
            </label>
            <label>
              音色
              <select v-model="charDraft.voice">
                <option v-for="voice in voices" :key="voice.id" :value="voice.id">{{ voice.label }}</option>
              </select>
            </label>
            <div class="drama-freeze">
              <button type="button" class="btn-tiny" :disabled="saving" @click="refInput?.click()">
                上传参考图
              </button>
              <button type="button" class="btn-tiny" :disabled="saving || !selectedCharacter.ref_exists" @click="emit('lock-ref')">
                {{ selectedCharacter.ref_locked ? '解锁参考图' : '锁定参考图' }}
              </button>
              <span>{{ selectedCharacter.ref_locked ? '已锁，不会被覆盖' : '锁住后不能替换定妆图' }}</span>
            </div>
            <input ref="refInput" class="drama-file" type="file" accept="image/*" @change="onRefFile" />
            <div class="drama-actions">
              <button type="button" class="btn-primary" :disabled="saving" @click="emit('save-character')">
                {{ saving ? '保存中…' : '保存角色卡' }}
              </button>
              <button type="button" class="btn-ghost" :disabled="saving" @click="emit('delete-character')">
                删除
              </button>
            </div>
          </template>
        </template>
        <template v-else-if="boardMode === 'timeline'">
          <label>
            曲库
            <select v-model="mixDraft.catalog_id" :disabled="saving || !catalogTracks.length">
              <option value="">{{ catalogTracks.length ? '不选曲库（用手传）' : '项目尚无曲库条目' }}</option>
              <option v-for="track in catalogTracks" :key="track.id" :value="track.id">
                {{ track.title || track.id }}
              </option>
            </select>
          </label>
          <div class="drama-freeze">
            <button type="button" class="btn-tiny" :disabled="saving || rendering" @click="bgmInput?.click()">
              上传 BGM
            </button>
            <button type="button" class="btn-tiny" :disabled="saving || !mix?.has_bgm" @click="emit('clear-bgm')">
              清除
            </button>
            <span>{{ mix?.bgm?.title || '未挂配乐' }}</span>
          </div>
          <input ref="bgmInput" class="drama-file" type="file" accept="audio/*" @change="onBgmFile" />
          <label class="drama-check">
            <input v-model="mixDraft.license_ok" type="checkbox" />
            我有商用权
          </label>
          <p v-if="mixUnlicensed" class="drama-empty-hint drama-warn">
            {{ mix?.license?.reason || '没有 license 的曲子禁止导出' }}
          </p>
          <audio v-if="bgmPreviewUrl" class="drama-audio" :src="bgmPreviewUrl" controls />
          <label>
            BGM 音量
            <input v-model.number="mixDraft.volume" type="range" min="0" max="1" step="0.02" />
            <span>{{ mixDraft.volume }}</span>
          </label>
          <label>
            对白 duck（dB）
            <input v-model.number="mixDraft.duck_db" type="range" min="-24" max="0" step="1" />
            <span>{{ mixDraft.duck_db }}</span>
          </label>
          <p class="drama-empty-hint">音效点（SFX）本刀仅占位，mix.json 可写空数组。</p>
          <div class="drama-actions">
            <button type="button" class="btn-ghost" :disabled="saving || !mixDirty" @click="emit('save-mix')">
              {{ saving ? '保存中…' : '保存混音' }}
            </button>
            <button
              type="button"
              class="btn-ghost"
              :disabled="rendering || saving || mixUnlicensed"
              @click="emit('apply-mix')"
            >
              {{ rendering ? '混音中…' : '应用混音' }}
            </button>
          </div>
          <p v-if="!selected" class="drama-empty-hint">选一条镜头改切点、转场或音量。</p>
          <template v-else>
            <div class="drama-actions drama-actions--script">
              <button type="button" class="btn-ghost" :disabled="saving" @click="emit('move-timeline-shot', selected.n, -1)">
                上移
              </button>
              <button type="button" class="btn-ghost" :disabled="saving" @click="emit('move-timeline-shot', selected.n, 1)">
                下移
              </button>
              <button type="button" class="btn-ghost" :disabled="saving || !orderDirty" @click="emit('save-timeline-order')">
                保存镜序
              </button>
            </div>
            <label>
              尾部裁切（秒）
              <input v-model.number="tlDraft.trim_out" type="number" min="0" step="0.1" />
            </label>
            <label>
              头部裁切（秒）
              <input v-model.number="tlDraft.trim_in" type="number" min="0" step="0.1" />
            </label>
            <label>
              音量
              <input v-model.number="tlDraft.volume" type="range" min="0" max="2" step="0.05" />
              <span>{{ tlDraft.volume }}</span>
            </label>
            <label>
              到下镜转场
              <select v-model="tlDraft.transition">
                <option v-for="t in transitions" :key="t" :value="t">{{ t }}</option>
              </select>
            </label>
            <p class="drama-empty-hint">
              源 clip {{ tlItem(selected.n)?.source_duration || selected.duration }}s → 时间线
              {{ tlItem(selected.n)?.play_duration || '?' }}s
            </p>
            <div class="drama-actions">
              <button
                type="button"
                class="btn-primary"
                :disabled="saving || (!timelineDirty && !orderDirty)"
                @click="emit('save-timeline-all')"
              >
                {{ saving ? '保存中…' : '保存时间线' }}
              </button>
              <button
                type="button"
                class="btn-ghost"
                :disabled="rendering || saving || mixUnlicensed"
                @click="emit('export-timeline')"
              >
                {{ rendering ? '导出中…' : '导出整集' }}
              </button>
            </div>
          </template>
          <div v-if="!selected" class="drama-actions">
            <button
              type="button"
              class="btn-ghost"
              :disabled="rendering || saving || mixUnlicensed"
              @click="emit('export-timeline')"
            >
              {{ rendering ? '导出中…' : '导出整集' }}
            </button>
          </div>
        </template>
        <template v-else-if="boardMode === 'qc'">
          <p class="drama-empty-hint" :class="episodeQc?.verdict === '通过' ? 'drama-qc-pass' : ''">
            整集 {{ episodeQc?.verdict || '待修' }}
            · 通过 {{ episodeQc?.summary?.passed ?? 0 }}
            / 未过 {{ episodeQc?.summary?.failed ?? 0 }}
            / skipped {{ episodeQc?.summary?.skipped ?? 0 }}
          </p>
          <p v-if="episodeQc?.block_reason && episodeQc?.verdict !== '通过'" class="drama-empty-hint drama-qc-skip">
            {{ episodeQc.block_reason }}
          </p>
          <div class="drama-qc-grid">
            <div class="drama-qc-row">
              <span>身份</span>
              <em :class="qcCheckClass(selectedQcRow?.identity)">{{ qcCheckLabel(selectedQcRow?.identity) }}</em>
            </div>
            <p v-if="selectedQcRow?.identity?.hint" class="drama-empty-hint">{{ selectedQcRow.identity.hint }}</p>
            <div class="drama-qc-row">
              <span>口型</span>
              <em :class="qcCheckClass(selectedQcRow?.lip)">{{ qcCheckLabel(selectedQcRow?.lip) }}</em>
            </div>
            <p v-if="selectedQcRow?.lip?.hint" class="drama-empty-hint">{{ selectedQcRow.lip.hint }}</p>
            <div class="drama-qc-row">
              <span>闪烁</span>
              <em :class="qcCheckClass(selectedQcRow?.flicker)">{{ qcCheckLabel(selectedQcRow?.flicker) }}</em>
            </div>
            <p v-if="selectedQcRow?.flicker?.hint" class="drama-empty-hint">{{ selectedQcRow.flicker.hint }}</p>
            <div class="drama-qc-row">
              <span>响度</span>
              <em :class="qcCheckClass(episodeQc?.loudness)">{{ qcCheckLabel(episodeQc?.loudness) }}</em>
            </div>
            <p v-if="episodeQc?.loudness?.hint" class="drama-empty-hint">{{ episodeQc.loudness.hint }}</p>
            <p v-if="episodeQc?.loudness?.lufs != null" class="drama-empty-hint">
              {{ episodeQc.loudness.lufs }} LUFS（目标 {{ episodeQc.loudness.lufs_target }}）
            </p>
          </div>
          <div class="drama-actions">
            <button type="button" class="btn-primary" :disabled="rendering || saving" @click="emit('qc-episode')">
              {{ rendering ? '验收中…' : '跑验收' }}
            </button>
            <button
              type="button"
              class="btn-ghost"
              :disabled="rendering || saving || !episodeQc?.can_pass"
              @click="emit('pass-episode-qc')"
            >
              通过
            </button>
            <button
              type="button"
              class="btn-ghost"
              :disabled="rendering || saving || !selected"
              @click="emit('reject-shot-qc')"
            >
              退回本镜
            </button>
            <button type="button" class="btn-ghost" :disabled="rendering || saving" @click="emit('remix-loudness')">
              重混音
            </button>
          </div>
          <p class="drama-empty-hint">skipped 不能点通过。响度不达标只重 mix，不重渲各镜 clip。</p>
        </template>
        <template v-else-if="selected">
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
          <div v-if="boardMode === 'shots'" class="drama-roles">
            <span>本镜角色</span>
            <p v-if="!characters.length" class="drama-empty-hint">先到角色页建卡，再勾选本镜出场人物。</p>
            <label v-for="char in characters" :key="char.id" class="drama-role-chip">
              <input
                type="checkbox"
                :checked="isRoleOn(char.id)"
                :disabled="shotFrozen || saving"
                @change="emit('toggle-role', char.id)"
              />
              {{ char.name }}
            </label>
            <em v-if="boundVoice">配音：{{ boundVoice }}</em>
          </div>
          <label>
            镜头类型
            <select v-model="draft.kind" :disabled="kindLocked || saving">
              <option v-for="k in shotKinds" :key="k" :value="k">{{ kindLabel(k) }}</option>
            </select>
            <button
              type="button"
              class="btn-tiny"
              :disabled="saving || rendering || shotFrozen"
              @click="emit('toggle-lock', 'kind')"
            >
              {{ kindLocked && !shotFrozen ? '解锁类型' : '锁定类型' }}
            </button>
          </label>
          <label>
            景别
            <select v-model="draft.size" :disabled="kindLocked || saving">
              <option v-for="s in shotSizes" :key="s" :value="s">{{ s }}</option>
            </select>
          </label>
          <label>
            说话人 speaker
            <select v-model="draft.speaker" :disabled="shotFrozen || saving">
              <option value="">（未指定）</option>
              <option v-for="char in characters" :key="char.id" :value="char.id">{{ char.name }}</option>
            </select>
          </label>
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
          <label>
            I2V 运动
            <select v-model="draft.i2v" :disabled="shotFrozen || isLocked('clip')">
              <option v-for="mode in i2vModes" :key="mode" :value="mode">
                {{ mode === 'off' ? '关闭' : mode === 'auto' ? '自动（锁画面后）' : '始终开启' }}
              </option>
            </select>
          </label>
          <p v-if="boardMode === 'shots'" class="drama-empty-hint">{{ i2vSourceLabel }}</p>
          <div v-if="boardMode === 'shots'" class="drama-actions">
            <button
              type="button"
              class="btn-ghost"
              :disabled="rendering || saving || !canGenerateI2v"
              @click="emit('generate-i2v')"
            >
              {{ rendering ? '处理中…' : '生成 I2V' }}
            </button>
            <button
              type="button"
              class="btn-ghost"
              :disabled="rendering || saving || !canGenerateLip"
              @click="emit('generate-lip')"
            >
              {{ rendering ? '处理中…' : '生成口型' }}
            </button>
            <button
              type="button"
              class="btn-ghost"
              :disabled="rendering || saving || !canGenerateKeys"
              @click="emit('generate-keys')"
            >
              {{ rendering ? '处理中…' : '生成关键帧' }}
            </button>
            <button
              type="button"
              class="btn-ghost"
              :disabled="rendering || saving || !selected"
              @click="emit('qc-shot')"
            >
              {{ rendering ? '处理中…' : '抽检身份' }}
            </button>
          </div>
          <p v-if="boardMode === 'shots'" class="drama-empty-hint" :class="identityClass">{{ identityLabel }}</p>
          <p v-if="boardMode === 'shots' && !canGenerateKeys && selected?.keys_gate?.reason" class="drama-empty-hint">
            {{ selected.keys_gate.reason }}
          </p>
          <div v-if="boardMode === 'shots' && (selected?.keys || []).length" class="drama-keys">
            <h3 class="drama-layers-title">姿态关键帧</h3>
            <div class="drama-keys-strip">
              <button
                v-for="key in selected.keys"
                :key="key.id"
                type="button"
                class="drama-key"
                :class="{ active: selectedKey?.id === key.id, locked: key.locked }"
                @click="selectedKeyId = key.id"
              >
                <img v-if="keyUrl(key)" :src="keyUrl(key)" :alt="key.pose" />
                <span v-else class="drama-candidate-empty">无图</span>
                <em>{{ key.pose }} · {{ key.t }}s{{ key.locked ? ' · 锁' : '' }}</em>
              </button>
            </div>
            <input ref="keyInput" class="drama-file" type="file" accept="image/*" @change="onKeyFile" />
            <div v-if="selectedKey" class="drama-actions">
              <button
                type="button"
                class="btn-tiny"
                :disabled="saving || rendering || selectedKey.locked"
                @click="keyInput?.click()"
              >
                手传姿态
              </button>
              <button
                type="button"
                class="btn-tiny"
                :disabled="saving || rendering"
                @click="emit('lock-key', selectedKey.id, !selectedKey.locked)"
              >
                {{ selectedKey.locked ? '解锁姿态' : '锁定姿态' }}
              </button>
            </div>
            <div v-if="selectedKey?.candidates?.length" class="drama-candidate-grid drama-key-cands">
              <button
                v-for="cand in selectedKey.candidates"
                :key="cand.id"
                type="button"
                class="drama-candidate"
                :class="{ chosen: cand.chosen || selectedKey.chosen === cand.id }"
                :disabled="rendering || saving || selectedKey.locked || shotFrozen"
                @click="emit('choose-key', selectedKey.id, cand.id)"
              >
                <img v-if="candUrl(cand)" :src="candUrl(cand)" :alt="cand.id" />
                <span v-else class="drama-candidate-empty">无图</span>
                <em>{{ cand.id }}{{ cand.source === 'upload' ? ' · 手传' : '' }}</em>
              </button>
            </div>
          </div>
          <p v-if="boardMode === 'shots' && i2vCostLabel" class="drama-empty-hint">{{ i2vCostLabel }}</p>
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
          {{
            boardMode === 'script'
              ? '可先保存剧本生成分镜，再选镜头锁定整镜。'
              : boardMode === 'cast'
                ? '添加角色卡，写外形并锁定参考图。'
                : boardMode === 'timeline'
                  ? '拖拽左侧镜序，或选中镜头改切点与转场。'
                  : boardMode === 'qc'
                    ? '先跑验收。skipped 不能点通过；响度只重 mix。'
                    : '选择左侧一个镜头。'
          }}
        </p>
      </section>
    </div>

    <div v-else class="drama-idle">
      <h2>分镜台</h2>
      <p>从左侧打开一个漫剧项目。分镜页可重抽候选、对已锁画面生成 I2V；时间线页改镜序/切点/转场后导出整集，不覆盖各镜 clip。</p>
    </div>
  </main>
</template>
