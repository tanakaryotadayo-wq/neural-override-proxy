import importlib.util
import json
import sys
import threading
from pathlib import Path
from urllib.request import Request, urlopen

import pytest


def load_bridge_module():
    module_path = Path(__file__).resolve().parents[1] / "titan-bridge" / "gemini_a2a_bridge.py"
    spec = importlib.util.spec_from_file_location("gemini_a2a_bridge", module_path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


BRIDGE = load_bridge_module()


class MockOpenAIHandler(BRIDGE.BaseHTTPRequestHandler):
    def log_message(self, _format, *args):
        return

    def do_POST(self):
        content_length = int(self.headers.get("Content-Length", "0"))
        payload = json.loads(self.rfile.read(content_length).decode("utf-8"))
        self.server.requests.append(payload)  # type: ignore[attr-defined]
        self.send_response(self.server.response_status)  # type: ignore[attr-defined]
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        if self.server.response_status >= 400:  # type: ignore[attr-defined]
            body = {"error": {"message": self.server.response_text}}  # type: ignore[attr-defined]
        else:
            body = {
                "choices": [
                    {
                        "message": {
                            "content": self.server.response_text  # type: ignore[attr-defined]
                        }
                    }
                ]
            }
        self.wfile.write(json.dumps(body).encode("utf-8"))


def start_http_server(server):
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return thread


def post_json(url, payload, headers=None):
    request = Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json", **(headers or {})},
        method="POST",
    )
    with urlopen(request, timeout=5) as response:
        return response.status, response.headers, json.loads(response.read().decode("utf-8"))


def get_json(url):
    with urlopen(url, timeout=5) as response:
        return response.status, response.headers, json.loads(response.read().decode("utf-8"))


def post_sse(url, payload):
    request = Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json", "Accept": "text/event-stream"},
        method="POST",
    )
    with urlopen(request, timeout=5) as response:
        raw = response.read().decode("utf-8")
    events = []
    for block in raw.strip().split("\n\n"):
        data_lines = [line[6:] for line in block.splitlines() if line.startswith("data: ")]
        if data_lines:
            events.append(json.loads("".join(data_lines)))
    return events


@pytest.fixture
def mock_backends():
    servers = {}
    try:
        for name, text in {
            "conversation": "conversation-ok",
            "agent": "agent-ok",
            "utility": "utility-ok",
        }.items():
            server = BRIDGE.ThreadingHTTPServer(("127.0.0.1", 0), MockOpenAIHandler)
            server.requests = []  # type: ignore[attr-defined]
            server.response_text = text  # type: ignore[attr-defined]
            server.response_status = 200  # type: ignore[attr-defined]
            start_http_server(server)
            servers[name] = server
        yield servers
    finally:
        for server in servers.values():
            server.shutdown()
            server.server_close()


@pytest.fixture
def bridge_server(mock_backends):
    routes = {
        "conversation": BRIDGE.RouteConfig(
            route_id="conversation",
            display_name="Conversation Lane",
            base_url=f"http://127.0.0.1:{mock_backends['conversation'].server_address[1]}",
            model="chat-model",
            temperature=0.6,
            max_tokens=256,
            description="chat lane",
            system_prompt="chat system prompt",
        ),
        "agent": BRIDGE.RouteConfig(
            route_id="agent",
            display_name="Implementation Lane",
            base_url=f"http://127.0.0.1:{mock_backends['agent'].server_address[1]}",
            model="agent-model",
            temperature=0.2,
            max_tokens=256,
            description="agent lane",
            system_prompt="agent system prompt",
        ),
        "utility": BRIDGE.RouteConfig(
            route_id="utility",
            display_name="Utility Lane",
            base_url=f"http://127.0.0.1:{mock_backends['utility'].server_address[1]}",
            model="utility-model",
            temperature=0.1,
            max_tokens=256,
            description="utility lane",
            system_prompt="utility system prompt",
        ),
    }
    bridge = BRIDGE.LocalGeminiA2ABridge(host="127.0.0.1", port=0, timeout_seconds=5, routes=routes)
    server = BRIDGE.BridgeHTTPServer(("127.0.0.1", 0), bridge)
    start_http_server(server)
    try:
        base_url = f"http://127.0.0.1:{server.server_address[1]}"
        yield bridge, server, base_url
    finally:
        server.shutdown()
        server.server_close()


def test_agent_card_advertises_http_json_and_newgate_skill(bridge_server):
    _, _, base_url = bridge_server

    status, _, payload = get_json(f"{base_url}/.well-known/agent-card.json")

    assert status == 200
    assert payload["preferredTransport"] == "HTTP+JSON"
    assert payload["additionalInterfaces"][0]["transport"] == "JSONRPC"
    assert len(payload["skills"]) == 4
    assert any(skill["id"] == "newgate_system" for skill in payload["skills"])


