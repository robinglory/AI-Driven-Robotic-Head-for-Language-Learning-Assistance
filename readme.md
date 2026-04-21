# AI Driven Robotic Head for Language Learning Assistance - Technical Documentation

## Table of Contents
1. [Overview](#overview)  
2. [Hardware Integration](#hardware-integration)  
3. [Software Components](#software-components)
4. [Demo Videos](#demo-videos)
5. [The UI Design](#guidesign)  
6. [System Architecture](#system-architecture)  
7. [Technical Specifications](#technical-specifications)  
8. [Installation Guide](#installation-guide)  
9. [Configuration](#configuration)  
10. [Usage](#usage)  
11. [API & AI Integration](#api--ai-integration)  
12. [File Structure](#file-structure)  
13. [Dependencies](#dependencies)  
14. [Testing & Results](#testing--results)  
15. [Known Issues](#known-issues)  
16. [Future Enhancements](#future-enhancements)
17. [Related Work & Global Context](#related-work-with-global-context)

---

## Overview
### Experimental Setup
1. **Final Setup Interface**  
   *Lingo Laguage Learning Assistance*  
   ![Ling](GUI/GUI_IMG/IMG_20250911_204801.png)

The **AI Driven Robotic Head for Language Learning Assistance** (codenamed **Lingo**) is a combined **software + hardware platform** that delivers personalized English tutoring through natural conversation, interactive lessons, and human-like robotic expressions.  

The system runs on **Raspberry Pi 4** and integrates:  
- **GUI Application (Tkinter)** for lessons, progress tracking, and digital textbooks.  
- **AI Pipeline** with speech recognition (STT), large language models (LLM), and speech synthesis (TTS).  
- **Robotic Head** powered by Arduino + PCA9685 servo controller for eyes, mouth, and neck gestures.  

**Key Achievements & Features:**
- Fully functional **GUI** with login, student dashboard, grammar, vocabulary, and reading lessons.  
- **Voice interaction loop**: STT (Faster-Whisper) → LLM (OpenRouter) → TTS (Piper).  
- **Persistent Piper engine** for streaming, low-latency text-to-speech.  
- **TinyDB database** for storing students and lesson progress.  
- **Face recognition login** (LBPH + Haar cascade).  
- **Arduino-controlled robotic head** with lifelike gestures (listen, think, talk).  
- **Servo limits & safety controls** for mouth, eyes, and neck.  
- **Academic-style PDF export** for completed lessons.  

---
## Hardware Integration

The robotic head is driven by **Arduino UNO + PCA9685** servo controller with external 12V → 6V regulated power.  

**Servo Ranges (degrees):**  
- Mouth: 25° → 60°  
- Neck: 45° → 135°  
- Eyes Left/Right: 50° → 120°  
- Eyes Up/Down: 130° → 170°  

**Features:**  
- Event-driven serial commands (`listen`, `think`, `talk`, `stop`, etc.).  
- Smooth return to **idle pose** after each gesture.  
- Human-like **thinking**, **listening**, and **talking** animations.  
- Integration with GUI stages (pause tracking during “think”/“talk”).  

---

## Software Components

- **main.py** – Tkinter main app with login, dashboard, and lesson screens.  
- **lesson.py** – Lesson mode with stricter system prompts and TTS-first pipeline.  
- **gui_serial.py** – Serial bridge for controlling Arduino gestures.  
- **FaceTracker** – Controls robot eye tracking during idle states.  
- **VADRecorder** – WebRTC-based voice activity detection for clean STT.  
- **LLMHandler** – Multi-provider LLM calls with failover & streaming hedge.  
- **PiperEngine** – Persistent streaming TTS with auto sample-rate handling.  

---

## GUIDesign

### Interface Overview
The application features a **responsive Tkinter interface** with enhanced styles for readability and academic presentation.

### Main Components:
1. **Main Chat Interface**  
   *Entry point for AI assistant chat*  
   ![Main Page](Photos/20250912_15h25m14s_grim.png)

2. **Login Screen**  
   *Student authentication and profile loading*  
   ![Login](GUI/GUI_IMG/log_in.png)

3. **Student Dashboard**  
   *Lesson selection, progress tracking, and textbook access*  
   ![Dashboard](GUI/GUI_IMG/student_dashboard.png)

4. **Grammar Section**  
   *Grammar Section where the user can learns the Grammar*  
   ![Grammar](GUI/GUI_IMG/grammar_lesson.png)

5. **Reading Section**  
   *Lingo will help you learns lots of Intermediate and Pre-intermediate level readings.*  
   ![Reading](GUI/GUI_IMG/reading_lesson.png)

6. **Vocabulary Sections**  
   *Our Lingo will teach ther user lots of essential vocabs.*  
   ![Vocabulary](GUI/GUI_IMG/vocab_lesson.png)

---
## Demo Videos

See **Lingo – the AI-Driven Robotic Head for Language Learning Assistance** in action! Start with our high-level project overviews, then explore the specific testing and interaction results.

### 🌟 Project Overviews

| Meet Lingo: The AI-Driven Robot Tutor (Short Overview) | Deep Dive: Building Lingo (Detailed Breakdown) |
| :---: | :---: |
| [![Short Version](https://img.youtube.com/vi/bE_uEdicx6Y/0.jpg)](https://youtu.be/bE_uEdicx6Y) | [![Deep Dive Version](https://img.youtube.com/vi/27ZzGbhwjw0/0.jpg)](https://youtu.be/27ZzGbhwjw0) |

---

### 🔬 Testing & Interaction Results

| ▶️ Main Demo – General Teacher Mode | 👤 Face Recognition – Personalized Login | 📚 Personalized Teacher Mode |
| :---: | :---: | :---: |
| [![General Teacher Mode](https://img.youtube.com/vi/7IBsDtvbOOo/0.jpg)](https://youtu.be/7IBsDtvbOOo) | [![Personalized Login](https://img.youtube.com/vi/A4hE7prCXok/0.jpg)](https://youtu.be/A4hE7prCXok) | [![Lesson Enforcement](https://img.youtube.com/vi/aG6oOYA1lXU/0.jpg)](https://youtu.be/aG6oOYA1lXU) |

---

### 📌 Highlights
- **Main Demo** – Ask questions, Lingo listens → thinks → answers.  
- **Face Recognition** – Login with OpenCV (Haar + LBPH) to load your personal dashboard.  
- **Personalized Teacher** – Strict lesson flow using TinyDB (Pre-Intermediate & Intermediate levels).  
---

## System Architecture

The app follows an **MVC-like** pattern:

1. **Presentation Layer (GUI)**
   - Tkinter-based screens: login, dashboard, lessons, textbook viewer  
   - Custom styles for academic look & feel

2. **Business Logic Layer**
   - `student_manager.py` – Handles TinyDB student profiles & progress
   - `lesson_manager.py` – Loads lessons & tracks completion
   - `textbook_manager.py` – Manages PDF/textbook content display
   - `api_manager.py` – AI API communications

3. **Data Layer**
   - **TinyDB** for student profiles & lesson progression
   - JSON lesson definitions
   - PDF/Textbook files
   - `.env` config for API keys

---

## Technical Specifications

- **Platform**: Raspberry Pi 4 (4GB RAM)  
- **Python**: 3.9+  
- **GUI**: Tkinter with ttk styling  
- **Database**: TinyDB + JSON  
- **STT**: Faster-Whisper (int8, tiny.en)  
- **TTS**: Piper (streaming engine)  
- **LLM**: OpenRouter (Qwen primary, Mistral/GPT fallback)  
- **Face Recognition**: OpenCV LBPH + Haar cascades  
- **Servo Control**: Arduino UNO + PCA9685  

---

## Installation Guide

### Prerequisites
- Raspberry Pi OS (Bullseye) or compatible Linux distro
- Python 3.9+ with `pip`
- Virtual environment recommended

### Setup
```bash
# Clone the repo
git clone https://github.com/robinglory/AI-Driven-Robotic-Head-for-Language-Learning-Assistance.git
cd AI-Driven-Robotic-Head-for-Language-Learning-Assistance/GUI

# Create & activate venv
python -m venv myenv
source myenv/bin/activate

# Install dependencies
pip install -r requirements.txt

# Setup environment variables
cp .env.example .env
nano .env  # add your API keys
```

---

## Configuration

Add to `.env`:
```ini
QWEN_API_KEY=your_openrouter_api_key
MINSTRAL_API_KEY=your_backup_api_key
```

---

## Usage

```bash
python main.py
```

**Workflow:**
1. **Login** → Login via face recognition / new student signup. 
2. **Dashboard** → Select lessons from dashboard.
3. **Implement STT**  → Voice or text input.
4. **Lingo Head Implement** → Robot responds with voice + gestures.
5. **Lesson Delivery** → Content adapts to prior progress  
6. **Progress Tracking** → Stores completion & mastery in TinyDB  
7. **PDF Export** → Generate academic-style lesson PDFs with title page

---

## API & AI Integration

1. Speech Recognition: Faster-Whisper (local, int8).
2. Language Model: OpenRouter (Qwen + Mistral failover).
   **Primary API** – Qwen (OpenRouter)  
   **Secondary API** – Mistral 7B fallback  (Both are wrapped in `api_manager.py` with provider switching, retries, and graceful fallbacks.)
3. Speech Synthesis: Piper (streaming, low-latency).
4. Face Recognition: OpenCV LBPH + Haar Cascade.

---

## File Structure

```
GUI/
├── main.py
├── lesson.py
├── login.py
├── dashboard.py
├── gui_serial.py
├── face_tracker.py
├── student_manager.py
├── lesson_manager.py
├── styles.py
├── conversations.json
├── students.json
├── requirements.txt
└── .env.example

```

---

## Dependencies

**requirements.txt**
```text
python-dotenv==1.0.0
openai==1.12.0
Pillow==10.0.0
requests==2.31.0
tinydb==4.8.0
reportlab==4.0.8
faster-whisper
webrtcvad
sounddevice
opencv-python
```

**Purpose:**
| Package        | Purpose                        |
| -------------- | ------------------------------ |
| faster-whisper | Local STT                      |
| webrtcvad      | Voice activity detection       |
| sounddevice    | Audio playback/record          |
| opencv-python  | Face recognition, Haar cascade |
| python-dotenv  | Env var management             |
| tinydb         | Student database               |
| reportlab      | PDF export                     |
| Pillow         | Image handling                 |
| requests       | API HTTP calls                 |

---

## Testing & Results
Latency (Raspberry Pi 4)
  1. STT: ~7.5s (tiny.en, int8)
  2. LLM response: <3s (Qwen/Mistral)
  3. TTS: <2s per chunk
Gesture Control
  1. Smooth servo transitions with PCA9685.
  2. Realistic human-like “listen / think / talk” animations.
Face Recognition
  1. Reliable login using LBPH with 20+ training images per student.

---
## Known Issues
- TinyDB file can grow if not periodically cleaned
- PDF export speed depends on lesson length
- GUI may hang during slow LLM calls (threading planned).
- Whisper int8 still ~7s latency (could improve with faster models).
- Piper voice selection limited to trained JSON configs.


---

## Future Enhancements
- Multi-language support (beyond English).
- Web-based interface (Flask/React).
- Rich media lessons (images, videos).
- Improved latency with quantized STT/LLM models.
- Servo gesture learning from real human data.
- Animated lesson transitions
- Progress analytics dashboard

## Related Work With Global Context

The development of AI-driven social robots and edge-based voice assistants is a highly active field of global research. To provide a fair, objective, and evidence-based overview of this ecosystem, the table below compares **Lingo** (this repository) with five recently published 2024–2026 academic papers from universities around the world. 

Each project tackles the challenge of Human-Robot Interaction (HRI) with different trade-offs between **Compute Power**, **Cost**, **Latency**, and **Physical Embodiment**.

| Research Paper / Project | Institution & Year | Hardware Platform | AI / Software Pipeline | Key Strengths | Limitations & Trade-offs |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **Lingo: AI-Driven Robot Head for Language Learning** *(This Repo)* | West Yangon Technological University (2026) | Raspberry Pi 4, Arduino Mega, 4-DOF 3D-Printed Head | Faster-Whisper (Local STT), OpenRouter API (LLMs), Piper (Local TTS), OpenCV/MediaPipe | **Mechatronic Sync:** Successfully syncs local edge-AI speech outputs with physical 4-DOF servo motors. Features a complete GUI and local database tracking on a single low-power Pi 4. | Experiences ~12-18s total loop latency due to heavy STT/TTS on Pi 4. Relies on an external API for LLM reasoning to avoid further CPU bottlenecks. |
| **"AI Assistant using LLM on Raspberry Pi"** *(Dr. Kiran G M et al.)* | International Journal of Advanced Scientific Innovation (2025) | Raspberry Pi 5 | Whisper/Vosk (STT), LLaMA 3.2 via Ollama (LLM), RHVoice (TTS) | **100% Offline & Fast:** Operates entirely without internet, ensuring complete privacy. Highly optimized with a response latency of only 2.2 seconds. | Exclusively a voice assistant. Completely lacks physical robotic embodiment, face-tracking, or mechatronic actuators. |
| **"Bloom Preview: A Low-Cost LLM-Powered Social Robot"** *(Kong et al.)* | University of South Florida (2026) | Raspberry Pi 5, XL-320 Servos, Touch Sensors | Dual Pipeline: Vosk/Google (STT), Gemini 2.5 Flash Lite, Piper/OpenAI (TTS) | **Affective Touch & Cost:** Integrates capacitive touch sensors for physical interaction. Highly cost-effective ($315-$556) compared to commercial alternatives. | Head actuation relies on a less-accurate tensile string mechanism. Relies heavily on cloud APIs (Google/OpenAI) for optimal speech synthesis. |
| **"Voice Intelligence at the Brilliance Edge"** *(A. Chu)* | Tampere University, Finland (2025) | Raspberry Pi 5 | Wav2Vec2 (STT), Gemma-3 1B (LLM), RAG Pipeline, Piper (TTS) | **Local RAG Integration:** Successfully utilizes a local vector database and RAG pipeline to query specific PDF manuals entirely offline. | **Severe Edge Latency:** Running the 1B parameter LLM locally on the Pi 5 CPU causes a massive generation delay of ~20 seconds, frustrating real-time conversations. No physical embodiment. |
| **"Social Robots for Second Language Learning"** *(E. Inoue)* | KTH Royal Institute of Technology, Sweden (2024) | Furhat Robot | GPT-4o (LLM), Google Cloud ASR, Amazon Polly (TTS) | **Pedagogical UX:** Deep analysis of bilingual vs. monolingual teaching. Features a highly realistic, 3D-projected face for immersive interaction. | **Extreme Cost & Cloud Dependency:** Dependent on the Furhat platform (~$28k). Requires constant, high-speed internet, and suffers from turn-taking interruption flaws. |
| **"Using a LLM-Based Conversational Agent in the Social Robot Mini"** *(Esteban-Lozano et al.)* | Universidad Carlos III de Madrid (2024) | "Mini" Social Robot | GPT-3.5-turbo (LLM), Google Cloud STT, ReadSpeaker (TTS) | **Advanced Architecture:** Excellent software architecture integrating a Decision-Making System (DMS) and HRI manager for elderly companionship. | Introduces noticeable cloud latency. ASR struggles significantly in noisy environments or with short sentences. |

> **Conclusion on Global Trade-offs:** 
> Current research demonstrates that deploying social robots requires strict compromises. Commercial platforms like **Furhat** (Sweden) offer incredible realism but are prohibitively expensive and strictly cloud-dependent. 100% offline edge-LLMs (like the **Tampere University** research) provide maximum privacy but suffer from severe CPU latency (~20 seconds). **Lingo** positions itself as a highly effective hybrid mechatronic middle-ground: proving that low-cost Raspberry Pi 4 hardware can physically drive 4-DOF servos and process local vision/speech, while offloading only the heavy LLM reasoning to an API to maintain a viable conversation speed for language learners.

