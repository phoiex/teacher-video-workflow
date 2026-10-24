'use client'

import { cn } from '@langgenius/dify-ui/cn'

const previews: Record<string, string> = {
  暖色图解: '/teacher-style/warm.png',
  'ASCII 终端科技': '/teacher-style/ascii.png',
  空间代码动画: '/teacher-style/openfilm.png',
}

type Props = { options: string[]; value?: string; onChange: (value: string) => void }

export default function StylePreviewOptions({ options, value, onChange }: Props) {
  return (
    <div className="mb-3 grid grid-cols-1 gap-3 sm:grid-cols-3">
      {options
        .filter((option) => previews[option])
        .map((option) => (
          <button
            key={option}
            type="button"
            aria-label={option}
            aria-pressed={value === option}
            onClick={() => onChange(option)}
            className="group overflow-hidden rounded-xl border border-divider-subtle bg-components-panel-bg text-left shadow-xs transition-[border-color,box-shadow] duration-200 hover:border-text-quaternary hover:shadow-sm focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-state-accent-solid aria-pressed:border-state-accent-solid aria-pressed:ring-2 aria-pressed:ring-state-accent-solid/15 motion-reduce:transition-none"
          >
            <img
              src={previews[option]}
              alt=""
              width={1920}
              height={1080}
              className="aspect-video w-full object-cover"
            />
            <span className="flex min-h-12 items-center justify-between gap-2 px-3 py-2.5 text-sm font-medium text-text-primary">
              <span>{option}</span>
              <span
                aria-hidden="true"
                className={cn(
                  'flex size-4.5 shrink-0 items-center justify-center rounded-full border border-divider-regular',
                  value === option && 'border-state-accent-solid bg-state-accent-solid text-white',
                )}
              >
                {value === option && <span className="i-ri-check-line size-3.5" />}
              </span>
            </span>
          </button>
        ))}
    </div>
  )
}
