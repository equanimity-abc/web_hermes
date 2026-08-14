import { marked } from 'marked'

const codeBlockCounter = { count: 0 }

marked.use({
  renderer: {
    link({ href, title, text }) {
      const url = String(href || '')
      const safeHref = escapeHtml(url)
      const label = text || url
      const isVideo =
        /\.mp4(\?|$)/i.test(url) ||
        (url.includes('/api/workspace/file') && /\.mp4/i.test(url))
      if (isVideo) {
        return `<video class="md-video" controls preload="metadata" src="${safeHref}"></video>`
      }
      const titleAttr = title ? ` title="${escapeHtml(title)}"` : ''
      return `<a href="${safeHref}"${titleAttr} target="_blank" rel="noopener noreferrer">${label}</a>`
    },
    code({ text, lang }) {
      const id = 'code-' + codeBlockCounter.count++
      const safeLang = (lang || '').replace(/[<>"']/g, '')
      const label = safeLang || 'code'
      const langLabel = `<div class="code-lang"><span>${label}</span><button class="code-copy-btn" data-code="${id}" title="复制代码"><svg width="14" height="14" viewBox="0 0 14 14" fill="none"><rect x="3" y="3" width="8" height="8" rx="1" stroke="currentColor" stroke-width="1.2"/><path d="M5 1h7a1 1 0 011 1v7" stroke="currentColor" stroke-width="1.2" stroke-linecap="round"/></svg></button></div>`
      // Escape HTML in code body to avoid broken rendering / XSS
      const escaped = text
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
      return `<pre class="code-block" data-code-container="${id}">${langLabel}<code id="${id}">${escaped}</code></pre>`
    },
  },
})

marked.setOptions({
  gfm: true,
  breaks: true,
})

/**
 * Normalize common LLM markdown quirks before parsing.
 * Models often glue headings/lists onto the previous sentence without newlines.
 */
export function normalizeMarkdown(text) {
  let s = String(text || '').replace(/\r\n?/g, '\n')

  // Fullwidth asterisks / hashes → ASCII (common in CN model output)
  s = s.replace(/＊/g, '*').replace(/＃/g, '#')

  // ATX heading glued to previous text: "...结束。## 3. 标题"
  s = s.replace(/([^\n#])[ \t]*(#{1,6}[ \t]+)/g, '$1\n\n$2')

  // Heading immediately after another block without blank line
  s = s.replace(/\n(#{1,6}[ \t]+)/g, '\n\n$1')

  // Ensure space after # markers: "##标题" → "## 标题"
  s = s.replace(/^(#{1,6})([^\s#])/gm, '$1 $2')

  // Standalone bold line used as section title → heading
  // e.g. **1. 基本作用**  /  **对比说明**
  s = s.replace(
    /^(?:[ \t]*)\*\*(.+?)\*\*[ \t]*$/gm,
    (_, title) => `### ${title.trim()}`,
  )

  // Unordered / ordered list glued to previous sentence
  s = s.replace(/([^\n])\n([-*+][ \t]+|\d+\.[ \t]+)/g, '$1\n\n$2')

  // Horizontal rule glued without blank lines
  s = s.replace(/([^\n])\n(---+|___+|\*\*\*+)\s*(?=\n|$)/g, '$1\n\n$2\n')

  // Collapse excessive blank lines
  s = s.replace(/\n{3,}/g, '\n\n')

  return s.trim()
}

/**
 * Render markdown to HTML (sync). Safe for v-html in Vue.
 */
export function renderMarkdown(text) {
  if (!text) return ''
  try {
    const normalized = normalizeMarkdown(text)
    let html = marked.parse(normalized, { async: false })
    html = String(html || '')
    return html
      .replace(/<table>/g, '<div class="table-wrapper"><table>')
      .replace(/<\/table>/g, '</table></div>')
  } catch (e) {
    console.error('Markdown render error:', e, 'Text:', String(text).substring(0, 200))
    return escapeHtml(text)
  }
}

function escapeHtml(text) {
  return String(text)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
}
