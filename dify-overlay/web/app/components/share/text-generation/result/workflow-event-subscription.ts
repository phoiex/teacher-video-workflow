import { watchWorkflowRun } from '@/service/share'

type IOtherOptions = Parameters<typeof watchWorkflowRun>[1]

// 订阅只读取已有执行；空闲断流后重新读取服务端快照。
export const subscribeWorkflowEvents = (runId: string, options: IOtherOptions) => {
  const lifetime = new AbortController()
  let request: AbortController | undefined
  let timer: ReturnType<typeof setTimeout> | undefined
  let finished = false
  let attempt = 0
  let generation = 0

  const stop = () => {
    generation += 1
    clearTimeout(timer)
    request?.abort()
  }
  lifetime.signal.addEventListener('abort', stop, { once: true })
  options.getAbortController?.(lifetime)

  const connect = () => {
    if (lifetime.signal.aborted || finished) return
    const current = ++generation
    const active = () => !lifetime.signal.aborted && !finished && generation === current
    const retry = () => {
      if (!active() || timer) return
      generation += 1
      request?.abort()
      timer = setTimeout(
        () => {
          timer = undefined
          connect()
        },
        Math.min(1000 * 2 ** attempt++, 15000),
      )
    }
    const guarded = Object.fromEntries(
      Object.entries(options).map(([name, value]) => [
        name,
        typeof value === 'function'
          ? (...args: unknown[]) => active() && Reflect.apply(value, undefined, args)
          : value,
      ]),
    ) as IOtherOptions
    void watchWorkflowRun(runId, {
      ...guarded,
      silent: true,
      getAbortController: (controller) => {
        request = controller
        if (!active()) controller.abort()
      },
      onWorkflowStarted: (event) => {
        if (!active()) return
        attempt = 0
        options.onWorkflowStarted?.(event)
      },
      onWorkflowFinished: (event) => {
        if (!active()) return
        finished = true
        clearTimeout(timer)
        options.onWorkflowFinished?.(event)
        request?.abort()
      },
      onError: retry,
      onCompleted: retry,
    })
  }
  connect()
  return () => lifetime.abort()
}
