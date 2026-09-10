/**
 * Cast / prop / scene reference canvas presets (mirrors backend drama_characters).
 * ref_size stores the preset key; canvas WxH comes from the map.
 */

export const FACE_REF_SIZE = 1024

export const REF_SIZE_PRESETS = {
  character: {
    1024: [1024, 1024],
    1536: [1536, 1536],
    2048: [2048, 2048],
  },
  prop: {
    1024: [1024, 1024],
    1080: [1080, 1920],
  },
  scene: {
    1440: [1440, 2560],
    1080: [1080, 1920],
    1600: [1600, 2848],
  },
}

export const DEFAULT_REF_SIZE_BY_CATEGORY = {
  character: 1024,
  prop: 1024,
  scene: 1440,
}

const LEGACY_REF_SIZES = new Set([640, 1980])

export function normalizeCategory(raw) {
  const c = String(raw || 'character').trim().toLowerCase()
  if (c === 'prop' || c === 'scene') return c
  return 'character'
}

export function defaultRefSizeFor(category) {
  const cat = normalizeCategory(category)
  return DEFAULT_REF_SIZE_BY_CATEGORY[cat] || 1024
}

export function normalizeRefSize(raw, category = 'character') {
  const cat = normalizeCategory(category)
  const presets = REF_SIZE_PRESETS[cat] || REF_SIZE_PRESETS.character
  const fallback = defaultRefSizeFor(cat)
  const n = Number(raw)
  if (!Number.isFinite(n)) return fallback
  if (presets[n]) return n
  if (LEGACY_REF_SIZES.has(n)) return fallback
  return fallback
}

export function refCanvasSize(category, sizeKey) {
  const cat = normalizeCategory(category)
  const key = normalizeRefSize(sizeKey, cat)
  const presets = REF_SIZE_PRESETS[cat] || REF_SIZE_PRESETS.character
  return presets[key] || presets[defaultRefSizeFor(cat)]
}

export function castRefSizeOptions(category) {
  const cat = normalizeCategory(category)
  const presets = REF_SIZE_PRESETS[cat] || REF_SIZE_PRESETS.character
  return Object.keys(presets)
    .map((k) => Number(k))
    .sort((a, b) => a - b)
    .map((value) => {
      const [w, h] = presets[value]
      return { value, hint: `${w}×${h}` }
    })
}
