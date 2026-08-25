<script setup>
import { computed, ref } from 'vue'

const props = defineProps({
  project: { type: Object, default: null },
  episode: { type: Object, default: null },
  episodeN: { type: [Number, null], default: null },
  episodes: { type: Array, default: () => [] },
  shots: { type: Array, default: () => [] },
  selectedN: { type: [Number, null], default: null },
  selected: { type: Object, default: null },
  draft: { type: Object, required: true },
  dirty: { type: Boolean, default: false },
  saving: { type: Boolean, default: false },
  rendering: { type: Boolean, default: false },
  error: { type: String, default: '' },
  notice: { type: String, default: '' },
  bust: { type: Number, default: 0 },
  scriptDraft: { type: String, default: '' },
  scriptImpact: { type: Object, default: null },
  boardMode: { type: String, default: 'shots' },
  characters: { type: Array, default: () => [] },
  voices: { type: Array, default: () => [] },
  selectedCharacterId: { type: [String, null], default: null },
  selectedCharacter: { type: Object, default: null },
  charDraft: { type: Object, required: true },
  timelineOrder: { type: Array, default: () => [] },
  tlDraft: { type: Object, required: true },
  timelineItems: { type: Array, default: () => [] },
  orderedShots: { type: Array, default: () => [] },
  transitions: { type: Array, default: () => [] },
  i2vModes: { type: Array, default: () => ['off', 'auto', 'on'] },
  shotKinds: { type: Array, default: () => [] },
  shotSizes: { type: Array, default: () => [] },
  timelineDirty: { type: Boolean, default: false },
  orderDirty: { type: Boolean, default: false },
  mixDraft: { type: Object, required: true },
  mixDirty: { type: Boolean, default: false },
  mixUnlicensed: { type: Boolean, default: false },
  presets: { type: Array, default: () => [] },
  currentPreset: { type: String, default: 'balanced' },
  degradedProviders: { type: Array, default: () => [] },
  configNodeList: { type: Array, default: () => [] },
  selectedConfigNode: { type: String, default: 'script' },
  configNodeDraft: { type: String, default: '' },
  selectedShotIds: { type: Array, default: () => [] },
  snapshots: { type: Array, default: () => [] },
  snapshotsOpen: { type: Boolean, default: false },
  budget: { type: Object, default: null },
  budgetBlocked: { type: Boolean, default: false },
  budgetWarn: { type: Boolean, default: false },
  budgetDraft: { type: Object, required: true },
  budgetOpen: { type: Boolean, default: false },
  qcChecklist: { type: Object, default: null },
  checklistOpen: { type: Boolean, default: false },
  rejectingAll: { type: Boolean, default: false },
})

const emit = defineEmits([
  'open-episode',
  'select-shot',
  'save',
  'rerender',
  'rerender-layer',
  'toggle-lock',
  'update:scriptDraft',
  'update:boardMode',
  'preview-script',
  'save-script',
  'generate-script',
  'rerender-dirty',
  'select-character',
  'add-character',
  'save-character',
  'lock-ref',
  'upload-ref',
  'delete-character',
  'generate-character-ref',
  'generate-all-refs',
  'toggle-role',
  'generate-candidates',
  'choose-candidate',
  'upload-scene',
  'generate-i2v',
  'generate-all-video',
  'generate-lip',
  'generate-all-voice',
  'generate-keys',
  'choose-key',
  'upload-key',
  'lock-key',
  'qc-shot',
  'qc-episode',
  'pass-episode-qc',
  'pass-shot-qc',
  'reject-shot-qc',
  'remix-loudness',
  'suggest-coverage',
  'apply-coverage',
  'dismiss-coverage',
  'lock-coverage',
  'classify-shots',
  'apply-style',
  'save-timeline-shot',
  'save-timeline-all',
  'save-timeline-order',
  'move-timeline-shot',
  'reorder-timeline',
  'export-timeline',
  'save-mix',
  'upload-bgm',
  'apply-mix',
  'clear-bgm',
  'apply-preset',
  'select-config-node',
  'save-config-node',
  'toggle-shot-selected',
  'clear-shot-selection',
  'select-all-shots',
  'apply-batch-edit',
  'toggle-snapshots',
  'restore-snapshot',
  'delete-snapshot',
  'toggle-budget',
  'save-budget',
  'toggle-checklist',
  'refresh-checklist',
  'reject-all-qc',
])

