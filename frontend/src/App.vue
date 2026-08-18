<script setup>
import { nextTick, onMounted, ref, watch } from 'vue'
import AppSidebar from '@/components/layout/AppSidebar.vue'
import AppToast from '@/components/layout/AppToast.vue'
import ChatView from '@/components/chat/ChatView.vue'
import DramaStudio from '@/components/drama/DramaStudio.vue'
import ApprovalModal from '@/components/chat/ApprovalModal.vue'
import { useChat } from '@/composables/useChat'
import { useDramaStudio } from '@/composables/useDramaStudio'
import { useSessions } from '@/composables/useSessions'
import { useSidebarResize } from '@/composables/useSidebarResize'
import { useClipboardToast } from '@/composables/useClipboardToast'

const chatViewRef = ref(null)
const view = ref('chat')
const {
  projects: dramaProjects,
  slug: dramaSlug,
  project: dramaProject,
  episodeN: dramaEpisodeN,
  episode: dramaEpisode,
  selectedN: dramaSelectedN,
  selected: dramaSelected,
  shots: dramaShots,
  episodes: dramaEpisodes,
  draft: dramaDraft,
  dirty: dramaDirty,
  saving: dramaSaving,
  rendering: dramaRendering,
  error: dramaError,
  notice: dramaNotice,
  bust: dramaBust,
  scriptDraft: dramaScriptDraft,
  scriptImpact: dramaScriptImpact,
  boardMode: dramaBoardMode,
  characters: dramaCharacters,
  voices: dramaVoices,
  selectedCharacterId: dramaSelectedCharacterId,
  selectedCharacter: dramaSelectedCharacter,
  charDraft: dramaCharDraft,
  refreshProjects,
  openProject,
  openEpisode,
  selectShot,
  saveShot,
  rerenderSelected,
  rerenderLayer,
  toggleLock,
  previewScriptChanges,
  saveScriptChanges,
  rerenderDirtyShots,
  selectCharacter,
  toggleShotRole,
  addCharacter,
  saveCharacterCard,
  lockSelectedRef,
  uploadSelectedRef,
  deleteSelectedCharacter,
  generateShotCandidates,
  chooseShotCandidate,
  uploadShotScene,
} = useDramaStudio()

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
const { toast, showToast, copyWithToast } = useClipboardToast()

const {
  messages,
  userInput,
  isLoading,
  pendingApproval,
  approvalBusy,
  resetConversation,
  setMessages,
  sendMessage,
  stopGeneration,
  decideApproval,
  uploadFile,
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
  view.value = 'chat'
  clearCurrentSession()
  resetConversation()
  nextTick(() => chatViewRef.value?.focusComposer?.())
}

async function switchSession(sessionId) {
  view.value = 'chat'
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

async function onAttach(file) {
  try {
    const meta = await uploadFile(file)
    showToast(`已上传：${meta.path || file.name}`)
    nextTick(() => chatViewRef.value?.focusComposer?.())
  } catch (e) {
    console.error('上传失败:', e)
    showToast(`上传失败: ${e.message}`)
  }
}

function setView(next) {
  view.value = next
}

async function openDramaProject(slug) {
  view.value = 'drama'
  try {
    await openProject(slug)
  } catch (e) {
    console.error('打开漫剧项目失败:', e)
    showToast(e.message || '打开项目失败')
  }
}

watch(view, async (next) => {
  if (next !== 'drama') return
  try {
    await refreshProjects()
  } catch (e) {
    console.error('加载漫剧项目失败:', e)
    showToast(e.message || '加载项目失败')
  }
})

onMounted(() => {
  refreshSessionList()
})
</script>

<template>
  <div class="app-shell">
    <AppSidebar
      :width="sidebarWidth"
      :view="view"
      :sessions="sessionList"
      :current-session-id="currentSessionId"
      :projects="dramaProjects"
      :current-slug="dramaSlug"
      @new-chat="newChat"
      @select-session="switchSession"
      @delete-session="deleteSession"
      @resize-start="startResize"
      @set-view="setView"
      @select-project="openDramaProject"
    />

    <ChatView
      v-if="view === 'chat'"
      ref="chatViewRef"
      v-model="userInput"
      :messages="messages"
      :is-loading="isLoading"
      @submit="sendMessage"
      @stop="stopGeneration"
      @attach="onAttach"
      @copy="copyWithToast"
      @edit="onEditMessage"
      @regenerate="regenerateResponse"
      @like="toggleLike"
      @dislike="toggleDislike"
    />

    <DramaStudio
      v-else
      :project="dramaProject"
      :episode="dramaEpisode"
      :episode-n="dramaEpisodeN"
      :episodes="dramaEpisodes"
      :shots="dramaShots"
      :selected-n="dramaSelectedN"
      :selected="dramaSelected"
      :draft="dramaDraft"
      :dirty="dramaDirty"
      :saving="dramaSaving"
      :rendering="dramaRendering"
      :error="dramaError"
      :notice="dramaNotice"
      :bust="dramaBust"
      v-model:script-draft="dramaScriptDraft"
      :script-impact="dramaScriptImpact"
      v-model:board-mode="dramaBoardMode"
      :characters="dramaCharacters"
      :voices="dramaVoices"
      :selected-character-id="dramaSelectedCharacterId"
      :selected-character="dramaSelectedCharacter"
      :char-draft="dramaCharDraft"
      @open-episode="openEpisode"
      @select-shot="selectShot"
      @save="saveShot"
      @rerender="rerenderSelected"
      @rerender-layer="rerenderLayer"
      @toggle-lock="toggleLock"
      @preview-script="previewScriptChanges"
      @save-script="saveScriptChanges"
      @rerender-dirty="rerenderDirtyShots"
      @select-character="selectCharacter"
      @add-character="addCharacter"
      @save-character="saveCharacterCard"
      @lock-ref="lockSelectedRef"
      @upload-ref="uploadSelectedRef"
      @delete-character="deleteSelectedCharacter"
      @toggle-role="toggleShotRole"
      @generate-candidates="generateShotCandidates"
      @choose-candidate="chooseShotCandidate"
      @upload-scene="uploadShotScene"
    />

    <ApprovalModal
      :approval="pendingApproval"
      :busy="approvalBusy"
      @approve="decideApproval('approved')"
      @deny="decideApproval('denied')"
    />

    <AppToast :message="toast" />
  </div>
</template>
