import type { LoopDurationMap, LoopVariableMap, NodeTracing } from '@/types/workflow'
import { Button } from '@langgenius/dify-ui/button'
import { useTranslation } from 'react-i18next'
import { getLoopDetails } from '../container-details'

type LoopLogTriggerProps = {
  nodeInfo: NodeTracing
  allExecutions?: NodeTracing[]
  onShowLoopResultList: (
    loopResultList: NodeTracing[][],
    loopResultDurationMap: LoopDurationMap,
    loopVariableMap: LoopVariableMap,
  ) => void
}
const LoopLogTrigger = ({ nodeInfo, allExecutions, onShowLoopResultList }: LoopLogTriggerProps) => {
  const { t } = useTranslation()

  const handleOnShowLoopDetail = (e: React.MouseEvent<HTMLButtonElement>) => {
    e.stopPropagation()
    e.nativeEvent.stopImmediatePropagation()

    const { list, durationMap, variableMap } = getLoopDetails(nodeInfo, allExecutions)
    onShowLoopResultList(list, durationMap, variableMap)
  }

  let displayLoopCount = 0
  const loopMap = nodeInfo.execution_metadata?.loop_duration_map
  if (loopMap) displayLoopCount = Object.keys(loopMap).length
  else if (nodeInfo.details?.length) displayLoopCount = nodeInfo.details.length
  else if (nodeInfo.metadata?.loop_length) displayLoopCount = nodeInfo.metadata.loop_length

  const getErrorCount = (details: NodeTracing[][] | undefined) => {
    if (!details || details.length === 0) return 0
    return details.reduce((acc, loop) => {
      if (loop.some((item) => item.status === 'failed')) acc++
      return acc
    }, 0)
  }
  const errorCount = getErrorCount(nodeInfo.details)

  return (
    <Button
      className="flex w-full cursor-pointer items-center self-stretch rounded-lg bg-components-button-tertiary-bg-hover px-3 py-2 inset-ring-0 hover:bg-components-button-tertiary-bg-hover"
      onClick={handleOnShowLoopDetail}
    >
      <span
        aria-hidden
        className="i-custom-vender-workflow-loop size-4 shrink-0 text-components-button-tertiary-text"
      />
      <div className="flex-1 text-left system-sm-medium text-components-button-tertiary-text">
        {t(($) => $['nodes.loop.loop'], { ns: 'workflow', count: displayLoopCount })}
        {errorCount > 0 && (
          <>
            {t(($) => $['nodes.loop.comma'], { ns: 'workflow' })}
            {t(($) => $['nodes.loop.error'], { ns: 'workflow', count: errorCount })}
          </>
        )}
      </div>
      <span
        aria-hidden
        className="i-ri-arrow-right-s-line size-4 shrink-0 text-components-button-tertiary-text"
      />
    </Button>
  )
}

export default LoopLogTrigger
