import { computed, ref, watch } from 'vue'
import * as dramaApi from '@/api/drama'

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

  const shots = computed(() => episode.value?.shots || [])
  const timelineItems = computed(() => episode.value?.timeline?.items || [])
  const transitions = computed(() => episode.value?.transitions || episode.value?.timeline?.transitions || [])
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

  function emptyDraft() {
    return { 画面: '', 对白: '', 字幕: '', 角色: [], camera: 'punch_in', duration: 3 }
  }

  function emptyCharDraft() {
    return { id: '', name: '', look: '', voice: 'zh-CN-YunxiNeural', aliases: '', colors: '' }
  }

  function emptyTlDraft() {
    return { trim_in: 0, trim_out: 0, volume: 1, transition: 'auto' }
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
    rendering.value = true
    error.value = ''
    notice.value = ''
    try {
      const result = await dramaApi.rerenderDirty(slug.value, episodeN.value)
      bust.value = Date.now()
      await openEpisode(episodeN.value)
      notice.value = result.impact?.summary || '脏镜已重渲'
    } catch (e) {
      error.value = e.message || String(e)
    } finally {
      rendering.value = false
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

  async function exportTimeline() {
    if (!slug.value || !episodeN.value) return
    if (orderDirty.value) await saveTimelineOrder()
    if (timelineDirty.value && selectedN.value) await saveTimelineShot()
    rendering.value = true
    error.value = ''
    notice.value = ''
    try {
      const result = await dramaApi.exportEpisode(slug.value, episodeN.value)
      bust.value = Date.now()
      await openEpisode(episodeN.value)
      notice.value = `整集已导出（${result.assemble || 'assemble'}，约 ${result.timeline?.total_duration || '?'}s）`
    } catch (e) {
      error.value = e.message || String(e)
    } finally {
      rendering.value = false
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
    timelineItems,
    orderedShots,
    transitions,
    timelineDirty,
    orderDirty,
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
    saveTimelineShot,
    saveTimelineOrder,
    saveTimelineAll,
    moveTimelineShot,
    reorderTimeline,
    exportTimeline,
  }
}
