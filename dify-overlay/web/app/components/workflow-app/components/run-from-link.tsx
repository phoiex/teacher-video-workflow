'use client'

import { useQuery } from '@tanstack/react-query'
import { useEffect, useRef } from 'react'
import { useStore as useAppStore } from '@/app/components/app/store'
import { useHooksStore } from '@/app/components/workflow/hooks-store'
import { liveRunOptions } from '@/app/components/workflow/run/live-query'
import { useStore, useWorkflowStore } from '@/app/components/workflow/store'
import { ControlMode } from '@/app/components/workflow/types'
import { usePathname, useRouter, useSearchParams } from '@/next/navigation'

// 在原生编辑器中查看已有运行；只读取记录，不重新执行工作流。
export default function RunFromLink() {
  const appId = useAppStore((s) => s.appDetail?.id)
  const params = useSearchParams()
  const router = useRouter()
  const pathname = usePathname()
  const requested = params.get('run_id')
  const runId = requested && /^[0-9a-f-]{36}$/i.test(requested) ? requested : undefined
  const run = useQuery(liveRunOptions(appId, runId))
  const store = useWorkflowStore()
  const currentRunId = useStore(
    (s) => s.historyWorkflowData?.id || s.workflowRunningData?.result.id,
  )
  const handleBackupDraft = useHooksStore((s) => s.handleBackupDraft)
  const attachedRef = useRef('')
  useEffect(() => {
    if (!appId || !currentRunId || currentRunId === requested) return
    if (requested && attachedRef.current !== `${appId}:${requested}`) return
    const next = new URLSearchParams(params.toString())
    next.set('run_id', currentRunId)
    router.replace(`${pathname}?${next}`, { scroll: false })
  }, [appId, currentRunId, requested, params, router, pathname])
  useEffect(() => {
    if (!appId || !runId || !run.data?.status) return
    const key = `${appId}:${runId}`
    const current = store.getState()
    if (attachedRef.current === key && current.historyWorkflowData?.id !== runId) return
    const first = attachedRef.current !== key
    attachedRef.current = key
    // 新启动的原生测试继续用现有预览；从链接重开时使用原生运行记录视图。
    if (first && current.workflowRunningData?.result.id === runId) return
    if (first) handleBackupDraft()
    store.setState({
      historyWorkflowData: {
        id: runId,
        status: run.data.status,
        finished_at: run.data.finished_at ?? undefined,
      },
      ...(first
        ? {
            showInputsPanel: false,
            showDebugAndPreviewPanel: false,
            showEnvPanel: false,
            controlMode: ControlMode.Hand,
          }
        : {}),
    })
  }, [appId, runId, run.data, store, handleBackupDraft])
  return null
}
