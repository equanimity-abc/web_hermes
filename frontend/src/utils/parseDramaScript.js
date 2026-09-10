/**
 * Client-side parse of episode markdown for structured script display.
 */

const SECTION_ALIASES = {
  角色设定: 'cast',
  角色表: 'cast',
  人物设定: 'cast',
  场景设定: 'locations',
  地点设定: 'locations',
  场景表: 'locations',
  道具设定: 'props',
  道具表: 'props',
  物品设定: 'props',
}

const META_RE = /^-\s*\*{0,2}(时长|钩子|悬念|配乐)\*{0,2}\s*[:：]\s*(.*)\s*$/
const SHOT_HEAD_RE = /^###\s*Shot\s+(\d+)\s*(?:\(([^)]*)\))?\s*$/i
const FIELD_RE = /^-\s*\*{0,2}(画面|字幕|旁白|对白|角色|地点|道具)\*{0,2}\s*[:：]\s*(.*)\s*$/
const ASSET_FIELD_RE = /^-\s*\*{0,2}([^\*{：:]+)(?:\*{0,2})\s*[:：]\s*(.*)$/

function parseAssetSections(text) {
  const out = { cast: [], locations: [], props: [] }
  const lines = String(text || '').replace(/\r\n/g, '\n').split('\n')
  let section = null
  let current = null
  let bucket = null

  const flush = () => {
    if (current && bucket && String(current.name || '').trim()) bucket.push(current)
    current = null
  }

  for (const raw of lines) {
    const line = raw.replace(/\s+$/, '')
    const h2 = line.startsWith('## ') && !line.startsWith('### ')
    if (h2) {
      flush()
      const title = line.slice(3).trim()
      if (title.startsWith('分镜')) {
        section = null
        bucket = null
        continue
      }
      const key = SECTION_ALIASES[title]
      section = key || null
      bucket = key ? out[key] : null
      continue
    }
    if (!section || !bucket) continue
    if (line.startsWith('### ')) {
      flush()
      current = { name: line.slice(4).trim() }
      continue
    }
    if (!current) continue
    const m = line.match(ASSET_FIELD_RE)
    if (m) {
      const key = m[1].trim()
      const val = m[2].trim()
      if (key && val) current[key] = val
    }
  }
  flush()
  return out
}

const EMPTY_SCRIPT_PLACEHOLDERS = new Set([
  '无',
  '没有',
  '无。',
  '无旁白',
  '暂无',
  '空',
  'none',
  'n/a',
  'na',
  '-',
  '—',
  '–',
  '/',
  '（无）',
  '(无)',
])

function sanitizeScriptPlaceholder(value) {
  const text = String(value || '').trim()
  if (!text) return ''
  if (EMPTY_SCRIPT_PLACEHOLDERS.has(text) || EMPTY_SCRIPT_PLACEHOLDERS.has(text.toLowerCase())) {
    return ''
  }
  return text
}

function parseTiming(timing) {
  const t = String(timing || '').trim()
  const m = t.match(/([\d.]+)\s*[-–—~～到至]\s*([\d.]+)/)
  if (!m) {
    const one = t.match(/([\d.]+)/)
    const d = one ? Number(one[1]) : 0
    return { start: 0, end: d, duration: d }
  }
  const start = Number(m[1])
  const end = Number(m[2])
  return { start, end, duration: Math.max(0, end - start) }
}

export function parseDramaScript(text) {
  const lines = String(text || '').replace(/\r\n/g, '\n').split('\n')
  let title = ''
  const meta = {}
  const shots = []
  let current = null
  let inShots = false

  for (const raw of lines) {
    const line = raw.replace(/\s+$/, '')
    if (line.startsWith('# ') && !title && !line.startsWith('##')) {
      title = line.slice(2).trim()
      continue
    }
    if (line.startsWith('## ') && line.slice(3).trim().startsWith('分镜')) {
      inShots = true
      continue
    }
    const mMeta = line.match(META_RE)
    if (mMeta && !current && !inShots) {
      meta[mMeta[1]] = mMeta[2].trim()
      continue
    }
    const mShot = line.match(SHOT_HEAD_RE)
    if (mShot) {
      inShots = true
      if (current) shots.push(current)
      const timing = (mShot[2] || '').trim()
      const { start, end, duration } = parseTiming(timing)
      current = {
        n: Number(mShot[1]),
        timing,
        start,
        end,
        duration,
        画面: '',
        地点: '',
        道具: '',
        字幕: '',
        旁白: '',
        角色: '',
      }
      continue
    }
    if (!current) continue
    const mField = line.match(FIELD_RE)
    if (mField) {
      const key = mField[1] === '对白' ? '字幕' : mField[1]
      let val = mField[2].trim()
      if (key === '旁白') val = sanitizeScriptPlaceholder(val)
      current[key] = val
    }
  }
  if (current) shots.push(current)

  const assets = parseAssetSections(text)
  shots.sort((a, b) => Number(a.n) - Number(b.n))
  return {
    title,
    meta,
    cast: assets.cast || [],
    locations: assets.locations || [],
    props: assets.props || [],
    shots,
  }
}

export const SCRIPT_ASSET_FIELDS = {
  cast: ['外形', '性格', '音色倾向', '口头禅', '别名'],
  locations: ['描述', '光影色调', '标志物'],
  props: ['描述', '材质外形', '剧情作用'],
}

export const SCRIPT_SHOT_FIELDS = ['画面', '地点', '道具', '角色', '字幕', '旁白']
export const SCRIPT_META_FIELDS = ['时长', '钩子', '悬念', '配乐']
