# 家具推广图自动生成器

上传家具产品图 → AI 识别型号/数量/尺寸 → 选场景 → 一键生成推广图。

## 功能

- 拖拽上传产品图 + 可选参照图
- MiMo AI 自动识别家具清单（型号、数量、尺寸）
- 手动编辑校对清单
- **5 种场景选择**：开放办公区 / 会议室 / 展厅陈列 / 居家书房 / 创意工作室
- 无音科技 API 生成场景布局图（产品图会传给 AI 参考，保证配色造型一致）
- 一键下载结果

## 部署

### 环境变量

```bash
export WUYIN_KEY="你的无音科技API key"
export MIMO_KEY="你的MiMo视觉识别API key"
export LOCAL_HOST="http://你的服务器IP:8892"  # 可选，默认 localhost:8892
```

### 后端

```bash
cd furniture-generator
pip install fastapi uvicorn python-multipart requests
uvicorn api:app --host 0.0.0.0 --port 8892
```

生产环境可用 systemd + nginx 反代。

### nginx 配置

```nginx
location /api/ {
    proxy_pass http://127.0.0.1:8892/api/;
    proxy_set_header Host $host;
    proxy_read_timeout 300s;
}
location /uploads/ {
    proxy_pass http://127.0.0.1:8892/uploads/;
}
```

### 前端

直接浏览器打开 `index.html`，或部署到 GitHub Pages / VPS。

## API

| 端点 | 说明 |
|------|------|
| `GET /api/health` | 健康检查 + key 配置状态 |
| `GET /api/scenes` | 获取场景列表 |
| `POST /api/analyze` | MiMo 识别产品图（product file） |
| `POST /api/generate` | 生成推广图（product + items + scene + optional ref） |
| `POST /api/pipeline` | 一站式：识别 + 生成 |

## 技术栈

- 前端：单文件 HTML/CSS/JS，零依赖
- 后端：FastAPI + StaticFiles
- AI：MiMo V2.5（识图）+ 无音科技（生图）
