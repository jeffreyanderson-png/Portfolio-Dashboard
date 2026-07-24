import urllib.parse as urlparse
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
import ssl
import os
import subprocess
import tempfile

class OAuthCallbackHandler(BaseHTTPRequestHandler):
    """
    Custom HTTP request handler to intercept the OAuth redirect from Schwab.
    """
    def do_GET(self):
        parsed_url = urlparse.urlparse(self.path)
        query_components = urlparse.parse_qs(parsed_url.query)
        
        if 'code' in query_components:
            auth_code = query_components['code'][0]
            
            self.send_response(200)
            self.send_header('Content-type', 'text/html')
            self.end_headers()
            
            html_content = """
            <!DOCTYPE html>
            <html>
            <head>
                <title>Authentication Successful</title>
                <style>
                    body { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif; display: flex; flex-direction: column; align-items: center; justify-content: center; height: 100vh; margin: 0; background-color: #f0f4f9; color: #1b1c1d; }
                    .container { background: white; padding: 40px; border-radius: 12px; box-shadow: 0 4px 12px rgba(0,0,0,0.1); text-align: center; }
                    h2 { color: #146c2e; margin-top: 0; }
                    p { color: #444746; line-height: 1.5; }
                    .close-msg { font-size: 0.9em; color: #747775; margin-top: 20px; }
                </style>
            </head>
            <body>
                <div class="container">
                    <h2>✅ Authentication Successful!</h2>
                    <p>The Pilot Portfolio HUD has successfully captured the authorization code.</p>
                    <p class="close-msg">You can securely close this tab and return to your dashboard.</p>
                </div>
                <script>
                    setTimeout(() => { window.close(); }, 3000);
                </script>
            </body>
            </html>
            """
            self.wfile.write(html_content.encode('utf-8'))
            
            self.server.auth_code = auth_code
            threading.Thread(target=self.server.shutdown, daemon=True).start()
            
        else:
            self.send_response(400)
            self.send_header('Content-type', 'text/html')
            self.end_headers()
            self.wfile.write(b"<h2>Authentication Failed</h2><p>No authorization code was found in the URL. Please try the login process again.</p>")
            
            threading.Thread(target=self.server.shutdown, daemon=True).start()

    def log_message(self, format, *args):
        pass


def generate_self_signed_cert(cert_path, key_path):
    """Generates a temporary self-signed certificate for local HTTPS testing."""
    print("Generating temporary self-signed SSL certificate for localhost...")
    
    # Check if we are on Windows and if Git's OpenSSL exists
    openssl_cmd = "openssl"
    if os.name == 'nt':
        git_openssl = r"C:\Program Files\Git\usr\bin\openssl.exe"
        if os.path.exists(git_openssl):
            openssl_cmd = git_openssl
            print(f"Using Windows Git OpenSSL at: {git_openssl}")

    try:
        subprocess.run([
            openssl_cmd, "req", "-x509", "-newkey", "rsa:2048", 
            "-keyout", key_path, "-out", cert_path, 
            "-days", "1", "-nodes", 
            "-subj", "/CN=127.0.0.1"
        ], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return True
    except FileNotFoundError:
        print(f"ERROR: OpenSSL not found at '{openssl_cmd}'. Cannot generate HTTPS certificate.")
        print("Please install OpenSSL or Git for Windows to enable automatic HTTPS redirects.")
        return False
    except subprocess.CalledProcessError as e:
        print(f"ERROR: Failed to generate certificate: {e}")
        return False

def capture_oauth_code(port: int = 8080, timeout: int = 120, use_https: bool = True) -> str:
    """
    Starts a temporary local server to catch the OAuth redirect.
    """
    server = HTTPServer(('127.0.0.1', port), OAuthCallbackHandler)
    server.auth_code = None 
    
    cert_file = None
    key_file = None
    
    if use_https:
        cert_fd, cert_file = tempfile.mkstemp(suffix=".crt")
        key_fd, key_file = tempfile.mkstemp(suffix=".key")
        os.close(cert_fd)
        os.close(key_fd)
        
        if generate_self_signed_cert(cert_file, key_file):
            context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
            context.load_cert_chain(certfile=cert_file, keyfile=key_file)
            server.socket = context.wrap_socket(server.socket, server_side=True)
        else:
            print("WARNING: Falling back to HTTP because cert generation failed.")
            use_https = False # Stop it from trying to delete files that were never made
    
    server_thread = threading.Thread(target=server.serve_forever, daemon=True)
    server_thread.start()
    
    server_thread.join(timeout=timeout)
    
    if server_thread.is_alive():
        server.shutdown()
        server_thread.join()
        
    if use_https:
        if cert_file and os.path.exists(cert_file):
            os.remove(cert_file)
        if key_file and os.path.exists(key_file):
            os.remove(key_file)
        
    return server.auth_code