import type { FormInputItem } from '@/app/components/workflow/nodes/human-input/types'
import type { HumanInputFormData } from '@/types/workflow'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { UserActionButtonType } from '@/app/components/workflow/nodes/human-input/types'
import HumanInputForm from '../human-input-form'

vi.mock('@/app/components/base/markdown', () => ({
  Markdown: ({ content }: { content: string }) => <p>{content}</p>,
}))

const form: HumanInputFormData = {
  form_id: 'guidance-test',
  node_id: 'requirements_review',
  node_title: '课程要求',
  form_token: 'test-token',
  display_in_ui: true,
  expiration_time: null,
  form_content: '### 主题\n\n{{#$output.topic#}}\n\n### 画面风格\n\n{{#$output.style_preset#}}',
  inputs: [
    {
      type: 'paragraph',
      output_variable_name: 'topic',
      label: '主题',
      required: true,
      default: { type: 'variable', selector: ['requirements_data', 'topic'], value: '' },
    },
    {
      type: 'select',
      output_variable_name: 'style_preset',
      label: '画面风格',
      default: { type: 'variable', selector: ['requirements_data', 'style_preset'], value: '' },
      option_source: { type: 'constant', selector: [], value: ['暖色图解', '空间代码动画'] },
    },
  ] as FormInputItem[],
  resolved_default_values: { topic: '注意力机制', style_preset: '空间代码动画' },
  actions: [{ id: 'approve', title: '确认课程要求', button_style: UserActionButtonType.Primary }],
}

describe('审核表单默认值和缺项提示', () => {
  it('刷新表单数据不会覆盖手动改过的风格，可选段落留空不拦截', async () => {
    const user = userEvent.setup()
    const optionalForm = {
      ...form,
      form_content: `${form.form_content}\n{{#$output.feedback#}}`,
      inputs: [
        ...form.inputs,
        {
          type: 'paragraph',
          output_variable_name: 'feedback',
          default: { type: 'constant', value: '', selector: [] },
        },
      ] as FormInputItem[],
    }
    const { rerender } = render(<HumanInputForm formData={optionalForm} />)
    await user.click(screen.getByRole('combobox', { name: '画面风格' }))
    await user.click(screen.getByRole('option', { name: '暖色图解' }))
    rerender(
      <HumanInputForm
        formData={{
          ...optionalForm,
          resolved_default_values: { ...optionalForm.resolved_default_values },
        }}
      />,
    )
    expect(screen.getByRole('combobox', { name: '画面风格' })).toHaveTextContent('暖色图解')
    expect(screen.getByRole('button', { name: '确认课程要求' })).toBeEnabled()
  })
  it('沿用上游风格，不要求重复选择，并提交同一选择', async () => {
    const user = userEvent.setup()
    const submit = vi.fn()
    render(<HumanInputForm formData={form} onSubmit={submit} />)
    expect(screen.getByRole('combobox', { name: '画面风格' })).toHaveTextContent('空间代码动画')
    await user.click(screen.getByRole('button', { name: '确认课程要求' }))
    expect(submit).toHaveBeenCalledWith('test-token', {
      action: 'approve',
      inputs: { topic: '注意力机制', style_preset: '空间代码动画' },
    })
  })

  it('标出空的必填项，并可从缺项列表定位，填写后解除提示', async () => {
    const user = userEvent.setup()
    render(
      <HumanInputForm
        formData={{ ...form, resolved_default_values: { topic: '', style_preset: '空间代码动画' } }}
      />,
    )
    const topic = screen.getByRole('textbox', { name: '主题' })
    expect(topic).toHaveAttribute('aria-invalid', 'true')
    expect(screen.getByRole('button', { name: '确认课程要求' })).toBeDisabled()
    await user.click(screen.getByRole('button', { name: '主题' }))
    expect(topic).toHaveFocus()
    await user.type(topic, '注意力机制')
    expect(topic).not.toHaveAttribute('aria-invalid', 'true')
    expect(screen.getByRole('button', { name: '确认课程要求' })).toBeEnabled()
  })

  it('不会把缺失或不在选项中的默认值伪装成已选择', () => {
    render(
      <HumanInputForm
        formData={{
          ...form,
          resolved_default_values: { topic: '注意力机制', style_preset: '已删除的风格' },
        }}
      />,
    )
    expect(screen.getByRole('combobox', { name: '画面风格' })).toHaveAttribute(
      'aria-invalid',
      'true',
    )
    expect(screen.getByRole('button', { name: '确认课程要求' })).toBeDisabled()
  })
})
