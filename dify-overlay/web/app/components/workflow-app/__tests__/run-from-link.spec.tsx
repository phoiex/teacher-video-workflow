import type { HistoryWorkflowData, WorkflowRunningData } from '@/app/components/workflow/types'
import { QueryClient, QueryClientProvider, skipToken } from '@tanstack/react-query'
import { act, render, waitFor } from '@testing-library/react'
import RunFromLink from '../components/run-from-link'

type RunViewState = {
  workflowRunningData?: WorkflowRunningData
  historyWorkflowData?: HistoryWorkflowData
  showDebugAndPreviewPanel?: boolean
  showInputsPanel?: boolean
}

const { state, getRun, requested, store, router, backup } = vi.hoisted(() => {
  const state: RunViewState = {}
  return {
    state,
    backup: vi.fn(),
    getRun: vi.fn(async (_input: unknown) => ({
      id: '6cd4e78e-d332-4fd3-8870-674c9900bf89',
      status: 'running',
    })),
    requested: { id: '6cd4e78e-d332-4fd3-8870-674c9900bf89' as string | null },
    router: { replace: vi.fn() },
    store: {
      getState: () => state,
      setState: (patch: Record<string, unknown>) => Object.assign(state, patch),
    },
  }
})
vi.mock('@/next/navigation', () => ({
  useSearchParams: () => new URLSearchParams(requested.id ? { run_id: requested.id } : {}),
  useRouter: () => router,
  usePathname: () => '/app/course-app/workflow',
}))
vi.mock('@/app/components/app/store', () => ({
  useStore: (selector: (s: { appDetail: { id: string } }) => unknown) =>
    selector({ appDetail: { id: 'course-app' } }),
}))
vi.mock('@/app/components/workflow/store', () => ({
  useWorkflowStore: () => store,
  useStore: (selector: (s: RunViewState) => unknown) => selector(state),
}))
vi.mock('@/app/components/workflow/hooks-store', () => ({
  useHooksStore: (selector: (s: { handleBackupDraft: () => void }) => unknown) =>
    selector({ handleBackupDraft: backup }),
}))
vi.mock('@/service/console', () => ({
  consoleQuery: {
    apps: {
      byAppId: {
        workflowRuns: {
          byRunId: {
            get: {
              queryOptions: ({ input, ...options }: Record<string, unknown>) => ({
                ...options,
                queryKey: ['native-run', input],
                queryFn: input === skipToken ? skipToken : () => getRun(input),
              }),
            },
          },
        },
      },
    },
  },
}))

describe('原生界面查看已有运行', () => {
  beforeEach(() => {
    getRun.mockClear()
    router.replace.mockClear()
    backup.mockClear()
    Object.keys(state).forEach((key) => delete state[key as keyof RunViewState])
    requested.id = '6cd4e78e-d332-4fd3-8870-674c9900bf89'
  })
  it('打开原有进度，关闭后轮询不会重新弹开，也不打开初始填写', async () => {
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
    const view = render(
      <QueryClientProvider client={client}>
        <RunFromLink />
      </QueryClientProvider>,
    )
    await waitFor(() => expect(state.historyWorkflowData?.id).toBe(requested.id))
    expect(state.showInputsPanel).toBe(false)
    expect(state.showDebugAndPreviewPanel).toBe(false)
    expect(backup).toHaveBeenCalledTimes(1)
    expect(getRun).toHaveBeenCalledWith({ params: { app_id: 'course-app', run_id: requested.id } })
    act(() => store.setState({ historyWorkflowData: undefined }))
    await act(async () => {
      await client.invalidateQueries()
    })
    expect(state.showDebugAndPreviewPanel).toBe(false)
    expect(state.workflowRunningData).toBeUndefined()
    expect(state.historyWorkflowData).toBeUndefined()
    view.unmount()
    client.clear()
  })
  it('没有运行编号时只进入编辑器，不读取旧记录', () => {
    requested.id = null
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
    const view = render(
      <QueryClientProvider client={client}>
        <RunFromLink />
      </QueryClientProvider>,
    )
    expect(getRun).not.toHaveBeenCalled()
    expect(state.showDebugAndPreviewPanel).toBeUndefined()
    view.unmount()
    client.clear()
  })
  it('原生界面开始新一轮后，地址随当前运行更新，刷新仍打开同一轮', async () => {
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
    const element = () => (
      <QueryClientProvider client={client}>
        <RunFromLink />
      </QueryClientProvider>
    )
    const view = render(element())
    await waitFor(() => expect(state.historyWorkflowData?.id).toBe(requested.id))
    const next = '3536e71a-281f-47b0-a50c-5c0a13abc997'
    state.historyWorkflowData = undefined
    state.workflowRunningData = {
      result: {
        id: next,
        status: 'running',
        inputs_truncated: false,
        process_data_truncated: false,
        outputs_truncated: false,
      },
    }
    view.rerender(element())
    await waitFor(() =>
      expect(router.replace).toHaveBeenCalledWith(`/app/course-app/workflow?run_id=${next}`, {
        scroll: false,
      }),
    )
    expect(state.workflowRunningData.result.id).toBe(next)
    view.unmount()
    client.clear()
  })
  it('用户在原生页面新启动的执行保持原有预览', async () => {
    state.workflowRunningData = {
      result: {
        id: requested.id!,
        status: 'running',
        inputs_truncated: false,
        process_data_truncated: false,
        outputs_truncated: false,
      },
    }
    state.showDebugAndPreviewPanel = true
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
    const view = render(
      <QueryClientProvider client={client}>
        <RunFromLink />
      </QueryClientProvider>,
    )
    await waitFor(() => expect(getRun).toHaveBeenCalled())
    expect(state.showDebugAndPreviewPanel).toBe(true)
    expect(state.historyWorkflowData).toBeUndefined()
    expect(backup).not.toHaveBeenCalled()
    view.unmount()
    client.clear()
  })
})
