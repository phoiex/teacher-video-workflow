import type { PromptConfig } from '@/models/debug'
import type { SiteInfo } from '@/models/share'
import type { IOtherOptions } from '@/service/base'
import type { VisionSettings } from '@/types/app'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { act, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { AppSourceType } from '@/service/share'
import { Resolution, TransferMethod } from '@/types/app'
import Result from '../index'

const {
  notifyMock,
  sendCompletionMessageMock,
  sendWorkflowMessageMock,
  sleepMock,
  stopChatMessageRespondingMock,
  textGenerationResPropsSpy,
  retryPublishedMock,
  watchWorkflowMock,
} = vi.hoisted(() => ({
  notifyMock: vi.fn(),
  sendCompletionMessageMock: vi.fn(),
  sendWorkflowMessageMock: vi.fn(),
  sleepMock: vi.fn(),
  stopChatMessageRespondingMock: vi.fn(),
  textGenerationResPropsSpy: vi.fn(),
  retryPublishedMock: vi.fn(),
  watchWorkflowMock: vi.fn(),
}))

vi.mock('i18next', async (importOriginal) => {
  const actual = await importOriginal<typeof import('i18next')>()

  return {
    ...actual,
    t: () => '',
  }
})

vi.mock('react-i18next', async (importOriginal) => {
  const actual = await importOriginal<typeof import('react-i18next')>()
  const { createReactI18nextMock } = await import('@/test/i18n-mock')

  return {
    ...actual,
    ...createReactI18nextMock({
      'operation.stopResponding': 'operation.stopResponding',
      'warningMessage.timeoutExceeded': 'Translated timeout warning',
    }),
  }
})

vi.mock('@langgenius/dify-ui/toast', () => ({
  toast: (...args: unknown[]) => notifyMock(...args),
}))

vi.mock('@/utils', async () => {
  const actual = await vi.importActual<typeof import('@/utils')>('@/utils')
  return {
    ...actual,
    sleep: (...args: Parameters<typeof actual.sleep>) => sleepMock(...args),
  }
})

vi.mock('@/service/share', async () => {
  const actual = await vi.importActual<typeof import('@/service/share')>('@/service/share')
  return {
    ...actual,
    sendCompletionMessage: (...args: Parameters<typeof actual.sendCompletionMessage>) =>
      sendCompletionMessageMock(...args),
    sendWorkflowMessage: (...args: Parameters<typeof actual.sendWorkflowMessage>) =>
      sendWorkflowMessageMock(...args),
    stopChatMessageResponding: (...args: Parameters<typeof actual.stopChatMessageResponding>) =>
      stopChatMessageRespondingMock(...args),
    retryPublishedWorkflow: retryPublishedMock,
    watchWorkflowRun: watchWorkflowMock,
  }
})

vi.mock('@/app/components/app/text-generate/item', () => ({
  default: (props: Record<string, unknown>) => {
    textGenerationResPropsSpy(props)
    return (
      <div data-testid="text-generation-res">
        {typeof props.content === 'string' ? props.content : JSON.stringify(props.content ?? null)}
      </div>
    )
  },
}))

vi.mock('@/next/navigation', () => ({ useRouter: () => ({ replace: vi.fn() }) }))

vi.mock('@/app/components/share/text-generation/no-data', () => ({
  default: () => <div data-testid="no-data">No data</div>,
}))

const promptConfig: PromptConfig = {
  prompt_template: 'template',
  prompt_variables: [{ key: 'name', name: 'Name', type: 'string', required: true }],
}

const siteInfo: SiteInfo = {
  title: 'Share title',
  description: 'Share description',
  icon_type: 'emoji',
  icon: 'robot',
}

const visionConfig: VisionSettings = {
  enabled: false,
  number_limits: 2,
  detail: Resolution.low,
  transfer_methods: [TransferMethod.local_file],
}

const baseProps = {
  appId: 'app-1',
  appSourceType: AppSourceType.webApp,
  completionFiles: [],
  controlRetry: 0,
  controlSend: 0,
  controlStopResponding: 0,
  handleSaveMessage: vi.fn(),
  inputs: { name: 'Alice' },
  isCallBatchAPI: false,
  isError: false,
  isMobile: false,
  isPC: true,
  isShowTextToSpeech: true,
  isWorkflow: false,
  moreLikeThisEnabled: true,
  onCompleted: vi.fn(),
  onRunControlChange: vi.fn(),
  onRunStart: vi.fn(),
  onShowRes: vi.fn(),
  promptConfig,
  siteInfo,
  visionConfig,
}

describe('Result', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    sleepMock.mockImplementation(() => new Promise<void>(() => {}))
    stopChatMessageRespondingMock.mockResolvedValue(undefined)
  })

  it('shows checkpoint retry after a connection error and reconnects without a new course request', async () => {
    const oldRun = 'aaaaaaaa-1111-2222-3333-444444444444'
    const nextRun = 'bbbbbbbb-1111-2222-3333-444444444444'
    let handlers: IOtherOptions | undefined
    sendWorkflowMessageMock.mockImplementation(async (_data, options) => {
      handlers = options
    })
    retryPublishedMock.mockResolvedValue(nextRun)
    watchWorkflowMock.mockImplementation(async (id, options: IOtherOptions) => {
      options.onWorkflowStarted?.({
        event: 'workflow_started',
        workflow_run_id: id,
        task_id: id,
        data: { id, workflow_id: 'original-published-version', created_at: 0 },
      })
    })
    vi.stubGlobal(
      'fetch',
      vi
        .fn()
        .mockResolvedValue(new Response(JSON.stringify({ status: 'failed', retryable: true }))),
    )
    try {
      render(
        <QueryClientProvider
          client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}
        >
          <Result
            {...baseProps}
            isWorkflow
            controlSend={1}
            promptConfig={{
              ...promptConfig,
              prompt_variables: [
                { key: 'resume_course', name: 'Course', type: 'string', required: false },
              ],
            }}
          />
        </QueryClientProvider>,
      )
      await waitFor(() => expect(sendWorkflowMessageMock).toHaveBeenCalledOnce())
      await act(async () => {
        handlers?.onWorkflowStarted?.({
          event: 'workflow_started',
          workflow_run_id: oldRun,
          task_id: oldRun,
          data: { id: oldRun, workflow_id: 'original-published-version', created_at: 0 },
        })
        handlers?.onError?.('network connection interrupted')
      })
      fireEvent.click(
        await screen.findByRole('button', { name: /retrySaved|从断点重试|Retry from saved/ }),
      )
      await waitFor(() =>
        expect(watchWorkflowMock).toHaveBeenCalledWith(
          nextRun,
          expect.objectContaining({ isPublicAPI: true }),
        ),
      )
      expect(retryPublishedMock).toHaveBeenCalledWith(oldRun)
      expect(sendWorkflowMessageMock).toHaveBeenCalledOnce()
      await waitFor(() =>
        expect(
          screen.queryByRole('button', { name: /retrySaved|从断点重试|Retry from saved/ }),
        ).toBeNull(),
      )
    } finally {
      vi.unstubAllGlobals()
    }
  })

  it('should render no data before the first execution', () => {
    render(<Result {...baseProps} />)

    expect(screen.getByTestId('no-data')).toBeTruthy()
    expect(screen.queryByTestId('text-generation-res')).toBeNull()
  })

  it('should stream completion results and stop the current task', async () => {
    let completionHandlers: {
      onCompleted: () => void
      onData: (
        chunk: string,
        isFirstMessage: boolean,
        info: { messageId: string; taskId?: string },
      ) => void
      onError: () => void
      onMessageReplace: (messageReplace: { answer: string }) => void
    } | null = null

    sendCompletionMessageMock.mockImplementation(async (_data, handlers) => {
      completionHandlers = handlers
    })

    const onCompleted = vi.fn()
    const onRunControlChange = vi.fn()
    const { rerender } = render(
      <Result {...baseProps} onCompleted={onCompleted} onRunControlChange={onRunControlChange} />,
    )

    rerender(
      <Result
        {...baseProps}
        controlSend={1}
        onCompleted={onCompleted}
        onRunControlChange={onRunControlChange}
      />,
    )

    expect(sendCompletionMessageMock).toHaveBeenCalledTimes(1)
    expect(screen.getByRole('status', { name: 'appApi.loading' })).toBeTruthy()

    await act(async () => {
      completionHandlers?.onData('Hello', false, {
        messageId: 'message-1',
        taskId: 'task-1',
      })
    })

    expect(screen.getByTestId('text-generation-res').textContent).toContain('Hello')

    await waitFor(() => {
      expect(onRunControlChange).toHaveBeenLastCalledWith(
        expect.objectContaining({
          isStopping: false,
        }),
      )
    })

    fireEvent.click(screen.getByRole('button', { name: 'operation.stopResponding' }))
    await waitFor(() => {
      expect(stopChatMessageRespondingMock).toHaveBeenCalledWith(
        'app-1',
        'task-1',
        AppSourceType.webApp,
        'app-1',
      )
    })

    await act(async () => {
      completionHandlers?.onCompleted()
    })

    expect(onCompleted).toHaveBeenCalledWith('Hello', undefined, true)
    expect(textGenerationResPropsSpy).toHaveBeenLastCalledWith(
      expect.objectContaining({
        messageId: 'message-1',
      }),
    )
  })

  it('should render workflow results after workflow completion', async () => {
    let workflowHandlers: IOtherOptions | null = null
    sendWorkflowMessageMock.mockImplementation(async (_data, handlers) => {
      workflowHandlers = handlers
    })

    const onCompleted = vi.fn()
    const { rerender } = render(<Result {...baseProps} isWorkflow onCompleted={onCompleted} />)

    rerender(<Result {...baseProps} isWorkflow controlSend={1} onCompleted={onCompleted} />)

    await act(async () => {
      workflowHandlers?.onWorkflowStarted?.({
        workflow_run_id: 'run-1',
        task_id: 'task-1',
        event: 'workflow_started',
        data: {
          id: 'run-1',
          workflow_id: 'wf-1',
          created_at: 0,
        },
      })
      workflowHandlers?.onTextChunk?.({
        task_id: 'task-1',
        workflow_run_id: 'run-1',
        event: 'text_chunk',
        data: {
          text: 'Hello',
        },
      })
      workflowHandlers?.onWorkflowFinished?.({
        task_id: 'task-1',
        workflow_run_id: 'run-1',
        event: 'workflow_finished',
        data: {
          id: 'run-1',
          workflow_id: 'wf-1',
          status: 'succeeded',
          outputs: {
            answer: 'Hello',
          },
          error: '',
          elapsed_time: 0,
          total_tokens: 0,
          total_steps: 0,
          created_at: 0,
          created_by: {
            id: 'user-1',
            name: 'User',
            email: 'user@example.com',
          },
          finished_at: 0,
        },
      })
    })

    expect(screen.getByTestId('text-generation-res').textContent).toContain('{"answer":"Hello"}')
    expect(textGenerationResPropsSpy).toHaveBeenLastCalledWith(
      expect.objectContaining({
        workflowProcessData: expect.objectContaining({
          resultText: 'Hello',
          status: 'succeeded',
        }),
      }),
    )
    expect(onCompleted).toHaveBeenCalledWith('{"answer":"Hello"}', undefined, true)
  })

  it('keeps a workflow open until the server finishes it, including long reviews', async () => {
    let workflowHandlers: IOtherOptions | null = null
    sendWorkflowMessageMock.mockImplementation(async (_data, handlers) => {
      workflowHandlers = handlers
    })

    const onCompleted = vi.fn()
    const { rerender } = render(<Result {...baseProps} isWorkflow onCompleted={onCompleted} />)

    rerender(<Result {...baseProps} isWorkflow controlSend={1} onCompleted={onCompleted} />)

    await act(async () => {
      workflowHandlers?.onWorkflowStarted?.({
        workflow_run_id: 'run-timeout',
        task_id: 'task-timeout',
        event: 'workflow_started',
        data: {
          id: 'run-timeout',
          workflow_id: 'wf-1',
          created_at: 0,
        },
      })
      await Promise.resolve()
    })
    expect(sleepMock).not.toHaveBeenCalled()
    expect(onCompleted).not.toHaveBeenCalled()

    await act(async () => {
      workflowHandlers?.onWorkflowFinished?.({
        task_id: 'task-timeout',
        workflow_run_id: 'run-timeout',
        event: 'workflow_finished',
        data: {
          id: 'run-timeout',
          workflow_id: 'wf-1',
          status: 'succeeded',
          outputs: { answer: 'Late result' },
          error: '',
          elapsed_time: 61,
          total_tokens: 0,
          total_steps: 0,
          created_at: 0,
          created_by: {
            id: 'user-1',
            name: 'User',
            email: 'user@example.com',
          },
          finished_at: 61,
        },
      })
    })

    expect(textGenerationResPropsSpy).toHaveBeenLastCalledWith(
      expect.objectContaining({
        workflowProcessData: expect.objectContaining({
          resultText: 'Late result',
          status: 'succeeded',
        }),
      }),
    )
    expect(notifyMock).not.toHaveBeenCalledWith('Translated timeout warning', { type: 'warning' })
    expect(onCompleted).toHaveBeenCalledWith('{"answer":"Late result"}', undefined, true)
    expect(onCompleted).toHaveBeenCalledTimes(1)
  })

  it('should render batch task ids for both short and long indexes', () => {
    const { rerender } = render(<Result {...baseProps} isCallBatchAPI taskId={3} />)

    expect(textGenerationResPropsSpy).toHaveBeenLastCalledWith(
      expect.objectContaining({
        taskId: '03',
      }),
    )

    rerender(<Result {...baseProps} isCallBatchAPI taskId={12} />)

    expect(textGenerationResPropsSpy).toHaveBeenLastCalledWith(
      expect.objectContaining({
        taskId: '12',
      }),
    )
  })

  it('should render the mobile stop button layout while a batch run is responding', async () => {
    let completionHandlers: {
      onData: (
        chunk: string,
        isFirstMessage: boolean,
        info: { messageId: string; taskId?: string },
      ) => void
    } | null = null

    sendCompletionMessageMock.mockImplementation(async (_data, handlers) => {
      completionHandlers = handlers
    })

    const { rerender } = render(
      <Result {...baseProps} isCallBatchAPI isMobile isPC={false} taskId={2} />,
    )

    rerender(
      <Result {...baseProps} controlSend={1} isCallBatchAPI isMobile isPC={false} taskId={2} />,
    )

    await act(async () => {
      completionHandlers?.onData('Hello', false, {
        messageId: 'message-batch',
        taskId: 'task-batch',
      })
    })

    expect(
      screen.getByRole('button', { name: 'operation.stopResponding' }).parentElement?.className,
    ).toContain('justify-center')
  })
})
