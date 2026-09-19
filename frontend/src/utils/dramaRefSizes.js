/**
 * Cast / prop / scene reference canvas presets (mirrors backend drama_characters).
 * Ark：角色默认竖屏全身 1440×2560；大头照固定 1024²。
 * Seedream 5.0 lite: total pixels ≥ 3_686_400.
 * ref_size stores the preset key; canvas WxH comes from the map.
 */

export const FACE_REF_SIZE = 1024

export const REF_SIZE_PRESETS = {
  character: {
    1440: [1440, 2560], // 9:16 正面全身（竖屏短剧默认）
    2048: [2048, 2048],
    1536: [1536, 1536],
    1024: [1024, 1024],
  },
  prop: {
    2048: [2048, 2048],
    1440: [1440, 2560],
  },
  scene: {
    1440: [1440, 2560],
    1600: [1600, 2848],
  },
}

export const DEFAULT_REF_SIZE_BY_CATEGORY = {
  character: 1440,
  prop: 2048,
  scene: 1440,
}

export function normalizeCategory(raw) {
  const c = String(raw || 'character').trim().toLowerCase()
  if (c === 'prop' || c === 'scene') return c
  return 'character'
}

export function defaultRefSizeFor(category) {
  const cat = normalizeCategory(category)
  return DEFAULT_REF_SIZE_BY_CATEGORY[cat] || 1440
}

export function normalizeRefSize(raw, category = 'character') {
  const cat = normalizeCategory(category)
  const presets = REF_SIZE_PRESETS[cat] || REF_SIZE_PRESETS.character
  let fallback = defaultRefSizeFor(cat)
  if (!presets[fallback]) {
    fallback = Number(Object.keys(presets)[0]) || 1440
  }
  const n = Number(raw)
  if (!Number.isFinite(n)) return fallback
  if (presets[n]) return n
  return fallback
}

export function refCanvasSize(category, sizeKey) {
  const cat = normalizeCategory(category)
  const key = normalizeRefSize(sizeKey, cat)
  const presets = REF_SIZE_PRESETS[cat] || REF_SIZE_PRESETS.character
  return presets[key] || presets[defaultRefSizeFor(cat)] || [1440, 2560]
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
