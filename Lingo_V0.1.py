import time
import os
import json
import random
from openai import OpenAI
from dotenv import load_dotenv
load_dotenv()

# Load API keys from environment
deepseek_api_key = os.getenv("DEEPSEEK_API_KEY")
minstral_api_key = os.getenv("MINSTRAL_API_KEY")


# Default model and client
current_model = "qwen/qwen3-coder:free"
current_key = deepseek_api_key

client = OpenAI(
    base_url="https://openrouter.ai/api/v1",
    api_key=current_key,
    timeout=10.0
)
client._client.headers = {
    "HTTP-Referer": "http://localhost:3000",
    "X-Title": "Lingo Language Tutor"
}

def switch_to_backup_client():
    global client, current_key, current_model
    print("Lingo: Switching to backup API key (Mistral)...")
    current_key = minstral_api_key
    current_model = "mistralai/mistral-7b-instruct:free"
    client = OpenAI(
        base_url="https://openrouter.ai/api/v1",
        api_key=current_key,
        timeout=10.0
    )
    client._client.headers = {
        "HTTP-Referer": "http://localhost:3000",
        "X-Title": "Lingo Language Tutor"
    }


# --- Print with Typing Effect --- #
def lingo_print(text, delay=0.05, end='\n'):
    """Print text with a typing effect"""
    for char in text:
        print(char, end='', flush=True)
        time.sleep(delay)
    print(end=end)


# --- Student Database --- #
students = {
    "yan naing kyaw tint": {
        "level": "A2",
        "name": "Yan Naing Kyaw Tint",
        "last_visited": "2025-6-22",
        "progress": {"vocabulary": 0.4, "grammar": 0.2, "reading":0.6}
    },
    "ngwe thant sin": {
        "level": "B1",
        "name": "Ngwe Thant Sin",
        "last_visited": "2023-11-15",
        "progress": {"vocabulary": 0.4, "grammar": 0.2}
    },
    "wai yan aung": {
        "level": "B1",
        "name": "Wai Yan Aung",
        "last_visited": "2023-11-20",
        "progress": {"reading": 0.7, "vocabulary": 0.5}
    },
    "aye mrat san": {
        "level": "A2",
        "name": "Aye Mrat San",
        "last_visited": "2023-11-18",
        "progress": {"grammar": 0.3, "reading": 0.6}
    }
}

# --- Global State --- #
conversation_history = []
current_user = None
current_lesson = {}
current_topic = None

# --- Personalized Greetings --- #
GREETINGS = [
    "It's wonderful to see you again, {name}!",
    "Welcome back, {name}! Ready to continue our English journey?",
    "Hello there, {name}! I've been looking forward to our session today.",
    "{name}! How have you been since our last lesson?",
    "Ah, {name}! Perfect timing for our English practice."
]

# --- Encouragements --- #
ENCOURAGEMENTS = [
    "Great choice!",
    "Excellent selection!",
    "That's a wonderful topic to focus on!",
    "I think you'll really enjoy this lesson.",
    "Perfect! Let's dive into this together."
]

# --- Load Lessons by Type --- #
def get_lesson_by_type(user_level, lesson_type):
    try:
        root = "/home/robinglory/Desktop/AI Projects/Thesis/english_lessons"
        folder = os.path.join(root, 
                            f"{user_level} Level (Pre-Intermediate)" if user_level == "A2" 
                            else f"{user_level} Level (Intermediate)", 
                            lesson_type.capitalize())
        
        if not os.path.isdir(folder):
            return None
        
        files = [f for f in os.listdir(folder) if f.endswith(".json")]
        if not files:
            return None
        
        # Select lesson based on progress
        progress = current_user['progress'].get(lesson_type.lower(), 0)
        lesson_index = min(int(progress * len(files)), len(files)-1)
        filepath = os.path.join(folder, files[lesson_index])
        
        with open(filepath, "r", encoding="utf-8") as f:
            lesson = json.load(f)
            lesson['filepath'] = filepath
            return lesson
            
    except Exception as e:
        lingo_print(f"Lingo: Error loading lesson: {e}")
        return None

# --- Update Student Progress --- #
def update_progress(lesson_type):
    if current_user and current_lesson:
        current_user['progress'][lesson_type.lower()] = current_user['progress'].get(lesson_type.lower(), 0) + 0.1
        current_user['last_visited'] = datetime.now().strftime("%Y-%m-%d")

