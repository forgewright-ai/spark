"""Serve the sales report over HTTP on the port the config names."""

import http.server
import json
import sys

from shopkit.report import read_rows, render


def load_config(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def main(argv):
    config = load_config(argv[1] if len(argv) > 1 else "config.json")
    host = config.get("host", "127.0.0.1")
    port = int(config["port"])
    rows = read_rows(config["sales_file"])

    class Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            body = render(rows).encode()
            self.send_response(200)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.end_headers()
            self.wfile.write(body)

    print("serving on %s:%d" % (host, port))
    http.server.HTTPServer((host, port), Handler).serve_forever()


if __name__ == "__main__":
    sys.exit(main(sys.argv))
