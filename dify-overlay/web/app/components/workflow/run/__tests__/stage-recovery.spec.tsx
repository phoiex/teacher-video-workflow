import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { act, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vite-plus/test'
import StageRecovery from '../stage-recovery'

const { send, publicSend, draftSend, replace } = vi.hoisted(() => ({
  send: vi.fn(),
  publicSend: vi.fn(),
  draftSend: vi.fn(),
  replace: vi.fn(),
}))
vi.mock('@/service/base', () => ({ ssePost: draftSend, postPublic: publicSend }))
vi.mock('@/service/console', () => ({
  consoleClient: {
    apps: {
      byAppId: {
        workflowRuns: {
          byRunId: {
            retry: { post: send },
          },
        },
      },
    },
  },
}))
vi.mock('@/next/navigation', () => ({ useRouter: () => ({ replace }) }))
const course = 'a'.repeat(24)
const mount = (runError = 'network', onResumed?: (runId: string) => void) =>
  render(
    <QueryClientProvider
      client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}
    >
      <StageRecovery
        appId="app"
        runId="run"
        runStatus="failed"
        runError={runError}
        publicApp={!!onResumed}
        onResumed={onResumed}
      />
    </QueryClientProvider>,
  )

describe('failed content stage recovery', () => {
  beforeEach(() => {
    send.mockReset()
    publicSend.mockReset()
    draftSend.mockReset()
    replace.mockReset()
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue(
        new Response(
          JSON.stringify({
            status: 'failed',
            retryable: true,
            course_id: course,
            message: '网络中断，进度保留。',
          }),
        ),
      ),
    )
  })
  afterEach(() => vi.unstubAllGlobals())

  it('restarts the saved course once and opens the new run', async () => {
    let resolve!: (value: { workflow_run_id: string }) => void
    send.mockImplementation(
      () =>
        new Promise((done) => {
          resolve = done
        }),
    )
    mount()
    await screen.findByText('网络中断，进度保留。')
    const button = screen.getByRole('button')
    fireEvent.click(button)
    fireEvent.click(button)
    await waitFor(() => expect(send).toHaveBeenCalledTimes(1))
    expect(send).toHaveBeenCalledWith({ params: { app_id: 'app', run_id: 'run' } })
    expect(draftSend).not.toHaveBeenCalled()
    await act(async () =>
      resolve({ workflow_run_id: `${'b'.repeat(8)}-1111-2222-3333-444444444444` }),
    )
    expect(replace).toHaveBeenCalledWith(expect.stringContaining('run_id='))
  })

  it('retries on the published page without navigating to the editor', async () => {
    const next = 'bbbbbbbb-1111-2222-3333-444444444444'
    publicSend.mockResolvedValue({ workflow_run_id: next, reused: false })
    const resumed = vi.fn()
    mount('connection timeout', resumed)
    fireEvent.click(await screen.findByRole('button'))
    await waitFor(() => expect(resumed).toHaveBeenCalledWith(next))
    expect(publicSend).toHaveBeenCalledWith('/workflow/run/retry', { body: {} })
    expect(send).not.toHaveBeenCalled()
    expect(draftSend).not.toHaveBeenCalled()
    expect(replace).not.toHaveBeenCalled()
  })

  it('allows another click after the recovery connection fails', async () => {
    send.mockRejectedValueOnce(new Error('connection unavailable'))
    mount()
    fireEvent.click(await screen.findByRole('button'))
    await screen.findByRole('alert')
    send.mockResolvedValue({ workflow_run_id: 'bbbbbbbb-1111-2222-3333-444444444444' })
    fireEvent.click(screen.getByRole('button'))
    await waitFor(() => expect(send).toHaveBeenCalledTimes(2))
  })

  it('does not offer a network retry for an input error', async () => {
    vi.mocked(fetch).mockResolvedValue(
      new Response(JSON.stringify({ status: 'failed', retryable: false })),
    )
    mount('invalid input')
    await waitFor(() => expect(fetch).toHaveBeenCalled())
    expect(screen.queryByRole('button')).toBeNull()
  })
})
