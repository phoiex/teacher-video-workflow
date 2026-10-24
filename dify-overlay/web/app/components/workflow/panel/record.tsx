import type { WorkflowDataUpdater } from '../types'
import type { WorkflowRunDetailResponse } from '@/models/log'
import { memo, useCallback } from 'react'
import { useTranslation } from 'react-i18next'
import { useHooksStore } from '../hooks-store'
import { useWorkflowUpdate } from '../hooks/use-workflow-update'
import Run from '../run'
import LiveRun from '../run/live-run'
import { useStore } from '../store'
import { formatWorkflowRunIdentifier } from '../utils'

const Record = () => {
  const { t } = useTranslation()
  const historyWorkflowData = useStore((s) => s.historyWorkflowData)
  const { handleUpdateWorkflowCanvas } = useWorkflowUpdate()
  const getWorkflowRunAndTraceUrl = useHooksStore((s) => s.getWorkflowRunAndTraceUrl)

  const handleResultCallback = useCallback(
    (res: WorkflowRunDetailResponse) => {
      const graph = res.graph
      handleUpdateWorkflowCanvas({
        nodes: graph.nodes,
        edges: graph.edges,
        viewport: graph.viewport || { x: 0, y: 0, zoom: 1 },
      })
    },
    [handleUpdateWorkflowCanvas],
  )
  const handleGraphLoaded = useCallback(
    (graph: WorkflowDataUpdater) => {
      handleUpdateWorkflowCanvas(graph)
    },
    [handleUpdateWorkflowCanvas],
  )
  const urls = getWorkflowRunAndTraceUrl(historyWorkflowData?.id)
  const liveMatch = urls.runUrl?.match(/\/apps\/([^/]+)\/workflow-runs\/([^/?]+)$/)

  return (
    <div className="flex h-full w-100 flex-col rounded-l-2xl border-[0.5px] border-components-panel-border bg-components-panel-bg shadow-xl">
      <div className="flex items-center justify-between p-4 pb-0 system-xl-semibold text-text-primary">
        {liveMatch
          ? t(($) => $['common.workflowProcess'], { ns: 'workflow' })
          : `Test Run${formatWorkflowRunIdentifier(historyWorkflowData?.finished_at)}`}
      </div>
      {liveMatch?.[1] && liveMatch[2] ? (
        <LiveRun
          key={liveMatch[2]}
          appId={liveMatch[1]}
          runId={liveMatch[2]}
          onGraphLoaded={handleGraphLoaded}
        />
      ) : (
        <Run
          runDetailUrl={urls.runUrl}
          tracingListUrl={urls.traceUrl}
          getResultCallback={handleResultCallback}
        />
      )}
    </div>
  )
}

export default memo(Record)
