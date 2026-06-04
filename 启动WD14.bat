@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo 🚀 启动 WD14 标签反推 API...
echo.

:: 检查 wd14 文件夹和模型是否已安装
if not exist "wd14\wd14_server.py" (
    echo [❌] 未检测到 WD14 服务文件！
    echo.
    echo 请先运行 wd14 文件夹内的「安装WD14.bat」完成安装。
    echo.
    pause
    exit /b 1
)

:: 检查是否至少有一个模型文件夹
set HAS_MODEL=0
if exist "wd14\models\vit\model.onnx" set HAS_MODEL=1
if exist "wd14\models\convnext\model.onnx" set HAS_MODEL=1
if exist "wd14\models\swinv2\model.onnx" set HAS_MODEL=1
if exist "wd14\models\moat\model.onnx" set HAS_MODEL=1
if exist "wd14\models\convnextv2\model.onnx" set HAS_MODEL=1
if exist "wd14\models\vit_large_v3\model.onnx" set HAS_MODEL=1

if %HAS_MODEL%==0 (
    echo [❌] 未检测到 WD14 模型文件！
    echo.
    echo 请先运行 wd14 文件夹内的「安装WD14.bat」下载模型。
    echo.
    pause
    exit /b 1
)

echo 请选择模型:
if exist "wd14\models\vit\model.onnx"          echo   [1] ViT v2        — 精度最高 (~2GB^)
if exist "wd14\models\convnext\model.onnx"     echo   [2] ConvNeXt v2   — 速度最快 (~1GB^)
if exist "wd14\models\swinv2\model.onnx"       echo   [3] SwinV2 v2     — 平衡型 (~1.2GB^)
if exist "wd14\models\moat\model.onnx"         echo   [4] MOAT v2       — 新型架构 (~1.5GB^)
if exist "wd14\models\convnextv2\model.onnx"   echo   [5] ConvNeXtV2    — 升级版 (~1.1GB^)
if exist "wd14\models\vit_large_v3\model.onnx" echo   [6] ViT Large v3  — 大模型 (~3.5GB^)
echo.
set /p model_choice="请输入选项 (默认1): "
if "%model_choice%"=="" set model_choice=1

if "%model_choice%"=="1" set MODEL=vit
if "%model_choice%"=="2" set MODEL=convnext
if "%model_choice%"=="3" set MODEL=swinv2
if "%model_choice%"=="4" set MODEL=moat
if "%model_choice%"=="5" set MODEL=convnextv2
if "%model_choice%"=="6" set MODEL=vit_large_v3

:: 检查所选模型是否存在
if not exist "wd14\models\%MODEL%\model.onnx" (
    echo [❌] 所选模型未下载！请先运行 wd14\安装WD14.bat 下载模型。
    pause
    exit /b 1
)

echo.
echo 启动模型: %MODEL%
cd wd14
python wd14_server.py %MODEL%
pause
