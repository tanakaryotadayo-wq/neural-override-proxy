import urllib.request
import json
import logging

logging.basicConfig(level=logging.INFO)

payload = {
    "systemInstruction": {
        "role": "user",
        "parts": [{"text": "You are a helpful coding assistant. Do what the user says."}]
    },
    "contents": [{"role": "user", "parts": [{"text": "Hello"}]}]
}

data = json.dumps(payload).encode('utf-8')

req = urllib.request.Request("http://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-pro-exp:streamGenerateContent",
                             data=data,
                             headers={"Content-Type": "application/json"},
                             method="POST")

req.set_proxy("127.0.0.1:18080", "http")

try:
    print("Testing JSON injection via proxy...")
    urllib.request.urlopen(req)
except Exception as e:
    print("Response details:", e)
