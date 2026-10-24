import type { Window as HappyDOMWindow } from 'happy-dom'
import type { WorkflowProcess } from '../../../types'
import type { SiteInfo } from '@/models/share'
import type { HumanInputFormData } from '@/types/workflow'
import { act, render, screen, waitFor } from '@testing-library/react'
import WorkflowBody from '@/app/components/app/text-generate/item/workflow-body'
import { UserActionButtonType } from '@/app/components/workflow/nodes/human-input/types'
import { WorkflowRunningStatus } from '@/app/components/workflow/types'
import HumanInputFormList from '../human-input-form-list'

vi.mock('@/app/components/base/markdown', () => ({
  Markdown: ({ content }: { content: string }) => <p>{content}</p>,
}))
vi.mock('@/app/components/workflow/run/tracing-panel', () => ({ default: () => null }))
vi.mock('@/app/components/app/text-generate/item/result-tab', () => ({ default: () => null }))

const waiting = (id = 'wait'): HumanInputFormData => ({
  form_id: id,
  node_id: 'storyboard_wait',
  node_title: '制作分镜',
  form_token: `token-${id}`,
  form_content: '正在制作分镜。\n\nhttp://127.0.0.1:8794/storyboard-panel/bccfc5f889b89d6658c74cb8',
  inputs: [],
  resolved_default_values: {},
  actions: [
    { id: 'job_updated', title: '读取制作结果', button_style: UserActionButtonType.Primary },
  ],
  expiration_time: null,
  display_in_ui: true,
})

const emit = (frame: HTMLIFrameElement, status: string) =>
  window.dispatchEvent(
    new MessageEvent('message', {
      origin: 'http://127.0.0.1:8794',
      source: frame.contentWindow,
      data: {
        type: 'production-state',
        channel: new URL(frame.src).searchParams.get('channel'),
        status,
        height: 250,
      },
    }),
  )

