#!/usr/bin/env python3
import json
import argparse
import sys
import struct
from pathlib import Path

def decode_varint(data: bytes, index: int = 0):
    result = 0
    shift = 0
    while index < len(data):
        b = data[index]
        result |= ((b & 0x7F) << shift)
        index += 1
        if not (b & 0x80):
            return result, index
        shift += 7
    return result, index

def decode_message(data: bytes, strict: bool = False):
    index = 0
    fields = []
    while index < len(data):
        start_index = index
        try:
            tag_type, index = decode_varint(data, index)
            if index > len(data): break
            
            wire_type = tag_type & 0x7
            tag_num = tag_type >> 3
            
            if wire_type == 0:  # Varint
                val, index = decode_varint(data, index)
                fields.append((tag_num, wire_type, val))
            elif wire_type == 1:  # 64-bit
                if index + 8 > len(data): break
                val = struct.unpack('<Q', data[index:index+8])[0]
                index += 8
                fields.append((tag_num, wire_type, val))
            elif wire_type == 2:  # Length-delimited
                length, index = decode_varint(data, index)
                if index + length > len(data): break
                val = data[index:index+length]
                index += length
                
                # Check if it's a sub-message or a string
                is_submessage = False
                if len(val) > 0:
                    try:
                        # strict check for submessage: it must consume exactly len(val) bytes
                        sub_fields, parsed_len = decode_message(val, strict=True)
                        if sub_fields and parsed_len == len(val):
                            fields.append((tag_num, wire_type, sub_fields))
                            is_submessage = True
                    except Exception:
                        pass
                
                if not is_submessage:
                    # check if string
                    try:
                        text = val.decode('utf-8')
                        # only consider it a string if it has mostly printable characters
                        if text.isprintable() or text.isascii():
                            fields.append((tag_num, wire_type, text))
                        else:
                            fields.append((tag_num, wire_type, val))
                    except UnicodeDecodeError:
                        fields.append((tag_num, wire_type, val))
            elif wire_type == 5:  # 32-bit
                if index + 4 > len(data): break
                val = struct.unpack('<I', data[index:index+4])[0]
                index += 4
                fields.append((tag_num, wire_type, val))
            else:
                break
        except Exception:
            break
            
    if strict:
        return fields, index
    return fields

def to_dict(fields):
    """Convert decoded fields to a nested dictionary/list structure for easy JSON dumping."""
    result = {}
    for tag_num, wire_type, val in fields:
        out_val = val
        if isinstance(val, list) and len(val) > 0 and isinstance(val[0], tuple):
            out_val = to_dict(val)
        elif isinstance(val, bytes):
            out_val = f"<bytes length={len(val)}>"
            
        if tag_num in result:
            if isinstance(result[tag_num], list):
                result[tag_num].append(out_val)
            else:
                result[tag_num] = [result[tag_num], out_val]
        else:
            result[tag_num] = out_val
    return result

def extract_content(doc):
    """Recursively search for interesting Gemini content fields"""
    results = {
        "systemInstruction": [],
        "ephemeralMessage": [],
        "plannerConfig": [],
        "raw_strings": []
    }
    
    if isinstance(doc, dict):
        for k, v in doc.items():
            sub = extract_content(v)
            for k2, v2 in sub.items():
                results[k2].extend(v2)
    elif isinstance(doc, list):
        for el in doc:
            sub = extract_content(el)
            for k2, v2 in sub.items():
                results[k2].extend(v2)
    elif isinstance(doc, str):
        if len(doc) > 5:
            # Simple content heuristics
            if "systemInstruction" in doc or "You are" in doc or "Antigravity" in doc:
                results["systemInstruction"].append(doc)
            elif "ephemeralMessage" in doc or "EPHEMERAL" in doc:
                results["ephemeralMessage"].append(doc)
            elif "plannerConfig" in doc or "planner" in doc:
                results["plannerConfig"].append(doc)
            else:
                results["raw_strings"].append(doc)
                
    return results

def main():
    parser = argparse.ArgumentParser(description="Analyze Protobuf messages from Gemini API captures")
    parser.add_argument("file", help="Path to .bin dump file")
    parser.add_argument("--json", action="store_true", help="Output purely in JSON format")
    args = parser.parse_args()

    path = Path(args.file)
    if not path.exists():
        print(f"Error: {path} not found.", file=sys.stderr)
        sys.exit(1)

    data = path.read_bytes()
    # If the file contains HTTP headers/gRPC envelope, we might need to strip it.
    # gRPC messages start with a 5-byte envelope: [0] = compressed flag, [1:5] = length
    offset = 0
    messages = []
    
    # Simple heuristics to detect multiple gRPC frames
    while offset < len(data):
        if len(data) - offset >= 5 and data[offset] == 0:
            msg_len = struct.unpack(">I", data[offset+1:offset+5])[0]
            if msg_len > 0 and msg_len <= len(data) - offset - 5:
                frame_data = data[offset+5:offset+5+msg_len]
                msg = decode_message(frame_data)
                messages.append(msg)
                offset += 5 + msg_len
                continue
        # If not recognizable gRPC frame, parse whole
        msg = decode_message(data[offset:])
        messages.append(msg)
        break

    output = {"messages": []}
    for m in messages:
        msg_dict = to_dict(m)
        extracted = extract_content(msg_dict)
        output["messages"].append({
            "structure": msg_dict,
            "extracted": extracted
        })

    if args.json:
        print(json.dumps(output, ensure_ascii=False, indent=2))
    else:
        for idx, m in enumerate(output["messages"]):
            print(f"--- Message {idx} ---")
            ex = m["extracted"]
            if ex["systemInstruction"]:
                print("\\n[+] systemInstruction fragments found:")
                for s in ex["systemInstruction"]: print(f"  - {s[:200]}...")
            if ex["ephemeralMessage"]:
                print("\\n[+] ephemeralMessage fragments found:")
                for s in ex["ephemeralMessage"]: print(f"  - {s[:200]}...")
            if ex["plannerConfig"]:
                print("\\n[+] plannerConfig fragments found:")
                for s in ex["plannerConfig"]: print(f"  - {s[:200]}...")
                
            print(f"Total raw strings extracted: {len(ex['raw_strings'])}")
            print("-" * 20)

if __name__ == "__main__":
    main()
