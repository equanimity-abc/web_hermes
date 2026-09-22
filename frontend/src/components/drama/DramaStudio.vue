<script setup>
import { computed, onMounted, onUnmounted, ref, watch } from 'vue'
import DramaThumbImg from '@/components/drama/DramaThumbImg.vue'
import DramaProgressStatusBar from '@/components/drama/DramaProgressStatusBar.vue'
import DramaScriptFileSummary from '@/components/drama/DramaScriptFileSummary.vue'
import { normalizeRefSize } from '@/utils/dramaRefSizes'

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
  busyCharacterIds: { type: Array, default: () => [] },
  busyShotNs: { type: Array, default: () => [] },
  videoGenProgress: { type: Object, default: null },
  error: { type: String, default: '' },
  notice: { type: String, default: '' },
  bust: { type: Number, default: 0 },
  scriptDraft: { type: String, default: '' },
  scriptImpact: { type: Object, default: null },
  scriptWorkspace: { type: Object, default: null },
  scriptWorkspaceDrafts: { type: Object, default: () => ({}) },
  scriptWorkspaceDirty: { type: Object, default: () => ({}) },
  scriptWorkspaceKey: { type: String, default: 'series_pack' },
  scriptWorkspaceLoading: { type: Boolean, default: false },
  scriptWorkspaceLabels: { type: Object, default: () => ({}) },
  scriptChatLoading: { type: Boolean, default: false },
  scriptChatProgress: { type: Object, default: null },
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
  'save-script-workspace-current',
  'save-script-workspace-all',
  'select-script-workspace-key',
  'update-script-workspace-content',
  'reload-script-workspace',
  'script-chat-send',
  'enter-script-stage',
  'select-character',
  'add-character',
  'save-character',
  'lock-ref',
  'delete-character',
  'generate-character-ref',
  'generate-all-refs',
  'generate-all-scenes',
  'toggle-role',
  'upload-scene',
  'generate-i2v',
  'generate-all-video',
  'generate-lip',
  'generate-all-voice',
  'set-manual-voice',
  'generate-keys',
  'choose-key',
  'upload-key',
  'lock-key',
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
  'start-new-drama',
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
])

const stage = ref('script')
const keyInput = ref(null)
const bgmInput = ref(null)
const voiceVideoRef = ref(null)
const voiceAudioRef = ref(null)
const selectedKeyId = ref(null)
const scriptPremiseInput = ref('')
const scriptPremiseRef = ref(null)
/** raw = 原文直接展示；summary = 关键信息 */
const scriptFileViewMode = ref('summary')

const hasLayer = (layer) => (props.shots || []).some((s) => s.files?.[layer]?.exists)

const manualVoice = computed(() => Boolean(props.project?.project?.manual_voice))

const stageList = computed(() => [
  { id: 'script', label: '剧本', title: '步骤一：结构化剧本（角色/场景/道具/配乐/分镜）', done: Boolean(props.episode?.script) },
  { id: 'cast', label: '资产', title: '步骤二：资产管理（角色 / 道具 / 场景）', done: (props.characters || []).some((c) => c.ref_exists) },
  { id: 'scene', label: '画面', title: '步骤三：Seedream 分镜静帧', done: hasLayer('scene') },
  {
    id: 'video',
    label: '视频',
    title: manualVoice.value
      ? '步骤四：Seedance 图生视频（手动配音开 → 先 TTS 再挂参考音频）'
      : '步骤四：Seedance 图生视频（默认模型自带声）',
    done: hasLayer('motion') || (props.shots || []).some((s) => ['ai', 'keys', 'fallback'].includes(s.i2v_source)),
  },
  { id: 'assemble', label: '成片', title: '步骤五：拼接、BGM 与导出', done: Boolean(props.episode?.play_url) },
])

const scriptWorkspaceTabs = computed(() => {
    const keys = props.scriptWorkspace?.keys || ['series_pack', 'project', 'characters', 'shots']
  const labels = props.scriptWorkspaceLabels || {}
  const epLabel = `ep${String(props.episodeN || 1).padStart(2, '0')}.md`
  return keys.map((key) => {
    const file = props.scriptWorkspace?.files?.[key]
    let label = labels[key] || file?.label || key
    if (key === 'script') {
      const base = String(file?.path || '').split('/').pop()
      label = base && base.endsWith('.md') ? base : epLabel
    }
    return {
      key,
      label,
      path: file?.path || '',
      dirty: Boolean(props.scriptWorkspaceDirty?.[key]),
    }
  })
})

const activeWorkspaceFile = computed(() => props.scriptWorkspace?.files?.[props.scriptWorkspaceKey] || null)

const activeWorkspaceContent = computed({
  get() {
    return props.scriptWorkspaceDrafts?.[props.scriptWorkspaceKey] ?? ''
  },
  set(v) {
    emit('update-script-workspace-content', { key: props.scriptWorkspaceKey, content: v })
  },
})

const workspaceDirtyCount = computed(
  () => Object.values(props.scriptWorkspaceDirty || {}).filter(Boolean).length,
)

