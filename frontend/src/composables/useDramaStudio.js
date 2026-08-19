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
  const error = ref('')
  const notice = ref('')
  const bust = ref(0)
  const scriptDraft = ref('')
  const scriptImpact = ref(null)
  const boardMode = ref('shots')
  const selectedCharacterId = ref(null)
  const charDraft = ref(emptyCharDraft())
  const timelineOrder = ref([])
  const tlDraft = ref(emptyTlDraft())
  const mixDraft = ref(emptyMixDraft())

  const {
    jobs: renderJobs,
    activeJobs,
    trackJob,
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
  const voices = computed(() => project.value?.voices || episode.value?.voices || [])
  const selectedCharacter = computed(
    () => characters.value.find((c) => c.id === selectedCharacterId.value) || null,
  )
  const dirty = computed(() => {
    const shot = selected.value
    if (!shot) return false
    return (
      String(draft.value.画面 || '') !== String(shot.画面 || '') ||
      String(draft.value.对白 || '') !== String(shot.对白 || '') ||
      String(draft.value.字幕 || '') !== String(shot.字幕 || '') ||
      String(draft.value.camera || '') !== String(shot.camera || '') ||
      Number(draft.value.duration || 0) !== Number(shot.duration || 0) ||
      String(draft.value.i2v || 'auto') !== String(shot.i2v || 'auto') ||
      String(draft.value.kind || '') !== String(shot.kind || '') ||
      String(draft.value.size || '') !== String(shot.size || '') ||
      String(draft.value.speaker || '') !== String(shot.speaker || '') ||
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
    return { 画面: '', 对白: '', 字幕: '', 角色: [], camera: 'punch_in', duration: 3, i2v: 'auto', kind: 'establishing', size: 'WS', speaker: '' }
  }

  function emptyCharDraft() {
    return { id: '', name: '', look: '', voice: 'zh-CN-YunxiNeural', aliases: '', colors: '' }
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

  function fillDraft(shot) {
    draft.value = {
      画面: shot?.画面 || '',
      对白: shot?.对白 || '',
      字幕: shot?.字幕 || '',
      角色: Array.isArray(shot?.角色) ? [...shot.角色] : [],
      camera: shot?.camera || 'punch_in',
      duration: Number(shot?.duration || 3),
      i2v: shot?.i2v || 'auto',
      kind: shot?.kind || 'establishing',
      size: shot?.size || 'WS',
      speaker: shot?.speaker || '',
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
    charDraft.value = {
      id: char?.id || '',
      name: char?.name || '',
      look: char?.look || '',
      voice: char?.voice || 'zh-CN-YunxiNeural',
      aliases: (char?.aliases || []).join('、'),
      colors: char?.colors || '',
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

  async function saveShot() {
    if (!slug.value || !episodeN.value || !selectedN.value) return
    saving.value = true
    error.value = ''
    notice.value = ''
    try {
      const shot = selected.value
      const body = {}
      if (String(draft.value.画面 || '') !== String(shot.画面 || '')) body.画面 = draft.value.画面
      if (String(draft.value.对白 || '') !== String(shot.对白 || '')) body.对白 = draft.value.对白
      if (String(draft.value.字幕 || '') !== String(shot.字幕 || '')) body.字幕 = draft.value.字幕
      if (String(draft.value.camera || '') !== String(shot.camera || '')) body.camera = draft.value.camera
      if (Number(draft.value.duration || 0) !== Number(shot.duration || 0)) {
        body.duration = Number(draft.value.duration)
      }
      if (rolesKey(draft.value.角色) !== rolesKey(shot.角色)) {
        body.角色 = [...(draft.value.角色 || [])]
      }
      if (String(draft.value.i2v || 'auto') !== String(shot.i2v || 'auto')) {
        body.i2v = draft.value.i2v || 'auto'
      }
      if (String(draft.value.kind || '') !== String(shot.kind || '')) body.kind = draft.value.kind
      if (String(draft.value.size || '') !== String(shot.size || '')) body.size = draft.value.size
      if (String(draft.value.speaker || '') !== String(shot.speaker || '')) {
        body.speaker = draft.value.speaker || ''
      }
      if (!Object.keys(body).length) {
        notice.value = '没有改动'
        return
      }
      await dramaApi.patchShot(slug.value, episodeN.value, selectedN.value, body)
      bust.value = Date.now()
      await openEpisode(episodeN.value)
      notice.value = '已保存（未重渲）。脏层会在下次渲染时更新。'
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
      await dramaApi.lockShot(slug.value, episodeN.value, selectedN.value, has ? { unlock: [layer] } : { lock: [layer] })
      await openEpisode(episodeN.value)
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

  async function rerenderDirtyShots() {
    if (!slug.value || !episodeN.value) return
    error.value = ''
    notice.value = ''
    try {
      const result = await dramaApi.rerenderDirty(slug.value, episodeN.value)
      if (result.job_id) {
        await trackJob(result, slug.value)
        notice.value = '脏镜渲染已加入后台队列，可切回聊天或看底部任务条'
        return
      }
      bust.value = Date.now()
      await openEpisode(episodeN.value)
      notice.value = result.impact?.summary || '脏镜已重渲'
    } catch (e) {
      error.value = e.message || String(e)
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

  async function addCharacter() {
    if (!slug.value) return
    saving.value = true
    error.value = ''
    notice.value = ''
    try {
      const rec = await dramaApi.createCharacter(slug.value, { name: '新角色' })
      await refreshCast()
      selectCharacter(rec.id)
      notice.value = '已添加角色卡'
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
      error.value = '请填写角色 id 或名字'
      return
    }
    saving.value = true
    error.value = ''
    notice.value = ''
    try {
      const rec = cid
        ? await dramaApi.saveCharacter(slug.value, cid, {
            name: charDraft.value.name,
            look: charDraft.value.look,
            voice: charDraft.value.voice,
            aliases: charDraft.value.aliases,
            colors: charDraft.value.colors,
          })
        : await dramaApi.createCharacter(slug.value, {
            name: charDraft.value.name,
            look: charDraft.value.look,
            voice: charDraft.value.voice,
            aliases: charDraft.value.aliases,
            colors: charDraft.value.colors,
          })
      await refreshCast()
      selectCharacter(rec.id)
      notice.value = '角色卡已保存；外形/音色改动会标记相关镜头为脏'
    } catch (e) {
      error.value = e.message || String(e)
    } finally {
      saving.value = false
    }
  }

  async function lockSelectedRef() {
    if (!slug.value || !selectedCharacterId.value) return
    const locked = !selectedCharacter.value?.ref_locked
    saving.value = true
    error.value = ''
    try {
      await dramaApi.lockCharacterRef(slug.value, selectedCharacterId.value, locked)
      await refreshCast()
      notice.value = locked ? '已锁定参考图' : '已解锁参考图'
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
      notice.value = '参考图已更新，出图 prompt 会带上外形与配色'
    } catch (e) {
      error.value = e.message || String(e)
    } finally {
      saving.value = false
    }
  }

  async function deleteSelectedCharacter() {
    if (!slug.value || !selectedCharacterId.value) return
    saving.value = true
    error.value = ''
    try {
      await dramaApi.deleteCharacter(slug.value, selectedCharacterId.value)
      selectedCharacterId.value = null
      await refreshCast()
      notice.value = '角色已删除'
    } catch (e) {
      error.value = e.message || String(e)
    } finally {
      saving.value = false
    }
  }

  async function generateShotCandidates(count = 4) {
    if (!slug.value || !episodeN.value || !selectedN.value) return
    rendering.value = true
    error.value = ''
    notice.value = ''
    try {
      const result = await dramaApi.generateCandidates(slug.value, episodeN.value, selectedN.value, count)
      bust.value = Date.now()
      await openEpisode(episodeN.value)
      notice.value = `已生成 ${(result.created || []).length} 张候选`
    } catch (e) {
      error.value = e.message || String(e)
    } finally {
      rendering.value = false
    }
  }

  async function chooseShotCandidate(cid) {
    if (!slug.value || !episodeN.value || !selectedN.value || !cid) return
    rendering.value = true
    error.value = ''
    notice.value = ''
    try {
      const result = await dramaApi.chooseCandidate(slug.value, episodeN.value, selectedN.value, cid)
      bust.value = Date.now()
      await openEpisode(episodeN.value)
      const rebuilt = (result.rebuilt_layers || []).join(' / ') || '无'
      notice.value = `已锁定 ${cid}（只换画面，配音保留；重建：${rebuilt}）`
    } catch (e) {
      error.value = e.message || String(e)
    } finally {
      rendering.value = false
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

  async function generateShotI2v() {
    if (!slug.value || !episodeN.value || !selectedN.value) return
    error.value = ''
    notice.value = ''
    try {
      const result = await dramaApi.generateI2v(slug.value, episodeN.value, selectedN.value)
      if (result.job_id) {
        await trackJob(result, slug.value)
        notice.value = `Shot ${selectedN.value} I2V 已加入后台队列`
        return
      }
      bust.value = Date.now()
      await openEpisode(episodeN.value)
      notice.value = `I2V 完成（${result.i2v_source || 'none'}）`
    } catch (e) {
      error.value = e.message || String(e)
    }
  }

  async function generateShotLip() {
    if (!slug.value || !episodeN.value || !selectedN.value) return
    error.value = ''
    notice.value = ''
    try {
      const result = await dramaApi.generateLip(slug.value, episodeN.value, selectedN.value)
      if (result.job_id) {
        await trackJob(result, slug.value)
        notice.value = `Shot ${selectedN.value} 口型已加入后台队列`
        return
      }
      bust.value = Date.now()
      await openEpisode(episodeN.value)
      notice.value = `口型完成（${result.lip_source || 'none'}）`
    } catch (e) {
      error.value = e.message || String(e)
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
    try {
      const result = await dramaApi.exportEpisode(slug.value, episodeN.value, true)
      if (result.job_id) {
        await trackJob(result, slug.value)
        notice.value = '整集导出已加入后台队列'
        return
      }
      bust.value = Date.now()
      await openEpisode(episodeN.value)
      notice.value = `整集已导出（${result.assemble || 'assemble'} / ${result.mix_mode || 'mix'}，约 ${result.timeline?.total_duration || '?'}s）`
    } catch (e) {
      error.value = e.message || String(e)
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
    try {
      const result = await dramaApi.mixEpisode(slug.value, episodeN.value, false)
      if (result.job_id) {
        await trackJob(result, slug.value)
        notice.value = '混音已加入后台队列'
        return
      }
      bust.value = Date.now()
      episode.value = result
      fillMixDraft(result)
      notice.value = `已混音（${result.mix_mode || 'mix'}），各镜 clip 未改`
    } catch (e) {
      error.value = e.message || String(e)
    } finally {
      rendering.value = false
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
    rerenderDirtyShots,
    selectCharacter,
    toggleShotRole,
    addCharacter,
    saveCharacterCard,
    lockSelectedRef,
    uploadSelectedRef,
    deleteSelectedCharacter,
    generateShotCandidates,
    chooseShotCandidate,
    uploadShotScene,
    generateShotI2v,
    generateShotLip,
    classifyEpisodeShots,
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
