<script setup>
import { computed, nextTick, onMounted, ref, watch } from 'vue'
import AppSidebar from '@/components/layout/AppSidebar.vue'
import AppToast from '@/components/layout/AppToast.vue'
import ChatView from '@/components/chat/ChatView.vue'
import DramaStudio from '@/components/drama/DramaStudio.vue'
import DramaJobBar from '@/components/drama/DramaJobBar.vue'
import DramaProgressStatusBar from '@/components/drama/DramaProgressStatusBar.vue'
import ApprovalModal from '@/components/chat/ApprovalModal.vue'
import { useChat } from '@/composables/useChat'
import {
  peekSessionMessages,
  clearSessionMessageCache,
} from '@/composables/useDramaChatProgress'
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
  generatingCandidateNs: dramaGeneratingCandidateNs,
  videoGenProgress: dramaVideoGenProgress,
  batchProgress: dramaBatchProgress,
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
  deleteProject,
  openProject,
  openEpisode,
  selectShot,
  saveShot,
  rerenderSelected,
  rerenderLayer,
  toggleLock,
  previewScriptChanges,
  saveScriptChanges,
  scriptChatProgress,
  scriptChatLoading,
  scriptChatMessages,
  ensureScriptChatSeed,
  sendScriptChat,
  rerenderDirtyShots,
  selectCharacter,
  toggleShotRole,
  addCharacter,
  saveCharacterCard,
  lockSelectedRef,
  uploadSelectedRef,
  deleteSelectedCharacter,
  generateCharacterRef,
  sendCastChatRefine,
  castChatMessages,
  shotChatMessages,
  refineShotChat,
  generateAllCharacterRefs,
  generateAllScenes,
  generateAllVideo,
  generateAllVoice,
  generateShotCandidates,
  chooseShotCandidate,
  deleteCandidate,
  uploadShotScene,
  generateShotI2v,
  generateShotLip,
  generateShotKeys,
  chooseShotKey,
  uploadShotKey,
  lockShotKey,
  qcSelectedShot,
  runEpisodeQc,
  passEpisodeQcGate,
  rejectSelectedShotQc,
  remixEpisodeLoudness,
  suggestEpisodeCoverage,
  applyCoverageSuggestion,
  dismissCoverageSuggestion,
  lockCoverageSuggestion,
  classifyEpisodeShots,
  applyEpisodeStyle,
  timelineOrder: dramaTimelineOrder,
  tlDraft: dramaTlDraft,
  timelineItems: dramaTimelineItems,
  orderedShots: dramaOrderedShots,
  transitions: dramaTransitions,
  i2vModes: dramaI2vModes,
  shotKinds: dramaShotKinds,
  shotSizes: dramaShotSizes,
  timelineDirty: dramaTimelineDirty,
  orderDirty: dramaOrderDirty,
  mixDraft: dramaMixDraft,
  mixDirty: dramaMixDirty,
  mixUnlicensed: dramaMixUnlicensed,
  config: dramaConfig,
  presets: dramaPresets,
  currentPreset: dramaCurrentPreset,
  modelCatalog: dramaModelCatalog,
  degradedProviders: dramaDegradedProviders,
  applyProjectPreset,
  applyStageModel,
  stageModelSelection,
  selectedConfigNode: dramaSelectedConfigNode,
  configNodeDraft: dramaConfigNodeDraft,
  configNodeList: dramaConfigNodeList,
  selectConfigNode,
  saveConfigNode,
  selectedShotIds: dramaSelectedShotIds,
  toggleShotSelected,
  clearShotSelection,
  selectAllShots,
  applyBatchEdit,
  snapshots: dramaSnapshots,
  snapshotsOpen: dramaSnapshotsOpen,
  toggleSnapshotsPanel,
  restoreSnapshotVersion,
  deleteSnapshotVersion,
  budget: dramaBudget,
  budgetBlocked: dramaBudgetBlocked,
  budgetWarn: dramaBudgetWarn,
  budgetDraft: dramaBudgetDraft,
  budgetOpen: dramaBudgetOpen,
  toggleBudgetPanel,
  saveBudget,
  qcChecklist: dramaQcChecklist,
  checklistOpen: dramaChecklistOpen,
  rejectingAll: dramaRejectingAll,
  toggleChecklistPanel,
  refreshQcChecklist,
  rejectAllProblems,
  saveTimelineAll,
  saveTimelineOrder,
  moveTimelineShot,
  reorderTimeline,
  exportTimeline,
  saveMix,
  uploadBgm,
  applyMix,
  clearBgm,
  renderJobs: dramaRenderJobs,
  activeJobs: dramaActiveJobs,
  cancelRenderJob,
  retryRenderJob,
} = useDramaStudio()

