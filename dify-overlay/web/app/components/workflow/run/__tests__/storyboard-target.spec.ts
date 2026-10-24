import type { NodeTracing } from '@/types/workflow'
import { describe, expect, it } from 'vite-plus/test'
import { BlockEnum } from '../../types'
import { storyboardProgressUrl } from '../storyboard-target'

const entry = (
  id: string,
  status: string,
  index: number,
  outputs?: Record<string, unknown>,
): NodeTracing => ({
  id,
  node_id: id,
  node_type: BlockEnum.HttpRequest,
  title: id,
  status,
  index,
  predecessor_node_id: '',
  inputs: {},
  inputs_truncated: false,
  process_data: {},
  process_data_truncated: false,
  outputs,
  outputs_truncated: false,
  elapsed_time: 0,
  metadata: { iterator_length: 0, iterator_index: 0, loop_length: 0, loop_index: 0 },
  created_at: index,
  created_by: { id: 'teacher', name: 'Teacher', email: '' },
  finished_at: 0,
})
const cid = 'd44508354fb76144befce35d'
const created = entry('create_data', 'succeeded', 1, { course_id: cid })

describe('分镜进度入口', () => {
  it('制作时关联准确课程', () => {
    expect(storyboardProgressUrl([created, entry('storyboard_show', 'running', 2)])).toBe(
      `http://127.0.0.1:8794/storyboard-panel/${cid}`,
    )
  })
  it.each(['storyboard_review', 'storyboard_resume'])('需要老师操作时保留原生表单：%s', (id) => {
    expect(storyboardProgressUrl([created, entry(id, 'paused', 3)])).toBeUndefined()
  })
  it('公开页面隐藏节点输出时按运行编号关联进度', () => {
    const run = 'dde5637e-7fa4-46da-aaa9-9e9f08b67409'
    expect(storyboardProgressUrl([entry('storyboard_loop', 'running', 1)], run)).toBe(
      `http://127.0.0.1:8794/storyboard-run-panel/${run}`,
    )
  })
  it('其他阶段及不合法的课程编号不嵌入本地页面', () => {
    expect(storyboardProgressUrl([created, entry('script_show', 'running', 2)])).toBeUndefined()
    expect(
      storyboardProgressUrl([
        entry('create_data', 'succeeded', 1, { course_id: '../outside' }),
        entry('storyboard_show', 'running', 2),
      ]),
    ).toBeUndefined()
  })
})
