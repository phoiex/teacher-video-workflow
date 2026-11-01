'use client'

import { cn } from '@langgenius/dify-ui/cn'
import { useRef } from 'react'
import catalog from '@/public/teacher-style/catalog.json'

type Preview = {
  name: string
  image?: string
  preview_video?: string
  preview_poster?: string
  preview_captions?: string
}

const previews: Record<string, Preview> = Object.fromEntries(
  catalog.presets.filter((preset) => preset.image).map((preset) => [preset.name, preset]),
)

type Props = { options: string[]; value?: string; onChange: (value: string) => void }

export default function StylePreviewOptions({ options, value, onChange }: Props) {
  const playingRef = useRef<HTMLVideoElement | null>(null)

  return (
    <div className="mb-3 grid grid-cols-1 gap-3 sm:grid-cols-3">
      {options
        .filter((option) => previews[option])
        .map((option) => (
          <div
            key={option}
            data-selected={value === option}
            className="overflow-hidden rounded-xl border border-divider-subtle bg-components-panel-bg shadow-xs transition-[border-color,box-shadow] duration-200 hover:border-text-quaternary hover:shadow-sm data-[selected=true]:border-state-accent-solid data-[selected=true]:ring-2 data-[selected=true]:ring-state-accent-solid/15 motion-reduce:transition-none"
          >
            {previews[option]?.preview_video ? (
              <video
                aria-label={option}
                src={`/teacher-style/${previews[option].preview_video}`}
                poster={`/teacher-style/${previews[option].preview_poster || previews[option].image}`}
                controls
                playsInline
                preload="none"
                className="aspect-video w-full object-cover focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-state-accent-solid"
                onPlay={(event) => {
                  if (playingRef.current && playingRef.current !== event.currentTarget)
                    playingRef.current.pause()
                  playingRef.current = event.currentTarget
                }}
              >
                <track
                  kind="captions"
                  src={`/teacher-style/${previews[option].preview_captions}`}
                  srcLang="zh-CN"
                />
              </video>
            ) : (
              <img
                src={`/teacher-style/${previews[option]?.image}`}
                alt=""
                width={1920}
                height={1080}
                className="aspect-video w-full object-cover"
              />
            )}
            <button
              type="button"
              aria-label={option}
              aria-pressed={value === option}
              onClick={() => onChange(option)}
              className="flex min-h-12 w-full items-center justify-between gap-2 px-3 py-2.5 text-left text-sm font-medium text-text-primary focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-state-accent-solid"
            >
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
            </button>
          </div>
        ))}
    </div>
  )
}
