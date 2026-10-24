import type { NodeTracing } from '@/types/workflow'
import { describe, expect, it } from 'vite-plus/test'
import { BlockEnum } from '../../types'
import { activeExecution, latestExecutions } from '../live-nodes'

const entry = (
  node: string,
  status: string,
  time: number,
  type = BlockEnum.HttpRequest,
): NodeTracing => ({
  id: `${node}-${time}`,
  node_id: node,
  node_type: type,
  title: node,
  status,
  index: time,
  predecessor_node_id: '',
  inputs: {},
  inputs_truncated: false,
  process_data: {},
  process_data_truncated: false,
  outputs_truncated: false,
  elapsed_time: 0,
  metadata: { iterator_length: 0, iterator_index: 0, loop_length: 0, loop_index: 0 },
  created_at: time,
  created_by: { id: 'teacher', name: 'Teacher', email: '' },
  finished_at: 0,
})

describe('当前执行节点', () => {
  it('循环再次运行时使用新执行记录，不保留旧的暂停高亮', () => {
    const items = [
      entry('review', 'paused', 1),
      entry('review', 'succeeded', 2),
      entry('script', 'running', 3),
    ]
    expect(latestExecutions(items).get('review')?.status).toBe('succeeded')
    expect(activeExecution(items)?.node_id).toBe('script')
  })

  it('同时存在运行中的循环和子节点时显示正在处理的子节点', () => {
    expect(
      activeExecution([entry('script', 'running', 2), entry('loop', 'running', 3, BlockEnum.Loop)])
        ?.node_id,
    ).toBe('script')
  })

  it('从嵌套执行记录里找到等待确认的节点', () => {
    const loop = entry('loop', 'running', 1, BlockEnum.Loop)
    loop.details = [[entry('review', 'paused', 2, BlockEnum.HumanInput)]]
    expect(activeExecution([loop])?.node_id).toBe('review')
  })

  it('结束后不再保留运行节点', () => {
    expect(activeExecution([entry('script', 'succeeded', 2)])).toBeUndefined()
  })
})