# --- Lingo AI Response --- #
def ask_lingo(question):
    global current_lesson, current_topic

    if question.lower() in ["quit", "exit", "bye", "that's all for today"]:
        if current_topic:
            update_progress(current_topic)
        farewell = random.choice([
            "It was a pleasure teaching you today!",
            "Great work today! I'm proud of your progress.",
            "Wonderful session! Let's continue next time.",
            "You're doing amazing! Until next time."
        ])
        return farewell

    # Prepare context for the AI
    context = []
    
    if current_lesson:
        context.append(f"Current Lesson: {current_lesson.get('title', '')}")
        if 'objective' in current_lesson:
            context.append(f"Lesson Objective: {current_lesson['objective']}")
        if 'text' in current_lesson:
            context.append(f"Key Content: {current_lesson['text'][:200]}...")
    
    context.append(f"Student Level: {current_user['level']}")
    context.append(f"Student Name: {current_user['name']}")
    
    if current_user['progress']:
        progress_str = ", ".join([f"{k}: {int(v*100)}%" for k,v in current_user['progress'].items()])
        context.append(f"Student Progress: {progress_str}")
    
    context.append(f"Student Question: {question}")
    
    # Build conversation history
    messages = [
        {"role": "system", "content": "You are Lingo, a friendly, patient English teaching AI. "
         "You teach English to non-native speakers. Be warm, encouraging, and engaging. "
         "Adapt to the student's level. Ask questions to check understanding. "
         "Use the lesson content but don't just recite it - explain clearly. "
         "Keep responses under 4 sentences unless explaining complex concepts."}
    ]
    
    messages.extend(conversation_history[-4:])
    messages.append({"role": "user", "content": "\n".join(context)})
    
    try:
        try:
            response = client.chat.completions.create(
                model=current_model,
                messages=messages,
                max_tokens=150,
                temperature=0.8,
            )
            reply = response.choices[0].message.content.strip()
            conversation_history.append({"role": "assistant", "content": reply})
            return reply

        except Exception as e:
            if "invalid_api_key" in str(e).lower() or "unauthorized" in str(e).lower():
                switch_to_backup_client()
                return ask_lingo(question)  # retry with backup

            return f"I'm having trouble thinking right now. Could you try asking again? ({str(e)})"
        reply = response.choices[0].message.content.strip()
        conversation_history.append({"role": "assistant", "content": reply})
        return reply
        
    except Exception as e:
        return f"I'm having trouble thinking right now. Could you try asking again? ({str(e)})"

# --- Natural Language Understanding --- #
def understand_lesson_choice(input_text):
    """Convert natural language to lesson choice"""
    input_text = input_text.lower()
    
    if any(word in input_text for word in ['read', '1']):
        return 'reading'
    elif any(word in input_text for word in ['grammar', '2', 'gram']):
        return 'grammar'
    elif any(word in input_text for word in ['vocab', '3', 'word']):
        return 'vocabulary'
    return None

# --- Improved Lesson Interaction --- #
def start_lesson_interaction():
    """Guide the student through starting a lesson"""
    while True:
        lingo_print("\nLingo: How would you like to begin?", delay=0.03)
        lingo_print("1. Explain key concepts first", delay=0.02)
        lingo_print("2. Start with the lesson material", delay=0.02)
        
        choice = input(f"{current_user['name'].split()[0]}: ").lower()
        
        if any(word in choice for word in ['1', 'explain', 'concept', 'teach']):
            lingo_print("\nLingo: Let me explain the key concepts...")
            if 'objective' in current_lesson:
                lingo_print(f"Lingo: {current_lesson['objective']}", delay=0.03)
            if 'summary' in current_lesson:
                lingo_print(f"Lingo: {current_lesson['summary']}", delay=0.03)
            return True
                
        elif any(word in choice for word in ['2', 'start', 'begin', 'material']):
            lingo_print("\nLingo: Let's begin with the lesson material...")
            if 'text' in current_lesson:
                lingo_print(f"\nLingo: {current_lesson['text'][:200]}...", delay=0.03)
                lingo_print("\nLingo: What are your thoughts on this?", delay=0.02)
            return False
            
        else:
            lingo_print("Lingo: I didn't understand. Please choose:")
            lingo_print("'explain' or 'start'", delay=0.02)

# --- Main Conversation Flow --- #
def main():
    global current_user, current_lesson, current_topic
    
    # Initial greeting
    lingo_print("Lingo: Hello! I'm Lingo, your English tutor. What's your full name?")
    
    # User recognition
    while True:
        name = input("You: ").strip().lower()
        if name in students:
            current_user = students[name]
            greeting = random.choice(GREETINGS).format(name=current_user['name'].split()[0])
            
            # Add personalized progress mention
            if current_user['progress']:
                best_subject = max(current_user['progress'].items(), key=lambda x: x[1])[0]
                greeting += f" Last time we worked on {best_subject}."
                
            lingo_print(f"Lingo: {greeting}")
            break
        else:
            lingo_print("Lingo: I don't recognize that name. Please try your full name.")
    
    # Main lesson loop
    while True:
        try:
            # Lesson selection
            lingo_print("\nLingo: What would you like to practice today?")
            lingo_print("1. Reading\n2. Grammar\n3. Vocabulary\n4. Quit", delay=0.02)
            
            choice = input(f"{current_user['name'].split()[0]}: ").strip().lower()
            
            # Handle quitting
            if choice in ['4', 'quit', 'exit', 'bye']:
                lingo_print("\nLingo: It was great working with you today! Goodbye!")
                break
                
            # Get lesson type
            lesson_type = understand_lesson_choice(choice)
            if not lesson_type:
                lingo_print("Lingo: I didn't understand. Please choose Reading, Grammar, or Vocabulary.")
                continue
                
            # Load lesson
            current_topic = lesson_type
            lesson = get_lesson_by_type(current_user['level'], lesson_type.capitalize())
            if not lesson:
                lingo_print("Lingo: Couldn't find a lesson for that topic.")
                continue
                
            current_lesson = lesson
            lingo_print(f"\nLingo: {random.choice(ENCOURAGEMENTS)}")
            lingo_print(f"Lingo: Today's lesson: {lesson.get('title', 'English Practice')}")
            
            # Start lesson interaction
            start_lesson_interaction()
            
            # Continue with lesson...
            while True:
                user_input = input(f"{current_user['name'].split()[0]}: ").strip()
                
                if user_input.lower() in ['back', 'menu']:
                    break
                    
                response = ask_lingo(user_input)
                lingo_print(f"Lingo: {response}")
                
                if user_input.lower() in ['quit', 'exit']:
                    return
                    
        except Exception as e:
            lingo_print(f"Lingo: Sorry, I encountered an error: {str(e)}")
            continue

if __name__ == "__main__":
    main()
