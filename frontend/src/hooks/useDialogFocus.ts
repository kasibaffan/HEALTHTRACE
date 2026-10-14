import { useEffect, useRef } from 'react'

/** Moves focus into the dialog, keeps Tab inside it, and restores focus to the opener on close. */
export function useDialogFocus<T extends HTMLElement>() {
  const ref = useRef<T>(null)

  useEffect(() => {
    const opener = document.activeElement as HTMLElement | null
    const node = ref.current
    node?.focus()

    const onKey = (e: KeyboardEvent) => {
      if (e.key !== 'Tab' || !node) return
      const items = node.querySelectorAll<HTMLElement>('button:not(:disabled), [href], input:not(:disabled), textarea:not(:disabled), select, [tabindex]:not([tabindex="-1"])')
      if (!items.length) return
      const first = items[0]
      const last = items[items.length - 1]
      if (e.shiftKey && (document.activeElement === first || document.activeElement === node)) { e.preventDefault(); last.focus() }
      else if (!e.shiftKey && document.activeElement === last) { e.preventDefault(); first.focus() }
    }
    document.addEventListener('keydown', onKey)
    return () => {
      document.removeEventListener('keydown', onKey)
      opener?.focus?.()
    }
  }, [])

  return ref
}
