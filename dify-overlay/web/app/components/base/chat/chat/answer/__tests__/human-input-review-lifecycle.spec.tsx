import type { HumanInputFormData } from '@/types/workflow'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { UserActionButtonType } from '@/app/components/workflow/nodes/human-input/types'
import { InputVarType } from '@/app/components/workflow/types'
import HumanInputFormList from '../human-input-form-list'

vi.mock('@/app/components/base/markdown', () => ({
  Markdown: ({ content }: { content: string }) => <p>{content}</p>,
}))

const form = (id: string, title: string): HumanInputFormData => ({
  form_id: id,
  node_id: id,
  node_title: title,
  form_token: `token-${id}`,
  form_content: '{{#$output.topic#}}',
  inputs: [
    {
      type: InputVarType.paragraph,
      output_variable_name: 'topic',
      default: { type: 'constant', selector: [], value: '注意力机制' },
    },
  ],
  resolved_default_values: { topic: '注意力机制' },
  actions: [{ id: 'approve', title: '确认', button_style: UserActionButtonType.Primary }],
  expiration_time: null,
  display_in_ui: true,
})

describe('review lifecycle with delayed workflow events', () => {
  it.each(['课程要求', '讲稿', '分镜', '时长确认'])(
    'removes the submitted %s form even while the parent still has stale data',
    async (title) => {
      const user = userEvent.setup()
      const submit = vi.fn().mockResolvedValue(undefined)
      const pending = form('first', title)
      const { rerender } = render(
        <HumanInputFormList humanInputFormDataList={[pending]} onHumanInputFormSubmit={submit} />,
      )
      await user.click(screen.getByRole('button', { name: '确认' }))
      await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument())
      expect(
        screen.queryByRole('button', { name: 'workflow.liveProgress.review' }),
      ).not.toBeInTheDocument()
      rerender(
        <HumanInputFormList
          humanInputFormDataList={[{ ...pending }]}
          onHumanInputFormSubmit={submit}
        />,
      )
      expect(
        screen.queryByRole('button', { name: 'workflow.liveProgress.review' }),
      ).not.toBeInTheDocument()
      rerender(
        <HumanInputFormList
          humanInputFormDataList={[pending, form('second', '下一次确认')]}
          onHumanInputFormSubmit={submit}
        />,
      )
      expect(await screen.findByRole('dialog', { name: '下一次确认' })).toBeVisible()
      expect(submit).toHaveBeenCalledTimes(1)
    },
  )

  it('allows a failed submission to be closed, reopened and retried with edits preserved', async () => {
    const user = userEvent.setup()
    const submit = vi
      .fn()
      .mockRejectedValueOnce(new Error('连接中断'))
      .mockResolvedValueOnce(undefined)
    render(
      <HumanInputFormList
        humanInputFormDataList={[form('review', '讲稿')]}
        onHumanInputFormSubmit={submit}
      />,
    )
    await user.clear(screen.getByRole('textbox', { name: 'topic' }))
    await user.type(screen.getByRole('textbox', { name: 'topic' }), '老师修改的内容')
    await user.click(screen.getByRole('button', { name: '确认' }))
    expect(await screen.findByRole('alert')).toHaveTextContent('连接中断')
    await user.click(screen.getByRole('button', { name: 'common.operation.close' }))
    await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument())
    await user.click(screen.getByRole('button', { name: 'workflow.liveProgress.review' }))
    expect(screen.getByRole('textbox', { name: 'topic' })).toHaveValue('老师修改的内容')
    await user.click(screen.getByRole('button', { name: '确认' }))
    await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument())
    expect(submit).toHaveBeenCalledTimes(2)
  })

  it('retires a form when the server confirms it was already submitted', async () => {
    const user = userEvent.setup()
    const submit = vi
      .fn()
      .mockRejectedValue(
        new Response(
          JSON.stringify({ code: 'human_input_form_submitted', message: 'Already submitted' }),
          { status: 412 },
        ),
      )
    render(
      <HumanInputFormList
        humanInputFormDataList={[form('old', '课程要求')]}
        onHumanInputFormSubmit={submit}
      />,
    )
    await user.click(screen.getByRole('button', { name: '确认' }))
    await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument())
    expect(
      screen.queryByRole('button', { name: 'workflow.liveProgress.review' }),
    ).not.toBeInTheDocument()
    expect(screen.queryByRole('alert')).not.toBeInTheDocument()
    expect(submit).toHaveBeenCalledTimes(1)
  })

  it('closes the review window when multiple forms are waiting without opening another one', async () => {
    const user = userEvent.setup()
    render(
      <HumanInputFormList
        humanInputFormDataList={[form('a', '需求'), form('b', '讲稿')]}
        onHumanInputFormSubmit={vi.fn()}
      />,
    )
    await user.click(screen.getByRole('button', { name: 'common.operation.close' }))
    await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument())
    expect(screen.getAllByRole('button', { name: 'workflow.liveProgress.review' })).toHaveLength(2)
  })
})
