import type { NodeTracing } from '@/types/workflow'

// 同一节点在循环里可以执行多次，使用最近一次执行记录。
export const latestExecutions = (items: NodeTracing[]) => {
  const latest = new Map<string, NodeTracing>()
  const visit = (item: NodeTracing) => {
    const previous = latest.get(item.node_id)
    if (!previous || item.created_at >= previous.created_at) latest.set(item.node_id, item)
    item.details?.flat().forEach(visit)
  }
  items.forEach(visit)
  return latest
}

export const activeExecution = (items: NodeTracing[]) => {
  const active = [...latestExecutions(items).values()]
    .filter((item) => item.status === 'running' || item.status === 'paused')
    .sort((a, b) => a.created_at - b.created_at || a.index - b.index)
  return (
    active.filter((item) => item.node_type !== 'loop' && item.node_type !== 'iteration').at(-1) ||
    active.at(-1)
  )
}

// 制作等待节点和所在循环展示制作服务的状态，保留原始执行记录。
export const productionExecutions = (
  items: NodeTracing[],
  waitingNodeId: string | undefined,
  status: string,
  waitingReason = '',
) => {
  if (!waitingNodeId) return items
  const latest = latestExecutions(items)
  const ids = new Set<string>()
  let current = latest.get(waitingNodeId)
  while (current && !ids.has(current.id)) {
    ids.add(current.id)
    const parent =
      current.execution_metadata?.loop_id ||
      current.execution_metadata?.iteration_id ||
      current.loop_id ||
      current.iteration_id
    current = parent ? latest.get(parent) : undefined
  }
  const shown = ['starting', 'queued', 'armed', 'running', 'complete'].includes(status)
    ? 'running'
    : ['failed', 'unknown'].includes(status)
      ? 'failed'
      : 'paused'
  const update = (item: NodeTracing): NodeTracing => ({
    ...item,
    ...(ids.has(item.id)
      ? { status: shown, ...(status === 'network_wait' ? { error: waitingReason } : {}) }
      : {}),
    ...(item.details ? { details: item.details.map((row) => row.map(update)) } : {}),
  })
  return items.map(update)
}
