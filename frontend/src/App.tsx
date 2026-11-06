import { useEffect, useRef, useState } from 'react'
import type { FormEvent } from 'react'
import {
  uploadVideo,
  getTaskProgress,
  isTerminalStatus,
  isSuccessStatus,
  type AspectRatio,
  type TaskProgress,
} from './api/client'
import './App.css'

type Phase = 'idle' | 'uploading' | 'processing' | 'done' | 'error'

const ASPECT_OPTIONS: { value: AspectRatio; label: string; hint: string }[] = [
  { value: '16:9', label: '16:9', hint: '横屏 · Bilibili/YouTube' },
  { value: '9:16', label: '9:16', hint: '竖屏 · 抖音/Reels' },
  { value: '1:1', label: '1:1', hint: '方形 · 信息流' },
]

const STATUS_LABEL: Record<string, string> = {
  pending: '排队中',
  running: '剪辑中',
  processing: '剪辑中',
  uploading: '上传中',
  transcribing: '语音识别中',
  editing: '剪辑中',
  rendering: '渲染中',
  ready: '已完成',
  completed: '已完成',
  success: '已完成',
  failed: '失败',
  error: '失败',
}

function formatSize(bytes: number): string {
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`
  if (bytes < 1024 * 1024 * 1024) return `${(bytes / 1024 / 1024).toFixed(1)} MB`
  return `${(bytes / 1024 / 1024 / 1024).toFixed(2)} GB`
}

export default function App() {
  const [file, setFile] = useState<File | null>(null)
  const [targetDurationMin, setTargetDurationMin] = useState(3)
  const [aspectRatio, setAspectRatio] = useState<AspectRatio>('9:16')
  const [subtitles, setSubtitles] = useState(true)

  const [phase, setPhase] = useState<Phase>('idle')
  const [task, setTask] = useState<TaskProgress | null>(null)
  const [errorMsg, setErrorMsg] = useState<string | null>(null)
  const pollRef = useRef<number | null>(null)

  const stopPolling = () => {
    if (pollRef.current !== null) {
      window.clearInterval(pollRef.current)
      pollRef.current = null
    }
  }

  useEffect(() => stopPolling, [])

  const startPolling = (taskId: string) => {
    stopPolling()
    const tick = async () => {
      try {
        const p = await getTaskProgress(taskId)
        setTask(p)
        if (isTerminalStatus(p.status)) {
          if (isSuccessStatus(p.status) && p.outputUrl) {
            setPhase('done')
          } else {
            setPhase('error')
            setErrorMsg(p.error ?? `任务结束于状态: ${p.status}`)
          }
          stopPolling()
        }
      } catch (err) {
        setPhase('error')
        setErrorMsg(err instanceof Error ? err.message : '轮询任务进度失败')
        stopPolling()
      }
    }
    void tick()
    pollRef.current = window.setInterval(() => void tick(), 3000)
  }

  const reset = () => {
    stopPolling()
    setFile(null)
    setTask(null)
    setErrorMsg(null)
    setPhase('idle')
  }

  const handleSubmit = async (e: FormEvent<HTMLFormElement>) => {
    e.preventDefault()
    if (!file) {
      setPhase('error')
      setErrorMsg('请先选择要剪辑的视频文件')
      return
    }
    setPhase('uploading')
    setTask(null)
    setErrorMsg(null)
    try {
      const taskId = await uploadVideo({
        file,
        targetDurationMin,
        aspectRatio,
        subtitles,
      })
      setTask({
        taskId,
        status: 'pending',
        progress: 0,
        outputUrl: null,
        message: null,
        error: null,
      })
      setPhase('processing')
      startPolling(taskId)
    } catch (err) {
      setPhase('error')
      setErrorMsg(err instanceof Error ? err.message : '上传失败')
    }
  }

  const busy = phase === 'uploading' || phase === 'processing'
  const statusLabel = task ? (STATUS_LABEL[task.status] ?? task.status) : ''

  return (
    <div className="page">
      <header className="page-header">
        <h1>AI 自动剪辑</h1>
        <p className="subtitle">上传长视频，自动剪出目标时长的短片，支持自定义画幅与字幕</p>
      </header>

      <main className="columns">
        <section className="card">
          <h2>剪辑参数</h2>
          <form className="form" onSubmit={handleSubmit}>
            <label className="field">
              <span className="field-label">视频文件</span>
              <input
                type="file"
                accept="video/*"
                disabled={busy}
                onChange={(e) => setFile(e.target.files?.[0] ?? null)}
              />
              {file ? (
                <span className="file-name">
                  {file.name}（{formatSize(file.size)}）
                </span>
              ) : null}
            </label>

            <label className="field">
              <span className="field-label">目标时长（分钟）</span>
              <input
                type="number"
                min={1}
                max={120}
                step={1}
                value={targetDurationMin}
                disabled={busy}
                onChange={(e) => setTargetDurationMin(Number(e.target.value) || 1)}
              />
            </label>

            <div className="field">
              <span className="field-label">画幅</span>
              <div className="ratio-group" role="radiogroup">
                {ASPECT_OPTIONS.map((opt) => (
                  <button
                    key={opt.value}
                    type="button"
                    role="radio"
                    aria-checked={aspectRatio === opt.value}
                    className={aspectRatio === opt.value ? 'ratio-btn active' : 'ratio-btn'}
                    disabled={busy}
                    onClick={() => setAspectRatio(opt.value)}
                  >
                    <span className="ratio-btn-label">{opt.label}</span>
                    <span className="ratio-btn-hint">{opt.hint}</span>
                  </button>
                ))}
              </div>
            </div>

            <label className="field switch-field">
              <span className="field-label">自动加字幕</span>
              <button
                type="button"
                role="switch"
                aria-checked={subtitles}
                className={subtitles ? 'switch on' : 'switch'}
                disabled={busy}
                onClick={() => setSubtitles((v) => !v)}
              >
                <span className="switch-thumb" />
              </button>
              <span className="switch-text">{subtitles ? '开启' : '关闭'}</span>
            </label>

            <div className="actions">
              <button type="submit" className="primary" disabled={busy}>
                {busy ? '处理中…' : '开始剪辑'}
              </button>
              {task ? <button type="button" className="ghost" onClick={reset}>重新剪辑</button> : null}
            </div>
          </form>
        </section>

        <section className="card">
          <h2>任务状态</h2>

          {phase === 'idle' ? (
            <p className="muted">左侧填写参数并上传视频，任务开始后这里会显示进度。</p>
          ) : null}

          {busy || phase === 'done' || (phase === 'error' && task) ? (
            <div className="task">
              <div className="task-meta">
                <span className="task-status">{phase === 'uploading' ? '上传中' : statusLabel}</span>
                {task?.taskId ? <span className="task-id">任务 {task.taskId}</span> : null}
              </div>
              <div className="progress-track" aria-label="任务进度">
                <div
                  className="progress-fill"
                  style={{ width: `${Math.round(task?.progress ?? 0)}%` }}
                />
              </div>
              <p className="task-percent">{Math.round(task?.progress ?? 0)}%</p>
              {task?.message ? <p className="task-message">{task.message}</p> : null}
            </div>
          ) : null}

          {phase === 'error' ? (
            <div className="error-box">
              <p>{errorMsg ?? '任务失败'}</p>
            </div>
          ) : null}

          {phase === 'done' && task?.outputUrl ? (
            <div className="result">
              <div className={`preview ratio-${aspectRatio.replace(':', '')}`}>
                <video src={task.outputUrl} controls autoPlay />
              </div>
              <div className="result-actions">
                <a
                  className="primary download"
                  href={task.outputUrl}
                  download
                  target="_blank"
                  rel="noreferrer"
                >
                  下载成片
                </a>
                <a
                  className="ghost"
                  href={task.outputUrl}
                  target="_blank"
                  rel="noreferrer"
                >
                  新标签页打开
                </a>
              </div>
            </div>
          ) : null}
        </section>
      </main>
    </div>
  )
}
