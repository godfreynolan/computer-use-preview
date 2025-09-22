from openai import OpenAI
from dotenv import load_dotenv
import os

load_dotenv()
client = OpenAI()

response = client.responses.create(
    model="computer-use-preview",
    tools=[{
        "type": "computer_use_preview",
        "display_width": 1024,
        "display_height": 768,
        "environment": "browser" # other possible values: "mac", "windows", "ubuntu"
    }],    
    input=[
        {
          "role": "user",
          "content": [
            {
              "type": "input_text",
              "text": "Check the latest OpenAI news on bing.com."
            }
          ]
        }
    ],
    reasoning={
        "summary": "concise",
    },
    truncation="auto"
)
print(response.output)
