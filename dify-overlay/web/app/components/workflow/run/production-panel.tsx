'use client'

import { useEffect, useRef, useState } from 'react'

type Props = {
  url: string
  title: string
  actions: { id: string }[]
  onAction: (action: string) => Promise<void>
  onStatusChange?: (status: string) => void
}

const ProductionPanel = ({ url, title, actions, onAction, onStatusChange }: Props) => {
  const frameRef = useRef<HTMLIFrameElement>(null)
  const busyRef = useRef(false)
  const [channel] = useState(() => crypto.randomUUID())
  const [height, setHeight] = useState(380)

  useEffect(() => {
    const origin = new URL(url).origin
    const receive = (event: MessageEvent) => {
      if (
        event.origin !== origin ||
        event.source !== frameRef.current?.contentWindow ||
        event.data?.channel !== channel
      )
        return
      if (event.data.type === 'production-state') {
        const nextHeight = Number(event.data.height)
        if (Number.isFinite(nextHeight)) setHeight(Math.max(220, Math.min(900, nextHeight)))
        if (typeof event.data.status === 'string') onStatusChange?.(event.data.status)
        return
      }
      if (event.data.type !== 'production-action' || busyRef.current) return
      const action = event.data.action
      if (typeof action !== 'string' || !actions.some((item) => item.id === action)) return
      busyRef.current = true
      void onAction(action).then(
        () =>
          frameRef.current?.contentWindow?.postMessage(
            { channel, type: 'production-ack', ok: true },
            origin,
          ),
        (cause) => {
          busyRef.current = false
          frameRef.current?.contentWindow?.postMessage(
            {
              channel,
              type: 'production-ack',
              ok: false,
              error: cause instanceof Error ? cause.message : String(cause),
            },
            origin,
          )
        },
      )
    }
    window.addEventListener('message', receive)
    return () => window.removeEventListener('message', receive)
  }, [url, channel, actions, onAction, onStatusChange])

  /* oxlint-disable eslint-react/dom-no-unsafe-iframe-sandbox -- Only the fixed 8794 renderer is embedded; it is cross-origin from Dify on 8788 and cannot remove the parent's sandbox. */
  return (
    <iframe
      ref={frameRef}
      title={title}
      src={`${url}?channel=${encodeURIComponent(channel)}`}
      className="w-full border-0"
      style={{ height }}
      sandbox="allow-scripts allow-same-origin allow-downloads"
    />
  )
  /* oxlint-enable eslint-react/dom-no-unsafe-iframe-sandbox */
}

export default ProductionPanel