const stage = ref('script')
const premise = ref('')
const refInput = ref(null)
const sceneInput = ref(null)
const keyInput = ref(null)
const bgmInput = ref(null)
const selectedKeyId = ref(null)

const hasLayer = (layer) => (props.shots || []).some((s) => s.files?.[layer]?.exists)

const stageList = computed(() => [
  { id: 'script', label: '剧本', done: Boolean(props.episode?.script) },
  { id: 'cast', label: '角色', done: (props.characters || []).length > 0 },
  { id: 'scene', label: '画面', done: hasLayer('scene') },
  { id: 'video', label: '视频', done: hasLayer('motion') || (props.shots || []).some((s) => ['ai', 'keys', 'fallback'].includes(s.i2v_source)) },
  { id: 'voice', label: '声音', done: hasLayer('voice') },
  { id: 'assemble', label: '成片', done: Boolean(props.episode?.play_url) },
])

const stageBoardMap = {
  script: 'script',
  cast: 'cast',
  scene: 'shots',
  video: 'shots',
  voice: 'shots',
  assemble: 'timeline',
}
const stageIndex = computed(() => stageList.value.findIndex((s) => s.id === stage.value))
const currentStage = computed(() => stageList.value[stageIndex.value] || stageList.value[0])
const nextStage = computed(() => stageList.value[stageIndex.value + 1] || null)

function goStage(id) {
  stage.value = id
  emit('update:boardMode', stageBoardMap[id] || 'shots')
}
function goNext() {
  if (nextStage.value) goStage(nextStage.value.id)
}

const previewUrl = computed(() => {
  const shot = props.selected
  const url = shot?.files?.clip?.url || shot?.files?.scene?.url || shot?.preview_url || ''
  if (!url) return ''
  return `${url}${url.includes('?') ? '&' : '?'}_=${props.bust || 0}`
})
const episodePreviewUrl = computed(() => {
  const url = props.episode?.play_url || ''
  if (!url) return ''
  return `${url}${url.includes('?') ? '&' : '?'}_=${props.bust || 0}`
})
const previewKind = computed(() => {
  const url = previewUrl.value
  if (!url) return 'empty'
  return url.includes('.mp4') ? 'video' : 'image'
})
const refPreviewUrl = computed(() => {
  const url = props.selectedCharacter?.ref_url || ''
  if (!url) return ''
  return `${url}${url.includes('?') ? '&' : '?'}_=${props.bust || 0}`
})
const mix = computed(() => props.episode?.mix || null)
const bgmPreviewUrl = computed(() => {
  const url = mix.value?.file?.url || ''
  if (!url) return ''
  return `${url}${url.includes('?') ? '&' : '?'}_=${props.bust || 0}`
})
const catalogTracks = computed(() => mix.value?.catalog || [])

