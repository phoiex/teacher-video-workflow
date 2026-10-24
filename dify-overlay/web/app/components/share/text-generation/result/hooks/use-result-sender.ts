import type { TextGenerationTranslate } from '../../types'
import type { ResultInputValue } from '../result-request'
import type { ResultRunStateController } from './use-result-run-state'
import type { PromptConfig } from '@/models/debug'
import type { VisionFile, VisionSettings } from '@/types/app'
import { useCallback, useEffect, useRef } from 'react'
import { trackWebAppEvent } from '@/app/components/base/amplitude/web-app-event'
import { WorkflowRunningStatus } from '@/app/components/workflow/types'
import { TEXT_GENERATION_TIMEOUT_MS } from '@/config'
import { useWebAppStore } from '@/context/web-app-context'
import { AppSourceType, sendCompletionMessage, sendWorkflowMessage } from '@/service/share'
import { sleep } from '@/utils'
import { buildResultRequestData, validateResultRequest } from '../result-request'
import { subscribeWorkflowEvents } from '../workflow-event-subscription'
import { createWorkflowStreamHandlers } from '../workflow-stream-handlers'

type Notify = (payload: { type: 'error' | 'info' | 'warning'; message: string }) => void
type UseResultSenderOptions = {
  resumeRunId?: string
  appId?: string
  appSourceType: AppSourceType
  completionFiles: VisionFile[]
  controlRetry?: number
  controlSend?: number
  inputs: Record<string, ResultInputValue>
  isCallBatchAPI: boolean
  isPC: boolean
  isWorkflow: boolean
  notify: Notify
  onCompleted: (completionRes: string, taskId?: number, success?: boolean) => void
  onRunStart: () => void
  onShowRes: () => void
  promptConfig: PromptConfig | null
  runState: ResultRunStateController
  t: TextGenerationTranslate
  taskId?: number
  visionConfig: VisionSettings
}

