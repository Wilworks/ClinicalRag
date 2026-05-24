import os
import django
from django.conf import settings

# Setup Django environment
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
django.setup()

from groq import Groq

print("Groq API Key from settings:", settings.GROQ_API_KEY)
client = Groq(api_key=settings.GROQ_API_KEY)

try:
    print("Testing llama-3.1-8b-instant model...")
    response = client.chat.completions.create(
        model="llama-3.1-8b-instant",
        messages=[{"role": "user", "content": "Hello! Say test."}],
        temperature=0.2,
        max_tokens=10,
    )
    print("Success! Response:", response.choices[0].message.content)
except Exception as e:
    print("Failed llama-3.1-8b-instant:", e)

try:
    print("Testing llama3-8b-8192 model...")
    response = client.chat.completions.create(
        model="llama3-8b-8192",
        messages=[{"role": "user", "content": "Hello! Say test."}],
        temperature=0.2,
        max_tokens=10,
    )
    print("Success! Response:", response.choices[0].message.content)
except Exception as e:
    print("Failed llama3-8b-8192:", e)
