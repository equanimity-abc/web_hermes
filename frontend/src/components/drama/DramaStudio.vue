<script setup>
import { computed, nextTick, ref, watch } from 'vue'
import DramaThumbImg from '@/components/drama/DramaThumbImg.vue'
import DramaCastChat from '@/components/drama/DramaCastChat.vue'
import DramaScriptChat from '@/components/drama/DramaScriptChat.vue'
import DramaProgressStatusBar from '@/components/drama/DramaProgressStatusBar.vue'

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
  generatingCandidateNs: { type: Array, default: () => [] },
  videoGenProgress: { type: Object, default: null },
  error: { type: String, default: '' },
  notice: { type: String, default: '' },
  bust: { type: Number, default: 0 },
  scriptDraft: { type: String, default: '' },
  scriptImpact: { type: Object, default: null },
  scriptChatMessages: { type: Array, default: () => [] },
  scriptChatLoading: { type: Boolean, default: false },
  scriptChatProgress: { type: Object, default: null },
  boardMode: { type: String, default: 'shots' },
  characters: { type: Array, default: () => [] },
  voices: { type: Array, default: () => [] },
  selectedCharacterId: { type: [String, null], default: null },
  selectedCharacter: { type: Object, default: null },
  charDraft: { type: Object, required: true },
  castChatMessages: { type: Array, default: () => [] },
  videoChatMessages: { type: Array, default: () => [] },
  voiceChatMessages: { type: Array, default: () => [] },
  sceneChatMessages: { type: Array, default: () => [] },
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
  currentPreset: { type: String, default: 'ark' },
  modelCatalog: { type: Object, default: () => ({}) },
  degradedProviders: { type: Array, default: () => [] },
  configNodeList: { type: Array, default: () => [] },
  selectedConfigNode: { type: String, default: 'script' },
  configNodeDraft: { type: String, default: '' },
  stageModelSelection: { type: Function, default: null },
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
  'script-chat-send',
  'enter-script-stage',
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
  'refine-shot-chat',
  'generate-all-refs',
  'generate-all-scenes',
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
  'apply-stage-model',
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
const refInput = ref(null)
const keyInput = ref(null)
const bgmInput = ref(null)
const videoChatRef = ref(null)
const voiceChatRef = ref(null)
const sceneChatRef = ref(null)
const voiceVideoRef = ref(null)
const voiceAudioRef = ref(null)
const selectedKeyId = ref(null)
const castChatRef = ref(null)

const hasLayer = (layer) => (props.shots || []).some((s) => s.files?.[layer]?.exists)

