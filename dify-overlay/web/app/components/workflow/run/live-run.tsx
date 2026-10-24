'use client'

import type { Edge, Node, WorkflowDataUpdater } from '../types'
import type { NodeTracing } from '@/types/workflow'
import { skipToken, useQuery } from '@tanstack/react-query'
import { useEffect, useMemo, useRef, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { useReactFlow, useStoreApi } from 'reactflow'
import Loading from '@/app/components/base/loading'
import { consoleQuery } from '@/service/console'
import { NodeRunningStatus } from '../types'
import { activeExecution, latestExecutions, productionExecutions } from './live-nodes'
import { isLiveRun, liveRunOptions } from './live-query'
import { viewportForNode } from './live-viewport'
import OutputPanel from './output-panel'
import ReviewDialog from './review-dialog'
import StageRecovery from './stage-recovery'
import StoryboardProgress from './storyboard-progress'
import TracingPanel from './tracing-panel'

type Props = {
  appId: string
  runId: string
  onGraphLoaded?: (graph: WorkflowDataUpdater) => void
}
const EMPTY_TRACES: NodeTracing[] = []

const LiveRun = ({ appId, runId, onGraphLoaded }: Props) => {
  const { t } = useTranslation()
  const canvas = useReactFlow()
  const canvasStore = useStoreApi()
  const loadedGraphRef = useRef('')
  const followedNodeRef = useRef('')
  const panelRef = useRef<HTMLDivElement>(null)
  const [submittedForm, setSubmittedForm] = useState('')
  const [productionStatus, setProductionStatus] = useState('')
  const run = useQuery(liveRunOptions(appId, runId))
  const status = run.data?.status
  const trace = useQuery(
    consoleQuery.apps.byAppId.workflowRuns.byRunId.nodeExecutions.get.queryOptions({
      input: { params: { app_id: appId, run_id: runId } },
      refetchInterval: (query) =>
        isLiveRun(status) || query.state.dataUpdatedAt < run.dataUpdatedAt ? 2000 : false,
      refetchOnWindowFocus: 'always',
      retry: false,
    }),
  )
  const pause = useQuery(
    consoleQuery.workflow.byWorkflowRunId.pauseDetails.get.queryOptions({
      input: status === 'paused' ? { params: { workflow_run_id: runId } } : skipToken,
      refetchInterval: status === 'paused' ? 2000 : false,
      refetchOnWindowFocus: 'always',
      retry: false,
    }),
  )
  // 节点追踪组件沿用既有接口，后端执行记录保持原样。
  const rawNodes = (trace.data?.data || EMPTY_TRACES) as NodeTracing[]
  const active = activeExecution(rawNodes)
  const pending = status === 'paused' ? pause.data?.paused_nodes?.[0] : undefined
  const formUrl = pending?.pause_type.backstage_input_url
  const formToken = formUrl?.split('/form/')[1]?.split(/[?#]/)[0]
  const waitingAfterSubmit = !!formToken && formToken === submittedForm
  const currentId = pending?.node_id || active?.node_id
  const currentTitle = pending?.node_title || active?.title || ''
  const isProduction = pending?.node_id === 'production_review'
  const isStoryboardWait = pending?.node_id === 'storyboard_wait'
  const networkWaitingMessage = t(($) => $['liveProgress.connectionLost'], { ns: 'workflow' })
  const productionRunning =
    (isProduction && ['armed', 'running', 'complete'].includes(productionStatus)) ||
    (isStoryboardWait && ['starting', 'queued', 'running', 'complete'].includes(productionStatus))
  const nodes = useMemo(
    () =>
      productionExecutions(
        rawNodes,
        pending?.node_id,
        isStoryboardWait || isProduction ? productionStatus : 'paused',
        networkWaitingMessage,
      ),
    [
      rawNodes,
      isStoryboardWait,
      isProduction,
      pending?.node_id,
      productionStatus,
      networkWaitingMessage,
    ],
  )
  const description = canvas.getNode(currentId || '')?.data.desc
  const courseOutput = rawNodes.find((node) => node.node_id === 'create_data')?.outputs
  const savedCourse =
    courseOutput &&
    typeof courseOutput === 'object' &&
    'course_id' in courseOutput &&
    typeof courseOutput.course_id === 'string'
      ? courseOutput.course_id
      : undefined

  // 服务端快照只初始化一次画布，之后同步运行状态，不重置缩放或拖动位置。
  useEffect(() => {
    const graph = run.data?.graph
    if (!graph || typeof graph !== 'object' || loadedGraphRef.current === runId || !onGraphLoaded)
      return
    if (
      !('nodes' in graph) ||
      !('edges' in graph) ||
      !Array.isArray(graph.nodes) ||
      !Array.isArray(graph.edges)
    )
      return
    // 已缓存的记录可能在父画布订阅前挂载，下一拍再交付节点图。
    const timer = window.setTimeout(() => {
      onGraphLoaded({
        nodes: graph.nodes as Node[],
        edges: graph.edges as Edge[],
        viewport: canvas.getViewport(),
      })
      loadedGraphRef.current = runId
    }, 0)
    return () => window.clearTimeout(timer)
  }, [run.data?.graph, runId, onGraphLoaded, canvas])

  useEffect(() => {
    const executions = latestExecutions(nodes)
    const { getNodes, setNodes } = canvasStore.getState()
    let changed = false
    const next = getNodes().map((node) => {
      const execution = executions.get(node.id)
      const nextStatus =
        pending?.node_id === node.id && !isStoryboardWait
          ? productionRunning
            ? NodeRunningStatus.Running
            : NodeRunningStatus.Paused
          : ((execution?.status as NodeRunningStatus | undefined) ?? NodeRunningStatus.NotStart)
      if (node.data._runningStatus === nextStatus && !node.data._waitingRun) return node
      changed = true
      return { ...node, data: { ...node.data, _runningStatus: nextStatus, _waitingRun: false } }
    })
    if (changed) setNodes(next)
  }, [
    nodes,
    trace.dataUpdatedAt,
    pending?.node_id,
    canvasStore,
    productionRunning,
    isStoryboardWait,
  ])

  // 每次换节点才移动一次；同一节点的轮询和手动拖动不会反复拉回画布。
  useEffect(() => {
    if (!currentId || !isLiveRun(status)) return
    const key = `${runId}:${currentId}`
    if (followedNodeRef.current === key) return
    const timer = window.setTimeout(() => {
      const state = canvasStore.getState()
      const bounds = state.domNode?.getBoundingClientRect()
      const panel = panelRef.current?.getBoundingClientRect()
      const inset = bounds && panel ? Math.max(0, bounds.right - panel.left) : 0
      const viewport = viewportForNode(
        currentId,
        state.getNodes(),
        state.width,
        state.height,
        inset,
      )
      if (!viewport) return
      followedNodeRef.current = key
      void canvas.setViewport(viewport, {
        duration: window.matchMedia('(prefers-reduced-motion: reduce)').matches ? 0 : 600,
      })
    }, 180)
    return () => window.clearTimeout(timer)
  }, [currentId, status, runId, trace.dataUpdatedAt, canvas, canvasStore])

  const refresh = () => {
    void run.refetch({ cancelRefetch: false })
    void trace.refetch({ cancelRefetch: false })
    void pause.refetch({ cancelRefetch: false })
  }
  const message = waitingAfterSubmit
    ? t(($) => $['liveProgress.submitted'], { ns: 'workflow' })
    : productionRunning
      ? t(($) => $['liveProgress.running'], { ns: 'workflow', node: currentTitle.split(' · ')[0] })
      : isStoryboardWait
        ? productionStatus === 'network_wait'
          ? networkWaitingMessage
          : currentTitle
        : status === 'paused'
          ? t(($) => $['liveProgress.paused'], { ns: 'workflow', node: currentTitle })
          : status === 'running'
            ? t(($) => $['liveProgress.running'], { ns: 'workflow', node: currentTitle })
            : status === 'succeeded'
              ? t(($) => $['common.workflowProcessSucceeded'], { ns: 'workflow' })
              : status === 'failed' || status === 'stopped'
                ? t(($) => $['common.workflowProcessFailed'], { ns: 'workflow' })
                : t(($) => $.loading, { ns: 'common' })

  return (
    <div ref={panelRef} className="flex min-h-0 grow flex-col">
      <section
        aria-live="polite"
        className="m-3 rounded-xl border border-components-panel-border bg-background-section p-3"
      >
        <p role="status" className="system-sm-semibold text-text-primary">
          {message}
        </p>
        {description && !isProduction && (
          <p className="mt-1 system-sm-regular text-text-secondary">{description}</p>
        )}
        {(run.isError || trace.isError) && (
          <p role="alert" className="mt-1 text-text-destructive">
            {t(($) => $['liveProgress.connectionLost'], { ns: 'workflow' })}
          </p>
        )}
        <div className="mt-3 w-full">
          {!isProduction &&
            !isStoryboardWait &&
            rawNodes.some((node) => node.node_id === 'create') && (
              <StageRecovery
                key={runId}
                appId={appId}
                runId={runId}
                runStatus={status}
                runError={run.data?.error}
                savedCourse={savedCourse}
              />
            )}
          <StoryboardProgress nodes={nodes} title={currentTitle} runId={runId} />
          {(formToken || submittedForm) && (
            <ReviewDialog
              key={formToken || submittedForm}
              token={formToken || submittedForm}
              title={pending?.node_title || currentTitle}
              onProductionStatus={setProductionStatus}
              onSubmitted={() => {
                setSubmittedForm(formToken || submittedForm)
                refresh()
              }}
            />
          )}
        </div>
      </section>
      <div className="min-h-0 grow overflow-y-auto">
        {run.isLoading && <Loading />}
        {!isLiveRun(status) && run.data && (
          <OutputPanel
            outputs={run.data.outputs}
            error={run.data.error || undefined}
            height={600}
          />
        )}
        <TracingPanel list={nodes} className="bg-background-section-burn" />
      </div>
    </div>
  )
}

export default LiveRun
