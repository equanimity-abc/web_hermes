/**
 * Drama workbench REST (does not go through the agent loop).
 */

async function request(path, options = {}) {
  const method = (options.method || 'GET').toUpperCase()
  const headers = { ...(options.headers || {}) }
  if (method !== 'GET' && method !== 'HEAD') {
    headers['Content-Type'] = headers['Content-Type'] || 'application/json'
  }
  const resp = await fetch(path, {
    ...options,
    headers,
  })
  const text = await resp.text()
  let data = {}
  try {
    data = text ? JSON.parse(text) : {}
  } catch {
    data = { detail: text || `HTTP ${resp.status}` }
  }
  if (!resp.ok) {
    const detail = data.detail || data.error || text || `HTTP ${resp.status}`
    throw new Error(typeof detail === 'string' ? detail : JSON.stringify(detail))
  }
  return data
}

export function listProjects() {
  return request('/api/drama/projects')
}

export function getProject(slug) {
  return request(`/api/drama/projects/${encodeURIComponent(slug)}`)
}

export function patchProject(slug, body) {
  return request(`/api/drama/projects/${encodeURIComponent(slug)}`, {
    method: 'PATCH',
    body: JSON.stringify(body),
  })
}

export function getConfig(slug) {
  return request(`/api/drama/projects/${encodeURIComponent(slug)}/config`)
}

export function applyPreset(slug, presetId) {
  return request(`/api/drama/projects/${encodeURIComponent(slug)}/config/preset`, {
    method: 'POST',
    body: JSON.stringify({ preset_id: presetId }),
  })
}

export function putNodeConfig(slug, node, value) {
  return request(`/api/drama/projects/${encodeURIComponent(slug)}/config/nodes/${encodeURIComponent(node)}`, {
    method: 'PUT',
    body: JSON.stringify({ value }),
  })
}

export function deleteProject(slug) {
  return request(`/api/drama/projects/${encodeURIComponent(slug)}`, {
    method: 'DELETE',
  })
}

export function getEpisode(slug, episode) {
  return request(`/api/drama/projects/${encodeURIComponent(slug)}/episodes/${episode}`)
}

export function patchEpisode(slug, episode, body) {
  return request(`/api/drama/projects/${encodeURIComponent(slug)}/episodes/${episode}`, {
    method: 'PATCH',
    body: JSON.stringify(body),
  })
}

export function patchShot(slug, episode, shot, body) {
  return request(
    `/api/drama/projects/${encodeURIComponent(slug)}/episodes/${episode}/shots/${shot}`,
    { method: 'PATCH', body: JSON.stringify(body) },
  )
}

export function patchShots(slug, episode, shots, field, value) {
  return request(
    `/api/drama/projects/${encodeURIComponent(slug)}/episodes/${episode}/shots`,
    { method: 'PATCH', body: JSON.stringify({ shots, field, value }) },
  )
}

export function rerenderShot(slug, episode, shot, layers) {
  return request(
    `/api/drama/projects/${encodeURIComponent(slug)}/episodes/${episode}/shots/${shot}/rerender`,
    { method: 'POST', body: JSON.stringify(layers ? { layers } : {}) },
  )
}

export function lockShot(slug, episode, shot, { lock, unlock, locked } = {}) {
  const body = {}
  if (locked !== undefined) body.locked = locked
  if (lock) body.lock = lock
  if (unlock) body.unlock = unlock
  return patchShot(slug, episode, shot, body)
}

export function previewScript(slug, episode, content) {
  return request(
    `/api/drama/projects/${encodeURIComponent(slug)}/episodes/${episode}/script/preview`,
    { method: 'POST', body: JSON.stringify({ content }) },
  )
}

export function saveScript(slug, episode, content, title) {
  return request(`/api/drama/projects/${encodeURIComponent(slug)}/episodes/${episode}/script`, {
    method: 'PUT',
    body: JSON.stringify({ content, title }),
  })
}

export function generateScript(slug, episode, premise) {
  return request(
    `/api/drama/projects/${encodeURIComponent(slug)}/episodes/${episode}/script/generate`,
    { method: 'POST', body: JSON.stringify({ premise }) },
  )
}

export function refineScript(slug, episode, content, instruction) {
  return request(
    `/api/drama/projects/${encodeURIComponent(slug)}/episodes/${episode}/script/refine`,
    { method: 'POST', body: JSON.stringify({ content, instruction }) },
  )
}

export function rerenderDirty(slug, episode) {
  return request(
    `/api/drama/projects/${encodeURIComponent(slug)}/episodes/${episode}/rerender-dirty`,
    { method: 'POST', body: JSON.stringify({}) },
  )
}

export function listCharacters(slug) {
  return request(`/api/drama/projects/${encodeURIComponent(slug)}/characters`)
}

