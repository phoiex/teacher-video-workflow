import type { Node } from '../types'

type PositionedNode = Pick<
  Node,
  'id' | 'position' | 'positionAbsolute' | 'parentId' | 'width' | 'height'
>

export const viewportForNode = (
  nodeId: string,
  nodes: PositionedNode[],
  width: number,
  height: number,
  rightInset: number,
) => {
  const node = nodes.find((item) => item.id === nodeId)
  const visibleWidth = width - rightInset
  if (!node || visibleWidth <= 0 || height <= 0) return

  let { x, y } = node.positionAbsolute || node.position
  if (!node.positionAbsolute) {
    let parentId = node.parentId
    const visited = new Set([node.id])
    while (parentId && !visited.has(parentId)) {
      const parent = nodes.find((item) => item.id === parentId)
      if (!parent) return
      visited.add(parentId)
      x += parent.position.x
      y += parent.position.y
      parentId = parent.parentId
    }
  }
  const nodeWidth = node.width || 244
  const nodeHeight = node.height || 110
  const zoom = Math.max(
    0.25,
    Math.min(1, (visibleWidth - 96) / nodeWidth, (height - 160) / nodeHeight),
  )
  return {
    x: visibleWidth / 2 - (x + nodeWidth / 2) * zoom,
    y: height / 2 - (y + nodeHeight / 2) * zoom,
    zoom,
  }
}
