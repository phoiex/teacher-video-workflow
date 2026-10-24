import { render, screen } from '@testing-library/react'
import NativeWorkflowEntry from '../native-workflow-entry'

const { replace } = vi.hoisted(() => ({
  replace: vi.fn(),
}))
vi.mock('@/next/navigation', () => ({
  useRouter: () => ({ replace }),
}))

describe('课程发布页的可选流程入口', () => {
  beforeEach(() => {
    replace.mockClear()
  })
  it('stays on the published page until the user chooses the editor link', () => {
    render(<NativeWorkflowEntry appId="course-app" />)
    expect(replace).not.toHaveBeenCalled()
    expect(screen.getByRole('link')).toHaveAttribute('href', '/app/course-app/workflow')
    expect(screen.getByRole('link')).toHaveAttribute('target', '_blank')
  })
  it('已有运行编号保留在原生界面的地址中', () => {
    render(<NativeWorkflowEntry appId="course-app" runId="6cd4e78e-d332-4fd3-8870-674c9900bf89" />)
    expect(screen.getByRole('link')).toHaveAttribute(
      'href',
      '/app/course-app/workflow?run_id=6cd4e78e-d332-4fd3-8870-674c9900bf89',
    )
    expect(replace).not.toHaveBeenCalled()
  })
})
