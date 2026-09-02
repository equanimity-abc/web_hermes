/**
 * API key settings (masked status + partial update).
 */

export async function fetchApiKeys() {
  const resp = await fetch('/api/settings/keys')
  if (!resp.ok) {
    throw new Error(`加载密钥设置失败: HTTP ${resp.status}`)
  }
  return resp.json()
}

/**
 * @param {Record<string, string>} patch keys to set; empty string clears secrets.json entry
 */
export async function saveApiKeys(patch) {
  const resp = await fetch('/api/settings/keys', {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(patch),
  })
  if (!resp.ok) {
    const text = await resp.text().catch(() => '')
    throw new Error(text || `保存密钥失败: HTTP ${resp.status}`)
  }
  return resp.json()
}
