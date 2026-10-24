import type { NodeTracing } from '@/types/workflow'
import { activeExecution, latestExecutions } from './live-nodes'

// 仅在本课程的分镜生成阶段显示本地进度；确认表单继续由原组件负责。
export const storyboardProgressUrl = (nodes: NodeTracing[], runId?: string) => {
  const active = activeExecution(nodes)
  if (
    !active?.node_id.startsWith('storyboard_') ||
    [
      'storyboard_review',
      'storyboard_wait',
      'storyboard_resume',
      'storyboard_apply',
      'storyboard_apply_args',
      'storyboard_applied',
      'storyboard_accepted',
    ].includes(active.node_id)
  )
    return undefined
  const cid = latestExecutions(nodes).get('create_data')?.outputs?.course_id
  if (typeof cid === 'string' && /^[a-f0-9]{24}$/.test(cid))
    return `http://127.0.0.1:8794/storyboard-panel/${cid}`
  if (runId && /^[a-f0-9-]{36}$/.test(runId))
    return `http://127.0.0.1:8794/storyboard-run-panel/${runId}`
  return undefined
}
