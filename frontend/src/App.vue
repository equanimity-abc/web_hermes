<template>
  <div class="app-container">
    <!-- ====== 左侧边栏 ====== -->
    <aside class="sidebar" :style="{ width: sidebarWidth + 'px' }">
      <div class="sidebar-top">
        <div class="sidebar-brand" @click="newChat">
          <svg class="brand-icon" viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg">
            <rect width="24" height="24" rx="6" fill="#4f46e5"/>
            <path d="M7 8h10M7 12h10M7 16h7" stroke="#fff" stroke-width="2" stroke-linecap="round"/>
          </svg>
          <span class="brand-text">web_hermes</span>
        </div>
        <button class="btn-new-chat" @click="newChat">
          <svg width="16" height="16" viewBox="0 0 16 16" fill="none">
            <path d="M8 3v10M3 8h10" stroke="currentColor" stroke-width="1.5" stroke-linecap="round"/>
          </svg>
          <span>开启新对话</span>
        </button>
      </div>

      <div class="session-list">
        <div
          v-for="session in sessionList"
          :key="session.id"
          class="session-item"
          :class="{ active: session.id === currentSessionId }"
          @click="switchSession(session.id)"
        >
          <svg class="session-icon" width="16" height="16" viewBox="0 0 16 16" fill="none">
            <path d="M3 3h10v10H3V3z" stroke="currentColor" stroke-width="1.5" stroke-linejoin="round"/>
            <path d="M6 6h4M6 9h2" stroke="currentColor" stroke-width="1.2" stroke-linecap="round"/>
          </svg>
          <span class="session-title">{{ session.title }}</span>
          <button class="btn-delete" @click.stop="deleteSession(session.id)" title="删除">
            <svg width="14" height="14" viewBox="0 0 14 14" fill="none">
              <path d="M3 3l8 8M11 3l-8 8" stroke="currentColor" stroke-width="1.5" stroke-linecap="round"/>
            </svg>
          </button>
        </div>
        <div v-if="sessionList.length === 0" class="no-sessions">暂无对话记录</div>
      </div>

      <div class="sidebar-footer">
        <div class="sidebar-user">
          <div class="user-avatar">👤</div>
          <span class="user-name">用户</span>
        </div>
      </div>

      <!-- 拖拽调整宽度的手柄 -->
      <div class="sidebar-resize-handle" @mousedown="startResize"></div>
    </aside>

    <!-- ====== 主聊天区域 ====== -->
    <main class="chat-area">
      <!-- 空状态欢迎页 -->
      <div v-if="messages.length === 0" class="welcome-screen">
        <div class="welcome-brand">
          <svg width="48" height="48" viewBox="0 0 48 48" fill="none" xmlns="http://www.w3.org/2000/svg">
            <rect width="48" height="48" rx="12" fill="#4f46e5"/>
            <path d="M14 16h20M14 24h20M14 32h14" stroke="#fff" stroke-width="3" stroke-linecap="round"/>
          </svg>
          <h1 class="welcome-title">web_hermes</h1>
        </div>

        <div class="agent-hint">
          <p>🤖 Agent 模式已开启，我将作为智能助手逐步拆解任务、调用工具并执行操作</p>
        </div>

        <!-- 欢迎页输入框 -->
        <div class="welcome-input-area">
          <div class="welcome-input-container">
            <div class="input-box-wrapper">
              <textarea
                ref="inputBox"
                v-model="userInput"
                class="input-box"
                placeholder="给 web_hermes 发送消息"
                @keydown.enter.exact.prevent="sendMessage"
                @input="autoResize"
                rows="1"
              ></textarea>
            </div>
            <div class="input-actions">
              <button class="btn-send" :class="{ 'has-content': userInput.trim() }" :disabled="!userInput.trim()" @click="sendMessage">
                <svg width="18" height="18" viewBox="0 0 18 18" fill="none">
                  <path d="M9 16V4M4 9l5-5 5 5" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/>
                </svg>
              </button>
            </div>
          </div>
        </div>
      </div>

      <!-- 消息列表 -->
      <div v-else class="messages-container" ref="messagesContainer">
        <div v-for="(msg, index) in messages" :key="index" class="message-wrapper" :class="msg.role">
          <div class="message-inner">
            <div class="message-avatar">
              <template v-if="msg.role === 'user'">
                <div class="avatar-user">👤</div>
              </template>
              <template v-else>
                <svg class="avatar-ai" viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg">
                  <rect width="24" height="24" rx="6" fill="#4f46e5"/>
                  <path d="M7 8h10M7 12h10M7 16h7" stroke="#fff" stroke-width="2" stroke-linecap="round"/>
                </svg>
              </template>
            </div>
            <div class="message-body">
              <div v-if="msg.role === 'user'" class="user-bubble-wrapper">
                <div class="user-bubble">{{ msg.content }}</div>
                <div class="bubble-actions">
                  <button class="bubble-action-btn" @click="copyText(msg.content)" title="复制">
                    <svg width="14" height="14" viewBox="0 0 14 14" fill="none">
                      <rect x="3" y="3" width="8" height="8" rx="1" stroke="currentColor" stroke-width="1.2"/>
                      <path d="M5 1h7a1 1 0 011 1v7" stroke="currentColor" stroke-width="1.2" stroke-linecap="round"/>
                    </svg>
                  </button>
                  <button class="bubble-action-btn" @click="editMessage(index)" title="编辑">
                    <svg width="14" height="14" viewBox="0 0 14 14" fill="none">
                      <path d="M10 2l2 2L5 11H3V9l7-7z" stroke="currentColor" stroke-width="1.2" stroke-linejoin="round"/>
                    </svg>
                  </button>
                </div>
              </div>
              <div v-else-if="msg.isStreaming" class="streaming-text markdown-body" v-html="renderMarkdown(msg.content) + '<span class=\'typing-cursor\'>▊</span>'"></div>
              <div v-else class="ai-text markdown-body" v-html="renderMarkdown(msg.content)"></div>
              <div v-if="!msg.isStreaming && msg.role === 'assistant'" class="ai-actions">
                <button class="ai-action-btn" @click="copyText(msg.content)" title="复制">
                  <svg width="15" height="15" viewBox="0 0 15 15" fill="none">
                    <rect x="3.5" y="3.5" width="8" height="8" rx="1" stroke="currentColor" stroke-width="1.2"/>
                    <path d="M5.5 1.5h7a1 1 0 011 1v7" stroke="currentColor" stroke-width="1.2" stroke-linecap="round"/>
                  </svg>
                </button>
                <button class="ai-action-btn" @click="regenerateResponse(index)" title="重新生成">
                  <svg width="15" height="15" viewBox="0 0 15 15" fill="none">
                    <path d="M2.5 7.5a5 5 0 019.5-2" stroke="currentColor" stroke-width="1.2" stroke-linecap="round"/>
                    <path d="M12.5 7.5a5 5 0 01-9.5 2" stroke="currentColor" stroke-width="1.2" stroke-linecap="round"/>
                    <path d="M10 3l2-1.5L13.5 5" stroke="currentColor" stroke-width="1.2" stroke-linecap="round" stroke-linejoin="round"/>
                  </svg>
                </button>
                <button class="ai-action-btn" :class="{ active: msg.liked }" @click="toggleLike(index)" title="喜欢">
                  <svg width="15" height="15" viewBox="0 0 15 15" fill="none">
                    <path d="M7.5 12l-4.2-4.2c-.8-.8-.8-2 0-2.8.8-.8 2-.8 2.8 0l1.4 1.4 1.4-1.4c.8-.8 2-.8 2.8 0 .8.8.8 2 0 2.8L7.5 12z" stroke="currentColor" stroke-width="1.2" stroke-linejoin="round"/>
                  </svg>
                </button>
                <button class="ai-action-btn" :class="{ active: msg.disliked }" @click="toggleDislike(index)" title="不喜欢">
                  <svg width="15" height="15" viewBox="0 0 15 15" fill="none">
                    <path d="M7.5 3l4.2 4.2c.8.8.8 2 0 2.8-.8.8-2 .8-2.8 0L7.5 8.6 6.1 10c-.8.8-2 .8-2.8 0-.8-.8-.8-2 0-2.8L7.5 3z" stroke="currentColor" stroke-width="1.2" stroke-linejoin="round"/>
                  </svg>
                </button>
                <button class="ai-action-btn" @click="copyText(msg.content)" title="分享">
                  <svg width="15" height="15" viewBox="0 0 15 15" fill="none">
                    <circle cx="3" cy="7.5" r="2" stroke="currentColor" stroke-width="1.2"/>
                    <circle cx="12" cy="3" r="2" stroke="currentColor" stroke-width="1.2"/>
                    <circle cx="12" cy="12" r="2" stroke="currentColor" stroke-width="1.2"/>
                    <path d="M4.8 6.5l5.6-2.8M4.8 8.5l5.6 2.8" stroke="currentColor" stroke-width="1.2"/>
                  </svg>
                </button>
              </div>
            </div>
          </div>
        </div>
      </div>

      <!-- 底部输入区域（对话中） -->
      <div v-if="messages.length > 0" class="input-area">
        <div class="input-container">
          <div class="input-box-wrapper">
            <textarea
              ref="inputBox"
              v-model="userInput"
              class="input-box"
              :placeholder="isLoading ? '正在回复...' : '给 web_hermes 发送消息'"
              :disabled="isLoading"
              @keydown.enter.exact.prevent="sendMessage"
              @input="autoResize"
              rows="1"
            ></textarea>
          </div>
          <div class="input-actions">
            <button class="btn-send" :class="{ 'has-content': userInput.trim() }" :disabled="!userInput.trim() || isLoading" @click="sendMessage">
              <svg width="18" height="18" viewBox="0 0 18 18" fill="none">
                <path d="M9 16V4M4 9l5-5 5 5" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/>
              </svg>
            </button>
          </div>
        </div>
      </div>
    </main>

    <!-- 复制成功 Toast -->
    <transition name="toast-fade">
      <div v-if="copyToast" class="copy-toast">{{ copyToast }}</div>
    </transition>
  </div>
