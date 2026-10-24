import type { Dispatch, SetStateAction } from 'react'
import type { TextGenerationTranslate } from '../types'
import type { WorkflowProcess } from '@/app/components/base/chat/types'
import type { IOtherOptions } from '@/service/base'
import type {
  HumanInputFormTimeoutData,
  NodeTracing,
  WorkflowFinishedResponse,
} from '@/types/workflow'
import { produce } from 'immer'
import { enrichSubmittedHumanInputFormData } from '@/app/components/base/chat/chat/answer/human-input-content/submitted-utils'
import { getFilesInLogs } from '@/app/components/base/file-uploader/utils'
import { NodeRunningStatus, WorkflowRunningStatus } from '@/app/components/workflow/types'
import { subscribeWorkflowEvents } from './workflow-event-subscription'

type Notify = (payload: { type: 'error' | 'warning'; message: string }) => void
type CreateWorkflowStreamHandlersParams = {
  isResumeStream?: boolean
  getCompletionRes: () => string
  getWorkflowProcessData: () => WorkflowProcess | undefined
  isPublicAPI: boolean
  isTimedOut: () => boolean
  markEnded: () => void
  notify: Notify
  onCompleted: (completionRes: string, taskId?: number, success?: boolean) => void
  resetRunState: () => void
  setCompletionRes: (res: string) => void
  setCurrentTaskId: Dispatch<SetStateAction<string | null>>
  setIsStopping: Dispatch<SetStateAction<boolean>>
  setMessageId: Dispatch<SetStateAction<string | null>>
  setRespondingFalse: () => void
  setWorkflowProcessData: (data: WorkflowProcess | undefined) => void
  setAbortController?: (controller: AbortController) => void
  t: TextGenerationTranslate
  taskId?: number
}

const createInitialWorkflowProcess = (): WorkflowProcess => ({
  status: WorkflowRunningStatus.Running,
  tracing: [],
  error: undefined,
  expand: false,
  resultText: '',
})

const updateWorkflowProcess = (
  current: WorkflowProcess | undefined,
  updater: (draft: WorkflowProcess) => void,
) => {
  return produce(current ?? createInitialWorkflowProcess(), updater)
}

const matchParallelTrace = (trace: WorkflowProcess['tracing'][number], data: NodeTracing) => {
  return (
    trace.node_id === data.node_id &&
    (trace.execution_metadata?.parallel_id === data.execution_metadata?.parallel_id ||
      trace.parallel_id === data.execution_metadata?.parallel_id)
  )
}

const ensureParallelTraceDetails = (details?: NodeTracing['details']) => {
  return details?.length ? details : [[]]
}

const appendParallelStart = (current: WorkflowProcess | undefined, data: NodeTracing) => {
  return updateWorkflowProcess(current, (draft) => {
    draft.expand = true
    draft.tracing.push({
      ...data,
      details: ensureParallelTraceDetails(data.details),
      status: NodeRunningStatus.Running,
      expand: true,
    })
  })
}

const appendParallelNext = (current: WorkflowProcess | undefined, data: NodeTracing) => {
  return updateWorkflowProcess(current, (draft) => {
    draft.expand = true
    const trace = draft.tracing.find((item) => matchParallelTrace(item, data))
    if (!trace) return

    trace.details = ensureParallelTraceDetails(trace.details)
    trace.details.push([])
  })
}

const finishParallelTrace = (current: WorkflowProcess | undefined, data: NodeTracing) => {
  return updateWorkflowProcess(current, (draft) => {
    draft.expand = true
    const traceIndex = draft.tracing.findIndex((item) => matchParallelTrace(item, data))
    if (traceIndex > -1) {
      draft.tracing[traceIndex] = {
        ...data,
        expand: !!data.error,
      }
    }
  })
}

const upsertWorkflowNode = (current: WorkflowProcess | undefined, data: NodeTracing) => {
  return updateWorkflowProcess(current, (draft) => {
    if (!draft.humanInputFormDataList?.length && draft.status === WorkflowRunningStatus.Paused)
      draft.status = WorkflowRunningStatus.Running
    draft.nodeExecutions = [
      ...(draft.nodeExecutions || []).filter((item) => item.node_id !== data.node_id),
      { ...data, status: NodeRunningStatus.Running },
    ]
    if (data.iteration_id || data.loop_id) return
    draft.expand = true
    const currentIndex = draft.tracing.findIndex((item) => item.node_id === data.node_id)
    const nextTrace = {
      ...data,
      status: NodeRunningStatus.Running,
      expand: true,
    }

    if (currentIndex > -1) draft.tracing[currentIndex] = nextTrace
    else draft.tracing.push(nextTrace)
  })
}

