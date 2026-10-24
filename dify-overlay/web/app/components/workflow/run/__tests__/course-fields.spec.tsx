import { fireEvent, render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import CourseKnowledge from '../course-knowledge'
import { parseKnowledgeChoice } from '../course-knowledge-data'
import StylePreviewOptions from '../style-preview-options'

describe('course material selection', () => {
  it('keeps the suggested selection and submits the changed knowledge ids', () => {
    const value = parseKnowledgeChoice(
      JSON.stringify({
        kind: 'course-knowledge-v1',
        options: [
          { id: 'K01', title: '词向量', summary: '数字表示', source: 'NLP.pdf 第1页' },
          { id: 'K02', title: '注意力', summary: '加权汇总', source: 'NLP.pdf 第2页' },
        ],
        selected: ['K02'],
      }),
    )!
    const onChange = vi.fn()
    render(<CourseKnowledge value={value} label="本次知识点" onChange={onChange} />)
    expect(screen.getByRole('checkbox', { name: '注意力' })).toBeChecked()
    expect(screen.getByRole('checkbox', { name: '词向量' })).not.toBeChecked()
    expect(screen.getByText('NLP.pdf 第2页')).toBeInTheDocument()
    fireEvent.click(screen.getByRole('checkbox', { name: '词向量' }))
    expect(JSON.parse(onChange.mock.calls[0]![0]).selected).toEqual(['K02', 'K01'])
  })

  it('uses the existing style value when a reference card is clicked', () => {
    const onChange = vi.fn()
    render(
      <StylePreviewOptions
        options={['暖色图解', 'ASCII 终端科技', '空间代码动画', '自由设计']}
        value="暖色图解"
        onChange={onChange}
      />,
    )
    expect(screen.getByRole('button', { name: '暖色图解' })).toHaveAttribute('aria-pressed', 'true')
    fireEvent.click(screen.getByRole('button', { name: '空间代码动画' }))
    expect(onChange).toHaveBeenCalledWith('空间代码动画')
    expect(screen.getAllByRole('button')).toHaveLength(3)
  })
})