const dramaCastChatMessages = computed(() => castChatMessages(dramaSelectedCharacterId.value))
const dramaVideoChatMessages = computed(() => shotChatMessages('video', dramaSelectedN.value))
const dramaVoiceChatMessages = computed(() => shotChatMessages('voice', dramaSelectedN.value))
const dramaSceneChatMessages = computed(() => shotChatMessages('scene', dramaSelectedN.value))

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
  stashCurrent,
  resumeAfterMessagesLoad,
} = useChat({
  getSessionId: () => currentSessionId.value,
  setSessionId: (id) => {
    setCurrentSessionId(id)
    refreshSessionList()
  },
  scrollToBottom: () => chatViewRef.value?.scrollToBottom?.(),
  onTurnComplete: () => refreshSessionList(),
})

const dramaScriptChatMessages = computed(() => scriptChatMessages())
const firstUserContent = computed(() => {
  const msg = (messages.value || []).find((m) => m.role === 'user')
  return String(msg?.content || '').trim()
})

const dramaBatchPct = computed(() => {
  const p = dramaBatchProgress.value
  if (!p) return 0
  if (p.total) {
    return Math.min(100, Math.round(((p.current || 0) / p.total) * 100))
  }
  if (p.status === 'done') return 100
  if (p.status === 'running') return 35
  return 0
})

const dramaBatchStatusTitle = computed(() => {
  const s = dramaBatchProgress.value?.status
  if (s === 'running') return '处理中'
  if (s === 'done') return '完成'
  if (s === 'error') return '失败'
  return dramaBatchProgress.value?.label || '批量任务'
})

const dramaBatchStatusMessage = computed(() => {
  const p = dramaBatchProgress.value
  if (!p) return ''
  const parts = []
  if (p.label) parts.push(p.label)
  if (p.total) {
    let count = `${p.current || 0}/${p.total}`
    if (p.failed) count += ` · 失败 ${p.failed}`
    parts.push(count)
  }
  if (p.message) parts.push(p.message)
  return parts.filter(Boolean).join(' · ') || '就绪'
})

function newChat() {
  view.value = 'chat'
  stashCurrent(currentSessionId.value || '__draft__')
  clearCurrentSession()
  resetConversation()
  nextTick(() => chatViewRef.value?.focusComposer?.())
}

async function switchSession(sessionId) {
  view.value = 'chat'
  // Mid-generate: reloading from disk would wipe live tool/status UI (session not flushed yet).
  if (sessionId === currentSessionId.value && isLoading.value) {
    return
  }

  // Keep live progress for the session we leave
  const leaving = currentSessionId.value || '__draft__'
  stashCurrent(leaving)

  setCurrentSessionId(sessionId)
  const cached = peekSessionMessages(sessionId)
  if (cached && cached.length) {
    setMessages(cached)
    void resumeAfterMessagesLoad(sessionId)
    nextTick(() => chatViewRef.value?.scrollToBottom?.())
    return
  }
  try {
    const list = await loadSessionMessages(sessionId)
    setMessages(list)
    // Cache the live array reference so later switches keep dramaJob updates
    stashCurrent(sessionId)
    void resumeAfterMessagesLoad(sessionId)
  } catch (e) {
    console.error('加载会话失败:', e)
  }
}

