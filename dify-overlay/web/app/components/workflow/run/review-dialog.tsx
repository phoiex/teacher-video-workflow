'use client'

import { Button } from '@langgenius/dify-ui/button'
import {
  Dialog,
  DialogBackdrop,
  DialogClose,
  DialogDescription,
  DialogPopup,
  DialogPortal,
  DialogTitle,
} from '@langgenius/dify-ui/dialog'
import { useCallback, useEffect, useRef, useState } from 'react'
import { useTranslation } from 'react-i18next'
import HumanInputForm from '@/app/components/base/chat/chat/answer/human-input-content/human-input-form'
import Loading from '@/app/components/base/loading'
import { humanInputError } from '@/service/human-input-error'
import { useGetHumanInputForm, useSubmitHumanInputForm } from '@/service/use-share'
import ProductionPanel from './production-panel'
import { productionPanelUrl, storyboardWaitUrl } from './production-target'
import StoryboardWaitPanel from './storyboard-wait-panel'

type Props = {
  token: string
  title: string
  onSubmitted: () => void
  onProductionStatus?: (status: string) => void
}

const ReviewDialog = ({ token, title, onSubmitted, onProductionStatus }: Props) => {
  const { t } = useTranslation()
  const [open, setOpen] = useState(true)
  const [error, setError] = useState('')
  const [submitted, setSubmitted] = useState(false)
  const completedRef = useRef(false)
  const form = useGetHumanInputForm(token, { refetchOnWindowFocus: false })
  const submit = useSubmitHumanInputForm({ silent: true })
  const serverSubmitted = form.error?.code === 'human_input_form_submitted'
  const resolved = submitted || serverSubmitted
  const finish = useCallback(() => {
    if (completedRef.current) return
    completedRef.current = true
    setSubmitted(true)
    setOpen(false)
    onSubmitted()
  }, [onSubmitted])
  useEffect(() => {
    if (!serverSubmitted || completedRef.current) return
    completedRef.current = true
    onSubmitted()
  }, [serverSubmitted, onSubmitted])
  const submitAction = async (
    formToken: string,
    data: { inputs: Record<string, unknown>; action: string },
  ) => {
    try {
      await submit.mutateAsync({ token: formToken, data })
      finish()
    } catch (cause) {
      const detail = await humanInputError(cause)
      if (detail.code === 'human_input_form_submitted') finish()
      else throw new Error(detail.message)
    }
  }
  const productionUrl =
    form.data && productionPanelUrl(form.data.form_content, form.data.user_actions)
  const waitUrl = form.data && storyboardWaitUrl(form.data.form_content, form.data.user_actions)
  if (waitUrl && form.data && !resolved) {
    return (
      <StoryboardWaitPanel
        key={token}
        url={waitUrl}
        title={title}
        onStatusChange={onProductionStatus}
        onReady={() => submitAction(token, { inputs: {}, action: 'job_updated' })}
      />
    )
  }
  if (productionUrl && form.data && !resolved) {
    return (
      <ProductionPanel
        url={productionUrl}
        title={title.split(' · ')[0] || title}
        actions={form.data.user_actions}
        onStatusChange={onProductionStatus}
        onAction={async (action) => {
          await submitAction(token, { inputs: {}, action })
        }}
      />
    )
  }

  return (
    <Dialog
      open={open && !resolved && !form.isLoading}
      onOpenChange={setOpen}
      disablePointerDismissal
    >
      {!resolved && (
        <Button size="small" variant="secondary" onClick={() => setOpen(true)}>
          {t(($) => $['liveProgress.review'], { ns: 'workflow' })}
        </Button>
      )}
      {/* 关闭弹窗时保留草稿，轮询不会重置填写内容。 */}
      <DialogPortal keepMounted>
        <DialogBackdrop className="data-closed:hidden" />
        <DialogPopup className="fixed top-1/2 left-1/2 flex max-h-[90dvh] w-230 max-w-[calc(100vw-2rem)] -translate-x-1/2 -translate-y-1/2 flex-col overflow-hidden p-0 data-closed:hidden">
          <div className="flex shrink-0 items-center justify-between gap-4 border-b border-divider-subtle px-6 py-4">
            <DialogTitle className="system-xl-semibold text-text-primary">{title}</DialogTitle>
            <DialogClose render={<Button variant="secondary" size="small" />}>
              {t(($) => $['operation.close'], { ns: 'common' })}
            </DialogClose>
          </div>
          <DialogDescription className="sr-only">
            {t(($) => $['liveProgress.review'], { ns: 'workflow' })}
          </DialogDescription>
          <div className="min-h-0 overflow-y-auto overscroll-contain px-6 py-4">
            {form.isLoading && <Loading />}
            {(error || form.error) && (
              <p role="alert" className="mb-3 text-text-destructive">
                {error || form.error?.message}
              </p>
            )}
            {form.data && (
              <HumanInputForm
                key={token}
                formData={{
                  form_token: token,
                  form_content: form.data.form_content,
                  inputs: form.data.inputs,
                  resolved_default_values: form.data.resolved_default_values,
                  actions: form.data.user_actions,
                }}
                onSubmit={async (formToken, data) => {
                  setError('')
                  try {
                    await submitAction(formToken, data)
                  } catch (cause) {
                    setError(cause instanceof Error ? cause.message : String(cause))
                  }
                }}
              />
            )}
          </div>
        </DialogPopup>
      </DialogPortal>
    </Dialog>
  )
}

export default ReviewDialog