const finishWorkflowNode = (current: WorkflowProcess | undefined, data: NodeTracing) => {
  return updateWorkflowProcess(current, (draft) => {
    draft.nodeExecutions = [
      ...(draft.nodeExecutions || []).filter((item) => item.node_id !== data.node_id),
      data,
    ]
    if (data.iteration_id || data.loop_id) return
    const currentIndex = draft.tracing.findIndex((trace) => matchParallelTrace(trace, data))
    if (currentIndex > -1) {
      draft.tracing[currentIndex] = {
        ...(draft.tracing[currentIndex]!.extras
          ? { extras: draft.tracing[currentIndex]!.extras }
          : {}),
        ...data,
        expand: !!data.error,
      }
    }
  })
}

const markNodesStopped = (traces?: WorkflowProcess['tracing']) => {
  if (!traces) return

  const markTrace = (trace: WorkflowProcess['tracing'][number]) => {
    if (
      [NodeRunningStatus.Running, NodeRunningStatus.Waiting].includes(
        trace.status as NodeRunningStatus,
      )
    )
      trace.status = NodeRunningStatus.Stopped

    trace.details?.forEach((detailGroup) => detailGroup.forEach(markTrace))
    trace.retryDetail?.forEach(markTrace)
    trace.parallelDetail?.children?.forEach(markTrace)
  }

  traces.forEach(markTrace)
}

const applyWorkflowFinishedState = (
  current: WorkflowProcess | undefined,
  status: WorkflowRunningStatus,
  error?: string,
) => {
  return updateWorkflowProcess(current, (draft) => {
    draft.status = status
    draft.error = error
    if ([WorkflowRunningStatus.Stopped, WorkflowRunningStatus.Failed].includes(status)) {
      markNodesStopped(draft.tracing)
      markNodesStopped(draft.nodeExecutions)
    }
  })
}

const applyWorkflowOutputs = (
  current: WorkflowProcess | undefined,
  outputs: WorkflowFinishedResponse['data']['outputs'],
) => {
  return updateWorkflowProcess(current, (draft) => {
    draft.status = WorkflowRunningStatus.Succeeded
    draft.error = undefined
    draft.files = getFilesInLogs(outputs || []) as unknown as WorkflowProcess['files']
  })
}

const appendResultText = (current: WorkflowProcess | undefined, text: string) => {
  return updateWorkflowProcess(current, (draft) => {
    draft.resultText = `${draft.resultText || ''}${text}`
  })
}

const replaceResultText = (current: WorkflowProcess | undefined, text: string) => {
  return updateWorkflowProcess(current, (draft) => {
    draft.resultText = text
  })
}

const updateHumanInputRequired = (
  current: WorkflowProcess | undefined,
  data: NonNullable<WorkflowProcess['humanInputFormDataList']>[number],
) => {
  return updateWorkflowProcess(current, (draft) => {
    if (draft.submittedHumanInputFormIds?.includes(data.form_id)) return
    if (!draft.humanInputFormDataList) {
      draft.humanInputFormDataList = [data]
    } else {
      const currentFormIndex = draft.humanInputFormDataList.findIndex(
        (item) => item.node_id === data.node_id,
      )
      if (currentFormIndex > -1) draft.humanInputFormDataList[currentFormIndex] = data
      else draft.humanInputFormDataList.push(data)
    }

    const currentIndex = draft.tracing.findIndex((item) => item.node_id === data.node_id)
    if (currentIndex > -1) draft.tracing[currentIndex]!.status = NodeRunningStatus.Paused
    const currentNode = draft.nodeExecutions?.find((item) => item.node_id === data.node_id)
    if (currentNode) currentNode.status = NodeRunningStatus.Paused
  })
}

const updateHumanInputFilled = (
  current: WorkflowProcess | undefined,
  data: NonNullable<WorkflowProcess['humanInputFilledFormDataList']>[number],
) => {
  return updateWorkflowProcess(current, (draft) => {
    let requiredFormData: NonNullable<WorkflowProcess['humanInputFormDataList']>[number] | undefined
    if (draft.humanInputFormDataList?.length) {
      const currentFormIndex = draft.humanInputFormDataList.findIndex(
        (item) => item.node_id === data.node_id,
      )
      if (currentFormIndex > -1) {
        requiredFormData = draft.humanInputFormDataList[currentFormIndex]
        if (requiredFormData)
          draft.submittedHumanInputFormIds = [
            ...new Set([...(draft.submittedHumanInputFormIds || []), requiredFormData.form_id]),
          ]
        draft.humanInputFormDataList.splice(currentFormIndex, 1)
      }
    }

    const enrichedData = enrichSubmittedHumanInputFormData(data, requiredFormData)
    const currentNode = draft.nodeExecutions?.find((item) => item.node_id === data.node_id)
    if (currentNode) currentNode.status = NodeRunningStatus.Succeeded
    if (!draft.humanInputFormDataList?.length && draft.status === WorkflowRunningStatus.Paused)
      draft.status = WorkflowRunningStatus.Running
    if (!draft.humanInputFilledFormDataList) draft.humanInputFilledFormDataList = [enrichedData]
    else draft.humanInputFilledFormDataList.push(enrichedData)
  })
}

