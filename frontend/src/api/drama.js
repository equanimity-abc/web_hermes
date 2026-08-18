/**
 * Drama workbench REST (does not go through the agent loop).
 */

async function request(path, options = {}) {
  const resp = await fetch(path, {
    headers: { 'Content-Type': 'application/json', ...(options.headers || {}) },
    ...options,
  })
  const data = await resp.json().catch(() => ({}))
  if (!resp.ok) {
    const detail = data.detail || data.error || `HTTP ${resp.status}`
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

export function rerenderShot(slug, episode, shot, layers) {
  return request(
    `/api/drama/projects/${encodeURIComponent(slug)}/episodes/${episode}/shots/${shot}/rerender`,
    { method: 'POST', body: JSON.stringify(layers ? { layers } : {}) },
  )
}
