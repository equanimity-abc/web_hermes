<script setup>
import { computed } from 'vue'

const props = defineProps({
  /** 0–100 */
  pct: { type: [Number, String], default: 0 },
  /** idle | running | done | error | pending */
  status: { type: String, default: 'idle' },
  title: { type: String, default: '状态' },
  message: { type: String, default: '' },
  /** default = light panel; dark = under video preview */
  variant: { type: String, default: 'default' },
  showPct: { type: Boolean, default: true },
})

const pctValue = computed(() => {
  const n = Number(props.pct)
  if (!Number.isFinite(n)) return 0
  return Math.max(0, Math.min(100, Math.round(n)))
})

const statusClass = computed(() => {
  const s = String(props.status || 'idle')
  if (s === 'running' || s === 'pending') return 'is-running'
  if (s === 'error') return 'is-error'
  if (s === 'done') return 'is-done'
  return 'is-idle'
})
</script>

<template>
  <div
    class="drama-progress-status-bar"
    :class="[statusClass, variant === 'dark' ? 'is-dark' : '']"
  >
    <div class="drama-progress-status-progress">
      <div class="drama-progress-status-track">
        <div class="drama-progress-status-fill" :style="{ width: pctValue + '%' }" />
      </div>
      <span v-if="showPct" class="drama-progress-status-pct">{{ pctValue }}%</span>
    </div>
    <div class="drama-progress-status-info">
      <strong>{{ title }}</strong>
      <p class="drama-progress-status-msg">{{ message || '就绪' }}</p>
    </div>
  </div>
</template>

<style scoped>
.drama-progress-status-bar {
  flex-shrink: 0;
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 8px;
  height: 40px;
  padding: 0 10px;
  border-radius: 8px;
  border: 1px solid #e5e7eb;
  background: #f9fafb;
  align-items: center;
  box-sizing: border-box;
}

.drama-progress-status-bar.is-running {
  border-color: #c7d2fe;
  background: #eef2ff;
}

.drama-progress-status-bar.is-error {
  border-color: #fecaca;
  background: #fef2f2;
}

.drama-progress-status-bar.is-done {
  border-color: #a7f3d0;
  background: #ecfdf5;
}

.drama-progress-status-bar.is-dark {
  background: #2a3648;
  border: 1px solid rgba(255, 255, 255, 0.16);
  border-top: 2px solid rgba(147, 197, 253, 0.45);
  box-shadow:
    0 -6px 16px rgba(0, 0, 0, 0.28),
    inset 0 1px 0 rgba(255, 255, 255, 0.06);
}

.drama-progress-status-bar.is-dark.is-running {
  background: #243044;
  border-color: rgba(147, 197, 253, 0.35);
}

.drama-progress-status-bar.is-dark.is-error {
  background: #3f1d24;
  border-color: rgba(252, 165, 165, 0.4);
}

.drama-progress-status-bar.is-dark.is-done {
  background: #1e3a2f;
  border-color: rgba(167, 243, 208, 0.35);
}

.drama-progress-status-progress,
.drama-progress-status-info {
  min-width: 0;
  display: flex;
  align-items: center;
  gap: 8px;
  height: 100%;
}

.drama-progress-status-track {
  flex: 1;
  height: 6px;
  margin: 0;
  border-radius: 999px;
  background: rgba(0, 0, 0, 0.08);
  overflow: hidden;
}

.drama-progress-status-bar.is-dark .drama-progress-status-track {
  background: rgba(255, 255, 255, 0.12);
}

.drama-progress-status-fill {
  height: 100%;
  background: #6366f1;
  transition: width 0.25s;
}

.drama-progress-status-bar.is-error .drama-progress-status-fill {
  background: #dc2626;
}

.drama-progress-status-bar.is-done .drama-progress-status-fill {
  background: #16a34a;
}

.drama-progress-status-bar.is-idle .drama-progress-status-fill {
  background: rgba(15, 23, 42, 0.2);
}

.drama-progress-status-bar.is-dark.is-idle .drama-progress-status-fill {
  background: rgba(255, 255, 255, 0.2);
}

.drama-progress-status-bar.is-dark.is-running .drama-progress-status-fill {
  background: #f59e0b;
}

.drama-progress-status-pct {
  font-size: 12px;
  font-variant-numeric: tabular-nums;
  color: #6b7280;
  flex-shrink: 0;
  min-width: 2.5em;
}

.drama-progress-status-bar.is-dark .drama-progress-status-pct {
  color: #93c5fd;
}

.drama-progress-status-info strong {
  font-size: 12px;
  flex-shrink: 0;
}

.drama-progress-status-bar.is-dark .drama-progress-status-info strong {
  color: #e5e7eb;
}

.drama-progress-status-msg {
  margin: 0;
  font-size: 12px;
  color: #6b7280;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.drama-progress-status-bar.is-dark .drama-progress-status-msg {
  color: #d1d5db;
}

.drama-progress-status-bar.is-error .drama-progress-status-msg,
.drama-progress-status-bar.is-error .drama-progress-status-info strong {
  color: #b91c1c;
}

.drama-progress-status-bar.is-dark.is-error .drama-progress-status-msg,
.drama-progress-status-bar.is-dark.is-error .drama-progress-status-info strong {
  color: #fecaca;
}
</style>
