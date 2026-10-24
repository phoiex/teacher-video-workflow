import { describe, expect, it } from 'vite-plus/test'
import { viewportForNode } from '../live-viewport'

describe('当前节点在可见画布中居中', () => {
  it('定位循环内的子节点并避开右侧面板', () => {
    const nodes = [
      { id: 'loop', position: { x: 400, y: 1000 } },
      { id: 'child', parentId: 'loop', position: { x: 1360, y: 80 }, width: 244, height: 110 },
    ]
    const viewport = viewportForNode('child', nodes, 1600, 900, 500)!
    expect((400 + 1360 + 122) * viewport.zoom + viewport.x).toBe(550)
    expect((1000 + 80 + 55) * viewport.zoom + viewport.y).toBe(450)
    expect(viewport.zoom).toBe(1)
  })

  it('已有绝对坐标时不重复叠加父节点偏移', () => {
    const nodes = [
      { id: 'loop', position: { x: 400, y: 1000 } },
      {
        id: 'child',
        parentId: 'loop',
        position: { x: 100, y: 80 },
        positionAbsolute: { x: 500, y: 1080 },
        width: 244,
        height: 110,
      },
    ]
    const viewport = viewportForNode('child', nodes, 1600, 900, 500)!
    expect(622 * viewport.zoom + viewport.x).toBe(550)
    expect(1135 * viewport.zoom + viewport.y).toBe(450)
  })

  it('较窄的可见区域会缩小节点，保留周围空间', () => {
    const nodes = [{ id: 'node', position: { x: 300, y: 80 }, width: 244, height: 110 }]
    const viewport = viewportForNode('node', nodes, 800, 600, 500)!
    const left = 300 * viewport.zoom + viewport.x
    const right = left + 244 * viewport.zoom
    expect(viewport.zoom).toBeLessThan(1)
    expect(left).toBeCloseTo(48)
    expect(right).toBeCloseTo(252)
  })
})
