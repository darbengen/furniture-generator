from fastapi import FastAPI, HTTPException
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
import requests, time, base64, os, json, uuid, re

# ── Load .env ──────────────────────────────────────────────────
def _load_dotenv(path):
    if os.path.isfile(path):
        with open(path) as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))
_load_dotenv(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env"))

# ── Config ─────────────────────────────────────────────────────
WUYIN_KEY = os.environ.get("WUYIN_KEY", "")
MIMO_KEY = os.environ.get("MIMO_KEY", "")
BIGJPG_KEY = os.environ.get("BIGJPG_KEY", "")
UPLOAD_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "uploads")
LOCAL_HOST = os.environ.get("LOCAL_HOST", "http://localhost:8892")
# Xiaolongxia2 poster_backend handles uploads + static serving
X2_UPLOAD_URL = os.environ.get("X2_UPLOAD_URL", "http://124.223.42.124:8891/upload")
X2_SECRET = os.environ.get("X2_SECRET", "-1xweDVeOQrxgXBfgcTUMgxBH9GOhIP8")
PUBLIC_BASE = os.environ.get("PUBLIC_BASE", "http://124.223.42.124:8891/uploads")

os.makedirs(UPLOAD_DIR, exist_ok=True)

app = FastAPI()
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

# ── Pydantic models ────────────────────────────────────────────
class ImgEntry(BaseModel):
    dataUrl: str

class UploadReq(BaseModel):
    images: list[ImgEntry]

class AnalyzeReq(BaseModel):
    data_url: str

class GenerateReq(BaseModel):
    product_url: str
    ref_url: str = ""
    items: list[dict] = []
    scene: str = "office"
    upscale: int = 0  # 0=none, 2=2x, 4=4x

class PipelineReq(BaseModel):
    product_url: str
    data_url: str = ""
    ref_url: str = ""
    scene: str = "office"
    upscale: int = 0

# ── Scene Catalog ───────────────────────────────────────────────
SCENES = {
    "office": {
        "name": "开放办公区",
        "description": "明亮现代开放办公室，白墙木地板，绿植点缀",
        "prompt": (
            "Place every item from the product photo exactly as shown: identical look, color, and finish. "
            "Dimensions MUST match: {dims}. "
            "Items to place: {items}. "
            "Layout: {total} items in an open-plan office. "
            "White walls, light wood floor, potted plants, floor-to-ceiling windows with natural daylight. "
            "Wide angle shot showing the full layout. Professional furniture catalog quality."
        )
    },
    "meeting": {
        "name": "会议室",
        "description": "深色木质会议桌，皮质座椅，专业氛围",
        "prompt": (
            "Place every item from the product photo exactly as shown: identical look, color, and finish. "
            "Dimensions MUST match: {dims}. "
            "Items to place: {items}. "
            "Layout: {total} items arranged around a dark wood conference table. "
            "Dark wood conference table as centerpiece, leather chairs positioned around it. "
            "Warm overhead lighting, glass partition walls, corporate professional atmosphere. "
            "Wide angle shot showing the full meeting room. Premium catalog quality."
        )
    },
    "showroom": {
        "name": "展厅陈列",
        "description": "高端展厅灯光，独立陈列，美术馆风格",
        "prompt": (
            "Place every item from the product photo exactly as shown: identical look, color, and finish. "
            "Dimensions MUST match: {dims}. "
            "Items to place: {items}. "
            "Layout: {total} items displayed in a high-end furniture showroom. "
            "Gallery-style track lighting, polished concrete floor, minimalist white walls. "
            "Each piece given breathing room with strategic spotlighting. "
            "Museum/gallery curation feel. Premium furniture exhibition quality."
        )
    },
    "home": {
        "name": "居家书房",
        "description": "温馨家庭书房，书架背景，暖色调灯光",
        "prompt": (
            "Place every item from the product photo exactly as shown: identical look, color, and finish. "
            "Dimensions MUST match: {dims}. "
            "Items to place: {items}. "
            "Layout: {total} items in a cozy home study. "
            "Built-in bookshelf wall background, warm ambient lighting, area rug on hardwood floor. "
            "Lived-in but tidy feel. Natural light from side window. "
            "Cozy home office catalog quality."
        )
    },
    "creative": {
        "name": "创意工作室",
        "description": "工业风 loft，裸露砖墙，彩色 accent，活泼氛围",
        "prompt": (
            "Place every item from the product photo exactly as shown: identical look, color, and finish. "
            "Dimensions MUST match: {dims}. "
            "Items to place: {items}. "
            "Layout: {total} items in a creative studio loft. "
            "Exposed brick wall, colorful accent decorations, industrial pendant lights. "
            "Large factory windows, polished concrete floor, vibrant energetic atmosphere. "
            "Creative workspace catalog quality."
        )
    },
}

