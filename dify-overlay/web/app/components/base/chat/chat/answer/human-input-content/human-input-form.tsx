'use client'
import type { HumanInputFieldValue } from './field-renderer'
import type { HumanInputFormProps } from './type'
import type { UserAction } from '@/app/components/workflow/nodes/human-input/types'
import { Button } from '@langgenius/dify-ui/button'
import * as React from 'react'
import { useCallback, useId, useMemo, useRef, useState } from 'react'
import { useTranslation } from 'react-i18next'
import ContentItem from './content-item'
import {
  getButtonStyle,
  getInvalidFormInputs,
  getProcessedHumanInputFormInputs,
  getRenderedFormInputs,
  initializeInputs,
  splitByOutputVar,
} from './utils'

const HumanInputForm = ({ formData, onSubmit }: HumanInputFormProps) => {
  const { t } = useTranslation('workflow')
  const formId = useId()
  const formToken = formData.form_token
  const contentList = useMemo(() => {
    const counts = new Map<string, number>()
    return splitByOutputVar(formData.form_content).map((content) => {
      const occurrence = (counts.get(content) || 0) + 1
      counts.set(content, occurrence)
      return { content, key: `${content}-${occurrence}` }
    })
  }, [formData.form_content])
  const renderedFormInputs = getRenderedFormInputs(formData.inputs, formData.form_content)
  const defaultInputs = initializeInputs(renderedFormInputs, formData.resolved_default_values || {})
  const [inputs, setInputs] = useState(defaultInputs)
  const [isSubmitting, setIsSubmitting] = useState(false)
  const submittingRef = useRef(false)
  const invalidInputs = getInvalidFormInputs(renderedFormInputs, inputs)
  const invalidFields = new Set(invalidInputs.map((input) => input.output_variable_name))

  const handleInputsChange = useCallback((name: string, value: HumanInputFieldValue) => {
    setInputs((prev) => ({
      ...prev,
      [name]: value,
    }))
  }, [])

  const submit = async (
    formToken: string,
    actionID: string,
    inputs: Record<string, HumanInputFieldValue>,
  ) => {
    if (submittingRef.current) return
    submittingRef.current = true
    setIsSubmitting(true)
    try {
      await onSubmit?.(formToken, {
        inputs: getProcessedHumanInputFormInputs(renderedFormInputs, inputs) || {},
        action: actionID,
      })
    } finally {
      submittingRef.current = false
      setIsSubmitting(false)
    }
  }

  const isActionDisabled = isSubmitting || !formToken || invalidInputs.length > 0

  return (
    <form onSubmit={(event) => event.preventDefault()}>
      {invalidInputs.length > 0 && (
        <div
          className="mb-4 rounded-xl border border-amber-400 bg-amber-50 p-4 text-amber-900 dark:bg-amber-950/20 dark:text-amber-100"
          role="status"
        >
          <p className="mb-2 font-medium">{t(($) => $['humanInput.form.missingFields'])}</p>
          <div className="flex flex-wrap gap-2">
            {invalidInputs.map((input) => (
              <button
                key={input.output_variable_name}
                type="button"
                className="rounded-md border border-amber-300 px-3 py-1 text-sm underline underline-offset-2"
                onClick={() =>
                  document.getElementById(`${formId}-${input.output_variable_name}`)?.focus()
                }
              >
                {input.label || input.output_variable_name}
              </button>
            ))}
          </div>
        </div>
      )}
      {contentList.map(({ content, key }) => (
        <ContentItem
          key={key}
          id={formId}
          invalidFields={invalidFields}
          content={content}
          formInputFields={formData.inputs}
          inputs={inputs}
          onInputChange={handleInputsChange}
        />
      ))}
      <div className="flex flex-wrap gap-1 py-1">
        {formData.actions.map((action: UserAction) => (
          <Button
            type="button"
            key={action.id}
            disabled={isActionDisabled}
            variant={getButtonStyle(action.button_style)}
            onClick={() => formToken && submit(formToken, action.id, inputs)}
          >
            {action.title}
          </Button>
        ))}
      </div>
    </form>
  )
}

export default React.memo(HumanInputForm)
