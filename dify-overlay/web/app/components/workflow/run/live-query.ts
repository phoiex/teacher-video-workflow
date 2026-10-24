import { skipToken } from '@tanstack/react-query'
import { consoleQuery } from '@/service/console'

export const isLiveRun = (status?: string | null) => status === 'running' || status === 'paused'

export const liveRunOptions = (appId?: string, runId?: string) =>
  consoleQuery.apps.byAppId.workflowRuns.byRunId.get.queryOptions({
    input: appId && runId ? { params: { app_id: appId, run_id: runId } } : skipToken,
    refetchInterval: (query) =>
      !query.state.data || isLiveRun(query.state.data.status) ? 2000 : false,
    refetchOnWindowFocus: 'always',
    refetchOnReconnect: 'always',
    retry: false,
  })
