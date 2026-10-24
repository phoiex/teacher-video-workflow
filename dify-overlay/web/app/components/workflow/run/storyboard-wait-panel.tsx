'use client'

import { useRef, useState } from 'react'
import ProductionPanel from './production-panel'

type Props = {
  url: string
  title: string
  onReady?: () => Promise<void>
  onStatusChange?: (status: string) => void
}

const NO_ACTIONS: { id: string }[] = []
const ignoreAction = async () => {}

const StoryboardWaitPanel = ({ url, title, onReady, onStatusChange }: Props) => {
  const submittedRef = useRef(false)
  const [error, setError] = useState('')
  return (
    <>
      <ProductionPanel
        url={url}
        title={title}
        actions={NO_ACTIONS}
        onAction={ignoreAction}
        onStatusChange={(status) => {
          onStatusChange?.(status)
          if (!onReady || submittedRef.current || !['complete', 'paused'].includes(status)) return
          submittedRef.current = true
          setError('')
          void onReady().catch((cause) => {
            submittedRef.current = false
            setError(cause instanceof Error ? cause.message : String(cause))
          })
        }}
      />
      {error && (
        <p role="alert" className="mt-1 text-text-destructive">
          {error}
        </p>
      )}
    </>
  )
}

export default StoryboardWaitPanel