def test_rest_message_send_defaults_to_conversation_lane(bridge_server, mock_backends):
    _, _, base_url = bridge_server

    status, _, payload = post_json(
        f"{base_url}/v1/message:send",
        {
            "message": {
                "role": "ROLE_USER",
                "content": [{"text": "Explain the architecture tradeoff."}],
            }
        },
    )

    assert status == 200
    assert payload["task"]["status"]["state"] == "TASK_STATE_COMPLETED"
    assert len(mock_backends["conversation"].requests) == 1
    assert len(mock_backends["agent"].requests) == 0
    assert len(mock_backends["utility"].requests) == 0
    assert payload["task"]["artifacts"][0]["parts"][0]["text"] == "conversation-ok"


def test_rest_message_send_routes_agent_when_autoexecute_is_enabled(bridge_server, mock_backends):
    _, _, base_url = bridge_server

    status, _, payload = post_json(
        f"{base_url}/v1/message:send",
        {
            "message": {
                "role": "ROLE_USER",
                "content": [{"text": "Fix the failing unit test."}],
                "metadata": {
                    "coderAgent": {
                        "kind": "agent-settings",
                        "workspacePath": "/tmp/project",
                        "autoExecute": True,
                    }
                },
            }
        },
    )

    assert status == 200
    assert payload["task"]["metadata"]["routeId"] == "agent"
    assert len(mock_backends["conversation"].requests) == 0
    assert len(mock_backends["agent"].requests) == 1
    assert mock_backends["agent"].requests[0]["model"] == "agent-model"


def test_custom_task_create_then_cancel(bridge_server):
    _, _, base_url = bridge_server

    _, _, task_id = post_json(
        f"{base_url}/tasks",
        {"agentSettings": {"route": "utility"}, "contextId": "ctx-1"},
    )

    status, _, payload = post_json(f"{base_url}/v1/tasks/{task_id}:cancel", {})

    assert status == 200
    assert payload["status"]["state"] == "TASK_STATE_CANCELLED"
    assert payload["metadata"]["routeId"] == "utility"


def test_rest_stream_emits_status_update_and_final_task(bridge_server, mock_backends):
    _, _, base_url = bridge_server

    events = post_sse(
        f"{base_url}/v1/message:stream",
        {
            "message": {
                "role": "ROLE_USER",
                "content": [{"text": "@utility Summarize these logs."}],
            }
        },
    )

    assert len(events) == 2
    assert "statusUpdate" in events[0]
    assert events[0]["statusUpdate"]["status"]["state"] == "TASK_STATE_WORKING"
    assert "task" in events[1]
    assert events[1]["task"]["metadata"]["routeId"] == "utility"
    assert len(mock_backends["utility"].requests) == 1


def test_jsonrpc_message_send_returns_normalized_task_shape(bridge_server, mock_backends):
    _, _, base_url = bridge_server

    status, _, payload = post_json(
        f"{base_url}/",
        {
            "jsonrpc": "2.0",
            "id": 7,
            "method": "message/send",
            "params": {
                "message": {
                    "kind": "message",
                    "role": "user",
                    "parts": [{"kind": "text", "text": "Hello there"}],
                }
            },
        },
    )

    assert status == 200
    assert payload["jsonrpc"] == "2.0"
    assert payload["id"] == 7
    assert payload["result"]["kind"] == "task"
    assert payload["result"]["status"]["state"] == "completed"
    assert len(mock_backends["conversation"].requests) == 1


def test_list_commands_includes_acp_commands(bridge_server):
    _, _, base_url = bridge_server

    status, _, payload = get_json(f"{base_url}/listCommands")

    names = {command["name"] for command in payload["commands"]}
    assert status == 200
    assert "acp_deepthink" in names
    assert "acp_deepsearch" in names
    assert "newgate_status" in names
    assert "newgate_deepthink" in names


def test_execute_command_runs_acp_deepthink_with_audit(bridge_server):
    bridge, _, base_url = bridge_server
    seen = {}

    def fake_invoke(runtime, prompt, model, timeout):
        seen.update({"runtime": runtime, "prompt": prompt, "model": model, "timeout": timeout})
        return {
            "text": "However this design has a risk because the fallback path is missing. Specifically the failure mode is undocumented.",
            "exit_code": 0,
            "elapsed": 0.4,
            "command": ["fake-cli", runtime],
        }

    bridge._invoke_acp_cli = fake_invoke  # type: ignore[method-assign]

    status, _, payload = post_json(
        f"{base_url}/executeCommand",
        {
            "command": "acp_deepthink",
            "args": [
                {
                    "prompt": "この設計の穴を洗い出して",
                    "runtime": "claude",
                    "model": "sonnet",
                    "timeout": 33,
                }
            ],
        },
    )

    assert status == 200
    assert payload["command"] == "acp_deepthink"
    assert payload["runtime"] == "claude"
    assert payload["model"] == "sonnet"
    assert payload["preset"] == "刃"
    assert payload["audit"]["verdict"] == "PASS"
    assert seen["runtime"] == "claude"
    assert seen["model"] == "sonnet"
    assert seen["timeout"] == 33
    assert "PCC Protocol" in seen["prompt"]
    assert "ACP DEEPTHINK" in seen["prompt"]


