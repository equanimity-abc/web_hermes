import { computed, ref } from 'vue'
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
    episodeN.value = data.episode
    episode.value = data
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

  async function rerenderSelected() {
    if (!slug.value || !episodeN.value || !selectedN.value) return
    if (dirty.value) {
      await saveShot()
      if (error.value) return
    }
    rendering.value = true
    error.value = ''
    notice.value = ''
    try {
      await dramaApi.rerenderShot(slug.value, episodeN.value, selectedN.value)
      bust.value = Date.now()
      await openEpisode(episodeN.value)
      notice.value = '本镜已重渲，整集已重拼。'
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
    assetUrl,
    refreshProjects,
    openProject,
    openEpisode,
    selectShot,
    saveShot,
    rerenderSelected,
    saveEpisodeMeta,
  }
}