function candUrl(cand) {
  const url = cand?.url || ''
  if (!url) return ''
  return `${url}${url.includes('?') ? '&' : '?'}_=${props.bust || 0}`
}
function shotThumb(shot) {
  return shot?.files?.scene?.url || shot?.preview_url || ''
}
function shotStatusLabel(shot) {
  const locked = shot.locked || []
  if (locked.includes('shot')) return '锁'
  if ((shot.dirty || []).length) return '脏'
  if (shot.files?.clip?.exists) return '成'
  if (shot.files?.scene?.exists) return '图'
  return '待'
}
function shotStatusClass(shot) {
  const locked = shot.locked || []
  if (locked.includes('shot')) return 'is-locked'
  if ((shot.dirty || []).length) return 'is-dirty'
  if (shot.files?.clip?.exists) return 'is-done'
  if (shot.files?.scene?.exists) return 'is-scene'
  return 'is-todo'
}
function isLocked(layer) {
  return (props.selected?.locked || []).includes(layer)
}
const shotFrozen = computed(() => isLocked('shot'))
const canGenerateI2v = computed(() => {
  const shot = props.selected
  if (!shot) return false
  if ((shot.route && shot.route.will_run === false) || shot.route?.ladder === 'L0') return false
  const mode = props.draft?.i2v || shot.i2v || 'auto'
  if (mode === 'off') return false
  if (mode === 'on') return true
  return (shot.locked || []).includes('scene') || shotFrozen.value
})
const canGenerateLip = computed(() => Boolean(props.selected?.lip?.ok || props.selected?.lip?.will_run))
const canGenerateKeys = computed(() => Boolean(props.selected?.keys_gate?.ok || props.selected?.keys_gate?.will_run))
const selectedKey = computed(() => {
  const keys = props.selected?.keys || []
  return keys.find((k) => k.id === selectedKeyId.value) || keys[0] || null
})
const identityLabel = computed(() => {
  const id = props.selected?.identity
  if (!id) return props.selected?.identity_hint || '尚未抽检身份'
  if (id.status === 'skipped') return id.hint || '身份未出分'
  const score = id.cosine == null ? '—' : Number(id.cosine).toFixed(2)
  return id.pass ? `身份 ${score} 通过` : `身份 ${score} 未通过`
})
const identityClass = computed(() => {
  const id = props.selected?.identity
  if (!id) return ''
  if (id.status === 'skipped') return 'drama-qc-skip'
  if (id.status === 'ok' && id.pass) return 'drama-qc-pass'
  return 'drama-qc-fail'
})
const i2vSourceLabel = computed(() => {
  const src = props.selected?.i2v_source || ''
  if (src === 'ai') return '已生成 I2V 运动'
  if (src === 'keys') return '已用关键帧补间'
  if (src === 'fallback') return '已回退静图运镜'
  return '尚未生成视频'
})

function onRefFile(ev) {
  const file = ev.target.files?.[0]
  ev.target.value = ''
  if (file) emit('upload-ref', file)
}
function onSceneFile(ev) {
  const file = ev.target.files?.[0]
  ev.target.value = ''
  if (file) emit('upload-scene', file)
}
function onBgmFile(ev) {
  const file = ev.target.files?.[0]
  ev.target.value = ''
  if (file) emit('upload-bgm', file, Boolean(props.mixDraft.license_ok))
}
function onKeyFile(ev) {
  const file = ev.target.files?.[0]
  ev.target.value = ''
  const kid = selectedKey.value?.id
  if (file && kid) emit('upload-key', kid, file)
}
function onGenerateScript() {
  emit('generate-script', premise.value)
}
</script>