export const useResultSender = ({
  resumeRunId,
  appId,
  appSourceType,
  completionFiles,
  controlRetry,
  controlSend,
  inputs,
  isCallBatchAPI,
  isPC,
  isWorkflow,
  notify,
  onCompleted,
  onRunStart,
  onShowRes,
  promptConfig,
  runState,
  t,
  taskId,
  visionConfig,
}: UseResultSenderOptions) => {
  const { clearMoreLikeThis } = runState
  const appMode = useWebAppStore((state) => state.appInfo?.mode)

  const handleSend = useCallback(async () => {
    if (runState.isResponding) {
      notify({
        type: 'info',
        message: t(($) => $['errorMessage.waitForResponse'], { ns: 'appDebug' }),
      })
      return false
    }

    const validation = validateResultRequest({
      completionFiles,
      inputs,
      isCallBatchAPI,
      promptConfig,
      t,
    })
    if (!validation.canSend) {
      notify(validation.notification!)
      return false
    }

    const data = buildResultRequestData({
      completionFiles,
      inputs,
      promptConfig,
      visionConfig,
    })

    runState.prepareForNewRun()

    if (!isPC) onShowRes()
    onRunStart()

    runState.setRespondingTrue()

    if (appSourceType === AppSourceType.webApp && appMode)
      trackWebAppEvent('webapp_run', { app_mode: appMode })

    let isEnd = false
    let isTimeout = false
    let completionChunks: string[] = []
    let tempMessageId = ''

    if (isWorkflow) {
      const otherOptions = createWorkflowStreamHandlers({
        getCompletionRes: runState.getCompletionRes,
        getWorkflowProcessData: runState.getWorkflowProcessData,
        isPublicAPI: appSourceType === AppSourceType.webApp,
        isTimedOut: () => isTimeout,
        markEnded: () => {
          isEnd = true
        },
        notify,
        onCompleted,
        resetRunState: runState.resetRunState,
        setCompletionRes: runState.setCompletionRes,
        setCurrentTaskId: runState.setCurrentTaskId,
        setIsStopping: runState.setIsStopping,
        setMessageId: runState.setMessageId,
        setRespondingFalse: runState.setRespondingFalse,
        setWorkflowProcessData: runState.setWorkflowProcessData,
        setAbortController: (controller) => {
          runState.abortControllerRef.current = controller
        },
        t,
        taskId,
      })

      void sendWorkflowMessage(data, otherOptions, appSourceType, appId).catch((error) => {
        otherOptions.onError?.(error instanceof Error ? error.message : String(error))
      })
      return true
    }

    // 工作流可以等待人工审核，结束状态由工作流事件决定。
    void (async () => {
      await sleep(TEXT_GENERATION_TIMEOUT_MS)
      if (!isEnd) {
        runState.setRespondingFalse()
        onCompleted(runState.getCompletionRes(), taskId, false)
        runState.resetRunState()
        isTimeout = true
      }
    })()

    void sendCompletionMessage(
      data,
      {
        onData: (chunk, _isFirstMessage, { messageId, taskId: nextTaskId }) => {
          tempMessageId = messageId
          if (nextTaskId && nextTaskId.trim() !== '')
            runState.setCurrentTaskId((prev) => prev ?? nextTaskId)

          completionChunks.push(chunk)
          runState.setCompletionRes(completionChunks.join(''))
        },
        onCompleted: () => {
          if (isTimeout) {
            notify({
              type: 'warning',
              message: t(($) => $['warningMessage.timeoutExceeded'], { ns: 'appDebug' }),
            })
            return
          }

          runState.setRespondingFalse()
          runState.resetRunState()
          runState.setMessageId(tempMessageId)
          onCompleted(runState.getCompletionRes(), taskId, true)
          isEnd = true
        },
        onMessageReplace: (messageReplace) => {
          completionChunks = [messageReplace.answer]
          runState.setCompletionRes(completionChunks.join(''))
        },
        onError: () => {
          if (isTimeout) {
            notify({
              type: 'warning',
              message: t(($) => $['warningMessage.timeoutExceeded'], { ns: 'appDebug' }),
            })
            return
          }

          runState.setRespondingFalse()
          runState.resetRunState()
          onCompleted(runState.getCompletionRes(), taskId, false)
          isEnd = true
        },
        getAbortController: (abortController) => {
          runState.abortControllerRef.current = abortController
        },
      },
      appSourceType,
      appId,
    )

    return true
  }, [
    appId,
    appMode,
    appSourceType,
    completionFiles,
    inputs,
    isCallBatchAPI,
    isPC,
    isWorkflow,
    notify,
    onCompleted,
    onRunStart,
    onShowRes,
    promptConfig,
    runState,
    t,
    taskId,
    visionConfig,
  ])

  const handleSendRef = useRef(handleSend)
  const reconnectRef = useRef<(id: string) => void>(() => {})

  useEffect(() => {
    reconnectRef.current = (id: string) => {
      runState.abortControllerRef.current?.abort()
      const previous = runState.getWorkflowProcessData()
      if (previous?.runId !== id) runState.prepareForNewRun()
      runState.setWorkflowProcessData({
        ...(previous?.runId === id ? previous : {}),
        runId: id,
        status: WorkflowRunningStatus.Running,
        tracing: previous?.runId === id ? previous.tracing : [],
        expand: true,
      })
      runState.setRespondingTrue()
      onRunStart()
      const handlers = createWorkflowStreamHandlers({
        isResumeStream: true,
        getCompletionRes: runState.getCompletionRes,
        getWorkflowProcessData: runState.getWorkflowProcessData,
        isPublicAPI: appSourceType === AppSourceType.webApp,
        isTimedOut: () => false,
        markEnded: () => {},
        notify,
        onCompleted,
        resetRunState: runState.resetRunState,
        setCompletionRes: runState.setCompletionRes,
        setCurrentTaskId: runState.setCurrentTaskId,
        setIsStopping: runState.setIsStopping,
        setMessageId: runState.setMessageId,
        setRespondingFalse: runState.setRespondingFalse,
        setWorkflowProcessData: runState.setWorkflowProcessData,
        t,
        taskId,
      })
      // 这里只读取已有执行的事件，不创建任务或提交审核。
      subscribeWorkflowEvents(id, {
        ...handlers,
        getAbortController: (controller) => {
          runState.abortControllerRef.current = controller
        },
      })
    }
  }, [appSourceType, notify, onCompleted, onRunStart, runState, t, taskId])

  useEffect(() => {
    if (resumeRunId) reconnectRef.current(resumeRunId)
  }, [resumeRunId])

  useEffect(() => {
    handleSendRef.current = handleSend
  }, [handleSend])

  useEffect(() => {
    if (!controlSend) return

    void handleSendRef.current()
    clearMoreLikeThis()
  }, [clearMoreLikeThis, controlSend])

  useEffect(() => {
    if (!controlRetry) return

    void handleSendRef.current()
  }, [controlRetry])

  return {
    handleSend,
    handleResume: (id: string) => reconnectRef.current(id),
  }
}
