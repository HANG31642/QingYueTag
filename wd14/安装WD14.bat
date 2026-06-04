@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo ========================================
echo   WD14 标签反推 API — 一键安装
echo ========================================
echo.

:: 检查 Python
python --version >nul 2>&1
if %errorlevel% neq 0 (
    echo [❌] 未检测到 Python，请先安装 Python 3.10+
    pause
    exit /b 1
)
echo [✅] Python 已检测

:: 选择 pip 镜像源
echo.
echo 请选择 pip 镜像源:
echo   [1] 默认源 (pypi.org)
echo   [2] 清华镜像 (推荐国内用户)
echo   [3] 阿里云镜像
set /p mirror_choice="请输入选项 (1/2/3, 默认2): "
if "%mirror_choice%"=="" set mirror_choice=2
if "%mirror_choice%"=="1" set PIP_INDEX=
if "%mirror_choice%"=="2" set PIP_INDEX=-i https://pypi.tuna.tsinghua.edu.cn/simple
if "%mirror_choice%"=="3" set PIP_INDEX=-i https://mirrors.aliyun.com/pypi/simple

:: 安装依赖
echo [📦] 安装 onnxruntime, huggingface_hub, flask...
python -m pip install --upgrade pip %PIP_INDEX% -q
python -m pip install onnxruntime huggingface_hub flask pillow numpy requests %PIP_INDEX%
if %errorlevel% neq 0 (
    echo [❌] 依赖安装失败，请检查网络或更换镜像源重试
    pause
    exit /b 1
)
echo [✅] 依赖安装完成

:: 选择下载源
echo.
echo 请选择模型下载源:
echo   [1] HuggingFace 官方 (huggingface.co)
echo   [2] HF-Mirror 国内镜像 (推荐)
set /p dl_choice="请输入选项 (1/2, 默认2): "
if "%dl_choice%"=="" set dl_choice=2
if "%dl_choice%"=="1" set HF_ENDPOINT=
if "%dl_choice%"=="2" set HF_ENDPOINT=https://hf-mirror.com

:: 下载模型文件
echo.
echo ========================================
echo   可用的 WD14 模型:
echo.
echo   [1] ViT v2 (推荐)   — 精度最高，~2GB
echo   [2] ConvNeXt v2      — 速度最快，~1GB
echo   [3] SwinV2 v2       — 均衡型，~1.2GB
echo   [4] MOAT v2         — 新型架构，~1.5GB
echo   [5] ConvNeXtV2      — 升级版，~1.1GB
echo   [6] ViT Large v3    — 最新大模型，~3.5GB
echo   [A] 全部下载
echo ========================================
set /p model_choice="请选择 (1-6/A, 默认1): "
if "%model_choice%"=="" set model_choice=1

set HF_ENV=
if not "%HF_ENDPOINT%"=="" set HF_ENV=HF_ENDPOINT=%HF_ENDPOINT%

if "%model_choice%"=="1" goto download_vit
if "%model_choice%"=="2" goto download_convnext
if "%model_choice%"=="3" goto download_swinv2
if "%model_choice%"=="4" goto download_moat
if "%model_choice%"=="5" goto download_convnextv2
if "%model_choice%"=="6" goto download_vit_large_v3
if "%model_choice%"=="A" goto download_all
goto download_vit

:download_vit
echo [📥] 下载 ViT v2...
%HF_ENV% python -c "from huggingface_hub import snapshot_download; snapshot_download('SmilingWolf/wd-v1-4-vit-tagger-v2', local_dir='models/vit', local_dir_use_symlinks=False)" 2>nul
if %errorlevel% neq 0 echo [⚠] 失败，请重试或手动下载 & echo https://hf-mirror.com/SmilingWolf/wd-v1-4-vit-tagger-v2
goto end_download

:download_convnext
echo [📥] 下载 ConvNeXt v2...
%HF_ENV% python -c "from huggingface_hub import snapshot_download; snapshot_download('SmilingWolf/wd-v1-4-convnext-tagger-v2', local_dir='models/convnext', local_dir_use_symlinks=False)" 2>nul
if %errorlevel% neq 0 echo [⚠] 失败 & echo https://hf-mirror.com/SmilingWolf/wd-v1-4-convnext-tagger-v2
goto end_download

