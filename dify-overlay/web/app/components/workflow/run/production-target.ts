// 本机制作器的嵌入页，不是Dify Console接口；审批仍走原生表单提交。
export const productionPanelUrl = (content: string, actions: { id: string }[]) => {
  if (
    !['check', 'pause', 'continue', 'accept_duration', 'revise'].every((id) =>
      actions.some((action) => action.id === id),
    )
  )
    return undefined
  const match = content.match(/http:\/\/127\.0\.0\.1:8794\/presence\/([a-f0-9]{24})\b/)
  return match ? `http://127.0.0.1:8794/production-panel/${match[1]}` : undefined
}

export const storyboardWaitUrl = (content: string, actions: { id: string }[]) => {
  if (actions.length !== 1 || actions[0]?.id !== 'job_updated') return undefined
  return content.match(/http:\/\/127\.0\.0\.1:8794\/storyboard-panel\/[a-f0-9]{24}\b/)?.[0]
}

export const isInternalProgressResult = (content: string, action: string) =>
  !!storyboardWaitUrl(content, [{ id: action }]) ||
  (action === 'check' && /http:\/\/127\.0\.0\.1:8794\/presence\/[a-f0-9]{24}\b/.test(content))
