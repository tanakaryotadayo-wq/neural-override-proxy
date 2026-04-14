import json
import urllib.request
import urllib.error
from io import BytesIO
from unittest.mock import patch, MagicMock

import pytest

from prompt_hook import NeuralOverrideProxy, INJECTED_SYSTEM_INSTRUCTION

# --- Mock Handlers ---

class MockHTTPServer:
    def __init__(self):
        self.server_address = ("127.0.0.1", 18008)

class MockRequest:
    def __init__(self, data=b"", headers=None, method="POST", path="/v1/models/gemini-1.5-pro:generateContent"):
        self.data = data
        self.headers = headers or {}
        self.method = method
        self.path = path
        
    def makefile(self, *args, **kwargs):
        return BytesIO(self.data)

class MockHandler(NeuralOverrideProxy):
    def __init__(self, request, client_address, server):
        self.responses = []
        self.headers_written = []
        self.wfile = BytesIO()
        self.rfile = BytesIO(request.data)
        self.headers = request.headers
        self.path = request.path
        
        # overriding the setup to prevent actual socket connection
        self.connection = MagicMock()
        self.client_address = client_address
        self.server = server

    def setup(self):
        pass
    def handle(self):
        pass
    def finish(self):
        pass

    def send_response(self, code, message=None):
        self.responses.append(code)

    def send_header(self, keyword, value):
        self.headers_written.append((keyword, value))

    def end_headers(self):
        pass


@pytest.fixture
def base_handler():
    data = b'{"contents": [{"role": "user", "parts": [{"text": "Hello"}]}]}'
    req = MockRequest(
        data=data,
        headers={"Content-Length": str(len(data)), "Content-Type": "application/json"}
    )
    handler = MockHandler(
        request=req,
        client_address=("127.0.0.1", 12345),
        server=MockHTTPServer()
    )
    return handler


# --- Tests for _inject_locale_constraint ---

def test_inject_locale_constraint_new(base_handler):
    """systemInstruction が存在しない場合の新規作成"""
    payload = {"contents": [{"role": "user", "parts": [{"text": "Hello"}]}]}
    base_handler._inject_locale_constraint(payload)
    
    assert "systemInstruction" in payload
    assert payload["systemInstruction"]["role"] == "system"
    assert payload["systemInstruction"]["parts"][0]["text"] == INJECTED_SYSTEM_INSTRUCTION

def test_inject_locale_constraint_existing(base_handler):
    """systemInstruction が既に存在する場合の追記動作"""
    payload = {
        "contents": [{"role": "user", "parts": [{"text": "Hello"}]}],
        "systemInstruction": {
            "role": "system",
            "parts": [{"text": "Original text"}]
        }
    }
    base_handler._inject_locale_constraint(payload)
    
    parts = payload["systemInstruction"]["parts"]
    assert len(parts) == 2
    assert parts[0]["text"] == "Original text"
    assert parts[1]["text"] == f"\n\n[COMPLIANCE OVERRIDE]: {INJECTED_SYSTEM_INSTRUCTION}"

def test_inject_locale_constraint_no_contents(base_handler):
    """contents がない場合は無反応"""
    payload = {"other": "data"}
    base_handler._inject_locale_constraint(payload)
    assert "systemInstruction" not in payload


# --- Tests for _validate_path ---

def test_validate_path_allowed(base_handler):
    """SSRF対策パスバリデーション（許可）"""
    base_handler.path = "/v1beta/models/gemini-pro:generateContent"
    assert base_handler._validate_path() is True
    
    base_handler.path = "/v1/models/gemini-pro:generateContent"
    assert base_handler._validate_path() is True
    
    base_handler.path = "/v1alpha/models/gemini-pro:generateContent"
    assert base_handler._validate_path() is True

def test_validate_path_blocked(base_handler):
    """SSRF ブロック対象パス"""
    base_handler.path = "/admin"
    assert base_handler._validate_path() is False
    
    base_handler.path = "/etc/passwd"
    assert base_handler._validate_path() is False
    
    base_handler.path = "http://example.com/v1/"
    assert base_handler._validate_path() is False


# --- Tests for _send_error ---

def test_send_error(base_handler):
    """統一エラーレスポンス"""
    base_handler._send_error(400, "invalid_json")
    
    assert base_handler.responses[0] == 400
    assert ("Content-Type", "application/json") in base_handler.headers_written
    
    body = base_handler.wfile.getvalue().decode("utf-8")
    assert json.loads(body) == {"error": "invalid_json"}


# --- Tests for do_OPTIONS ---

def test_do_options(base_handler):
    """CORS preflight"""
    base_handler.do_OPTIONS()
    
    assert base_handler.responses[0] == 200
    assert ("Access-Control-Allow-Origin", "*") in base_handler.headers_written


# --- Tests for _stream_response ---

