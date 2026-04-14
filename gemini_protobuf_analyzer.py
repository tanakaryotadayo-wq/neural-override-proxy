#!/usr/bin/env python3
import argparse
import io
import json
import sys

TARGET_STRINGS = [b"systemInstruction", b"ephemeralMessage", b"plannerConfig"]

def read_varint(stream):
    result = 0
    shift = 0
    while True:
        byte = stream.read(1)
        if not byte:
            raise EOFError()
        b = ord(byte)
        result |= (b & 0x7f) << shift
        shift += 7
        if not (b & 0x80):
            break
        if shift > 70:
            raise ValueError("Varint too long")
    return result

def parse_protobuf(stream, end_pos, path, results):
    while stream.tell() < end_pos:
        try:
            tag = read_varint(stream)
        except EOFError:
            break
            
        field_num = tag >> 3
        wire_type = tag & 7
        
        current_path = path + [str(field_num)]
        
        try:
            if wire_type == 0:
                read_varint(stream)
            elif wire_type == 1:
                stream.read(8)
            elif wire_type == 2:
                length = read_varint(stream)
                if length < 0 or stream.tell() + length > end_pos:
                    break
                data = stream.read(length)
                
                # Only process fields that contain our target strings in their raw bytes
                if any(t in data for t in TARGET_STRINGS):
                    sub_stream = io.BytesIO(data)
                    sub_results = []
                    
                    # Attempt to parse as a nested sub-message first
                    try:
                        parse_protobuf(sub_stream, length, current_path, sub_results)
                    except Exception:
                        pass
                    
                    # If parsing as a sub-message yielded targets, add them
                    if sub_results:
                        results.extend(sub_results)
                    else:
                        # Otherwise, fall back to interpreting this field as a string/bytes value
                        try:
                            str_val = data.decode('utf-8')
                        except UnicodeDecodeError:
                            str_val = str(data)
                        results.append({"path": ".".join(current_path), "value": str_val})
            elif wire_type == 5:
                stream.read(4)
            elif wire_type == 3 or wire_type == 4:
                # Start/End groups are deprecated; ignore their structure safely
                pass
            else:
                # Unknown wire type, cannot proceed safely
                break
        except Exception:
            # If any error occurs reading the field data, abort this level
            break

def main():
    parser = argparse.ArgumentParser(description="Parse Gemini API Protobuf binary data without a schema.")
    parser.add_argument("input_file", help="Path to the binary protobuf file")
    parser.add_argument("--json", action="store_true", help="Output in JSON format")
    args = parser.parse_args()

    try:
        with open(args.input_file, "rb") as f:
            data = f.read()
    except Exception as e:
        print(f"Error reading file: {e}", file=sys.stderr)
        sys.exit(1)

    stream = io.BytesIO(data)
    results = []
    
    parse_protobuf(stream, len(data), [], results)

    if args.json:
        print(json.dumps(results, indent=2, ensure_ascii=False))
    else:
        if not results:
            print("No matching fields found.")
        for res in results:
            print(f"Field Path: {res['path']}")
            print(f"Value: {res['value']}")
            print("-" * 40)

if __name__ == "__main__":
    main()
