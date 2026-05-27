from fastapi import FastAPI, UploadFile, File, Form
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
import requests, time, base64, os, json, uuid, re

app = FastAPI()
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

WUYIN_KEY = "8p8GmYqBSDUWx2xcMzkZmaISm1"
MIMO_KEY = "tp-cnk3nzszdbyq8xsthxzn9r5mfn54i226zdu8sw6m5475s9oy"
UPLOAD_DIR = "/tmp/uploads"

os.makedirs(UPLOAD_DIR, exist_ok=True)

TEMPLATE = "Copy every item from product photo exactly: same look color. Dimensions must match: {dims}. {items}. Different chairs as in photo. Bright office. White walls wood floor plants. Total {total} items. Nothing else."


def mimo_analyze(image_bytes):
    img_b64 = base64.b64encode(image_bytes).decode()
    resp = requests.post(
        "https://token-plan-cn.xiaomimimo.com/v1/chat/completions",
        headers={"Authorization": f"Bearer {MIMO_KEY}", "Content-Type": "application/json"},
        json={"model": "mimo-v2.5", "messages": [{"role": "user", "content": [
            {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{img_b64}"}},
            {"type": "text",
             "text": "List ALL furniture items: model name, quantity, dimensions in mm. Output JSON array only: [{\"model\":\"...\",\"qty\":N,\"dims\":\"...\"}]"}
        ]}], "max_tokens": 500}, timeout=120)
    return resp.json()["choices"][0]["message"]["content"]


def build_prompt(items):
    dims, lines = [], []
    total = sum(i.get("qty", 1) for i in items)
    for item in items:
        qty = item.get("qty", 1)
        dims.append(f"{item['model']}={item.get('dims', '')}")
        lines.append(f"{qty} {item['model']}")
    return TEMPLATE.format(dims=", ".join(dims), items=". ".join(lines), total=total), total


def wuyin_generate(prompt, urls):
    r = requests.post("https://api.wuyinkeji.com/api/async/image_gpt",
                      json={"key": WUYIN_KEY, "prompt": prompt, "urls": urls}, timeout=30).json()
    if r.get("code") != 200:
        return None, r.get("msg", r.get("message", "error"))
    tid = r["data"]["id"]
    for _ in range(80):
        time.sleep(4)
        d = requests.get(
            f"https://api.wuyinkeji.com/api/async/detail?id={tid}&key={WUYIN_KEY}",
            timeout=30).json()
        s = d.get("data", {}).get("status", -1)
        if s == 2:
            return d["data"]["result"][0], None
        if s == 3:
            return None, d.get("data", {}).get("message", "policy")
    return None, "timeout"


# Local serving via localhost HTTP server
LOCAL_HOST = "http://localhost:8890"

def save_upload(data, prefix=""):
    name = f"{prefix}{uuid.uuid4().hex[:12]}.jpg"
    local_path = os.path.join(UPLOAD_DIR, name)
    with open(local_path, "wb") as f:
        f.write(data)
    # Return localhost URL for Wuyin to fetch (needs to be accessible)
    return f"{LOCAL_HOST}/uploads/{name}"


def parse_items(analysis_text):
    """Extract JSON array from MiMo response."""
    try:
        m = re.search(r'\[.*\]', analysis_text, re.DOTALL)
        if m:
            items = json.loads(m.group())
            # Ensure each item has required fields
            for item in items:
                if "model" not in item:
                    item["model"] = "furniture"
                if "qty" not in item:
                    item["qty"] = 1
                if "dims" not in item:
                    item["dims"] = ""
            return items
    except Exception:
        pass
    return [{"model": "furniture", "qty": 1, "dims": ""}]


@app.get("/api/health")
async def health():
    return {"ok": True}


@app.post("/api/analyze")
async def analyze(product: UploadFile = File(...)):
    """Analyze product image with MiMo — returns parsed furniture items only."""
    prod_data = await product.read()
    analysis_text = mimo_analyze(prod_data)
    items = parse_items(analysis_text)
    return JSONResponse(content={"ok": True, "items": items, "raw_analysis": analysis_text})


@app.post("/api/generate")
async def generate(
    product: UploadFile = File(...),
    reference: UploadFile = File(None),
    items: str = Form("[]"),
):
    """Generate using pure text prompt (no external image reference)."""
    # Save locally only
    prod_data = await product.read()
    save_upload(prod_data, "prod_")
    ref_data = await reference.read() if reference else None
    if ref_data:
        save_upload(ref_data, "ref_")

    try:
        user_items = json.loads(items)
    except json.JSONDecodeError:
        return JSONResponse(content={"ok": False, "error": "Invalid items JSON"}, status_code=400)

    # Build prompt WITHOUT image URLs - pure text
    prompt, total = build_prompt(user_items)
    
    # Call Wuyin with empty URLs - rely on text description
    result_url, error = wuyin_generate(prompt, [])  # empty urls array
    if error:
        return JSONResponse(content={"ok": False, "error": error, "prompt": prompt})

    # Download result
    img_data = requests.get(result_url, timeout=60).content
    out_url = save_upload(img_data, "out_")
    return JSONResponse(content={
        "ok": True,
        "image_url": out_url,
        "prompt": prompt,
        "items": user_items,
        "total": total,
    })


@app.post("/api/pipeline")
async def pipeline(product: UploadFile = File(...), reference: UploadFile = File(None)):
    """Full pipeline (analyze + generate) for backward compatibility."""
    prod_data = await product.read()
    prod_url = save_upload(prod_data, "prod_")
    ref_url = save_upload(await reference.read(), "ref_") if reference else None

    analysis = mimo_analyze(prod_data)
    items = parse_items(analysis)

    prompt, total = build_prompt(items)
    refs = [prod_url] + ([ref_url] if ref_url else [])
    result_url, error = wuyin_generate(prompt, refs)
    if error:
        return JSONResponse(content={"ok": False, "error": error, "prompt": prompt})

    img_data = requests.get(result_url, timeout=60).content
    out_url = save_upload(img_data, "out_")
    return JSONResponse(content={
        "ok": True,
        "image_url": out_url,
        "prompt": prompt,
        "items": items,
        "total": total,
    })
