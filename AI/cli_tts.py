#!/usr/bin/env python3
"""
Headless voice loop for Raspberry Pi:
  STT (faster-whisper + WebRTC VAD) → LLM (OpenRouter) → TTS (Piper CLI)

No GUI. No external TTS module. Single-file script.

Quick start (in your venv):
  pip install faster-whisper webrtcvad sounddevice requests
  export OPENROUTER_API_KEY="<your key>"
  python stt_llm_tts_cli.py --base --voice auto --piper auto

Hotkeys during run:
  • Press ENTER to start/stop a recording (auto-stops on silence)
  • Type ":q" then ENTER to quit
  • Type ":t <text>" to speak typed text directly (skip STT/LLM)

Args:
  --base / --tiny      : choose STT model dir (base.en or tiny.en)
  --compute-type       : int8 (fast on Pi) | int8_float16 | int16 | float32
  --mic INDEX          : ALSA device index for mic (sounddevice index)
  --voice PATH|auto    : Piper voice .onnx (auto = first .onnx in models)
  --piper PATH|auto    : Piper binary (auto = search common locations)
  --model NAME         : OpenRouter model name (default: openai/gpt-4o-mini)
"""
from __future__ import annotations
import os, sys, time, json, wave, struct, math, collections, argparse, shutil, tempfile, subprocess
from typing import Optional

# --- Third-party deps ---
try:
    import sounddevice as sd
    import webrtcvad
    from faster_whisper import WhisperModel
except Exception as e:
    print("Missing deps. Install: pip install faster-whisper webrtcvad sounddevice requests", file=sys.stderr)
    raise

import requests

# --- Paths you can customize (auto-discovered by default) ---
FW_BASE = "/home/robinglory/Desktop/Thesis/STT/faster-whisper/fw-base.en"
FW_TINY = "/home/robinglory/Desktop/Thesis/STT/faster-whisper/fw-tiny.en"
PIPER_MODELS_DIR = "/home/robinglory/Desktop/Thesis/TTS/piper/models"
PIPER_BUILD_DIR  = "/home/robinglory/Desktop/Thesis/TTS/piper/build"

