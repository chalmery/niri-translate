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
cmake -S "$BUILD_DIR/llama.cpp" -B "$BUILD_DIR/llama.cpp/build" -G Ninja \
  -DCMAKE_BUILD_TYPE=Release -DCMAKE_BUILD_RPATH_USE_ORIGIN=ON -DGGML_CUDA=OFF -DGGML_VULKAN=OFF \
  -DLLAMA_CURL=OFF -DLLAMA_BUILD_TESTS=OFF -DLLAMA_BUILD_SERVER=ON
cmake --build "$BUILD_DIR/llama.cpp/build" --target llama-server -j "${BUILD_JOBS:-8}"
mkdir -p "$DATA_DIR/runtime/bin"
cp -a "$BUILD_DIR/llama.cpp/build/bin/llama-server" "$BUILD_DIR/llama.cpp/build/bin/"*.so* "$DATA_DIR/runtime/bin/"
cp "$ROOT/runtime.lock.json" "$DATA_DIR/runtime/"
cp "$BUILD_DIR/llama.cpp/LICENSE" "$DATA_DIR/runtime/LICENSE.llama.cpp"
echo "CPU 运行时已安装：$DATA_DIR/runtime/bin/llama-server"
