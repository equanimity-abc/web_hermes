<script setup>
import { computed, nextTick, ref, watch } from 'vue'
import DramaThumbImg from '@/components/drama/DramaThumbImg.vue'
import DramaCastChat from '@/components/drama/DramaCastChat.vue'

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
  castChatMessages: { type: Array, default: () => [] },
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
  presets: { type: Array, default: () => [] },
  currentPreset: { type: String, default: 'balanced' },
  degradedProviders: { type: Array, default: () => [] },
  configNodeList: { type: Array, default: () => [] },
  selectedConfigNode: { type: String, default: 'script' },
  configNodeDraft: { type: String, default: '' },
  selectedShotIds: { type: Array, default: () => [] },
  snapshots: { type: Array, default: () => [] },
  snapshotsOpen: { type: Boolean, default: false },
  budget: { type: Object, default: null },
  budgetBlocked: { type: Boolean, default: false },
  budgetWarn: { type: Boolean, default: false },
  budgetDraft: { type: Object, required: true },
  budgetOpen: { type: Boolean, default: false },
  qcChecklist: { type: Object, default: null },
  checklistOpen: { type: Boolean, default: false },
  rejectingAll: { type: Boolean, default: false },
})

const emit = defineEmits([
  'open-episode',
  'select-shot',
  'save',
  'rerender',
  'rerender-layer',
  'toggle-lock',
  'update:scriptDraft',
  'update:boardMode',
  'preview-script',
  'save-script',
  'generate-script',
  'rerender-dirty',
  'select-character',
  'add-character',
  'save-character',
  'lock-ref',
  'upload-ref',
  'delete-character',
  'delete-candidate',
  'generate-character-ref',
  'refine-character-ref',
  'generate-all-refs',
  'toggle-role',
  'generate-candidates',
  'choose-candidate',
  'upload-scene',
  'generate-i2v',
  'generate-all-video',
  'generate-lip',
  'generate-all-voice',
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
  'apply-style',
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
  'apply-preset',
  'select-config-node',
  'save-config-node',
  'toggle-shot-selected',
  'clear-shot-selection',
  'select-all-shots',
  'apply-batch-edit',
  'toggle-snapshots',
  'restore-snapshot',
  'delete-snapshot',
  'toggle-budget',
  'save-budget',
  'toggle-checklist',
  'refresh-checklist',
  'reject-all-qc',
])

const stage = ref('script')
const premise = ref('')
const refInput = ref(null)
const sceneInput = ref(null)
const keyInput = ref(null)
const bgmInput = ref(null)
const selectedKeyId = ref(null)
const addMenuOpen = ref(false)
/** 点击候选后立即反映到 shot 缩略图，不等待 API */
const localChosen = ref({})
/** 候选图大图预览（仅分镜画面步骤） */
const candidatePreview = ref(null)
const castChatRef = ref(null)

const hasLayer = (layer) => (props.shots || []).some((s) => s.files?.[layer]?.exists)

const stageList = computed(() => [
  { id: 'script', label: '剧本', title: '步骤一：一句话生成完整剧本与分镜', done: Boolean(props.episode?.script) },
  { id: 'cast', label: '角色', title: '步骤二：文生图生成定妆图，定角色、物品、场景', done: (props.characters || []).some((c) => c.ref_exists) },
  { id: 'scene', label: '画面', title: '步骤三：分镜文生图与候选墙锁图', done: hasLayer('scene') },
  { id: 'video', label: '视频', title: '步骤四：图生视频（I2V 运动）', done: hasLayer('motion') || (props.shots || []).some((s) => ['ai', 'keys', 'fallback'].includes(s.i2v_source)) },
  { id: 'voice', label: '声音', title: '步骤五：配音与口型', done: hasLayer('voice') },
  { id: 'assemble', label: '成片', title: '步骤六：拼接、BGM 与导出', done: Boolean(props.episode?.play_url) },
])

const castCategory = ref('character')
const CAST_TABS = [
  { id: 'character', label: '角色' },
  { id: 'prop', label: '物品' },
  { id: 'scene', label: '场景' },
]
const CAST_REF_SIZES = [
  { value: 640, hint: '640×640' },
  { value: 1024, hint: '1024×1024' },
  { value: 1980, hint: '1980×1980' },
]
const CAST_REF_MODELS = [
  { provider: 'kling-image', model: 'kling/kling-v3-omni-image-generation', label: '可灵 · Kling V3 Omni' },
  { provider: 'wanx', model: 'qwen-image-plus', label: '百炼 · Qwen-Image-Plus' },
]

