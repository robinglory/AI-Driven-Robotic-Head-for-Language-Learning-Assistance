import wave
from piper import PiperVoice

voice = PiperVoice.load("/home/robinglory/Desktop/Thesis/TTS/piper/models/en_US-hfc_female-medium.onnx")
with wave.open("test.wav", "wb") as wav_file:
    voice.synthesize_wav(r"Hello, Yan Naing Kyaw Tint! It's nice to meet you! 😊 I'm here to help you learn English. I saw that we're going to talk about why people collect things - like stamps, coins, or toys. Can you tell me - do you collect anything? What would you like to learn today?", wav_file)
