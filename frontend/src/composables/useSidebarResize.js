import { ref } from 'vue'

const MIN = 200
const MAX = 500
const DEFAULT = 325

export function useSidebarResize(initialWidth = DEFAULT) {
  const sidebarWidth = ref(initialWidth)

  function startResize(e) {
    e.preventDefault()
    const startX = e.clientX
    const startWidth = sidebarWidth.value

    const onMouseMove = (ev) => {
      const delta = ev.clientX - startX
      sidebarWidth.value = Math.max(MIN, Math.min(MAX, startWidth + delta))
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
  }

  return {
    sidebarWidth,
    startResize,
  }
}