</template>

<script>
import { marked } from 'marked'

// 配置 marked 以使用自定义代码块样式
const codeBlockCounter = { count: 0 }

marked.use({
  renderer: {
    code({ text, lang }) {
      const id = 'code-' + (codeBlockCounter.count++)
      const safeLang = (lang || '').replace(/[<>\"']/g, '')
      const langLabel = safeLang
        ? `<div class="code-lang"><span>${safeLang}</span><button class="code-copy-btn" data-code="${id}" title="复制代码"><svg width="14" height="14" viewBox="0 0 14 14" fill="none"><rect x="3" y="3" width="8" height="8" rx="1" stroke="currentColor" stroke-width="1.2"/><path d="M5 1h7a1 1 0 011 1v7" stroke="currentColor" stroke-width="1.2" stroke-linecap="round"/></svg></button></div>`
        : `<div class="code-lang"><span>code</span><button class="code-copy-btn" data-code="${id}" title="复制代码"><svg width="14" height="14" viewBox="0 0 14 14" fill="none"><rect x="3" y="3" width="8" height="8" rx="1" stroke="currentColor" stroke-width="1.2"/><path d="M5 1h7a1 1 0 011 1v7" stroke="currentColor" stroke-width="1.2" stroke-linecap="round"/></svg></button></div>`
      return `<pre class="code-block" data-code-container="${id}">${langLabel}<code id="${id}">${text}</code></pre>`
    }
  }
})

marked.setOptions({
  gfm: true,
  breaks: false,
})

function renderMarkdown(text) {
  if (!text) return ''
  try {
    // marked v15 默认异步，需强制同步模式才能在 v-html 中使用
    let html = marked.parse(text, { async: false })
    html = String(html || '')
    html = html.replace(/<table>/g, '<div class="table-wrapper"><table>').replace(/<\/table>/g, '</table></div>')
    return html
  } catch (e) {
    console.error('Markdown render error:', e, 'Text:', text.substring(0, 200))
    return text
  }
}

export default {
  name: 'App',
  data() {
    return {
      currentSessionId: null,
      messages: [],
      userInput: '',
      isLoading: false,
      sessionList: [],
      sidebarWidth: 325,
      copyToast: '',
    }
  },
  computed: {
    currentSessionTitle() {
      if (!this.currentSessionId) return '新对话'
      const s = this.sessionList.find(s => s.id === this.currentSessionId)
      return s?.title || '新对话'
    },
  },
  mounted() {
    this.updateSessionList()
    // 委托点击：复制代码块
    this.$el.addEventListener('click', (e) => {
      const btn = e.target.closest('.code-copy-btn')
      if (!btn) return
      const codeId = btn.getAttribute('data-code')
      if (!codeId) return
      const codeEl = document.getElementById(codeId)
      if (!codeEl) return
      const text = codeEl.textContent || ''
      navigator.clipboard.writeText(text).then(() => {
        const orig = btn.innerHTML
        btn.innerHTML = '✓'
        setTimeout(() => { btn.innerHTML = orig }, 1500)
      }).catch(() => {})
    })
  },
  methods: {
    renderMarkdown,
    autoResize() {
      const el = this.$refs.inputBox
      if (!el) return
      el.style.height = 'auto'
      el.style.height = Math.min(el.scrollHeight, 200) + 'px'
    },
    newChat() {
      this.currentSessionId = null
      this.messages = []
      this.userInput = ''
      this.$nextTick(() => this.$refs.inputBox?.focus())
    },
    switchSession(sessionId) {
      this.currentSessionId = sessionId
      this.loadSessionMessages(sessionId)
    },
    async loadSessionMessages(sessionId) {
      try {
        const resp = await fetch(`/api/sessions/${sessionId}`)
        if (resp.ok) {
          const data = await resp.json()
          this.messages = data.messages.filter(m => m.role !== 'system').map(m => ({ ...m, isStreaming: false }))
        }
      } catch (e) { console.error('加载会话失败:', e) }
    },
    async deleteSession(sessionId) {
      try {
        await fetch(`/api/sessions/${sessionId}`, { method: 'DELETE' })
        this.sessionList = this.sessionList.filter(s => s.id !== sessionId)
        if (sessionId === this.currentSessionId) this.newChat()
        this.updateSessionList()
      } catch (e) { console.error('删除会话失败:', e) }
    },
    async updateSessionList() {},
    startResize(e) {
      e.preventDefault()
      const startX = e.clientX
      const startWidth = this.sidebarWidth

      const onMouseMove = (ev) => {
        const delta = ev.clientX - startX
        this.sidebarWidth = Math.max(200, Math.min(500, startWidth + delta))
      }

      const onMouseUp = () => {
        document.removeEventListener('mousemove', onMouseMove)
        document.removeEventListener('mouseup', onMouseUp)
        document.body.style.cursor = ''
        document.body.style.userSelect = ''
      }

      document.addEventListener('mousemove', onMouseMove)
      document.addEventListener('mouseup', onMouseUp)
      document.body.style.cursor = 'col-resize'
      document.body.style.userSelect = 'none'
    },
    async sendMessage() {
      const content = this.userInput.trim()
      if (!content || this.isLoading) return
      this.messages.push({ role: 'user', content, isStreaming: false })
      this.userInput = ''
      this.isLoading = true
      this.messages.push({ role: 'assistant', content: '', isStreaming: true })
      this.$nextTick(() => this.scrollToBottom())
      try {
        const response = await fetch('/api/chat/stream', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ session_id: this.currentSessionId, message: content }),
        })
        if (!response.ok) {
          const errText = await response.text()
          throw new Error(`HTTP ${response.status}: ${errText}`)
        }
        const reader = response.body.getReader()
        const decoder = new TextDecoder()
        let buffer = ''
        let sseData = ''
        while (true) {
          const { done, value } = await reader.read()
          if (done) break
          buffer += decoder.decode(value, { stream: true })
          const lines = buffer.split('\n')
          buffer = lines.pop() || ''
          for (const line of lines) {
            const cleanLine = line.replace(/\r$/, '')
            if (cleanLine === '') {
              // 空行：一个 SSE 事件结束，处理已收集的数据
              if (sseData) {
                try {
                  const parsed = JSON.parse(sseData)
                  if (parsed.session_id) {
                    if (!this.currentSessionId) this.currentSessionId = parsed.session_id
                    sseData = ''
                    continue
                  }
                } catch {}
                const lastMsg = this.messages[this.messages.length - 1]
                if (lastMsg && lastMsg.role === 'assistant') {
                  lastMsg.content += sseData
                  this.$nextTick(() => this.scrollToBottom())
                }
                sseData = ''
              }
            } else if (cleanLine.startsWith('data:')) {
              // 累加多行 data（保留换行符）
              if (sseData) sseData += '\n'
              // slice(5) 去掉 "data:"，再去掉 SSE 规范中可选的一个空格
              sseData += cleanLine.slice(5).replace(/^ /, '')
            }
            // 忽略 event: 等其他字段
          }
        }
        const lastMsg = this.messages[this.messages.length - 1]
        if (lastMsg && lastMsg.role === 'assistant') lastMsg.isStreaming = false
      } catch (e) {
        const lastMsg = this.messages[this.messages.length - 1]
        if (lastMsg && lastMsg.role === 'assistant') {
          lastMsg.content = `❌ 错误: ${e.message}`
          lastMsg.isStreaming = false
        }
      } finally {
        this.isLoading = false
        this.$nextTick(() => { this.$refs.inputBox?.focus(); this.autoResize() })
      }
    },
    async copyText(text) {
      try {
        // 尝试 Clipboard API
        await navigator.clipboard.writeText(text)
        this.showCopyToast()
      } catch {
        // 降级方案：创建临时 textarea
        try {
          const ta = document.createElement('textarea')
          ta.value = text
          ta.style.position = 'fixed'
          ta.style.left = '-9999px'
          document.body.appendChild(ta)
          ta.select()
          document.execCommand('copy')
          document.body.removeChild(ta)
          this.showCopyToast()
        } catch {
          console.error('复制失败')
        }
      }
    },
    showCopyToast() {
      this.copyToast = '✓ 已复制'
      setTimeout(() => { this.copyToast = '' }, 2000)
    },
    editMessage(index) {
      const msg = this.messages[index]
      if (msg) {
        this.userInput = msg.content
        this.messages.splice(index, 1)
        this.$nextTick(() => this.$refs.inputBox?.focus())
      }
    },
    regenerateResponse(index) {
      // 删除当前 AI 回复及之后的消息，重新发送上一条用户消息
      const userMsg = this.messages.slice(0, index).reverse().find(m => m.role === 'user')
      if (userMsg) {
        const userContent = userMsg.content
        // 删除当前及之后的 AI 回复
        this.messages = this.messages.slice(0, index)
        this.userInput = userContent
        this.$nextTick(() => this.sendMessage())
      }
    },
    toggleLike(index) {
      const msg = this.messages[index]
      if (msg) {
        msg.liked = !msg.liked
        if (msg.liked) msg.disliked = false
      }
    },
    toggleDislike(index) {
      const msg = this.messages[index]
      if (msg) {
        msg.disliked = !msg.disliked
        if (msg.disliked) msg.liked = false
      }
    },
    scrollToBottom() {
      const el = this.$refs.messagesContainer
      if (el) el.scrollTop = el.scrollHeight
    },
  },
}
</script>