const charRefModelKey = computed({
  get() {
    const p = props.charDraft.ref_image_provider || 'kling-image'
    const m = props.charDraft.ref_image_model || 'kling/kling-v3-omni-image-generation'
    return `${p}|${m}`
  },
  set(v) {
    const [provider, model] = String(v || '').split('|')
    const hit = CAST_REF_MODELS.find((o) => o.provider === provider && o.model === model)
    if (hit) {
      props.charDraft.ref_image_provider = hit.provider
      props.charDraft.ref_image_model = hit.model
    }
  },
})

const castAssets = computed(() =>
  (props.characters || []).filter((c) => (c.category || 'character') === castCategory.value),
)

const castAddLabel = computed(() => {
  const map = { character: '添加角色', prop: '添加物品', scene: '添加场景' }
  return map[castCategory.value] || '添加'
})

function castAssetUrl(url) {
  if (!url) return ''
  return `${url}${url.includes('?') ? '&' : '?'}_=${props.bust || 0}`
}

function fullAssetUrl(url) {
  return castAssetUrl(url)
}

function onAddCastAsset() {
  const names = { character: '新角色', prop: '新物品', scene: '新场景' }
  emit('add-character', {
    category: castCategory.value,
    name: names[castCategory.value] || '新资产',
  })
}

function onGenerateAllCastRefs() {
  emit('generate-all-refs', castCategory.value)
}

function onCastChatSend(instruction) {
  const char = props.selectedCharacter
  if (!char?.id || char.ref_locked) return
  emit('refine-character-ref', char.id, instruction)
}

watch(
  () => props.castChatMessages.length,
  () => nextTick(() => castChatRef.value?.scrollToBottom?.()),
)

watch(castCategory, () => {
  const ids = new Set(castAssets.value.map((c) => c.id))
  if (props.selectedCharacterId && ids.has(props.selectedCharacterId)) return
  emit('select-character', castAssets.value[0]?.id || null)
})

const stageBoardMap = {
  script: 'script',
  cast: 'cast',
  scene: 'shots',
  video: 'shots',
  voice: 'shots',
  assemble: 'timeline',
}
const stageIndex = computed(() => stageList.value.findIndex((s) => s.id === stage.value))
const currentStage = computed(() => stageList.value[stageIndex.value] || stageList.value[0])
const nextStage = computed(() => stageList.value[stageIndex.value + 1] || null)

function goStage(id) {
  stage.value = id
  emit('update:boardMode', stageBoardMap[id] || 'shots')
}
function goNext() {
  if (nextStage.value) goStage(nextStage.value.id)
}

