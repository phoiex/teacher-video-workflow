import type { HumanInputFormSubmitData } from './human-input-content/type'
import type {
  DeliveryMethod,
  HumanInputNodeType,
} from '@/app/components/workflow/nodes/human-input/types'
import type { Node } from '@/app/components/workflow/types'
import type { HumanInputFormData } from '@/types/workflow'
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
import { useMemo, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { DeliveryMethodType } from '@/app/components/workflow/nodes/human-input/types'
import ProductionPanel from '@/app/components/workflow/run/production-panel'
import {
  productionPanelUrl,
  storyboardWaitUrl,
} from '@/app/components/workflow/run/production-target'
import StoryboardWaitPanel from '@/app/components/workflow/run/storyboard-wait-panel'
import { humanInputError } from '@/service/human-input-error'
import ContentWrapper from './human-input-content/content-wrapper'
import { UnsubmittedHumanInputContent } from './human-input-content/unsubmitted'

type HumanInputFormListProps = {
  humanInputFormDataList: HumanInputFormData[]
  onHumanInputFormSubmit?: (formToken: string, formData: HumanInputFormSubmitData) => Promise<void>
  getHumanInputNodeData?: (nodeID: string) => Node<HumanInputNodeType> | undefined
  showReviews?: boolean
}

const HumanInputFormList = ({
  humanInputFormDataList,
  onHumanInputFormSubmit,
  getHumanInputNodeData,
  showReviews = true,
}: HumanInputFormListProps) => {
  const { t } = useTranslation()
  const [dismissed, setDismissed] = useState<string[]>([])
  const [selected, setSelected] = useState<string>()
  const [error, setError] = useState('')
  const [submitted, setSubmitted] = useState<string[]>([])
  const deliveryMethodsConfig = useMemo((): Record<
    string,
    { showEmailTip: boolean; isEmailDebugMode: boolean; showDebugModeTip: boolean }
  > => {
    if (!humanInputFormDataList.length) return {}
    return humanInputFormDataList.reduce(
      (acc, formData) => {
        const deliveryMethodsConfig =
          getHumanInputNodeData?.(formData.node_id)?.data.delivery_methods || []
        if (!deliveryMethodsConfig.length) {
          acc[formData.node_id] = {
            showEmailTip: false,
            isEmailDebugMode: false,
            showDebugModeTip: false,
          }
          return acc
        }
        const isWebappEnabled = deliveryMethodsConfig.some(
          (method: DeliveryMethod) => method.type === DeliveryMethodType.WebApp && method.enabled,
        )
        const isEmailEnabled = deliveryMethodsConfig.some(
          (method: DeliveryMethod) => method.type === DeliveryMethodType.Email && method.enabled,
        )
        const isEmailDebugMode = deliveryMethodsConfig.some(
          (method: DeliveryMethod) =>
            method.type === DeliveryMethodType.Email && method.config?.debug_mode,
        )
        acc[formData.node_id] = {
          showEmailTip: isEmailEnabled,
          isEmailDebugMode,
          showDebugModeTip: !isWebappEnabled,
        }
        return acc
      },
      {} as Record<
        string,
        { showEmailTip: boolean; isEmailDebugMode: boolean; showDebugModeTip: boolean }
      >,
    )
  }, [getHumanInputNodeData, humanInputFormDataList])

  const filteredHumanInputFormDataList = humanInputFormDataList.filter(
    (formData) => formData.display_in_ui && !submitted.includes(formData.form_id),
  )
  const productionForms = filteredHumanInputFormDataList.filter((form) =>
    productionPanelUrl(form.form_content, form.actions),
  )
  const storyboardForms = filteredHumanInputFormDataList.filter((form) =>
    storyboardWaitUrl(form.form_content, form.actions),
  )
  const reviewForms = filteredHumanInputFormDataList.filter(
    (form) =>
      !productionPanelUrl(form.form_content, form.actions) &&
      !storyboardWaitUrl(form.form_content, form.actions),
  )
  const activeForm =
    reviewForms.find((form) => form.form_id === selected) ||
    reviewForms.find((form) => !dismissed.includes(form.form_id))
  const close = (id: string) => {
    setDismissed((previous) => [
      ...new Set([...previous, id, ...reviewForms.map((form) => form.form_id)]),
    ])
    setSelected(undefined)
  }
  const finish = (id: string) => {
    setSubmitted((previous) => [...new Set([...previous, id])])
    if (reviewForms.some((form) => form.form_id === id)) close(id)
  }

  return (
    <Dialog
      open={showReviews && !!activeForm}
      onOpenChange={(open) => !open && activeForm && close(activeForm.form_id)}
      disablePointerDismissal
    >
      <div className="mt-2 flex flex-col gap-y-2" data-testid="human-input-form-list">
        {storyboardForms.map((form) => (
          <StoryboardWaitPanel
            key={form.form_id}
            url={storyboardWaitUrl(form.form_content, form.actions)!}
            title={form.node_title}
            onReady={
              form.form_token && onHumanInputFormSubmit
                ? async () => {
                    try {
                      await onHumanInputFormSubmit(form.form_token!, {
                        inputs: {},
                        action: 'job_updated',
                      })
                    } catch (cause) {
                      const detail = await humanInputError(cause)
                      if (detail.code !== 'human_input_form_submitted')
                        throw new Error(detail.message)
                    }
                    finish(form.form_id)
                  }
                : undefined
            }
          />
        ))}
        {productionForms.map((form) => (
          <ProductionPanel
            key={form.form_id}
            url={productionPanelUrl(form.form_content, form.actions)!}
            title={form.node_title.split(' · ')[0] || form.node_title}
            actions={onHumanInputFormSubmit && form.form_token ? form.actions : []}
            onAction={async (action) => {
              if (form.form_token && onHumanInputFormSubmit) {
                try {
                  await onHumanInputFormSubmit(form.form_token, { inputs: {}, action })
                } catch (cause) {
                  const detail = await humanInputError(cause)
                  if (detail.code !== 'human_input_form_submitted') throw new Error(detail.message)
                }
                finish(form.form_id)
              }
            }}
          />
        ))}
        {showReviews &&
          reviewForms.map((formData) => (
            <div key={formData.form_id} data-testid="human-input-form-item">
              <ContentWrapper nodeTitle={formData.node_title}>
                <Button
                  size="small"
                  variant="secondary"
                  onClick={() => {
                    setError('')
                    setSelected(formData.form_id)
                  }}
                >
                  {t(($) => $['liveProgress.review'], { ns: 'workflow' })}
                </Button>
              </ContentWrapper>
            </div>
          ))}
      </div>
      <DialogPortal keepMounted>
        <DialogBackdrop className="data-closed:hidden" />
        <DialogPopup className="fixed top-1/2 left-1/2 flex max-h-[90dvh] w-230 max-w-[calc(100vw-2rem)] -translate-x-1/2 -translate-y-1/2 flex-col overflow-hidden p-0 data-closed:hidden">
          <div className="flex shrink-0 items-center justify-between gap-4 border-b border-divider-subtle px-6 py-4">
            <DialogTitle className="system-xl-semibold text-text-primary">
              {activeForm?.node_title}
            </DialogTitle>
            <DialogClose render={<Button size="small" variant="secondary" />}>
              {t(($) => $['operation.close'], { ns: 'common' })}
            </DialogClose>
          </div>
          <DialogDescription className="sr-only">
            {t(($) => $['liveProgress.review'], { ns: 'workflow' })}
          </DialogDescription>
          <div className="min-h-0 overflow-y-auto overscroll-contain px-6 py-4">
            {error && (
              <p role="alert" className="text-text-destructive">
                {error}
              </p>
            )}
            {reviewForms.map((formData) => (
              <div key={formData.form_id} hidden={formData.form_id !== activeForm?.form_id}>
                <UnsubmittedHumanInputContent
                  formData={formData}
                  showEmailTip={!!deliveryMethodsConfig[formData.node_id]?.showEmailTip}
                  isEmailDebugMode={!!deliveryMethodsConfig[formData.node_id]?.isEmailDebugMode}
                  showDebugModeTip={!!deliveryMethodsConfig[formData.node_id]?.showDebugModeTip}
                  onSubmit={async (token, data) => {
                    setError('')
                    try {
                      await onHumanInputFormSubmit?.(token, data)
                      finish(formData.form_id)
                    } catch (cause) {
                      const detail = await humanInputError(cause)
                      if (detail.code === 'human_input_form_submitted') finish(formData.form_id)
                      else setError(detail.message)
                    }
                  }}
                />
              </div>
            ))}
          </div>
        </DialogPopup>
      </DialogPortal>
    </Dialog>
  )
}

export default HumanInputFormList
