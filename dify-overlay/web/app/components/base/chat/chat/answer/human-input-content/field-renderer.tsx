import type { FileEntity } from '@/app/components/base/file-uploader/types'
import type { FormInputItem } from '@/app/components/workflow/nodes/human-input/types'
import {
  Select,
  SelectItem,
  SelectItemIndicator,
  SelectItemText,
  SelectList,
  SelectPopup,
  SelectPortal,
  SelectPositioner,
  SelectTrigger,
  SelectValue,
} from '@langgenius/dify-ui/select'
import { Textarea } from '@langgenius/dify-ui/textarea'
import * as React from 'react'
import { FileUploaderInAttachmentWrapper } from '@/app/components/base/file-uploader'
import {
  isFileFormInput,
  isFileListFormInput,
  isParagraphFormInput,
  isSelectFormInput,
} from '@/app/components/workflow/nodes/human-input/types'
import CourseKnowledge from '@/app/components/workflow/run/course-knowledge'
import { parseKnowledgeChoice } from '@/app/components/workflow/run/course-knowledge-data'

export type HumanInputFieldValue = string | FileEntity | FileEntity[] | null

type Props = Readonly<{
  id?: string
  invalid?: boolean
  describedBy?: string
  field: FormInputItem
  value?: HumanInputFieldValue
  onChange: (value: HumanInputFieldValue) => void
}>

const HumanInputFieldRenderer = ({ field, value, onChange, id, invalid, describedBy }: Props) => {
  if (isParagraphFormInput(field)) {
    const knowledge =
      field.output_variable_name === 'knowledge_selection' ? parseKnowledgeChoice(value) : null
    if (knowledge)
      return (
        <CourseKnowledge
          value={knowledge}
          label={field.label || field.output_variable_name}
          id={id}
          invalid={invalid}
          describedBy={describedBy}
          onChange={onChange}
        />
      )
    return (
      <Textarea
        id={id}
        aria-label={field.label || field.output_variable_name}
        aria-invalid={invalid || undefined}
        aria-describedby={describedBy}
        className="h-26 sm:text-xs"
        value={typeof value === 'string' ? value : ''}
        onValueChange={(nextValue) => onChange(nextValue)}
        data-testid="content-item-textarea"
      />
    )
  }

  if (isSelectFormInput(field)) {
    const options = field.option_source.value.map((option) => ({
      name: option,
      value: option,
    }))

    return (
      <Select
        value={typeof value === 'string' ? value : ''}
        onValueChange={(nextValue) => {
          if (nextValue == null) return
          onChange(nextValue)
        }}
      >
        <SelectTrigger
          size="large"
          className="w-full"
          id={id}
          aria-label={field.label || field.output_variable_name}
          aria-invalid={invalid || undefined}
          aria-describedby={describedBy}
        >
          <SelectValue />
        </SelectTrigger>
        <SelectPortal>
          <SelectPositioner>
            <SelectPopup>
              <SelectList className="max-h-35 overflow-y-auto">
                {options.map((option) => (
                  <SelectItem key={option.value} value={option.value}>
                    <SelectItemText>{option.name}</SelectItemText>
                    <SelectItemIndicator />
                  </SelectItem>
                ))}
              </SelectList>
            </SelectPopup>
          </SelectPositioner>
        </SelectPortal>
      </Select>
    )
  }

  if (isFileFormInput(field)) {
    const singleFileValue =
      value && !Array.isArray(value) && typeof value !== 'string' ? [value] : []

    return (
      <FileUploaderInAttachmentWrapper
        value={singleFileValue}
        onChange={(files) => onChange(files[0] || null)}
        fileConfig={{
          allowed_file_types: field.allowed_file_types,
          allowed_file_extensions: field.allowed_file_extensions,
          allowed_file_upload_methods: field.allowed_file_upload_methods,
          number_limits: 1,
        }}
      />
    )
  }

  if (isFileListFormInput(field)) {
    return (
      <FileUploaderInAttachmentWrapper
        value={Array.isArray(value) ? value : []}
        onChange={(files) => onChange(files)}
        fileConfig={{
          allowed_file_types: field.allowed_file_types,
          allowed_file_extensions: field.allowed_file_extensions,
          allowed_file_upload_methods: field.allowed_file_upload_methods,
          number_limits: field.number_limits || 5,
        }}
      />
    )
  }

  return null
}

export default React.memo(HumanInputFieldRenderer)
