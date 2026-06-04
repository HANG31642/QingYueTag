# -*- coding: utf-8 -*-
"""WD14 Tagger API 服务 (Flask) — 支持多模型选择"""
import io, json, os, csv, sys
from flask import Flask, request, jsonify
from PIL import Image
import onnxruntime as ort
import numpy as np

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
MODELS_DIR = os.path.join(BASE_DIR, "models")

# 可用模型配置（在线模型信息，包括本地未下载的）
AVAILABLE_MODELS = {
    "vit": {
        "name": "ViT v2",
        "desc": "精度最高，标签最准确 (~2GB)",
        "dir": "vit",
        "size": "~2GB",
        "repo": "SmilingWolf/wd-v1-4-vit-tagger-v2",
        "note": "推荐用于高质量标注"
    },
    "convnext": {
        "name": "ConvNeXt v2",
        "desc": "速度最快，适合批量 (~1GB)",
        "dir": "convnext",
        "size": "~1GB",
        "repo": "SmilingWolf/wd-v1-4-convnext-tagger-v2",
        "note": "推荐用于大量图片批量处理"
    },
    "swinv2": {
        "name": "SwinV2 v2",
        "desc": "精度速度均衡 (~1.2GB)",
        "dir": "swinv2",
        "size": "~1.2GB",
        "repo": "SmilingWolf/wd-v1-4-swinv2-tagger-v2",
        "note": "兼顾精度与性能"
    },
    "moat": {
        "name": "MOAT v2",
        "desc": "新型架构，综合表现优秀 (~1.5GB)",
        "dir": "moat",
        "size": "~1.5GB",
        "repo": "SmilingWolf/wd-v1-4-moat-tagger-v2",
        "note": "较新的MOAT架构"
    },
    "convnextv2": {
        "name": "ConvNeXtV2",
        "desc": "ConvNeXt升级版 (~1.1GB)",
        "dir": "convnextv2",
        "size": "~1.1GB",
        "repo": "SmilingWolf/wd-v1-4-convnextv2-tagger-v2",
        "note": "ConvNeXt架构升级版"
    },
    "vit_large_v3": {
        "name": "ViT Large v3",
        "desc": "大模型高精度 (~3.5GB)",
        "dir": "vit_large_v3",
        "size": "~3.5GB",
        "repo": "SmilingWolf/wd-vit-large-tagger-v3",
        "note": "最新版大模型，精度更高但速度较慢"
    },
}

# 命令行参数选择模型，默认 vit
MODEL_KEY = sys.argv[1] if len(sys.argv) > 1 else "vit"
if MODEL_KEY not in AVAILABLE_MODELS:
    print(f"可用模型: {', '.join(AVAILABLE_MODELS.keys())}")
    print(f"用法: python wd14_server.py [vit|convnext|swinv2]")
    exit(1)

model_info = AVAILABLE_MODELS[MODEL_KEY]
MODEL_DIR = os.path.join(MODELS_DIR, model_info["dir"])
MODEL_PATH = os.path.join(MODEL_DIR, "model.onnx")
TAGS_PATH = os.path.join(MODEL_DIR, "selected_tags.csv")

# 加载模型
print(f"⏳ 加载 WD14 {model_info['name']} 模型 ...")
if not os.path.exists(MODEL_PATH):
    print(f"❌ 模型文件不存在: {MODEL_PATH}")
    print("请先运行「安装WD14.bat」下载模型")
    exit(1)

providers = ['CUDAExecutionProvider', 'CPUExecutionProvider']
session = ort.InferenceSession(MODEL_PATH, providers=providers)
print(f"✅ 模型加载成功 ({model_info['name']}, {session.get_providers()[0]})")

# 加载标签
tags = []
if os.path.exists(TAGS_PATH):
    with open(TAGS_PATH, 'r', encoding='utf-8') as f:
        reader = csv.reader(f)
        next(reader)
        for row in reader:
            if len(row) >= 2:
                tags.append(row[1])
print(f"✅ 标签库加载成功 ({len(tags)} 个标签)")

TARGET_SIZE = 448

app = Flask(__name__)


def preprocess(img: Image.Image):
    img = img.convert("RGB")
    w, h = img.size
    scale = TARGET_SIZE / min(w, h)
    nw, nh = int(w * scale), int(h * scale)
    img = img.resize((nw, nh), Image.LANCZOS)
    left = (nw - TARGET_SIZE) // 2
    top = (nh - TARGET_SIZE) // 2
    img = img.crop((left, top, left + TARGET_SIZE, top + TARGET_SIZE))
    arr = np.array(img, dtype=np.float32) / 255.0
    arr = arr.transpose(2, 0, 1)[np.newaxis]
    return arr


@app.route('/wd14/predict', methods=['POST'])
def predict():
    if 'image' not in request.files:
        return jsonify({"error": "no image"}), 400
    file = request.files['image']
    img = Image.open(io.BytesIO(file.read()))
    inp = preprocess(img)
    outputs = session.run(None, {"input": inp.astype(np.float32)})
    probs = outputs[0][0]
    result = {}
    for i, p in enumerate(probs):
        if i < len(tags):
            result[tags[i]] = float(p)
    return jsonify({"tags": result})


@app.route('/wd14/models', methods=['GET'])
def list_models():
    """返回已安装的模型列表"""
    installed = {}
    for key, info in AVAILABLE_MODELS.items():
        mp = os.path.join(MODELS_DIR, info["dir"], "model.onnx")
        installed[key] = {
            "name": info["name"],
            "desc": info["desc"],
            "size": info["size"],
            "installed": os.path.exists(mp),
            "repo": info.get("repo", ""),
            "note": info.get("note", ""),
        }
    return jsonify({"models": installed, "current": MODEL_KEY})


if __name__ == '__main__':
    print(f"🚀 WD14 API 已启动: http://localhost:7860/wd14/predict")
    print(f"   模型列表: http://localhost:7860/wd14/models")
    print(f"   当前模型: {model_info['name']}")
    app.run(host='0.0.0.0', port=7860, debug=False)