export function saveCharacter(slug, cid, body) {
  return request(`/api/drama/projects/${encodeURIComponent(slug)}/characters/${encodeURIComponent(cid)}`, {
    method: 'PUT',
    body: JSON.stringify(body),
  })
}

export function createCharacter(slug, body) {
  return request(`/api/drama/projects/${encodeURIComponent(slug)}/characters`, {
    method: 'POST',
    body: JSON.stringify(body),
  })
}

export function deleteCharacter(slug, cid) {
  return request(`/api/drama/projects/${encodeURIComponent(slug)}/characters/${encodeURIComponent(cid)}`, {
    method: 'DELETE',
  })
}

export function generateCharacterRef(slug, cid) {
  return request(
    `/api/drama/projects/${encodeURIComponent(slug)}/characters/${encodeURIComponent(cid)}/generate-ref`,
    { method: 'POST', body: JSON.stringify({}) },
  )
}

export function refineCharacterRef(slug, cid, instruction) {
  return request(
    `/api/drama/projects/${encodeURIComponent(slug)}/characters/${encodeURIComponent(cid)}/refine-ref`,
    { method: 'POST', body: JSON.stringify({ instruction }) },
  )
}

export function refineShot(slug, episode, shot, instruction, stage = 'video') {
  return request(
    `/api/drama/projects/${encodeURIComponent(slug)}/episodes/${episode}/shots/${shot}/refine`,
    { method: 'POST', body: JSON.stringify({ instruction, stage }) },
  )
}

export function chooseCharacterCandidate(slug, cid, candId) {
  return request(
    `/api/drama/projects/${encodeURIComponent(slug)}/characters/${encodeURIComponent(cid)}/candidates/${encodeURIComponent(candId)}/choose`,
    { method: 'POST', body: JSON.stringify({}) },
  )
}

export function deleteCharacterCandidate(slug, cid, candId) {
  return request(
    `/api/drama/projects/${encodeURIComponent(slug)}/characters/${encodeURIComponent(cid)}/candidates/${encodeURIComponent(candId)}`,
    { method: 'DELETE' },
  )
}

export function lockCharacterRef(slug, cid, locked) {
  return request(
    `/api/drama/projects/${encodeURIComponent(slug)}/characters/${encodeURIComponent(cid)}/lock-ref`,
    { method: 'POST', body: JSON.stringify({ locked }) },
  )
}

export async function uploadCharacterRef(slug, cid, file) {
  const form = new FormData()
  form.append('file', file)
  const resp = await fetch(
    `/api/drama/projects/${encodeURIComponent(slug)}/characters/${encodeURIComponent(cid)}/ref`,
    { method: 'POST', body: form },
  )
  const text = await resp.text()
  let data = {}
  try {
    data = text ? JSON.parse(text) : {}
  } catch {
    data = { detail: text || `HTTP ${resp.status}` }
  }
  if (!resp.ok) {
    const detail = data.detail || data.error || text || `HTTP ${resp.status}`
    throw new Error(typeof detail === 'string' ? detail : JSON.stringify(detail))
  }
  return data
}

export function generateCandidates(slug, episode, shot, count = 1) {
  return request(
    `/api/drama/projects/${encodeURIComponent(slug)}/episodes/${episode}/shots/${shot}/candidates`,
    { method: 'POST', body: JSON.stringify({ count }) },
  )
}

export function chooseCandidate(slug, episode, shot, cid) {
  return request(
    `/api/drama/projects/${encodeURIComponent(slug)}/episodes/${episode}/shots/${shot}/choose/${encodeURIComponent(cid)}`,
    { method: 'POST', body: JSON.stringify({}) },
  )
}

export function deleteCandidate(slug, episode, shot, cid) {
  return request(
    `/api/drama/projects/${encodeURIComponent(slug)}/episodes/${episode}/shots/${shot}/candidates/${encodeURIComponent(cid)}`,
    { method: 'DELETE' },
  )
}

export async function uploadShotScene(slug, episode, shot, file) {
  const form = new FormData()
  form.append('file', file)
  const resp = await fetch(
    `/api/drama/projects/${encodeURIComponent(slug)}/episodes/${episode}/shots/${shot}/scene`,
    { method: 'POST', body: form },
  )
  const text = await resp.text()
  let data = {}
  try {
    data = text ? JSON.parse(text) : {}
  } catch {
    data = { detail: text || `HTTP ${resp.status}` }
  }
  if (!resp.ok) {
    const detail = data.detail || data.error || text || `HTTP ${resp.status}`
    throw new Error(typeof detail === 'string' ? detail : JSON.stringify(detail))
  }
  return data
}

export function getTimeline(slug, episode) {
  return request(`/api/drama/projects/${encodeURIComponent(slug)}/episodes/${episode}/timeline`)
}

