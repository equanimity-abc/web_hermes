<script setup>
defineProps({
  width: { type: Number, required: true },
  view: { type: String, default: 'chat' },
  sessions: { type: Array, default: () => [] },
  currentSessionId: { type: [String, Number], default: null },
  projects: { type: Array, default: () => [] },
  currentSlug: { type: String, default: null },
  userName: { type: String, default: '用户' },
})

const emit = defineEmits([
  'new-chat',
  'select-session',
  'delete-session',
  'resize-start',
  'set-view',
  'select-project',
  'delete-project',
])
</script>

<template>
  <aside class="sidebar" :style="{ width: width + 'px' }">
    <div class="sidebar-top">
      <div class="sidebar-brand" @click="emit('new-chat'); emit('set-view', 'chat')">
        <svg class="brand-icon" viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg">
          <rect width="24" height="24" rx="6" fill="#4f46e5" />
          <path d="M7 8h10M7 12h10M7 16h7" stroke="#fff" stroke-width="2" stroke-linecap="round" />
        </svg>
        <span class="brand-text">web_hermes</span>
      </div>
      <div class="sidebar-views">
        <button type="button" :class="{ active: view === 'chat' }" @click="emit('set-view', 'chat')">
          对话
        </button>
        <button type="button" :class="{ active: view === 'drama' }" @click="emit('set-view', 'drama')">
          漫剧
        </button>
      </div>
      <button v-if="view === 'chat'" type="button" class="btn-new-chat" @click="emit('new-chat')">
        <svg width="16" height="16" viewBox="0 0 16 16" fill="none">
          <path d="M8 3v10M3 8h10" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" />
        </svg>
        <span>开启新对话</span>
      </button>
    </div>

    <div v-if="view === 'chat'" class="session-list">
      <div
        v-for="session in sessions"
        :key="session.id"
        class="session-item"
        :class="{ active: session.id === currentSessionId }"
        @click="emit('select-session', session.id)"
      >
        <svg class="session-icon" width="16" height="16" viewBox="0 0 16 16" fill="none">
          <path d="M3 3h10v10H3V3z" stroke="currentColor" stroke-width="1.5" stroke-linejoin="round" />
          <path d="M6 6h4M6 9h2" stroke="currentColor" stroke-width="1.2" stroke-linecap="round" />
        </svg>
        <span class="session-title">{{ session.title }}</span>
        <button
          type="button"
          class="btn-delete"
          title="删除"
          @click.stop="emit('delete-session', session.id)"
        >
          <svg width="14" height="14" viewBox="0 0 14 14" fill="none">
            <path d="M3 3l8 8M11 3l-8 8" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" />
          </svg>
        </button>
      </div>
      <div v-if="sessions.length === 0" class="no-sessions">暂无对话记录</div>
    </div>

    <div v-else class="session-list">
      <div
        v-for="item in projects"
        :key="item.slug"
        class="session-item"
        :class="{ active: item.slug === currentSlug }"
        @click="emit('select-project', item.slug)"
      >
        <svg class="session-icon" width="16" height="16" viewBox="0 0 16 16" fill="none">
          <rect x="3" y="4" width="10" height="8" rx="1.5" stroke="currentColor" stroke-width="1.5" />
          <path d="M6 8h4" stroke="currentColor" stroke-width="1.2" stroke-linecap="round" />
        </svg>
        <span class="session-title">{{ item.title }}</span>
        <button
          type="button"
          class="btn-delete"
          title="删除项目"
          @click.stop="emit('delete-project', item.slug)"
        >
          <svg width="14" height="14" viewBox="0 0 14 14" fill="none">
            <path d="M3 3l8 8M11 3l-8 8" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" />
          </svg>
        </button>
      </div>
      <div v-if="projects.length === 0" class="no-sessions">暂无漫剧项目</div>
    </div>

    <div class="sidebar-footer">
      <div class="sidebar-user">
        <div class="user-avatar">👤</div>
        <span class="user-name">{{ userName }}</span>
      </div>
    </div>

    <div class="sidebar-resize-handle" @mousedown="emit('resize-start', $event)" />
  </aside>
</template>
