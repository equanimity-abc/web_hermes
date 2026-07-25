import { ref } from 'vue'
import { copyText } from '@/utils/clipboard'

export function useClipboardToast() {
  const toast = ref('')
  let timer = null

  function showToast(message = '✓ 已复制', duration = 2000) {
    toast.value = message
    if (timer) clearTimeout(timer)
    timer = setTimeout(() => {
      toast.value = ''
      timer = null
    }, duration)
  }

  async function copyWithToast(text) {
    const ok = await copyText(text)
    if (ok) showToast()
    return ok
  }

  return {
    toast,
    showToast,
    copyWithToast,
  }
}
