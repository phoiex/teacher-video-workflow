'use client'
import type { KnowledgeChoice } from './course-knowledge-data'

type Props = {
  value: KnowledgeChoice
  label: string
  id?: string
  invalid?: boolean
  describedBy?: string
  onChange: (value: string) => void
}

export default function CourseKnowledge({
  value,
  label,
  id,
  invalid,
  describedBy,
  onChange,
}: Props) {
  return (
    <fieldset
      id={id}
      tabIndex={-1}
      aria-label={label}
      aria-invalid={invalid || undefined}
      aria-describedby={describedBy}
      className="grid gap-3 rounded-xl focus-visible:outline-2 focus-visible:outline-blue-600"
    >
      {value.options.map((option) => (
        <label
          key={option.id}
          className="flex cursor-pointer items-start gap-3 rounded-xl border border-components-panel-border bg-components-panel-bg p-4"
        >
          <input
            type="checkbox"
            aria-label={option.title}
            className="mt-1 size-4 accent-blue-600"
            checked={value.selected.includes(option.id)}
            onChange={(event) =>
              onChange(
                JSON.stringify({
                  ...value,
                  selected: event.target.checked
                    ? [...value.selected, option.id]
                    : value.selected.filter((item) => item !== option.id),
                }),
              )
            }
          />
          <span className="min-w-0">
            <span className="block font-semibold text-text-primary">{option.title}</span>
            <span className="mt-1 block text-sm text-text-secondary">{option.summary}</span>
            <span className="mt-2 block text-xs text-text-tertiary">{option.source}</span>
          </span>
        </label>
      ))}
    </fieldset>
  )
}
