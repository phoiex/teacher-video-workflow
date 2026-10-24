'use client'

import { Button } from '@langgenius/dify-ui/button'
import { queryOptions, useQuery } from '@tanstack/react-query'
import { useRef, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { useRouter } from '@/next/navigation'
import { retryPublishedWorkflow } from '@/service/share'
import { retrySavedWorkflow } from '@/service/workflow'

// 本机制作工具的进度协议，与 Dify Console 的运行记录分开读取。
type StageState = {
  status: string
  course_id?: string | null
  title?: string
  message?: string
  retryable?: boolean
}

const StageRecovery = ({
  appId,
  runId,
  runStatus,
  runError,
  publicApp = false,
  onResumed,
}: {
  appId: string
  runId: string
  runStatus?: string | null
  runError?: string | null
  savedCourse?: string
  publicApp?: boolean
  onResumed?: (runId: string) => void
}) => {
  const { t } = useTranslation()
  const router = useRouter()
  const busyRef = useRef(false)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const failed = runStatus === 'failed' || runStatus === 'stopped'
  const stage = useQuery(
    queryOptions({
      queryKey: ['teacher-stage', runId],
      queryFn: async (): Promise<StageState> => {
        const response = await fetch(
          `http://127.0.0.1:8794/stage-status/${encodeURIComponent(runId)}`,
          { cache: 'no-store' },
        )
        if (!response.ok) throw new Error('stage unavailable')
        return response.json()
      },
      refetchInterval: runStatus === 'running' ? 2000 : false,
      refetchOnWindowFocus: 'always',
      refetchOnReconnect: 'always',
      retry: 2,
    }),
  )
  const networkError =
    /timeout|timed out|connection|connect error|network|502|503|504|429|网络|连接中断/i.test(
      runError || '',
    )
  const retryable = failed && (stage.data?.retryable === true || networkError || stage.isError)
  if (!retryable && stage.data?.status !== 'retrying') return null

  const retry = () => {
    if (busyRef.current) return
    busyRef.current = true
    setBusy(true)
    setError('')
    void (publicApp ? retryPublishedWorkflow(runId) : retrySavedWorkflow(appId, runId))
      .then((nextRunId) => {
        if (!/^[a-f0-9-]{36}$/.test(nextRunId)) throw new Error('Invalid recovery response')
        if (onResumed) onResumed(nextRunId)
        else router.replace(`/app/${appId}/workflow?run_id=${nextRunId}`)
      })
      .catch((cause: unknown) => {
        busyRef.current = false
        setBusy(false)
        setError(
          cause instanceof Error
            ? cause.message
            : t(($) => $['liveProgress.connectionLost'], { ns: 'workflow' }),
        )
      })
  }

  return (
    <div className="mb-3 rounded-xl border border-components-panel-border bg-background-default p-3">
      <p role="status" className="system-sm-regular text-text-secondary">
        {busy
          ? t(($) => $['nodes.common.retry.retrying'], { ns: 'workflow' })
          : stage.data?.message || t(($) => $['liveProgress.retryAvailable'], { ns: 'workflow' })}
      </p>
      {retryable && (
        <Button className="mt-3" loading={busy} onClick={retry}>
          {t(($) => $['liveProgress.retrySaved'], { ns: 'workflow' })}
        </Button>
      )}
      {error && (
        <p role="alert" className="mt-2 text-text-destructive">
          {error}
        </p>
      )}
    </div>
  )
}

export default StageRecovery