:download_swinv2
echo [📥] 下载 SwinV2 v2...
%HF_ENV% python -c "from huggingface_hub import snapshot_download; snapshot_download('SmilingWolf/wd-v1-4-swinv2-tagger-v2', local_dir='models/swinv2', local_dir_use_symlinks=False)" 2>nul
if %errorlevel% neq 0 echo [⚠] 失败 & echo https://hf-mirror.com/SmilingWolf/wd-v1-4-swinv2-tagger-v2
goto end_download

:download_moat
echo [📥] 下载 MOAT v2...
%HF_ENV% python -c "from huggingface_hub import snapshot_download; snapshot_download('SmilingWolf/wd-v1-4-moat-tagger-v2', local_dir='models/moat', local_dir_use_symlinks=False)" 2>nul
if %errorlevel% neq 0 echo [⚠] 失败 & echo https://hf-mirror.com/SmilingWolf/wd-v1-4-moat-tagger-v2
goto end_download

:download_convnextv2
echo [📥] 下载 ConvNeXtV2...
%HF_ENV% python -c "from huggingface_hub import snapshot_download; snapshot_download('SmilingWolf/wd-v1-4-convnextv2-tagger-v2', local_dir='models/convnextv2', local_dir_use_symlinks=False)" 2>nul
if %errorlevel% neq 0 echo [⚠] 失败 & echo https://hf-mirror.com/SmilingWolf/wd-v1-4-convnextv2-tagger-v2
goto end_download

:download_vit_large_v3
echo [📥] 下载 ViT Large v3...
%HF_ENV% python -c "from huggingface_hub import snapshot_download; snapshot_download('SmilingWolf/wd-vit-large-tagger-v3', local_dir='models/vit_large_v3', local_dir_use_symlinks=False)" 2>nul
if %errorlevel% neq 0 echo [⚠] 失败 & echo https://hf-mirror.com/SmilingWolf/wd-vit-large-tagger-v3
goto end_download

:download_all
echo [📥] 下载全部模型 (约10GB)...
%HF_ENV% python -c "from huggingface_hub import snapshot_download; snapshot_download('SmilingWolf/wd-v1-4-vit-tagger-v2', local_dir='models/vit', local_dir_use_symlinks=False)"
%HF_ENV% python -c "from huggingface_hub import snapshot_download; snapshot_download('SmilingWolf/wd-v1-4-convnext-tagger-v2', local_dir='models/convnext', local_dir_use_symlinks=False)"
%HF_ENV% python -c "from huggingface_hub import snapshot_download; snapshot_download('SmilingWolf/wd-v1-4-swinv2-tagger-v2', local_dir='models/swinv2', local_dir_use_symlinks=False)"
%HF_ENV% python -c "from huggingface_hub import snapshot_download; snapshot_download('SmilingWolf/wd-v1-4-moat-tagger-v2', local_dir='models/moat', local_dir_use_symlinks=False)"
%HF_ENV% python -c "from huggingface_hub import snapshot_download; snapshot_download('SmilingWolf/wd-v1-4-convnextv2-tagger-v2', local_dir='models/convnextv2', local_dir_use_symlinks=False)"
%HF_ENV% python -c "from huggingface_hub import snapshot_download; snapshot_download('SmilingWolf/wd-vit-large-tagger-v3', local_dir='models/vit_large_v3', local_dir_use_symlinks=False)"

:end_download

echo.
echo ========================================
echo   ✅ WD14 安装完成！
echo ========================================
echo.
echo   启动方式：退回主目录，双击 启动WD14.bat
echo   API 地址：http://localhost:7860/wd14/predict
echo.
echo   在工具的「反推页」→ 引擎选择「WD14 标签反推」
echo   填入 http://localhost:7860/wd14/predict
echo   选择已下载的模型即可使用
echo.
echo   国内镜像源：
echo     pip  : 清华 https://pypi.tuna.tsinghua.edu.cn
echo     模型 : https://hf-mirror.com
echo.
pause
