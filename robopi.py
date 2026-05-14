#!/usr/bin/env python3
import ollama
import subprocess
import time
import datetime
from PIL import Image, ImageDraw
import struct
import random
import threading
import os
import vosk
import wave
import json
import math

# --- CONFIG ---
FB_DEVICE = "/dev/fb0"
WIDTH = 240
HEIGHT = 320
DISPLAY_OFFSET_X = 20
SPEAKER_DEVICE = "plughw:2,0"
MIC_DEVICE = "plughw:3,0"

# --- MOOD BACKGROUND COLORS ---
MOOD_COLORS = {
    "idle":      (20,  40,  80),
    "listening": (20,  80,  40),
    "thinking":  (50,  20,  80),
    "eureka":    (80,  70,  10),
    "speaking":  (80,  35,  10),
}

# --- GLOBAL STATE ---
current_state = "idle"
current_pupil_x = 0
current_pupil_y = 0
eye_openness = 1.0
animation_frame = 0
conversation_history = []

# --- OPEN FRAMEBUFFER ---
try:
    fb_handle = open(FB_DEVICE, 'wb')
except Exception as e:
    print(f"Error opening framebuffer: {e}")
    exit(1)

# --- LOAD VOSK MODEL ONCE AT STARTUP ---
vosk.SetLogLevel(-1)
print("Loading Vosk model...")
vosk_model = vosk.Model("/home/robopi/robot/vosk-model")
print("Vosk model loaded!")

def display_on_fb(image):
    pixels = []
    for r, g, b in image.getdata():
        rgb565 = ((b & 0xF8) << 8) | ((g & 0xFC) << 3) | (r >> 3)
        pixels.append(struct.pack('H', rgb565))
    fb_handle.seek(0)
    fb_handle.write(b''.join(pixels))
    fb_handle.flush()

