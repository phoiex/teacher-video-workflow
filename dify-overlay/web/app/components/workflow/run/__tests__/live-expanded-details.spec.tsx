import type { ComponentProps } from 'react'
import { fireEvent, render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { useState } from 'react'
import { createNodeTracing } from '@/app/components/workflow/__tests__/fixtures'
import { BlockEnum } from '../../types'
import IterationLogTrigger from '../iteration-log/iteration-log-trigger'
import LoopLogTrigger from '../loop-log/loop-log-trigger'
import TracingPanel from '../tracing-panel'

vi.mock('../node', () => ({
  default: function TraceRow({
    nodeInfo,
    allExecutions,
    onShowLoopDetail,
    onShowIterationDetail,
  }: ComponentProps<typeof import('../node').default>) {
    const [open, setOpen] = useState(false)
    return (
      <div>
        <span>{`${nodeInfo.title} ${nodeInfo.status}`}</span>
        {nodeInfo.node_type === BlockEnum.Loop && onShowLoopDetail && (
          <LoopLogTrigger
            nodeInfo={nodeInfo}
            allExecutions={allExecutions}
            onShowLoopResultList={onShowLoopDetail}
          />
        )}
        {nodeInfo.node_type === BlockEnum.Iteration && onShowIterationDetail && (
          <IterationLogTrigger
            nodeInfo={nodeInfo}
            allExecutions={allExecutions}
            onShowIterationResultList={onShowIterationDetail}
          />
        )}
        {nodeInfo.node_type === BlockEnum.Code && (
          <button type="button" onClick={() => setOpen((v) => !v)}>
            查看{nodeInfo.title}
          </button>
        )}
        {open && <p>{nodeInfo.title}的详情已展开</p>}
      </div>
    )
  },
}))

describe.each([BlockEnum.Loop, BlockEnum.Iteration])('展开的%s详情跟随后台更新', (kind) => {
  const parent = createNodeTracing({
    id: 'execution-1',
    node_id: 'script-group',
    node_type: kind,
    title: '讲稿',
    status: 'running',
  })
  const child = (id: string, title: string, status: string, round = 0) =>
    createNodeTracing({
      id,
      node_id: id,
      title,
      status,
      execution_metadata: {
        total_tokens: 0,
        total_price: 0,
        currency: 'USD',
        ...(kind === BlockEnum.Loop
          ? { loop_id: 'script-group', loop_index: round }
          : { iteration_id: 'script-group', iteration_index: round }),
      },
    })
  it('不用返回重开即可看到完成状态和新增步骤，已经展开的内容保持展开', async () => {
    const user = userEvent.setup()
    const before = [parent, child('deslop', '调整讲稿表达', 'running')]
    const { rerender } = render(<TracingPanel list={before} />)
    await user.click(screen.getByRole('button', { name: new RegExp(`workflow.nodes.${kind}.`) }))
    const header = `workflow.singleRun.${kind} 1`
    fireEvent.click(screen.getByText(header))
    await user.click(screen.getByRole('button', { name: '查看调整讲稿表达' }))
    expect(screen.getByText('调整讲稿表达 running')).toBeInTheDocument()
    rerender(
      <TracingPanel
        list={[
          { ...parent, status: 'succeeded' },
          child('deslop', '调整讲稿表达', 'succeeded'),
          child('review', '讲稿确认', 'succeeded'),
        ]}
      />,
    )
    expect(screen.getByText('调整讲稿表达 succeeded')).toBeInTheDocument()
    expect(screen.getByText('讲稿确认 succeeded')).toBeInTheDocument()
    expect(screen.getByText('调整讲稿表达的详情已展开')).toBeVisible()
    expect(screen.queryByText('调整讲稿表达 running')).not.toBeInTheDocument()
    expect(screen.getByText(header)).toBeInTheDocument()
  })
})
