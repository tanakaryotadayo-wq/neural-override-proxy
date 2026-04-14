import urllib.request
import struct

# Simple valid protobuf containing a string
# Tag 1 (Type 2: length delimited): 0x0a
# Length: 34
# Data: "You are a helpful coding assistant"
test_string = b"You are a helpful coding assistant"
encoded_data = struct.pack(">B B", 0x0a, len(test_string)) + test_string

# Wrap it in a gRPC frame (prefix 0, 4-byte length)
payload = struct.pack(">B I", 0, len(encoded_data)) + encoded_data

print("Payload size:", len(payload))

req = urllib.request.Request("http://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-pro-exp:streamGenerateContent",
                             data=payload,
                             headers={
                                 "Content-Type": "application/grpc"
                             },
                             method="POST")

req.set_proxy("127.0.0.1:18080", "http")

try:
    print("Testing injection via proxy...")
    urllib.request.urlopen(req)
except Exception as e:
    print("Response details:", e)


