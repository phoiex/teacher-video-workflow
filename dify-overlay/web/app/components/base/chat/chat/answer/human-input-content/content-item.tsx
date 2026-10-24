import type { ContentItemProps } from './type'
import * as React from 'react'
import { useMemo } from 'react'
import { useTranslation } from 'react-i18next'
import { Markdown } from '@/app/components/base/markdown'
import HumanInputFieldRenderer from './field-renderer'

const ContentItem = ({
  content,
  formInputFields,
  inputs,
  onInputChange,
  id,
  invalidFields,
}: ContentItemProps) => {
  const { t } = useTranslation('workflow')
  const isInputField = (field: string) => {
    const outputVarRegex = /\{\{#\$output\.[^#]+#\}\}/
    return outputVarRegex.test(field)
  }

  const extractFieldName = (str: string): string => {
    const outputVarRegex = /\{\{#\$output\.([^#]+)#\}\}/
    const match = outputVarRegex.exec(str)
    return match ? match[1]! : ''
  }

  const fieldName = useMemo(() => {
    return extractFieldName(content)
  }, [content])

  const formInputField = useMemo(() => {
    return formInputFields.find((field) => field.output_variable_name === fieldName)
  }, [formInputFields, fieldName])

  if (!isInputField(content)) {
    return <Markdown content={content} />
  }

  if (!formInputField) return null

  const invalid = invalidFields?.has(fieldName)
  const fieldId = id ? `${id}-${fieldName}` : undefined
  const errorId = fieldId ? `${fieldId}-error` : undefined

  return (
    <div
      className={
        invalid
          ? 'my-3 rounded-xl border border-amber-400 bg-amber-50 p-3 dark:bg-amber-950/20'
          : 'py-3'
      }
    >
      <HumanInputFieldRenderer
        id={fieldId}
        invalid={invalid}
        describedBy={invalid ? errorId : undefined}
        field={formInputField}
        value={inputs[fieldName]}
        onChange={(value) => onInputChange(fieldName, value)}
      />
      {invalid && (
        <p id={errorId} className="mt-2 text-sm font-medium text-amber-800 dark:text-amber-200">
          {t(($) => $['humanInput.form.needsCompletion'])}
        </p>
      )}
    </div>
  )
}

export default React.memo(ContentItem)
