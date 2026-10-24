import { subscribeWorkflowEvents } from '../workflow-event-subscription'

type IOtherOptions = Parameters<typeof subscribeWorkflowEvents>[1]

const { watch } = vi.hoisted(() => ({ watch: vi.fn() }))
vi.mock('@/service/share', () => ({ watchWorkflowRun: watch }))

describe('existing workflow event subscriptions', () => {
  beforeEach(() => {
    vi.useFakeTimers()
    vi.clearAllMocks()
  })
  afterEach(() => {
    vi.clearAllTimers()
    vi.useRealTimers()
  })
  const events = () => watch.mock.lastCall![1] as IOtherOptions

  it('reconnects the same run after the server closes an idle review stream', () => {
    const stop = subscribeWorkflowEvents('run-existing', { isPublicAPI: true })
    vi.advanceTimersByTime(300000)
    events().onCompleted?.()
    vi.advanceTimersByTime(1000)
    expect(watch).toHaveBeenCalledTimes(2)
    expect(watch.mock.calls.map(([id]) => id)).toEqual(['run-existing', 'run-existing'])
    stop()
  })

  it('reconnects a transport failure without marking the running workflow failed', () => {
    const onError = vi.fn()
    const stop = subscribeWorkflowEvents('run-existing', { onError })
    const stale = events()
    stale.onError?.('network disconnected')
    stale.onCompleted?.()
    vi.advanceTimersByTime(1000)
    expect(watch).toHaveBeenCalledTimes(2)
    expect(onError).not.toHaveBeenCalled()
    stop()
  })

  it('cancels the current read and pending reconnection when the page stops observing', () => {
    let controller: AbortController | undefined
    subscribeWorkflowEvents('run-existing', {
      getAbortController: (value) => {
        controller = value
      },
    })
    const request = new AbortController()
    events().getAbortController?.(request)
    events().onCompleted?.()
    controller!.abort()
    vi.advanceTimersByTime(60000)
    expect(request.signal.aborted).toBe(true)
    expect(watch).toHaveBeenCalledTimes(1)
  })

  it('stops reconnecting after the workflow finishes and ignores late events from an old connection', () => {
    const finished = vi.fn()
    const started = vi.fn()
    const stop = subscribeWorkflowEvents('run-existing', {
      onWorkflowFinished: finished,
      onNodeStarted: started,
    })
    const stale = events()
    stale.onCompleted?.()
    vi.advanceTimersByTime(1000)
    stale.onNodeStarted?.({} as Parameters<NonNullable<IOtherOptions['onNodeStarted']>>[0])
    expect(started).not.toHaveBeenCalled()
    const current = events()
    current.onWorkflowFinished?.(
      {} as Parameters<NonNullable<IOtherOptions['onWorkflowFinished']>>[0],
    )
    current.onCompleted?.()
    vi.advanceTimersByTime(60000)
    expect(finished).toHaveBeenCalledTimes(1)
    expect(watch).toHaveBeenCalledTimes(2)
    stop()
  })
})
