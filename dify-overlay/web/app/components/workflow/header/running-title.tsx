import type { WorkflowRunningStatus } from '../types'
import { useQuery } from '@tanstack/react-query'
import { memo } from 'react'
import { useTranslation } from 'react-i18next'
import { useIsChatMode } from '../hooks/use-workflow'
import { liveRunOptions } from '../run/live-query'
import { useStore } from '../store'
import { formatWorkflowRunIdentifier } from '../utils'

const RunningTitle = () => {
  const { t } = useTranslation()
  const isChatMode = useIsChatMode()
  const historyWorkflowData = useStore((s) => s.historyWorkflowData)
  const appId = useStore((s) => s.appId)
  const live = useQuery(liveRunOptions(isChatMode ? undefined : appId, historyWorkflowData?.id))
  const displayed = live.data || historyWorkflowData

  return (
    <div className="flex h-4.5 items-center text-xs text-gray-500">
      <span
        aria-hidden
        className="mr-1 i-custom-vender-line-time-clock-play size-3 text-gray-500"
      />
      <span>
        {isChatMode
          ? `Test Chat${formatWorkflowRunIdentifier(historyWorkflowData?.finished_at)}`
          : `Test Run${formatWorkflowRunIdentifier(displayed?.finished_at || undefined, displayed?.status as WorkflowRunningStatus)}`}
      </span>
      <span className="mx-1">·</span>
      <span className="ml-1 flex h-4.5 items-center rounded-[5px] border border-indigo-300 bg-white/48 px-1 text-2xs font-semibold text-indigo-600 uppercase">
        {t(($) => $['common.viewOnly'], { ns: 'workflow' })}
      </span>
    </div>
  )
}

export default memo(RunningTitle)
