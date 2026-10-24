import type { Window as HappyDOMWindow } from 'happy-dom'
import { act, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vite-plus/test'
import ProductionPanel from '../production-panel'
import { productionPanelUrl } from '../production-target'

const url = 'http://127.0.0.1:8794/production-panel/d44508354fb76144befce35d'
const actions = ['check', 'pause', 'continue', 'accept_duration', 'revise'].map((id) => ({ id }))

describe('本机制作进度与Dify动作桥接', () => {
  beforeEach(() => {
    ;(window as unknown as HappyDOMWindow).happyDOM.settings.disableIframePageLoading = true
  })
  it('只识别已知本机制作器与完整动作集合，普通讲稿不进入进度页', () => {
    expect(
      productionPanelUrl(
        '![进度](http://127.0.0.1:8794/presence/d44508354fb76144befce35d)',
        actions,
      ),
    ).toBe(url)
    expect(productionPanelUrl('普通讲稿', actions)).toBeUndefined()
    expect(
      productionPanelUrl('http://evil.test/presence/d44508354fb76144befce35d', actions),
    ).toBeUndefined()
  })

  it('完成事件只推进一次，拒绝其他来源或不匹配的页面标识', async () => {
    const onAction = vi.fn().mockResolvedValue(undefined)
    const onStatusChange = vi.fn()
    render(
      <ProductionPanel
        url={url}
        title="制作进度"
        actions={actions}
        onAction={onAction}
        onStatusChange={onStatusChange}
      />,
    )
    const frame = screen.getByTitle('制作进度') as HTMLIFrameElement
    const channel = new URL(frame.src).searchParams.get('channel')
    const event = { type: 'production-action', channel, action: 'check' }
    fireEvent(
      window,
      new MessageEvent('message', {
        origin: 'https://elsewhere.test',
        source: frame.contentWindow,
        data: event,
      }),
    )
    fireEvent(
      window,
      new MessageEvent('message', {
        origin: new URL(url).origin,
        source: frame.contentWindow,
        data: { ...event, channel: 'old' },
      }),
    )
    expect(onAction).not.toHaveBeenCalled()
    fireEvent(
      window,
      new MessageEvent('message', {
        origin: new URL(url).origin,
        source: frame.contentWindow,
        data: { type: 'production-state', channel, status: 'complete', height: 480 },
      }),
    )
    expect(onStatusChange).toHaveBeenCalledWith('complete')
    await act(async () => {
      fireEvent(
        window,
        new MessageEvent('message', {
          origin: new URL(url).origin,
          source: frame.contentWindow,
          data: event,
        }),
      )
      fireEvent(
        window,
        new MessageEvent('message', {
          origin: new URL(url).origin,
          source: frame.contentWindow,
          data: event,
        }),
      )
    })
    await waitFor(() => expect(onAction).toHaveBeenCalledExactlyOnceWith('check'))
  })
})
