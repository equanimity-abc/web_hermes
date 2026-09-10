<script setup>
import { computed } from 'vue'
import DramaScriptOutline from '@/components/drama/DramaScriptOutline.vue'
import { parseDramaScript } from '@/utils/parseDramaScript'

const props = defineProps({
  fileKey: { type: String, default: '' },
  content: { type: String, default: '' },
  path: { type: String, default: '' },
})

function safeJson(text) {
  try {
    return JSON.parse(String(text || '') || 'null')
  } catch {
    return null
  }
}

const parsedScript = computed(() =>
  props.fileKey === 'script' ? parseDramaScript(props.content) : null,
)

const shotsSummary = computed(() => {
  if (props.fileKey !== 'shots') return null
  const data = safeJson(props.content)
  if (!data || !Array.isArray(data.shots)) return { error: '无法解析 shots.json', shots: [] }
  return {
    title: data.title || '',
    count: data.shots.length,
    shots: data.shots.map((s) => ({
      n: s.n,
      timing: s.timing || `${s.start ?? '?'}-${s.end ?? '?'}s`,
      画面: s.画面 || '',
      地点: s.地点 || '',
      角色: Array.isArray(s.角色) ? s.角色.join('、') : s.角色 || '',
      字幕: s.字幕 || '',
      status: s.status || '',
      locked: Array.isArray(s.locked) ? s.locked.join(',') : '',
    })),
  }
})

const charactersSummary = computed(() => {
  if (props.fileKey !== 'characters') return null
  const data = safeJson(props.content)
  const list = Array.isArray(data?.characters) ? data.characters : Array.isArray(data) ? data : null
  if (!list) return { error: '无法解析 characters.json', items: [] }
  const catLabel = { character: '角色', scene: '场景', prop: '道具' }
  return {
    items: list.map((c) => ({
      id: c.id,
      name: c.name || c.id,
      category: catLabel[c.category || 'character'] || c.category || '角色',
      look: c.look || '',
      voice: c.voice || '',
      ref_locked: Boolean(c.ref_locked),
    })),
  }
})

const projectSummary = computed(() => {
  if (props.fileKey !== 'project') return null
  const data = safeJson(props.content)
  if (!data || typeof data !== 'object') return { error: '无法解析 project.json' }
  const series = data.series && typeof data.series === 'object' ? data.series : {}
  const episodes = Array.isArray(data.episodes) ? data.episodes : []
  return {
    slug: data.slug || '',
    title: data.title || '',
    logline: data.logline || '',
    aspect: data.aspect || '',
    episode_count: series.episode_count || episodes.length || '',
    seconds_per_episode: series.seconds_per_episode || '',
    episodes: episodes.map((e) => ({
      n: e.n,
      title: e.title || '',
      seconds: e.seconds || '',
      path: e.path || '',
    })),
  }
})

const mixSummary = computed(() => {
  if (props.fileKey !== 'mix') return null
  const data = safeJson(props.content)
  if (!data || typeof data !== 'object') return { error: '无法解析 mix.json' }
  const bgm = data.bgm && typeof data.bgm === 'object' ? data.bgm : {}
  return {
    bgm_intent: data.bgm_intent || '',
    volume: data.volume,
    duck_db: data.duck_db,
    fade_in: data.fade_in,
    fade_out: data.fade_out,
    bgm_title: bgm.title || bgm.id || '',
    bgm_path: bgm.path || data.path || '',
    license: data.license || bgm.license || '',
    catalog_id: data.catalog_id || bgm.catalog_id || '',
    sfx_count: Array.isArray(data.sfx) ? data.sfx.length : 0,
  }
})

