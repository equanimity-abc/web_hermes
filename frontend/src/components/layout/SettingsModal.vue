<script setup>
import { computed, reactive, ref, watch } from 'vue'
import { fetchApiKeys, saveApiKeys } from '@/api/settings'

const props = defineProps({
  open: { type: Boolean, default: false },
})

const emit = defineEmits(['close', 'saved'])

const loading = ref(false)
const saving = ref(false)
const error = ref('')
const status = ref(null)
const drafts = reactive({
  DEEPSEEK_API_KEY: '',
  KIMI_API_KEY: '',
  ARK_API_KEY: '',
  DASHSCOPE_API_KEY: '',
})

const hints = {
  DEEPSEEK_API_KEY: '剧本/分镜 · deepseek-v4-pro（与 Kimi 可互相替代）',
  KIMI_API_KEY: '剧本/分镜 · kimi-k3（与 DeepSeek 可互相替代）',
  ARK_API_KEY: '火山方舟 · Seedream 生图 / Seedance 视频 / Seed Audio 配音',
  DASHSCOPE_API_KEY: '阿里云百炼 · 万相出图 / 图生视频 / CosyVoice（可选）',
}

const keys = computed(() => status.value?.keys || [])
const scriptAlts = computed(() => status.value?.script_alternatives || [])
const arkModels = computed(() => status.value?.providers?.ark || null)

async function load() {
  loading.value = true
  error.value = ''
  try {
    status.value = await fetchApiKeys()
    for (const row of status.value.keys || []) {
      drafts[row.key] = ''
    }
  } catch (e) {
    error.value = e.message || String(e)
  } finally {
    loading.value = false
  }
}

watch(
  () => props.open,
  (v) => {
    if (v) load()
  },
)

async function onSave() {
  const patch = {}
  for (const key of Object.keys(drafts)) {
    const val = String(drafts[key] || '').trim()
    if (val) patch[key] = val
  }
  if (!Object.keys(patch).length) {
    error.value = '请至少填写一个新的 API Key（留空表示不改动）'
    return
  }
  saving.value = true
  error.value = ''
  try {
    status.value = await saveApiKeys(patch)
    for (const key of Object.keys(drafts)) drafts[key] = ''
    emit('saved', status.value)
  } catch (e) {
    error.value = e.message || String(e)
  } finally {
    saving.value = false
  }
}

function onBackdrop(e) {
  if (e.target === e.currentTarget) emit('close')
}
</script>

<template>
  <div v-if="open" class="settings-overlay" role="dialog" aria-modal="true" @click="onBackdrop">
    <div class="settings-modal">
      <div class="settings-head">
        <h2 class="settings-title">API Key 设置</h2>
        <button type="button" class="settings-close" title="关闭" @click="emit('close')">×</button>
      </div>

      <p class="settings-desc">
        密钥保存在本机 <code>backend/data/secrets.json</code>（也可写在 <code>.env</code>）。界面只显示脱敏值，不会回显完整 Key。
      </p>

      <div v-if="scriptAlts.length" class="settings-note">
        剧本/分镜：
        <span v-for="(a, i) in scriptAlts" :key="a.provider">
          <template v-if="i"> ↔ </template>
          <code>{{ a.provider }}/{{ a.model }}</code>
        </span>
        （有 Key 即可用，失败自动换另一家）
      </div>

      <div v-if="arkModels" class="settings-note">
        火山方舟模型：文本
        <code>{{ (arkModels.text_models || []).join(' / ') }}</code>
        · 生图 <code>{{ arkModels.image_model }}</code>
        · 视频 <code>{{ arkModels.video_model }}</code>
        · 音频 <code>{{ arkModels.audio_model }}</code>
      </div>

      <div v-if="loading" class="settings-loading">加载中…</div>
      <div v-else class="settings-fields">
        <label v-for="row in keys" :key="row.key" class="settings-field">
          <div class="settings-field-head">
            <span class="settings-label">{{ row.label }}</span>
            <span class="settings-badge" :class="{ on: row.configured }">
              {{ row.configured ? `已配置 · ${row.source}` : '未配置' }}
            </span>
          </div>
          <div class="settings-hint">{{ hints[row.key] || row.key }}</div>
          <div v-if="row.masked" class="settings-masked">当前：{{ row.masked }}</div>
          <input
            v-model="drafts[row.key]"
            class="settings-input"
            type="password"
            autocomplete="off"
            :placeholder="row.configured ? '输入新 Key 以覆盖（留空不改）' : '粘贴 API Key'"
          />
        </label>
      </div>

      <p v-if="error" class="settings-error">{{ error }}</p>

      <div class="settings-actions">
        <button type="button" class="approval-btn deny" :disabled="saving" @click="emit('close')">
          取消
        </button>
        <button type="button" class="approval-btn approve" :disabled="saving || loading" @click="onSave">
          {{ saving ? '保存中…' : '保存' }}
        </button>
      </div>
    </div>
  </div>
</template>
