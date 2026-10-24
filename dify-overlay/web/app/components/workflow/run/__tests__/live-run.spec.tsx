import { focusManager, QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { act, render, screen } from '@testing-library/react'
import { useEffect, useRef } from 'react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vite-plus/test'
import LiveRun from '../live-run'

const { backend, getRun, getTrace, getPause, canvas, shownTrace, production } = vi.hoisted(() => {
  const backend = {
    status: 'running',
    title: '讲稿',
    nodeId: 'script',
    formId: 'form-a',
  }
  return {
    backend,
    shownTrace: vi.fn(),
    production: { report: undefined as undefined | ((status: string) => void) },
    getRun: vi.fn(async () => ({
      id: 'run-1',
      status: backend.status,
      graph: { nodes: [], edges: [] },
      outputs: {},
    })),
    getTrace: vi.fn(async () => ({
      data: [
        {
          node_id: backend.nodeId,
          node_type: 'http-request',
          title: backend.title,
          status: backend.status,
          created_at: 1,
          index: 1,
        },
      ],
    })),
    getPause: vi.fn(async () => ({
      paused_nodes: [
        {
          node_id: backend.nodeId,
          node_title: backend.title,
          pause_type: { backstage_input_url: `http://localhost/form/${backend.formId}` },
        },
      ],
    })),
    canvas: {
      setNodes: vi.fn(),
      getNodes: vi.fn(() => [
        {
          id: 'script',
          position: { x: 100, y: 80 },
          width: 244,
          height: 110,
          data: { _runningStatus: 'succeeded' },
        },
        {
          id: 'storyboard',
          position: { x: 800, y: 400 },
          width: 244,
          height: 110,
          data: { _runningStatus: 'succeeded' },
        },
      ]),
      getNode: vi.fn(),
      getViewport: vi.fn(() => ({ x: 0, y: 0, zoom: 1 })),
      fitView: vi.fn(),
      setViewport: vi.fn(),
      width: 1600,
      height: 1000,
      domNode: null,
    },
  }
})

vi.mock('reactflow', () => ({
  useReactFlow: () => canvas,
  useStoreApi: () => ({ getState: () => canvas }),
}))
vi.mock('@/service/console', () => {
  const options = (key: string, fn: () => Promise<unknown>) => ({
    queryOptions: ({ input: _input, ...rest }: Record<string, unknown>) => ({
      ...rest,
      queryKey: [key],
      queryFn: fn,
    }),
  })
  return {
    consoleQuery: {
      apps: {
        byAppId: {
          workflowRuns: {
            byRunId: {
              get: options('run', getRun),
              nodeExecutions: { get: options('trace', getTrace) },
            },
          },
        },
      },
      workflow: { byWorkflowRunId: { pauseDetails: { get: options('pause', getPause) } } },
    },
  }
})
vi.mock('../tracing-panel', () => ({
  default: ({ list }: { list: unknown }) => {
    shownTrace(list)
    return null
  },
}))
vi.mock('../output-panel', () => ({ default: () => <div>已完成</div> }))
vi.mock('../review-dialog', () => ({
  default: ({
    title,
    onProductionStatus,
  }: {
    title: string
    onProductionStatus?: (status: string) => void
  }) => {
    production.report = onProductionStatus
    return <div role="dialog" aria-label={title} />
  },
}))

let client: QueryClient
const advance = async (ms: number) => {
  await act(async () => {
    await vi.advanceTimersByTimeAsync(ms)
  })
}
const mount = () =>
  render(
    <QueryClientProvider client={client}>
      <LiveRun appId="app-1" runId="run-1" />
    </QueryClientProvider>,
  )

describe('运行记录自动更新', () => {
  beforeEach(() => {
    vi.useFakeTimers()
    vi.clearAllMocks()
    backend.status = 'running'
    backend.title = '讲稿'
    backend.nodeId = 'script'
    backend.formId = 'form-a'
    client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
    focusManager.setFocused(true)
  })
  afterEach(() => {
    client.clear()
    focusManager.setFocused(undefined)
    vi.useRealTimers()
    vi.restoreAllMocks()
  })

  it('实际制作失败时，等待节点和外层分镜同时停止转圈；重试时一起恢复', async () => {
    backend.status = 'paused'
    backend.nodeId = 'storyboard_wait'
    backend.title = '制作分镜'
    const records = [
      {
        id: 'loop-old',
        node_id: 'storyboard_loop',
        node_type: 'loop',
        title: '分镜',
        status: 'succeeded',
        created_at: 0,
        index: 0,
      },
      {
        id: 'loop-current',
        node_id: 'storyboard_loop',
        node_type: 'loop',
        title: '分镜',
        status: 'running',
        created_at: 1,
        index: 1,
      },
      {
        id: 'wait-current',
        node_id: 'storyboard_wait',
        node_type: 'human-input',
        title: '制作分镜',
        status: 'paused',
        created_at: 2,
        index: 2,
        execution_metadata: { loop_id: 'storyboard_loop' },
      },
      {
        id: 'unrelated',
        node_id: 'other',
        node_type: 'http-request',
        title: '另一路任务',
        status: 'running',
        created_at: 3,
        index: 3,
      },
    ]
    getTrace.mockResolvedValueOnce({ data: records })
    const view = mount()
    await advance(50)
    act(() => production.report?.('failed'))
    expect(
      shownTrace.mock.calls.at(-1)?.[0].map((node: { status: string }) => node.status),
    ).toEqual(['succeeded', 'failed', 'failed', 'running'])
    act(() => production.report?.('starting'))
    expect(
      shownTrace.mock.calls.at(-1)?.[0].map((node: { status: string }) => node.status),
    ).toEqual(['succeeded', 'running', 'running', 'running'])
    act(() => production.report?.('network_wait'))
    expect(shownTrace.mock.calls.at(-1)?.[0][1].status).toBe('paused')
    expect(shownTrace.mock.calls.at(-1)?.[0][2].error).toBe('workflow.liveProgress.connectionLost')
    expect(screen.getByRole('status')).toHaveTextContent('workflow.liveProgress.connectionLost')
    act(() => production.report?.('failed'))
    expect(shownTrace.mock.calls.at(-1)?.[0][1].status).toBe('failed')
    expect(records[1]?.status).toBe('running')
    view.unmount()
  })

  it('等待用户继续制作时，外层循环也显示暂停', async () => {
    backend.status = 'paused'
    backend.nodeId = 'storyboard_resume'
    backend.title = '继续分镜制作'
    const pausedRecords = {
      data: [
        {
          id: 'loop-paused',
          node_id: 'storyboard_loop',
          node_type: 'loop',
          title: '分镜',
          status: 'running',
          created_at: 1,
          index: 1,
        },
        {
          id: 'resume-paused',
          node_id: 'storyboard_resume',
          node_type: 'human-input',
          title: '继续分镜制作',
          status: 'paused',
          created_at: 2,
          index: 2,
          execution_metadata: { loop_id: 'storyboard_loop' },
        },
      ],
    }
    getTrace.mockResolvedValueOnce(pausedRecords)
    const view = mount()
    await advance(50)
    expect(
      shownTrace.mock.calls.at(-1)?.[0].map((node: { status: string }) => node.status),
    ).toEqual(['paused', 'paused'])
    view.unmount()
  })

  it('从已有运行打开时，父画布完成订阅后仍收到缓存中的节点图', async () => {
    client.setQueryData(['run'], {
      id: 'run-1',
      status: 'running',
      graph: { nodes: [], edges: [] },
    })
    const received = vi.fn()
    const CanvasOwner = () => {
      const readyRef = useRef(false)
      useEffect(() => {
        readyRef.current = true
      }, [])
      return (
        <LiveRun
          appId="app-1"
          runId="run-1"
          onGraphLoaded={(graph) => {
            if (readyRef.current) received(graph)
          }}
        />
      )
    }
    const view = render(
      <QueryClientProvider client={client}>
        <CanvasOwner />
      </QueryClientProvider>,
    )
    await advance(50)
    expect(received).toHaveBeenCalledTimes(1)
    view.unmount()
  })

  it('后台从暂停继续后自动离开Pending，无需重新打开页面', async () => {
    backend.status = 'paused'
    const view = mount()
    await advance(50)
    expect(screen.getByRole('status')).toHaveTextContent('workflow.liveProgress.paused')
    backend.status = 'running'
    backend.nodeId = 'storyboard'
    backend.title = '分镜'
    await advance(2200)
    expect(screen.getByRole('status')).toHaveTextContent('workflow.liveProgress.running')
    expect(screen.getByRole('status')).not.toHaveTextContent('workflow.liveProgress.paused')
    view.unmount()
  })

  it('运行结束后停止定时请求', async () => {
    const view = mount()
    await advance(50)
    backend.status = 'succeeded'
    await advance(4200)
    expect(screen.getByRole('status')).toHaveTextContent('workflow.common.workflowProcessSucceeded')
    const requests = getRun.mock.calls.length
    await advance(6000)
    expect(getRun).toHaveBeenCalledTimes(requests)
    view.unmount()
  })

  it('尚未运行的节点不会沿用上一轮缓存的完成颜色', async () => {
    const view = mount()
    await advance(50)
    const changed = canvas.setNodes.mock.calls.at(-1)?.[0]
    expect(changed[0].data._runningStatus).toBe('running')
    expect(changed[1].data._runningStatus).toBe('not-start')
    view.unmount()
  })

  it('切回页面时立即读取新状态并显示待确认内容', async () => {
    const view = mount()
    await advance(50)
    focusManager.setFocused(false)
    backend.status = 'paused'
    backend.nodeId = 'script_review'
    backend.title = '讲稿确认'
    await act(async () => {
      focusManager.setFocused(true)
    })
    await advance(50)
    expect(screen.getByRole('status')).toHaveTextContent('workflow.liveProgress.paused')
    expect(screen.getByRole('dialog', { name: '讲稿确认' })).toBeInTheDocument()
    view.unmount()
  })

  it('换节点时自动跟随，同一节点轮询不会拉回用户拖动的位置', async () => {
    const view = mount()
    await advance(500)
    expect(canvas.setViewport).toHaveBeenCalledTimes(1)
    expect(canvas.setViewport.mock.calls[0]?.[1]).toEqual({ duration: 600 })
    await advance(4500)
    expect(canvas.setViewport).toHaveBeenCalledTimes(1)
    backend.nodeId = 'storyboard'
    backend.title = '分镜'
    await advance(2500)
    expect(canvas.setViewport).toHaveBeenCalledTimes(2)
    expect(
      screen.queryByRole('button', { name: 'workflow.liveProgress.locate' }),
    ).not.toBeInTheDocument()
    view.unmount()
  })

  it('减少动态效果时自动定位但不播放镜头移动', async () => {
    vi.spyOn(window, 'matchMedia').mockReturnValue({ matches: true } as MediaQueryList)
    const view = mount()
    await advance(500)
    expect(canvas.setViewport.mock.calls[0]?.[1]).toEqual({ duration: 0 })
    view.unmount()
  })
})