<template>
  <main class="drama-studio">
    <header class="drama-top">
      <div class="drama-top-head">
        <div class="drama-top-title">
          <h1>{{ project?.project?.title || '漫剧工作台' }}</h1>
          <p v-if="project?.project?.logline" class="drama-logline">{{ project.project.logline }}</p>
        </div>
        <div class="drama-eps">
          <button
            v-for="ep in episodes"
            :key="ep.n"
            type="button"
            class="drama-ep-btn"
            :class="{ active: ep.n === episodeN }"
            @click="emit('open-episode', ep.n)"
          >
            EP{{ String(ep.n).padStart(2, '0') }}
            <span class="drama-ep-meta">{{ ep.shot_count || 0 }} 镜</span>
          </button>
        </div>
      </div>
    </header>

    <!-- 6 阶段线性步进器 -->
    <div v-if="project" class="drama-stepper">
      <button
        v-for="(st, idx) in stageList"
        :key="st.id"
        type="button"
        class="drama-step"
        :class="{ active: st.id === stage, done: st.done, passed: idx < stageIndex }"
        @click="goStage(st.id)"
      >
        <span class="drama-step-idx">{{ st.done ? '✓' : idx + 1 }}</span>
        <span class="drama-step-label">{{ st.label }}</span>
      </button>
    </div>

    <p v-if="error" class="drama-banner drama-banner--err">{{ error }}</p>
    <p v-else-if="notice" class="drama-banner">{{ notice }}</p>

    <div v-if="project" class="drama-flow">
      <!-- ============ 阶段 1：剧本 ============ -->
      <section v-if="stage === 'script'" class="drama-stage-panel">
        <div class="drama-panel-head">
          <h2>① 剧本 —— 一句话生成完整剧本与分镜</h2>
        </div>
        <div class="drama-panel-body">
          <label class="drama-field">
            故事梗概
            <textarea
              v-model="premise"
              rows="2"
              placeholder="例如：齐天大圣大闹天宫后被压五指山，五百年后遇到唐僧……"
            />
          </label>
          <div class="drama-actions">
            <button type="button" class="btn-primary" :disabled="saving || rendering || !premise.trim()" @click="onGenerateScript">
              {{ saving ? '生成中…' : '生成剧本' }}
            </button>
          </div>
          <label class="drama-field">
            剧本（生成后可手动微调）
            <textarea
              :value="scriptDraft"
              spellcheck="false"
              rows="16"
              placeholder="# EP01 标题&#10;- 时长: 45s&#10;## 分镜&#10;### Shot 1 (0-3s)"
              @input="emit('update:scriptDraft', $event.target.value)"
            />
          </label>
          <p v-if="scriptImpact?.summary" class="drama-impact-summary">{{ scriptImpact.summary }}</p>
          <div class="drama-actions">
            <button type="button" class="btn-ghost" :disabled="saving || rendering || !scriptDraft.trim()" @click="emit('save-script')">
              {{ saving ? '保存中…' : '保存剧本' }}
            </button>
          </div>
        </div>
      </section>

      <!-- ============ 阶段 2：角色 ============ -->
      <section v-else-if="stage === 'cast'" class="drama-stage-panel">
        <div class="drama-panel-head">
          <h2>② 角色 —— 文生图生成定妆图</h2>
        </div>
        <div class="drama-panel-body">
          <div class="drama-actions">
            <button type="button" class="btn-primary" :disabled="saving || rendering" @click="emit('generate-all-refs')">
              {{ rendering ? '生成中…' : '一键生成所有定妆图' }}
            </button>
            <button type="button" class="btn-ghost" :disabled="saving" @click="emit('add-character')">添加角色</button>
          </div>
          <div class="drama-cast-grid">
            <article v-for="char in characters" :key="char.id" class="drama-cast-card" :class="{ active: char.id === selectedCharacterId }" @click="emit('select-character', char.id)">
              <div class="drama-cast-thumb">
                <img v-if="char.ref_url" :src="char.ref_url" :alt="char.name" />
                <span v-else class="drama-candidate-empty">无图</span>
              </div>
              <strong>{{ char.name || char.id }}</strong>
              <em>{{ char.look || '（未写外形，生成前请先填写）' }}</em>
              <div class="drama-cast-actions">
                <button type="button" class="btn-tiny" :disabled="saving || rendering" @click.stop="emit('generate-character-ref', char.id)">生成</button>
                <button type="button" class="btn-tiny" :disabled="saving || !char.ref_exists" @click.stop="emit('lock-ref')">
                  {{ char.ref_locked ? '解锁' : '锁定' }}
                </button>
              </div>
            </article>
            <p v-if="!characters.length" class="drama-empty-hint">还没有角色。先添加角色并填外形，再生成定妆图。</p>
          </div>
          <template v-if="selectedCharacter">
            <div class="drama-cast-editor">
              <label class="drama-field">名字 <input v-model="charDraft.name" type="text" /></label>
              <label class="drama-field">外形 <textarea v-model="charDraft.look" rows="2" placeholder="金箍、火眼金睛、虎皮裙…" /></label>
              <label class="drama-field">配色 <input v-model="charDraft.colors" type="text" placeholder="金、赤、青绿" /></label>
              <label class="drama-field">别名（对白匹配）<input v-model="charDraft.aliases" type="text" placeholder="悟空、齐天大圣" /></label>
              <div class="drama-actions">
                <button type="button" class="btn-primary" :disabled="saving" @click="emit('save-character')">保存角色卡</button>
                <button type="button" class="btn-ghost" :disabled="saving" @click="refInput?.click()">手传兜底</button>
                <input ref="refInput" class="drama-file" type="file" accept="image/*" @change="onRefFile" />
              </div>
            </div>
          </template>
        </div>
      </section>

      <!-- ============ 阶段 3：画面（可分镜出图） ============ -->
      <section v-else-if="stage === 'scene'" class="drama-stage-panel">
        <div class="drama-panel-head">
          <h2>③ 画面 —— 分镜文生图 + 候选墙锁图</h2>
        </div>
        <div class="drama-panel-body">
          <div class="drama-actions">
            <button type="button" class="btn-primary" :disabled="rendering" @click="emit('generate-all-scenes')">
              {{ rendering ? '出图中…' : '一键全部出图' }}
            </button>
          </div>
          <div class="drama-shot-grid">
            <button v-for="shot in shots" :key="shot.n" type="button" class="drama-shot-card" :class="{ active: shot.n === selectedN }" @click="emit('select-shot', shot.n)">
              <img v-if="shotThumb(shot)" :src="shotThumb(shot)" :alt="`Shot ${shot.n}`" />
              <span v-else class="drama-candidate-empty">{{ shot.n }}</span>
              <span class="drama-status-dot" :class="shotStatusClass(shot)">{{ shotStatusLabel(shot) }}</span>
            </button>
          </div>
          <div v-if="selected" class="drama-inspector-panel">
            <div class="drama-candidates-head"><h3>候选墙 · Shot {{ selected.n }}</h3></div>
            <div class="drama-actions">
              <button type="button" class="btn-ghost" :disabled="rendering || shotFrozen || isLocked('scene')" @click="emit('generate-candidates')">重抽 4 张</button>
              <button type="button" class="btn-ghost" :disabled="rendering || shotFrozen" @click="sceneInput?.click()">手传覆盖</button>
            </div>
            <input ref="sceneInput" class="drama-file" type="file" accept="image/*" @change="onSceneFile" />
            <div class="drama-candidate-grid">
              <button
                v-for="cand in selected.candidates || []"
                :key="cand.id"
                type="button"
                class="drama-candidate"
                :class="{ chosen: cand.chosen || selected.chosen === cand.id }"
                :disabled="rendering || shotFrozen"
                @click="emit('choose-candidate', cand.id)"
              >
                <img v-if="candUrl(cand)" :src="candUrl(cand)" :alt="cand.id" />
                <span v-else class="drama-candidate-empty">无图</span>
              </button>
            </div>
            <p v-if="!selected.candidates?.length" class="drama-empty-hint">点「重抽 4 张」生成候选，点缩略图锁定画面。</p>
          </div>
        </div>
      </section>

      <!-- ============ 阶段 4：视频 ============ -->
      <section v-else-if="stage === 'video'" class="drama-stage-panel">
        <div class="drama-panel-head">
          <h2>④ 视频 —— 图生视频（I2V 运动）</h2>
        </div>
        <div class="drama-panel-body">
          <div class="drama-actions">
            <button type="button" class="btn-primary" :disabled="rendering" @click="emit('generate-all-video')">
              {{ rendering ? '生成中…' : '一键全部生成视频' }}
            </button>
          </div>
          <div class="drama-shot-list">
            <button v-for="shot in shots" :key="shot.n" type="button" class="drama-row" :class="{ active: shot.n === selectedN }" @click="emit('select-shot', shot.n)">
              <span class="drama-row-n">{{ shot.n }}</span>
              <span class="drama-row-body">{{ shot.画面 || '（无画面描述）' }}</span>
              <span class="drama-row-flag">{{ i2vSourceLabel }}</span>
              <button type="button" class="btn-tiny" :disabled="rendering || !canGenerateI2v" @click.stop="emit('generate-i2v')">生成视频</button>
            </button>
          </div>
          <div v-if="selected" class="drama-inspector-panel">
            <div class="drama-stage">
              <video v-if="previewKind === 'video'" :key="previewUrl" class="drama-media" :src="previewUrl" controls playsinline />
              <img v-else-if="previewKind === 'image'" class="drama-media" :src="previewUrl" alt="镜头画面" />
              <div v-else class="drama-stage-empty">本镜尚未出图或成片</div>
            </div>
          </div>
        </div>
      </section>

      <!-- ============ 阶段 5：声音 ============ -->
      <section v-else-if="stage === 'voice'" class="drama-stage-panel">
        <div class="drama-panel-head">
          <h2>⑤ 声音 —— 配音 + 口型</h2>
        </div>
        <div class="drama-panel-body">
          <div class="drama-actions">
            <button type="button" class="btn-primary" :disabled="rendering" @click="emit('generate-all-voice')">
              {{ rendering ? '生成中…' : '一键生成配音与口型' }}
            </button>
          </div>
          <div class="drama-shot-list">
            <button v-for="shot in shots" :key="shot.n" type="button" class="drama-row" :class="{ active: shot.n === selectedN }" @click="emit('select-shot', shot.n)">
              <span class="drama-row-n">{{ shot.n }}</span>
              <span class="drama-row-body">{{ shot.对白 || shot.字幕 || '（无对白）' }}</span>
              <span class="drama-row-flag">{{ shot.voice ? '配音' : '未配' }}</span>
              <button type="button" class="btn-tiny" :disabled="rendering || !canGenerateLip" @click.stop="emit('generate-lip')">生成口型</button>
            </button>
            <p v-if="!shots.filter((s) => (s.对白 || s.字幕 || '').trim()).length" class="drama-empty-hint">剧本里没有对白镜头，仍需生成。</p>
          </div>
          <p v-if="selected" class="drama-empty-hint" :class="identityClass">{{ identityLabel }}</p>
        </div>
      </section>

      <!-- ============ 阶段 6：成片 ============ -->
      <section v-else-if="stage === 'assemble'" class="drama-stage-panel">
        <div class="drama-panel-head">
          <h2>⑥ 成片 —— 拼接 + BGM + 导出</h2>
        </div>
        <div class="drama-panel-body">
          <div class="drama-actions">
            <button type="button" class="btn-primary" :disabled="rendering || saving || mixUnlicensed" @click="emit('export-timeline')">
              {{ rendering ? '导出中…' : '导出整集' }}
            </button>
          </div>
          <div class="drama-stage">
            <video v-if="episode?.play_url" :key="episodePreviewUrl" class="drama-media" :src="episodePreviewUrl" controls playsinline />
            <div v-else class="drama-stage-empty">导出后在此预览整集 mp4</div>
          </div>
          <div class="drama-freeze">
            <button type="button" class="btn-tiny" :disabled="saving || rendering" @click="bgmInput?.click()">上传 BGM</button>
            <button type="button" class="btn-tiny" :disabled="saving || !mix?.has_bgm" @click="emit('clear-bgm')">清除</button>
            <span>{{ mix?.bgm?.title || '未挂配乐' }}</span>
          </div>
          <input ref="bgmInput" class="drama-file" type="file" accept="audio/*" @change="onBgmFile" />
          <audio v-if="bgmPreviewUrl" class="drama-audio" :src="bgmPreviewUrl" controls />
          <p v-if="mixUnlicensed" class="drama-empty-hint drama-warn">{{ mix?.license?.reason || '无版权曲子禁止导出' }}</p>
        </div>
      </section>

      <!-- 底部：唯一下一步 -->
      <footer class="drama-flow-footer">
        <span>当前：<strong>{{ currentStage.label }}</strong></span>
        <button v-if="nextStage" type="button" class="btn-primary" @click="goNext">下一步：{{ nextStage.label }}</button>
        <button v-else type="button" class="btn-ghost" @click="emit('export-timeline')">重新导出</button>
      </footer>
    </div>

    <div v-else class="drama-idle">
      <h2>分镜台</h2>
      <ol class="drama-idle-steps">
        <li><strong>1. 立项</strong> 在对话里说「帮我立项一个 xxx 漫剧」或点左侧项目</li>
        <li><strong>2. 剧本</strong> 一句话生成完整剧本与分镜</li>
        <li><strong>3. 一路生成</strong> 角色 → 画面 → 视频 → 声音 → 成片</li>
      </ol>
    </div>
  </main>
</template>