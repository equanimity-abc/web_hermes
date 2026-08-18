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

  const shots = computed(() => episode.value?.shots || [])
  const selected = computed(() => shots.value.find((s) => s.n === selectedN.value) || null)
  const episodes = computed(() => project.value?.episodes || [])
  const dirty = computed(() => {
    const shot = selected.value
    if (!shot) return false
    return (
      String(draft.value.画面 || '') !== String(shot.画面 || '') ||
      String(draft.value.对白 || '') !== String(shot.对白 || '') ||
      String(draft.value.字幕 || '') !== String(shot.字幕 || '') ||
      String(draft.value.camera || '') !== String(shot.camera || '') ||
      Number(draft.value.duration || 0) !== Number(shot.duration || 0)
    )
  })

  function emptyDraft() {
    return { 画面: '', 对白: '', 字幕: '', camera: 'punch_in', duration: 3 }
  }

  function fillDraft(shot) {
    draft.value = {
      画面: shot?.画面 || '',
      对白: shot?.对白 || '',
      字幕: shot?.字幕 || '',
      camera: shot?.camera || 'punch_in',
      duration: Number(shot?.duration || 3),
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
  }

  async function openEpisode(n) {
    if (!slug.value) return
    error.value = ''
    const data = await dramaApi.getEpisode(slug.value, n)
    if (episodeN.value !== data.episode) scriptImpact.value = null
    episodeN.value = data.episode
    episode.value = data
    scriptDraft.value = data.script || ''
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
  }
}