# ── Helpers ──────────────────────────────────────────────────────

def decode_data_url(data_url: str) -> tuple[bytes, str]:
    """Decode a base64 data URL to raw bytes + file extension. No compression."""
    m = re.match(r"data:image/(\w+);base64,(.+)", data_url)
    if not m:
        raise ValueError("Invalid data URL format")
    ext = m.group(1)
    if ext == "jpeg":
        ext = "jpg"
    return base64.b64decode(m.group(2)), ext


def upload_to_x2(data_url: str) -> str | None:
    """Upload image to xiaolongxia2 poster_backend via HTTP. Returns public URL."""
    try:
        r = requests.post(
            X2_UPLOAD_URL,
            headers={"Content-Type": "application/json", "x-poster-secret": X2_SECRET},
            json={"images": [{"dataUrl": data_url}]},
            timeout=30
        ).json()
    except requests.RequestException as e:
        print(f"Upload to xiaolongxia2 failed: {e}")
        return None
    if r.get("ok") and r.get("urls"):
        return r["urls"][0]
    print(f"Upload rejected: {r.get('error', 'unknown')}")
    return None


def mimo_analyze(image_bytes: bytes) -> str:
    """Analyze product image with MiMo. Returns raw JSON text."""
    if not MIMO_KEY:
        raise RuntimeError("MIMO_KEY not configured")
    img_b64 = base64.b64encode(image_bytes).decode()
    try:
        resp = requests.post(
            "https://token-plan-cn.xiaomimimo.com/v1/chat/completions",
            headers={"Authorization": f"Bearer {MIMO_KEY}", "Content-Type": "application/json"},
            json={
                "model": "mimo-v2.5",
                "messages": [{"role": "user", "content": [
                    {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{img_b64}"}},
                    {"type": "text", "text": (
                        "Output ONLY a JSON array of furniture in the photo. "
                        "Format: [{\"model\":\"name\",\"qty\":number,\"dims\":\"W*D*H mm\"}]. "
                        "No explanation, no markdown, just the array."
                    )}
                ]}],
                "max_tokens": 2000
            }, timeout=120)
        data = resp.json()
        if "choices" not in data:
            raise RuntimeError(f"MiMo response error: {data.get('error', {}).get('message', str(data))}")
        return data["choices"][0]["message"]["content"]
    except requests.Timeout:
        raise RuntimeError("MiMo 识别超时，请重试")
    except requests.RequestException as e:
        raise RuntimeError(f"MiMo 网络错误: {str(e)}")


def parse_items(analysis_text: str) -> list[dict]:
    """Extract JSON array from MiMo response."""
    text = analysis_text.strip()
    fence = re.search(r'```(?:json)?\s*\n?(.*?)\n?```', text, re.DOTALL)
    if fence:
        text = fence.group(1).strip()
    for m in re.finditer(r'\[.*?\]', text, re.DOTALL):
        try:
            items = json.loads(m.group())
            if isinstance(items, list) and len(items) > 0 and isinstance(items[0], dict):
                for item in items:
                    item.setdefault("model", "furniture")
                    item.setdefault("qty", 1)
                    item.setdefault("dims", "")
                return items
        except json.JSONDecodeError:
            continue
    try:
        items = json.loads(text)
        if isinstance(items, list) and len(items) > 0:
            for item in items:
                item.setdefault("model", "furniture")
                item.setdefault("qty", 1)
                item.setdefault("dims", "")
            return items
    except Exception:
        pass
    return [{"model": "furniture", "qty": 1, "dims": ""}]


def build_prompt(items: list[dict], scene_id: str = "office") -> tuple[str, int]:
    scene = SCENES.get(scene_id, SCENES["office"])
    dims, lines = [], []
    total = sum(i.get("qty", 1) for i in items)
    for item in items:
        qty = item.get("qty", 1)
        dims.append(f"{item['model']}={item.get('dims', '')}")
        lines.append(f"{qty} {item['model']}")
    prompt = scene["prompt"].format(
        dims=", ".join(dims),
        items=". ".join(lines),
        total=total
    )
    return prompt, total


def wuyin_generate(prompt: str, urls: list[str]) -> tuple[str | None, str | None]:
    """Call Wuyin async generation with VPS URLs. Returns (result_url, error)."""
    if not WUYIN_KEY:
        return None, "WUYIN_KEY not configured"
    try:
        r = requests.post(
            "https://api.wuyinkeji.com/api/async/image_gpt",
            json={"key": WUYIN_KEY, "prompt": prompt, "urls": urls},
            timeout=30
        ).json()
    except requests.Timeout:
        return None, "无音 API 超时"
    except requests.RequestException as e:
        return None, f"无音网络错误: {str(e)}"

    if r.get("code") != 200:
        return None, r.get("msg") or r.get("message") or "无音返回错误"

    tid = r["data"]["id"]
    for attempt in range(80):
        time.sleep(4)
        try:
            d = requests.get(
                f"https://api.wuyinkeji.com/api/async/detail?id={tid}&key={WUYIN_KEY}",
                timeout=30
            ).json()
        except Exception:
            continue
        s = d.get("data", {}).get("status", -1)
        if s == 2:
            return d["data"]["result"][0], None
        if s == 3:
            return None, d.get("data", {}).get("message", "内容审核未通过")
    return None, "生成超时（5分钟）"


def cache_output(image_url: str) -> str:
    """Download generated image from Wuyin CDN, save locally, return local URL."""
    try:
        img_data = requests.get(image_url, timeout=60).content
    except Exception:
        raise RuntimeError("下载生成结果失败")
    name = f"out_{uuid.uuid4().hex[:12]}.jpg"
    local_path = os.path.join(UPLOAD_DIR, name)
    with open(local_path, "wb") as f:
        f.write(img_data)
    return f"/uploads/{name}"


def cache_and_vps(image_url: str) -> tuple[str, str]:
    """Download generated image, save locally AND upload to xiaolongxia2 for public access.
    Returns (local_url, public_url)."""
    try:
        img_data = requests.get(image_url, timeout=60).content
    except Exception:
        raise RuntimeError("下载生成结果失败")
    name = f"out_{uuid.uuid4().hex[:12]}.jpg"
    local_path = os.path.join(UPLOAD_DIR, name)
    with open(local_path, "wb") as f:
        f.write(img_data)

    data_url = "data:image/jpeg;base64," + base64.b64encode(img_data).decode()
    public_url = upload_to_x2(data_url)
    if not public_url:
        raise RuntimeError("上传输出图到小龙虾2号失败")
    return f"/uploads/{name}", public_url


def bigjpg_upscale(image_url: str, scale: int = 2) -> bytes:
    """Upscale image via bigjpg.com API. Returns raw bytes of upscaled image.
    scale: 2 (2x) or 4 (4x). Blocks until done (polling)."""
    if not BIGJPG_KEY:
        raise RuntimeError("BIGJPG_KEY not configured")
    if scale not in (2, 4):
        raise RuntimeError("upscale must be 2 or 4")
    x2 = "1" if scale == 2 else "2"  # bigjpg API: 1=2x, 2=4x

    # Submit task
    try:
        r = requests.post(
            "https://bigjpg.com/api/task/",
            data={"conf": json.dumps({"style": "photo", "noise": "-1", "x2": x2, "input": image_url})},
            headers={"X-API-KEY": BIGJPG_KEY},
            timeout=30
        ).json()
    except requests.RequestException as e:
        raise RuntimeError(f"bigjpg 提交失败: {str(e)}")

    if r.get("status") == "valid_api_key_required":
        raise RuntimeError("bigjpg API key 无效，请在 bigjpg.com 注册获取")
    if r.get("status") == "param_error":
        raise RuntimeError(f"bigjpg 参数错误: {r}")
    tid = r.get("tid")
    if not tid:
        raise RuntimeError(f"bigjpg 返回异常: {r}")

    # Poll for result
    for attempt in range(120):
        time.sleep(2)
        try:
            d = requests.get(f"https://bigjpg.com/api/task/{tid}", timeout=30).json()
        except Exception:
            continue
        status = d.get(tid, {}).get("status", "")
        if status == "success":
            result_url = d[tid]["url"]
            try:
                return requests.get(result_url, timeout=120).content
            except Exception:
                raise RuntimeError("下载超分结果失败")
        if status == "error":
            raise RuntimeError("bigjpg 处理失败")

    raise RuntimeError("bigjpg 超分超时（4分钟）")


# ── Routes ───────────────────────────────────────────────────────

@app.get("/api/health")
async def health():
    return {"ok": True, "mimo_configured": bool(MIMO_KEY), "wuyin_configured": bool(WUYIN_KEY),
            "bigjpg_configured": bool(BIGJPG_KEY)}


@app.get("/api/scenes")
async def list_scenes():
    return {"ok": True, "scenes": [
        {"id": k, "name": v["name"], "description": v["description"]}
        for k, v in SCENES.items()
    ]}


@app.post("/api/upload")
async def upload(req: UploadReq):
    """Upload images to VPS. Takes base64 data URLs → SCP to VPS → returns public URLs."""
    urls = []
    for img in req.images:
        vps_url = upload_to_x2(img.dataUrl)
        if vps_url:
            urls.append(vps_url)
        else:
            return JSONResponse(content={"ok": False, "error": "上传到小龙虾2号失败"}, status_code=500)
    return {"ok": True, "urls": urls}


@app.post("/api/analyze")
async def analyze(req: AnalyzeReq):
    """Analyze product image with MiMo. Takes base64 data URL → returns furniture items."""
    if not MIMO_KEY:
        return JSONResponse(content={"ok": False, "error": "MiMo API key 未配置"}, status_code=500)
    try:
        raw, ext = decode_data_url(req.data_url)
    except ValueError as e:
        return JSONResponse(content={"ok": False, "error": str(e)}, status_code=400)
    if len(raw) > 10 * 1024 * 1024:
        return JSONResponse(content={"ok": False, "error": "图片不能超过 10MB"}, status_code=400)
    try:
        analysis_text = mimo_analyze(raw)
        items = parse_items(analysis_text)
        return {"ok": True, "items": items, "raw_analysis": analysis_text}
    except RuntimeError as e:
        return JSONResponse(content={"ok": False, "error": str(e)}, status_code=500)


@app.post("/api/generate")
async def generate(req: GenerateReq):
    """Generate furniture promotional image using VPS-hosted product/reference images."""
    if not WUYIN_KEY:
        return JSONResponse(content={"ok": False, "error": "Wuyin API key 未配置"}, status_code=500)
    if not req.items:
        return JSONResponse(content={"ok": False, "error": "请至少添加一件家具"}, status_code=400)
    if req.scene not in SCENES:
        req.scene = "office"

    prompt, total = build_prompt(req.items, req.scene)

    urls = [req.product_url]
    if req.ref_url:
        urls.append(req.ref_url)

    result_url, error = wuyin_generate(prompt, urls)
    if error:
        return JSONResponse(content={"ok": False, "error": error, "prompt": prompt})

    # Optional bigjpg upscale
    if req.upscale and req.upscale in (2, 4):
        if not BIGJPG_KEY:
            return JSONResponse(content={"ok": False, "error": "BIGJPG_KEY 未配置"}, status_code=500)
        try:
            _, vps_url = cache_and_vps(result_url)
            upscaled = bigjpg_upscale(vps_url, req.upscale)
            name = f"out_{uuid.uuid4().hex[:12]}.jpg"
            with open(os.path.join(UPLOAD_DIR, name), "wb") as f:
                f.write(upscaled)
            local_url = f"/uploads/{name}"
        except RuntimeError as e:
            return JSONResponse(content={"ok": False, "error": str(e)}, status_code=500)
    else:
        try:
            local_url = cache_output(result_url)
        except RuntimeError as e:
            return JSONResponse(content={"ok": False, "error": str(e)}, status_code=500)

    return {"ok": True, "image_url": local_url, "prompt": prompt,
            "items": req.items, "total": total, "scene": req.scene}


@app.post("/api/pipeline")
async def pipeline(req: PipelineReq):
    """Full pipeline: analyze product + generate image in one call."""
    if not MIMO_KEY or not WUYIN_KEY:
        missing = []
        if not MIMO_KEY: missing.append("MiMo")
        if not WUYIN_KEY: missing.append("Wuyin")
        return JSONResponse(
            content={"ok": False, "error": f"API key 未配置: {', '.join(missing)}"},
            status_code=500)

    # Step 1: get product bytes for MiMo (prefer supplied data_url, else download from VPS)
    prod_data = None
    if req.data_url:
        try:
            prod_data, _ = decode_data_url(req.data_url)
        except ValueError as e:
            return JSONResponse(content={"ok": False, "error": str(e)}, status_code=400)
    else:
        try:
            prod_resp = requests.get(req.product_url, timeout=30)
            prod_resp.raise_for_status()
            prod_data = prod_resp.content
        except Exception as e:
            return JSONResponse(content={"ok": False, "error": f"下载产品图失败: {str(e)}"}, status_code=500)

    if len(prod_data) > 10 * 1024 * 1024:
        return JSONResponse(content={"ok": False, "error": "图片不能超过 10MB"}, status_code=400)

    try:
        analysis_text = mimo_analyze(prod_data)
        items = parse_items(analysis_text)
    except RuntimeError as e:
        return JSONResponse(content={"ok": False, "error": f"识别失败: {str(e)}"}, status_code=500)

    if req.scene not in SCENES:
        req.scene = "office"

    prompt, total = build_prompt(items, req.scene)

    urls = [req.product_url]
    if req.ref_url:
        urls.append(req.ref_url)

    result_url, error = wuyin_generate(prompt, urls)
    if error:
        return JSONResponse(content={"ok": False, "error": error, "prompt": prompt})

    # Optional bigjpg upscale
    if req.upscale and req.upscale in (2, 4):
        if not BIGJPG_KEY:
            return JSONResponse(content={"ok": False, "error": "BIGJPG_KEY 未配置"}, status_code=500)
        try:
            _, vps_url = cache_and_vps(result_url)
            upscaled = bigjpg_upscale(vps_url, req.upscale)
            name = f"out_{uuid.uuid4().hex[:12]}.jpg"
            with open(os.path.join(UPLOAD_DIR, name), "wb") as f:
                f.write(upscaled)
            local_url = f"/uploads/{name}"
        except RuntimeError as e:
            return JSONResponse(content={"ok": False, "error": str(e)}, status_code=500)
    else:
        try:
            local_url = cache_output(result_url)
        except RuntimeError as e:
            return JSONResponse(content={"ok": False, "error": str(e)}, status_code=500)

    return {"ok": True, "image_url": local_url, "prompt": prompt,
            "items": items, "total": total, "scene": req.scene}


# ── Static files ─────────────────────────────────────────────────
app.mount("/uploads", StaticFiles(directory=UPLOAD_DIR), name="uploads")
