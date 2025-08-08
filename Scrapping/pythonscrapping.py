import requests
from bs4 import BeautifulSoup
import json
import os

# URL of the lesson
url = "https://test-english.com/grammar-points/a2/much-many-little-few-some-any/"

# Request page content
response = requests.get(url)
soup = BeautifulSoup(response.text, "html.parser")

# Parse title and summary
title = soup.find("h1").get_text(strip=True)
summary = soup.find("p").get_text(strip=True)

# Parse content sections and examples
content = []
examples = []

headers = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                  "AppleWebKit/537.36 (KHTML, like Gecko) "
                  "Chrome/116.0.5845.111 Safari/537.36"
}

response = requests.get(url, headers=headers)


for section in soup.find_all("div", class_="entry-content"):
    paragraphs = section.find_all("p")
    for p in paragraphs:
        text = p.get_text(strip=True)
        if text:
            content.append(text)
            
    # optional: if examples are marked in <ul><li>
    lists = section.find_all("ul")
    for ul in lists:
        for li in ul.find_all("li"):
            examples.append(li.get_text(strip=True))

# Build JSON structure
lesson_data = {
    "lesson_id": "a2_quantifiers_01",
    "type": "Grammar",
    "level": "A2",
    "title": title,
    "summary": summary,
    "content": content,
    "examples": examples,
    "tips": []
}

# Path to save JSON
save_path = "/home/robinglory/Desktop/AIProjects/Thesis/english_lessons/A2 Level (Pre-Intermediate)/Grammar/much_many_little_few_some_any.json"

# Ensure directory exists
os.makedirs(os.path.dirname(save_path), exist_ok=True)

# Save JSON file
with open(save_path, "w", encoding="utf-8") as f:
    json.dump(lesson_data, f, ensure_ascii=False, indent=2)

print("JSON saved successfully!")