export function patchTimeline(slug, episode, body) {
  return request(`/api/drama/projects/${encodeURIComponent(slug)}/episodes/${episode}/timeline`, {
    method: 'PATCH',
    body: JSON.stringify(body),
  })
}

export function exportEpisode(slug, episode, background = true, force = false) {
  return request(`/api/drama/projects/${encodeURIComponent(slug)}/episodes/${episode}/export`, {
    method: 'POST',
    body: JSON.stringify({ background, force: Boolean(force) }),
  })
}

export function getMix(slug, episode) {
  return request(`/api/drama/projects/${encodeURIComponent(slug)}/episodes/${episode}/mix`)
}

export function patchMix(slug, episode, body) {
  return request(`/api/drama/projects/${encodeURIComponent(slug)}/episodes/${episode}/mix`, {
    method: 'PATCH',
    body: JSON.stringify(body),
  })
}

export function mixEpisode(slug, episode, background = false) {
  return request(`/api/drama/projects/${encodeURIComponent(slug)}/episodes/${episode}/mix`, {
    method: 'POST',
    body: JSON.stringify({ background }),
  })
}

export async function uploadEpisodeBgm(slug, episode, file, { licenseOk = false, title = '' } = {}) {
  const form = new FormData()
  form.append('file', file)
  form.append('license_ok', licenseOk ? 'true' : 'false')
  if (title) form.append('title', title)
  const resp = await fetch(
    `/api/drama/projects/${encodeURIComponent(slug)}/episodes/${episode}/mix/bgm`,
    { method: 'POST', body: form },
  )
  const text = await resp.text()
  let data = {}
  try {
    data = text ? JSON.parse(text) : {}
  } catch {
    data = { detail: text || `HTTP ${resp.status}` }
  }
  if (!resp.ok) {
    const detail = data.detail || data.error || text || `HTTP ${resp.status}`
    throw new Error(typeof detail === 'string' ? detail : JSON.stringify(detail))
  }
  return data
}

export function createJob(slug, episode, body) {
  return request(
    `/api/drama/projects/${encodeURIComponent(slug)}/episodes/${episode}/jobs`,
    { method: 'POST', body: JSON.stringify(body) },
  )
}

export function listJobs({ slug, active = false, limit = 20 } = {}) {
  const params = new URLSearchParams()
  if (slug) params.set('slug', slug)
  if (active) params.set('active', 'true')
  if (limit) params.set('limit', String(limit))
  const q = params.toString()
  return request(`/api/drama/jobs${q ? `?${q}` : ''}`)
}

export function getJob(jobId) {
  return request(`/api/drama/jobs/${encodeURIComponent(jobId)}`)
}

export function cancelJob(jobId) {
  return request(`/api/drama/jobs/${encodeURIComponent(jobId)}/cancel`, {
    method: 'POST',
    body: JSON.stringify({}),
  })
}

export function retryJob(jobId) {
  return request(`/api/drama/jobs/${encodeURIComponent(jobId)}/retry`, {
    method: 'POST',
    body: JSON.stringify({}),
  })
}

export function generateI2v(slug, episode, shot) {
  return request(
    `/api/drama/projects/${encodeURIComponent(slug)}/episodes/${episode}/shots/${shot}/i2v`,
    { method: 'POST', body: JSON.stringify({}) },
  )
}

export function generateLip(slug, episode, shot) {
  return request(
    `/api/drama/projects/${encodeURIComponent(slug)}/episodes/${episode}/shots/${shot}/lip`,
    { method: 'POST', body: JSON.stringify({}) },
  )
}

export function qcShot(slug, episode, shot) {
  return request(
    `/api/drama/projects/${encodeURIComponent(slug)}/episodes/${episode}/shots/${shot}/qc`,
    { method: 'POST', body: JSON.stringify({}) },
  )
}

export function qcEpisode(slug, episode) {
  return request(
    `/api/drama/projects/${encodeURIComponent(slug)}/episodes/${episode}/qc`,
    { method: 'POST', body: JSON.stringify({}) },
  )
}

export function getQcChecklist(slug, episode) {
  return request(
    `/api/drama/projects/${encodeURIComponent(slug)}/episodes/${episode}/qc/checklist`,
  )
}

export function rejectAllQc(slug, episode) {
  return request(
    `/api/drama/projects/${encodeURIComponent(slug)}/episodes/${episode}/qc/reject-all`,
    { method: 'POST', body: JSON.stringify({}) },
  )
}

export function passEpisodeQc(slug, episode) {
  return request(
    `/api/drama/projects/${encodeURIComponent(slug)}/episodes/${episode}/qc/pass`,
    { method: 'POST', body: JSON.stringify({}) },
  )
}

export function remixLoudness(slug, episode) {
  return request(
    `/api/drama/projects/${encodeURIComponent(slug)}/episodes/${episode}/qc/remix`,
    { method: 'POST', body: JSON.stringify({}) },
  )
}

