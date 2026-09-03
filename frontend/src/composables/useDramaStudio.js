import { computed, ref, watch } from 'vue'
import * as dramaApi from '@/api/drama'
import { useDramaJobs } from '@/composables/useDramaJobs'

export function useDramaStudio() {
  const projects = ref([])
  const slug = ref(null)
  const project = ref(null)
  const episodeN = ref(null)
  const episode = ref(null)
  const selectedN = ref(null)
  const draft = ref(emptyDraft())
  const saving = ref(false)
  const rendering = ref(false)
  const generatingCandidateNs = ref([])
  const error = ref('')
  const notice = ref('')
  const bust = ref(0)
  const scriptDraft = ref('')
  const scriptImpact = ref(null)
  const boardMode = ref('shots')
  const selectedCharacterId = ref(null)
  const charDraft = ref(emptyCharDraft())
  const castChatHistory = ref({})
  const shotChatHistory = ref({})
  const timelineOrder = ref([])
  const tlDraft = ref(emptyTlDraft())
  const mixDraft = ref(emptyMixDraft())
  const config = ref(null)
  const presets = ref([])
  const selectedConfigNode = ref('script')
  const configNodeDraft = ref('')
  const configNodeList = [
    { id: 'script', label: '脚本' },
    { id: 'image', label: '出图' },
    { id: 'motion', label: '运动' },
    { id: 'lip', label: '口型' },
    { id: 'tts', label: '配音' },
    { id: 'subtitle', label: '字幕' },
    { id: 'bgm', label: 'BGM' },
    { id: 'sfx', label: '音效' },
    { id: 'qc', label: 'QC 阈值' },
  ]
  const selectedShotIds = ref([])
  const snapshots = ref([])
  const snapshotsOpen = ref(false)
  const budgetDraft = ref({ enabled: false, per_episode: 0, warn_at: 0.8 })
  const budgetOpen = ref(false)
  const qcChecklist = ref(null)
  const checklistOpen = ref(false)
  const rejectingAll = ref(false)
  const batchField = ref('camera')
  const batchValue = ref('')
  const batchFields = [
    { id: 'camera', label: '运镜' },
    { id: 'voice', label: '音色' },
    { id: 'kind', label: '镜头类型' },
    { id: 'i2v', label: 'I2V 运动' },
    { id: 'speaker', label: '说话人' },
  ]

  const videoGenProgress = ref(null)
  const batchProgress = ref(null)
  const BATCH_CONCURRENCY = 3

  const {
    jobs: renderJobs,
    activeJobs,
    trackJob,
    waitForJob,
    cancelJob,
    retryJob,
    refreshJobs,
  } = useDramaJobs({
    onTerminal: async (job) => {
      if (slug.value && job.slug === slug.value) {
        bust.value = Date.now()
        try {
          await openEpisode(episodeN.value || job.episode)
        } catch {
          /* ignore refresh errors */
        }
        if (batchProgress.value?.jobId && batchProgress.value.jobId === job.job_id) {
          const ok = job.status === 'done'
          setBatchProgress({
            status: ok ? 'done' : 'error',
            current: 1,
            total: 1,
            message: ok
              ? job.result?.impact?.summary || job.result?.assemble || '后台任务已完成'
              : job.error || '后台任务失败',
          })
          clearBatchProgressSoon()
        }
        // 单镜/批量视频生成由自身更新 notice，避免后台回调抢写
        if (videoGenProgress.value?.status === 'running' || batchProgress.value?.status === 'running') return
        if (job.status === 'done') {
          notice.value =
            job.result?.impact?.summary ||
            job.result?.assemble ||
            `任务 ${job.job_id} 已完成`
        } else if (job.status === 'error') {
          error.value = job.error || '渲染失败'
        }
      }
    },
  })

  function setVideoGenProgress(partial) {
    if (!partial) {
      videoGenProgress.value = null
      return
    }
    videoGenProgress.value = { ...(videoGenProgress.value || {}), ...partial }
  }

  function setBatchProgress(partial) {
    if (!partial) {
      batchProgress.value = null
      return
    }
    batchProgress.value = { ...(batchProgress.value || {}), ...partial }
    // 视频页内嵌进度条与底部条同步
    const kind = batchProgress.value.kind
    if (kind === 'video') {
      setVideoGenProgress({
        mode: 'batch',
        current: batchProgress.value.current,
        total: batchProgress.value.total,
        shotN: batchProgress.value.shotN,
        status: batchProgress.value.status,
        message: batchProgress.value.message,
      })
    }
  }

  function clearBatchProgressSoon(ms = 3000) {
    window.setTimeout(() => {
      if (batchProgress.value?.status !== 'running') {
        setBatchProgress(null)
        if (videoGenProgress.value?.status !== 'running') setVideoGenProgress(null)
      }
    }, ms)
  }

  async function runPool(items, worker, { concurrency = BATCH_CONCURRENCY, onProgress } = {}) {
    const list = [...(items || [])]
    if (!list.length) return []
    let cursor = 0
    let completed = 0
    const results = new Array(list.length)
    async function pump() {
      while (cursor < list.length) {
        const i = cursor
        cursor += 1
        const item = list[i]
        try {
          results[i] = await worker(item, i)
        } catch (e) {
          results[i] = { __error: e }
        }
        completed += 1
        onProgress?.(completed, list.length, item, results[i])
      }
    }
    const n = Math.min(Math.max(1, concurrency), list.length)
    await Promise.all(Array.from({ length: n }, () => pump()))
    return results
  }

  function shotEligibleForI2v(s) {
    if (!s) return false
    if ((s.locked || []).includes('shot')) return false
    if ((s.i2v || 'auto') === 'off') return false
    if (!s.files?.scene?.exists) return false
    const mode = s.i2v || 'auto'
    if (mode === 'on') return true
    // auto：需锁定画面；L0 也会走静图运镜
    return (s.locked || []).includes('scene')
  }

  async function runI2vForShot(shotN, { track = true } = {}) {
    const result = await dramaApi.generateI2v(slug.value, episodeN.value, shotN)
    if (result.job_id) {
      const finished = track
        ? await waitForJob(result, slug.value)
        : await trackJob(result, slug.value)
      return finished
    }
    return result
  }

  const shots = computed(() => episode.value?.shots || [])
  const timelineItems = computed(() => episode.value?.timeline?.items || [])
  const transitions = computed(() => episode.value?.transitions || episode.value?.timeline?.transitions || [])
  const i2vModes = computed(() => episode.value?.i2v_modes || ['off', 'auto', 'on'])
  const shotKinds = computed(
    () => episode.value?.shot_kinds || ['establishing', 'insert', 'dialogue', 'reaction', 'action', 'crowd', 'title'],
  )
  const shotSizes = computed(() => episode.value?.shot_sizes || ['WS', 'MS', 'MCU', 'CU', 'ECU'])
  const orderedShots = computed(() => {
    const order = timelineOrder.value.length ? timelineOrder.value : timelineItems.value.map((i) => i.n)
    const byN = Object.fromEntries((shots.value || []).map((s) => [s.n, s]))
    return order.map((n) => byN[n]).filter(Boolean)
  })
  const selected = computed(() => shots.value.find((s) => s.n === selectedN.value) || null)
  const episodes = computed(() => project.value?.episodes || [])
  const characters = computed(() => project.value?.characters || episode.value?.characters || [])
  const voices = computed(() => {
    const fromCfg = config.value?.nodes?.tts?.voices
    if (Array.isArray(fromCfg) && fromCfg.length) {
      return fromCfg
        .map((v) => {
          if (v && typeof v === 'object') {
            const id = String(v.id || v.voice || '').trim()
            if (!id) return null
            return { id, label: String(v.label || v.name || id) }
          }
          if (typeof v === 'string' && v.trim()) return { id: v.trim(), label: v.trim() }
          return null
        })
        .filter(Boolean)
    }
    return project.value?.voices || episode.value?.voices || []
  })
  const selectedCharacter = computed(
    () => characters.value.find((c) => c.id === selectedCharacterId.value) || null,
  )
  const dirty = computed(() => {
    const shot = selected.value
    if (!shot) return false
    return (
      String(draft.value.画面 || '') !== String(shot.画面 || '') ||
      String(draft.value.字幕 || '') !== String(shot.字幕 || '') ||
      String(draft.value.旁白 || '') !== String(shot.旁白 || '') ||
      String(draft.value.camera || '') !== String(shot.camera || '') ||
      Number(draft.value.duration || 0) !== Number(shot.duration || 0) ||
      String(draft.value.i2v || 'auto') !== String(shot.i2v || 'auto') ||
      String(draft.value.i2v_ladder || '') !== String(shot.i2v_ladder || '') ||
      String(draft.value.i2v_source || '') !== String(shot.i2v_source || '') ||
      String(draft.value.kind || '') !== String(shot.kind || '') ||
      String(draft.value.size || '') !== String(shot.size || '') ||
      String(draft.value.speaker || '') !== String(shot.speaker || '') ||
      String(draft.value.voice || '') !== String(shot.voice || '') ||
      rolesKey(draft.value.角色) !== rolesKey(shot.角色)
    )
  })
  const timelineDirty = computed(() => {
    const shot = selected.value
    if (!shot) return false
    return (
      Number(tlDraft.value.trim_in || 0) !== Number(shot.trim_in || 0) ||
      Number(tlDraft.value.trim_out || 0) !== Number(shot.trim_out || 0) ||
      Number(tlDraft.value.volume || 1) !== Number(shot.volume ?? 1) ||
      String(tlDraft.value.transition || 'auto') !== String(shot.transition || 'auto')
    )
  })
  const orderDirty = computed(() => {
    const saved = episode.value?.timeline?.order || []
    const cur = timelineOrder.value
    if (saved.length !== cur.length) return true
    return saved.some((n, i) => n !== cur[i])
  })
  const currentPreset = computed(() => config.value?.preset || 'ark')
  const modelCatalog = computed(() => config.value?.catalog || {})
  const providerHealth = computed(() => config.value?.health || null)
  const degradedProviders = computed(() =>
    (providerHealth.value?.items || []).filter(
      (it) => it.status === 'alias' || it.status === 'missing' || it.status === 'gated',
    ),
  )
  const mixUnlicensed = computed(() => {
    const mix = episode.value?.mix
    return Boolean(mix?.has_bgm && mix?.license && !mix.license.ok)
  })
  const mixDirty = computed(() => {
    const bgm = episode.value?.mix?.bgm || {}
    const catalogId = mixDraft.value.catalog_id || ''
    const savedCatalog = bgm.id && bgm.id !== 'upload' ? String(bgm.id) : ''
    return (
      Number(mixDraft.value.volume ?? 0.22) !== Number(bgm.volume ?? 0.22) ||
      Number(mixDraft.value.duck_db ?? -12) !== Number(bgm.duck_db ?? -12) ||
      Boolean(mixDraft.value.license_ok) !== Boolean(bgm.license_ok) ||
      catalogId !== savedCatalog
    )
  })

  function emptyDraft() {
    return {
      画面: '',
      字幕: '',
      旁白: '',
      角色: [],
      camera: 'punch_in',
      duration: 3,
      i2v: 'auto',
      i2v_ladder: '',
      i2v_source: '',
      kind: 'establishing',
      size: 'WS',
      speaker: '',
      voice: '',
    }
  }

  function emptyCharDraft() {
    return {
      id: '',
      name: '',
      look: '',
      voice: 'zh_female_vv_uranus_bigtts',
      aliases: '',
      colors: '',
      ref_size: 1024,
      ref_image_provider: 'seedream',
      ref_image_model: 'doubao-seedream-5-0-pro-260628',
      category: 'character',
    }
  }

  function emptyTlDraft() {
    return { trim_in: 0, trim_out: 0, volume: 1, transition: 'auto' }
  }

  function emptyMixDraft() {
    return { volume: 0.22, duck_db: -12, license_ok: false, catalog_id: '' }
  }

  function rolesKey(raw) {
    const list = Array.isArray(raw) ? raw : String(raw || '').split(/[,，、]/)
    return list.map((x) => String(x || '').trim()).filter(Boolean).join(',')
  }

  /** Mirror backend spoken_text / clean_subtitle for voice draft defaults. */
  function cleanSpokenText(dialogue, subtitle = '') {
    const text = String(dialogue || '').trim()
    if (text) {
      const quoteRe = /[「『“"]([^」』”"]+)[」』”"]/g
      const quotes = []
      let m
      while ((m = quoteRe.exec(text)) !== null) {
        const q = String(m[1] || '').trim()
        if (q) quotes.push(q)
      }
      if (quotes.length) {
        let out = quotes[0]
        for (let i = 1; i < quotes.length; i += 1) {
          if (!/[。！？!?…]$/.test(out)) out += '。'
          out += quotes[i]
        }
        return out
      }
      let cleaned = text.replace(
        /^(?:【[^】]{1,12}】|\[[^\]]{1,12}\])?[^:：\s「『“"]{1,16}(?:\s*[（(][^）)]{0,40}[）)])?\s*[:：]\s*/,
        '',
      )
      cleaned = cleaned.replace(/[（(][^）)]{0,24}[）)]/g, '').trim()
      cleaned = cleaned.replace(/\s{2,}/g, ' ').replace(/^[ ：:，,]+|[ ：:，,]+$/g, '')
      if (cleaned) return cleaned
    }
    return cleanSubtitleText(subtitle)
  }

  function cleanSubtitleText(subtitle) {
    const text = String(subtitle || '').trim()
    if (!text) return ''
    let cleaned = text.replace(
      /^(?:【[^】]{1,12}】|\[[^\]]{1,12}\])?[^:：\s「『“"]{1,16}(?:\s*[（(][^）)]{0,40}[）)])?\s*[:：]\s*/,
      '',
    )
    cleaned = cleaned.replace(/[（(][^）)]{0,24}[）)]/g, '').trim()
    cleaned = cleaned.replace(/\s{2,}/g, ' ').replace(/^[ ：:，,]+|[ ：:，,]+$/g, '')
    return cleaned || text
  }

  function voiceForSpeaker(speaker, shot) {
    const name = String(speaker || '').trim()
    if (name) {
      const hit = (characters.value || []).find(
        (c) => c.name === name || c.id === name || (c.aliases || []).includes(name),
      )
      if (hit?.voice) return String(hit.voice)
    }
    return String(shot?.voice || '')
  }

  function fillDraft(shot) {
    const speaker = shot?.speaker || ''
    draft.value = {
      画面: shot?.画面 || '',
      // Keep raw script text so save/chat never strip speaker prefixes.
      字幕: String(shot?.字幕 || shot?.对白 || ''),
      旁白: String(shot?.旁白 || ''),
      角色: Array.isArray(shot?.角色) ? [...shot.角色] : [],
      camera: shot?.camera || 'punch_in',
      duration: Number(Number(shot?.duration || 3).toFixed(1)),
      i2v: shot?.i2v || 'auto',
      i2v_ladder: String(shot?.i2v_ladder || ''),
      i2v_source: String(shot?.i2v_source || ''),
      kind: shot?.kind || 'establishing',
      size: shot?.size || 'WS',
      speaker,
      voice: String(shot?.voice || '').trim() || voiceForSpeaker(speaker, shot),
    }
    fillTlDraft(shot)
  }

  function fillTlDraft(shot) {
    tlDraft.value = {
      trim_in: Number(shot?.trim_in || 0),
      trim_out: Number(shot?.trim_out || 0),
      volume: Number(shot?.volume ?? 1),
      transition: shot?.transition || 'auto',
    }
  }

  function fillMixDraft(data) {
    const bgm = data?.mix?.bgm || {}
    mixDraft.value = {
      volume: Number(bgm.volume ?? 0.22),
      duck_db: Number(bgm.duck_db ?? -12),
      license_ok: Boolean(bgm.license_ok),
      catalog_id: bgm.id && bgm.id !== 'upload' ? String(bgm.id) : '',
    }
  }

  function syncTimelineFromEpisode(data) {
    timelineOrder.value = [...(data?.timeline?.order || (data?.shots || []).map((s) => s.n))]
  }

  function fillCharDraft(char) {
    const refProvider = String(char?.ref_image_provider || 'seedream')
    const refModel = String(char?.ref_image_model || 'doubao-seedream-5-0-pro-260628')
    charDraft.value = {
      id: char?.id || '',
      name: char?.name || '',
      look: char?.look || '',
      voice: char?.voice || 'zh_female_vv_uranus_bigtts',
      aliases: (char?.aliases || []).join('、'),
      colors: char?.colors || '',
      ref_size: [640, 1024, 1980].includes(Number(char?.ref_size)) ? Number(char.ref_size) : 1024,
      ref_image_provider: refProvider,
      ref_image_model: refModel,
      category: char?.category || 'character',
    }
  }

  function assetUrl(url) {
    if (!url) return ''
    return `${url}${url.includes('?') ? '&' : '?'}_=${bust.value}`
  }

  async function refreshProjects() {
    const data = await dramaApi.listProjects()
    projects.value = data.projects || []
    return projects.value
  }

  async function loadConfig() {
    if (!slug.value) return
    const data = await dramaApi.getConfig(slug.value)
    config.value = data
    presets.value = data.presets || []
    return data
  }

  async function applyProjectPreset(presetId) {
    if (!slug.value || !presetId) return
    error.value = ''
    notice.value = ''
    saving.value = true
    try {
      const data = await dramaApi.applyPreset(slug.value, presetId)
      config.value = { ...(config.value || {}), preset: data.preset, health: data.health }
      presets.value = data.presets || presets.value
      selectConfigNode(selectedConfigNode.value, true)
      notice.value = `已切换预设：${data.title || data.preset}`
      return data
    } catch (e) {
      error.value = e.message || String(e)
    } finally {
      saving.value = false
    }
  }

  function selectConfigNode(nodeId, silent = false) {
    if (!nodeId) return
    selectedConfigNode.value = nodeId
    const value = config.value?.nodes?.[nodeId]
    configNodeDraft.value = JSON.stringify(value ?? {}, null, 2)
    if (!silent) {
      error.value = ''
      notice.value = ''
    }
  }

  async function saveConfigNode() {
    if (!slug.value || !selectedConfigNode.value) return
    let value
    try {
      value = JSON.parse(configNodeDraft.value || '{}')
    } catch (e) {
      error.value = 'JSON 格式错误：' + e.message
      return
    }
    saving.value = true
    error.value = ''
    notice.value = ''
    try {
      const data = await dramaApi.putNodeConfig(slug.value, selectedConfigNode.value, value)
      config.value = { ...(config.value || {}), ...data, nodes: data.models ? undefined : (config.value || {}).nodes }
      await loadConfig()
      selectConfigNode(selectedConfigNode.value, true)
      notice.value = `已保存节点 ${selectedConfigNode.value}`
    } catch (e) {
      error.value = e.message || String(e)
    } finally {
      saving.value = false
    }
  }

  function _optionKey(provider, model) {
    return `${provider || ''}|${model || ''}`
  }

  function stageModelSelection(nodeId) {
    const nodes = config.value?.nodes || {}
    const catalog = modelCatalog.value?.[nodeId] || []
    if (nodeId === 'script') {
      const n = nodes.script || {}
      return _optionKey(n.provider || 'ark', n.model || 'doubao-seed-character-260628')
    }
    if (nodeId === 'image') {
      const image = nodes.image || {}
      const sample = image.dialogue || image.establishing || image.character_ref || {}
      return _optionKey(sample.provider || 'seedream', sample.model || 'doubao-seedream-5-0-pro-260628')
    }
    if (nodeId === 'character_ref') {
      const cref = (nodes.image || {}).character_ref || {}
      return _optionKey(cref.provider || 'seedream', cref.model || 'doubao-seedream-5-0-pro-260628')
    }
    if (nodeId === 'motion') {
      const motion = nodes.motion || {}
      const sample = motion.action || motion.dialogue || motion.reaction || {}
      return _optionKey(sample.provider || 'seedance', sample.model || 'doubao-seedance-2-5-260628')
    }
    if (nodeId === 'tts') {
      const n = nodes.tts || {}
      return _optionKey(n.provider || 'seed-audio', n.model || 'doubao-seed-audio-1-0')
    }
    if (nodeId === 'lip') {
      const n = nodes.lip || {}
      return _optionKey(n.provider || 'pixverse', n.model || '')
    }
    const hit = catalog[0]
    return hit ? _optionKey(hit.provider, hit.model) : ''
  }

  async function applyStageModel(nodeId, optionKey) {
    if (!slug.value || !nodeId || !optionKey) return
    const [provider, model = ''] = String(optionKey).split('|')
    if (!provider) return
    saving.value = true
    error.value = ''
    notice.value = ''
    try {
      let value
      const nodes = config.value?.nodes || {}
      if (nodeId === 'script') {
        value = {
          ...(nodes.script || {}),
          provider,
          model,
          refine_model: model,
          alternatives: ['ark', 'deepseek', 'kimi'],
        }
        await dramaApi.putNodeConfig(slug.value, 'script', value)
      } else if (nodeId === 'image' || nodeId === 'character_ref') {
        const image = { ...(nodes.image || {}) }
        const kinds =
          nodeId === 'character_ref'
            ? ['character_ref']
            : [
                'establishing',
                'insert',
                'dialogue',
                'reaction',
                'action',
                'crowd',
                'title',
                'character_ref',
              ]
        for (const kind of kinds) {
          const cur = { ...(image[kind] || {}) }
          cur.provider = provider
          if (model) cur.model = model
          image[kind] = cur
        }
        await dramaApi.putNodeConfig(slug.value, 'image', image)
        if (nodeId === 'character_ref' || nodeId === 'image') {
          charDraft.value.ref_image_provider = provider
          charDraft.value.ref_image_model = model || charDraft.value.ref_image_model
        }
      } else if (nodeId === 'motion') {
        const motion = { ...(nodes.motion || {}) }
        for (const kind of Object.keys(motion)) {
          const cur = { ...(motion[kind] || {}) }
          if (provider === 'l0') {
            motion[kind] = { ...cur, ladder: 'L0', provider: 'l0', fallback: 'L0' }
            continue
          }
          // Keep establishing/insert on L0 unless user explicitly picks L0 above.
          if (String(cur.ladder || '') === 'L0' && ['establishing', 'insert', 'crowd', 'title'].includes(kind)) {
            continue
          }
          motion[kind] = {
            ...cur,
            provider,
            ...(model ? { model } : {}),
            fallback: cur.fallback || 'L0',
          }
        }
        await dramaApi.putNodeConfig(slug.value, 'motion', motion)
      } else if (nodeId === 'tts') {
        value = { ...(nodes.tts || {}), provider, ...(model ? { model } : {}) }
        await dramaApi.putNodeConfig(slug.value, 'tts', value)
      } else if (nodeId === 'lip') {
        value = { ...(nodes.lip || {}), provider, enabled: provider !== 'mock' }
        await dramaApi.putNodeConfig(slug.value, 'lip', value)
      } else {
        return
      }
      await loadConfig()
      notice.value = `已切换${nodeId}模型`
    } catch (e) {
      error.value = e.message || String(e)
    } finally {
      saving.value = false
    }
  }

  async function deleteProject(targetSlug) {
    error.value = ''
    notice.value = ''
    await dramaApi.deleteProject(targetSlug)
    if (slug.value === targetSlug) {
      slug.value = null
      project.value = null
      episodeN.value = null
      episode.value = null
      selectedN.value = null
      fillDraft(null)
      selectedCharacterId.value = null
      fillCharDraft(null)
    }
    await refreshProjects()
    return true
  }

  async function openProject(nextSlug) {
    error.value = ''
    notice.value = ''
    const data = await dramaApi.getProject(nextSlug)
    slug.value = data.slug
    project.value = data
    const first = (data.episodes || [])[0]
    if (first) {
      await openEpisode(first.n)
    } else {
      episodeN.value = null
      episode.value = null
      selectedN.value = null
      fillDraft(null)
    }
    const firstChar = (data.characters || [])[0]
    selectedCharacterId.value = firstChar?.id || null
    fillCharDraft(firstChar || null)
    void loadConfig()
  }

  async function openEpisode(n) {
    if (!slug.value) return
    error.value = ''
    const data = await dramaApi.getEpisode(slug.value, n)
    if (episodeN.value !== data.episode) scriptImpact.value = null
    episodeN.value = data.episode
    episode.value = data
    scriptDraft.value = data.script || ''
    syncTimelineFromEpisode(data)
    fillMixDraft(data)
    void refreshJobs(slug.value)
    const keep = (data.shots || []).some((s) => s.n === selectedN.value)
    const next = keep ? selectedN.value : data.shots?.[0]?.n || null
    selectShot(next)
  }

  function selectShot(n) {
    selectedN.value = n
    const shot = shots.value.find((s) => s.n === n)
    fillDraft(shot || null)
  }

  function mergeEpisodeShot(updatedShot) {
    if (!updatedShot || !episode.value?.shots) return
    const n = Number(updatedShot.n)
    const idx = episode.value.shots.findIndex((s) => Number(s.n) === n)
    if (idx < 0) return
    episode.value.shots.splice(idx, 1, updatedShot)
    if (Number(selectedN.value) === n) {
      fillDraft(updatedShot)
    }
  }

  function finishCandidateGeneration(shotN) {
    generatingCandidateNs.value = generatingCandidateNs.value.filter((n) => n !== shotN)
    if (!generatingCandidateNs.value.length) rendering.value = false
  }

  function toggleShotSelected(n) {
    const idx = selectedShotIds.value.indexOf(n)
    if (idx >= 0) selectedShotIds.value.splice(idx, 1)
    else selectedShotIds.value.push(n)
  }

  function clearShotSelection() {
    selectedShotIds.value = []
  }

  function selectAllShots() {
    selectedShotIds.value = shots.value.map((s) => s.n)
  }

  const budget = computed(() => episode.value?.budget || null)
  const budgetBlocked = computed(() => Boolean(budget.value?.blocked))
  const budgetWarn = computed(() => Boolean(budget.value?.warn))

  function fillBudgetDraft() {
    const b = episode.value?.budget || {}
    budgetDraft.value = {
      enabled: Boolean(b.enabled),
      per_episode: Number(b.per_episode || 0),
      warn_at: Number(b.warn_at ?? 0.8),
    }
  }

  function toggleBudgetPanel() {
    budgetOpen.value = !budgetOpen.value
    if (budgetOpen.value) fillBudgetDraft()
  }

  async function saveBudget() {
    if (!slug.value) return
    saving.value = true
    error.value = ''
    notice.value = ''
    try {
      await dramaApi.patchModels(slug.value, {
        budget: {
          enabled: Boolean(budgetDraft.value.enabled),
          per_episode: Number(budgetDraft.value.per_episode || 0),
          warn_at: Number(budgetDraft.value.warn_at ?? 0.8),
        },
      })
      await openEpisode(episodeN.value || 1)
      notice.value = budgetDraft.value.enabled
        ? `预算闸已开启（每集 ¥${budgetDraft.value.per_episode}，警告线 ${Math.round(budgetDraft.value.warn_at * 100)}%）`
        : '预算闸已关闭'
    } catch (e) {
      error.value = e.message || String(e)
    } finally {
      saving.value = false
    }
  }

  async function refreshSnapshots() {
    if (!slug.value || !episodeN.value) return
    try {
      const data = await dramaApi.listSnapshots(slug.value, episodeN.value)
      snapshots.value = data.snapshots || []
    } catch {
      snapshots.value = []
    }
    return snapshots.value
  }

  function toggleSnapshotsPanel() {
    snapshotsOpen.value = !snapshotsOpen.value
    if (snapshotsOpen.value) void refreshSnapshots()
  }

  async function restoreSnapshotVersion(sid) {
    if (!slug.value || !episodeN.value || !sid) return
    saving.value = true
    error.value = ''
    notice.value = ''
    try {
      const data = await dramaApi.restoreSnapshot(slug.value, episodeN.value, sid)
      bust.value = Date.now()
      await openEpisode(episodeN.value)
      await refreshSnapshots()
      notice.value = `已恢复到 ${sid}（还原 ${data.restored?.restored_scenes || 0} 张画面）`
    } catch (e) {
      error.value = e.message || String(e)
    } finally {
      saving.value = false
    }
  }

  async function deleteSnapshotVersion(sid) {
    if (!slug.value || !episodeN.value || !sid) return
    saving.value = true
    error.value = ''
    notice.value = ''
    try {
      await dramaApi.deleteSnapshot(slug.value, episodeN.value, sid)
      await refreshSnapshots()
      notice.value = `已删除快照 ${sid}`
    } catch (e) {
      error.value = e.message || String(e)
    } finally {
      saving.value = false
    }
  }

  async function applyBatchEdit(field, value) {
    if (!slug.value || !episodeN.value) return
    const targetShots = [...selectedShotIds.value]
    const fieldSel = String(field || batchField.value || '').trim()
    const valueSel = value ?? batchValue.value
    if (!targetShots.length) {
      error.value = '请先在左侧勾选要批量修改的镜头'
      return
    }
    if (!fieldSel) {
      error.value = '请选择要批量修改的字段'
      return
    }
    saving.value = true
    error.value = ''
    notice.value = ''
    try {
      const result = await dramaApi.patchShots(
        slug.value,
        episodeN.value,
        targetShots,
        fieldSel,
        valueSel,
      )
      bust.value = Date.now()
      await openEpisode(episodeN.value)
      const skipped = (result.skipped_locked || []).length
      const updated = (result.updated || []).length
      notice.value = skipped
        ? `已批量更新 ${updated} 镜；${skipped} 镜已锁定未改`
        : `已批量更新 ${updated} 镜（未重渲，脏层下次渲染生效）`
    } catch (e) {
      error.value = e.message || String(e)
    } finally {
      saving.value = false
    }
  }

  async function saveShot() {
    if (!slug.value || !episodeN.value || !selectedN.value) return
    saving.value = true
    error.value = ''
    notice.value = ''
    try {
      const shot = selected.value
      const body = {}
      if (String(draft.value.画面 || '') !== String(shot.画面 || '')) body.画面 = draft.value.画面
      if (String(draft.value.字幕 || '') !== String(shot.字幕 || '')) body.字幕 = draft.value.字幕
      if (String(draft.value.旁白 || '') !== String(shot.旁白 || '')) body.旁白 = draft.value.旁白
      if (String(draft.value.camera || '') !== String(shot.camera || '')) body.camera = draft.value.camera
      if (Number(draft.value.duration || 0) !== Number(shot.duration || 0)) {
        const dur = Number(Number(draft.value.duration).toFixed(1))
        if (!Number.isFinite(dur) || dur <= 0) {
          error.value = '时长须为大于 0 的数字'
          return
        }
        body.duration = dur
      }
      if (rolesKey(draft.value.角色) !== rolesKey(shot.角色)) {
        body.角色 = [...(draft.value.角色 || [])]
      }
      if (String(draft.value.i2v || 'auto') !== String(shot.i2v || 'auto')) {
        body.i2v = draft.value.i2v || 'auto'
      }
      if (String(draft.value.i2v_ladder || '') !== String(shot.i2v_ladder || '')) {
        body.i2v_ladder = draft.value.i2v_ladder || ''
      }
      if (String(draft.value.i2v_source || '') !== String(shot.i2v_source || '')) {
        body.i2v_source = draft.value.i2v_source || ''
      }
      if (String(draft.value.kind || '') !== String(shot.kind || '')) body.kind = draft.value.kind
      if (String(draft.value.size || '') !== String(shot.size || '')) body.size = draft.value.size
      if (String(draft.value.speaker || '') !== String(shot.speaker || '')) {
        body.speaker = draft.value.speaker || ''
      }
      if (String(draft.value.voice || '') !== String(shot.voice || '')) {
        body.voice = draft.value.voice || ''
      }
      if (!Object.keys(body).length) {
        notice.value = '没有改动'
        return
      }
      await dramaApi.patchShot(slug.value, episodeN.value, selectedN.value, body)
      bust.value = Date.now()
      await openEpisode(episodeN.value)
      notice.value = Object.prototype.hasOwnProperty.call(body, 'duration')
        ? '已保存：时长已同步到剧本时间轴（后续镜头顺延）。脏层会在下次渲染时更新。'
        : '已保存（未重渲）。脏层会在下次渲染时更新。'
    } catch (e) {
      error.value = e.message || String(e)
    } finally {
      saving.value = false
    }
  }

  async function toggleLock(layer) {
    if (!slug.value || !episodeN.value || !selectedN.value || !layer) return
    const locked = selected.value?.locked || []
    const has = locked.includes(layer)
    saving.value = true
    error.value = ''
    notice.value = ''
    try {
      const result = await dramaApi.lockShot(
        slug.value,
        episodeN.value,
        selectedN.value,
        has ? { unlock: [layer] } : { lock: [layer] },
      )
      if (result.shot) {
        mergeEpisodeShot(result.shot)
      } else {
        await openEpisode(episodeN.value)
      }
      bust.value = Date.now()
      notice.value = has
        ? `已解锁 ${layer}`
        : layer === 'shot'
          ? '已锁定整镜，保存剧本时不会覆盖这一镜'
          : `已锁定 ${layer}，重渲不会覆盖该层`
    } catch (e) {
      error.value = e.message || String(e)
    } finally {
      saving.value = false
    }
  }

  async function rerenderLayer(layer) {
    if (!slug.value || !episodeN.value || !selectedN.value) return
    if (dirty.value) {
      await saveShot()
      if (error.value) return
    }
    rendering.value = true
    error.value = ''
    notice.value = ''
    try {
      const result = await dramaApi.rerenderShot(
        slug.value,
        episodeN.value,
        selectedN.value,
        layer ? [layer] : undefined,
      )
      bust.value = Date.now()
      await openEpisode(episodeN.value)
      const rebuilt = (result.rebuilt_layers || []).join(' / ') || '无'
      notice.value = layer ? `已重做 ${layer}（实际重建：${rebuilt}）` : `本镜已重渲（${rebuilt}）`
    } catch (e) {
      error.value = e.message || String(e)
    } finally {
      rendering.value = false
    }
  }

  async function previewScriptChanges({ silent = false } = {}) {
    if (!slug.value || !episodeN.value) return
    const draft = scriptDraft.value
    const s = slug.value
    const n = episodeN.value
    if (!String(draft || '').trim()) return
    if (!silent) {
      saving.value = true
      error.value = ''
      notice.value = ''
    }
    try {
      const data = await dramaApi.previewScript(s, n, draft)
      if (scriptDraft.value !== draft || slug.value !== s || episodeN.value !== n) return
      scriptImpact.value = data.impact
      if (!silent) notice.value = data.impact?.summary || '已预览影响'
    } catch (e) {
      if (!silent) error.value = e.message || String(e)
    } finally {
      if (!silent) saving.value = false
    }
  }

  let previewTimer = 0
  watch([scriptDraft, boardMode, slug, episodeN], () => {
    if (boardMode.value !== 'script' || !slug.value || !episodeN.value) return
    if (!String(scriptDraft.value || '').trim()) return
    window.clearTimeout(previewTimer)
    previewTimer = window.setTimeout(() => {
      void previewScriptChanges({ silent: true })
    }, 450)
  })

  async function saveScriptChanges() {
    if (!slug.value || !episodeN.value) return
    saving.value = true
    error.value = ''
    notice.value = ''
    try {
      const data = await dramaApi.saveScript(slug.value, episodeN.value, scriptDraft.value)
      scriptImpact.value = data.impact
      try {
        project.value = await dramaApi.getProject(slug.value)
      } catch {
        /* keep current project if refresh fails */
      }
      episode.value = data
      scriptDraft.value = data.script || scriptDraft.value
      const keep = (data.shots || []).some((s) => s.n === selectedN.value)
      selectShot(keep ? selectedN.value : data.shots?.[0]?.n || null)
      notice.value = data.impact?.summary || '剧本已保存'
    } catch (e) {
      error.value = e.message || String(e)
    } finally {
      saving.value = false
    }
  }

  async function generateScriptFromPremise(premise) {
    if (!slug.value) return
    const text = String(premise || '').trim()
    if (!text) {
      error.value = '请先给一句故事梗概'
      return
    }
    // init 立项后可能还没有任何分集（episodeN == null），此时默认落到 EP01。
    // 后端 save_script 会自动把该集写进 project.json，无需预建分集。
    const ep = episodeN.value || 1
    saving.value = true
    error.value = ''
    notice.value = '正在根据梗概生成剧本…'
    try {
      const data = await dramaApi.generateScript(slug.value, ep, text)
      episodeN.value = data.episode || ep
      episode.value = data
      scriptDraft.value = data.script || ''
      scriptImpact.value = data.impact || null
      try {
        project.value = await dramaApi.getProject(slug.value)
      } catch {
        /* keep current project */
      }
      const keep = (data.shots || []).some((s) => s.n === selectedN.value)
      selectShot(keep ? selectedN.value : data.shots?.[0]?.n || null)
      notice.value = (data.shots || []).length
        ? `已生成剧本，共 ${data.shots.length} 镜`
        : '剧本已生成'
      return data
    } catch (e) {
      error.value = e.message || String(e)
    } finally {
      saving.value = false
    }
  }

  async function rerenderDirtyShots() {
    if (!slug.value || !episodeN.value) return
    error.value = ''
    notice.value = ''
    rendering.value = true
    setBatchProgress({
      kind: 'dirty',
      label: '重渲脏镜',
      current: 0,
      total: 1,
      status: 'running',
      message: '脏镜渲染排队中…',
    })
    try {
      const result = await dramaApi.rerenderDirty(slug.value, episodeN.value)
      if (result.job_id) {
        await trackJob(result, slug.value)
        notice.value = '脏镜渲染已加入后台队列'
        setBatchProgress({
          status: 'running',
          message: '脏镜渲染进行中（后台）…',
          jobId: result.job_id,
        })
        rendering.value = false
        return
      }
      bust.value = Date.now()
      await openEpisode(episodeN.value)
      notice.value = result.impact?.summary || '脏镜已重渲'
      setBatchProgress({ status: 'done', current: 1, total: 1, message: notice.value })
    } catch (e) {
      error.value = e.message || String(e)
      setBatchProgress({ status: 'error', message: error.value })
    } finally {
      if (!batchProgress.value?.jobId) {
        rendering.value = false
        clearBatchProgressSoon()
      }
    }
  }

  async function saveEpisodeMeta(patch) {
    if (!slug.value || !episodeN.value) return
    saving.value = true
    error.value = ''
    try {
      await dramaApi.patchEpisode(slug.value, episodeN.value, patch)
      await openProject(slug.value)
      notice.value = '分集信息已保存'
    } catch (e) {
      error.value = e.message || String(e)
    } finally {
      saving.value = false
    }
  }

  async function refreshCast() {
    if (!slug.value) return
    project.value = await dramaApi.getProject(slug.value)
    const keep = characters.value.some((c) => c.id === selectedCharacterId.value)
    selectCharacter(keep ? selectedCharacterId.value : characters.value[0]?.id || null)
    if (episodeN.value) {
      try {
        await openEpisode(episodeN.value)
      } catch {
        /* keep current episode */
      }
    }
  }

  function selectCharacter(id) {
    selectedCharacterId.value = id
    fillCharDraft(characters.value.find((c) => c.id === id) || null)
  }

  function toggleShotRole(id) {
    if (!id || shotFrozenLocked()) return
    const cur = new Set(draft.value.角色 || [])
    if (cur.has(id)) cur.delete(id)
    else cur.add(id)
    const ordered = characters.value.map((c) => c.id).filter((cid) => cur.has(cid))
    for (const extra of cur) {
      if (!ordered.includes(extra)) ordered.push(extra)
    }
    draft.value.角色 = ordered
  }

  function shotFrozenLocked() {
    return (selected.value?.locked || []).includes('shot')
  }

  async function addCharacter(payload = {}) {
    if (!slug.value) return
    saving.value = true
    error.value = ''
    try {
      const category = payload.category || 'character'
      const names = { character: '新角色', prop: '新物品', scene: '新场景' }
      const rec = await dramaApi.createCharacter(slug.value, {
        name: payload.name || names[category] || '新资产',
        category,
      })
      await refreshCast()
      selectCharacter(rec.id)
    } catch (e) {
      error.value = e.message || String(e)
    } finally {
      saving.value = false
    }
  }

  async function saveCharacterCard() {
    if (!slug.value) return
    const cid = String(charDraft.value.id || selectedCharacterId.value || '').trim()
    if (!cid && !charDraft.value.name) {
      error.value = '请填写名称'
      return
    }
    saving.value = true
    error.value = ''
    try {
      const body = {
        name: String(charDraft.value.name || '').trim(),
        look: charDraft.value.look,
        voice: charDraft.value.voice,
        aliases: String(charDraft.value.aliases || '').trim(),
        ref_size: charDraft.value.ref_size || 1024,
        ref_image_provider: charDraft.value.ref_image_provider,
        ref_image_model: charDraft.value.ref_image_model,
        category: charDraft.value.category || 'character',
      }
      const rec = cid
        ? await dramaApi.saveCharacter(slug.value, cid, body)
        : await dramaApi.createCharacter(slug.value, body)
      await refreshCast()
      selectCharacter(rec.id)
    } catch (e) {
      error.value = e.message || String(e)
    } finally {
      saving.value = false
    }
  }

  async function lockSelectedRef(cid) {
    const targetId = String(cid || selectedCharacterId.value || '').trim()
    if (!slug.value || !targetId) return
    const target = characters.value.find((c) => c.id === targetId) || null
    const locked = !target?.ref_locked
    saving.value = true
    error.value = ''
    try {
      await dramaApi.lockCharacterRef(slug.value, targetId, locked)
      await refreshCast()
    } catch (e) {
      error.value = e.message || String(e)
    } finally {
      saving.value = false
    }
  }

  async function uploadSelectedRef(file) {
    if (!slug.value || !selectedCharacterId.value || !file) return
    saving.value = true
    error.value = ''
    try {
      await dramaApi.uploadCharacterRef(slug.value, selectedCharacterId.value, file)
      bust.value = Date.now()
      await refreshCast()
    } catch (e) {
      error.value = e.message || String(e)
    } finally {
      saving.value = false
    }
  }

  async function deleteSelectedCharacter(cid) {
    const targetId = String(cid || selectedCharacterId.value || '').trim()
    if (!slug.value || !targetId) return
    saving.value = true
    error.value = ''
    try {
      await dramaApi.deleteCharacter(slug.value, targetId)
      if (selectedCharacterId.value === targetId) selectedCharacterId.value = null
      await refreshCast()
    } catch (e) {
      error.value = e.message || String(e)
    } finally {
      saving.value = false
    }
  }

  async function generateShotCandidates(count = 1) {
    const shotN = selectedN.value
    if (!slug.value || !episodeN.value || !shotN) return
    if (generatingCandidateNs.value.includes(shotN)) return
    generatingCandidateNs.value = [...generatingCandidateNs.value, shotN]
    rendering.value = true
    error.value = ''
    notice.value = ''
    try {
      const result = await dramaApi.generateCandidates(slug.value, episodeN.value, shotN, count)
      if (result.shot) mergeEpisodeShot(result.shot)
      bust.value = Date.now()
      notice.value = `Shot ${shotN} 已生成 ${(result.created || []).length} 张候选`
    } catch (e) {
      error.value = e.message || String(e)
    } finally {
      finishCandidateGeneration(shotN)
    }
  }

  const choosingCandidate = ref(null)

  function patchShotChosen(shots, idx, cid) {
    const shot = shots[idx]
    if (!shot) return
    const next = {
      ...shot,
      chosen: cid,
      candidates: (shot.candidates || []).map((c) => ({
        ...c,
        chosen: String(c.id) === String(cid),
      })),
      locked: [...new Set([...(shot.locked || []), 'scene'])],
      dirty: (shot.dirty || []).filter((layer) => layer !== 'scene'),
    }
    shots.splice(idx, 1, next)
  }

  async function chooseShotCandidate(cid) {
    if (!slug.value || !episodeN.value || !selectedN.value || !cid) return
    if (choosingCandidate.value) return
    choosingCandidate.value = cid
    const idx = episode.value?.shots?.findIndex((s) => s.n === selectedN.value) ?? -1
    let snapshot = null
    if (idx >= 0) {
      snapshot = JSON.parse(JSON.stringify(episode.value.shots[idx]))
      patchShotChosen(episode.value.shots, idx, cid)
    }
    error.value = ''
    notice.value = ''
    try {
      const result = await dramaApi.chooseCandidate(slug.value, episodeN.value, selectedN.value, cid)
      if (result.shot) {
        mergeEpisodeShot(result.shot)
      } else {
        await openEpisode(episodeN.value)
      }
      bust.value = Date.now()
      const rebuilt = (result.rebuilt_layers || []).join(' / ') || '无'
      notice.value = `已锁定 ${cid}（只换画面，配音保留；重建：${rebuilt}）`
    } catch (e) {
      if (snapshot != null && idx >= 0) {
        episode.value.shots.splice(idx, 1, snapshot)
      }
      error.value = e.message || String(e)
    } finally {
      choosingCandidate.value = null
    }
  }

  async function deleteCandidate(cid) {
    if (!slug.value || !episodeN.value || !selectedN.value || !cid) return
    saving.value = true
    error.value = ''
    notice.value = ''
    try {
      const result = await dramaApi.deleteCandidate(slug.value, episodeN.value, selectedN.value, cid)
      if (result.shot) mergeEpisodeShot(result.shot)
      bust.value = Date.now()
      notice.value = `已删除候选 ${cid}`
    } catch (e) {
      error.value = e.message || String(e)
    } finally {
      saving.value = false
    }
  }

  async function uploadShotScene(file) {
    if (!slug.value || !episodeN.value || !selectedN.value || !file) return
    rendering.value = true
    error.value = ''
    notice.value = ''
    try {
      const result = await dramaApi.uploadShotScene(slug.value, episodeN.value, selectedN.value, file)
      bust.value = Date.now()
      await openEpisode(episodeN.value)
      notice.value = `已用手传图覆盖 ${result.chosen || '画面'}（配音保留）`
    } catch (e) {
      error.value = e.message || String(e)
    } finally {
      rendering.value = false
    }
  }

  async function saveTimelineShot() {
    if (!slug.value || !episodeN.value || !selectedN.value || !timelineDirty.value) return
    saving.value = true
    error.value = ''
    notice.value = ''
    try {
      await dramaApi.patchShot(slug.value, episodeN.value, selectedN.value, {
        trim_in: Number(tlDraft.value.trim_in || 0),
        trim_out: Number(tlDraft.value.trim_out || 0),
        volume: Number(tlDraft.value.volume ?? 1),
        transition: tlDraft.value.transition || 'auto',
      })
      await openEpisode(episodeN.value)
      notice.value = '时间线参数已保存（未改源 clip）'
    } catch (e) {
      error.value = e.message || String(e)
    } finally {
      saving.value = false
    }
  }

  async function saveTimelineOrder() {
    if (!slug.value || !episodeN.value || !orderDirty.value) return
    saving.value = true
    error.value = ''
    notice.value = ''
    try {
      await dramaApi.patchTimeline(slug.value, episodeN.value, { order: [...timelineOrder.value] })
      await openEpisode(episodeN.value)
      notice.value = '镜序已保存'
    } catch (e) {
      error.value = e.message || String(e)
    } finally {
      saving.value = false
    }
  }

  function moveTimelineShot(n, delta) {
    const order = [...timelineOrder.value]
    const idx = order.indexOf(n)
    if (idx < 0) return
    const next = idx + delta
    if (next < 0 || next >= order.length) return
    ;[order[idx], order[next]] = [order[next], order[idx]]
    timelineOrder.value = order
  }

  function reorderTimeline(fromN, toN) {
    if (fromN === toN) return
    const order = [...timelineOrder.value]
    const from = order.indexOf(fromN)
    const to = order.indexOf(toN)
    if (from < 0 || to < 0) return
    order.splice(from, 1)
    order.splice(to, 0, fromN)
    timelineOrder.value = order
  }

  async function saveTimelineAll() {
    if (!orderDirty.value && !timelineDirty.value) {
      notice.value = '没有改动'
      return
    }
    if (orderDirty.value) await saveTimelineOrder()
    if (error.value) return
    if (timelineDirty.value) await saveTimelineShot()
  }

  async function classifyEpisodeShots(force = false) {
    if (!slug.value || !episodeN.value) return
    saving.value = true
    error.value = ''
    notice.value = ''
    try {
      const result = await dramaApi.classifyShots(slug.value, episodeN.value, force)
      bust.value = Date.now()
      await openEpisode(episodeN.value)
      const n = (result.changed || []).length
      notice.value = n ? `已分类 ${result.classified} 镜，更新 ${n} 镜` : '镜头类型已是最新'
    } catch (e) {
      error.value = e.message || String(e)
    } finally {
      saving.value = false
    }
  }

  async function applyEpisodeStyle(styleId) {
    if (!slug.value || !episodeN.value) return
    saving.value = true
    error.value = ''
    notice.value = ''
    try {
      const data = await dramaApi.applyStyle(slug.value, episodeN.value, styleId || '')
      episode.value = data
      notice.value = data.hint || '已切换风格，未重渲已有 clip'
    } catch (e) {
      error.value = e.message || String(e)
    } finally {
      saving.value = false
    }
  }

  async function generateShotI2v() {
    if (!slug.value || !episodeN.value || !selectedN.value) return
    const shotN = selectedN.value
    const shot = shots.value.find((s) => s.n === shotN)
    if (!shotEligibleForI2v(shot)) {
      error.value = !shot?.files?.scene?.exists
        ? '请先在「画面」步骤生成画面'
        : '请先在「画面」步骤锁定关键帧后再生成视频'
      return
    }
    if (dirty.value) {
      await saveShot()
      if (error.value) return
    }
    rendering.value = true
    error.value = ''
    notice.value = ''
    setVideoGenProgress({
      mode: 'single',
      current: 1,
      total: 1,
      shotN,
      status: 'running',
      message: `Shot ${shotN} 视频生成中…`,
    })
    try {
      const result = await runI2vForShot(shotN)
      bust.value = Date.now()
      await openEpisode(episodeN.value)
      if (result?.status === 'error') {
        error.value = result.error || `Shot ${shotN} 视频生成失败`
        setVideoGenProgress({
          status: 'error',
          message: error.value,
        })
        return
      }
      const src = result?.result?.i2v_source || result?.i2v_source || ''
      notice.value = `Shot ${shotN} 视频完成${src ? `（${src}）` : ''}`
      setVideoGenProgress({
        status: 'done',
        message: `Shot ${shotN} 已完成`,
      })
    } catch (e) {
      error.value = e.message || String(e)
      setVideoGenProgress({
        status: 'error',
        message: error.value,
      })
    } finally {
      rendering.value = false
      window.setTimeout(() => {
        if (videoGenProgress.value?.status !== 'running') setVideoGenProgress(null)
      }, 2500)
    }
  }

  async function generateShotLip() {
    if (!slug.value || !episodeN.value || !selectedN.value) return
    if (dirty.value) {
      await saveShot()
      if (error.value) return
    }
    rendering.value = true
    error.value = ''
    notice.value = ''
    try {
      // 声音页：配音 + 旁白叠层 + 口型一起重建（与批量一致）
      const result = await dramaApi.rerenderShot(slug.value, episodeN.value, selectedN.value, [
        'overlay',
        'voice',
        'lip',
      ])
      if (result.job_id) {
        await waitForJob(result, slug.value)
      }
      bust.value = Date.now()
      await openEpisode(episodeN.value)
      notice.value = `Shot ${selectedN.value} 配音与口型已完成`
    } catch (e) {
      error.value = e.message || String(e)
    } finally {
      rendering.value = false
    }
  }

  async function generateShotKeys() {
    if (!slug.value || !episodeN.value || !selectedN.value) return
    error.value = ''
    notice.value = ''
    try {
      const result = await dramaApi.generateKeys(slug.value, episodeN.value, selectedN.value, 3)
      if (result.job_id) {
        await trackJob(result, slug.value)
        notice.value = `Shot ${selectedN.value} 关键帧已加入后台队列`
        return
      }
      bust.value = Date.now()
      await openEpisode(episodeN.value)
      notice.value = `关键帧完成（${result.count || 3} 张，未重配音）`
    } catch (e) {
      error.value = e.message || String(e)
    }
  }

  async function chooseShotKey(kid, cid) {
    if (!slug.value || !episodeN.value || !selectedN.value || !kid || !cid) return
    error.value = ''
    notice.value = ''
    try {
      await dramaApi.chooseKey(slug.value, episodeN.value, selectedN.value, kid, cid)
      bust.value = Date.now()
      await openEpisode(episodeN.value)
      notice.value = `已锁姿态 ${kid}（不重配音）`
    } catch (e) {
      error.value = e.message || String(e)
    }
  }

  async function uploadShotKey(kid, file) {
    if (!slug.value || !episodeN.value || !selectedN.value || !kid || !file) return
    error.value = ''
    notice.value = ''
    try {
      await dramaApi.uploadKey(slug.value, episodeN.value, selectedN.value, kid, file)
      bust.value = Date.now()
      await openEpisode(episodeN.value)
      notice.value = `已上传姿态 ${kid}（不重配音）`
    } catch (e) {
      error.value = e.message || String(e)
    }
  }

  async function lockShotKey(kid, locked) {
    if (!slug.value || !episodeN.value || !selectedN.value || !kid) return
    error.value = ''
    notice.value = ''
    try {
      await dramaApi.lockKey(slug.value, episodeN.value, selectedN.value, kid, locked)
      await openEpisode(episodeN.value)
      notice.value = locked ? `已锁定姿态 ${kid}` : `已解锁姿态 ${kid}`
    } catch (e) {
      error.value = e.message || String(e)
    }
  }

  async function qcSelectedShot() {
    if (!slug.value || !episodeN.value || !selectedN.value) return
    error.value = ''
    notice.value = ''
    try {
      const result = await dramaApi.qcShot(slug.value, episodeN.value, selectedN.value)
      bust.value = Date.now()
      await openEpisode(episodeN.value)
      const id = result.identity || {}
      if (id.status === 'skipped' || !result.passed) {
        notice.value = id.hint || '身份抽检未出分或未通过，不得记为通过'
      } else {
        notice.value = `身份通过（余弦 ${id.cosine}）`
      }
    } catch (e) {
      error.value = e.message || String(e)
    }
  }

  async function refreshQcChecklist() {
    if (!slug.value || !episodeN.value) return
    try {
      const data = await dramaApi.getQcChecklist(slug.value, episodeN.value)
      qcChecklist.value = data
    } catch (e) {
      error.value = e.message || String(e)
    }
    return qcChecklist.value
  }

  function toggleChecklistPanel() {
    checklistOpen.value = !checklistOpen.value
    if (checklistOpen.value) void refreshQcChecklist()
  }

  async function rejectAllProblems() {
    if (!slug.value || !episodeN.value) return
    rejectingAll.value = true
    error.value = ''
    notice.value = ''
    try {
      const data = await dramaApi.rejectAllQc(slug.value, episodeN.value)
      qcChecklist.value = data
      bust.value = Date.now()
      await openEpisode(episodeN.value)
      notice.value = `已一键退回 ${data.summary?.total || 0} 镜（标脏待重渲）`
    } catch (e) {
      error.value = e.message || String(e)
    } finally {
      rejectingAll.value = false
    }
  }

  async function runEpisodeQc() {
    if (!slug.value || !episodeN.value) return
    error.value = ''
    notice.value = ''
    rendering.value = true
    try {
      const result = await dramaApi.qcEpisode(slug.value, episodeN.value)
      bust.value = Date.now()
      await openEpisode(episodeN.value)
      const qc = result.qc || {}
      if (qc.can_pass) {
        notice.value = '脚本可点通过（仍须在验收页确认）'
      } else {
        notice.value = qc.block_reason || result.hint || '待修：skipped 或未通过，不能点通过'
      }
    } catch (e) {
      error.value = e.message || String(e)
    } finally {
      rendering.value = false
    }
  }

  async function passEpisodeQcGate() {
    if (!slug.value || !episodeN.value) return
    error.value = ''
    notice.value = ''
    try {
      const data = await dramaApi.passEpisodeQc(slug.value, episodeN.value)
      episode.value = data
      notice.value = '本集已通过'
    } catch (e) {
      error.value = e.message || String(e)
    }
  }

  async function rejectSelectedShotQc() {
    if (!slug.value || !episodeN.value || !selectedN.value) return
    error.value = ''
    notice.value = ''
    try {
      const data = await dramaApi.rejectShotQc(slug.value, episodeN.value, selectedN.value)
      episode.value = data
      notice.value = `Shot ${selectedN.value} 已退回待修`
    } catch (e) {
      error.value = e.message || String(e)
    }
  }

  async function passSelectedShotQc() {
    if (!slug.value || !episodeN.value || !selectedN.value) return
    error.value = ''
    notice.value = ''
    try {
      const data = await dramaApi.passShotQc(slug.value, episodeN.value, selectedN.value)
      episode.value = data
      notice.value = `Shot ${selectedN.value} 已通过`
    } catch (e) {
      error.value = e.message || String(e)
    }
  }

  async function remixEpisodeLoudness() {
    if (!slug.value || !episodeN.value) return
    error.value = ''
    notice.value = ''
    rendering.value = true
    try {
      const data = await dramaApi.remixLoudness(slug.value, episodeN.value)
      episode.value = data
      bust.value = Date.now()
      notice.value = data.hint || '已只重 mix，各镜 clip 未改'
    } catch (e) {
      error.value = e.message || String(e)
    } finally {
      rendering.value = false
    }
  }

  async function suggestEpisodeCoverage() {
    if (!slug.value || !episodeN.value) return
    saving.value = true
    error.value = ''
    notice.value = ''
    try {
      const result = await dramaApi.suggestCoverage(slug.value, episodeN.value)
      await openEpisode(episodeN.value)
      const n = result.coverage?.open ?? (result.coverage?.suggestions || []).filter((s) => s.status === 'open').length
      notice.value = n ? `导演建议 ${n} 条（未改镜头、未加锁）` : '暂无新的覆盖建议'
    } catch (e) {
      error.value = e.message || String(e)
    } finally {
      saving.value = false
    }
  }

  async function applyCoverageSuggestion(sid) {
    if (!slug.value || !episodeN.value || !sid) return
    saving.value = true
    error.value = ''
    notice.value = ''
    try {
      await dramaApi.applyCoverage(slug.value, episodeN.value, sid)
      bust.value = Date.now()
      await openEpisode(episodeN.value)
      notice.value = '已采纳建议（未自动锁定）'
    } catch (e) {
      error.value = e.message || String(e)
    } finally {
      saving.value = false
    }
  }

  async function dismissCoverageSuggestion(sid) {
    if (!slug.value || !episodeN.value || !sid) return
    saving.value = true
    error.value = ''
    notice.value = ''
    try {
      await dramaApi.dismissCoverage(slug.value, episodeN.value, sid)
      await openEpisode(episodeN.value)
      notice.value = '已忽略该建议'
    } catch (e) {
      error.value = e.message || String(e)
    } finally {
      saving.value = false
    }
  }

  async function lockCoverageSuggestion(sid) {
    if (!slug.value || !episodeN.value || !sid) return
    saving.value = true
    error.value = ''
    notice.value = ''
    try {
      await dramaApi.lockCoverage(slug.value, episodeN.value, sid)
      await openEpisode(episodeN.value)
      notice.value = '已锁定该镜类型，建议不会再覆盖'
    } catch (e) {
      error.value = e.message || String(e)
    } finally {
      saving.value = false
    }
  }

  async function exportTimeline() {
    if (!slug.value || !episodeN.value) return
    if (mixUnlicensed.value) {
      error.value = episode.value?.mix?.license?.reason || '上传 BGM 需要勾选「我有商用权」'
      return
    }
    if (orderDirty.value) await saveTimelineOrder()
    if (timelineDirty.value && selectedN.value) await saveTimelineShot()
    if (mixDirty.value) await saveMix()
    error.value = ''
    notice.value = ''
    rendering.value = true
    setBatchProgress({
      kind: 'export',
      label: '导出整集',
      current: 0,
      total: 1,
      status: 'running',
      message: '整集导出排队中…',
    })
    try {
      const result = await dramaApi.exportEpisode(slug.value, episodeN.value, true, false)
      if (result.job_id) {
        await trackJob(result, slug.value)
        notice.value = '整集导出已加入后台队列'
        setBatchProgress({
          status: 'running',
          message: '整集导出进行中（后台）…',
          jobId: result.job_id,
        })
        rendering.value = false
        return
      }
      bust.value = Date.now()
      await openEpisode(episodeN.value)
      notice.value = `整集已导出（${result.assemble || 'assemble'} / ${result.mix_mode || 'mix'}，约 ${result.timeline?.total_duration || '?'}s）`
      setBatchProgress({ status: 'done', current: 1, total: 1, message: notice.value })
    } catch (e) {
      const msg = e.message || String(e)
      const qcBlocked = /QC 硬闸|响度验收|身份/.test(msg)
      if (qcBlocked && window.confirm(`${msg}\n\n工作台可强制导出带瑕疵成片，是否强制导出？`)) {
        try {
          const forced = await dramaApi.exportEpisode(slug.value, episodeN.value, true, true)
          if (forced.job_id) {
            await trackJob(forced, slug.value)
            notice.value = '已强制导出（后台队列）'
            setBatchProgress({
              status: 'running',
              message: '强制导出进行中…',
              jobId: forced.job_id,
            })
            rendering.value = false
            return
          }
          bust.value = Date.now()
          await openEpisode(episodeN.value)
          notice.value = '已强制导出（QC 未全部通过）'
          setBatchProgress({ status: 'done', current: 1, total: 1, message: notice.value })
          return
        } catch (e2) {
          error.value = e2.message || String(e2)
          setBatchProgress({ status: 'error', message: error.value })
          return
        }
      }
      error.value = msg
      setBatchProgress({ status: 'error', message: error.value })
    } finally {
      if (!batchProgress.value?.jobId) {
        rendering.value = false
        clearBatchProgressSoon()
      }
    }
  }

  async function saveMix() {
    if (!slug.value || !episodeN.value) return
    error.value = ''
    saving.value = true
    try {
      const body = {
        volume: mixDraft.value.volume,
        duck_db: mixDraft.value.duck_db,
        license_ok: mixDraft.value.license_ok,
      }
      if (mixDraft.value.catalog_id) body.catalog_id = mixDraft.value.catalog_id
      const data = await dramaApi.patchMix(slug.value, episodeN.value, body)
      episode.value = data
      fillMixDraft(data)
      notice.value = '混音参数已保存（未烧进各镜 clip）'
    } catch (e) {
      error.value = e.message || String(e)
    } finally {
      saving.value = false
    }
  }

  async function uploadBgm(file, licenseOk) {
    if (!slug.value || !episodeN.value || !file) return
    error.value = ''
    saving.value = true
    try {
      const data = await dramaApi.uploadEpisodeBgm(slug.value, episodeN.value, file, {
        licenseOk: Boolean(licenseOk),
        title: file.name || '',
      })
      episode.value = data
      fillMixDraft(data)
      notice.value = licenseOk ? 'BGM 已上传并标记商用权' : 'BGM 已上传，勾选「我有商用权」后才能导出'
    } catch (e) {
      error.value = e.message || String(e)
    } finally {
      saving.value = false
    }
  }

  async function applyMix() {
    if (!slug.value || !episodeN.value) return
    if (mixUnlicensed.value) {
      error.value = episode.value?.mix?.license?.reason || '上传 BGM 需要勾选「我有商用权」'
      return
    }
    if (mixDirty.value) await saveMix()
    error.value = ''
    notice.value = ''
    rendering.value = true
    setBatchProgress({
      kind: 'mix',
      label: '应用混音',
      current: 0,
      total: 1,
      status: 'running',
      message: '混音处理中…',
    })
    try {
      const result = await dramaApi.mixEpisode(slug.value, episodeN.value, false)
      if (result.job_id) {
        await trackJob(result, slug.value)
        notice.value = '混音已加入后台队列'
        setBatchProgress({
          status: 'running',
          message: '混音进行中（后台）…',
          jobId: result.job_id,
        })
        rendering.value = false
        return
      }
      bust.value = Date.now()
      episode.value = result
      fillMixDraft(result)
      notice.value = `已混音（${result.mix_mode || 'mix'}），各镜 clip 未改`
      setBatchProgress({ status: 'done', current: 1, total: 1, message: notice.value })
    } catch (e) {
      error.value = e.message || String(e)
      setBatchProgress({ status: 'error', message: error.value })
    } finally {
      if (!batchProgress.value?.jobId) {
        rendering.value = false
        clearBatchProgressSoon()
      }
    }
  }

  async function clearBgm() {
    if (!slug.value || !episodeN.value) return
    error.value = ''
    saving.value = true
    try {
      const data = await dramaApi.patchMix(slug.value, episodeN.value, { clear: true })
      episode.value = data
      fillMixDraft(data)
      notice.value = '已清除 BGM'
    } catch (e) {
      error.value = e.message || String(e)
    } finally {
      saving.value = false
    }
  }

  async function generateCharacterRef(cid) {
    if (!slug.value || !cid) return
    saving.value = true
    error.value = ''
    try {
      await dramaApi.saveCharacter(slug.value, cid, {
        name: String(charDraft.value.name || '').trim(),
        look: charDraft.value.look,
        voice: charDraft.value.voice,
        aliases: String(charDraft.value.aliases || '').trim(),
        ref_size: charDraft.value.ref_size || 1024,
        ref_image_provider: charDraft.value.ref_image_provider,
        ref_image_model: charDraft.value.ref_image_model,
        category: charDraft.value.category || 'character',
      })
      const rec = await dramaApi.generateCharacterRef(slug.value, cid)
      bust.value = Date.now()
      await refreshCast()
      return rec
    } catch (e) {
      error.value = e.message || String(e)
    } finally {
      saving.value = false
    }
  }

  async function refineCharacterRef(cid, instruction) {
    if (!slug.value || !cid || !String(instruction || '').trim()) return null
    saving.value = true
    error.value = ''
    try {
      const data = await dramaApi.refineCharacterRef(slug.value, cid, instruction)
      bust.value = Date.now()
      if (selectedCharacterId.value === cid && data?.look != null) {
        charDraft.value.look = data.look
      }
      await refreshCast()
      return data
    } catch (e) {
      error.value = e.message || String(e)
      return null
    } finally {
      saving.value = false
    }
  }

  function castChatMessages(cid) {
    if (!cid) return []
    return castChatHistory.value[cid] || []
  }

  function pushCastChatMessage(cid, role, content) {
    if (!cid || !content) return
    const prev = castChatHistory.value[cid] || []
    castChatHistory.value = {
      ...castChatHistory.value,
      [cid]: [...prev, { role, content }],
    }
  }

  async function sendCastChatRefine(cid, instruction) {
    const text = String(instruction || '').trim()
    if (!cid || !text) return null
    pushCastChatMessage(cid, 'user', text)
    const data = await refineCharacterRef(cid, text)
    if (data?.reply) {
      pushCastChatMessage(cid, 'assistant', data.reply)
    } else if (error.value) {
      pushCastChatMessage(cid, 'assistant', error.value)
    }
    return data
  }

  function shotChatKey(stage, shotN) {
    return `${stage}:${episodeN.value || 0}:${shotN}`
  }

  function shotChatMessages(stage, shotN) {
    if (!stage || !shotN) return []
    return shotChatHistory.value[shotChatKey(stage, shotN)] || []
  }

  function pushShotChatMessage(stage, shotN, role, content) {
    if (!stage || !shotN || !content) return
    const key = shotChatKey(stage, shotN)
    const prev = shotChatHistory.value[key] || []
    shotChatHistory.value = {
      ...shotChatHistory.value,
      [key]: [...prev, { role, content }],
    }
  }

  async function refineShotChat(stage, shotN, instruction) {
    const text = String(instruction || '').trim()
    if (!slug.value || !episodeN.value || !shotN || !text) return null
    pushShotChatMessage(stage, shotN, 'user', text)
    saving.value = true
    error.value = ''
    try {
      const data = await dramaApi.refineShot(slug.value, episodeN.value, shotN, text, stage)
      // Always reload episode so scriptDraft / cascaded timings stay globally in sync.
      bust.value = Date.now()
      await openEpisode(episodeN.value)
      if (data?.shot && Number(selectedN.value) === Number(shotN)) {
        fillDraft(data.shot)
      }
      const reply = data?.reply || '已更新分镜字段。'
      pushShotChatMessage(stage, shotN, 'assistant', reply)
      notice.value = reply
      return data
    } catch (e) {
      error.value = e.message || String(e)
      pushShotChatMessage(stage, shotN, 'assistant', error.value)
      return null
    } finally {
      saving.value = false
    }
  }

  async function generateAllCharacterRefs(category = '') {
    if (!slug.value) return
    rendering.value = true
    error.value = ''
    notice.value = ''
    try {
      const cards = characters.value.filter((c) => {
        if (category && (c.category || 'character') !== category) return false
        return !(c.ref_locked && c.ref_exists)
      })
      if (!cards.length) {
        notice.value = '没有可生成的定妆照'
        return
      }
      setBatchProgress({
        kind: 'refs',
        label: '批量生成定妆',
        current: 0,
        total: cards.length,
        status: 'running',
        message: `批量定妆 0/${cards.length}`,
        failed: 0,
      })
      let done = 0
      let failed = 0
      await runPool(
        cards,
        async (c) => {
          await dramaApi.generateCharacterRef(slug.value, c.id)
          return c
        },
        {
          onProgress: (completed, total, item, result) => {
            if (result?.__error) failed += 1
            else done += 1
            setBatchProgress({
              kind: 'refs',
              label: '批量生成定妆',
              current: completed,
              total,
              status: 'running',
              message: `批量定妆 ${completed}/${total}${item?.name ? ` · ${item.name}` : ''}`,
              failed,
            })
          },
        },
      )
      bust.value = Date.now()
      await refreshCast()
      notice.value = failed
        ? `已生成 ${done} 张定妆，${failed} 张失败`
        : `已生成 ${done} 张定妆`
      setBatchProgress({
        status: done ? 'done' : 'error',
        current: cards.length,
        total: cards.length,
        message: notice.value,
        failed,
      })
    } catch (e) {
      error.value = e.message || String(e)
      setBatchProgress({ status: 'error', message: error.value })
    } finally {
      rendering.value = false
      clearBatchProgressSoon()
    }
  }

  async function chooseCharacterCandidate(cid, candId) {
    if (!slug.value || !cid || !candId) return
    saving.value = true
    error.value = ''
    try {
      await dramaApi.chooseCharacterCandidate(slug.value, cid, candId)
      bust.value = Date.now()
      await refreshCast()
    } catch (e) {
      error.value = e.message || String(e)
    } finally {
      saving.value = false
    }
  }

  async function deleteCharacterCandidate(cid, candId) {
    if (!slug.value || !cid || !candId) return
    saving.value = true
    error.value = ''
    try {
      await dramaApi.deleteCharacterCandidate(slug.value, cid, candId)
      bust.value = Date.now()
      await refreshCast()
    } catch (e) {
      error.value = e.message || String(e)
    } finally {
      saving.value = false
    }
  }

  async function generateAllScenes() {
    const ep = episodeN.value
    if (!slug.value || !ep) return
    const targets = shots.value.filter((s) => {
      if ((s.locked || []).some((k) => k === 'shot' || k === 'scene')) return false
      if (generatingCandidateNs.value.includes(s.n)) return false
      return true
    })
    if (!targets.length) {
      notice.value = '没有可出图的镜头（已锁画面或整镜）'
      return
    }
    rendering.value = true
    error.value = ''
    notice.value = ''
    generatingCandidateNs.value = [...generatingCandidateNs.value, ...targets.map((s) => s.n)]
    setBatchProgress({
      kind: 'scenes',
      label: '批量出图',
      current: 0,
      total: targets.length,
      status: 'running',
      message: `批量出图 0/${targets.length}`,
      failed: 0,
    })
    let done = 0
    let failed = 0
    try {
      await runPool(
        targets,
        async (s) => {
          const result = await dramaApi.generateCandidates(slug.value, ep, s.n, 4)
          if (result.shot) mergeEpisodeShot(result.shot)
          bust.value = Date.now()
          return result
        },
        {
          onProgress: (completed, total, item, result) => {
            if (result?.__error) failed += 1
            else done += 1
            setBatchProgress({
              kind: 'scenes',
              label: '批量出图',
              current: completed,
              total,
              shotN: item?.n,
              status: 'running',
              message: `批量出图 ${completed}/${total} · Shot ${item?.n ?? '?'}`,
              failed,
            })
            finishCandidateGeneration(item.n)
          },
        },
      )
      notice.value = done
        ? failed
          ? `已为 ${done} 镜出图，${failed} 镜失败`
          : `已为 ${done} 镜出图（画面）`
        : '没有可出图的镜头（已锁画面或整镜）'
      setBatchProgress({
        status: done ? 'done' : 'error',
        current: targets.length,
        total: targets.length,
        message: notice.value,
        failed,
      })
    } catch (e) {
      error.value = e.message || String(e)
      setBatchProgress({ status: 'error', message: error.value })
      generatingCandidateNs.value = []
    } finally {
      rendering.value = false
      clearBatchProgressSoon()
    }
  }

  async function generateAllVideo() {
    const ep = episodeN.value
    if (!slug.value || !ep) return
    const targets = shots.value.filter((s) => shotEligibleForI2v(s) && s.i2v_source !== 'ai' && s.i2v_source !== 'keys')
    if (!targets.length) {
      error.value = ''
      notice.value = '没有可生成视频的镜头（需已锁定画面，且非 L0 / 未生成过 I2V）'
      return
    }
    rendering.value = true
    error.value = ''
    notice.value = ''
    let done = 0
    let failed = 0
    setBatchProgress({
      kind: 'video',
      label: '批量生成视频',
      mode: 'batch',
      current: 0,
      total: targets.length,
      status: 'running',
      message: `批量生成 0/${targets.length}`,
      failed: 0,
    })
    try {
      await runPool(
        targets,
        async (s) => {
          const result = await runI2vForShot(s.n)
          return result
        },
        {
          onProgress: (completed, total, item, result) => {
            const bad = result?.__error || result?.status === 'error'
            if (bad) failed += 1
            else done += 1
            setBatchProgress({
              kind: 'video',
              label: '批量生成视频',
              mode: 'batch',
              current: completed,
              total,
              shotN: item?.n,
              status: 'running',
              message: `批量生成 ${completed}/${total} · Shot ${item?.n ?? '?'}`,
              failed,
            })
          },
        },
      )
      bust.value = Date.now()
      await openEpisode(ep)
      if (done) {
        notice.value = failed
          ? `已为 ${done} 镜生成视频，${failed} 镜失败`
          : `已为 ${done} 镜生成视频`
        setBatchProgress({
          status: 'done',
          current: targets.length,
          total: targets.length,
          message: notice.value,
          failed,
        })
      } else {
        error.value = '批量生成视频失败，请检查画面是否已锁定'
        setBatchProgress({
          status: 'error',
          message: error.value,
          failed,
        })
      }
    } catch (e) {
      error.value = e.message || String(e)
      setBatchProgress({
        status: 'error',
        message: error.value,
      })
    } finally {
      rendering.value = false
      clearBatchProgressSoon()
    }
  }

  async function generateAllVoice() {
    const ep = episodeN.value
    if (!slug.value || !ep) return
    const targets = shots.value.filter((s) => {
      if ((s.locked || []).includes('shot')) return false
      return Boolean(String(s.字幕 || '').trim())
    })
    if (!targets.length) {
      notice.value = '没有可配音的镜头'
      return
    }
    rendering.value = true
    error.value = ''
    notice.value = ''
    let done = 0
    let failed = 0
    setBatchProgress({
      kind: 'voice',
      label: '批量生成配音',
      current: 0,
      total: targets.length,
      status: 'running',
      message: `批量配音 0/${targets.length}`,
      failed: 0,
    })
    try {
      await runPool(
        targets,
        async (s) => {
          await dramaApi.rerenderShot(slug.value, ep, s.n, ['overlay', 'voice', 'lip'])
          return s
        },
        {
          onProgress: (completed, total, item, result) => {
            if (result?.__error) failed += 1
            else done += 1
            setBatchProgress({
              kind: 'voice',
              label: '批量生成配音',
              current: completed,
              total,
              shotN: item?.n,
              status: 'running',
              message: `批量配音 ${completed}/${total} · Shot ${item?.n ?? '?'}`,
              failed,
            })
          },
        },
      )
      bust.value = Date.now()
      await openEpisode(ep)
      notice.value = done
        ? failed
          ? `已为 ${done} 镜生成配音，${failed} 镜失败`
          : `已为 ${done} 镜生成配音与口型`
        : '没有可配音的镜头'
      setBatchProgress({
        status: done ? 'done' : 'error',
        current: targets.length,
        total: targets.length,
        message: notice.value,
        failed,
      })
    } catch (e) {
      error.value = e.message || String(e)
      setBatchProgress({ status: 'error', message: error.value })
    } finally {
      rendering.value = false
      clearBatchProgressSoon()
    }
  }

  return {
    projects,
    slug,
    project,
    episodeN,
    episode,
    selectedN,
    selected,
    shots,
    episodes,
    draft,
    dirty,
    saving,
    rendering,
    generatingCandidateNs,
    videoGenProgress,
    batchProgress,
    error,
    notice,
    bust,
    scriptDraft,
    scriptImpact,
    boardMode,
    characters,
    voices,
    selectedCharacterId,
    selectedCharacter,
    charDraft,
    timelineOrder,
    tlDraft,
    mixDraft,
    config,
    presets,
    currentPreset,
    modelCatalog,
    providerHealth,
    degradedProviders,
    selectedConfigNode,
    configNodeDraft,
    configNodeList,
    stageModelSelection,
    applyStageModel,
    selectedShotIds,
    batchField,
    batchValue,
    batchFields,
    snapshots,
    snapshotsOpen,
    budget,
    budgetBlocked,
    budgetWarn,
    budgetDraft,
    budgetOpen,
    toggleBudgetPanel,
    saveBudget,
    qcChecklist,
    checklistOpen,
    rejectingAll,
    toggleChecklistPanel,
    refreshQcChecklist,
    rejectAllProblems,
    toggleShotSelected,
    clearShotSelection,
    selectAllShots,
    applyBatchEdit,
    refreshSnapshots,
    toggleSnapshotsPanel,
    restoreSnapshotVersion,
    deleteSnapshotVersion,
    timelineItems,
    orderedShots,
    transitions,
    i2vModes,
    shotKinds,
    shotSizes,
    timelineDirty,
    orderDirty,
    mixDirty,
    mixUnlicensed,
    assetUrl,
    refreshProjects,
    deleteProject,
    loadConfig,
    applyProjectPreset,
    selectConfigNode,
    saveConfigNode,
    openProject,
    openEpisode,
    selectShot,
    saveShot,
    rerenderSelected: () => rerenderLayer(),
    rerenderLayer,
    toggleLock,
    saveEpisodeMeta,
    previewScriptChanges,
    saveScriptChanges,
    generateScriptFromPremise,
    rerenderDirtyShots,
    selectCharacter,
    toggleShotRole,
    addCharacter,
    saveCharacterCard,
    lockSelectedRef,
    uploadSelectedRef,
    deleteSelectedCharacter,
    generateCharacterRef,
    refineCharacterRef,
    castChatHistory,
    castChatMessages,
    sendCastChatRefine,
    shotChatMessages,
    refineShotChat,
    generateAllCharacterRefs,
    chooseCharacterCandidate,
    deleteCharacterCandidate,
    generateAllScenes,
    generateAllVideo,
    generateAllVoice,
    generateShotCandidates,
    chooseShotCandidate,
    deleteCandidate,
    uploadShotScene,
    generateShotI2v,
    generateShotLip,
    generateShotKeys,
    chooseShotKey,
    uploadShotKey,
    lockShotKey,
    qcSelectedShot,
    runEpisodeQc,
    passEpisodeQcGate,
    rejectSelectedShotQc,
    passSelectedShotQc,
    remixEpisodeLoudness,
    suggestEpisodeCoverage,
    applyCoverageSuggestion,
    dismissCoverageSuggestion,
    lockCoverageSuggestion,
    classifyEpisodeShots,
    applyEpisodeStyle,
    saveTimelineShot,
    saveTimelineOrder,
    saveTimelineAll,
    moveTimelineShot,
    reorderTimeline,
    exportTimeline,
    saveMix,
    uploadBgm,
    applyMix,
    clearBgm,
    renderJobs,
    activeJobs,
    cancelRenderJob: cancelJob,
    retryRenderJob: (jobId) => retryJob(jobId, slug.value),
  }
}
