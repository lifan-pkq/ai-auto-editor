# AI Auto-Editor Backend

FastAPI MVP：上传 → Agnes 分析出剪辑方案 → FFmpeg 剪辑导出 → 成片下载。

## 环境变量

- `AGNES_API_BASE`（例：`https://api.agnes-ai.cn/v1`）
- `AGNES_API_KEY`
- 可选 `AGNES_MODEL`（默认 `agnes-3.0-flash`）

## 启动

```bash
cd /workspace/projects/ai-auto-editor/backend
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload
```

## 验收

1. `GET /api/v1/health` → 200
2. `POST /api/v1/upload` multipart 字段 `file`
3. 轮询 `GET /api/v1/tasks/{id}/progress`：analyzing → editing → exporting → ready
4. `GET /api/v1/tasks/{id}` 的 `output_url`，再打开 `/api/v1/files/{id}/output.mp4`

依赖本机 `ffmpeg` / `ffprobe`。