export function passShotQc(slug, episode, shot) {
  return request(
    `/api/drama/projects/${encodeURIComponent(slug)}/episodes/${episode}/shots/${shot}/qc/pass`,
    { method: 'POST', body: JSON.stringify({}) },
  )
}

export function rejectShotQc(slug, episode, shot) {
  return request(
    `/api/drama/projects/${encodeURIComponent(slug)}/episodes/${episode}/shots/${shot}/qc/reject`,
    { method: 'POST', body: JSON.stringify({}) },
  )
}

export function generateKeys(slug, episode, shot, count = 3) {
  return request(
    `/api/drama/projects/${encodeURIComponent(slug)}/episodes/${episode}/shots/${shot}/keys`,
    { method: 'POST', body: JSON.stringify({ count }) },
  )
}

export function chooseKey(slug, episode, shot, kid, cid) {
  return request(
    `/api/drama/projects/${encodeURIComponent(slug)}/episodes/${episode}/shots/${shot}/keys/${encodeURIComponent(kid)}/choose/${encodeURIComponent(cid)}`,
    { method: 'POST', body: JSON.stringify({}) },
  )
}

export async function uploadKey(slug, episode, shot, kid, file) {
  const form = new FormData()
  form.append('file', file)
  const resp = await fetch(
    `/api/drama/projects/${encodeURIComponent(slug)}/episodes/${episode}/shots/${shot}/keys/${encodeURIComponent(kid)}/upload`,
    { method: 'POST', body: form },
  )
  const text = await resp.text()
  let data = {}
  try {
    data = text ? JSON.parse(text) : {}
  } catch {
    data = { detail: text || `HTTP ${resp.status}` }
  }
  if (!resp.ok) {
    const detail = data.detail || data.error || text || `HTTP ${resp.status}`
    throw new Error(typeof detail === 'string' ? detail : JSON.stringify(detail))
  }
  return data
}

export function lockKey(slug, episode, shot, kid, locked = true) {
  return request(
    `/api/drama/projects/${encodeURIComponent(slug)}/episodes/${episode}/shots/${shot}/keys/${encodeURIComponent(kid)}/lock`,
    { method: 'POST', body: JSON.stringify({ locked }) },
  )
}

export function suggestCoverage(slug, episode) {
  return request(
    `/api/drama/projects/${encodeURIComponent(slug)}/episodes/${episode}/coverage`,
    { method: 'POST', body: JSON.stringify({}) },
  )
}

export function applyCoverage(slug, episode, sid) {
  return request(
    `/api/drama/projects/${encodeURIComponent(slug)}/episodes/${episode}/coverage/${encodeURIComponent(sid)}/apply`,
    { method: 'POST', body: JSON.stringify({}) },
  )
}

export function dismissCoverage(slug, episode, sid) {
  return request(
    `/api/drama/projects/${encodeURIComponent(slug)}/episodes/${episode}/coverage/${encodeURIComponent(sid)}/dismiss`,
    { method: 'POST', body: JSON.stringify({}) },
  )
}

export function lockCoverage(slug, episode, sid) {
  return request(
    `/api/drama/projects/${encodeURIComponent(slug)}/episodes/${episode}/coverage/${encodeURIComponent(sid)}/lock`,
    { method: 'POST', body: JSON.stringify({}) },
  )
}

export function listSnapshots(slug, episode) {
  return request(`/api/drama/projects/${encodeURIComponent(slug)}/episodes/${episode}/snapshots`)
}

export function restoreSnapshot(slug, episode, sid) {
  return request(
    `/api/drama/projects/${encodeURIComponent(slug)}/episodes/${episode}/snapshots/restore/${encodeURIComponent(sid)}`,
    { method: 'POST', body: JSON.stringify({}) },
  )
}

export function deleteSnapshot(slug, episode, sid) {
  return request(
    `/api/drama/projects/${encodeURIComponent(slug)}/episodes/${episode}/snapshots/${encodeURIComponent(sid)}`,
    { method: 'DELETE' },
  )
}

export function classifyShots(slug, episode, force = false) {
  return request(
    `/api/drama/projects/${encodeURIComponent(slug)}/episodes/${episode}/classify`,
    { method: 'POST', body: JSON.stringify({ force }) },
  )
}

export function getModels(slug) {
  return request(`/api/drama/projects/${encodeURIComponent(slug)}/models`)
}

export function patchModels(slug, body) {
  return request(`/api/drama/projects/${encodeURIComponent(slug)}/models`, {
    method: 'PATCH',
    body: JSON.stringify(body),
  })
}

export function applyStyle(slug, episode, styleId = '') {
  return request(
    `/api/drama/projects/${encodeURIComponent(slug)}/episodes/${episode}/style`,
    { method: 'POST', body: JSON.stringify({ style_id: styleId || '' }) },
  )
}
