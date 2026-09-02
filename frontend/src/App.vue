<script setup>
import { computed, nextTick, onMounted, ref, watch } from 'vue'
import AppSidebar from '@/components/layout/AppSidebar.vue'
import AppToast from '@/components/layout/AppToast.vue'
import SettingsModal from '@/components/layout/SettingsModal.vue'
import ChatView from '@/components/chat/ChatView.vue'
import DramaStudio from '@/components/drama/DramaStudio.vue'
import DramaJobBar from '@/components/drama/DramaJobBar.vue'
import ApprovalModal from '@/components/chat/ApprovalModal.vue'
import { useChat } from '@/composables/useChat'
import { useDramaStudio } from '@/composables/useDramaStudio'
import { useSessions } from '@/composables/useSessions'
import { useSidebarResize } from '@/composables/useSidebarResize'
import { useClipboardToast } from '@/composables/useClipboardToast'

const chatViewRef = ref(null)
const view = ref('chat')
const settingsOpen = ref(false)
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
  generateScriptFromPremise,
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
  // Mid-generate: reloading from disk would wipe live tool/status UI (session not flushed yet).
  if (sessionId === currentSessionId.value && isLoading.value) {
    return
  }
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

function onSettingsSaved() {
  showToast('API Key 已保存')
  settingsOpen.value = false
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

async function openDramaFromChat({ slug, episode } = {}) {
  if (!slug) return
  view.value = 'drama'
  try {
    await openProject(slug)
    if (episode != null) await openEpisode(Number(episode))
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
      @delete-project="deleteDramaProject"
      @open-settings="settingsOpen = true"
    />

    <SettingsModal
      :open="settingsOpen"
      @close="settingsOpen = false"
      @saved="onSettingsSaved"
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
      v-model:board-mode="dramaBoardMode"
      :characters="dramaCharacters"
      :voices="dramaVoices"
      :selected-character-id="dramaSelectedCharacterId"
      :selected-character="dramaSelectedCharacter"
      :char-draft="dramaCharDraft"
      :cast-chat-messages="dramaCastChatMessages"
      :video-chat-messages="dramaVideoChatMessages"
      :voice-chat-messages="dramaVoiceChatMessages"
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
      @generate-script="generateScriptFromPremise"
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
      <div
        v-if="dramaBatchProgress"
        class="drama-batch-progress"
        :class="{
          'is-running': dramaBatchProgress.status === 'running',
          'is-done': dramaBatchProgress.status === 'done',
          'is-error': dramaBatchProgress.status === 'error',
        }"
      >
        <div class="drama-batch-progress-head">
          <strong>{{ dramaBatchProgress.label || '批量任务' }}</strong>
          <span>
            {{ dramaBatchProgress.current || 0 }}/{{ dramaBatchProgress.total || 0 }}
            <template v-if="dramaBatchProgress.failed"> · 失败 {{ dramaBatchProgress.failed }}</template>
          </span>
        </div>
        <p class="drama-batch-progress-msg">{{ dramaBatchProgress.message || '' }}</p>
        <div class="drama-batch-progress-track">
          <div
            class="drama-batch-progress-fill"
            :style="{
              width: `${
                dramaBatchProgress.total
                  ? Math.min(100, Math.round(((dramaBatchProgress.current || 0) / dramaBatchProgress.total) * 100))
                  : dramaBatchProgress.status === 'running'
                    ? 35
                    : 0
              }%`,
            }"
          />
        </div>
      </div>
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
