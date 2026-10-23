"""Check real LSP initialization and symbols, not just executable names or versions."""
import argparse
import json
import os
from pathlib import Path
import queue
import subprocess
import tempfile
import threading
import time


class Client:
    def __init__(self, command, folder):
        self.errors = tempfile.TemporaryFile()
        try:
            self.process = subprocess.Popen(command, cwd=folder, stdin=subprocess.PIPE,
                                            stdout=subprocess.PIPE, stderr=self.errors)
        except Exception:
            self.errors.close()
            raise
        self.messages = queue.Queue()
        self.sequence = 0
        self.reader = threading.Thread(target=self.read, daemon=True)
        self.reader.start()

    def read(self):
        try:
            while True:
                headers = {}
                while True:
                    line = self.process.stdout.readline()
                    if not line:
                        raise EOFError("language server closed stdout")
                    if line == b"\r\n":
                        break
                    key, value = line.decode("ascii").split(":", 1)
                    headers[key.lower()] = value.strip()
                length = int(headers["content-length"])
                if not 0 < length < 10 * 1024 * 1024:
                    raise ValueError("invalid LSP message length")
                body = self.process.stdout.read(length)
                if len(body) != length:
                    raise EOFError("incomplete LSP message")
                self.messages.put(json.loads(body))
        except Exception as error:
            self.messages.put(error)

    def send(self, message):
        body = json.dumps(dict(jsonrpc="2.0", **message)).encode()
        self.process.stdin.write(f"Content-Length: {len(body)}\r\n\r\n".encode() + body)
        self.process.stdin.flush()

    def request(self, method, params=None):
        self.sequence += 1
        identifier = self.sequence
        message = {"id": identifier, "method": method}
        if params is not None:
            message["params"] = params
        self.send(message)
        deadline = time.monotonic() + 60
        while True:
            message = self.messages.get(timeout=max(0.01, deadline - time.monotonic()))
            if isinstance(message, Exception):
                raise message
            if message.get("id") == identifier and "method" not in message:
                if "error" in message:
                    raise RuntimeError(str(message["error"]))
                return message.get("result")
            if "id" in message and "method" in message:
                if message["method"] == "workspace/configuration":
                    result = [None for _ in message.get("params", {}).get("items", [])]
                else:
                    result = None
                self.send({"id": message["id"], "result": result})
            if time.monotonic() >= deadline:
                raise TimeoutError("language server response timed out")

    def close(self):
        if self.process.poll() is None:
            self.process.terminate()
        try:
            self.process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            self.process.kill()
            self.process.wait()
        self.process.stdin.close()
        self.process.stdout.close()
        self.reader.join(timeout=5)
        self.errors.close()


def check(language, legacy_server=None):
    commands = {"go": ["gopls", "serve"], "rust": ["rust-analyzer"],
                "python": ["pyright-langserver", "--stdio"],
                "typescript": ["tsc", "--lsp", "--stdio"],
                "typescript-legacy": [legacy_server, "--stdio"]}
    with tempfile.TemporaryDirectory(prefix="cx-lsp-") as directory:
        root = Path(directory)
        if language == "go":
            (root / "go.mod").write_text("module example.com/fixture\n\ngo 1.20\n")
            path, source, symbol = root / "main.go", 'package fixture\nfunc Hello() string { return "hello" }\n', "Hello"
        elif language == "rust":
            (root / "Cargo.toml").write_text('[package]\nname = "fixture"\nversion = "0.1.0"\nedition = "2021"\n')
            (root / "src").mkdir()
            path, source, symbol = root / "src/lib.rs", 'pub fn hello() -> u32 { 42 }\n', "hello"
        elif language == "python":
            path, source, symbol = root / "example.py", 'def hello() -> int:\n    return 42\n', "hello"
        else:
            path, source, symbol = root / "example.ts", 'export function hello(): number { return 42; }\n', "hello"
        path.write_text(source)
        client = Client(commands[language], root)
        try:
            initialized = client.request("initialize", {"processId": os.getpid(), "rootUri": root.as_uri(),
                                         "capabilities": {}, "workspaceFolders": [{"uri": root.as_uri(), "name": "fixture"}]})
            if not initialized.get("capabilities", {}).get("documentSymbolProvider"):
                raise RuntimeError("server does not advertise document symbols")
            client.send({"method": "initialized", "params": {}})
            client.send({"method": "textDocument/didOpen", "params": {"textDocument": {
                "uri": path.as_uri(), "languageId": "typescript" if language.startswith("typescript") else language,
                "version": 1, "text": source}}})
            symbols = client.request("textDocument/documentSymbol", {"textDocument": {"uri": path.as_uri()}})
            if not isinstance(symbols, list) or not any(item.get("name") == symbol for item in symbols):
                raise RuntimeError("server did not return the fixture function")
            client.request("shutdown")
            client.send({"method": "exit"})
            # Closing the transport lets the server's input reader observe EOF.
            client.process.stdin.close()
            if client.process.wait(timeout=10) != 0:
                client.errors.seek(0)
                details = client.errors.read().decode("utf-8", errors="replace")
                raise RuntimeError("server did not exit successfully: " + details[-2000:])
        finally:
            client.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--server", choices=("go", "rust", "python", "typescript", "typescript-legacy"))
    parser.add_argument("--legacy-server", help="Path to a project-local TypeScript 6 language server")
    args = parser.parse_args()
    if args.server == "typescript-legacy" and not args.legacy_server:
        parser.error("--server typescript-legacy requires --legacy-server")
    languages = [args.server] if args.server else ["go", "rust", "python", "typescript"]
    if not args.server and args.legacy_server:
        languages.append("typescript-legacy")
    failures = 0
    for number, language in enumerate(languages, 1):
        try:
            check(language, args.legacy_server)
        except Exception as error:
            failures += 1
            print(f"not ok {number} - {language} LSP: {type(error).__name__}: {error}", flush=True)
        else:
            print(f"ok {number} - {language} initializes and returns document symbols", flush=True)
    print(f"1..{len(languages)}", flush=True)
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