const acknowledgeHumanInputSubmission = (current: WorkflowProcess | undefined, token: string) => {
  return updateWorkflowProcess(current, (draft) => {
    const form = draft.humanInputFormDataList?.find((item) => item.form_token === token)
    if (!form) return
    draft.submittedHumanInputFormIds = [
      ...new Set([...(draft.submittedHumanInputFormIds || []), form.form_id]),
    ]
    draft.humanInputFormDataList = draft.humanInputFormDataList?.filter(
      (item) => item.form_id !== form.form_id,
    )
    for (const node of [...draft.tracing, ...(draft.nodeExecutions || [])]) {
      if (node.node_id === form.node_id) node.status = NodeRunningStatus.Succeeded
    }
    if (!draft.humanInputFormDataList?.length && draft.status === WorkflowRunningStatus.Paused)
      draft.status = WorkflowRunningStatus.Running
  })
}

const updateHumanInputTimeout = (
  current: WorkflowProcess | undefined,
  data: HumanInputFormTimeoutData,
) => {
  return updateWorkflowProcess(current, (draft) => {
    if (!draft.humanInputFormDataList?.length) return

    const currentFormIndex = draft.humanInputFormDataList.findIndex(
      (item) => item.node_id === data.node_id,
    )
    if (currentFormIndex > -1)
      draft.humanInputFormDataList[currentFormIndex]!.expiration_time = data.expiration_time
  })
}

const applyWorkflowPaused = (current: WorkflowProcess | undefined) => {
  return updateWorkflowProcess(current, (draft) => {
    draft.expand = false
    draft.status = WorkflowRunningStatus.Paused
  })
}

const serializeWorkflowOutputs = (outputs: WorkflowFinishedResponse['data']['outputs']) => {
  if (outputs === undefined || outputs === null) return ''

  if (typeof outputs === 'string') return outputs

  try {
    return JSON.stringify(outputs) ?? ''
  } catch {
    return String(outputs)
  }
}