const previewUrl = computed(() => {
  const shot = props.selected
  const url = shot?.files?.clip?.url || shot?.files?.scene?.url || shot?.preview_url || ''
  if (!url) return ''
  return `${url}${url.includes('?') ? '&' : '?'}_=${props.bust || 0}`
})
const episodePreviewUrl = computed(() => {
  const url = props.episode?.play_url || ''
  if (!url) return ''
  return `${url}${url.includes('?') ? '&' : '?'}_=${props.bust || 0}`
})
const previewKind = computed(() => {
  const url = previewUrl.value
  if (!url) return 'empty'
  return url.includes('.mp4') ? 'video' : 'image'
})
const refPreviewUrl = computed(() => {
  const url = props.selectedCharacter?.ref_url || ''
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

const THUMB = 240
const preloaded = new Set()
function thumbUrl(url) {
  if (!url) return ''
  const s = String(url)
  // 工作区文件 URL 是 /api/workspace/file?path=...，扩展名在 path 参数里
  const m = /[?&]path=([^&]+)/.exec(s)
  const tail = m ? decodeURIComponent(m[1]) : s
  if (!/\.(png|jpe?g|gif|webp)([?#]|$)/i.test(tail)) return s
  return `${s}${s.includes('?') ? '&' : '?'}size=${THUMB}`
}
function assetThumb(url) {
  return thumbUrl(url)
}
function candUrl(cand) {
  return assetThumb(cand?.url || '')
}
function shotChosenId(shot) {
  if (!shot) return ''
  const local = localChosen.value[shot.n]
  if (local) return String(local)
  return String(shot.chosen || '').trim()
}
function shotThumb(shot) {
  if (!shot) return ''
  const chosenId = shotChosenId(shot)
  if (chosenId) {
    const cand = (shot.candidates || []).find((c) => String(c.id) === chosenId)
    if (cand?.url) return assetThumb(cand.url)
  }
  return assetThumb(shot?.files?.scene?.url || shot?.preview_url || '')
}
function candidateUrls(shot) {
  return (shot?.candidates || []).map((c) => candUrl(c)).filter(Boolean)
}
function preloadImage(url) {
  if (!url || preloaded.has(url)) return
  preloaded.add(url)
  const img = new Image()
  img.decoding = 'async'
  img.src = url
}
function preloadShotCandidates(shot) {
  for (const url of candidateUrls(shot)) preloadImage(url)
}
function shotStatusLabel(shot) {
  const locked = shot.locked || []
  if (locked.includes('shot')) return '锁'
  if ((shot.dirty || []).length) return '脏'
  if (shot.files?.clip?.exists) return '成'
  if (shot.files?.scene?.exists) return '图'
  return '待'
}
function shotStatusClass(shot) {
  const locked = shot.locked || []
  if (locked.includes('shot')) return 'is-locked'
  if ((shot.dirty || []).length) return 'is-dirty'
  if (shot.files?.clip?.exists) return 'is-done'
  if (shot.files?.scene?.exists) return 'is-scene'
  return 'is-todo'
}
function isLocked(layer) {
  return (props.selected?.locked || []).includes(layer)
}
const shotFrozen = computed(() => isLocked('shot'))
const candidatesFull = computed(() => (props.selected?.candidates || []).length >= 4)
const canAddCandidate = computed(() => !candidatesFull.value)
const canGenerateI2v = computed(() => {
  const shot = props.selected
  if (!shot) return false
  if ((shot.route && shot.route.will_run === false) || shot.route?.ladder === 'L0') return false
  const mode = props.draft?.i2v || shot.i2v || 'auto'
  if (mode === 'off') return false
  if (mode === 'on') return true
  return (shot.locked || []).includes('scene') || shotFrozen.value
})
const canGenerateLip = computed(() => Boolean(props.selected?.lip?.ok || props.selected?.lip?.will_run))
const canGenerateKeys = computed(() => Boolean(props.selected?.keys_gate?.ok || props.selected?.keys_gate?.will_run))
const selectedKey = computed(() => {
  const keys = props.selected?.keys || []
  return keys.find((k) => k.id === selectedKeyId.value) || keys[0] || null
})
const identityLabel = computed(() => {
  const id = props.selected?.identity
  if (!id) return props.selected?.identity_hint || '尚未抽检身份'
  if (id.status === 'skipped') return id.hint || '身份未出分'
  const score = id.cosine == null ? '—' : Number(id.cosine).toFixed(2)
  return id.pass ? `身份 ${score} 通过` : `身份 ${score} 未通过`
})
const identityClass = computed(() => {
  const id = props.selected?.identity
  if (!id) return ''
  if (id.status === 'skipped') return 'drama-qc-skip'
  if (id.status === 'ok' && id.pass) return 'drama-qc-pass'
  return 'drama-qc-fail'
})
const i2vSourceLabel = computed(() => {
  const src = props.selected?.i2v_source || ''
  if (src === 'ai') return '已生成 I2V 运动'
  if (src === 'keys') return '已用关键帧补间'
  if (src === 'fallback') return '已回退静图运镜'
  return '尚未生成视频'
})

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
function onBgmFile(ev) {
  const file = ev.target.files?.[0]
  ev.target.value = ''
  if (file) emit('upload-bgm', file, Boolean(props.mixDraft.license_ok))
}
function onKeyFile(ev) {
  const file = ev.target.files?.[0]
  ev.target.value = ''
  const kid = selectedKey.value?.id
  if (file && kid) emit('upload-key', kid, file)
}
function onGenerateScript() {
  emit('generate-script', premise.value)
}

function onEpisodeChange(event) {
  const n = Number(event.target.value)
  if (n && n !== props.episodeN) {
    emit('open-episode', n)
  }
}

// 切换镜头时收起「＋」菜单，并预加载候选缩略图
watch(
  () => props.shots,
  (rows) => {
    const next = { ...localChosen.value }
    let changed = false
    for (const shot of rows || []) {
      const cid = String(shot.chosen || '').trim()
      if (cid && next[shot.n] !== cid) {
        next[shot.n] = cid
        changed = true
      }
      preloadShotCandidates(shot)
      const sceneUrl = assetThumb(shot?.files?.scene?.url || shot?.preview_url || '')
      if (sceneUrl) preloadImage(sceneUrl)
    }
    if (changed) localChosen.value = next
  },
  { deep: true },
)
watch(
  () => props.selectedN,
  () => {
    addMenuOpen.value = false
  },
)
watch(
  () => props.selected,
  (shot) => {
    if (shot) preloadShotCandidates(shot)
  },
  { immediate: true },
)

function onUploadCandidate() {
  addMenuOpen.value = false
  sceneInput.value?.click()
}
function onGenerateCandidate() {
  addMenuOpen.value = false
  const left = 4 - (props.selected?.candidates || []).length
  emit('generate-candidates', Math.max(1, left))
}
function onChooseCandidate(cid) {
  if (!props.selectedN || !cid) return
  const cand = (props.selected?.candidates || []).find((c) => String(c.id) === String(cid))
  if (cand) preloadImage(candUrl(cand))
  localChosen.value = { ...localChosen.value, [props.selectedN]: cid }
  emit('choose-candidate', cid)
}
function openShotCandidatePreview(cand) {
  if (!cand?.url) return
  candidatePreview.value = {
    id: cand.id,
    url: cand.url,
    label: `Shot ${props.selected?.n} · ${cand.id}`,
    locked: props.rendering || shotFrozen.value,
  }
}
function closeCandidatePreview() {
  candidatePreview.value = null
}
function confirmCandidatePreview() {
  const preview = candidatePreview.value
  if (!preview || preview.locked) return
  onChooseCandidate(preview.id)
  closeCandidatePreview()
}
function isCandidateChosen(cand) {
  if (!props.selected) return false
  const id = String(cand?.id || '')
  return Boolean(cand?.chosen || shotChosenId(props.selected) === id)
}
</script>

<template>
  <main class="drama-studio">
    <header class="drama-top">
      <div class="drama-top-head">
        <div class="drama-top-title">
          <h1>{{ project?.project?.title || '漫剧工作台' }}</h1>
        </div>
        <div v-if="episodes.length" class="drama-ep-select">
          <label class="drama-ep-label">
            <span class="drama-ep-label-text">集数</span>
            <select class="drama-ep-dropdown" :value="episodeN" @change="onEpisodeChange">
              <option v-for="ep in episodes" :key="ep.n" :value="ep.n">
                第{{ ep.n }}集 · EP{{ String(ep.n).padStart(2, '0') }}
              </option>
            </select>
          </label>
        </div>
      </div>
    </header>

    <!-- 6 阶段线性步进器 + 下一步 -->
    <div v-if="project" class="drama-stepper">
      <div class="drama-stepper-steps">
        <button
          v-for="(st, idx) in stageList"
          :key="st.id"
          type="button"
          class="drama-step"
          :class="{ active: st.id === stage, done: st.done, passed: idx < stageIndex }"
          @click="goStage(st.id)"
        >
          <span class="drama-step-idx">{{ st.done ? '✓' : idx + 1 }}</span>
          <span class="drama-step-label">{{ st.label }}</span>
        </button>
      </div>
      <div class="drama-stepper-actions">
        <button v-if="nextStage" type="button" class="btn-primary" @click="goNext">下一步：{{ nextStage.label }}</button>
        <button v-else type="button" class="btn-ghost" @click="emit('export-timeline')">重新导出</button>
      </div>
    </div>

    <div v-if="project" class="drama-stage-title">
      <h2>{{ currentStage.title }}</h2>
    </div>

    <div v-if="project" class="drama-flow">
      <!-- ============ 阶段 1：剧本 ============ -->
      <section v-if="stage === 'script'" class="drama-stage-panel drama-script-stage">
        <div class="drama-panel-body drama-script-panels">
          <div class="drama-script-panel drama-script-panel--generate">
            <div class="drama-script-panel-inner">
              <textarea
                v-model="premise"
                class="drama-script-premise"
                rows="2"
                placeholder="输入一句话故事梗概，例如：被赶出家门的豪门养女，重生回到三年前复仇翻盘。"
              />
              <button
                type="button"
                class="btn-primary drama-script-generate-btn"
                :disabled="saving || rendering || !premise.trim()"
                @click="onGenerateScript"
              >
                {{ saving ? '生成中…' : '生成剧本' }}
              </button>
            </div>
          </div>

          <div class="drama-script-panel drama-script-panel--edit">
            <div class="drama-script-panel-head">
              <span class="drama-script-panel-title">剧本（生成后可手动微调）</span>
            </div>
            <div class="drama-script-panel-inner drama-script-panel-inner--edit">
              <textarea
                class="drama-script-editor"
                :value="scriptDraft"
                spellcheck="false"
                rows="16"
                placeholder="# EP01 标题&#10;- 时长: 45s&#10;## 分镜&#10;### Shot 1 (0-3s)"
                @input="emit('update:scriptDraft', $event.target.value)"
              />
              <div class="drama-script-panel-actions">
                <button
                  type="button"
                  class="btn-ghost"
                  :disabled="saving || rendering || !scriptDraft.trim()"
                  @click="emit('save-script')"
                >
                  {{ saving ? '保存中…' : '保存剧本' }}
                </button>
              </div>
            </div>
          </div>
        </div>
      </section>

      <!-- ============ 阶段 2：定妆资产 ============ -->
      <section v-else-if="stage === 'cast'" class="drama-stage-panel drama-cast-stage">
        <div class="drama-panel-body drama-cast-layout">
          <div class="drama-cast-sidebar">
            <div class="drama-cast-tabs">
              <button
                v-for="tab in CAST_TABS"
                :key="tab.id"
                type="button"
                class="drama-cast-tab"
                :class="{ active: tab.id === castCategory }"
                @click="castCategory = tab.id"
              >
                {{ tab.label }}
              </button>
            </div>
            <div class="drama-cast-toolbar">
              <button type="button" class="btn-ghost btn-sm" :disabled="saving" @click="onAddCastAsset">{{ castAddLabel }}</button>
              <button type="button" class="btn-ghost btn-sm" :disabled="rendering" @click="onGenerateAllCastRefs">
                {{ rendering ? '生成中…' : '批量生成' }}
              </button>
            </div>
            <div class="drama-cast-list">
              <div v-if="castCategory === 'character'" class="drama-cast-rows">
                <button
                  v-for="item in castAssets"
                  :key="item.id"
                  type="button"
                  class="drama-cast-row"
                  :class="{ active: item.id === selectedCharacterId, locked: item.ref_locked }"
                  @click="emit('select-character', item.id)"
                >
                  <div class="drama-cast-avatar">
                    <img v-if="item.ref_url" :src="castAssetUrl(item.ref_url)" :alt="item.name" />
                    <span v-else class="drama-cast-avatar-empty">{{ (item.name || item.id || '?').slice(0, 1) }}</span>
                  </div>
                  <span class="drama-cast-row-name">{{ item.name || item.id }}</span>
                  <span v-if="item.ref_locked" class="drama-cast-row-lock" title="已锁定">🔒</span>
                </button>
              </div>
              <div v-else class="drama-cast-folder-grid">
                <button
                  v-for="item in castAssets"
                  :key="item.id"
                  type="button"
                  class="drama-cast-card"
                  :class="{ active: item.id === selectedCharacterId, locked: item.ref_locked }"
                  @click="emit('select-character', item.id)"
                >
                  <div class="drama-cast-thumb">
                    <img v-if="item.ref_url" :src="castAssetUrl(item.ref_url)" :alt="item.name" />
                    <span v-else class="drama-candidate-empty">无图</span>
                  </div>
                  <span class="drama-cast-name">{{ item.name || item.id }}</span>
                  <span v-if="item.ref_locked" class="drama-cast-lock" title="已锁定">🔒</span>
                </button>
              </div>
              <p v-if="!castAssets.length" class="drama-empty-hint">暂无{{ CAST_TABS.find((t) => t.id === castCategory)?.label }}，点击上方添加。</p>
            </div>
          </div>

          <div v-if="selectedCharacter && (selectedCharacter.category || 'character') === castCategory" class="drama-cast-detail">
            <div class="drama-cast-detail-head">
              <h3>{{ selectedCharacter.name || selectedCharacter.id }}</h3>
              <div class="drama-cast-detail-actions">
                <button type="button" class="btn-primary btn-sm" :disabled="saving" @click="emit('save-character')">保存</button>
                <button type="button" class="btn-tiny" :disabled="saving || rendering || selectedCharacter.ref_locked" @click="emit('generate-character-ref', selectedCharacter.id)">
                  {{ saving ? '生成中…' : '生成定妆图' }}
                </button>
                <button type="button" class="btn-tiny" :disabled="saving || !selectedCharacter.ref_exists" @click="emit('lock-ref', selectedCharacter.id)">
                  {{ selectedCharacter.ref_locked ? '解锁' : '锁定' }}
                </button>
                <button type="button" class="btn-tiny btn-tiny-danger" :disabled="saving" @click="emit('delete-character', selectedCharacter.id)">删除</button>
              </div>
            </div>

            <div class="drama-cast-editor">
              <div class="drama-cast-fields-row" :class="{ 'drama-cast-fields-row--no-alias': castCategory !== 'character' }">
                <label class="drama-field">
                  名称
                  <input v-model="charDraft.name" type="text" placeholder="角色名称" />
                </label>
                <label v-if="castCategory === 'character'" class="drama-field">
                  别名
                  <input v-model="charDraft.aliases" type="text" placeholder="可选" />
                </label>
                <label class="drama-field">
                  尺寸
                  <select v-model.number="charDraft.ref_size">
                    <option v-for="opt in CAST_REF_SIZES" :key="opt.value" :value="opt.value">
                      {{ opt.hint }}
                    </option>
                  </select>
                </label>
                <label class="drama-field">
                  模型
                  <select v-model="charRefModelKey">
                    <option
                      v-for="opt in CAST_REF_MODELS"
                      :key="`${opt.provider}|${opt.model}`"
                      :value="`${opt.provider}|${opt.model}`"
                    >
                      {{ opt.label }}
                    </option>
                  </select>
                </label>
              </div>
              <label class="drama-field">
                三视图
                <textarea
                  v-model="charDraft.look"
                  rows="3"
                  placeholder="正面、侧面、背面的发型、服装、配饰与气质等细节描述"
                />
              </label>
            </div>

            <div class="drama-cast-main">
              <div class="drama-cast-ref-panel">
                <div class="drama-cast-ref-preview-area">
                  <div class="drama-cast-ref-preview">
                    <img v-if="refPreviewUrl" :src="refPreviewUrl" :alt="selectedCharacter.name || selectedCharacter.id" />
                    <span v-else class="drama-candidate-empty">暂无定妆图</span>
                  </div>
                </div>
                <button
                  type="button"
                  class="btn-ghost btn-sm drama-cast-ref-upload"
                  :disabled="saving || selectedCharacter.ref_locked"
                  @click="refInput?.click()"
                >
                  上传参考图
                </button>
                <input ref="refInput" class="drama-file" type="file" accept="image/*" @change="onRefFile" />
              </div>
              <DramaCastChat
                ref="castChatRef"
                :messages="castChatMessages"
                :loading="saving"
                :disabled="selectedCharacter.ref_locked"
                :character-name="selectedCharacter.name || selectedCharacter.id"
                @send="onCastChatSend"
              />
            </div>
          </div>

          <div v-else class="drama-cast-empty">
            <p>从左侧选择一项进行编辑，或点击「{{ castAddLabel }}」新建。</p>
          </div>
        </div>
      </section>

      <!-- ============ 阶段 3：画面（可分镜出图） ============ -->
      <section v-else-if="stage === 'scene'" class="drama-stage-panel">
        <div class="drama-panel-body">
          <div class="drama-shot-grid">
            <button
              v-for="shot in shots"
              :key="shot.n"
              type="button"
              class="drama-shot-card"
              :class="{ active: shot.n === selectedN }"
              @click="emit('select-shot', shot.n)"
              @mouseenter="preloadShotCandidates(shot)"
            >
              <DramaThumbImg
                v-if="shotThumb(shot)"
                :src="shotThumb(shot)"
                :alt="`Shot ${shot.n}`"
                :fetchpriority="shot.n === selectedN ? 'high' : 'low'"
              />
              <span v-else class="drama-candidate-empty">{{ shot.n }}</span>
              <span class="drama-status-dot" :class="shotStatusClass(shot)">{{ shotStatusLabel(shot) }}</span>
            </button>
          </div>
          <div v-if="selected" class="drama-inspector-panel">
            <div class="drama-candidates-head">
              <h3>候选墙 · Shot {{ selected.n }}</h3>
              <span class="drama-candidate-count">{{ (selected.candidates || []).length }}/4</span>
            </div>
            <input ref="sceneInput" class="drama-file" type="file" accept="image/*" @change="onSceneFile" />
            <div :key="selected.n" class="drama-candidate-grid">
              <button
                v-for="cand in selected.candidates || []"
                :key="cand.id"
                type="button"
                class="drama-candidate"
                :class="{ chosen: isCandidateChosen(cand) }"
                :disabled="rendering || shotFrozen"
                @click="openShotCandidatePreview(cand)"
              >
                <DramaThumbImg
                  v-if="candUrl(cand)"
                  :src="candUrl(cand)"
                  :alt="cand.id"
                  loading="eager"
                  fetchpriority="high"
                />
                <span v-else class="drama-candidate-empty">无图</span>
                <span class="drama-candidate-del" title="删除候选" @click.stop="emit('delete-candidate', cand.id)">×</span>
              </button>
              <div v-if="canAddCandidate" class="drama-candidate-add-wrap">
                <button
                  type="button"
                  class="drama-candidate drama-candidate-add"
                  :class="{ open: addMenuOpen }"
                  :disabled="rendering || shotFrozen"
                  :title="addMenuOpen ? '收起' : '添加候选图'"
                  @click="addMenuOpen = !addMenuOpen"
                >
                  <span class="drama-candidate-add-icon" aria-hidden="true">
                    <svg viewBox="0 0 24 24" width="22" height="22" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round">
                      <line x1="12" y1="5" x2="12" y2="19" />
                      <line x1="5" y1="12" x2="19" y2="12" />
                    </svg>
                  </span>
                </button>
                <div v-if="addMenuOpen" class="drama-add-menu">
                  <button type="button" class="drama-add-menu-item" :disabled="rendering || shotFrozen" @click="onUploadCandidate">
                    上传图片
                  </button>
                  <button type="button" class="drama-add-menu-item" :disabled="rendering || shotFrozen" @click="onGenerateCandidate">
                    生成候选图
                  </button>
                </div>
              </div>
            </div>
          </div>
        </div>
      </section>

      <!-- ============ 阶段 4：视频 ============ -->
      <section v-else-if="stage === 'video'" class="drama-stage-panel">
        <div class="drama-panel-body">
          <div class="drama-actions">
            <button type="button" class="btn-primary" :disabled="rendering" @click="emit('generate-all-video')">
              {{ rendering ? '生成中…' : '一键全部生成视频' }}
            </button>
          </div>
          <div class="drama-shot-list">
            <div v-for="shot in shots" :key="shot.n" class="drama-row" :class="{ active: shot.n === selectedN }" role="button" tabindex="0" @click="emit('select-shot', shot.n)">
              <span class="drama-row-n">{{ shot.n }}</span>
              <span class="drama-row-body">{{ shot.画面 || '（无画面描述）' }}</span>
              <span class="drama-row-flag">{{ i2vSourceLabel }}</span>
              <button type="button" class="btn-tiny" :disabled="rendering || !canGenerateI2v" @click.stop="emit('generate-i2v')">生成视频</button>
            </div>
          </div>
          <div v-if="selected" class="drama-inspector-panel">
            <div class="drama-stage">
              <video v-if="previewKind === 'video'" :key="previewUrl" class="drama-media" :src="previewUrl" controls playsinline />
              <img v-else-if="previewKind === 'image'" class="drama-media" :src="previewUrl" alt="镜头画面" />
              <div v-else class="drama-stage-empty">本镜尚未出图或成片</div>
            </div>
          </div>
        </div>
      </section>

      <!-- ============ 阶段 5：声音 ============ -->
      <section v-else-if="stage === 'voice'" class="drama-stage-panel">
        <div class="drama-panel-body">
          <div class="drama-actions">
            <button type="button" class="btn-primary" :disabled="rendering" @click="emit('generate-all-voice')">
              {{ rendering ? '生成中…' : '一键生成配音与口型' }}
            </button>
          </div>
          <div class="drama-shot-list">
            <div v-for="shot in shots" :key="shot.n" class="drama-row" :class="{ active: shot.n === selectedN }" role="button" tabindex="0" @click="emit('select-shot', shot.n)">
              <span class="drama-row-n">{{ shot.n }}</span>
              <span class="drama-row-body">{{ shot.对白 || shot.字幕 || '（无对白）' }}</span>
              <span class="drama-row-flag">{{ shot.voice ? '配音' : '未配' }}</span>
              <button type="button" class="btn-tiny" :disabled="rendering || !canGenerateLip" @click.stop="emit('generate-lip')">生成口型</button>
            </div>
            <p v-if="!shots.filter((s) => (s.对白 || s.字幕 || '').trim()).length" class="drama-empty-hint">剧本里没有对白镜头，仍需生成。</p>
          </div>
          <p v-if="selected" class="drama-empty-hint" :class="identityClass">{{ identityLabel }}</p>
        </div>
      </section>

      <!-- ============ 阶段 6：成片 ============ -->
      <section v-else-if="stage === 'assemble'" class="drama-stage-panel">
        <div class="drama-panel-body">
          <div class="drama-actions">
            <button type="button" class="btn-primary" :disabled="rendering || saving || mixUnlicensed" @click="emit('export-timeline')">
              {{ rendering ? '导出中…' : '导出整集' }}
            </button>
          </div>
          <div class="drama-stage">
            <video v-if="episode?.play_url" :key="episodePreviewUrl" class="drama-media" :src="episodePreviewUrl" controls playsinline />
            <div v-else class="drama-stage-empty">导出后在此预览整集 mp4</div>
          </div>
          <div class="drama-freeze">
            <button type="button" class="btn-tiny" :disabled="saving || rendering" @click="bgmInput?.click()">上传 BGM</button>
            <button type="button" class="btn-tiny" :disabled="saving || !mix?.has_bgm" @click="emit('clear-bgm')">清除</button>
            <span>{{ mix?.bgm?.title || '未挂配乐' }}</span>
          </div>
          <input ref="bgmInput" class="drama-file" type="file" accept="audio/*" @change="onBgmFile" />
          <audio v-if="bgmPreviewUrl" class="drama-audio" :src="bgmPreviewUrl" controls />
          <p v-if="mixUnlicensed" class="drama-empty-hint drama-warn">{{ mix?.license?.reason || '无版权曲子禁止导出' }}</p>
        </div>
      </section>

      <footer v-if="error" class="drama-flow-footer">
        <p class="drama-banner drama-banner--err drama-flow-footer-banner">{{ error }}</p>
      </footer>
    </div>

    <div v-else class="drama-idle">
      <h2>分镜台</h2>
      <ol class="drama-idle-steps">
        <li><strong>1. 立项</strong> 在对话里说「帮我立项一个 xxx 漫剧」或点左侧项目</li>
        <li><strong>2. 剧本</strong> 一句话生成完整剧本与分镜</li>
        <li><strong>3. 一路生成</strong> 角色 → 画面 → 视频 → 声音 → 成片</li>
      </ol>
    </div>

    <Teleport to="body">
      <div
        v-if="candidatePreview"
        class="drama-candidate-preview-overlay"
        @click.self="closeCandidatePreview"
        @keydown.esc.window="closeCandidatePreview"
      >
        <div class="drama-candidate-preview-modal" role="dialog" aria-modal="true">
          <header class="drama-candidate-preview-head">
            <h3>{{ candidatePreview.label }}</h3>
            <button type="button" class="drama-candidate-preview-close" aria-label="关闭" @click="closeCandidatePreview">×</button>
          </header>
          <div class="drama-candidate-preview-body">
            <img :src="fullAssetUrl(candidatePreview.url)" :alt="candidatePreview.label" />
          </div>
          <footer class="drama-candidate-preview-foot">
            <button type="button" class="btn-ghost" @click="closeCandidatePreview">关闭</button>
            <button
              type="button"
              class="btn-primary"
              :disabled="candidatePreview.locked"
              @click="confirmCandidatePreview"
            >
              选用此图
            </button>
          </footer>
        </div>
      </div>
    </Teleport>

  </main>
</template>