def draw_mouth(draw, cx, my, state, frame):
    if state == "idle":
        draw.arc([cx - 40, my - 20, cx + 40, my + 20],
                 start=0, end=180, fill=(255, 255, 255), width=5)
        draw.ellipse([cx - 43, my - 4, cx - 35, my + 4], fill=(255, 255, 255))
        draw.ellipse([cx + 35, my - 4, cx + 43, my + 4], fill=(255, 255, 255))
    elif state == "listening":
        draw.ellipse([cx - 14, my - 14, cx + 14, my + 14],
                     fill=(80, 30, 30), outline=(255, 255, 255), width=3)
    elif state == "thinking":
        draw.arc([cx - 28, my - 10, cx + 28, my + 10],
                 start=0, end=180, fill=(255, 255, 255), width=3)
    elif state == "speaking":
        phase = (frame // 4) % 3
        if phase == 0:
            draw.ellipse([cx - 22, my - 16, cx + 22, my + 16],
                         fill=(80, 20, 20), outline=(255, 255, 255), width=3)
        elif phase == 1:
            draw.ellipse([cx - 14, my - 8, cx + 14, my + 8],
                         fill=(80, 20, 20), outline=(255, 255, 255), width=2)
        else:
            draw.line([cx - 20, my, cx + 20, my], fill=(255, 255, 255), width=4)
    elif state == "eureka":
        draw.arc([cx - 40, my - 25, cx + 40, my + 15],
                 start=0, end=180, fill=(255, 255, 255), width=5)

def draw_thought_bubble(draw, cx, frame):
    bx = cx + 55
    by = 55
    pulse = frame / 8
    draw.ellipse([bx - 22, by - 14, bx + 22, by + 14],
                 outline=(200, 200, 220), fill=(60, 40, 90), width=2)
    draw.ellipse([bx - 12, by + 12, bx - 4, by + 20],
                 outline=(200, 200, 220), fill=(60, 40, 90), width=1)
    draw.ellipse([bx - 6, by + 20, bx, by + 26], fill=(60, 40, 90))
    for i in range(3):
        lit = (int(pulse) + i) % 3 == 0
        color = (255, 255, 255) if lit else (120, 100, 150)
        dx = bx - 11 + i * 11
        draw.ellipse([dx - 3, by - 3, dx + 3, by + 3], fill=color)

def draw_lightbulb(draw, cx, frame):
    lx = cx + 55
    ly = 45
    glow = abs((frame % 20) - 10) / 10
    g = int(12 + 10 * glow)
    draw.ellipse([lx - g, ly - g, lx + g, ly + g], fill=(255, 240, 80))
    draw.ellipse([lx - 9, ly - 13, lx + 9, ly + 5],
                 fill=(255, 255, 220), outline=(220, 200, 0), width=2)
    draw.rectangle([lx - 5, ly + 5, lx + 5, ly + 11], fill=(160, 160, 160))
    for angle_deg in [0, 45, 90, 135, 180, 225, 270, 315]:
        a = math.radians(angle_deg)
        x1 = lx + int(11 * math.cos(a))
        y1 = ly + int(11 * math.sin(a))
        x2 = lx + int(17 * math.cos(a))
        y2 = ly + int(17 * math.sin(a))
        draw.line([x1, y1, x2, y2], fill=(255, 230, 50), width=2)

def draw_sound_waves(draw, cx, cy, frame):
    wx = cx + 60
    phase = frame / 6
    for i in range(3):
        r = 8 + i * 8
        alpha = abs((phase + i) % 3 - 1.5) / 1.5
        color_val = int(80 + 120 * alpha)
        draw.arc([wx - r, cy - r, wx + r, cy + r],
                 start=300, end=60, fill=(color_val, 255, color_val), width=2)

def draw_face(state, frame, pupil_x, pupil_y, openness):
    bg = MOOD_COLORS.get(state, (20, 40, 80))
    image = Image.new('RGB', (WIDTH, HEIGHT), bg)
    draw = ImageDraw.Draw(image)

    FACE_WIDTH = WIDTH - DISPLAY_OFFSET_X
    cx = DISPLAY_OFFSET_X + (FACE_WIDTH // 2)
    cy = HEIGHT // 2 - 40

    # Cheeks
    cheek_y = cy + 22
    cheek_w = 28
    cheek_h = 14
    draw.ellipse([cx - 68, cheek_y - cheek_h, cx - 68 + cheek_w*2, cheek_y + cheek_h],
                 fill=(180, 60, 90))
    draw.ellipse([cx + 12, cheek_y - cheek_h, cx + 12 + cheek_w*2, cheek_y + cheek_h],
                 fill=(180, 60, 90))

    # Eyes
    eye_y = cy - 20
    left_eye_x  = cx - 30
    right_eye_x = cx + 30
    eye_rx = 22
    eye_ry = 22

    if openness > 0.1:
        ery = max(2, int(eye_ry * openness))
        draw.ellipse([left_eye_x  - eye_rx, eye_y - ery,
                      left_eye_x  + eye_rx, eye_y + ery], fill=(255, 255, 255))
        draw.ellipse([right_eye_x - eye_rx, eye_y - ery,
                      right_eye_x + eye_rx, eye_y + ery], fill=(255, 255, 255))

        if openness > 0.4:
            pupil_r = int(10 * openness)
            px = int(pupil_x * 0.5)
            py = int(pupil_y * openness * 0.5)

            draw.ellipse([left_eye_x  - pupil_r + px, eye_y - pupil_r + py,
                          left_eye_x  + pupil_r + px, eye_y + pupil_r + py], fill=(30, 30, 30))
            draw.ellipse([right_eye_x - pupil_r + px, eye_y - pupil_r + py,
                          right_eye_x + pupil_r + px, eye_y + pupil_r + py], fill=(30, 30, 30))

            shine_r = max(2, int(4 * openness))
            draw.ellipse([left_eye_x  + 6 + px, eye_y - 9 + py,
                          left_eye_x  + 6 + shine_r + px, eye_y - 9 + shine_r + py],
                         fill=(255, 255, 255))
            draw.ellipse([right_eye_x + 6 + px, eye_y - 9 + py,
                          right_eye_x + 6 + shine_r + px, eye_y - 9 + shine_r + py],
                         fill=(255, 255, 255))
    else:
        draw.line([left_eye_x  - eye_rx, eye_y, left_eye_x  + eye_rx, eye_y],
                  fill=(255, 255, 255), width=3)
        draw.line([right_eye_x - eye_rx, eye_y, right_eye_x + eye_rx, eye_y],
                  fill=(255, 255, 255), width=3)

    # Mouth
    mouth_y = cy + 48
    draw_mouth(draw, cx, mouth_y, state, frame)

    # Extras
    if state == "thinking":
        draw_thought_bubble(draw, cx, frame)
    if state == "eureka":
        draw_lightbulb(draw, cx, frame)
    if state == "listening":
        draw_sound_waves(draw, cx, cy, frame)

    return image

def update_display():
    global animation_frame
    while True:
        state = current_state
        px    = current_pupil_x
        py    = current_pupil_y
        opn   = eye_openness
        frame = animation_frame

        if state == "thinking":
            px, py = 5, -4
        elif state == "eureka":
            px, py = 0, -6
        elif state == "listening":
            px, py = 0, 0

        image = draw_face(state, frame, px, py, opn)
        display_on_fb(image)
        animation_frame += 1
        time.sleep(0.033)

def blink_logic():
    global eye_openness
    while True:
        time.sleep(random.uniform(3, 6))
        if current_state in ["idle", "listening", "thinking"]:
            for o in [0.6, 0.1, 0.0, 0.1, 0.6, 1.0]:
                eye_openness = o
                time.sleep(0.04)

def pupil_wander():
    global current_pupil_x, current_pupil_y
    while True:
        if current_state == "idle":
            current_pupil_x = random.randint(-6, 6)
            current_pupil_y = random.randint(-4, 4)
        time.sleep(random.uniform(1.5, 3.5))

def text_to_speech(text):
    try:
        current_state_backup = current_state
        piper_cmd = [
            "/home/robopi/robot/piper/piper",
            "--model", "/home/robopi/robot/piper/en_US-lessac-medium.onnx",
            "--output_file", "/home/robopi/robot/piper/response.wav"
        ]
        p = subprocess.Popen(piper_cmd, stdin=subprocess.PIPE,
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        p.communicate(input=text.encode())
        subprocess.run(["sox", "/home/robopi/robot/piper/response.wav",
                        "/home/robopi/robot/piper/response_loud.wav", "vol", "5"],
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        subprocess.run(["aplay", "-D", SPEAKER_DEVICE,
                        "/home/robopi/robot/piper/response_loud.wav"],
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except Exception as e:
        print(f"TTS Error: {e}")

def listen_for_voice():
    global current_state
    temp_file = "/home/robopi/robot/temp_recording.wav"
    try:
        current_state = "listening"
        print("[Listening for 4 seconds...]")
        subprocess.run([
            "arecord", "-D", MIC_DEVICE,
            "-f", "S16_LE", "-r", "16000", "-c", "1", "-d", "4",
            temp_file
        ], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True)

        print("[Processing...]")
        wf = wave.open(temp_file, "rb")

        if wf.getnchannels() != 1 or wf.getsampwidth() != 2 or wf.getframerate() != 16000:
            print("Audio format mismatch!")
            wf.close()
            return None

        # Reuse the globally loaded model
        rec = vosk.KaldiRecognizer(vosk_model, 16000)
        full_text = []

        while True:
            data = wf.readframes(4000)
            if len(data) == 0:
                break
            if rec.AcceptWaveform(data):
                partial = json.loads(rec.Result())
                text = partial.get("text", "").strip()
                if text:
                    full_text.append(text)

        final = json.loads(rec.FinalResult())
        text = final.get("text", "").strip()
        if text:
            full_text.append(text)

        wf.close()
        try:
            os.unlink(temp_file)
        except:
            pass

        transcription = " ".join(full_text).strip()
        print(f"[Heard]: '{transcription}'")
        return transcription if transcription else None

    except Exception as e:
        print(f"STT Error: {e}")
        import traceback
        traceback.print_exc()
        try:
            os.unlink(temp_file)
        except:
            pass
        return None

def chat_logic(user_input):
    global current_state, conversation_history
    current_state = "thinking"

    now = datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=5, minutes=30)))
    current_time = now.strftime("%I:%M %p")
    current_date = now.strftime("%A, %B %d %Y")

    SYSTEM_PROMPT = f"""You are RoboPi, a friendly desk robot assistant.

FACTS YOU MUST USE (never override these):
- Current time is EXACTLY {current_time} IST
- Today is {current_date}

Rules:
- Keep ALL answers to 1-2 short sentences maximum
- NEVER use emojis, emoticons, or symbols like :) or <3
- NEVER use markdown formatting like ** or * or _
- NEVER make up your own time or weather - always use the facts above
- When asked about weather, answer in exactly 1 sentence using only the facts provided
- Be helpful and cheerful but concise
- Speak naturally like a helpful friend"""

    try:
        conversation_history.append({'role': 'user', 'content': user_input})
        response = ollama.chat(
            model='qwen2.5:0.5b',
            messages=[
                {'role': 'system', 'content': SYSTEM_PROMPT},
                *conversation_history
            ]
        )
        ans = response['message']['content']
        conversation_history.append({'role': 'assistant', 'content': ans})
        current_state = "eureka"
        time.sleep(0.8)
        return ans
    except Exception as e:
        current_state = "idle"
        return "I had a brain glitch. Try again?"

# --- STARTUP ---
threading.Thread(target=update_display, daemon=True).start()
threading.Thread(target=blink_logic,    daemon=True).start()
threading.Thread(target=pupil_wander,   daemon=True).start()

time.sleep(2)

print("=" * 60)
print("  RoboPi Voice Assistant  |  Auto Listen Mode!")
print("=" * 60)

current_state = "speaking"
text_to_speech("Hi! I am RoboPi. Talk to me anytime!")

current_state = "idle"

# --- MAIN LOOP - Auto listen, no keyboard needed ---
while True:
    current_state = "idle"
    time.sleep(3)

    transcription = listen_for_voice()

    if transcription:
        print(f"You said: {transcription}")
        reply = chat_logic(transcription)
        print(f"RoboPi: {reply}")
        current_state = "speaking"
        text_to_speech(reply)
    else:
        print("[Nothing heard, going back to idle]")
        current_state = "idle"