watch(
  () => props.scriptWorkspaceKey,
  () => {
    // 换文件时默认回到关键信息，便于扫读
    scriptFileViewMode.value = 'summary'
  },
)

const castCategory = ref('character')
const CAST_TABS = [
  { id: 'character', label: '角色' },
  { id: 'prop', label: '道具' },
  { id: 'scene', label: '场景' },
]
/** 左侧竖排分组：默认展开「角色」，道具/场景可折叠 */
const castSectionOpen = ref({
  character: true,
  prop: false,
  scene: false,
})
const CAST_REF_MODELS = [
  { provider: 'seedream', model: 'doubao-seedream-5-0-pro-260628', label: '方舟 · Seedream 5.0 Pro' },
  { provider: 'kling-image', model: 'kling/kling-v3-omni-image-generation', label: '可灵 · Kling V3 Omni' },
  { provider: 'wanx', model: 'qwen-image-plus', label: '百炼 · Qwen-Image-Plus' },
]

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

function onGenerateScript() {
  const text = String(scriptPremiseInput.value || '').trim()
  if (!text || props.scriptChatLoading || props.saving) return
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

const castAssets = computed(() =>
  (props.characters || []).filter((c) => (c.category || 'character') === castCategory.value),
)

function castAssetsOf(category) {
  return (props.characters || []).filter((c) => (c.category || 'character') === category)
}

function toggleCastSection(category) {
  const next = !castSectionOpen.value[category]
  castSectionOpen.value = { ...castSectionOpen.value, [category]: next }
  if (next) {
    castCategory.value = category
    const list = castAssetsOf(category)
    const ids = new Set(list.map((c) => c.id))
    if (!ids.has(props.selectedCharacterId)) {
      emit('select-character', list[0]?.id || null)
    }
  }
}

function openCastSection(category) {
  castCategory.value = category
  castSectionOpen.value = { ...castSectionOpen.value, [category]: true }
}

function castAssetUrl(url) {
  if (!url) return ''
  return `${url}${url.includes('?') ? '&' : '?'}_=${props.bust || 0}`
}

watch(
  () => props.charDraft?.category,
  (cat) => {
    if (!props.charDraft) return
    const next = normalizeRefSize(props.charDraft.ref_size, cat)
    if (Number(props.charDraft.ref_size) !== next) {
      props.charDraft.ref_size = next
    }
  },
)

// 单图出画面（files.scene），无候选墙。
const sceneFallbackUrl = computed(() => {
  const scene = props.selected?.files?.scene
  if (!scene?.exists || !scene?.url) return ''
  const url = String(scene.url)
  return `${url}${url.includes('?') ? '&' : '?'}_=${props.bust || 0}`
})

watch(castCategory, () => {
  const ids = new Set(castAssets.value.map((c) => c.id))
  if (props.selectedCharacterId && ids.has(props.selectedCharacterId)) return
  emit('select-character', castAssets.value[0]?.id || null)
})

watch(
  () => props.selectedCharacter?.category || props.selectedCharacter?.id,
  () => {
    const cat = props.selectedCharacter?.category || 'character'
    if (!CAST_TABS.some((t) => t.id === cat)) return
    if (castCategory.value !== cat) castCategory.value = cat
    if (!castSectionOpen.value[cat]) {
      castSectionOpen.value = { ...castSectionOpen.value, [cat]: true }
    }
  },
)

const stageBoardMap = {
  script: 'script',
  cast: 'cast',
  scene: 'shots',
  video: 'shots',
  assemble: 'timeline',
}
const stageIndex = computed(() => stageList.value.findIndex((s) => s.id === stage.value))
const currentStage = computed(() => stageList.value[stageIndex.value] || stageList.value[0])
const nextStage = computed(() => stageList.value[stageIndex.value + 1] || null)

function goStage(id) {
  // 旧深链 stage=voice → 视频页（配音已并入）
  const next = id === 'voice' ? 'video' : id
  stage.value = next
  emit('update:boardMode', stageBoardMap[next] || 'shots')
}
function goNext() {
  if (nextStage.value) goStage(nextStage.value.id)
}

const STAGE_IDS = new Set(['script', 'cast', 'scene', 'video', 'voice', 'assemble'])

function onToggleManualVoice(ev) {
  emit('set-manual-voice', Boolean(ev?.target?.checked))
}

function applyDeepLink(hash = window.location.hash || '') {
  const raw = String(hash || '').replace(/^#/, '')
  if (!raw) return
  const params = new URLSearchParams(raw.includes('=') ? raw : '')
  // also support #shot=3&stage=scene
  const shot = Number(params.get('shot') || 0)
  const st = String(params.get('stage') || '').trim()
  if (st && STAGE_IDS.has(st)) goStage(st)
  if (shot > 0) emit('select-shot', shot)
}

function onHashChange() {
  applyDeepLink(window.location.hash)
}

onMounted(() => {
  applyDeepLink(window.location.hash)
  window.addEventListener('hashchange', onHashChange)
})
onUnmounted(() => {
  window.removeEventListener('hashchange', onHashChange)
})

function focusScriptPremise() {
  scriptPremiseRef.value?.focus?.()
}

defineExpose({ goStage, focusScriptChat: focusScriptPremise, focusScriptPremise })

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
const facePreviewUrl = computed(() => {
  const url = props.selectedCharacter?.ref_face_url || ''
  if (!url) return ''
  return `${url}${url.includes('?') ? '&' : '?'}_=${props.bust || 0}`
})

const platePreviewUrl = computed(() => {
  const url = props.selectedCharacter?.ref_plate_url || ''
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
function shotThumb(shot) {
  if (!shot) return ''
  const sceneUrl = shot?.files?.scene?.url
  if (sceneUrl && shot?.files?.scene?.exists) {
    return withBust(assetThumb(sceneUrl))
  }
  return withBust(assetThumb(shot?.preview_url || ''))
}
function shotThumbKey(shot) {
  if (!shot) return ''
  return `${shot.n}-${shot.files?.scene?.bytes || 0}`
}
function isGeneratingCandidates(n) {
  return (props.generatingCandidateNs || []).includes(n)
}
function isCharacterBusy(cid) {
  return (props.busyCharacterIds || []).includes(String(cid || ''))
}
function isShotBusy(n) {
  const sn = Number(n)
  return (props.busyShotNs || []).includes(sn) || isGeneratingCandidates(sn)
}
const selectedCharacterBusy = computed(() => isCharacterBusy(props.selectedCharacterId))
const selectedShotBusy = computed(() => isShotBusy(props.selectedN))
function preloadImage(url) {
  if (!url || preloaded.has(url)) return
  preloaded.add(url)
  const img = new Image()
  img.decoding = 'async'
  img.src = url
}
function sceneLocked(shot) {
  return (shot?.locked || []).includes('scene')
}
const sceneFileInput = ref(null)
function onSceneFile(e) {
  const file = e.target?.files?.[0]
  if (file) emit('upload-scene', file)
  if (e.target) e.target.value = ''
}
function shotStatusLabel(shot) {
  if (isShotBusy(shot.n)) return '…'
  const locked = shot.locked || []
  if (locked.includes('shot')) return '锁'
  if (sceneLocked(shot)) return '锁'
  if (shot.files?.clip?.exists) return '成'
  if (shot.files?.scene?.exists) return '图'
  return '待'
}
function shotStatusClass(shot) {
  if (isShotBusy(shot.n)) return 'is-busy'
  const locked = shot.locked || []
  if (locked.includes('shot')) return 'is-locked'
  if (sceneLocked(shot)) return 'is-locked'
  if (shot.files?.clip?.exists) return 'is-done'
  if (shot.files?.scene?.exists) return 'is-scene'
  return 'is-todo'
}
function isLocked(layer) {
  return (props.selected?.locked || []).includes(layer)
}
const shotFrozen = computed(() => isLocked('shot'))
const canGenerateI2v = computed(() => {
  const shot = props.selected
  if (!shot) return false
  const mode = props.draft?.i2v || shot.i2v || 'auto'
  if (mode === 'off') return false
  // 有关键帧即可生成；auto 下后端会自动锁 scene
  return Boolean(shot.files?.scene?.exists)
})
const canGenerateLip = computed(() => Boolean(props.selected?.lip?.ok || props.selected?.lip?.will_run))
const canGenerateKeys = computed(() => Boolean(props.selected?.keys_gate?.ok || props.selected?.keys_gate?.will_run))
const selectedKey = computed(() => {
  const keys = props.selected?.keys || []
  return keys.find((k) => k.id === selectedKeyId.value) || keys[0] || null
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
  // 视频页优先表演母带 motion；空镜（L0，专业档无 Ken Burns）无 motion 时回退成片 clip，再回退静态画面。
  if (!shot) return ''
  const url = shot.files?.motion?.url || shot.files?.clip?.url || shot.files?.scene?.url || ''
  return url ? withBust(url) : ''
}

function shotVoicePreviewUrl(shot) {
  // 声音页优先口型母带：clip 在 lip_source 丢失时可能退化成未对嘴的 motion 垫长片
  if (!shot) return ''
  if (shotHasLip(shot) && !shot.lip_base_used && shot.files?.lip?.url) {
    return withBust(shot.files.lip.url)
  }
  if (shot.files?.clip?.exists && shot.files?.clip?.url) {
    return withBust(shot.files.clip.url)
  }
  const url = shot.files?.motion?.url || shot.files?.scene?.url || shot.files?.lip?.url || ''
  return url ? withBust(url) : ''
}

function shotVoiceNeedsExternalAudio(shot) {
  if (!shot) return false
  // 口型预览：优先外挂配音，避免 provider 内嵌音轨与口型轻微错位
  if (shotHasLip(shot) && !shot.lip_base_used && shot.files?.lip?.exists) {
    return Boolean(shotVoiceAudioUrl(shot))
  }
  // clip 自带音轨
  if (shot.files?.clip?.exists) return false
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
  if (isShotBusy(shot.n) || isVideoGeneratingShot(shot.n)) return '…'
  const locked = shot.locked || []
  if (locked.includes('shot')) return '锁'
  const src = shot.i2v_source || ''
  if (src === 'ai' || src === 'keys') return '动'
  if (src === 'fallback') return '运'
  if (shot.files?.clip?.exists) return '成'
  if (shot.files?.motion?.exists) return '动'
  if (sceneLocked(shot)) return '图'
  if (shot.files?.scene?.exists) return '图'
  return '待'
}

function shotVideoStatusClass(shot) {
  if (isShotBusy(shot.n) || isVideoGeneratingShot(shot.n)) return 'is-busy'
  const locked = shot.locked || []
  if (locked.includes('shot')) return 'is-locked'
  const src = shot.i2v_source || ''
  if (src === 'ai' || src === 'keys') return 'is-done'
  if (shot.files?.clip?.exists) return 'is-done'
  if (shot.files?.motion?.exists) return 'is-scene'
  if (sceneLocked(shot)) return 'is-locked'
  if (shot.files?.scene?.exists) return 'is-scene'
  return 'is-todo'
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

const seriesEpisodeOptions = computed(() => {
  const n = Number(props.project?.project?.series?.episode_count || 0)
  if (!Number.isFinite(n) || n < 2) return []
  return Array.from({ length: Math.min(20, Math.floor(n)) }, (_, i) => ({
    n: i + 1,
    title: `第${i + 1}集`,
  }))
})

// 预加载候选缩略图
watch(
  () => props.shots,
  (rows) => {
    for (const shot of rows || []) {
      const thumb = shotThumb(shot)
      if (thumb) preloadImage(thumb)
    }
  },
  { deep: true },
)

function onGenerateVideo() {
  emit('generate-i2v')
}

function onGenerateAllVideo() {
  emit('generate-all-video')
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
    'seedance',
    'ai',
    'pixverse',
    'pixverse-lipsync',
    'latentsync',
    'musetalk',
    'wav2lip',
    'recovered',
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
  if (isShotBusy(shot.n)) return '…'
  const locked = shot.locked || []
  if (locked.includes('shot') || locked.includes('voice')) return '锁'
  if (shotHasLip(shot)) return '口'
  if (shotHasVoice(shot)) return '音'
  if ((shot.字幕 || shot.对白 || '').trim()) return '待'
  return '—'
}

function shotVoiceStatusClass(shot) {
  if (isShotBusy(shot.n)) return 'is-busy'
  const locked = shot.locked || []
  if (locked.includes('shot') || locked.includes('voice')) return 'is-locked'
  if (shotHasLip(shot)) return 'is-done'
  if (shotHasVoice(shot)) return 'is-scene'
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
  // 旁白 = 画外说明（左上角竖排）；展示时去掉心声前缀与「无」占位
  let text = String(props.draft?.旁白 || '').trim()
  if (!text || /^(无|没有|无。|无旁白|暂无|空|none|n\/a|-|—|–|\/|（无）|\(无\))$/i.test(text)) {
    return ''
  }
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

function onVoiceVideoPlay() {
  const video = voiceVideoRef.value
  const audio = voiceAudioRef.value
  if (!audio) return
  if (video) video.muted = true
  // 同一时间轴：外挂配音与口型画面都从当前画面时刻起算（开播时对齐到同一 PTS）
  syncVoiceVolumeFromVideo()
  syncVoiceAudioToVideo()
  audio.play().catch(() => {})
}

function syncVoiceAudioToVideo() {
  const video = voiceVideoRef.value
  const audio = voiceAudioRef.value
  if (!video || !audio) return
  const vt = Number(video.currentTime) || 0
  const at = Number(audio.currentTime) || 0
  // 更紧的对齐阈值：口型与声音共用同一时钟，偏差超过一帧就拉齐
  if (Math.abs(at - vt) > 0.04) {
    try {
      audio.currentTime = vt
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
      seedance: 'Seedance · 口型内生',
      musetalk: 'MuseTalk',
      wav2lip: 'Wav2Lip',
      http: '网关口型',
      ai: 'AI 口型',
      mock: '占位波形（非真口型）',
    }
    const base = map[src] || src || '已生成'
    label = base
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

// 全局底部状态栏：错误优先，再按当前步骤返回进度 / 状态 / 标题 / 消息。
const statusBar = computed(() => {
  const err = String(props.error || '').trim()
  if (err) {
    return {
      pct: 0,
      status: 'error',
      title: '失败',
      message: err,
    }
  }
  const notice = String(props.notice || '').trim()
  let base
  switch (stage.value) {
    case 'script':
      base = {
        pct: scriptStatusPct.value,
        status: props.scriptChatProgress?.status || 'idle',
        title: scriptStatusTitle.value,
        message: props.scriptChatProgress?.message || '就绪',
      }
      break
    case 'cast': {
      const list = props.characters || []
      const withRef = list.filter((c) => c.ref_exists).length
      base = {
        pct: list.length ? Math.round((withRef / list.length) * 100) : 0,
        status: list.length && withRef === list.length ? 'done' : 'idle',
        title: '资产',
        message: list.length ? `资产图 ${withRef}/${list.length}` : '暂无资产',
      }
      break
    }
    case 'scene': {
      const gen = props.generatingCandidateNs || []
      base = {
        pct: gen.length ? 40 : 0,
        status: gen.length ? 'running' : 'idle',
        title: '画面',
        message: gen.length ? `正在生成 ${gen.length} 个候选图…` : '候选项待生成',
      }
      break
    }
    case 'video':
      base = {
        pct: videoProgressPct.value,
        status: props.videoGenProgress?.status || (props.rendering && manualVoice.value ? voiceStatusState.value : 'idle'),
        title: videoStatusTitle.value,
        message: manualVoice.value && voiceStatusState.value === 'running'
          ? voiceStatusLabel.value
          : videoStatusLabel.value,
      }
      break
    case 'assemble':
      base = {
        pct: assembleStatusPct.value,
        status: assembleStatusState.value,
        title: assembleStatusTitle.value,
        message: assembleStatusLabel.value,
      }
      break
    default:
      base = { pct: 0, status: 'idle', title: '状态', message: '就绪' }
  }
  // 无进行中任务时，用 notice 覆盖默认文案（如「已保存」）
  if (notice && base.status !== 'running' && base.status !== 'pending') {
    return { ...base, message: notice }
  }
  return base
})
</script>

<template>
  <main class="drama-studio">
    <header class="drama-top">
      <div class="drama-top-head">
        <div class="drama-top-title">
          <h1>{{ project?.project?.title || '漫剧工作台' }}</h1>
        </div>
        <div v-if="episodes.length > 1 || Number(project?.project?.series?.episode_count || 0) > 1" class="drama-ep-select">
          <label class="drama-ep-label">
            <span class="drama-ep-label-text">集数</span>
            <select class="drama-ep-dropdown" :value="episodeN" @change="onEpisodeChange">
              <option
                v-for="ep in (episodes.length ? episodes : seriesEpisodeOptions)"
                :key="ep.n"
                :value="ep.n"
              >
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
        <template v-if="stage === 'scene'">
          <button type="button" class="btn-ghost btn-sm" :disabled="rendering || !shots.length" @click="onGenerateAllScenes">
            {{ rendering ? '生成中…' : '批量出图' }}
          </button>
        </template>
        <template v-else-if="stage === 'video'">
          <label class="drama-manual-voice-toggle" title="关闭：Seedance 自带声；打开：先手动配音再图生视频">
            <input type="checkbox" :checked="manualVoice" :disabled="saving || rendering" @change="onToggleManualVoice" />
            手动配音
          </label>
          <button
            v-if="manualVoice"
            type="button"
            class="btn-ghost btn-sm"
            :disabled="rendering || !shots.length"
            @click="onGenerateAllVoice"
          >
            {{ rendering ? '生成中…' : '批量配音' }}
          </button>
          <button type="button" class="btn-ghost btn-sm" :disabled="rendering || !shots.length" @click="onGenerateAllVideo">
            {{ rendering ? '生成中…' : '批量生成视频' }}
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
                  <span class="drama-script-panel-title">剧本产物</span>
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
                      :disabled="saving || scriptWorkspaceLoading || !episodeN"
                      @click="emit('reload-script-workspace')"
                    >
                      {{ scriptWorkspaceLoading ? '加载中…' : '刷新' }}
                    </button>
                    <button
                      type="button"
                      class="btn-ghost btn-sm"
                      :disabled="saving || !episodeN"
                      @click="emit('save-script-workspace-current')"
                    >
                      {{ saving ? '保存中…' : '保存当前' }}
                    </button>
                    <button
                      type="button"
                      class="btn-primary btn-sm"
                      :disabled="saving || !episodeN || workspaceDirtyCount < 1"
                      @click="emit('save-script-workspace-all')"
                    >
                      {{ saving ? '保存中…' : workspaceDirtyCount ? `保存全部(${workspaceDirtyCount})` : '保存全部' }}
                    </button>
                  </div>
                </div>

                <div class="drama-script-workspace">
                  <nav class="drama-script-file-tabs" aria-label="剧本产物文件">
                    <button
                      v-for="tab in scriptWorkspaceTabs"
                      :key="tab.key"
                      type="button"
                      class="drama-script-file-tab"
                      :class="{ active: tab.key === scriptWorkspaceKey, dirty: tab.dirty }"
                      :title="tab.path || tab.label"
                      @click="emit('select-script-workspace-key', tab.key)"
                    >
                      {{ tab.label }}<span v-if="tab.dirty"> *</span>
                    </button>
                  </nav>
                  <div class="drama-script-view-sheet" role="tablist" aria-label="展示方式">
                    <button
                      type="button"
                      role="tab"
                      class="drama-script-view-sheet-btn"
                      :class="{ active: scriptFileViewMode === 'summary' }"
                      :aria-selected="scriptFileViewMode === 'summary'"
                      @click="scriptFileViewMode = 'summary'"
                    >
                      关键信息
                    </button>
                    <button
                      type="button"
                      role="tab"
                      class="drama-script-view-sheet-btn"
                      :class="{ active: scriptFileViewMode === 'raw' }"
                      :aria-selected="scriptFileViewMode === 'raw'"
                      @click="scriptFileViewMode = 'raw'"
                    >
                      原文
                    </button>
                  </div>
                  <p v-if="activeWorkspaceFile?.path" class="drama-script-file-path">
                    {{ activeWorkspaceFile.path }}
                    <span v-if="!activeWorkspaceFile.exists" class="drama-script-file-missing">（尚未落盘）</span>
                  </p>
                  <p v-if="!episodeN" class="drama-script-outline-empty drama-script-structured-empty">
                    请先生成剧本或打开已有分集，以加载剧本产物文件。
                  </p>
                  <div v-else-if="scriptFileViewMode === 'summary'" class="drama-script-summary-pane">
                    <DramaScriptFileSummary
                      :file-key="scriptWorkspaceKey"
                      :content="activeWorkspaceContent"
                      :path="activeWorkspaceFile?.path || ''"
                    />
                  </div>
                  <textarea
                    v-else
                    class="drama-script-editor drama-script-workspace-editor"
                    :value="activeWorkspaceContent"
                    spellcheck="false"
                    rows="22"
                    :disabled="saving || scriptWorkspaceLoading"
                    :placeholder="`编辑 ${activeWorkspaceFile?.label || scriptWorkspaceKey} 内容后点保存落盘`"
                    @input="activeWorkspaceContent = $event.target.value"
                  />
                </div>
              </div>
            </div>

            <div class="drama-script-gen-col">
              <div class="drama-script-gen-bar">
                <textarea
                  ref="scriptPremiseRef"
                  v-model="scriptPremiseInput"
                  class="drama-script-gen-input"
                  rows="4"
                  :disabled="!project || saving || scriptChatLoading"
                  placeholder="一句话生成剧本，比如：废柴少年觉醒神瞳逆袭宗门，共3集，每集20秒，集末留悬念"
                  @keydown.enter.exact.prevent="onGenerateScript"
                />
                <button
                  type="button"
                  class="btn-primary drama-script-gen-btn"
                  :disabled="!project || saving || scriptChatLoading || !String(scriptPremiseInput || '').trim()"
                  @click="onGenerateScript"
                >
                  {{ scriptChatLoading ? '生成中…' : '生成剧本' }}
                </button>
              </div>
            </div>
          </div>
        </div>
      </section>

      <!-- ============ 阶段 2：定妆资产 ============ -->
      <section v-else-if="stage === 'cast'" class="drama-stage-panel drama-cast-stage">
        <div class="drama-panel-body drama-scene-layout drama-cast-layout">
          <div class="drama-cast-sidebar">
            <div class="drama-cast-sections">
              <div
                v-for="tab in CAST_TABS"
                :key="tab.id"
                class="drama-cast-section"
                :class="{ open: castSectionOpen[tab.id], active: castCategory === tab.id }"
              >
                <button
                  type="button"
                  class="drama-cast-section-head"
                  :aria-expanded="castSectionOpen[tab.id] ? 'true' : 'false'"
                  @click="toggleCastSection(tab.id)"
                >
                  <span class="drama-cast-section-chevron" aria-hidden="true">{{ castSectionOpen[tab.id] ? '▾' : '▸' }}</span>
                  <span class="drama-cast-section-label">{{ tab.label }}</span>
                  <span class="drama-cast-section-count">{{ castAssetsOf(tab.id).length }}</span>
                </button>
                <div v-show="castSectionOpen[tab.id]" class="drama-cast-section-body">
                  <div v-if="tab.id === 'character'" class="drama-cast-rows">
                    <div
                      v-for="item in castAssetsOf(tab.id)"
                      :key="item.id"
                      class="drama-cast-row"
                      :class="{ active: item.id === selectedCharacterId, busy: isCharacterBusy(item.id) }"
                    >
                      <button
                        type="button"
                        class="drama-cast-row-main"
                        @click="openCastSection(tab.id); emit('select-character', item.id)"
                      >
                        <div class="drama-cast-avatar">
                          <img v-if="item.ref_url" :src="castAssetUrl(item.ref_url)" :alt="item.name" />
                          <span v-else class="drama-cast-avatar-empty">{{ (item.name || item.id || '?').slice(0, 1) }}</span>
                        </div>
                        <span class="drama-cast-row-name">{{ item.name || item.id }}</span>
                        <span v-if="isCharacterBusy(item.id)" class="drama-cast-row-lock" title="处理中">…</span>
                        <span v-else-if="item.ref_exists" class="drama-cast-row-lock" title="已有定妆">✓</span>
                      </button>
                      <button
                        type="button"
                        class="btn-tiny drama-cast-row-gen"
                        :disabled="isCharacterBusy(item.id)"
                        :title="isCharacterBusy(item.id) ? '生成中' : '重新生成'"
                        @click.stop="openCastSection(tab.id); emit('generate-character-ref', item.id)"
                      >
                        {{ isCharacterBusy(item.id) ? '…' : '重生成' }}
                      </button>
                    </div>
                  </div>
                  <div v-else class="drama-cast-folder-grid">
                    <button
                      v-for="item in castAssetsOf(tab.id)"
                      :key="item.id"
                      type="button"
                      class="drama-cast-card"
                      :class="{ active: item.id === selectedCharacterId }"
                      @click="openCastSection(tab.id); emit('select-character', item.id)"
                    >
                      <div class="drama-cast-thumb">
                        <img
                          v-if="item.ref_plate_url || item.ref_url"
                          :src="castAssetUrl(item.ref_plate_url || item.ref_url)"
                          :alt="item.name"
                        />
                        <span v-else class="drama-candidate-empty">无图</span>
                      </div>
                      <span class="drama-cast-name">{{ item.name || item.id }}</span>
                    </button>
                  </div>
                  <p v-if="!castAssetsOf(tab.id).length" class="drama-empty-hint">暂无{{ tab.label }}（由剧本 SeriesPack 物化而来）。</p>
                </div>
              </div>
            </div>
          </div>

          <div
            v-if="selectedCharacter && (selectedCharacter.category || 'character') === castCategory"
            class="drama-scene-detail drama-cast-detail--asset"
          >
            <div class="drama-scene-detail-head">
              <h3>{{ selectedCharacter.name || selectedCharacter.id }}</h3>
              <div class="drama-scene-detail-actions drama-cast-regen-bar">
                <button
                  type="button"
                  class="btn-primary btn-sm"
                  :disabled="selectedCharacterBusy"
                  @click="emit('generate-character-ref', selectedCharacter.id)"
                >
                  {{ selectedCharacterBusy ? '生成中…' : '生成' }}
                </button>
                <button
                  type="button"
                  class="btn-tiny btn-tiny-danger"
                  :disabled="selectedCharacterBusy"
                  @click="emit('delete-character', selectedCharacter.id)"
                >
                  删除
                </button>
              </div>
            </div>

            <div
              class="drama-cast-char-board"
              :class="{ 'drama-cast-char-board--single': castCategory !== 'character' }"
            >
              <template v-if="castCategory === 'character'">
                <article class="drama-cast-char-pane">
                  <header class="drama-cast-char-pane-head">全身定妆</header>
                  <div class="drama-cast-char-preview drama-cast-char-preview--body">
                    <img v-if="refPreviewUrl" :src="refPreviewUrl" alt="全身定妆" />
                    <span v-else class="drama-cast-char-empty">暂无全身定妆</span>
                  </div>
                  <textarea
                    v-model="charDraft.look"
                    class="drama-cast-char-text"
                    rows="5"
                    placeholder="正面全身：年龄感、发型发色、服装主色、独占锚点"
                  />
                </article>
                <article class="drama-cast-char-pane">
                  <header class="drama-cast-char-pane-head">正脸锚点</header>
                  <div class="drama-cast-char-preview drama-cast-char-preview--face">
                    <img v-if="facePreviewUrl" :src="facePreviewUrl" alt="正脸锚点" />
                    <span v-else class="drama-cast-char-empty">尚未生成正脸</span>
                  </div>
                  <textarea
                    v-model="charDraft.look_face"
                    class="drama-cast-char-text"
                    rows="5"
                    placeholder="瞳色 / 眉眼 / 痣 / 耳饰等正脸特征"
                  />
                </article>
              </template>

              <article v-else-if="castCategory === 'scene'" class="drama-cast-char-pane">
                <header class="drama-cast-char-pane-head">场景底板</header>
                <div class="drama-cast-char-preview drama-cast-char-preview--body">
                  <img
                    v-if="platePreviewUrl || refPreviewUrl"
                    :src="platePreviewUrl || refPreviewUrl"
                    alt="场景底板"
                  />
                  <span v-else class="drama-cast-char-empty">暂无场景底板</span>
                </div>
                <textarea
                  v-model="charDraft.look"
                  class="drama-cast-char-text"
                  rows="5"
                  placeholder="无人物竖屏空镜：建筑轮廓、主光、地面材质"
                />
              </article>

              <article v-else class="drama-cast-char-pane">
                <header class="drama-cast-char-pane-head">道具设定</header>
                <div class="drama-cast-char-preview drama-cast-char-preview--prop">
                  <img v-if="refPreviewUrl" :src="refPreviewUrl" alt="道具设定" />
                  <span v-else class="drama-cast-char-empty">暂无道具设定图</span>
                </div>
                <textarea
                  v-model="charDraft.look"
                  class="drama-cast-char-text"
                  rows="5"
                  placeholder="外形、材质、尺寸感、纹样"
                />
              </article>
            </div>
          </div>

          <div v-else class="drama-cast-empty">
            <p>从左侧选择一项查看与重新生成；资产由剧本物化，不在此新建。</p>
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

          <div v-if="selected" class="drama-scene-detail drama-cast-detail--asset">
            <div class="drama-scene-detail-head">
              <h3>Shot {{ selected.n }}</h3>
              <div class="drama-scene-detail-actions drama-cast-regen-bar">
                <button
                  type="button"
                  class="btn-tiny"
                  :disabled="selectedShotBusy || shotFrozen"
                  @click="emit('toggle-lock', 'scene')"
                >
                  {{ sceneLocked(selected) ? '解锁画面' : '锁定画面' }}
                </button>
                <button
                  type="button"
                  class="btn-primary btn-sm"
                  :disabled="selectedShotBusy || shotFrozen"
                  @click="emit('rerender-layer', 'scene')"
                >
                  {{ selectedShotBusy ? '处理中…' : '重做画面' }}
                </button>
                <button
                  type="button"
                  class="btn-tiny"
                  :disabled="selectedShotBusy || shotFrozen"
                  @click="sceneFileInput && sceneFileInput.click()"
                >
                  上传画面
                </button>
                <input
                  ref="sceneFileInput"
                  class="drama-file"
                  type="file"
                  accept="image/*"
                  hidden
                  @change="onSceneFile"
                />
              </div>
            </div>

            <div class="drama-cast-char-board drama-cast-char-board--single drama-shot-board">
              <article class="drama-cast-char-pane">
                <header class="drama-cast-char-pane-head">画面</header>
                <div class="drama-cast-char-preview drama-cast-char-preview--shot">
                  <DramaThumbImg
                    v-if="sceneFallbackUrl"
                    :key="`scene-${selectedN}-${props.bust || 0}`"
                    :src="sceneFallbackUrl"
                    alt="当前画面"
                    loading="eager"
                    fetchpriority="high"
                  />
                  <span v-else class="drama-cast-char-empty">暂无画面</span>
                </div>
                <textarea
                  class="drama-cast-char-text"
                  :value="selected.画面 || ''"
                  rows="4"
                  readonly
                  placeholder="（剧本中尚未填写画面描述）"
                />
              </article>
            </div>
          </div>

          <div v-else class="drama-cast-empty">
            <p>从左侧选择一镜，查看画面描述并重做画面。</p>
          </div>
        </div>
      </section>

      <!-- ============ 阶段 5：视频（Seedance 含口型） ============ -->
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

          <div v-if="selected" class="drama-scene-detail drama-cast-detail--asset">
            <div class="drama-scene-detail-head">
              <h3>Shot {{ selected.n }}</h3>
              <div class="drama-scene-detail-actions drama-cast-regen-bar">
                <button
                  type="button"
                  class="btn-primary btn-sm"
                  :disabled="selectedShotBusy || !canGenerateI2v"
                  @click="onGenerateVideo"
                >
                  {{ isVideoGeneratingShot(selectedN) || (selectedShotBusy && !dirty) ? '生成中…' : '生成' }}
                </button>
              </div>
            </div>

            <div class="drama-cast-char-board drama-cast-char-board--single drama-shot-board">
              <article class="drama-cast-char-pane">
                <header class="drama-cast-char-pane-head">视频预览</header>
                <div class="drama-cast-char-preview drama-cast-char-preview--shot">
                  <video
                    v-if="shotVideoPreviewKind(selected) === 'video'"
                    :key="shotVideoPreviewUrl(selected)"
                    class="drama-shot-media"
                    :src="shotVideoPreviewUrl(selected)"
                    controls
                    autoplay
                    playsinline
                  />
                  <img
                    v-else-if="shotVideoPreviewKind(selected) === 'image'"
                    class="drama-shot-media"
                    :src="shotVideoPreviewUrl(selected)"
                    alt="镜头画面"
                  />
                  <span v-else class="drama-cast-char-empty">暂无视频，请先锁定画面关键帧</span>
                </div>
                <textarea
                  class="drama-cast-char-text"
                  :value="selected.画面 || ''"
                  rows="4"
                  readonly
                  placeholder="（剧本中尚未填写画面描述）"
                />
              </article>
            </div>
          </div>

          <div v-else class="drama-cast-empty">
            <p>从左侧选择一镜，查看画面并生成视频。</p>
          </div>
        </div>
      </section>

      <!-- ============ 阶段：成片 ============ -->
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
    </div>

    <div v-else class="drama-idle">
      <h2>分镜台</h2>
      <ol class="drama-idle-steps">
        <li><strong>1. 新建空项目</strong> 点下方按钮创建空白漫剧，或从左侧打开已有项目</li>
        <li><strong>2. 逐步制作</strong> 按步进器完成剧本 → 资产 → 画面 → 视频 → 成片</li>
        <li><strong>3. 导出成片</strong> 到「成片」阶段拼接并导出</li>
      </ol>
      <button type="button" class="btn-primary drama-idle-cta" @click="emit('start-new-drama')">
        新建空漫剧
      </button>
      <p class="drama-idle-hint">火山方舟单轨：剧本 → 资产 → 画面 → 视频（默认模型自带声）→ 成片</p>
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