const stageList = computed(() => [
  { id: 'script', label: '剧本', title: '步骤一：编写与对话生成剧本', done: Boolean(props.episode?.script) },
  { id: 'cast', label: '角色', title: '步骤二：文生图生成定妆图，定角色、物品、场景', done: (props.characters || []).some((c) => c.ref_exists) },
  { id: 'scene', label: '画面', title: '步骤三：分镜文生图与候选墙锁图', done: hasLayer('scene') },
  { id: 'video', label: '视频', title: '步骤四：图生视频（I2V 运动），时长取自剧本', done: hasLayer('motion') || (props.shots || []).some((s) => ['ai', 'keys', 'fallback'].includes(s.i2v_source)) },
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
  { provider: 'seedream', model: 'doubao-seedream-5-0-pro-260628', label: '方舟 · Seedream 5.0 Pro' },
  { provider: 'kling-image', model: 'kling/kling-v3-omni-image-generation', label: '可灵 · Kling V3 Omni' },
  { provider: 'wanx', model: 'qwen-image-plus', label: '百炼 · Qwen-Image-Plus' },
]

const charRefModelKey = computed({
  get() {
    const p = props.charDraft.ref_image_provider || 'seedream'
    const m = props.charDraft.ref_image_model || 'doubao-seedream-5-0-pro-260628'
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

function catalogOptions(nodeId) {
  if (nodeId === 'character_ref') return props.modelCatalog?.image || CAST_REF_MODELS
  return props.modelCatalog?.[nodeId] || []
}

function currentModelKey(nodeId) {
  if (typeof props.stageModelSelection === 'function') {
    return props.stageModelSelection(nodeId)
  }
  return ''
}

function onStageModelChange(nodeId, event) {
  const key = event?.target?.value
  if (!key) return
  emit('apply-stage-model', { node: nodeId, key })
}

const scriptStatusTitle = computed(() => {
  const s = props.scriptChatProgress?.status
  if (s === 'running') return '处理中'
  if (s === 'error') return '失败'
  if (s === 'done') return '完成'
  return '状态'
})

const scriptStatusPct = computed(() => {
  const p = props.scriptChatProgress?.pct
  if (p != null) return Math.max(0, Math.min(100, Number(p)))
  if (props.scriptChatProgress?.status === 'running') return 12
  if (props.scriptChatProgress?.status === 'done') return 100
  return 0
})

function onScriptChatSend(text) {
  emit('script-chat-send', text)
}

watch(
  stage,
  (s, prev) => {
    // prev is undefined on the immediate first run; still seed when landing on script.
    // flush:'post' so App has finished mounting listeners before we emit.
    if (s === 'script' && prev !== 'script') emit('enter-script-stage')
  },
  { immediate: true, flush: 'post' },
)

function onCastRefModelChange(event) {
  const key = event?.target?.value
  if (!key) return
  const [provider, model] = String(key).split('|')
  if (props.charDraft) {
    props.charDraft.ref_image_provider = provider
    props.charDraft.ref_image_model = model || props.charDraft.ref_image_model
  }
  emit('apply-stage-model', { node: 'character_ref', key })
}
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

function formatFileSize(bytes) {
  const n = Number(bytes || 0)
  if (!n) return '—'
  if (n < 1024) return `${n} B`
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)} KB`
  return `${(n / (1024 * 1024)).toFixed(2)} MB`
}

const castRefModelLabel = computed(() => {
  const p = props.selectedCharacter?.ref_image_provider || props.charDraft.ref_image_provider
  const m = props.selectedCharacter?.ref_image_model || props.charDraft.ref_image_model
  const hit = CAST_REF_MODELS.find((o) => o.provider === p && o.model === m)
  return hit?.label || m || '—'
})

const castRefInfo = computed(() => {
  const c = props.selectedCharacter
  if (!c?.ref_exists) return null
  const w = Number(c.ref_width || 0)
  const h = Number(c.ref_height || 0)
  const canvas = Number(c.ref_size || props.charDraft.ref_size || 0)
  return {
    pixelSize: w > 0 && h > 0 ? `${w} × ${h} px` : canvas ? `${canvas} × ${canvas} px（设定）` : '—',
    fileSize: formatFileSize(c.ref_bytes),
    model: castRefModelLabel.value,
    locked: Boolean(c.ref_locked),
  }
})

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

function onVideoChatSend(instruction) {
  if (!props.selectedN) return
  emit('refine-shot-chat', 'video', props.selectedN, instruction)
}

function onVoiceChatSend(instruction) {
  if (!props.selectedN) return
  emit('refine-shot-chat', 'voice', props.selectedN, instruction)
}

function onSceneChatSend(instruction) {
  if (!props.selectedN) return
  emit('refine-shot-chat', 'scene', props.selectedN, instruction)
}

// 画面候选图轮播
const currentCandidateIndex = ref(0)
const sceneCandidatesList = computed(() => props.selected?.candidates || [])
const currentCandidate = computed(() => sceneCandidatesList.value[currentCandidateIndex.value] || null)

function prevCandidate() {
  const len = sceneCandidatesList.value.length
  if (!len) return
  currentCandidateIndex.value = (currentCandidateIndex.value - 1 + len) % len
}

function nextCandidate() {
  const len = sceneCandidatesList.value.length
  if (!len) return
  currentCandidateIndex.value = (currentCandidateIndex.value + 1) % len
}

watch(
  () => props.selectedN,
  () => {
    currentCandidateIndex.value = 0
  },
)

watch(
  () => props.castChatMessages.length,
  () => nextTick(() => castChatRef.value?.scrollToBottom?.()),
)

watch(
  () => props.videoChatMessages.length,
  () => nextTick(() => videoChatRef.value?.scrollToBottom?.()),
)

watch(
  () => props.voiceChatMessages.length,
  () => nextTick(() => voiceChatRef.value?.scrollToBottom?.()),
)

watch(
  () => props.sceneChatMessages.length,
  () => nextTick(() => sceneChatRef.value?.scrollToBottom?.()),
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
  const mounted = mix.value?.file?.url || ''
  if (mounted) return `${mounted}${mounted.includes('?') ? '&' : '?'}_=${props.bust || 0}`
  const id = String(props.mixDraft?.catalog_id || '').trim()
  if (id) {
    const hit = catalogTracks.value.find((t) => String(t.id) === id)
    const preview = hit?.preview_url || ''
    if (preview) return `${preview}${preview.includes('?') ? '&' : '?'}_=${props.bust || 0}`
  }
  return ''
})
const catalogTracks = computed(() => mix.value?.catalog || [])
const selectedCatalogTrack = computed(() => {
  const id = String(props.mixDraft?.catalog_id || '').trim()
  if (!id) return null
  return catalogTracks.value.find((t) => String(t.id) === id) || null
})
const assembleMeta = computed(() => {
  const shotList = props.shots || []
  const items = props.timelineItems || []
  const total = Number(props.episode?.timeline?.total_duration || 0)
  const sumDur = shotList.reduce((acc, s) => acc + Number(s.duration || 0), 0)
  // 优先用分镜修改后的时长之和；导出后 timeline 探针会与之对齐
  const durationSec = sumDur > 0 ? sumDur : total
  return {
    exported: Boolean(props.episode?.play_url),
    shotCount: shotList.length || items.length,
    durationLabel: durationSec > 0 ? `${Number(durationSec).toFixed(1)}s` : '—',
    bgmTitle: mix.value?.bgm?.title || '',
    hasBgm: Boolean(mix.value?.has_bgm),
    licenseOk: Boolean(mix.value?.license?.ok || props.mixDraft?.license_ok),
  }
})
const assembleStatusLabel = computed(() => {
  if (props.rendering) return '导出 / 混音处理中…'
  if (assembleMeta.value.exported) return '已导出整集，可预览；改镜后需再点「导出整集」'
  return '尚未导出，配置配乐后点「导出整集」'
})
const assembleStatusClass = computed(() => {
  if (props.rendering) return 'is-running'
  if (assembleMeta.value.exported) return 'is-done'
  return 'is-idle'
})

function onCatalogChange() {
  const id = String(props.mixDraft.catalog_id || '').trim()
  if (id) props.mixDraft.license_ok = true
}

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
function withBust(url) {
  if (!url) return ''
  return `${url}${url.includes('?') ? '&' : '?'}_=${props.bust || 0}`
}
function candUrl(cand) {
  return withBust(assetThumb(cand?.url || ''))
}
function chosenCandidate(shot) {
  if (!shot) return null
  const chosenId = String(shot.chosen || '').trim()
  if (!chosenId) return null
  return (shot.candidates || []).find((c) => String(c.id) === chosenId) || null
}
function shotThumb(shot) {
  if (!shot) return ''
  const chosen = chosenCandidate(shot)
  if (chosen?.url) return withBust(assetThumb(chosen.url))
  const sceneUrl = shot?.files?.scene?.url
  if (sceneUrl && shot?.files?.scene?.exists) {
    return withBust(assetThumb(sceneUrl))
  }
  const cands = shot.candidates || []
  if (cands.length) {
    const last = cands[cands.length - 1]
    if (last?.url) return withBust(assetThumb(last.url))
  }
  return withBust(assetThumb(shot?.preview_url || ''))
}
function shotThumbKey(shot) {
  if (!shot) return ''
  return `${shot.n}-${shot.chosen || ''}-${shot.files?.scene?.bytes || 0}`
}
function isCandidateChosen(cand, shot) {
  return String(cand?.id || '') === String(shot?.chosen || '').trim()
}
function onChooseCandidate(cid) {
  if (shotFrozen.value || !cid) return
  if (isCandidateChosen({ id: cid }, props.selected)) return
  emit('choose-candidate', cid)
}
function isGeneratingCandidates(n) {
  return (props.generatingCandidateNs || []).includes(n)
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
function sceneLocked(shot) {
  return (shot?.locked || []).includes('scene')
}
function sceneLayerDirty(shot) {
  return (shot?.dirty || []).includes('scene')
}
function shotStatusLabel(shot) {
  if (isGeneratingCandidates(shot.n)) return '…'
  const locked = shot.locked || []
  if (locked.includes('shot')) return '锁'
  if (sceneLocked(shot) && !sceneLayerDirty(shot)) return '锁'
  if ((shot.dirty || []).length) return '脏'
  if (shot.files?.clip?.exists) return '成'
  if (shot.files?.scene?.exists) return '图'
  return '待'
}
function shotStatusClass(shot) {
  if (isGeneratingCandidates(shot.n)) return 'is-busy'
  const locked = shot.locked || []
  if (locked.includes('shot')) return 'is-locked'
  if (sceneLocked(shot) && !sceneLayerDirty(shot)) return 'is-locked'
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
const selectedGeneratingCandidates = computed(() => isGeneratingCandidates(props.selectedN))
const canGenerateI2v = computed(() => {
  const shot = props.selected
  if (!shot) return false
  const mode = props.draft?.i2v || shot.i2v || 'auto'
  if (mode === 'off') return false
  if (!shot.files?.scene?.exists) return false
  if (mode === 'on') return true
  // auto：锁定画面后可生成（L0 走静图运镜，其它走 I2V）
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
const i2vSourceLabel = computed(() => i2vSourceLabelFor(props.selected))

function i2vSourceLabelFor(shot) {
  const src = shot?.i2v_source || ''
  if (src === 'ai') return 'I2V 运动'
  if (src === 'keys') return '关键帧补间'
  if (src === 'fallback') return '静图运镜'
  return '待生成视频'
}

function shotHasVideo(shot) {
  if (!shot) return false
  const src = shot.i2v_source || ''
  if (src === 'ai' || src === 'keys' || src === 'fallback') return true
  return Boolean(shot.files?.motion?.exists || shot.files?.clip?.exists)
}

function shotPreviewUrl(shot) {
  if (!shot) return ''
  // 有口型一律播 lip（全景底片已改为原构图，不再硬推近）
  const hasLip = shotHasLip(shot)
  const url = hasLip
    ? shot.files?.lip?.url || shot.files?.clip?.url || shot.files?.motion?.url || shot.files?.scene?.url || ''
    : shot.files?.motion?.url || shot.files?.scene?.url || shot.files?.clip?.url || ''
  return url ? withBust(url) : ''
}

function shotVideoPreviewUrl(shot) {
  // 视频页只看表演母带 motion，避免被 clip/lip 污染观感
  if (!shot) return ''
  const url = shot.files?.motion?.url || shot.files?.scene?.url || ''
  return url ? withBust(url) : ''
}

function shotVoicePreviewUrl(shot) {
  // 单一时钟：优先 clip（装配后的音画）；其次同源 lip；最后才 motion+外挂音
  if (!shot) return ''
  if (shot.files?.clip?.exists && shot.files?.clip?.url) {
    return withBust(shot.files.clip.url)
  }
  if (shotHasLip(shot) && !shot.lip_base_used && shot.files?.lip?.url) {
    return withBust(shot.files.lip.url)
  }
  const url = shot.files?.motion?.url || shot.files?.scene?.url || shot.files?.lip?.url || ''
  return url ? withBust(url) : ''
}

function shotVoiceNeedsExternalAudio(shot) {
  if (!shot) return false
  // clip / 同源 lip 自带音轨，不要再挂 voice.mp3（否则前半段双轨错位）
  if (shot.files?.clip?.exists) return false
  if (shotHasLip(shot) && !shot.lip_base_used) return false
  return Boolean(shotVoiceAudioUrl(shot))
}

function shotVideoPreviewKind(shot) {
  const url = shotVideoPreviewUrl(shot)
  if (!url) return 'empty'
  return url.includes('.mp4') ? 'video' : 'image'
}

function shotVideoRowDesc(shot) {
  if (shotHasVideo(shot)) return i2vSourceLabelFor(shot)
  return shotDescPreview(shot)
}

function shotVideoStatusLabel(shot) {
  if (isVideoGeneratingShot(shot.n)) return '…'
  const locked = shot.locked || []
  if (locked.includes('shot')) return '锁'
  const src = shot.i2v_source || ''
  if (src === 'ai' || src === 'keys') return '动'
  if (src === 'fallback') return '运'
  if (shot.files?.clip?.exists) return '成'
  if (shot.files?.motion?.exists) return '动'
  const dirty = shot.dirty || []
  if (dirty.includes('motion') || dirty.includes('clip')) return '脏'
  if (sceneLocked(shot) && !sceneLayerDirty(shot)) return '图'
  if (shot.files?.scene?.exists) return '图'
  return '待'
}

function shotVideoStatusClass(shot) {
  if (isVideoGeneratingShot(shot.n)) return 'is-busy'
  const locked = shot.locked || []
  if (locked.includes('shot')) return 'is-locked'
  const src = shot.i2v_source || ''
  if (src === 'ai' || src === 'keys') return 'is-done'
  if (shot.files?.clip?.exists) return 'is-done'
  if (shot.files?.motion?.exists) return 'is-scene'
  const dirty = shot.dirty || []
  if (dirty.includes('motion') || dirty.includes('clip')) return 'is-dirty'
  if (sceneLocked(shot) && !sceneLayerDirty(shot)) return 'is-locked'
  if (shot.files?.scene?.exists) return 'is-scene'
  return 'is-todo'
}

function i2vModeLabel(mode) {
  if (mode === 'on') return '强制 I2V'
  if (mode === 'off') return '关闭 I2V'
  return '自动'
}

const cameraOptions = computed(() => {
  const ids = props.episode?.cameras?.length
    ? props.episode.cameras
    : ['punch_in', 'punch_shake', 'pan_right', 'pan_left', 'rise', 'fall', 'pull_out']
  const labels = {
    punch_in: '推进',
    punch_shake: '推进抖动',
    pan_right: '右摇',
    pan_left: '左摇',
    rise: '升起',
    fall: '下降',
    pull_out: '拉远',
  }
  return ids.map((id) => ({ id, label: labels[id] || id }))
})

const ladderOptions = [
  { id: 'L0', label: 'L0 静图运镜' },
  { id: 'L1', label: 'L1 I2V' },
  { id: 'L2', label: 'L2 口型' },
  { id: 'L3', label: 'L3 动作' },
  { id: 'L4', label: 'L4 关键帧' },
]

const i2vSourceOptions = [
  { id: '', label: '待生成' },
  { id: 'fallback', label: '静图运镜' },
  { id: 'ai', label: 'AI' },
  { id: 'keys', label: '关键帧' },
]

function cameraLabel(shot) {
  return String(shot?.camera || '—')
}

function routeLabel(shot) {
  const route = shot?.route
  if (!route) return '—'
  if (route.will_run === false || route.ladder === 'L0') return 'L0 静图运镜'
  return route.ladder ? `${route.ladder} I2V` : 'I2V'
}

function onRefFile(ev) {
  const file = ev.target.files?.[0]
  ev.target.value = ''
  if (file) emit('upload-ref', file)
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
function onGenerateAllScenes() {
  emit('generate-all-scenes')
}

function shotRolesLabel(shot) {
  const roles = shot?.角色
  if (Array.isArray(roles) && roles.length) return roles.join('、')
  return ''
}

function shotDescPreview(shot) {
  const raw = String(shot?.画面 || '').trim()
  if (!raw) return '（无画面描述）'
  // 去掉景别/机位前缀，取第一句动作要点作为摘要
  let text = raw
    .replace(/^(特写|近景|中景|全景|远景|大全景|大特写|快速闪回蒙太奇|画面切到[^—\-–]*)\s*[—\-–]+\s*/u, '')
    .replace(/^(特写|近景|中景|全景|远景)[：:]\s*/u, '')
    .trim()
  const clause = text.split(/[。！？；;\n]/u).map((s) => s.trim()).find(Boolean) || text
  const max = 22
  return clause.length > max ? `${clause.slice(0, max)}…` : clause
}

function onEpisodeChange(event) {
  const n = Number(event.target.value)
  if (n && n !== props.episodeN) {
    emit('open-episode', n)
  }
}

// 预加载候选缩略图
watch(
  () => props.shots,
  (rows) => {
    for (const shot of rows || []) {
      preloadShotCandidates(shot)
      const thumb = shotThumb(shot)
      if (thumb) preloadImage(thumb)
    }
  },
  { deep: true },
)
watch(
  () => props.selected,
  (shot) => {
    if (shot) preloadShotCandidates(shot)
  },
  { immediate: true },
)

function onGenerateCandidate() {
  emit('generate-candidates', 1)
}

function onGenerateVideo() {
  emit('generate-i2v')
}

function onGenerateAllVideo() {
  emit('generate-all-video')
}

function onGenerateVoice() {
  emit('generate-lip')
}

function onGenerateAllVoice() {
  emit('generate-all-voice')
}

function shotHasVoice(shot) {
  return Boolean(shot?.files?.voice?.exists || shot?.voice)
}

function lipSourceBase(src) {
  return String(src || '').trim().split('+')[0].toLowerCase()
}

function shotHasLip(shot) {
  const base = lipSourceBase(shot?.lip_source)
  const real = [
    'mock',
    'http',
    'ai',
    'pixverse',
    'pixverse-lipsync',
    'latentsync',
    'musetalk',
    'wav2lip',
  ]
  return Boolean(shot?.files?.lip?.exists || real.includes(base))
}

function shotDialoguePreview(shot) {
  const raw = String(shot?.字幕 || shot?.对白 || '').trim()
  if (!raw) return '（无字幕）'
  const quoteRe = /[「『“"]([^」』”"]+)[」』”"]/g
  const quotes = []
  let m
  while ((m = quoteRe.exec(raw)) !== null) {
    const q = String(m[1] || '').trim()
    if (q) quotes.push(q)
  }
  const cleaned = quotes.length
    ? (() => {
        let out = quotes[0]
        for (let i = 1; i < quotes.length; i += 1) {
          if (!/[。！？!?…]$/.test(out)) out += '。'
          out += quotes[i]
        }
        return out
      })()
    : raw
        .replace(
          /^(?:【[^】]{1,12}】|\[[^\]]{1,12}\])?[^:：\s「『“"]{1,16}(?:\s*[（(][^）)]{0,40}[）)])?\s*[:：]\s*/,
          '',
        )
        .replace(/[（(][^）)]{0,24}[）)]/g, '')
        .trim() || raw
  const clause = cleaned.split(/[。！？；;\n]/u).map((s) => s.trim()).find(Boolean) || cleaned
  const max = 22
  return clause.length > max ? `${clause.slice(0, max)}…` : clause
}

function shotVoiceRowDesc(shot) {
  if (shotHasVoice(shot)) {
    return shotHasLip(shot) ? '已配音·口型' : '已配音'
  }
  return shotDialoguePreview(shot)
}

function shotVoiceStatusLabel(shot) {
  if (props.rendering && props.selectedN === shot.n) return '…'
  const locked = shot.locked || []
  if (locked.includes('shot') || locked.includes('voice')) return '锁'
  if (shotHasLip(shot)) return '口'
  if (shotHasVoice(shot)) return '音'
  const dirty = shot.dirty || []
  if (dirty.includes('voice') || dirty.includes('lip')) return '脏'
  if ((shot.字幕 || shot.对白 || '').trim()) return '待'
  return '—'
}

function shotVoiceStatusClass(shot) {
  if (props.rendering && props.selectedN === shot.n) return 'is-busy'
  const locked = shot.locked || []
  if (locked.includes('shot') || locked.includes('voice')) return 'is-locked'
  if (shotHasLip(shot)) return 'is-done'
  if (shotHasVoice(shot)) return 'is-scene'
  const dirty = shot.dirty || []
  if (dirty.includes('voice') || dirty.includes('lip')) return 'is-dirty'
  return 'is-todo'
}

function shotVoicePreviewKind(shot) {
  const url = shotVoicePreviewUrl(shot)
  if (!url) return 'empty'
  return url.includes('.mp4') ? 'video' : 'image'
}

function shotVoiceAudioUrl(shot) {
  const url = shot?.files?.voice?.url || ''
  if (!url) return ''
  return withBust(url)
}

function voiceNarrationText() {
  // 旁白 = 画外说明（左上角竖排）；展示时去掉心声前缀
  let text = String(props.draft?.旁白 || '').trim()
  if (!text) return ''
  text = text.replace(/^(?:【\s*)?(?:内心独白|心声|OS)(?:\s*】)?\s*[:：]?\s*/i, '').trim()
  return text
}

function voiceDialogueCaption() {
  // 字幕 = 台词（底部）；预览去掉说话人前缀/引号，不改写草稿原文
  let text = String(props.draft?.字幕 || '').trim()
  if (!text) return ''
  const quote = text.match(/[「『“"]([^」』”"]+)[」』”"]/)
  if (quote?.[1]) return String(quote[1]).trim()
  text = text
    .replace(
      /^(?:【[^】]{1,12}】|\[[^\]]{1,12}\])?[^:：\s「『“"]{1,16}(?:\s*[（(][^）)]{0,40}[）)])?\s*[:：]\s*/,
      '',
    )
    .replace(/[「『“”」』"]/g, '')
    .trim()
  return text
}

function syncVoiceAudioToVideo() {
  const video = voiceVideoRef.value
  const audio = voiceAudioRef.value
  if (!video || !audio) return
  if (Math.abs((audio.currentTime || 0) - (video.currentTime || 0)) > 0.12) {
    try {
      audio.currentTime = video.currentTime || 0
    } catch {
      /* ignore seek errors while loading */
    }
  }
}

function syncVoiceVolumeFromVideo() {
  const video = voiceVideoRef.value
  const audio = voiceAudioRef.value
  if (!video || !audio) return
  audio.muted = Boolean(video.muted)
  audio.volume = Number.isFinite(video.volume) ? video.volume : 1
}

function restartVoicePreviewIfNeeded() {
  const video = voiceVideoRef.value
  if (!video) return false
  const dur = Number(video.duration) || 0
  const atEnd = Boolean(video.ended) || (dur > 0 && video.currentTime >= dur - 0.08)
  if (!atEnd) return false
  try {
    video.currentTime = 0
  } catch {
    /* ignore */
  }
  const audio = voiceAudioRef.value
  if (audio && shotVoiceNeedsExternalAudio(props.selected)) {
    try {
      audio.currentTime = 0
    } catch {
      /* ignore */
    }
  }
  return true
}

function onVoiceVideoPlay() {
  const video = voiceVideoRef.value
  const audio = voiceAudioRef.value
  if (!audio) return
  if (video) video.muted = true
  syncVoiceVolumeFromVideo()
  syncVoiceAudioToVideo()
  audio.play().catch(() => {})
}

function onVoiceVideoPause() {
  const video = voiceVideoRef.value
  const audio = voiceAudioRef.value
  if (!audio) return
  // 仅当用户暂停（非「画面先结束、音频还在」）时同步停音频
  if (video && video.ended && !audio.ended) return
  audio.pause()
}

function onVoiceVideoSeeked() {
  syncVoiceAudioToVideo()
}

function onVoiceVideoPlaySafe() {
  const video = voiceVideoRef.value
  const external = shotVoiceNeedsExternalAudio(props.selected)
  restartVoicePreviewIfNeeded()
  if (video) video.muted = Boolean(external)
  if (external) onVoiceVideoPlay()
}

function onVoiceVideoPauseSafe() {
  if (shotVoiceNeedsExternalAudio(props.selected)) onVoiceVideoPause()
}

function onVoiceVideoSeekedSafe() {
  if (shotVoiceNeedsExternalAudio(props.selected)) onVoiceVideoSeeked()
}

function onVoiceVideoVolumeChangeSafe() {
  if (shotVoiceNeedsExternalAudio(props.selected)) onVoiceVideoVolumeChange()
}

function onVoiceVideoEnded() {
  // 不要把 currentTime 钉在末尾，否则再次点播放会立刻 ended / 无法重播
  const audio = voiceAudioRef.value
  if (!shotVoiceNeedsExternalAudio(props.selected)) return
  // 画面短于配音：保持尾帧，让外挂音频继续；二者都结束则自然停
  if (audio && !audio.ended && !audio.paused) return
}

function onVoiceVideoVolumeChange() {
  syncVoiceVolumeFromVideo()
}

function onVoiceAudioPlay() {
  const video = voiceVideoRef.value
  const audio = voiceAudioRef.value
  if (!video || !audio) return
  if (Math.abs((video.currentTime || 0) - (audio.currentTime || 0)) > 0.12) {
    try {
      video.currentTime = audio.currentTime || 0
    } catch {
      /* ignore */
    }
  }
  video.muted = true
  video.play().catch(() => {})
}

function onVoiceAudioPause() {
  const video = voiceVideoRef.value
  if (video && !video.paused) video.pause()
}

function onVoiceAudioEnded() {
  const video = voiceVideoRef.value
  if (video && !video.paused) video.pause()
}

function speakerLabel(shot) {
  return String(shot?.speaker || shot?.voice_id || '—')
}

function voiceIdLabel(shot) {
  const id = String(shot?.voice || shot?.voice_id || '')
  if (!id) return '—'
  const hit = (props.voices || []).find((v) => v.id === id)
  return hit?.label || id
}

function voiceLabelForId(id) {
  const vid = String(id || '').trim()
  if (!vid) return '—'
  const hit = (props.voices || []).find((v) => v.id === vid)
  return hit?.label || vid
}

function findCharacterForSpeaker(name) {
  const key = String(name || '').trim()
  if (!key) return null
  return (
    (props.characters || []).find(
      (c) =>
        (c.category || 'character') === 'character' &&
        (c.name === key || c.id === key || (c.aliases || []).includes(key)),
    ) || null
  )
}

/** Canonical character card name only — never alias / id. */
function canonicalSpeakerName(raw) {
  const key = String(raw || '').trim()
  if (!key) return ''
  const hit = findCharacterForSpeaker(key)
  if (hit?.name) return hit.name
  // Hide bare ids like ruoxi when unresolved
  if (/^[a-z][a-z0-9_]{0,31}$/.test(key)) return ''
  return key
}

/**
 * Speakers who can talk in this shot — display **角色卡名称** only.
 * Aliases (林晚/林薇薇) and ids are resolved, never shown.
 */
const voiceSpeakerOptions = computed(() => {
  const names = []
  const seen = new Set()
  const push = (raw) => {
    const n = canonicalSpeakerName(raw)
    if (!n || seen.has(n)) return
    seen.add(n)
    names.push(n)
  }

  for (const sp of props.selected?.voice_speakers || []) {
    push(sp?.name || sp?.character_name)
  }
  for (const b of props.selected?.dialogue_track?.bindings || []) {
    push(b?.character_name || b?.speaker)
  }
  for (const t of props.selected?.dialogue_track?.turns || props.selected?.voice_turns || []) {
    push(t?.character_name || t?.speaker)
  }

  const dialogue = String(props.draft?.字幕 || props.selected?.字幕 || props.selected?.对白 || '')
  const quoteRe =
    /([^:：\s「『“"（(【\[]{1,16})(?:\s*[（(][^）)]{0,40}[）)])?\s*[:：]\s*[「『“"]([^」』”"]+)[」』”"]/g
  let m
  while ((m = quoteRe.exec(dialogue))) push(m[1])
  for (const line of dialogue.split(/[\n\r]+/)) {
    const lm = line
      .trim()
      .match(/^([^:：\s「『“"（(【\[]{1,16})(?:\s*[（(][^）)]{0,40}[）)])?\s*[:：]\s*(.+)$/)
    if (lm) push(lm[1])
  }

  for (const rid of props.draft?.角色 || props.selected?.角色 || []) {
    push(rid)
  }

  push(props.selected?.dialogue_track?.primary_speaker)
  push(props.selected?.speaker)

  return names
})

/** Inspect-only: browsing speaker↔voice must not dirty the save button. */
const voiceInspectSpeaker = ref('')

watch(
  () => [props.selectedN, props.selected?.speaker, props.selected?.dialogue_track?.primary_speaker, voiceSpeakerOptions.value.join('|')],
  () => {
    const opts = voiceSpeakerOptions.value
    const preferred = canonicalSpeakerName(
      props.selected?.dialogue_track?.primary_speaker || props.selected?.speaker || '',
    )
    if (preferred && opts.includes(preferred)) {
      voiceInspectSpeaker.value = preferred
    } else if (opts.length) {
      voiceInspectSpeaker.value = opts[0]
    } else {
      voiceInspectSpeaker.value = preferred || ''
    }
  },
  { immediate: true },
)

const selectedSpeakerVoiceLabel = computed(() => {
  const name = String(voiceInspectSpeaker.value || '').trim()
  const hit = findCharacterForSpeaker(name)
  if (hit?.voice) return voiceLabelForId(hit.voice)
  const bind = (props.selected?.dialogue_track?.bindings || []).find(
    (b) => (b.character_name || b.speaker) === name,
  )
  if (bind?.voice_label) return bind.voice_label
  if (bind?.voice) return voiceLabelForId(bind.voice)
  const sp = (props.selected?.voice_speakers || []).find((s) => s.name === name)
  if (sp?.voice_label) return sp.voice_label
  return '—'
})

function lipStatusLabel(shot) {
  const warnings = Array.isArray(shot?.lip_warnings) ? shot.lip_warnings : []
  const degraded = Boolean(shot?.lip_degraded || warnings.length)
  let label
  if (shotHasLip(shot)) {
    const src = lipSourceBase(shot?.lip_source)
    const map = {
      latentsync: 'LatentSync · 高清',
      pixverse: 'PixVerse · 已同步',
      'pixverse-lipsync': 'PixVerse · 已同步',
      musetalk: 'MuseTalk',
      wav2lip: 'Wav2Lip',
      http: '网关口型',
      ai: 'AI 口型',
      mock: '占位波形（非真口型）',
    }
    const score = shot?.lip_score?.lse_c ?? shot?.lip_score?.score
    const base = map[src] || src || '已生成'
    label = score != null && score !== '' ? `${base} · LSE ${Number(score).toFixed?.(2) ?? score}` : base
  } else if (shot?.lip_error) {
    label = `失败：${shot.lip_error}`
  } else if (shot?.lip?.will_run || shot?.lip?.ok) {
    label = '可生成（真口型）'
  } else {
    label = shot?.lip?.reason || '暂无'
  }
  const srcTag = { director: '导演锁定', arcface: '身份锁', color: '颜色启发式', none: '未锁定' }[
    shot?.lip_layout_source
  ]
  if (srcTag) label += ` · ${srcTag}`
  if (degraded) label += ' ⚠️ 降级'
  return label
}

function lipWarnings(shot) {
  return Array.isArray(shot?.lip_warnings) ? shot.lip_warnings : []
}

function canGenerateVoiceFor(shot) {
  if (!shot) return false
  if ((shot.locked || []).includes('shot')) return false
  return Boolean((shot.字幕 || shot.对白 || '').trim())
}

const canGenerateVoice = computed(() => canGenerateVoiceFor(props.selected))

function isVideoGeneratingShot(n) {
  const p = props.videoGenProgress
  return Boolean(p && p.status === 'running' && Number(p.shotN) === Number(n))
}

const videoProgressLabel = computed(() => {
  const p = props.videoGenProgress
  if (!p) return ''
  if (p.mode === 'batch' && p.total > 1) {
    return p.message || `批量生成 ${p.current || 0}/${p.total}`
  }
  return p.message || (p.status === 'running' ? '视频生成中…' : '')
})

const videoProgressPct = computed(() => {
  const p = props.videoGenProgress
  if (!p?.total) return 0
  const cur = Math.max(0, Number(p.current) || 0)
  const total = Math.max(1, Number(p.total) || 1)
  if (p.status === 'done') return 100
  // 进行中时按已完成镜数显示：current 是「当前正在做的第几镜」
  const finished = Math.max(0, cur - (p.status === 'running' ? 1 : 0))
  return Math.min(100, Math.round((finished / total) * 100))
})

const videoStatusTitle = computed(() => {
  const s = props.videoGenProgress?.status
  if (s === 'running') return '处理中'
  if (s === 'done') return '完成'
  if (s === 'error') return '失败'
  return '状态'
})

const videoStatusLabel = computed(() => {
  const p = props.videoGenProgress
  if (!p) return '待命'
  const count =
    p.mode === 'batch' && p.total
      ? `${p.current || 0}/${p.total}`
      : ''
  const msg =
    p.status === 'running'
      ? videoProgressLabel.value || '视频生成中…'
      : p.status === 'done'
        ? videoProgressLabel.value || '生成完成'
        : p.status === 'error'
          ? videoProgressLabel.value || '生成失败'
          : videoProgressLabel.value || '待命'
  return count ? `${count} · ${msg}` : msg
})

const voiceStatusTitle = computed(() => {
  if (props.rendering) return '处理中'
  if (props.selected && shotVoiceAudioUrl(props.selected)) return '完成'
  return '状态'
})

const voiceStatusLabel = computed(() => {
  if (props.rendering) return '配音生成中…'
  if (props.selected && shotVoiceAudioUrl(props.selected)) return '配音已就绪'
  return '尚未生成配音'
})

const voiceStatusPct = computed(() => {
  if (props.rendering) return 55
  if (props.selected && shotVoiceAudioUrl(props.selected)) return 100
  return 0
})

const voiceStatusState = computed(() => {
  if (props.rendering) return 'running'
  if (props.selected && shotVoiceAudioUrl(props.selected)) return 'done'
  return 'idle'
})

const assembleStatusTitle = computed(() => {
  if (props.rendering) return '处理中'
  if (assembleMeta.value.exported) return '完成'
  return '状态'
})

const assembleStatusPct = computed(() => {
  if (props.rendering) return 55
  if (assembleMeta.value.exported) return 100
  return 0
})

const assembleStatusState = computed(() => {
  if (props.rendering) return 'running'
  if (assembleMeta.value.exported) return 'done'
  return 'idle'
})

// 全局底部状态栏：按当前步骤返回对应的进度 / 状态 / 标题 / 消息。
const statusBar = computed(() => {
  switch (stage.value) {
    case 'script':
      return {
        pct: scriptStatusPct.value,
        status: props.scriptChatProgress?.status || 'idle',
        title: scriptStatusTitle.value,
        message: props.scriptChatProgress?.message || '就绪',
      }
    case 'cast': {
      const list = props.characters || []
      const withRef = list.filter((c) => c.ref_exists).length
      return {
        pct: list.length ? Math.round((withRef / list.length) * 100) : 0,
        status: list.length && withRef === list.length ? 'done' : 'idle',
        title: '角色',
        message: list.length ? `定妆图 ${withRef}/${list.length}` : '暂无角色',
      }
    }
    case 'scene': {
      const gen = props.generatingCandidateNs || []
      return {
        pct: gen.length ? 40 : 0,
        status: gen.length ? 'running' : 'idle',
        title: '画面',
        message: gen.length ? `正在生成 ${gen.length} 个候选图…` : '候选项待生成',
      }
    }
    case 'video':
      return {
        pct: videoProgressPct.value,
        status: props.videoGenProgress?.status || 'idle',
        title: videoStatusTitle.value,
        message: videoStatusLabel.value,
      }
    case 'voice':
      return {
        pct: voiceStatusPct.value,
        status: voiceStatusState.value,
        title: voiceStatusTitle.value,
        message: voiceStatusLabel.value,
      }
    case 'assemble':
      return {
        pct: assembleStatusPct.value,
        status: assembleStatusState.value,
        title: assembleStatusTitle.value,
        message: assembleStatusLabel.value,
      }
    default:
      return { pct: 0, status: 'idle', title: '状态', message: '就绪' }
  }
})
</script>

<template>
  <main class="drama-studio">
    <header class="drama-top">
      <div class="drama-top-head">
        <div class="drama-top-title">
          <h1>{{ project?.project?.title || '漫剧工作台' }}</h1>
        </div>
        <div v-if="episodes.length > 1" class="drama-ep-select">
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
      </div>
    </div>

    <div v-if="project" class="drama-stage-title">
      <h2>{{ currentStage.title }}</h2>
      <div class="drama-stage-title-actions">
        <template v-if="stage === 'cast'">
          <button type="button" class="btn-ghost btn-sm" :disabled="saving" @click="onAddCastAsset">
            {{ castAddLabel }}
          </button>
          <button type="button" class="btn-ghost btn-sm" :disabled="rendering" @click="onGenerateAllCastRefs">
            {{ rendering ? '生成中…' : '批量生成' }}
          </button>
        </template>
        <template v-else-if="stage === 'scene'">
          <button type="button" class="btn-ghost btn-sm" :disabled="rendering || !shots.length" @click="onGenerateAllScenes">
            {{ rendering ? '生成中…' : '批量出图' }}
          </button>
        </template>
        <template v-else-if="stage === 'video'">
          <button type="button" class="btn-ghost btn-sm" :disabled="rendering || !shots.length" @click="onGenerateAllVideo">
            {{ rendering ? '生成中…' : '批量生成视频' }}
          </button>
        </template>
        <template v-else-if="stage === 'voice'">
          <button type="button" class="btn-ghost btn-sm" :disabled="rendering || !shots.length" @click="onGenerateAllVoice">
            {{ rendering ? '生成中…' : '批量生成配音' }}
          </button>
        </template>
        <template v-else-if="stage === 'assemble'">
          <button
            type="button"
            class="btn-ghost btn-sm"
            :disabled="saving || !mixDirty"
            @click="emit('save-mix')"
          >
            {{ saving ? '保存中…' : mixDirty ? '保存' : '已保存' }}
          </button>
          <button
            type="button"
            class="btn-ghost btn-sm"
            :disabled="rendering || saving || mixUnlicensed || !mix?.has_bgm"
            @click="emit('apply-mix')"
          >
            {{ rendering ? '混音中…' : '应用混音' }}
          </button>
          <button
            type="button"
            class="btn-primary btn-sm"
            :disabled="rendering || saving || mixUnlicensed"
            @click="emit('export-timeline')"
          >
            {{ rendering ? '导出中…' : assembleMeta.exported ? '重新导出' : '导出整集' }}
          </button>
        </template>
      </div>
    </div>

    <div v-if="project" class="drama-flow">
      <!-- ============ 阶段 1：剧本 ============ -->
      <section v-if="stage === 'script'" class="drama-stage-panel drama-script-stage">
        <div class="drama-panel-body">
          <div class="drama-script-layout">
            <div class="drama-script-editor-col">
              <div class="drama-script-panel drama-script-panel--edit">
                <div class="drama-script-panel-head">
                  <span class="drama-script-panel-title">剧本</span>
                  <div class="drama-script-panel-head-actions">
                    <label class="drama-model-bar-label">剧本模型</label>
                    <select
                      class="drama-model-select"
                      :value="currentModelKey('script')"
                      :disabled="saving || scriptChatLoading"
                      @change="onStageModelChange('script', $event)"
                    >
                      <option
                        v-for="opt in catalogOptions('script')"
                        :key="`${opt.provider}|${opt.model}`"
                        :value="`${opt.provider}|${opt.model}`"
                      >
                        {{ opt.label }}
                      </option>
                    </select>
                    <button
                      type="button"
                      class="btn-ghost btn-sm"
                      :disabled="saving || rendering || !scriptDraft.trim()"
                      @click="emit('save-script')"
                    >
                      {{ saving ? '保存中…' : '保存剧本' }}
                    </button>
                  </div>
                </div>
                <textarea
                  class="drama-script-editor"
                  :value="scriptDraft"
                  spellcheck="false"
                  rows="22"
                  placeholder="在右侧对话生成或修改剧本；也可在此直接编辑后保存。"
                  @input="emit('update:scriptDraft', $event.target.value)"
                />
              </div>
            </div>

            <div class="drama-script-chat-col">
              <DramaScriptChat
                :messages="scriptChatMessages"
                :loading="scriptChatLoading"
                :disabled="!project || saving"
                hint="用一句话描述故事即可生成剧本；已有剧本时可继续对话修改。首条可来自主聊天。"
                placeholder="例如：豪门养女重生复仇，共1集60秒…"
                pending-label="正在生成 / 修改剧本…"
                @send="onScriptChatSend"
              />
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
                  <select
                    :value="charRefModelKey"
                    :disabled="saving"
                    @change="onCastRefModelChange"
                  >
                    <option
                      v-for="opt in catalogOptions('character_ref')"
                      :key="`${opt.provider}|${opt.model}`"
                      :value="`${opt.provider}|${opt.model}`"
                    >
                      {{ opt.label }}
                    </option>
                  </select>
                </label>
                <label v-if="castCategory === 'character'" class="drama-field">
                  音色
                  <select v-model="charDraft.voice">
                    <option v-for="v in voices" :key="v.id" :value="v.id">
                      {{ v.label || v.id }}
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
                <dl v-if="castRefInfo" class="drama-cast-ref-meta">
                  <div class="drama-cast-ref-meta-row">
                    <dt>像素</dt>
                    <dd>{{ castRefInfo.pixelSize }}</dd>
                  </div>
                  <div class="drama-cast-ref-meta-row">
                    <dt>文件</dt>
                    <dd>{{ castRefInfo.fileSize }}</dd>
                  </div>
                  <div class="drama-cast-ref-meta-row">
                    <dt>模型</dt>
                    <dd>{{ castRefInfo.model }}</dd>
                  </div>
                  <div class="drama-cast-ref-meta-row">
                    <dt>状态</dt>
                    <dd>{{ castRefInfo.locked ? '已锁定' : '未锁定' }}</dd>
                  </div>
                </dl>
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
      <section v-else-if="stage === 'scene'" class="drama-stage-panel drama-scene-stage">
        <div class="drama-panel-body drama-scene-layout">
          <div class="drama-scene-sidebar">
            <div class="drama-scene-list">
              <div class="drama-scene-rows">
                <button
                  v-for="shot in shots"
                  :key="shot.n"
                  type="button"
                  class="drama-scene-row"
                  :class="{ active: shot.n === selectedN, locked: (shot.locked || []).includes('scene') }"
                  @click="emit('select-shot', shot.n)"
                  @mouseenter="preloadShotCandidates(shot)"
                >
                  <div class="drama-scene-thumb">
                    <DramaThumbImg
                      v-if="shotThumb(shot)"
                      :key="shotThumbKey(shot)"
                      :src="shotThumb(shot)"
                      :alt="`Shot ${shot.n}`"
                      :fetchpriority="shot.n === selectedN ? 'high' : 'low'"
                    />
                    <span v-else class="drama-scene-thumb-empty">{{ shot.n }}</span>
                  </div>
                  <div class="drama-scene-row-body">
                    <span class="drama-scene-row-n">Shot {{ shot.n }}</span>
                    <span class="drama-scene-row-desc">{{ shotDescPreview(shot) }}</span>
                  </div>
                  <span class="drama-status-dot" :class="shotStatusClass(shot)">{{ shotStatusLabel(shot) }}</span>
                </button>
              </div>
              <p v-if="!shots.length" class="drama-empty-hint">暂无分镜，请先在「剧本」步骤生成分镜表。</p>
            </div>
          </div>

          <div v-if="selected" class="drama-scene-detail">
            <div class="drama-scene-detail-head">
              <h3>Shot {{ selected.n }}</h3>
              <div class="drama-scene-detail-actions">
                <button type="button" class="btn-primary btn-sm" :disabled="rendering || shotFrozen || candidatesFull || selectedGeneratingCandidates" @click="onGenerateCandidate">
                  {{ selectedGeneratingCandidates ? '生成中…' : '生成候选图' }}
                </button>
              </div>
            </div>

            <div class="drama-scene-body">
              <div class="drama-scene-left">
                <div class="drama-scene-script">
                  <label class="drama-field">
                    画面描述
                    <textarea class="drama-scene-script-text" :value="selected.画面 || ''" rows="4" readonly placeholder="（剧本中尚未填写画面描述）" />
                  </label>
                  <p class="drama-scene-script-hint">来自剧本分镜；修改请返回「剧本」步骤编辑对应 Shot 的「画面」字段。</p>
                  <div v-if="shotRolesLabel(selected) || selected.字幕 || selected.旁白 || selected.对白" class="drama-scene-meta">
                    <span v-if="shotRolesLabel(selected)" class="drama-scene-meta-item"><strong>角色</strong>{{ shotRolesLabel(selected) }}</span>
                    <span v-if="selected.字幕 || selected.对白" class="drama-scene-meta-item"><strong>字幕</strong>{{ selected.字幕 || selected.对白 }}</span>
                    <span v-if="selected.旁白" class="drama-scene-meta-item"><strong>旁白</strong>{{ selected.旁白 }}</span>
                  </div>
                </div>

                <div class="drama-stage-settings">
                  <div class="drama-stage-settings-head">设置</div>
                  <div class="drama-stage-settings-row">
                    <label class="drama-field">
                      出图模型
                      <select class="drama-model-select" :value="currentModelKey('image')" :disabled="saving" @change="onStageModelChange('image', $event)">
                        <option v-for="opt in catalogOptions('image')" :key="`${opt.provider}|${opt.model}`" :value="`${opt.provider}|${opt.model}`">{{ opt.label }}</option>
                      </select>
                    </label>
                  </div>
                  <p class="drama-stage-settings-hint">作用于本项目全部分镜出图</p>
                </div>
              </div>

              <div class="drama-scene-right">
                <div class="drama-scene-candidates">
                  <div class="drama-candidates-head">
                    <h4>候选图</h4>
                    <div class="drama-candidates-actions">
                      <span class="drama-candidate-count">{{ sceneCandidatesList.length ? currentCandidateIndex + 1 : 0 }}/{{ sceneCandidatesList.length }}</span>
                      <button type="button" class="btn-tiny" :disabled="rendering || shotFrozen" @click="emit('toggle-lock', 'scene')">
                        {{ isLocked('scene') ? '解锁' : '锁定' }}
                      </button>
                      <button type="button" class="btn-tiny" :disabled="!currentCandidate" @click="emit('delete-candidate', currentCandidate && currentCandidate.id)">删除</button>
                    </div>
                  </div>
                  <div class="drama-scene-carousel">
                    <button type="button" class="drama-candidate-nav drama-candidate-prev" :disabled="sceneCandidatesList.length <= 1" @click="prevCandidate">‹</button>
                    <div class="drama-candidate-frame">
                      <DramaThumbImg v-if="currentCandidate && candUrl(currentCandidate)" :key="currentCandidate.id" :src="candUrl(currentCandidate)" :alt="currentCandidate.id" loading="eager" fetchpriority="high" />
                      <span v-else class="drama-candidate-empty">无候选图，点击「生成候选图」</span>
                    </div>
                    <button type="button" class="drama-candidate-nav drama-candidate-next" :disabled="sceneCandidatesList.length <= 1" @click="nextCandidate">›</button>
                  </div>
                </div>

                <DramaCastChat ref="sceneChatRef" class="drama-scene-chat" title="对话改画面" :character-name="`Shot ${selected.n}`" hint="用自然语言调整画面描述等；保存后可点「生成候选图」生效。" placeholder="例如：改成分镜特写、画面加一条小河…" disabled-placeholder="请先选择镜头" pending-label="正在理解并更新…" :messages="sceneChatMessages" :loading="saving" @send="onSceneChatSend" />
              </div>
            </div>
          </div>

          <div v-else class="drama-cast-empty">
            <p>从左侧选择一镜，查看剧本画面描述并生成候选图。</p>
          </div>
        </div>
      </section>

      <!-- ============ 阶段 4：视频 ============ -->
      <section v-else-if="stage === 'video'" class="drama-stage-panel drama-video-stage">
        <div class="drama-panel-body drama-scene-layout">
          <div class="drama-scene-sidebar">
            <div class="drama-scene-list">
              <div class="drama-scene-rows">
                <button
                  v-for="shot in shots"
                  :key="shot.n"
                  type="button"
                  class="drama-scene-row"
                  :class="{ active: shot.n === selectedN, ready: shotHasVideo(shot) }"
                  @click="emit('select-shot', shot.n)"
                >
                  <div class="drama-scene-thumb">
                    <DramaThumbImg
                      v-if="shotThumb(shot)"
                      :key="shotThumbKey(shot)"
                      :src="shotThumb(shot)"
                      :alt="`Shot ${shot.n}`"
                      :fetchpriority="shot.n === selectedN ? 'high' : 'low'"
                    />
                    <span v-else class="drama-scene-thumb-empty">{{ shot.n }}</span>
                  </div>
                  <div class="drama-scene-row-body">
                    <span class="drama-scene-row-n">Shot {{ shot.n }}</span>
                    <span class="drama-scene-row-desc">{{ shotVideoRowDesc(shot) }}</span>
                  </div>
                  <span class="drama-status-dot" :class="shotVideoStatusClass(shot)">{{ shotVideoStatusLabel(shot) }}</span>
                </button>
              </div>
              <p v-if="!shots.length" class="drama-empty-hint">暂无分镜，请先在「剧本」步骤生成分镜表。</p>
            </div>
          </div>

          <div v-if="selected" class="drama-scene-detail">
            <div class="drama-scene-detail-head">
              <div class="drama-scene-detail-title">
                <h3>Shot {{ selected.n }}</h3>
              </div>
              <div class="drama-scene-detail-actions">
                <button type="button" class="btn-ghost btn-sm" :disabled="saving || !dirty" @click="emit('save')">
                  {{ saving ? '保存中…' : dirty ? '保存' : '已保存' }}
                </button>
                <button
                  type="button"
                  class="btn-ghost btn-sm"
                  :disabled="saving || rendering || !selected?.files?.motion?.exists"
                  :title="selected?.motion_locked ? '解锁后允许重新生成覆盖 motion' : '锁定后声音/口型不会改写表演母带'"
                  @click="emit('toggle-lock', 'motion')"
                >
                  {{ selected?.motion_locked || (selected?.locked || []).includes('motion') ? '解锁运动' : '锁定运动' }}
                </button>
                <button
                  type="button"
                  class="btn-primary btn-sm"
                  :disabled="rendering || !canGenerateI2v"
                  @click="onGenerateVideo"
                >
                  {{ rendering ? '生成中…' : '生成视频' }}
                </button>
              </div>
            </div>

            <div class="drama-scene-body">
              <div class="drama-scene-left">
                <div class="drama-scene-script">
              <label class="drama-field">
                画面描述
                <textarea
                  class="drama-scene-script-text"
                  :value="selected.画面 || ''"
                  rows="3"
                  readonly
                  placeholder="（剧本中尚未填写画面描述）"
                />
              </label>
              <div class="drama-voice-meta-row drama-video-meta-row">
                <label class="drama-voice-kv">
                  <strong>模型</strong>
                  <select
                    :value="currentModelKey('motion')"
                    :disabled="saving"
                    @change="onStageModelChange('motion', $event)"
                  >
                    <option
                      v-for="opt in catalogOptions('motion')"
                      :key="`${opt.provider}|${opt.model}`"
                      :value="`${opt.provider}|${opt.model}`"
                    >
                      {{ opt.label }}
                    </option>
                  </select>
                </label>
                <label class="drama-voice-kv">
                  <strong>运镜</strong>
                  <select v-model="draft.camera">
                    <option v-for="cam in cameraOptions" :key="cam.id" :value="cam.id">
                      {{ cam.label }}
                    </option>
                  </select>
                </label>
                <label class="drama-voice-kv">
                  <strong>I2V</strong>
                  <select v-model="draft.i2v">
                    <option v-for="mode in i2vModes" :key="mode" :value="mode">
                      {{ i2vModeLabel(mode) }}
                    </option>
                  </select>
                </label>
                <label class="drama-voice-kv">
                  <strong>路由</strong>
                  <select v-model="draft.i2v_ladder">
                    <option value="">自动（{{ selected.route?.ladder || '—' }}）</option>
                    <option v-for="lad in ladderOptions" :key="lad.id" :value="lad.id">
                      {{ lad.label }}
                    </option>
                  </select>
                </label>
                <label class="drama-voice-kv">
                  <strong>时长</strong>
                  <input
                    v-model="draft.duration"
                    class="drama-video-duration-input"
                    type="text"
                    inputmode="decimal"
                    placeholder="秒"
                    title="时长（秒，一位小数）"
                  />
                </label>
                <label class="drama-voice-kv">
                  <strong>状态</strong>
                  <select v-model="draft.i2v_source">
                    <option v-for="src in i2vSourceOptions" :key="src.id" :value="src.id">
                      {{ src.label }}
                    </option>
                  </select>
                </label>
              </div>
            </div>
              </div>

              <div class="drama-scene-right">
                <div class="drama-av-preview-panel">
                <div class="drama-av-preview-area">
                  <div class="drama-av-frame">
                    <video
                      v-if="shotVideoPreviewKind(selected) === 'video'"
                      :key="shotVideoPreviewUrl(selected)"
                      class="drama-media"
                      :src="shotVideoPreviewUrl(selected)"
                      controls
                      autoplay
                      muted
                      loop
                      playsinline
                    />
                    <img
                      v-else-if="shotVideoPreviewKind(selected) === 'image'"
                      class="drama-media"
                      :src="shotVideoPreviewUrl(selected)"
                      alt="镜头画面"
                    />
                    <div v-else class="drama-stage-empty">本镜尚未出图或视频，请先在「画面」步骤锁定关键帧</div>
                  </div>
                </div>
              </div>
              <DramaCastChat
                ref="videoChatRef"
                class="drama-scene-chat"
                title="对话改视频"
                :character-name="`Shot ${selected.n}`"
                hint="用自然语言调整运镜、时长、I2V 模式等；保存后可点「生成视频」生效。"
                placeholder="例如：运镜改成缓慢推进，时长改成 4 秒…"
                disabled-placeholder="请先选择镜头"
                pending-label="正在理解并更新…"
                :messages="videoChatMessages"
                :loading="saving"
                @send="onVideoChatSend"
              />
              </div>
            </div>
          </div>

          <div v-else class="drama-cast-empty">
            <p>从左侧选择一镜，查看画面并生成 I2V 视频。</p>
          </div>
        </div>
      </section>

      <!-- ============ 阶段 5：声音 ============ -->
      <section v-else-if="stage === 'voice'" class="drama-stage-panel drama-voice-stage">
        <div class="drama-panel-body drama-scene-layout">
          <div class="drama-scene-sidebar">
            <div class="drama-scene-list">
              <div class="drama-scene-rows">
                <button
                  v-for="shot in shots"
                  :key="shot.n"
                  type="button"
                  class="drama-scene-row"
                  :class="{ active: shot.n === selectedN, ready: shotHasVoice(shot) }"
                  @click="emit('select-shot', shot.n)"
                >
                  <div class="drama-scene-thumb">
                    <DramaThumbImg
                      v-if="shotThumb(shot)"
                      :key="shotThumbKey(shot)"
                      :src="shotThumb(shot)"
                      :alt="`Shot ${shot.n}`"
                      :fetchpriority="shot.n === selectedN ? 'high' : 'low'"
                    />
                    <span v-else class="drama-scene-thumb-empty">{{ shot.n }}</span>
                  </div>
                  <div class="drama-scene-row-body">
                    <span class="drama-scene-row-n">Shot {{ shot.n }}</span>
                    <span class="drama-scene-row-desc">{{ shotVoiceRowDesc(shot) }}</span>
                  </div>
                  <span class="drama-status-dot" :class="shotVoiceStatusClass(shot)">{{ shotVoiceStatusLabel(shot) }}</span>
                </button>
              </div>
              <p v-if="!shots.length" class="drama-empty-hint">暂无分镜，请先在「剧本」步骤生成分镜表。</p>
            </div>
          </div>

          <div v-if="selected" class="drama-scene-detail">
            <div class="drama-scene-detail-head">
              <div class="drama-scene-detail-title">
                <h3>Shot {{ selected.n }}</h3>
              </div>
              <div class="drama-scene-detail-actions">
                <button type="button" class="btn-ghost btn-sm" :disabled="saving || !dirty" @click="emit('save')">
                  {{ saving ? '保存中…' : dirty ? '保存' : '已保存' }}
                </button>
                <button
                  type="button"
                  class="btn-primary btn-sm"
                  :disabled="rendering || !canGenerateVoice"
                  @click="onGenerateVoice"
                >
                  {{ rendering ? '生成中…' : '生成配音' }}
                </button>
              </div>
            </div>

            <div class="drama-scene-body">
              <div class="drama-scene-left">
                <div class="drama-scene-script">
              <div class="drama-voice-script-row">
                <label class="drama-field">
                  字幕
                  <textarea
                    v-model="draft.字幕"
                    class="drama-scene-script-text"
                    rows="3"
                    placeholder="（本镜无台词字幕）"
                  />
                </label>
                <label class="drama-field">
                  旁白
                  <textarea
                    v-model="draft.旁白"
                    class="drama-scene-script-text"
                    rows="3"
                    placeholder="（本镜无旁白）"
                  />
                </label>
              </div>
              <div class="drama-voice-meta-row">
                <label class="drama-voice-kv">
                  <strong>说话人</strong>
                  <select v-model="voiceInspectSpeaker" title="仅查看绑定音色，不会修改分镜">
                    <option value="">（未指定）</option>
                    <option v-for="name in voiceSpeakerOptions" :key="name" :value="name">
                      {{ name }}
                    </option>
                  </select>
                </label>
                <div class="drama-voice-kv">
                  <strong>音色</strong>
                  <span class="drama-voice-readonly">{{ selectedSpeakerVoiceLabel }}</span>
                </div>
                <div class="drama-voice-kv">
                  <strong>口型状态</strong>
                  <span class="drama-voice-readonly">{{ lipStatusLabel(selected) }}</span>
                </div>
                <label class="drama-voice-kv">
                  <strong>配音</strong>
                  <select
                    :value="currentModelKey('tts')"
                    :disabled="saving"
                    @change="onStageModelChange('tts', $event)"
                  >
                    <option
                      v-for="opt in catalogOptions('tts')"
                      :key="`${opt.provider}|${opt.model}`"
                      :value="`${opt.provider}|${opt.model}`"
                    >
                      {{ opt.label }}
                    </option>
                  </select>
                </label>
                <label class="drama-voice-kv">
                  <strong>口型</strong>
                  <select
                    :value="currentModelKey('lip')"
                    :disabled="saving"
                    @change="onStageModelChange('lip', $event)"
                  >
                    <option
                      v-for="opt in catalogOptions('lip')"
                      :key="`${opt.provider}|${opt.model}`"
                      :value="`${opt.provider}|${opt.model}`"
                    >
                      {{ opt.label }}
                    </option>
                  </select>
                </label>
                <div class="drama-voice-kv" :class="identityClass">
                  <strong>身份</strong>
                  <span class="drama-voice-readonly">{{ identityLabel }}</span>
                </div>
              </div>
            </div>
              </div>

              <div class="drama-scene-right">
                <div class="drama-av-preview-panel">
                <div class="drama-av-preview-area">
                  <div class="drama-av-frame drama-voice-frame">
                    <video
                      v-if="shotVoicePreviewKind(selected) === 'video'"
                      :key="shotVoicePreviewUrl(selected)"
                      ref="voiceVideoRef"
                      class="drama-media"
                      :src="shotVoicePreviewUrl(selected)"
                      controls
                      playsinline
                      @play="onVoiceVideoPlaySafe"
                      @pause="onVoiceVideoPauseSafe"
                      @seeked="onVoiceVideoSeekedSafe"
                      @ended="onVoiceVideoEnded"
                      @volumechange="onVoiceVideoVolumeChangeSafe"
                    />
                    <img
                      v-else-if="shotVoicePreviewKind(selected) === 'image'"
                      class="drama-media"
                      :src="shotVoicePreviewUrl(selected)"
                      alt="镜头画面"
                    />
                    <div v-else class="drama-stage-empty">本镜尚未出图；可先在「画面 / 视频」步骤生成</div>
                    <p v-if="selected?.lip_base_mismatch" class="drama-voice-lip-hint">
                      本镜旧口型曾脱离 motion。请重新「生成配音」（会按 motion 重做口型并重装 clip），否则前半段容易音画错位。
                    </p>
                    <div
                      v-if="voiceNarrationText()"
                      class="drama-voice-sub-layer drama-voice-sub-layer--narration"
                      aria-hidden="true"
                    >
                      <p class="drama-voice-sub-text drama-voice-sub-text--narration">
                        {{ voiceNarrationText() }}
                      </p>
                    </div>
                    <div
                      v-if="voiceDialogueCaption()"
                      class="drama-voice-sub-layer drama-voice-sub-layer--dialogue"
                      aria-hidden="true"
                    >
                      <p class="drama-voice-sub-text drama-voice-sub-text--dialogue">
                        {{ voiceDialogueCaption() }}
                      </p>
                    </div>
                  </div>
                </div>
                <audio
                  v-if="shotVoiceNeedsExternalAudio(selected)"
                  :key="shotVoiceAudioUrl(selected)"
                  ref="voiceAudioRef"
                  class="drama-voice-audio-hidden"
                  :src="shotVoiceAudioUrl(selected)"
                  preload="auto"
                  @loadeddata="syncVoiceVolumeFromVideo"
                  @play="onVoiceAudioPlay"
                  @pause="onVoiceAudioPause"
                  @ended="onVoiceAudioEnded"
                />
              </div>
              <DramaCastChat
                ref="voiceChatRef"
                class="drama-scene-chat"
                title="对话改配音"
                :character-name="`Shot ${selected.n}`"
                hint="用自然语言改字幕或旁白；保存后可点「生成配音」生效。说话人用上方下拉选择，音色只读跟随角色卡。"
                placeholder="例如：字幕改成更狠一点，旁白删掉…"
                disabled-placeholder="请先选择镜头"
                pending-label="正在理解并更新…"
                :messages="voiceChatMessages"
                :loading="saving"
                @send="onVoiceChatSend"
              />
              </div>
            </div>
          </div>

          <div v-else class="drama-cast-empty">
            <p>从左侧选择一镜，查看字幕台词并生成配音与口型。</p>
          </div>
        </div>
      </section>

      <!-- ============ 阶段 6：成片 ============ -->
      <section v-else-if="stage === 'assemble'" class="drama-stage-panel drama-assemble-stage">
        <div class="drama-panel-body drama-assemble-body">
          <div class="drama-assemble-main">
            <div class="drama-assemble-preview-panel">
              <div class="drama-assemble-preview-area">
                <div class="drama-assemble-frame">
                  <video
                    v-if="episode?.play_url"
                    :key="episodePreviewUrl"
                    class="drama-media"
                    :src="episodePreviewUrl"
                    controls
                    playsinline
                  />
                  <div v-else class="drama-stage-empty">
                    导出后在此预览整集
                    <span>右侧配好 BGM 后点「导出整集」</span>
                  </div>
                </div>
              </div>
              <div class="drama-assemble-status" :class="assembleStatusClass">
                <dl class="drama-assemble-status-kv">
                  <div>
                    <dt>镜头</dt>
                    <dd>{{ assembleMeta.shotCount }}</dd>
                  </div>
                  <div>
                    <dt>时长</dt>
                    <dd>{{ assembleMeta.durationLabel }}</dd>
                  </div>
                  <div>
                    <dt>配乐</dt>
                    <dd>{{ assembleMeta.hasBgm ? assembleMeta.bgmTitle || '已挂载' : '未挂' }}</dd>
                  </div>
                  <div>
                    <dt>版权</dt>
                    <dd :class="{ 'drama-warn': mixUnlicensed }">
                      {{ mixUnlicensed ? '未授权' : assembleMeta.hasBgm ? '可用' : '—' }}
                    </dd>
                  </div>
                </dl>
              </div>
            </div>

            <aside class="drama-assemble-side">
              <p class="drama-assemble-side-lead">
                配乐只在整集导出时混入，不会烧进各镜 clip。换曲后点「应用混音」即可试听，无需重渲分镜。
              </p>
              <div class="drama-assemble-toolbar">
                <label class="drama-assemble-inline drama-assemble-inline--catalog">
                  <span>曲库</span>
                  <select v-model="mixDraft.catalog_id" @change="onCatalogChange">
                    <option value="">— 自选 / 上传 —</option>
                    <option v-for="t in catalogTracks" :key="t.id" :value="t.id">
                      {{ t.title }}{{ t.mood ? ` · ${t.mood}` : '' }}
                    </option>
                  </select>
                </label>
                <button type="button" class="btn-ghost btn-sm" :disabled="saving || rendering" @click="bgmInput?.click()">
                  上传
                </button>
                <button
                  type="button"
                  class="btn-ghost btn-sm"
                  :disabled="saving || rendering || !mix?.has_bgm"
                  @click="emit('clear-bgm')"
                >
                  清除
                </button>
                <span class="drama-assemble-file-name" :title="mix?.bgm?.title || ''">
                  {{ mix?.bgm?.title || '未挂配乐' }}
                </span>
                <label class="drama-check drama-assemble-check">
                  <input v-model="mixDraft.license_ok" type="checkbox" />
                  商用权
                </label>
                <label class="drama-assemble-inline drama-assemble-inline--slider">
                  <span>音量</span>
                  <input v-model.number="mixDraft.volume" type="range" min="0" max="1" step="0.01" />
                  <em>{{ Number(mixDraft.volume ?? 0.22).toFixed(2) }}</em>
                </label>
                <label class="drama-assemble-inline drama-assemble-inline--slider">
                  <span>闪避</span>
                  <input v-model.number="mixDraft.duck_db" type="range" min="-24" max="0" step="0.5" />
                  <em>{{ Number(mixDraft.duck_db ?? -12).toFixed(1) }}</em>
                </label>
                <input ref="bgmInput" class="drama-file" type="file" accept="audio/*" @change="onBgmFile" />
              </div>
              <p v-if="selectedCatalogTrack?.notes" class="drama-assemble-track-hint">
                {{ selectedCatalogTrack.notes }}
              </p>
              <audio v-if="bgmPreviewUrl" class="drama-audio drama-assemble-audio" :src="bgmPreviewUrl" controls />
              <p v-else-if="!catalogTracks.length" class="drama-empty-hint">
                曲库加载中或为空；也可点「上传」使用自有 BGM。
              </p>
              <p v-if="mixUnlicensed" class="drama-empty-hint drama-warn">
                {{ mix?.license?.reason || '无版权曲子禁止导出' }}
              </p>
            </aside>
          </div>
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
        <li><strong>2. 剧本</strong> 对话生成或编写剧本与分镜</li>
        <li><strong>3. 一路生成</strong> 角色 → 画面 → 视频 → 声音 → 成片</li>
      </ol>
    </div>

    <div v-if="project" class="drama-script-status">
      <DramaProgressStatusBar
        :pct="statusBar.pct"
        :status="statusBar.status"
        :title="statusBar.title"
        :message="statusBar.message"
      />
    </div>

  </main>
</template>
