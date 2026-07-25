/**
 * Copy text to clipboard with Clipboard API + textarea fallback.
 * @returns {Promise<boolean>} whether copy succeeded
 */
export async function copyText(text) {
  try {
    await navigator.clipboard.writeText(text)
    return true
  } catch {
    try {
      const ta = document.createElement('textarea')
      ta.value = text
      ta.style.position = 'fixed'
      ta.style.left = '-9999px'
      document.body.appendChild(ta)
      ta.select()
      document.execCommand('copy')
      document.body.removeChild(ta)
      return true
    } catch {
      console.error('复制失败')
      return false
    }
  }
}