def test_stream_response(base_handler):
    """SSE ストリーミングレスポンスの正しいチャンク転送"""
    mock_response = MagicMock()
    mock_response.read.side_effect = [b"chunk1", b"chunk2", b""]
    
    base_handler._stream_response(mock_response)
    
    output = base_handler.wfile.getvalue()
    expected = b"6\r\nchunk1\r\n6\r\nchunk2\r\n0\r\n\r\n"
    assert output == expected


# --- Tests for do_POST ---

@patch("prompt_hook.urllib.request.urlopen")
def test_do_post_success(mock_urlopen, base_handler):
    """do_POST() — メインハンドラの統合テスト"""
    mock_response = MagicMock()
    mock_response.status = 200
    mock_response.headers.items.return_value = [("Content-Type", "application/json")]
    mock_response.read.return_value = b'{"result": "ok"}'
    
    # Context manager setup
    mock_urlopen.return_value.__enter__.return_value = mock_response
    
    base_handler.do_POST()
    
    assert base_handler.responses[0] == 200
    assert base_handler.wfile.getvalue() == b'{"result": "ok"}'
    
    # Verify injected payload
    args, kwargs = mock_urlopen.call_args
    req = args[0]
    sent_payload = json.loads(req.data.decode("utf-8"))
    assert "systemInstruction" in sent_payload
    assert sent_payload["systemInstruction"]["parts"][0]["text"] == INJECTED_SYSTEM_INSTRUCTION

def test_do_post_invalid_path(base_handler):
    """SSRF ブロック対象パスのブロック"""
    base_handler.path = "/admin"
    base_handler.do_POST()
    
    assert base_handler.responses[0] == 403
    body = base_handler.wfile.getvalue().decode("utf-8")
    assert json.loads(body) == {"error": "forbidden_path"}

def test_do_post_invalid_content_type(base_handler):
    """非JSON Content-Type の拒否 (415)"""
    base_handler.headers = {"Content-Type": "text/plain"}
    base_handler.do_POST()
    
    assert base_handler.responses[0] == 415

def test_do_post_invalid_json(base_handler):
    """不正JSON (JSONDecodeError)"""
    base_handler.rfile = BytesIO(b"{invalid json")
    base_handler.headers = {"Content-Type": "application/json", "Content-Length": "13"}
    base_handler.do_POST()
    
    assert base_handler.responses[0] == 400
    body = base_handler.wfile.getvalue().decode("utf-8")
    assert json.loads(body) == {"error": "invalid_json"}

def test_do_post_empty_payload(base_handler):
    """空ペイロード / Content-Length=0"""
    base_handler.rfile = BytesIO(b"")
    base_handler.headers = {"Content-Type": "application/json", "Content-Length": "0"}
    base_handler.do_POST()
    
    assert base_handler.responses[0] == 400
    body = base_handler.wfile.getvalue().decode("utf-8")
    assert json.loads(body) == {"error": "invalid_json"}

@patch("prompt_hook.urllib.request.urlopen")
def test_do_post_streaming(mock_urlopen, base_handler):
    """SSE ストリーミングの処理テスト"""
    mock_response = MagicMock()
    mock_response.status = 200
    mock_response.headers.items.return_value = [("Content-Type", "text/event-stream")]
    mock_response.read.side_effect = [b"data: chunk\n\n", b""]
    
    mock_urlopen.return_value.__enter__.return_value = mock_response
    
    base_handler.do_POST()
    
    assert base_handler.responses[0] == 200
    assert ("Transfer-Encoding", "chunked") in base_handler.headers_written
    output = base_handler.wfile.getvalue()
    assert b"data: chunk\n\n" in output

@patch("prompt_hook.urllib.request.urlopen")
def test_do_post_timeout(mock_urlopen, base_handler):
    """タイムアウト発生時の504レスポンス"""
    mock_urlopen.side_effect = TimeoutError("timeout")
    
    base_handler.do_POST()
    
    assert base_handler.responses[0] == 504
    body = base_handler.wfile.getvalue().decode("utf-8")
    assert json.loads(body) == {"error": "upstream_timeout"}

@patch("prompt_hook.urllib.request.urlopen")
def test_do_post_http_error(mock_urlopen, base_handler):
    """上流エラーのプロキシ"""
    mock_error = urllib.error.HTTPError(
        url="http://test", code=503, msg="Service Unavailable", hdrs={}, fp=BytesIO(b"error body")
    )
    mock_urlopen.side_effect = mock_error
    
    base_handler.do_POST()
    
    assert base_handler.responses[0] == 503
    assert base_handler.wfile.getvalue() == b"error body"

@patch("prompt_hook.urllib.request.urlopen")
def test_do_post_general_error(mock_urlopen, base_handler):
    """一般エラー時の500レスポンス"""
    mock_urlopen.side_effect = RuntimeError("general error")
    
    base_handler.do_POST()
    
    assert base_handler.responses[0] == 500
    body = base_handler.wfile.getvalue().decode("utf-8")
    assert json.loads(body) == {"error": "proxy_error"}