# --- VAD Recorder: writes a 16 kHz mono WAV and returns its path ---
class VADRecorder:
    def __init__(self, sample_rate=16000, frame_ms=30, vad_aggr=3, silence_ms=2000, max_record_s=12,
                 device: Optional[int]=None, energy_margin=2.0, energy_min=2200, energy_max=6000, energy_calib_ms=500):
        self.sample_rate=sample_rate; self.frame_ms=frame_ms; self.vad_aggr=vad_aggr
        self.silence_ms=silence_ms; self.max_record_s=max_record_s; self.device=device
        self.energy_margin=energy_margin; self.energy_min=energy_min; self.energy_max=energy_max; self.energy_calib_ms=energy_calib_ms
    @staticmethod
    def _rms_int16(b: bytes)->float:
        if not b: return 0.0
        n=len(b)//2
        if n<=0: return 0.0
        s=struct.unpack(f"<{n}h", b); acc=0
        for x in s: acc+=x*x
        return math.sqrt(acc/float(n))
    def record(self, out_wav: str) -> str:
        vad = webrtcvad.Vad(self.vad_aggr)
        frame_samp = int(self.sample_rate*(self.frame_ms/1000.0))
        frame_bytes = frame_samp*2
        silence_frames_needed = max(1,int(self.silence_ms/self.frame_ms))
        max_frames = int(self.max_record_s*1000/self.frame_ms)
        calib_frames = max(1,int(self.energy_calib_ms/self.frame_ms))
        ring=collections.deque(); voiced=False; trailing=0; total=0
        energy_thr=None; calib_vals=[]
        print(f"[VAD] start {self.sample_rate}Hz frame={self.frame_ms}ms agg={self.vad_aggr} stop>{self.silence_ms}ms")
        def _cb(indata, frames, time_info, status):
            nonlocal voiced, trailing, total, energy_thr
            buf=indata.tobytes()
            if len(buf)<frame_bytes: return
            ring.append(buf); total+=1
            if energy_thr is None and len(calib_vals)<calib_frames:
                calib_vals.append(self._rms_int16(buf))
                if len(calib_vals)==calib_frames:
                    base=sorted(calib_vals)[len(calib_vals)//2]
                    thr=max(self.energy_min,min(self.energy_max, base*self.energy_margin)); energy_thr=thr
                    print(f"\n[VAD] energy floor≈{int(base)} → thr≈{int(thr)}")
                return
            rms=self._rms_int16(buf)
            try:
                speech = vad.is_speech(buf,self.sample_rate)
            except Exception:
                speech=False
            if energy_thr is not None and rms<energy_thr:
                speech=False
            if speech:
                voiced=True; trailing=0
                print(f"\r[VAD] frames={total} rms={int(rms)} (speech)  ", end="")
            else:
                if voiced: trailing=min(silence_frames_needed,trailing+1)
                print(f"\r[VAD] frames={total} rms={int(rms)} (silence {trailing*self.frame_ms} ms)", end="")
        with sd.InputStream(samplerate=self.sample_rate, channels=1, dtype='int16', device=self.device,
                             blocksize=frame_samp, callback=_cb):
            while True:
                time.sleep(self.frame_ms/1000.0)
                if total>=max_frames:
                    print("\n[VAD] max time reached"); break
                if voiced and trailing>=silence_frames_needed:
                    print("\n[VAD] silence reached — stop"); break
        os.makedirs(os.path.dirname(out_wav), exist_ok=True)
        with wave.open(out_wav,'wb') as w:
            w.setnchannels(1); w.setsampwidth(2); w.setframerate(self.sample_rate)
            while ring: w.writeframes(ring.popleft())
        dur=total*self.frame_ms/1000.0
        print(f"[VAD] wrote {out_wav} (≈{dur:.2f}s)")
        return out_wav

# --- Piper discovery and speaking ---
def which(cmd: str)->Optional[str]:
    return shutil.which(cmd)

def find_piper_binary(user: Optional[str]) -> str:
    if user and user != 'auto':
        return user
    candidates = [
        os.path.join(PIPER_BUILD_DIR, 'piper'),
        '/usr/local/bin/piper', '/usr/bin/piper', which('piper')
    ]
    for c in candidates:
        if c and os.path.isfile(c) and os.access(c, os.X_OK):
            return c
    raise FileNotFoundError("Piper binary not found. Set --piper PATH or install piper to /usr/local/bin.")

def find_piper_voice(user: Optional[str]) -> str:
    if user and user != 'auto':
        if not os.path.isfile(user):
            raise FileNotFoundError(f"Piper voice not found: {user}")
        return user
    # auto: pick first .onnx under PIPER_MODELS_DIR
    for root, _, files in os.walk(PIPER_MODELS_DIR):
        for f in files:
            if f.endswith('.onnx'):
                return os.path.join(root, f)
    raise FileNotFoundError(f"No .onnx voice found under {PIPER_MODELS_DIR}. Download a voice model.")

def piper_say(text: str, piper_bin: str, voice_onnx: str, player: str='aplay') -> float:
    if not text.strip():
        return 0.0
    t0=time.perf_counter()
    with tempfile.NamedTemporaryFile(suffix='.wav', delete=False) as wavf:
        wav_path = wavf.name
    try:
        # Feed text via stdin to piper (more compatible than -t across versions)
        proc = subprocess.Popen([piper_bin, '-m', voice_onnx, '-f', wav_path], stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        stdout, stderr = proc.communicate(text, timeout=120)
        if proc.returncode != 0:
            raise RuntimeError(f"piper failed: {stderr}\n{stdout}")
        # Play
        play_bin = which(player) or which('ffplay')
        if play_bin and os.path.basename(play_bin) == 'ffplay':
            subprocess.run([play_bin, '-nodisp', '-autoexit', wav_path], check=True)
        elif play_bin:
            subprocess.run([play_bin, wav_path], check=True)
        else:
            raise RuntimeError("No audio player found (tried 'aplay' and 'ffplay')")
    finally:
        try: os.remove(wav_path)
        except Exception: pass
    return time.perf_counter()-t0

# --- LLM via OpenRouter ---
class OpenRouter:
    def __init__(self, model: str):
        self.model = model
        self.api_key = (os.environ.get('OPENROUTER_API_KEY') or '').strip()
        if not self.api_key:
            # Optional compatibility: try reading keys.json if present
            km_path = "/home/robinglory/Desktop/Thesis/GUI/keys.json"
            try:
                with open(km_path, 'r') as f:
                    data = json.load(f)
                prof = data.get('current_profile') or (data.get('profiles') or [{}])[0].get('label')
                for p in data.get('profiles', []):
                    if p.get('label') == prof:
                        self.api_key = p.get('GPT_OSS_API_KEY') or p.get('MISTRAL_API_KEY') or p.get('QWEN_API_KEY') or ''
                        break
            except Exception:
                pass
        if not self.api_key:
            raise RuntimeError("No OpenRouter API key. Set OPENROUTER_API_KEY or provide GUI/keys.json.")
    def chat(self, user_text: str) -> str:
        url = "https://openrouter.ai/api/v1/chat/completions"
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "HTTP-Referer": "http://localhost/",
            "X-Title": "AI Voice Tester (headless)",
            "Content-Type": "application/json",
        }
        payload = {
            "model": self.model,
            "max_tokens": 256,
            "temperature": 0.7,
            "messages": [
                {"role":"system","content":"You are Lingo, a friendly English tutor in a robot head. Keep answers under 2 sentences and end with a short question."},
                {"role":"user","content": user_text},
            ]
        }
        r = requests.post(url, headers=headers, json=payload, timeout=60)
        r.raise_for_status()
        return r.json()["choices"][0]["message"]["content"].strip()

# --- STT wrapper ---
class FasterWhisperSTT:
    def __init__(self, model_dir: str, compute_type: str):
        if not os.path.isdir(model_dir):
            raise FileNotFoundError(f"STT model dir not found: {model_dir}")
        os.environ.setdefault("OMP_NUM_THREADS","4")
        t0=time.perf_counter()
        self.model = WhisperModel(model_dir, device="cpu", compute_type=compute_type)
        print(f"[STT] loaded {model_dir} in {time.perf_counter()-t0:.2f}s")
    def transcribe(self, wav_path: str) -> tuple[str, float, float]:
        t0 = time.perf_counter()
        segments, info = self.model.transcribe(wav_path, language="en", beam_size=3, vad_filter=True,
                                               vad_parameters=dict(min_silence_duration_ms=400))
        txt = "".join(s.text for s in segments).strip()
        return txt, info.duration, time.perf_counter()-t0

# --- Main loop ---
def main():
    pa = argparse.ArgumentParser(description="Headless STT→LLM→Piper loop")
    mgroup = pa.add_mutually_exclusive_group()
    mgroup.add_argument('--base', action='store_true', help='use base.en model (default)')
    mgroup.add_argument('--tiny', action='store_true', help='use tiny.en model')
    pa.add_argument('--compute-type', default='int8', help='int8|int8_float16|int16|float32 (default: int8)')
    pa.add_argument('--mic', type=int, default=None, help='sounddevice input index (use python -c "import sounddevice as sd;print(sd.query_devices())")')
    pa.add_argument('--voice', default='auto', help='path to Piper voice .onnx or "auto"')
    pa.add_argument('--piper', default='auto', help='path to Piper binary or "auto"')
    pa.add_argument('--model', default='openai/gpt-4o-mini', help='OpenRouter model id')
    args = pa.parse_args()

    stt_model_dir = FW_BASE if (args.base or not args.tiny) else FW_TINY
    stt = FasterWhisperSTT(stt_model_dir, args.compute_type)
    piper_bin = find_piper_binary(args.piper)
    voice_onnx = find_piper_voice(args.voice)
    llm = OpenRouter(model=args.model)

    print("\n=== Headless Voice Loop ===")
    print("Press ENTER to record, ':q' + ENTER to quit, or ':t your text' to TTS directly.\n")

    rec = VADRecorder(sample_rate=16000, frame_ms=30, vad_aggr=3, silence_ms=2000, max_record_s=12,
                      device=args.mic, energy_margin=2.0, energy_min=2200, energy_max=6000)

    while True:
        try:
            cmd = input('> ').strip()
        except (EOFError, KeyboardInterrupt):
            print() ; break
        if cmd == '':
            # Speak cycle
            wav_path = os.path.join(tempfile.gettempdir(), 'fw_dialog.wav')
            rec_path = rec.record(wav_path)
            print('[ASR] transcribing…')
            text, audio_len, asr_time = stt.transcribe(rec_path)
            if not text:
                print('[ASR] (no speech detected)')
                continue
            print(f"[ASR] text: {text}")
            print('[LLM] thinking…')
            t0=time.perf_counter();
            try:
                reply = llm.chat(text)
            except Exception as e:
                print(f"[LLM] error: {e}")
                continue
            llm_time = time.perf_counter()-t0
            print(f"[LLM] reply: {reply}")
            print('[TTS] speaking…')
            try:
                tts_time = piper_say(reply, piper_bin, voice_onnx)
            except Exception as e:
                print(f"[TTS] error: {e}")
                continue
            print(f"[TIMINGS] audio≈{audio_len:.2f}s  asr={asr_time:.2f}s  llm={llm_time:.2f}s  tts={tts_time:.2f}s  total={audio_len+asr_time+llm_time+tts_time:.2f}s")
        elif cmd.startswith(':q'):
            break
        elif cmd.startswith(':t'):
            text = cmd[2:].strip()
            if not text:
                print('Usage: :t your text here')
                continue
            try:
                piper_say(text, piper_bin, voice_onnx)
            except Exception as e:
                print(f"[TTS] error: {e}")
        else:
            # Treat any other input as a user message to LLM
            print('[LLM] thinking…')
            t0=time.perf_counter();
            try:
                reply = llm.chat(cmd)
            except Exception as e:
                print(f"[LLM] error: {e}")
                continue
            llm_time = time.perf_counter()-t0
            print(f"[LLM] reply: {reply}")
            try:
                piper_say(reply, piper_bin, voice_onnx)
            except Exception as e:
                print(f"[TTS] error: {e}")

if __name__ == '__main__':
    main()
