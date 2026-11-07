#!/bin/bash
# Reproduce the image-only OpenCV dependency used by the public Apple Silicon app.
# Run inside a Python 3.12 build environment with Xcode command-line tools.
set -euo pipefail
if [[ "$(uname -s)" != Darwin ]]; then echo 'This recipe targets macOS.'; exit 1; fi
PYTHON="${CUTOUT_BUILD_PYTHON:-python3.12}"
WORK="${CUTOUT_OPENCV_WORK:-$HOME/Library/Caches/CutoutPrepOpenCV-5.0.0.93}"
mkdir -p "$WORK/wheels" "$WORK/tmp"
export TMPDIR="$WORK/tmp"
"$PYTHON" -m pip install 'scikit-build==0.19.1' 'cmake==4.4.4' 'ninja==1.13.2' 'wheel==0.48.0' 'setuptools==84.2.1' 'numpy==2.5.4'
export ENABLE_HEADLESS=1 ENABLE_CONTRIB=0 CMAKE_BUILD_PARALLEL_LEVEL=4
export MACOSX_DEPLOYMENT_TARGET=13.0
export CMAKE_ARGS='-DWITH_FFMPEG=OFF -DWITH_GSTREAMER=OFF -DWITH_AVFOUNDATION=OFF -DWITH_OPENCL=OFF -DWITH_IPP=OFF -DWITH_OPENEXR=OFF -DWITH_WEBP=OFF -DWITH_OPENJPEG=OFF -DWITH_JASPER=OFF -DWITH_TIFF=OFF -DBUILD_ZLIB=ON -DBUILD_PNG=ON -DBUILD_JPEG=ON -DBUILD_TESTS=OFF -DBUILD_PERF_TESTS=OFF -DBUILD_EXAMPLES=OFF -DBUILD_opencv_videoio=OFF -DBUILD_opencv_highgui=OFF -DBUILD_opencv_gapi=OFF -DBUILD_LIST=core,imgproc,imgcodecs,features,flann,calib,geometry,photo,python3'
SOURCE="${CUTOUT_OPENCV_SOURCE:-opencv-python-headless==5.0.0.93}"
if [[ ! -f "$SOURCE" ]]; then
  mkdir -p "$WORK/downloads"
  "$PYTHON" -m pip download --no-deps --no-binary=:all: --no-build-isolation --dest "$WORK/downloads" "$SOURCE"
  SOURCE="$(find "$WORK/downloads" -maxdepth 1 -name 'opencv_python_headless-5.0.0.93.tar.gz' -print -quit)"
fi
SOURCE_DIR="$("$PYTHON" - "$SOURCE" "$WORK/source" <<'PY'
import hashlib,sys,tarfile
from pathlib import Path
archive=Path(sys.argv[1]);dest=Path(sys.argv[2]);root=dest/'opencv_python_headless-5.0.0.93'
with archive.open('rb') as f:
    assert hashlib.file_digest(f,'sha256').hexdigest()=='b82f9831daab90b725c7c1ee1b36cb5732c367096ac76d119e64e14eb70d5f3c','Unexpected OpenCV source archive'
if not (root/'setup.py').is_file():
    dest.mkdir(parents=True,exist_ok=True)
    with tarfile.open(archive) as t:t.extractall(dest,filter='data')
assert (root/'setup.py').is_file()
print(root)
PY
)"
"$PYTHON" -m pip wheel --no-build-isolation --no-deps --no-binary=opencv-python-headless --wheel-dir "$WORK/wheels" "$SOURCE_DIR"
"$PYTHON" "$(dirname "$0")/sanitize_opencv_wheel.py" --wheel "$WORK"/wheels/opencv_python_headless-5.0.0.93-*.whl --output "$WORK/public-wheels"
"$PYTHON" -m pip install --no-deps --force-reinstall "$WORK"/public-wheels/opencv_python_headless-5.0.0.93-*.whl
"$PYTHON" -c 'import cv2; info=cv2.getBuildInformation(); print(cv2.__version__); assert "FFMPEG:                      YES" not in info; assert hasattr(cv2,"SIFT_create"); assert hasattr(cv2,"grabCut"); print("Image-only OpenCV installed")'