<style>
*, *::before, *::after { margin: 0; padding: 0; box-sizing: border-box; }
body {
  font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', 'PingFang SC', 'Hiragino Sans GB', 'Microsoft YaHei', 'Noto Sans SC', sans-serif;
  background: #fff; color: #1f2937; height: 100vh; overflow: hidden; -webkit-font-smoothing: antialiased;
}
#app { height: 100vh; }
.app-container { display: flex; height: 100vh; }

/* ====== Sidebar ====== */
.sidebar {
  width: 260px; background: #f7f7f9; border-right: 1px solid #e5e7eb;
  display: flex; flex-direction: column; flex-shrink: 0; user-select: none;
  position: relative;
}
.sidebar-top { padding: 12px 8px; }
.sidebar-brand { display: flex; align-items: center; gap: 8px; padding: 4px 8px 12px; cursor: pointer; }
.brand-icon { width: 28px; height: 28px; flex-shrink: 0; }
.brand-text { font-size: 32px; font-weight: 700; color: #1f2937; }
.btn-new-chat {
  display: flex; align-items: center; justify-content: center; gap: 6px;
  width: 100%; padding: 8px 0; background: #e5e7eb; color: #374151;
  border: none; border-radius: 8px; cursor: pointer; font-size: 17px; font-family: inherit; transition: background 0.15s;
}
.btn-new-chat:hover { background: #d1d5db; }
.session-list { flex: 1; overflow-y: auto; padding: 4px 8px; }
.no-sessions { text-align: center; color: #9ca3af; font-size: 12px; padding: 24px 0; }
.session-item {
  display: flex; align-items: center; gap: 8px; padding: 8px 10px; border-radius: 8px;
  cursor: pointer; margin-bottom: 2px; transition: background 0.12s;
}
.session-item:hover { background: #e5e7eb; }
.session-item.active { background: #e5e7eb; }
.session-icon { color: #9ca3af; flex-shrink: 0; }
.session-title { font-size: 13px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; flex: 1; color: #4b5563; }
.session-item.active .session-title { color: #1f2937; font-weight: 500; }
.btn-delete {
  background: none; border: none; color: #9ca3af; cursor: pointer;
  padding: 2px; display: flex; opacity: 0; transition: opacity 0.12s;
}
.session-item:hover .btn-delete { opacity: 1; }
.btn-delete:hover { color: #ef4444; }
.sidebar-footer { padding: 8px 12px; border-top: 1px solid #e5e7eb; }
.sidebar-user { display: flex; align-items: center; gap: 8px; padding: 4px 0; }
.user-avatar { font-size: 20px; }
.user-name { font-size: 13px; color: #4b5563; }

/* ====== Chat Area ====== */
.chat-area { flex: 1; display: flex; flex-direction: column; min-width: 0; background: #fff; position: relative; }

/* ====== Welcome Screen ====== */
.welcome-screen {
  flex: 1; display: flex; flex-direction: column; align-items: center;
  justify-content: center; padding: 0 24px; gap: 0;
}
.welcome-brand { display: flex; align-items: center; gap: 14px; margin-bottom: 28px; }
.welcome-title { font-size: 32px; font-weight: 700; color: #1f2937; }

/* ====== Agent Hint ====== */
.agent-hint p {
  color: #6b7280; font-size: 17px; text-align: center;
  margin-bottom: 36px; line-height: 1.6;
}

/* ====== Welcome Input Area (150% bigger) ====== */
.welcome-input-area { width: 100%; max-width: 72rem; }
.welcome-input-container {
  border: 1.5px solid #e5e7eb; border-radius: 28px;
  padding: 20px 24px 10px; background: #fff;
  transition: border-color 0.15s, box-shadow 0.15s;
}
.welcome-input-container:focus-within {
  border-color: #4f46e5;
  box-shadow: 0 0 0 4px rgba(79, 70, 229, 0.08);
}
.welcome-input-container .input-box {
  font-size: 22px; min-height: 48px; max-height: 360px; line-height: 1.6; padding: 6px 0;
}
.welcome-input-container .input-actions { padding: 8px 0 4px; }
.welcome-input-container .btn-send { width: 36px; height: 36px; border-radius: 10px; }
.welcome-input-container .btn-send svg { width: 20px; height: 20px; }

/* ====== Messages ====== */
.messages-container { flex: 1; overflow-y: auto; padding: 16px 0; }
.message-wrapper { padding: 0; }
.message-wrapper.assistant { border-bottom: 1px solid #f3f4f6; }
.message-wrapper.user { background: #fff; }
.message-inner {
  display: flex; gap: 16px; max-width: 70%; margin: 0 auto;
  padding: 24px 0; width: 100%;
}
.message-wrapper.user .message-inner { flex-direction: row-reverse; }
.message-avatar { flex-shrink: 0; padding-top: 2px; }
.avatar-user { width: 30px; height: 30px; border-radius: 50%; background: #e5e7eb; display: flex; align-items: center; justify-content: center; font-size: 16px; }
.avatar-ai { width: 30px; height: 30px; flex-shrink: 0; }
.message-body { flex: 1; min-width: 0; }
/* User message bubble */
.user-bubble-wrapper {
  display: flex; flex-direction: column; align-items: flex-end;
}
.user-bubble {
  background: #eff0ff; color: #1f2937; font-size: 15px; line-height: 1.7;
  padding: 12px 16px; border-radius: 16px 16px 4px 16px;
  max-width: 100%; word-break: break-word; white-space: pre-wrap;
  display: inline-block;
}
.bubble-actions {
  display: flex; gap: 4px; margin-top: 6px; opacity: 0; transition: opacity 0.12s;
}
.user-bubble-wrapper:hover .bubble-actions { opacity: 1; }
.bubble-action-btn {
  background: none; border: none; color: #9ca3af; cursor: pointer;
  padding: 4px; border-radius: 4px; display: flex; transition: all 0.12s;
}
.bubble-action-btn:hover { background: #f3f4f6; color: #4b5563; }

.user-text { font-size: 15px; color: #1f2937; line-height: 1.7; text-align: right; white-space: pre-wrap; word-break: break-word; }
.streaming-text { font-size: 15px; color: #374151; line-height: 1.75; word-break: break-word; }
.typing-cursor { color: #4f46e5; animation: blink 1s step-end infinite; }
@keyframes blink { 50% { opacity: 0; } }

/* ====== Markdown ====== */
.markdown-body { font-size: 15px; color: #374151; line-height: 1.8; word-break: break-word; }
.markdown-body p { margin: 0 0 14px; }
.markdown-body p:last-child { margin-bottom: 0; }

/* Headings - with subtle accent bar */
.markdown-body h1, .markdown-body h2, .markdown-body h3, .markdown-body h4, .markdown-body h5, .markdown-body h6 {
  color: #111827; margin: 24px 0 12px; font-weight: 700; line-height: 1.35;
  position: relative;
}
.markdown-body h1 { font-size: 1.5em; border-bottom: 2px solid #e5e7eb; padding-bottom: 8px; }
.markdown-body h2 { font-size: 1.3em; border-bottom: 1.5px solid #f3f4f6; padding-bottom: 6px; }
.markdown-body h3 { font-size: 1.15em; }
.markdown-body h4 { font-size: 1.05em; color: #1f2937; }
.markdown-body h5 { font-size: 1em; color: #374151; }
.markdown-body h6 { font-size: 0.95em; color: #4b5563; }

/* Inline code */
.markdown-body :not(pre) > code {
  background: #fef2f2; padding: 3px 8px; border-radius: 5px;
  font-size: 0.88em; color: #dc2626; font-weight: 500;
  font-family: 'JetBrains Mono', 'Fira Code', 'Cascadia Code', 'Consolas', monospace;
  border: 1px solid #fecaca;
}

/* Code Block (single-layer: <pre> only) */
.markdown-body pre.code-block {
  margin: 16px 0; border-radius: 12px; overflow: hidden;
  border: 1px solid #1e293b; background: #1e293b;
  box-shadow: 0 2px 12px rgba(0,0,0,0.08);
  padding: 0;
}
.markdown-body pre.code-block .code-lang {
  display: flex; align-items: center; justify-content: space-between;
  padding: 8px 16px; background: #0f172a; border-bottom: 1px solid #334155;
}
.markdown-body pre.code-block .code-lang span {
  font-size: 11px; color: #94a3b8; text-transform: uppercase;
  letter-spacing: 0.8px; font-family: 'JetBrains Mono', 'Fira Code', monospace;
  display: flex; align-items: center; gap: 6px;
}
.markdown-body pre.code-block .code-lang span::before {
  content: ''; display: inline-block; width: 8px; height: 8px; border-radius: 50%;
  background: #22c55e; box-shadow: 0 0 6px rgba(34,197,94,0.5);
}
.markdown-body pre.code-block > code {
  display: block;
  padding: 16px 20px; overflow-x: auto;
  font-size: 13.5px; line-height: 1.75; color: #e2e8f0;
  font-family: 'JetBrains Mono', 'Fira Code', 'Cascadia Code', 'Consolas', monospace;
  background: none; border: none;
}
.code-copy-btn {
  background: rgba(148,163,184,0.12); border: none; color: #94a3b8; cursor: pointer;
  padding: 4px 10px; border-radius: 6px; display: flex; align-items: center;
  font-size: 11px; transition: all 0.15s; font-family: inherit;
}
.code-copy-btn:hover { background: rgba(148,163,184,0.25); color: #e2e8f0; }

/* Plain pre (when no lang specified) */
.markdown-body pre:not(.code-block) {
  background: #1e293b; border: 1px solid #334155; border-radius: 12px;
  padding: 16px 20px; margin: 16px 0; overflow-x: auto;
  box-shadow: 0 2px 12px rgba(0,0,0,0.08);
}
.markdown-body pre:not(.code-block) code {
  background: none; color: #e2e8f0; font-size: 13.5px; line-height: 1.75;
  font-family: 'JetBrains Mono', 'Fira Code', 'Cascadia Code', 'Consolas', monospace;
  padding: 0; border: none;
}

/* Lists */
.markdown-body ul, .markdown-body ol { margin: 10px 0; padding-left: 24px; }
.markdown-body li { margin: 4px 0; line-height: 1.8; }
.markdown-body li::marker { color: #9ca3af; }
.markdown-body ul ul, .markdown-body ol ol, .markdown-body ul ol, .markdown-body ol ul { margin: 4px 0; }

/* Task Lists */
.markdown-body input[type="checkbox"] {
  margin-right: 8px; accent-color: #4f46e5; transform: scale(1.1);
  vertical-align: middle; cursor: default;
}

/* Blockquote - enhanced */
.markdown-body blockquote {
  border-left: 4px solid #4f46e5; margin: 14px 0; padding: 10px 18px;
  background: #f5f3ff; border-radius: 0 8px 8px 0;
  color: #4b5563; font-style: italic;
}
.markdown-body blockquote p { margin: 0; }
.markdown-body blockquote strong { color: #111827; }

/* Links */
.markdown-body a { color: #4f46e5; text-decoration: none; font-weight: 500; border-bottom: 1px solid transparent; transition: border-color 0.15s; }
.markdown-body a:hover { border-bottom-color: #4f46e5; }

/* Tables - enhanced */
.table-wrapper { overflow-x: auto; margin: 16px 0; border-radius: 10px; border: 1px solid #e5e7eb; }
.markdown-body table { width: 100%; border-collapse: collapse; font-size: 14px; margin: 0; }
.markdown-body th, .markdown-body td { border-bottom: 1px solid #e5e7eb; padding: 10px 14px; text-align: left; }
.markdown-body th { background: #f8fafc; color: #111827; font-weight: 600; font-size: 13px; text-transform: uppercase; letter-spacing: 0.3px; }
.markdown-body tr:last-child td { border-bottom: none; }
.markdown-body tr:nth-child(even) td { background: #fafafa; }
.markdown-body tr:hover td { background: #f0f4ff; }

/* Horizontal rule */
.markdown-body hr { border: none; border-top: 2px solid #f3f4f6; margin: 24px 0; }

/* Images */
.markdown-body img { max-width: 100%; border-radius: 10px; margin: 12px 0; border: 1px solid #e5e7eb; }

/* Strong / Bold */
.markdown-body strong { color: #111827; font-weight: 650; }

/* Description Lists */
.markdown-body dl { margin: 12px 0; }
.markdown-body dt { font-weight: 600; color: #111827; margin-top: 10px; }
.markdown-body dd { margin-left: 20px; color: #4b5563; }

/* Keyboard tag */
.markdown-body kbd {
  background: #f3f4f6; border: 1px solid #d1d5db; border-bottom-width: 2px;
  border-radius: 5px; padding: 2px 7px; font-size: 0.85em;
  font-family: 'JetBrains Mono', 'Fira Code', monospace; color: #374151;
  box-shadow: 0 1px 0 #d1d5db;
}

/* Details / Summary */
.markdown-body details { margin: 12px 0; border: 1px solid #e5e7eb; border-radius: 8px; padding: 10px 16px; background: #fafafa; }
.markdown-body details[open] { padding-bottom: 14px; }
.markdown-body summary { cursor: pointer; font-weight: 600; color: #1f2937; padding: 4px 0; }
.markdown-body details[open] summary { margin-bottom: 8px; color: #4f46e5; }

/* Sub/Sup */
.markdown-body sub, .markdown-body sup { font-size: 0.8em; }
.markdown-body mark { background: #fef08a; padding: 1px 4px; border-radius: 3px; }

/* ====== Input Area (对话中) ====== */
.input-area { padding: 0 48px 24px; background: #fff; border-top: 1px solid transparent; }
.input-container {
  max-width: 56rem; margin: 0 auto;
  border: 1px solid #e5e7eb; border-radius: 20px;
  padding: 12px 16px 6px; background: #fff;
  transition: border-color 0.15s, box-shadow 0.15s;
}
.input-container:focus-within { border-color: #4f46e5; box-shadow: 0 0 0 3px rgba(79, 70, 229, 0.08); }
.input-box-wrapper { padding: 2px 0; }
.input-box {
  width: 100%; background: none; border: none; outline: none;
  color: #1f2937; font-size: 16px; font-family: inherit;
  resize: none; min-height: 28px; max-height: 240px; line-height: 1.6; padding: 4px 0;
}
.input-box::placeholder { color: #bfbfc3; }
.input-actions { display: flex; align-items: center; justify-content: flex-end; padding: 4px 0 2px; gap: 8px; }
.btn-send {
  width: 30px; height: 30px; border-radius: 8px; border: none;
  cursor: pointer; display: flex; align-items: center; justify-content: center;
  transition: all 0.15s; flex-shrink: 0;
  background: #e5e7eb; color: #9ca3af;
}
.btn-send.has-content { background: #4f46e5; color: #fff; }
.btn-send:hover:not(:disabled).has-content { background: #4338ca; }
.input-disclaimer { text-align: center; font-size: 11px; color: #bfbfc3; margin-top: 8px; max-width: 48rem; }

/* ====== AI Message Actions ====== */
.ai-actions {
  display: flex; gap: 2px; margin-top: 10px; opacity: 0; transition: opacity 0.12s;
}
.message-wrapper:hover .ai-actions { opacity: 1; }
.ai-action-btn {
  background: none; border: none; color: #9ca3af; cursor: pointer;
  padding: 5px 7px; border-radius: 4px; display: flex; transition: all 0.12s;
}
.ai-action-btn:hover { background: #f3f4f6; color: #4b5563; }
.ai-action-btn.active { color: #4f46e5; }
.ai-action-btn.active svg { fill: #4f46e5; }

/* ====== Sidebar Resize Handle ====== */
.sidebar-resize-handle {
  position: absolute; right: -3px; top: 0; bottom: 0;
  width: 6px; cursor: col-resize; z-index: 10;
  background: transparent; transition: background 0.15s;
}
.sidebar-resize-handle:hover { background: rgba(79, 70, 229, 0.2); }

/* ====== Copy Toast ====== */
.copy-toast {
  position: fixed; bottom: 80px; left: 50%; transform: translateX(-50%);
  background: #1f2937; color: #fff; padding: 10px 24px;
  border-radius: 10px; font-size: 14px; z-index: 1000;
  pointer-events: none; box-shadow: 0 4px 20px rgba(0,0,0,0.25);
}
.toast-fade-enter-active { transition: all 0.2s ease-out; }
.toast-fade-leave-active { transition: all 0.3s ease-in; }
.toast-fade-enter-from, .toast-fade-leave-to { opacity: 0; transform: translateX(-50%) translateY(10px); }
</style>