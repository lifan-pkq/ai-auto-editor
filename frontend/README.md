# frontend — AI 自动剪辑

上传长视频，AI 自动剪出目标时长短片（MVP）。

## 功能

- 上传视频并附带参数：目标时长（分钟）、画幅（16:9 / 9:16 / 1:1）、字幕开关
- 轮询任务进度，显示百分比与阶段信息
- 任务完成后在线预览成片并提供下载

## 接口约定

- 上传：`POST {API}/api/v1/upload`（multipart 字段 `file`，另附 `target_duration_min`、`aspect_ratio`、`subtitles`）
- 进度：`GET {API}/api/v1/tasks/{id}/progress`（前端每 3 秒轮询一次，直到任务终态；成片地址取响应中的 `output_url`）

## 配置

后端地址默认 `http://127.0.0.1:8000`。如需修改，在项目根目录创建 `.env` 文件：

```
VITE_API_BASE=http://127.0.0.1:8000
```

无需配置任何 API Key。

## 启动

```bash
npm install
npm run dev
```

开发服务器默认运行在 `http://127.0.0.1:5173`。

## 构建

```bash
npm run build
npm run preview
```

## 目录结构

- `src/api/client.ts` — API 客户端（上传 / 查询进度）
- `src/App.tsx` — 页面（参数表单、进度轮询、成片预览与下载）
- `src/App.css` — 页面样式
