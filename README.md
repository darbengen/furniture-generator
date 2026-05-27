# 家具推广图自动生成器

上传家具产品图 → AI 识别型号/数量/尺寸 → 一键生成办公室布局推广图。

## 功能

- 拖拽上传产品图 + 参照图
- MiMo AI 自动识别家具清单（型号、数量、尺寸）
- 手动编辑校对清单
- 无音科技 API 生成办公室布局图
- 一键下载结果

## 部署

### 前端（GitHub Pages）

1. Fork 本仓库
2. Settings → Pages → Source: Deploy from branch → main → / (root)
3. 修改 `index.html` 中的 `API_BASE` 指向你的 API 服务器

### 后端（VPS）

```bash
python3 -m venv venv && source venv/bin/activate
pip install fastapi uvicorn python-multipart requests
uvicorn api:app --host 0.0.0.0 --port 8892
```

nginx 配置：

```nginx
location /api/ {
    proxy_pass http://127.0.0.1:8892/api/;
    proxy_set_header Host $host;
    proxy_read_timeout 300s;
}
```

### 环境变量

| 变量 | 说明 |
|------|------|
| `WUYIN_KEY` | 无音科技 API key |
| `MIMO_KEY` | MiMo 视觉识别 API key |

## 技术栈

- 前端：单文件 HTML/CSS/JS，零依赖
- 后端：FastAPI
- AI：MiMo V2.5（识图）+ 无音科技（生图）
