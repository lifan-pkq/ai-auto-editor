# ai-auto-editor

AI 自动剪辑 MVP：上传长视频 → 分析 → Agnes 剪辑导出 → 预览微调。

## 目录

- `backend/` FastAPI：上传、任务状态、进度
- `frontend/` React + Vite + TypeScript：上传、进度、预览下载、参数

## 环境变量

`AGNES_API_BASE` 和 `AGNES_API_KEY` 只通过进程环境变量提供，不要写入仓库、代码或提交 `.env`。

在启动后端的 shell 里设置：

```bash
export AGNES_API_BASE="https://api.agnes-ai.cn/v1"
export AGNES_API_KEY="your-api-key"
```

可选：`export AGNES_MODEL="agnes-3.0-flash"`（未设置时后端使用该默认值）。后端启动时读取这些变量，不会从文件加载密钥。

前端开发服务器默认请求 `http://127.0.0.1:8000`。如需修改，在 `frontend/.env`（已被 gitignore）中设置 `VITE_API_BASE`。
