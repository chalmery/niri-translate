#!/usr/bin/env bash
set -euo pipefail
ROOT=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
DATA_DIR="${XDG_DATA_HOME:-$HOME/.local/share}/niri-translate"
BUILD_DIR="$ROOT/.build"
COMMIT=d2e54583c7452353eb35d40431281f6ee984332f
SHA256=8aeb94872f97ddc9c80bca3824d95aba00bdb17d1d28813db22150fb6caf6d15
mkdir -p "$BUILD_DIR"
if [[ ! -f "$BUILD_DIR/llama.cpp/.source-commit" ]] || [[ $(cat "$BUILD_DIR/llama.cpp/.source-commit") != "$COMMIT" ]]; then
  if [[ ! -f "$BUILD_DIR/llama.tar.gz" ]] || ! echo "$SHA256  $BUILD_DIR/llama.tar.gz" | sha256sum --check --status; then
    curl -fL --retry 3 "https://codeload.github.com/ggml-org/llama.cpp/tar.gz/$COMMIT" -o "$BUILD_DIR/llama.tar.gz"
  fi
  echo "$SHA256  $BUILD_DIR/llama.tar.gz" | sha256sum --check --status
  rm -rf "$BUILD_DIR/llama.cpp"
  mkdir -p "$BUILD_DIR/llama.cpp"
  tar -xzf "$BUILD_DIR/llama.tar.gz" --strip-components=1 -C "$BUILD_DIR/llama.cpp"
  echo "$COMMIT" > "$BUILD_DIR/llama.cpp/.source-commit"
fi
# Vulkan supports AMD, Intel and NVIDIA; dynamic backends preserve CPU-only use.
BACKEND=${NIRI_TRANSLATE_BACKEND:-auto}
case "$BACKEND" in auto|cpu|vulkan) ;; *) echo "后端必须为 auto、cpu 或 vulkan"; exit 2 ;; esac
VULKAN=OFF
if [[ "$BACKEND" == vulkan ]] || { [[ "$BACKEND" == auto ]] && command -v glslc >/dev/null && pkg-config --exists vulkan && [[ -f /usr/include/spirv/unified1/spirv.hpp ]]; }; then
  VULKAN=ON
fi
RUNTIME_BUILD="$BUILD_DIR/llama.cpp/build-${VULKAN,,}"
cmake -S "$BUILD_DIR/llama.cpp" -B "$RUNTIME_BUILD" -G Ninja \
  -DCMAKE_BUILD_TYPE=Release -DCMAKE_BUILD_RPATH_USE_ORIGIN=ON -DGGML_CUDA=OFF -DGGML_VULKAN="$VULKAN" -DGGML_BACKEND_DL=ON -DGGML_NATIVE=OFF -DGGML_CPU_ALL_VARIANTS=ON \
  -DLLAMA_CURL=OFF -DLLAMA_BUILD_TESTS=OFF -DLLAMA_BUILD_SERVER=ON
cmake --build "$RUNTIME_BUILD" --target llama-server -j "${BUILD_JOBS:-8}"
mkdir -p "$DATA_DIR/runtime"
# Replace files by rename: never truncate libraries mapped by a running server.
INSTALL_STAGE=$(mktemp -d "$DATA_DIR/runtime/.install-XXXXXX")
trap 'rm -rf "$INSTALL_STAGE"' EXIT
cp -a "$RUNTIME_BUILD/bin/llama-server" "$RUNTIME_BUILD/bin/"*.so* "$INSTALL_STAGE/"
mkdir -p "$DATA_DIR/runtime/bin"
for artifact in "$INSTALL_STAGE/"*; do mv -f "$artifact" "$DATA_DIR/runtime/bin/"; done
printf '{"vulkan": "%s"}\n' "$VULKAN" > "$DATA_DIR/runtime/build-info.json"
cp "$ROOT/runtime.lock.json" "$DATA_DIR/runtime/"
cp "$BUILD_DIR/llama.cpp/LICENSE" "$DATA_DIR/runtime/LICENSE.llama.cpp"
echo "运行时已安装（Vulkan=$VULKAN；CPU 可用）：$DATA_DIR/runtime/bin/llama-server"
