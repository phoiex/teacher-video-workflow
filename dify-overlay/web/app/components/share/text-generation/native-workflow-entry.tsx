'use client'

import { buttonVariants } from '@langgenius/dify-ui/button'
import { useTranslation } from 'react-i18next'
import Link from '@/next/link'

export default function NativeWorkflowEntry({ appId, runId }: { appId: string; runId?: string }) {
  const { t } = useTranslation()
  const query =
    runId && /^[0-9a-f-]{36}$/i.test(runId) ? `?run_id=${encodeURIComponent(runId)}` : ''
  const target = `/app/${encodeURIComponent(appId)}/workflow${query}`
  return (
    <Link
      className={buttonVariants({ variant: 'secondary', size: 'small' })}
      href={target}
      target="_blank"
      rel="noopener noreferrer"
      prefetch={false}
    >
      <span aria-hidden className="i-ri-node-tree size-4" />
      {t(($) => $['teacherCourse.editor'], { ns: 'share' })}
      <span aria-hidden className="i-ri-external-link-line size-3.5" />
    </Link>
  )
}