describe('published storyboard progress', () => {
  beforeEach(() => {
    ;(window as unknown as HappyDOMWindow).happyDOM.settings.disableIframePageLoading = true
  })

  it.each(['complete', 'paused'])(
    'keeps progress inline and advances only once when %s',
    async (status) => {
      const submit = vi.fn().mockResolvedValue(undefined)
      render(
        <HumanInputFormList humanInputFormDataList={[waiting()]} onHumanInputFormSubmit={submit} />,
      )
      expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
      expect(screen.queryByRole('button', { name: '读取制作结果' })).not.toBeInTheDocument()
      expect(
        screen.queryByRole('button', { name: 'workflow.liveProgress.review' }),
      ).not.toBeInTheDocument()
      const frame = screen.getByTitle('制作分镜') as HTMLIFrameElement
      act(() => {
        for (let i = 0; i < 600; i++) emit(frame, 'running')
        for (const value of ['failed', 'unknown', 'network_wait', 'pausing']) emit(frame, value)
      })
      expect(submit).not.toHaveBeenCalled()
      act(() => {
        emit(frame, status)
        emit(frame, status)
      })
      await waitFor(() => expect(screen.queryByTitle('制作分镜')).not.toBeInTheDocument())
      expect(submit).toHaveBeenCalledExactlyOnceWith('token-wait', {
        inputs: {},
        action: 'job_updated',
      })
    },
  )

  it('retries a failed result handoff without asking the teacher or resubmitting completed work', async () => {
    const submit = vi.fn().mockRejectedValueOnce(new Error('连接中断')).mockResolvedValue(undefined)
    render(
      <HumanInputFormList humanInputFormDataList={[waiting()]} onHumanInputFormSubmit={submit} />,
    )
    const frame = screen.getByTitle('制作分镜') as HTMLIFrameElement
    act(() => emit(frame, 'complete'))
    expect(await screen.findByRole('alert')).toHaveTextContent('连接中断')
    act(() => {
      emit(frame, 'complete')
      emit(frame, 'complete')
    })
    await waitFor(() => expect(screen.queryByTitle('制作分镜')).not.toBeInTheDocument())
    expect(submit).toHaveBeenCalledTimes(2)
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
  })

  it('requires an actual storyboard review even when its content includes the progress URL', () => {
    const submit = vi.fn()
    render(
      <HumanInputFormList
        humanInputFormDataList={[
          {
            ...waiting('review'),
            node_id: 'storyboard_review',
            node_title: '分镜 · 确认',
            actions: [
              {
                id: 'approve',
                title: '确认分镜，开始制作',
                button_style: UserActionButtonType.Primary,
              },
            ],
          },
        ]}
        onHumanInputFormSubmit={submit}
      />,
    )
    expect(screen.getByRole('dialog', { name: '分镜 · 确认' })).toBeVisible()
    expect(screen.getByRole('button', { name: '确认分镜，开始制作' })).toBeEnabled()
    expect(submit).not.toHaveBeenCalled()
  })

  it('retiring a background wait leaves an unrelated manual review open', async () => {
    const submit = vi
      .fn()
      .mockRejectedValueOnce(
        new Response(
          JSON.stringify({ code: 'human_input_form_submitted', message: 'Already submitted' }),
          { status: 412 },
        ),
      )
    const review = {
      ...waiting('review'),
      node_title: '讲稿 · 确认',
      actions: [{ id: 'approve', title: '确认讲稿', button_style: UserActionButtonType.Primary }],
    }
    render(
      <HumanInputFormList
        humanInputFormDataList={[waiting(), review]}
        onHumanInputFormSubmit={submit}
      />,
    )
    const frame = screen.getByTitle('制作分镜') as HTMLIFrameElement
    act(() => emit(frame, 'complete'))
    await waitFor(() => expect(screen.queryByTitle('制作分镜')).not.toBeInTheDocument())
    expect(screen.getByRole('dialog', { name: '讲稿 · 确认' })).toBeVisible()
    expect(submit).toHaveBeenCalledExactlyOnceWith('token-wait', {
      inputs: {},
      action: 'job_updated',
    })
  })

  it('keeps the same single progress panel active when switching to details', async () => {
    const submit = vi.fn().mockResolvedValue(undefined)
    const process = {
      status: WorkflowRunningStatus.Paused,
      runId: '13686558-723a-454e-a60b-1c0e2609709b',
      tracing: [{ node_id: 'storyboard_loop', title: '分镜', status: 'paused' }],
      humanInputFormDataList: [waiting()],
      humanInputFilledFormDataList: [
        {
          node_id: 'storyboard_wait',
          node_title: '制作分镜',
          rendered_content: waiting().form_content,
          action_id: 'job_updated',
          action_text: '读取制作结果',
        },
      ],
    } as WorkflowProcess
    const props = {
      content: '',
      depth: 1,
      isError: false,
      onSubmitHumanInputForm: submit,
      onSwitchTab: vi.fn(),
      showResultTabs: true,
      siteInfo: { show_workflow_steps: true } as SiteInfo,
      workflowProcessData: process,
    }
    const { container, rerender } = render(<WorkflowBody {...props} currentTab="RESULT" />)
    expect(container.querySelectorAll('iframe')).toHaveLength(1)
    expect(screen.queryByRole('img', { name: /workflowProcessPaused/ })).not.toBeInTheDocument()
    expect(screen.queryByText('读取制作结果')).not.toBeInTheDocument()
    const frame = screen.getByTitle('制作分镜') as HTMLIFrameElement
    rerender(<WorkflowBody {...props} currentTab="DETAIL" />)
    expect(screen.getByTitle('制作分镜')).toBe(frame)
    act(() => emit(frame, 'complete'))
    await waitFor(() =>
      expect(submit).toHaveBeenCalledExactlyOnceWith('token-wait', {
        inputs: {},
        action: 'job_updated',
      }),
    )
  })
})