const markdownHeadings = computed(() => {
  if (props.fileKey !== 'bible' && props.fileKey !== 'outline') return null
  const text = String(props.content || '')
  if (!text.trim()) return { empty: true, headings: [], preview: '' }
  const headings = []
  for (const line of text.split('\n')) {
    const m = line.match(/^(#{1,3})\s+(.+)$/)
    if (m) headings.push({ level: m[1].length, text: m[2].trim() })
  }
  return {
    empty: false,
    headings: headings.slice(0, 40),
    preview: text.trim().slice(0, 800),
    chars: text.length,
  }
})
</script>

<template>
  <div class="drama-script-summary">
    <!-- epNN.md -->
    <DramaScriptOutline v-if="fileKey === 'script'" :parsed="parsedScript" />

    <!-- shots.json -->
    <div v-else-if="fileKey === 'shots'" class="drama-script-summary-block">
      <p v-if="shotsSummary?.error" class="drama-script-outline-empty">{{ shotsSummary.error }}</p>
      <template v-else>
        <h4 class="drama-script-outline-h">
          分镜摘要
          <span class="drama-script-outline-count">{{ shotsSummary.count }}</span>
        </h4>
        <p v-if="shotsSummary.title" class="drama-script-summary-line">标题：{{ shotsSummary.title }}</p>
        <article v-for="s in shotsSummary.shots" :key="s.n" class="drama-script-shot-card">
          <h5 class="drama-script-shot-head">
            Shot {{ s.n }}
            <span v-if="s.timing" class="drama-script-shot-timing">{{ s.timing }}</span>
            <span v-if="s.status" class="drama-script-shot-timing">· {{ s.status }}</span>
          </h5>
          <dl class="drama-script-asset-fields">
            <div v-if="s.画面" class="drama-script-asset-field"><dt>画面</dt><dd>{{ s.画面 }}</dd></div>
            <div v-if="s.地点" class="drama-script-asset-field"><dt>地点</dt><dd>{{ s.地点 }}</dd></div>
            <div v-if="s.角色" class="drama-script-asset-field"><dt>角色</dt><dd>{{ s.角色 }}</dd></div>
            <div v-if="s.字幕" class="drama-script-asset-field"><dt>字幕</dt><dd>{{ s.字幕 }}</dd></div>
            <div v-if="s.locked" class="drama-script-asset-field"><dt>锁定</dt><dd>{{ s.locked }}</dd></div>
          </dl>
        </article>
        <p v-if="!shotsSummary.shots.length" class="drama-script-outline-empty">暂无分镜</p>
      </template>
    </div>

    <!-- characters.json -->
    <div v-else-if="fileKey === 'characters'" class="drama-script-summary-block">
      <p v-if="charactersSummary?.error" class="drama-script-outline-empty">{{ charactersSummary.error }}</p>
      <template v-else>
        <h4 class="drama-script-outline-h">
          资产摘要
          <span class="drama-script-outline-count">{{ charactersSummary.items.length }}</span>
        </h4>
        <article v-for="c in charactersSummary.items" :key="c.id || c.name" class="drama-script-asset-card">
          <h5 class="drama-script-asset-name">{{ c.name }} · {{ c.category }}</h5>
          <dl class="drama-script-asset-fields">
            <div v-if="c.look" class="drama-script-asset-field"><dt>设定</dt><dd>{{ c.look }}</dd></div>
            <div v-if="c.voice" class="drama-script-asset-field"><dt>音色</dt><dd>{{ c.voice }}</dd></div>
            <div class="drama-script-asset-field"><dt>定妆锁</dt><dd>{{ c.ref_locked ? '已锁' : '未锁' }}</dd></div>
          </dl>
        </article>
        <p v-if="!charactersSummary.items.length" class="drama-script-outline-empty">暂无角色/场景/道具卡</p>
      </template>
    </div>

    <!-- project.json -->
    <div v-else-if="fileKey === 'project'" class="drama-script-summary-block">
      <p v-if="projectSummary?.error" class="drama-script-outline-empty">{{ projectSummary.error }}</p>
      <template v-else>
        <h4 class="drama-script-outline-h">项目摘要</h4>
        <dl class="drama-script-asset-fields drama-script-summary-dl">
          <div class="drama-script-asset-field"><dt>标题</dt><dd>{{ projectSummary.title || '—' }}</dd></div>
          <div class="drama-script-asset-field"><dt>slug</dt><dd>{{ projectSummary.slug || '—' }}</dd></div>
          <div class="drama-script-asset-field"><dt>梗概</dt><dd>{{ projectSummary.logline || '—' }}</dd></div>
          <div class="drama-script-asset-field"><dt>画幅</dt><dd>{{ projectSummary.aspect || '—' }}</dd></div>
          <div class="drama-script-asset-field"><dt>集数</dt><dd>{{ projectSummary.episode_count || '—' }}</dd></div>
          <div class="drama-script-asset-field"><dt>单集秒</dt><dd>{{ projectSummary.seconds_per_episode || '—' }}</dd></div>
        </dl>
        <h4 class="drama-script-outline-h">分集</h4>
        <article v-for="e in projectSummary.episodes" :key="e.n" class="drama-script-asset-card">
          <h5 class="drama-script-asset-name">EP{{ String(e.n).padStart(2, '0') }} · {{ e.title || '未命名' }}</h5>
          <dl class="drama-script-asset-fields">
            <div class="drama-script-asset-field"><dt>时长</dt><dd>{{ e.seconds || '—' }}s</dd></div>
            <div v-if="e.path" class="drama-script-asset-field"><dt>路径</dt><dd>{{ e.path }}</dd></div>
          </dl>
        </article>
      </template>
    </div>

    <!-- mix.json -->
    <div v-else-if="fileKey === 'mix'" class="drama-script-summary-block">
      <p v-if="mixSummary?.error" class="drama-script-outline-empty">{{ mixSummary.error }}</p>
      <template v-else>
        <h4 class="drama-script-outline-h">配乐摘要</h4>
        <dl class="drama-script-asset-fields drama-script-summary-dl">
          <div class="drama-script-asset-field"><dt>意图</dt><dd>{{ mixSummary.bgm_intent || '—' }}</dd></div>
          <div class="drama-script-asset-field"><dt>曲目</dt><dd>{{ mixSummary.bgm_title || '—' }}</dd></div>
          <div class="drama-script-asset-field"><dt>路径</dt><dd>{{ mixSummary.bgm_path || '—' }}</dd></div>
          <div class="drama-script-asset-field"><dt>音量</dt><dd>{{ mixSummary.volume ?? '—' }}</dd></div>
          <div class="drama-script-asset-field"><dt>闪避</dt><dd>{{ mixSummary.duck_db ?? '—' }} dB</dd></div>
          <div class="drama-script-asset-field"><dt>淡入/出</dt><dd>{{ mixSummary.fade_in ?? '—' }} / {{ mixSummary.fade_out ?? '—' }}</dd></div>
          <div class="drama-script-asset-field"><dt>版权</dt><dd>{{ mixSummary.license || '—' }}</dd></div>
          <div class="drama-script-asset-field"><dt>音效数</dt><dd>{{ mixSummary.sfx_count }}</dd></div>
        </dl>
      </template>
    </div>

    <!-- bible / outline -->
    <div v-else-if="fileKey === 'bible' || fileKey === 'outline'" class="drama-script-summary-block">
      <p v-if="markdownHeadings?.empty" class="drama-script-outline-empty">文件为空</p>
      <template v-else>
        <h4 class="drama-script-outline-h">
          {{ fileKey === 'bible' ? '圣经要点' : '大纲要点' }}
          <span class="drama-script-outline-count">{{ markdownHeadings.chars }} 字</span>
        </h4>
        <ul v-if="markdownHeadings.headings.length" class="drama-script-summary-toc">
          <li
            v-for="(h, i) in markdownHeadings.headings"
            :key="i"
            :style="{ paddingLeft: `${(h.level - 1) * 12}px` }"
          >
            {{ h.text }}
          </li>
        </ul>
        <pre class="drama-script-summary-preview">{{ markdownHeadings.preview }}{{ markdownHeadings.chars > 800 ? '…' : '' }}</pre>
      </template>
    </div>

    <p v-else class="drama-script-outline-empty">该文件暂无关键信息视图</p>
  </div>
</template>
