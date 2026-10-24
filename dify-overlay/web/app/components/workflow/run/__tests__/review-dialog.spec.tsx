import type { Window as HappyDOMWindow } from 'happy-dom'
import { act, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vite-plus/test'
import ReviewDialog from '../review-dialog'

const { submit, productionForm } = vi.hoisted(() => ({
  submit: vi.fn(),
  productionForm: { active: false, waiting: false },
}))

vi.mock('@/app/components/base/markdown', () => ({
  Markdown: ({ content }: { content: string }) => <p>{content}</p>,
}))
vi.mock('@/service/use-share', () => ({
  useGetHumanInputForm: () => ({
    isLoading: false,
    data: productionForm.waiting
      ? {
          form_content: 'http://127.0.0.1:8794/storyboard-panel/d44508354fb76144befce35d',
          inputs: [],
          resolved_default_values: {},
          user_actions: [{ id: 'job_updated', title: '读取制作结果', button_style: 'primary' }],
        }
      : productionForm.active
        ? {
            form_content:
              '## 制作进度\n\n制作画面：第5/12段\n\n![实时制作进度](http://127.0.0.1:8794/presence/d44508354fb76144befce35d)',
            inputs: [],
            resolved_default_values: {},
            user_actions: [
              { id: 'check', title: '查看进度或成片', button_style: 'primary' },
              { id: 'continue', title: '继续制作', button_style: 'default' },
              { id: 'pause', title: '暂停', button_style: 'default' },
              { id: 'accept_duration', title: '接受这个时长', button_style: 'default' },
              { id: 'revise', title: '修改讲稿', button_style: 'default' },
            ],
          }
        : {
            form_content: '{{#$output.script#}}',
            inputs: [
              {
                type: 'paragraph',
                output_variable_name: 'script',
                default: { type: 'variable', selector: ['draft', 'script'], value: '' },
              },
            ],
            resolved_default_values: { script: '原讲稿' },
            user_actions: [{ id: 'approve', title: '确认讲稿', button_style: 'primary' }],
          },
  }),
  useSubmitHumanInputForm: () => ({ mutateAsync: submit }),
}))

describe('当前页面的确认弹窗', () => {
  beforeEach(() => {
    ;(window as unknown as HappyDOMWindow).happyDOM.settings.disableIframePageLoading = true
    vi.clearAllMocks()
    productionForm.active = false
    productionForm.waiting = false
    submit.mockResolvedValue({})
  })

  it.each(['complete', 'paused'])(
    '分镜等待的反复进度消息不推进节点，%s后只唤醒一次',
    async (status) => {
      productionForm.waiting = true
      const done = vi.fn()
      render(<ReviewDialog token="job-form" title="制作分镜" onSubmitted={done} />)
      expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
      const frame = screen.getByTitle('制作分镜') as HTMLIFrameElement
      const channel = new URL(frame.src).searchParams.get('channel')
      const emit = (value: string) =>
        window.dispatchEvent(
          new MessageEvent('message', {
            origin: 'http://127.0.0.1:8794',
            source: frame.contentWindow,
            data: { type: 'production-state', channel, status: value, height: 250 },
          }),
        )
      act(() => {
        for (let i = 0; i < 600; i++) emit('running')
      })
      expect(submit).not.toHaveBeenCalled()
      act(() => {
        emit(status)
        emit(status)
      })
      await waitFor(() => expect(done).toHaveBeenCalledTimes(1))
      expect(submit).toHaveBeenCalledExactlyOnceWith({
        token: 'job-form',
        data: { inputs: {}, action: 'job_updated' },
      })
    },
  )

  it.each(['failed', 'unknown', 'network_wait'])(
    '分镜%s时保留进度面板，重试完成后再继续流程',
    async (status) => {
      productionForm.waiting = true
      const done = vi.fn()
      render(<ReviewDialog token="retry-form" title="制作分镜" onSubmitted={done} />)
      const frame = screen.getByTitle('制作分镜') as HTMLIFrameElement
      const channel = new URL(frame.src).searchParams.get('channel')
      const emit = (value: string) =>
        window.dispatchEvent(
          new MessageEvent('message', {
            origin: 'http://127.0.0.1:8794',
            source: frame.contentWindow,
            data: { type: 'production-state', channel, status: value, height: 250 },
          }),
        )
      act(() => {
        emit(status)
        emit(status)
      })
      expect(submit).not.toHaveBeenCalled()
      expect(frame).toBeInTheDocument()
      act(() => emit('running'))
      expect(submit).not.toHaveBeenCalled()
      act(() => emit('complete'))
      await waitFor(() => expect(done).toHaveBeenCalledTimes(1))
      expect(submit).toHaveBeenCalledExactlyOnceWith({
        token: 'retry-form',
        data: { inputs: {}, action: 'job_updated' },
      })
    },
  )

  it('制作中的进度留在主页面，不弹人工确认或展示无效时长按钮', async () => {
    productionForm.active = true
    render(<ReviewDialog token="production-form" title="制作进度 · 确认" onSubmitted={vi.fn()} />)
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: '接受这个时长' })).not.toBeInTheDocument()
    expect(submit).not.toHaveBeenCalled()
  })

  it('关闭后重新打开仍保留未提交的编辑', async () => {
    const user = userEvent.setup()
    render(<ReviewDialog token="form-a" title="讲稿审核" onSubmitted={vi.fn()} />)
    expect(await screen.findByRole('dialog', { name: '讲稿审核' })).toBeVisible()
    const field = screen.getByRole('textbox', { name: 'script' })
    await user.clear(field)
    await user.type(field, '老师改过的讲稿')
    await user.click(screen.getByRole('button', { name: 'common.operation.close' }))
    await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument())
    await user.click(screen.getByRole('button', { name: 'workflow.liveProgress.review' }))
    expect(await screen.findByRole('textbox', { name: 'script' })).toHaveValue('老师改过的讲稿')
    expect(submit).not.toHaveBeenCalled()
  })

  it('一次提交后关闭弹窗并通知主页面更新，不打开新标签页', async () => {
    const user = userEvent.setup()
    const done = vi.fn()
    const open = vi.spyOn(window, 'open')
    render(<ReviewDialog token="form-a" title="讲稿审核" onSubmitted={done} />)
    await user.click(await screen.findByRole('button', { name: '确认讲稿' }))
    await waitFor(() => expect(done).toHaveBeenCalledTimes(1))
    expect(submit).toHaveBeenCalledWith({
      token: 'form-a',
      data: { inputs: { script: '原讲稿' }, action: 'approve' },
    })
    await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument())
    expect(open).not.toHaveBeenCalled()
    open.mockRestore()
  })

  it('服务端已提交时刷新状态并撤下旧入口，不要求再次确认', async () => {
    const user = userEvent.setup()
    const done = vi.fn()
    submit.mockRejectedValueOnce(
      new Response(
        JSON.stringify({ code: 'human_input_form_submitted', message: 'Already submitted' }),
        { status: 412 },
      ),
    )
    render(<ReviewDialog token="already-done" title="讲稿审核" onSubmitted={done} />)
    await user.click(await screen.findByRole('button', { name: '确认讲稿' }))
    await waitFor(() => expect(done).toHaveBeenCalledTimes(1))
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
    expect(
      screen.queryByRole('button', { name: 'workflow.liveProgress.review' }),
    ).not.toBeInTheDocument()
  })

  it('请求未完成时禁用重复提交', async () => {
    const user = userEvent.setup()
    let finish: (value: object) => void = () => {}
    submit.mockReturnValue(
      new Promise((resolve) => {
        finish = resolve
      }),
    )
    const done = vi.fn()
    render(<ReviewDialog token="form-a" title="讲稿审核" onSubmitted={done} />)
    const button = await screen.findByRole('button', { name: '确认讲稿' })
    await user.click(button)
    expect(button).toBeDisabled()
    await user.click(button)
    expect(submit).toHaveBeenCalledTimes(1)
    await act(async () => finish({}))
    expect(done).toHaveBeenCalledTimes(1)
  })

  it('提交失败保留内容并显示错误', async () => {
    const user = userEvent.setup()
    submit.mockRejectedValue(new Error('网络连接中断'))
    const done = vi.fn()
    render(<ReviewDialog token="form-a" title="讲稿审核" onSubmitted={done} />)
    await user.click(await screen.findByRole('button', { name: '确认讲稿' }))
    expect(await screen.findByRole('alert')).toHaveTextContent('网络连接中断')
    expect(screen.getByRole('textbox', { name: 'script' })).toHaveValue('原讲稿')
    expect(screen.getByRole('button', { name: '确认讲稿' })).toBeEnabled()
    expect(done).not.toHaveBeenCalled()
  })
})