export const createWorkflowStreamHandlers = ({
  isResumeStream = false,
  getCompletionRes,
  getWorkflowProcessData,
  isPublicAPI,
  isTimedOut,
  markEnded,
  notify,
  onCompleted,
  resetRunState,
  setCompletionRes,
  setCurrentTaskId,
  setIsStopping,
  setMessageId,
  setRespondingFalse,
  setWorkflowProcessData,
  setAbortController,
  t,
  taskId,
}: CreateWorkflowStreamHandlersParams): IOtherOptions => {
  let tempMessageId = ''
  let hasStartedResumeStream = isResumeStream

  const finishWithFailure = () => {
    setRespondingFalse()
    resetRunState()
    onCompleted(getCompletionRes(), taskId, false)
    markEnded()
  }

  const finishWithSuccess = () => {
    setRespondingFalse()
    resetRunState()
    setMessageId(tempMessageId)
    onCompleted(getCompletionRes(), taskId, true)
    markEnded()
  }

  const otherOptions: IOtherOptions = {
    isPublicAPI,
    getAbortController: setAbortController,
    onError: (message) => {
      setWorkflowProcessData(
        applyWorkflowFinishedState(getWorkflowProcessData(), WorkflowRunningStatus.Failed, message),
      )
      notify({ type: 'error', message })
      finishWithFailure()
    },
    onWorkflowStarted: ({ workflow_run_id, task_id }) => {
      setCurrentTaskId(task_id || null)
      setIsStopping(false)
      const workflowProcessData = getWorkflowProcessData()
      if (workflowProcessData?.tracing.length) {
        setWorkflowProcessData(
          updateWorkflowProcess(workflowProcessData, (draft) => {
            draft.expand = true
            draft.status = WorkflowRunningStatus.Running
            draft.error = undefined
          }),
        )
        return
      }

      tempMessageId = workflow_run_id
      setWorkflowProcessData({ ...createInitialWorkflowProcess(), runId: workflow_run_id })
    },
    onIterationStart: ({ data }) => {
      setWorkflowProcessData(appendParallelStart(getWorkflowProcessData(), data))
    },
    onIterationNext: ({ data }) => {
      setWorkflowProcessData(appendParallelNext(getWorkflowProcessData(), data))
    },
    onIterationFinish: ({ data }) => {
      setWorkflowProcessData(finishParallelTrace(getWorkflowProcessData(), data))
    },
    onLoopStart: ({ data }) => {
      setWorkflowProcessData(appendParallelStart(getWorkflowProcessData(), data))
    },
    onLoopNext: ({ data }) => {
      setWorkflowProcessData(appendParallelNext(getWorkflowProcessData(), data))
    },
    onLoopFinish: ({ data }) => {
      setWorkflowProcessData(finishParallelTrace(getWorkflowProcessData(), data))
    },
    onNodeStarted: ({ data }) => {
      setWorkflowProcessData(upsertWorkflowNode(getWorkflowProcessData(), data))
    },
    onNodeFinished: ({ data }) => {
      setWorkflowProcessData(finishWorkflowNode(getWorkflowProcessData(), data))
    },
    onWorkflowFinished: ({ data }) => {
      const workflowStatus = data.status as WorkflowRunningStatus | undefined
      if (isTimedOut()) {
        const finishedStatus =
          workflowStatus === WorkflowRunningStatus.Stopped
            ? WorkflowRunningStatus.Stopped
            : workflowStatus === WorkflowRunningStatus.Failed || data.error
              ? WorkflowRunningStatus.Failed
              : WorkflowRunningStatus.Succeeded
        setWorkflowProcessData(
          applyWorkflowFinishedState(getWorkflowProcessData(), finishedStatus, data.error),
        )
        notify({
          type: 'warning',
          message: t(($) => $['warningMessage.timeoutExceeded'], { ns: 'appDebug' }),
        })
        markEnded()
        return
      }

      if (workflowStatus === WorkflowRunningStatus.Stopped) {
        setWorkflowProcessData(
          applyWorkflowFinishedState(
            getWorkflowProcessData(),
            WorkflowRunningStatus.Stopped,
            data.error,
          ),
        )
        finishWithFailure()
        return
      }

      if (data.error) {
        notify({ type: 'error', message: data.error })
        setWorkflowProcessData(
          applyWorkflowFinishedState(
            getWorkflowProcessData(),
            WorkflowRunningStatus.Failed,
            data.error,
          ),
        )
        finishWithFailure()
        return
      }

      setWorkflowProcessData(applyWorkflowOutputs(getWorkflowProcessData(), data.outputs))
      const serializedOutputs = serializeWorkflowOutputs(data.outputs)
      setCompletionRes(serializedOutputs)
      if (data.outputs) {
        const outputKeys = Object.keys(data.outputs)
        const isStringOutput =
          outputKeys.length === 1 && typeof data.outputs[outputKeys[0]!] === 'string'
        if (isStringOutput) {
          setWorkflowProcessData(
            updateWorkflowProcess(getWorkflowProcessData(), (draft) => {
              draft.resultText = data.outputs[outputKeys[0]!]
            }),
          )
        }
      }

      finishWithSuccess()
    },
    onTextChunk: ({ data: { text } }) => {
      setWorkflowProcessData(appendResultText(getWorkflowProcessData(), text))
    },
    onTextReplace: ({ data: { text } }) => {
      setWorkflowProcessData(replaceResultText(getWorkflowProcessData(), text))
    },
    onHumanInputRequired: ({ data }) => {
      setWorkflowProcessData(updateHumanInputRequired(getWorkflowProcessData(), data))
    },
    onHumanInputFormFilled: ({ data }) => {
      setWorkflowProcessData(updateHumanInputFilled(getWorkflowProcessData(), data))
    },
    onHumanInputFormTimeout: ({ data }) => {
      setWorkflowProcessData(updateHumanInputTimeout(getWorkflowProcessData(), data))
    },
    onWorkflowPaused: ({ data }) => {
      tempMessageId = data.workflow_run_id
      if (!hasStartedResumeStream) {
        hasStartedResumeStream = true
        subscribeWorkflowEvents(data.workflow_run_id, otherOptions)
      }
      const acknowledged = getWorkflowProcessData()?.submittedHumanInputFormIds || []
      if (
        data.reasons?.length &&
        data.reasons.every(
          (reason) => 'form_id' in reason && acknowledged.includes(String(reason.form_id)),
        )
      )
        return
      setWorkflowProcessData(applyWorkflowPaused(getWorkflowProcessData()))
    },
  }

  return otherOptions
}

export {
  acknowledgeHumanInputSubmission,
  appendParallelNext,
  appendParallelStart,
  appendResultText,
  applyWorkflowFinishedState,
  applyWorkflowOutputs,
  applyWorkflowPaused,
  finishParallelTrace,
  finishWorkflowNode,
  markNodesStopped,
  replaceResultText,
  updateHumanInputFilled,
  updateHumanInputRequired,
  updateHumanInputTimeout,
  upsertWorkflowNode,
}
