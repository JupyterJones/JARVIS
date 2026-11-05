#!/usr/bin/env bash
# =============================================================================
# launch_kobold_vulkan.sh - Launch KoboldCpp with Vulkan GPU Acceleration
# Model: Llama-3.2-1B-Instruct-Q4_K_M.gguf
# Port: 5001
# =============================================================================

MODEL_PATH="/home/jack/Desktop/Media_Studio/KOLBOLB/Llama-3.2-1B-Instruct-Q4_K_M.gguf"
KOBOLD_DIR="/home/jack/Desktop/Media_Studio/KOLBOLB"
PORT=5001

echo "🚀 Starting KoboldCpp with Vulkan GPU acceleration..."
echo "Model: $MODEL_PATH"
echo "Port: $PORT"

cd "$KOBOLD_DIR" || exit 1
python3 koboldcpp.py "$MODEL_PATH" \
  --usevulkan \
  --gpulayers 99 \
  --port $PORT \
  --threads 4 \
  --contextsize 4096 \
  --skiplaunch
