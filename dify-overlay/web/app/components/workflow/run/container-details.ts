import type { NodeTracing } from '@/types/workflow'
import { NodeRunningStatus } from '../types'

const instanceNodes = (
  node: NodeTracing,
  all: NodeTracing[] | undefined,
  key: string,
  kind: 'loop' | 'iteration',
) => {
  if (!all) return []
  const parallel = all.filter((item) => item.execution_metadata?.parallel_mode_run_id === key)
  if (parallel.length) return parallel
  const index = Number.parseInt(key, 10)
  if (Number.isNaN(index)) return []
  return all.filter(
    (item) =>
      item.execution_metadata?.[`${kind}_id`] === node.node_id &&
      item.execution_metadata?.[`${kind}_index`] === index,
  )
}

export const getLoopDetails = (node: NodeTracing, all?: NodeTracing[]) => ({
  list: node.details?.length
    ? node.details
    : Object.keys(node.execution_metadata?.loop_duration_map || {})
        .map((key) => instanceNodes(node, all, key, 'loop'))
        .filter((group) => group.length > 0),
  durationMap: node.loopDurationMap || node.execution_metadata?.loop_duration_map || {},
  variableMap: node.execution_metadata?.loop_variable_map || {},
})

export const getIterationDetails = (node: NodeTracing, all?: NodeTracing[]) => {
  const durationMap = node.iterDurationMap || node.execution_metadata?.iteration_duration_map || {}
  if (!node.execution_metadata?.iteration_duration_map)
    return { list: node.details || [], durationMap }
  const list = Object.keys(node.execution_metadata.iteration_duration_map)
    .map((key) => instanceNodes(node, all, key, 'iteration'))
    .filter((group) => group.length > 0)
  if (!all || !node.details?.length) return { list, durationMap }
  const indices = new Set(
    list.flatMap((group) => group.map((item) => item.execution_metadata?.iteration_index)),
  )
  node.details.forEach((group, index) => {
    if (!indices.has(index) && group.some((item) => item.status === NodeRunningStatus.Failed))
      list.push(group)
  })
  list.sort(
    (a, b) =>
      (a[0]?.execution_metadata?.iteration_index ?? 0) -
      (b[0]?.execution_metadata?.iteration_index ?? 0),
  )
  return { list, durationMap }
}

export const findTraceExecution = (nodes: NodeTracing[], id: string): NodeTracing | undefined => {
  for (const node of nodes) {
    if (node.id === id) return node
    const child = findTraceExecution(node.parallelDetail?.children || [], id)
    if (child) return child
  }
}
