'use client'

import type { NodeTracing } from '@/types/workflow'
import ProductionPanel from './production-panel'
import { storyboardProgressUrl } from './storyboard-target'

const NO_ACTIONS: { id: string }[] = []
const ignoreAction = async () => {}

const StoryboardProgress = ({
  nodes,
  title,
  runId,
}: {
  nodes: NodeTracing[]
  title: string
  runId?: string
}) => {
  const url = storyboardProgressUrl(nodes, runId)
  if (!url) return null
  return (
    <ProductionPanel
      key={url}
      url={url}
      title={title}
      actions={NO_ACTIONS}
      onAction={ignoreAction}
    />
  )
}

export default StoryboardProgress
