<script setup>
import { computed } from 'vue'
import { SCRIPT_ASSET_FIELDS, SCRIPT_META_FIELDS, SCRIPT_SHOT_FIELDS } from '@/utils/parseDramaScript'

const props = defineProps({
  parsed: {
    type: Object,
    default: () => ({
      title: '',
      meta: {},
      cast: [],
      locations: [],
      props: [],
      shots: [],
    }),
  },
})

const metaRows = computed(() => {
  const meta = props.parsed?.meta || {}
  return SCRIPT_META_FIELDS.filter((k) => String(meta[k] || '').trim()).map((k) => ({
    key: k,
    value: meta[k],
  }))
})

const bgmText = computed(() => String(props.parsed?.meta?.配乐 || '').trim())

const sections = computed(() => [
  {
    id: 'cast',
    label: '角色',
    empty: '暂无角色设定',
    items: props.parsed?.cast || [],
    fields: SCRIPT_ASSET_FIELDS.cast,
  },
  {
    id: 'locations',
    label: '场景',
    empty: '暂无场景设定',
    items: props.parsed?.locations || [],
    fields: SCRIPT_ASSET_FIELDS.locations,
  },
  {
    id: 'props',
    label: '道具',
    empty: '暂无道具设定',
    items: props.parsed?.props || [],
    fields: SCRIPT_ASSET_FIELDS.props,
  },
])

const shots = computed(() => props.parsed?.shots || [])

function itemFields(item, fieldKeys) {
  const known = fieldKeys
    .filter((k) => String(item?.[k] || '').trim())
    .map((k) => ({ key: k, value: item[k] }))
  const extras = Object.keys(item || {})
    .filter((k) => k !== 'name' && !fieldKeys.includes(k) && String(item[k] || '').trim())
    .map((k) => ({ key: k, value: item[k] }))
  return [...known, ...extras]
}

function shotFields(shot) {
  return SCRIPT_SHOT_FIELDS.filter((k) => String(shot?.[k] || '').trim()).map((k) => ({
    key: k,
    value: shot[k],
  }))
}
</script>

<template>
  <div class="drama-script-outline">
    <header v-if="parsed.title || metaRows.length" class="drama-script-outline-hero">
      <h3 v-if="parsed.title" class="drama-script-outline-title">{{ parsed.title }}</h3>
      <dl v-if="metaRows.filter((r) => r.key !== '配乐').length" class="drama-script-outline-meta">
        <div
          v-for="row in metaRows.filter((r) => r.key !== '配乐')"
          :key="row.key"
          class="drama-script-outline-meta-row"
        >
          <dt>{{ row.key }}</dt>
          <dd>{{ row.value }}</dd>
        </div>
      </dl>
    </header>

    <section
      v-for="sec in sections"
      :id="`script-sec-${sec.id}`"
      :key="sec.id"
      class="drama-script-outline-section"
    >
      <h4 class="drama-script-outline-h">
        {{ sec.label }}
        <span class="drama-script-outline-count">{{ sec.items.length }}</span>
      </h4>
      <p v-if="!sec.items.length" class="drama-script-outline-empty">{{ sec.empty }}</p>
      <article
        v-for="(item, idx) in sec.items"
        :key="`${sec.id}-${item.name || idx}`"
        class="drama-script-asset-card"
      >
        <h5 class="drama-script-asset-name">{{ item.name || '未命名' }}</h5>
        <dl class="drama-script-asset-fields">
          <div v-for="f in itemFields(item, sec.fields)" :key="f.key" class="drama-script-asset-field">
            <dt>{{ f.key }}</dt>
            <dd>{{ f.value }}</dd>
          </div>
        </dl>
      </article>
    </section>

    <section id="script-sec-bgm" class="drama-script-outline-section">
      <h4 class="drama-script-outline-h">配乐</h4>
      <p v-if="!bgmText" class="drama-script-outline-empty">暂无配乐描述</p>
      <article v-else class="drama-script-asset-card">
        <dl class="drama-script-asset-fields">
          <div class="drama-script-asset-field">
            <dt>配乐</dt>
            <dd>{{ bgmText }}</dd>
          </div>
        </dl>
      </article>
    </section>

    <section id="script-sec-shots" class="drama-script-outline-section">
      <h4 class="drama-script-outline-h">
        分镜
        <span class="drama-script-outline-count">{{ shots.length }}</span>
      </h4>
      <p v-if="!shots.length" class="drama-script-outline-empty">暂无分镜</p>
      <article v-for="shot in shots" :key="shot.n" class="drama-script-shot-card">
        <h5 class="drama-script-shot-head">
          Shot {{ shot.n }}
          <span v-if="shot.timing" class="drama-script-shot-timing">{{ shot.timing }}</span>
        </h5>
        <dl class="drama-script-asset-fields">
          <div v-for="f in shotFields(shot)" :key="f.key" class="drama-script-asset-field">
            <dt>{{ f.key }}</dt>
            <dd>{{ f.value }}</dd>
          </div>
        </dl>
      </article>
    </section>
  </div>
</template>
