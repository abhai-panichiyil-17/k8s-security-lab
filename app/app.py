from http.server import HTTPServer, BaseHTTPRequestHandler

class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"Flask API - Zero Trust Backend")

    def log_message(self, format, *args):
        pass

if __name__ == "__main__":
    print("Starting mock Flask API on port 5000")
    HTTPServer(("", 5000), Handler).serve_forever()
