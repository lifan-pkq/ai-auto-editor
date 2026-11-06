const API_BASE: string = import.meta.env.VITE_API_BASE ?? 'http://127.0.0.1:8000'

export type AspectRatio = '16:9' | '9:16' | '1:1'

export interface UploadParams {
  file: File
  targetDurationMin: number
  aspectRatio: AspectRatio
  subtitles: boolean
}

export interface TaskProgress {
  taskId: string
  status: string
  progress: number
  outputUrl: string | null
  message: string | null
  error: string | null
}

async function parseJson(res: Response): Promise<Record<string, unknown>> {
  const text = await res.text()
  if (!text) return {}
  try {
    return JSON.parse(text) as Record<string, unknown>
  } catch {
    return {}
  }
}

function asString(value: unknown): string | null {
  return typeof value === 'string' && value.length > 0 ? value : null
}


function resolveMediaUrl(url: string | null): string | null {
  if (!url) return null
  if (/^https?:\/\//i.test(url)) return url
  if (url.startsWith('/')) return `${API_BASE}${url}`
  return `${API_BASE}/${url}`
}

function normalizeTask(data: Record<string, unknown>, taskId: string): TaskProgress {
  const nested = (data.task ?? data.data) as Record<string, unknown> | undefined
  const src = { ...data, ...(nested ?? {}) }
  const taskIdStr = asString(src.task_id) ?? asString(src.id) ?? taskId
  const status = (asString(src.status) ?? 'pending').toLowerCase()
  const rawProgress =
    typeof src.progress === 'number'
      ? src.progress
      : typeof src.percent === 'number'
        ? src.percent
        : 0
  const progress =
    rawProgress > 0 && rawProgress <= 1 ? rawProgress * 100 : Math.min(100, Math.max(0, rawProgress))
  const rawOutputUrl =
    asString(src.output_url) ??
    asString((src.output as Record<string, unknown> | undefined)?.url ?? null)
  const outputUrl = resolveMediaUrl(rawOutputUrl)

  return {
    taskId: taskIdStr,
    status,
    progress,
    outputUrl,
    message: asString(src.message) ?? asString(src.stage),
    error: asString(src.error) ?? asString(src.error_message),
  }
}

export async function uploadVideo(params: UploadParams): Promise<string> {
  const form = new FormData()
  form.append('file', params.file)
  form.append('target_duration_min', String(params.targetDurationMin))
  form.append('aspect_ratio', params.aspectRatio)
  form.append('subtitles', params.subtitles ? 'true' : 'false')

  const res = await fetch(`${API_BASE}/api/v1/upload`, {
    method: 'POST',
    body: form,
  })
  if (!res.ok) {
    const data = await parseJson(res)
    const detail = asString(data.detail) ?? asString(data.message)
    throw new Error(`上传失败 (${res.status})${detail ? `: ${detail}` : ''}`)
  }

  const data = await parseJson(res)
  const taskId =
    asString(data.task_id) ??
    asString(data.id) ??
    asString((data.task as Record<string, unknown> | undefined)?.id)
  if (!taskId) throw new Error('上传响应缺少 task_id')
  return taskId
}

export async function getTaskProgress(taskId: string): Promise<TaskProgress> {
  // Prefer task detail so message/output_url are always available.
  const res = await fetch(
    `${API_BASE}/api/v1/tasks/${encodeURIComponent(taskId)}`,
  )
  if (!res.ok) {
    const data = await parseJson(res)
    const detail = asString(data.detail) ?? asString(data.message)
    throw new Error(`查询任务失败 (${res.status})${detail ? `: ${detail}` : ''}`)
  }
  return normalizeTask(await parseJson(res), taskId)
}

export function isTerminalStatus(status: string): boolean {
  const s = status.toLowerCase()
  return (
    s === 'ready' ||
    s === 'completed' ||
    s === 'complete' ||
    s === 'success' ||
    s === 'succeeded' ||
    s === 'failed' ||
    s === 'error' ||
    s === 'cancelled' ||
    s === 'canceled'
  )
}

export function isSuccessStatus(status: string): boolean {
  const s = status.toLowerCase()
  return (
    s === 'ready' ||
    s === 'completed' ||
    s === 'complete' ||
    s === 'success' ||
    s === 'succeeded'
  )
}
