import { marked } from 'marked'

const codeBlockCounter = { count: 0 }

marked.use({
  renderer: {
    code({ text, lang }) {
      const id = 'code-' + codeBlockCounter.count++
      const safeLang = (lang || '').replace(/[<>"']/g, '')
      const label = safeLang || 'code'
      const langLabel = `<div class="code-lang"><span>${label}</span><button class="code-copy-btn" data-code="${id}" title="复制代码"><svg width="14" height="14" viewBox="0 0 14 14" fill="none"><rect x="3" y="3" width="8" height="8" rx="1" stroke="currentColor" stroke-width="1.2"/><path d="M5 1h7a1 1 0 011 1v7" stroke="currentColor" stroke-width="1.2" stroke-linecap="round"/></svg></button></div>`
      return `<pre class="code-block" data-code-container="${id}">${langLabel}<code id="${id}">${text}</code></pre>`
    },
  },
})

marked.setOptions({
  gfm: true,
  breaks: false,
})

/**
 * Render markdown to HTML (sync). Safe for v-html in Vue.
 */
export function renderMarkdown(text) {
  if (!text) return ''
  try {
    let html = marked.parse(text, { async: false })
    html = String(html || '')
    return html
      .replace(/<table>/g, '<div class="table-wrapper"><table>')
      .replace(/<\/table>/g, '</table></div>')
  } catch (e) {
    console.error('Markdown render error:', e, 'Text:', text.substring(0, 200))
    return text
  }
}
