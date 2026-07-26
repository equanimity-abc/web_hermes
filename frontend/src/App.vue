<script setup>
import { nextTick, onMounted, ref } from 'vue'
import AppSidebar from '@/components/layout/AppSidebar.vue'
import AppToast from '@/components/layout/AppToast.vue'
import ChatView from '@/components/chat/ChatView.vue'
import { useChat } from '@/composables/useChat'
import { useSessions } from '@/composables/useSessions'
import { useSidebarResize } from '@/composables/useSidebarResize'
import { useClipboardToast } from '@/composables/useClipboardToast'

const chatViewRef = ref(null)

const {
  currentSessionId,
  sessionList,
  refreshSessionList,
  loadSessionMessages,
  removeSession,
  clearCurrentSession,
  setCurrentSessionId,
} = useSessions()

const { sidebarWidth, startResize } = useSidebarResize()
const { toast, copyWithToast } = useClipboardToast()

const {
  messages,
  userInput,
  isLoading,
  resetConversation,
  setMessages,
  sendMessage,
  editMessage,
  regenerateResponse,
  toggleLike,
  toggleDislike,
} = useChat({
  getSessionId: () => currentSessionId.value,
  setSessionId: (id) => {
    setCurrentSessionId(id)
    refreshSessionList()
  },
  scrollToBottom: () => chatViewRef.value?.scrollToBottom?.(),
  onTurnComplete: () => refreshSessionList(),
})

function newChat() {
  clearCurrentSession()
  resetConversation()
  nextTick(() => chatViewRef.value?.focusComposer?.())
}

async function switchSession(sessionId) {
  setCurrentSessionId(sessionId)
  try {
    const list = await loadSessionMessages(sessionId)
    setMessages(list)
  } catch (e) {
    console.error('加载会话失败:', e)
  }
}

async function deleteSession(sessionId) {
  try {
    await removeSession(sessionId)
    if (sessionId === currentSessionId.value) newChat()
  } catch (e) {
    console.error('删除会话失败:', e)
  }
}

function onEditMessage(index) {
  editMessage(index)
  nextTick(() => chatViewRef.value?.focusComposer?.())
}

onMounted(() => {
  refreshSessionList()
})
</script>

<template>
  <div class="app-shell">
    <AppSidebar
      :width="sidebarWidth"
      :sessions="sessionList"
      :current-session-id="currentSessionId"
      @new-chat="newChat"
      @select-session="switchSession"
      @delete-session="deleteSession"
      @resize-start="startResize"
    />

    <ChatView
      ref="chatViewRef"
      v-model="userInput"
      :messages="messages"
      :is-loading="isLoading"
      @submit="sendMessage"
      @copy="copyWithToast"
      @edit="onEditMessage"
      @regenerate="regenerateResponse"
      @like="toggleLike"
      @dislike="toggleDislike"
    />

    <AppToast :message="toast" />
  </div>
</template>