def test_newgate_profile_endpoint_exposes_embedding_and_bridge_commands(bridge_server):
    _, _, base_url = bridge_server

    status, _, payload = get_json(f"{base_url}/newgate/profile")

    assert status == 200
    assert payload["profile"]["embedding"]["primaryModel"] == "qwen3-embedding-8b"
    assert "newgate_deepsearch" in payload["bridge"]["commands"]


def test_execute_command_runs_newgate_deepsearch_with_embedded_context(bridge_server):
    bridge, _, base_url = bridge_server
    seen = {}

    def fake_invoke(runtime, prompt, model, timeout):
        seen.update({"runtime": runtime, "prompt": prompt, "model": model, "timeout": timeout})
        return {
            "text": "However this pipeline has a weakness because store-side packetization is still pending. Specifically evidence is missing for automated normalization.",
            "exit_code": 0,
            "elapsed": 0.6,
            "command": ["fake-cli", runtime],
        }

    bridge._invoke_acp_cli = fake_invoke  # type: ignore[method-assign]

    status, _, payload = post_json(
        f"{base_url}/executeCommand",
        {
            "command": "newgate_deepsearch",
            "args": [
                {
                    "prompt": "file-first memory pipeline の弱点を洗って",
                    "runtime": "gemini",
                    "model": "standard",
                    "timeout": 21,
                }
            ],
        },
    )

    assert status == 200
    assert payload["command"] == "newgate_deepsearch"
    assert payload["newgateFocus"] == "research"
    assert payload["newgateVersion"] == "2.1"
    assert payload["audit"]["verdict"] == "PASS"
    assert seen["runtime"] == "gemini"
    assert seen["model"] == "gemini-2.5-pro"
    assert seen["timeout"] == 21
    assert "[Newgate Context]" in seen["prompt"]
    assert "qwen3-embedding-8b" in seen["prompt"]


def test_execute_command_uses_fusion_gate_for_acp_when_enabled(bridge_server):
    bridge, _, base_url = bridge_server
    bridge.use_fusion_gate_for_acp = True
    bridge.fusion_gate_cli_fallback = False
    seen = {}

    def fake_gate(runtime, prompt, model, timeout):
        seen.update({"runtime": runtime, "prompt": prompt, "model": model, "timeout": timeout})
        return {
            "text": "However the lane contract is still underspecified and needs concrete adapter boundaries.",
            "exit_code": 0,
            "elapsed": 0.5,
            "command": ["fusion-gate", "claude"],
            "provider": "claude",
            "reason": "preferred_by_user",
            "from_cache": True,
            "gateway_used": True,
        }

    def fail_direct(*_args, **_kwargs):
        raise AssertionError("direct CLI should not be used when Fusion Gate succeeds")

    bridge._invoke_acp_via_fusion_gate = fake_gate  # type: ignore[method-assign]
    bridge._invoke_acp_direct_cli = fail_direct  # type: ignore[method-assign]

    status, _, payload = post_json(
        f"{base_url}/executeCommand",
        {
            "command": "acp_deepthink",
            "args": [
                {
                    "prompt": "lane contract の不足を洗って",
                    "runtime": "claude",
                    "model": "sonnet",
                    "timeout": 18,
                }
            ],
        },
    )

    assert status == 200
    assert payload["gateway"]["used"] is True
    assert payload["gateway"]["provider"] == "claude"
    assert payload["gateway"]["fromCache"] is True
    assert seen["runtime"] == "claude"
    assert seen["model"] == "sonnet"
    assert "CBF Protocol" in seen["prompt"]
    assert "PCC Protocol" in seen["prompt"]


def test_execute_command_falls_back_to_direct_cli_when_fusion_gate_fails(bridge_server):
    bridge, _, base_url = bridge_server
    bridge.use_fusion_gate_for_acp = True
    bridge.fusion_gate_cli_fallback = True
    seen = {}

    def fail_gate(*_args, **_kwargs):
        raise BRIDGE.BackendError("Fusion Gate unavailable")

    def fake_direct(runtime, prompt, model, timeout):
        seen.update({"runtime": runtime, "prompt": prompt, "model": model, "timeout": timeout})
        return {
            "text": "Specifically the missing issue is timeout handling on the fallback lane.",
            "exit_code": 0,
            "elapsed": 0.7,
            "command": ["fake-cli", runtime],
            "provider": runtime,
            "reason": "direct_cli",
            "from_cache": False,
            "gateway_used": False,
        }

    bridge._invoke_acp_via_fusion_gate = fail_gate  # type: ignore[method-assign]
    bridge._invoke_acp_direct_cli = fake_direct  # type: ignore[method-assign]

    status, _, payload = post_json(
        f"{base_url}/executeCommand",
        {
            "command": "acp_deepsearch",
            "args": [
                {
                    "prompt": "fallback lane の欠点を探して",
                    "runtime": "gemini",
                    "model": "standard",
                    "timeout": 19,
                }
            ],
        },
    )

    assert status == 200
    assert payload["gateway"]["used"] is False
    assert payload["gateway"]["provider"] == "gemini"
    assert seen["runtime"] == "gemini"
    assert seen["model"] == "gemini-2.5-pro"
    assert "CBF Protocol" in seen["prompt"]
