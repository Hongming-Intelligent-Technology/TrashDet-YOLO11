import { cloneElement, useEffect, useRef, useState, type ReactElement } from 'react'

interface CssTransitionProps {
  /** Class prefix, e.g. "fade" -> fade-enter-from / fade-enter-active / fade-enter-to (and leave-*). */
  name: string
  show: boolean
  /** Must match the CSS transition duration. */
  durationMs: number
  children: ReactElement<{ className?: string }>
}

type Phase = 'enter-from' | 'enter-to' | 'idle' | 'leave-from' | 'leave-to' | 'hidden'

/**
 * Minimal equivalent of Vue's <transition>: applies the same enter/leave classes,
 * so existing transition CSS keeps working, and unmounts the child after leaving.
 */
export default function CssTransition({ name, show, durationMs, children }: CssTransitionProps) {
  const [phase, setPhase] = useState<Phase>(show ? 'idle' : 'hidden')
  const timers = useRef<number[]>([])

  useEffect(() => {
    timers.current.forEach((id) => window.clearTimeout(id))
    timers.current = []
    const later = (fn: () => void, ms: number) => timers.current.push(window.setTimeout(fn, ms))

    if (show) {
      setPhase('enter-from')
      later(() => setPhase('enter-to'), 20)
      later(() => setPhase('idle'), 20 + durationMs)
    } else {
      setPhase((current) => (current === 'hidden' ? 'hidden' : 'leave-from'))
      later(() => setPhase((current) => (current === 'hidden' ? 'hidden' : 'leave-to')), 20)
      later(() => setPhase('hidden'), 20 + durationMs)
    }
    return () => timers.current.forEach((id) => window.clearTimeout(id))
  }, [show, durationMs])

  if (phase === 'hidden') {
    return null
  }

  const phaseClasses: Record<Exclude<Phase, 'hidden'>, string> = {
    'enter-from': `${name}-enter-from ${name}-enter-active`,
    'enter-to': `${name}-enter-active ${name}-enter-to`,
    idle: '',
    'leave-from': `${name}-leave-from ${name}-leave-active`,
    'leave-to': `${name}-leave-active ${name}-leave-to`,
  }
  const extra = phaseClasses[phase]
  const className = [children.props.className, extra].filter(Boolean).join(' ')
  return cloneElement(children, { className })
}
