type KnowledgeOption = { id: string; title: string; summary: string; source: string }
export type KnowledgeChoice = {
  kind: 'course-knowledge-v1'
  options: KnowledgeOption[]
  selected: string[]
}

export const parseKnowledgeChoice = (value: unknown): KnowledgeChoice | null => {
  if (typeof value !== 'string') return null
  try {
    const data = JSON.parse(value)
    if (
      data.kind !== 'course-knowledge-v1' ||
      !Array.isArray(data.options) ||
      !Array.isArray(data.selected)
    )
      return null
    if (
      !data.options.every(
        (item: KnowledgeOption) =>
          item &&
          ['id', 'title', 'summary', 'source'].every(
            (key) => typeof item[key as keyof KnowledgeOption] === 'string',
          ),
      )
    )
      return null
    if (!data.selected.every((item: unknown) => typeof item === 'string')) return null
    return data
  } catch {
    return null
  }
}
