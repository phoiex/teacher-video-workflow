'use client'

import { cn } from '@langgenius/dify-ui/cn'
import { SegmentedControl, SegmentedControlItem } from '@langgenius/dify-ui/segmented-control'
import { useRef, useState } from 'react'
import { useTranslation } from 'react-i18next'
import catalog from '@/public/teacher-style/catalog.json'

type Preview = {
  name: string
  image?: string
  preview_video?: string
  preview_poster?: string
  preview_captions?: string
  preview_languages?: { en?: { video: string; poster: string; captions: string } }
}

const previews: Record<string, Preview> = Object.fromEntries(
  catalog.presets.filter((preset) => preset.image).map((preset) => [preset.name, preset]),
)

type PreviewLanguage = 'course' | 'zh' | 'en'
type Props = {
  options: string[]
  value?: string
  courseLanguage?: string
  onChange: (value: string) => void
}

export default function StylePreviewOptions({ options, value, courseLanguage, onChange }: Props) {
  const playingRef = useRef<HTMLVideoElement | null>(null)
  const { t } = useTranslation('workflow')
  const [previewLanguage, setPreviewLanguage] = useState<PreviewLanguage>('course')
  const courseLocale = /^en(?:glish|[-_]|$)/i.test(courseLanguage || '') ? 'en' : 'zh'
  const language = previewLanguage === 'course' ? courseLocale : previewLanguage

  return (
    <div className="mb-3">
      <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
        <span className="text-sm text-text-secondary">
          {t(($) => $['teacherStyle.previewLanguage'])}
        </span>
        <SegmentedControl<PreviewLanguage>
          aria-label={t(($) => $['teacherStyle.previewLanguage'])}
          value={previewLanguage}
          onValueChange={(next) => {
            playingRef.current?.pause()
            setPreviewLanguage(next)
          }}
        >
          <SegmentedControlItem value="course">
            {t(($) => $['teacherStyle.followCourse'])}
          </SegmentedControlItem>
          <SegmentedControlItem value="zh">中文</SegmentedControlItem>
          <SegmentedControlItem value="en">English</SegmentedControlItem>
        </SegmentedControl>
      </div>
      <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
        {options
          .filter((option) => previews[option])
          .map((option) => {
            const preset = previews[option]!
            const english = language === 'en' ? preset.preview_languages?.en : undefined
            const video = english?.video || preset.preview_video
            const poster = english?.poster || preset.preview_poster || preset.image
            const captions = english?.captions || preset.preview_captions
            return (
              <div
                key={option}
                data-selected={value === option}
                className="overflow-hidden rounded-xl border border-divider-subtle bg-components-panel-bg shadow-xs transition-[border-color,box-shadow] duration-200 hover:border-text-quaternary hover:shadow-sm data-[selected=true]:border-state-accent-solid data-[selected=true]:ring-2 data-[selected=true]:ring-state-accent-solid/15 motion-reduce:transition-none"
              >
                {video ? (
                  <video
                    key={`${option}-${language}`}
                    aria-label={option}
                    src={`/teacher-style/${video}`}
                    poster={`/teacher-style/${poster}`}
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
                      src={`/teacher-style/${captions}`}
                      srcLang={english ? 'en' : 'zh-CN'}
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
                      value === option &&
                        'border-state-accent-solid bg-state-accent-solid text-white',
                    )}
                  >
                    {value === option && <span className="i-ri-check-line size-3.5" />}
                  </span>
                </button>
              </div>
            )
          })}
      </div>
    </div>
  )
}