async function deleteSession(sessionId) {
  try {
    clearSessionMessageCache(sessionId)
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
  if (next === 'drama') {
    stashCurrent(currentSessionId.value || '__draft__')
  }
  view.value = next
}

async function openDramaProject(slug) {
  stashCurrent(currentSessionId.value || '__draft__')
  view.value = 'drama'
  try {
    await openProject(slug)
    ensureScriptChatSeed(firstUserContent.value)
  } catch (e) {
    console.error('打开漫剧项目失败:', e)
    showToast(e.message || '打开项目失败')
  }
}

async function openDramaFromChat({ slug, episode } = {}) {
  if (!slug) return
  stashCurrent(currentSessionId.value || '__draft__')
  view.value = 'drama'
  try {
    await openProject(slug)
    if (episode != null) await openEpisode(Number(episode))
    ensureScriptChatSeed(firstUserContent.value)
  } catch (e) {
    console.error('打开漫剧项目失败:', e)
    showToast(e.message || '打开项目失败')
  }
}

async function deleteDramaProject(slug) {
  if (!window.confirm(`确定删除漫剧项目「${slug}」？该操作会删除剧本、分镜、配音与成片，不可恢复。`)) {
    return
  }
  try {
    await deleteProject(slug)
    showToast(`已删除项目 ${slug}`)
  } catch (e) {
    console.error('删除漫剧项目失败:', e)
    showToast(e.message || '删除项目失败')
  }
}

watch(view, async (next) => {
  if (next !== 'drama') return
  ensureScriptChatSeed(firstUserContent.value)
  try {
    await refreshProjects()
  } catch (e) {
    console.error('加载漫剧项目失败:', e)
    showToast(e.message || '加载项目失败')
  }
})

function onEnterScriptStage() {
  ensureScriptChatSeed(firstUserContent.value)
}

onMounted(() => {
  refreshSessionList()
  if ((messages.value || []).length) {
    void resumeAfterMessagesLoad(currentSessionId.value)
  }
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
      @delete-project="deleteDramaProject"
    />

    <ChatView
      v-show="view === 'chat'"
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
      @open-drama="openDramaFromChat"
    />

    <DramaStudio
      v-show="view === 'drama'"
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
      :generating-candidate-ns="dramaGeneratingCandidateNs"
      :video-gen-progress="dramaVideoGenProgress"
      :error="dramaError"
      :notice="dramaNotice"
      :bust="dramaBust"
      v-model:script-draft="dramaScriptDraft"
      :script-impact="dramaScriptImpact"
      :script-chat-messages="dramaScriptChatMessages"
      :script-chat-loading="scriptChatLoading"
      :script-chat-progress="scriptChatProgress"
      v-model:board-mode="dramaBoardMode"
      :characters="dramaCharacters"
      :voices="dramaVoices"
      :selected-character-id="dramaSelectedCharacterId"
      :selected-character="dramaSelectedCharacter"
      :char-draft="dramaCharDraft"
      :cast-chat-messages="dramaCastChatMessages"
      :video-chat-messages="dramaVideoChatMessages"
      :voice-chat-messages="dramaVoiceChatMessages"
      :scene-chat-messages="dramaSceneChatMessages"
      :timeline-order="dramaTimelineOrder"
      :tl-draft="dramaTlDraft"
      :timeline-items="dramaTimelineItems"
      :ordered-shots="dramaOrderedShots"
      :transitions="dramaTransitions"
      :i2v-modes="dramaI2vModes"
      :shot-kinds="dramaShotKinds"
      :shot-sizes="dramaShotSizes"
      :timeline-dirty="dramaTimelineDirty"
      :order-dirty="dramaOrderDirty"
      :mix-draft="dramaMixDraft"
      :mix-dirty="dramaMixDirty"
      :mix-unlicensed="dramaMixUnlicensed"
      :presets="dramaPresets"
      :current-preset="dramaCurrentPreset"
      :model-catalog="dramaModelCatalog"
      :stage-model-selection="stageModelSelection"
      :degraded-providers="dramaDegradedProviders"
      :config-node-list="dramaConfigNodeList"
      :selected-config-node="dramaSelectedConfigNode"
      v-model:config-node-draft="dramaConfigNodeDraft"
      :selected-shot-ids="dramaSelectedShotIds"
      :snapshots="dramaSnapshots"
      :snapshots-open="dramaSnapshotsOpen"
      :budget="dramaBudget"
      :budget-blocked="dramaBudgetBlocked"
      :budget-warn="dramaBudgetWarn"
      :budget-draft="dramaBudgetDraft"
      :budget-open="dramaBudgetOpen"
      :qc-checklist="dramaQcChecklist"
      :checklist-open="dramaChecklistOpen"
      :rejecting-all="dramaRejectingAll"
      @open-episode="openEpisode"
      @apply-preset="applyProjectPreset"
      @apply-stage-model="({ node, key }) => applyStageModel(node, key)"
      @select-config-node="selectConfigNode"
      @save-config-node="saveConfigNode"
      @toggle-shot-selected="toggleShotSelected"
      @clear-shot-selection="clearShotSelection"
      @select-all-shots="selectAllShots"
      @apply-batch-edit="applyBatchEdit"
      @toggle-snapshots="toggleSnapshotsPanel"
      @restore-snapshot="restoreSnapshotVersion"
      @delete-snapshot="deleteSnapshotVersion"
      @toggle-budget="toggleBudgetPanel"
      @save-budget="saveBudget"
      @toggle-checklist="toggleChecklistPanel"
      @refresh-checklist="refreshQcChecklist"
      @reject-all-qc="rejectAllProblems"
      @select-shot="selectShot"
      @save="saveShot"
      @rerender="rerenderSelected"
      @rerender-layer="rerenderLayer"
      @toggle-lock="toggleLock"
      @preview-script="previewScriptChanges"
      @save-script="saveScriptChanges"
      @script-chat-send="sendScriptChat"
      @enter-script-stage="onEnterScriptStage"
      @rerender-dirty="rerenderDirtyShots"
      @select-character="selectCharacter"
      @add-character="addCharacter"
      @save-character="saveCharacterCard"
      @lock-ref="lockSelectedRef"
      @upload-ref="uploadSelectedRef"
      @delete-character="deleteSelectedCharacter"
      @generate-character-ref="generateCharacterRef"
      @refine-character-ref="(cid, instruction) => sendCastChatRefine(cid, instruction)"
      @refine-shot-chat="(stage, shotN, instruction) => refineShotChat(stage, shotN, instruction)"
      @generate-all-refs="(cat) => generateAllCharacterRefs(cat)"
      @generate-all-scenes="generateAllScenes"
      @generate-all-video="generateAllVideo"
      @generate-all-voice="generateAllVoice"
      @toggle-role="toggleShotRole"
      @generate-candidates="generateShotCandidates"
      @choose-candidate="chooseShotCandidate"
      @delete-candidate="deleteCandidate"
      @upload-scene="uploadShotScene"
      @generate-i2v="generateShotI2v"
      @generate-lip="generateShotLip"
      @generate-keys="generateShotKeys"
      @choose-key="chooseShotKey"
      @upload-key="uploadShotKey"
      @lock-key="lockShotKey"
      @qc-shot="qcSelectedShot"
      @qc-episode="runEpisodeQc"
      @pass-episode-qc="passEpisodeQcGate"
      @reject-shot-qc="rejectSelectedShotQc"
      @remix-loudness="remixEpisodeLoudness"
      @suggest-coverage="suggestEpisodeCoverage"
      @apply-coverage="applyCoverageSuggestion"
      @dismiss-coverage="dismissCoverageSuggestion"
      @lock-coverage="lockCoverageSuggestion"
      @classify-shots="() => classifyEpisodeShots(false)"
      @apply-style="applyEpisodeStyle"
      @save-timeline-all="saveTimelineAll"
      @save-timeline-order="saveTimelineOrder"
      @move-timeline-shot="(n, d) => moveTimelineShot(n, d)"
      @reorder-timeline="reorderTimeline"
      @export-timeline="exportTimeline"
      @save-mix="saveMix"
      @upload-bgm="uploadBgm"
      @apply-mix="applyMix"
      @clear-bgm="clearBgm"
    />

    <aside
      v-if="view === 'drama' && (dramaBatchProgress || (dramaActiveJobs && dramaActiveJobs.length))"
      class="drama-job-bar"
    >
      <DramaProgressStatusBar
        v-if="dramaBatchProgress"
        class="drama-job-bar-progress"
        :pct="dramaBatchPct"
        :status="dramaBatchProgress.status || 'idle'"
        :title="dramaBatchStatusTitle"
        :message="dramaBatchStatusMessage"
      />
      <DramaJobBar
        v-if="dramaActiveJobs?.length"
        :jobs="dramaActiveJobs"
        @cancel="cancelRenderJob"
        @retry="retryRenderJob"
      />
    </aside>

    <ApprovalModal
      :approval="pendingApproval"
      :busy="approvalBusy"
      @approve="decideApproval('approved')"
      @deny="decideApproval('denied')"
    />

    <AppToast :message="toast" />
  </div>
</template>
