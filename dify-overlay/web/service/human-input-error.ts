export const humanInputError = async (
  cause: unknown,
): Promise<{ code?: string; message: string }> => {
  if (cause instanceof Response) {
    try {
      const body = (await cause.clone().json()) as { code?: string; message?: string }
      return { code: body.code, message: body.message || cause.statusText }
    } catch {
      return { message: cause.statusText || `HTTP ${cause.status}` }
    }
  }
  if (cause instanceof Error)
    return { code: 'code' in cause ? String(cause.code) : undefined, message: cause.message }
  return { message: String(cause) }
}
