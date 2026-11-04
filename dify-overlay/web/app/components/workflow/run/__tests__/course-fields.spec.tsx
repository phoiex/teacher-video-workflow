import { fireEvent, render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
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

  it('plays a sample without changing the selected style', () => {
    const onChange = vi.fn()
    render(
      <StylePreviewOptions
        options={['暖色图解', '手绘白板']}
        value="暖色图解"
        onChange={onChange}
      />,
    )
    const video = screen.getByLabelText('手绘白板', { selector: 'video' })
    fireEvent.play(video)
    expect(onChange).not.toHaveBeenCalled()
    expect(screen.getByRole('button', { name: '暖色图解' })).toHaveAttribute('aria-pressed', 'true')
    fireEvent.click(screen.getByRole('button', { name: '手绘白板' }))
    expect(onChange).toHaveBeenCalledWith('手绘白板')
  })

  it('pauses the previous sample when another starts playing', () => {
    render(<StylePreviewOptions options={['暖色图解', '手绘白板']} onChange={vi.fn()} />)
    const first = screen.getByLabelText('暖色图解', { selector: 'video' }) as HTMLVideoElement
    const second = screen.getByLabelText('手绘白板', { selector: 'video' })
    const pause = vi.spyOn(first, 'pause').mockImplementation(() => {})
    fireEvent.play(first)
    fireEvent.play(second)
    expect(pause).toHaveBeenCalledOnce()
  })

  it('follows the course language for video, poster and captions', () => {
    const { rerender } = render(
      <StylePreviewOptions options={['暖色图解']} courseLanguage="English" onChange={vi.fn()} />,
    )
    const english = screen.getByLabelText('暖色图解', { selector: 'video' })
    expect(english).toHaveAttribute('src', '/teacher-style/videos/en/warm.mp4')
    expect(english).toHaveAttribute('poster', '/teacher-style/posters/en/warm.jpg')
    expect(english.querySelector('track')).toHaveAttribute('srcLang', 'en')
    rerender(
      <StylePreviewOptions
        options={['暖色图解']}
        courseLanguage="中文（普通话）"
        onChange={vi.fn()}
      />,
    )
    expect(screen.getByLabelText('暖色图解', { selector: 'video' })).toHaveAttribute(
      'src',
      '/teacher-style/videos/warm.mp4',
    )
  })

  it('switches the preview without changing style, and can follow the course again', async () => {
    const user = userEvent.setup()
    const onChange = vi.fn()
    render(
      <StylePreviewOptions
        options={['暖色图解']}
        value="暖色图解"
        courseLanguage="zh"
        onChange={onChange}
      />,
    )
    const first = screen.getByLabelText('暖色图解', { selector: 'video' }) as HTMLVideoElement
    const pause = vi.spyOn(first, 'pause').mockImplementation(() => {})
    fireEvent.play(first)
    await user.click(screen.getByRole('radio', { name: 'English' }))
    expect(pause).toHaveBeenCalled()
    expect(screen.getByLabelText('暖色图解', { selector: 'video' })).toHaveAttribute(
      'src',
      '/teacher-style/videos/en/warm.mp4',
    )
    expect(onChange).not.toHaveBeenCalled()
    expect(screen.getByRole('button', { name: '暖色图解' })).toHaveAttribute('aria-pressed', 'true')
    await user.click(screen.getByRole('radio', { name: 'workflow.teacherStyle.followCourse' }))
    expect(screen.getByLabelText('暖色图解', { selector: 'video' })).toHaveAttribute(
      'src',
      '/teacher-style/videos/warm.mp4',
    )
  })
})
