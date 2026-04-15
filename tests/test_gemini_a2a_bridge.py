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


def test_agent_card_advertises_http_json_and_three_skills(bridge_server):
    _, _, base_url = bridge_server

    status, _, payload = get_json(f"{base_url}/.well-known/agent-card.json")

    assert status == 200
    assert payload["preferredTransport"] == "HTTP+JSON"
    assert payload["additionalInterfaces"][0]["transport"] == "JSONRPC"
    assert len(payload["skills"]) == 3


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
