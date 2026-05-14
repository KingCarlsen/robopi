# robopi
Description:
Robopi is a fully offline AI robot built on a Raspberry Pi 5. It listens to your voice, processes it locally using a quantized language model, and responds with synthesized speech — all without internet or cloud services. It features an animated face that reacts to its emotional state in real time.
Components:

Raspberry Pi 5 (4GB)
2.4" ILI9341 TFT Display (240x320, SPI)
MAX98357A I2S Amplifier + 3W 4Ω Speaker
Waveshare USB Microphone

Software:

Vosk — offline speech recognition
Ollama + qwen2.5:0.5b — local AI inference
Piper TTS — neural text to speech
Python + Pillow — animated face via direct framebuffer writes
