import datetime
import logging
import select
import socket
import sys
import threading


local_host = "127.0.0.1"
local_port = 8080
max_conn = 20
buffer_size = 4096
proxy_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
usages = {}
limits = {}
proxy_thread = None

class ListenThread(threading.Thread):
    def __init__(self):
        super().__init__()
        self.proxy_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.proxy_running = True

    def run(self):
        self.proxy_socket.bind((local_host, local_port))
        self.proxy_socket.listen(max_conn)
        logging.info("Proxy started, listening at %s:%d" % (local_host, local_port))

        while self.proxy_running:
            (conn, addr) = self.proxy_socket.accept()
            if not self.proxy_running:
                break
            data = conn.recv(buffer_size)
            ConnectionThread(conn, data, addr).start()
        self.proxy_socket.close()

    def stop_proxy(self):
        self.proxy_running = False
        try:
            socket.socket().connect((local_host, local_port))
        except:
            pass

def server_info(data):
    if len(data) == 0:
        return (None, None, None)

    url = data.decode('latin-1').split(' ')[1]
    port = 80
    server = url
    path = ""

    # strip protocol from URL
    http_pos = url.find("://")
    if http_pos != -1:
        url = url[http_pos + 3:]
        if url[:http_pos].lower().find("https") != -1:
            port = 443

    # get port number
    port_pos = url.find(":")
    if port_pos != -1:
        server = url[:port_pos]
        port = int(url[port_pos + 1:])

    # get relative path
    path_pos = url.find("/")
    if path_pos != -1:
        server = url[:path_pos]
        path = url[path_pos:port_pos]

    return (server, port, path)

class ConnectionThread(threading.Thread):
    def __init__(self, conn, data, addr):
        super().__init__()
        self.client_socket = conn
        self.data = data
        self.addr = addr
        self.server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        (self.server, self.port, self.path) = server_info(self.data)
        self.domain = parse_domain(self.server)

    def run(self):
        if self.server is None:
            return

        try:
            self.server_socket.connect((self.server, self.port))
        except socket.gaierror:
            print("Attempted to connect to: " + self.server)
            return

        logging.debug("Connection to %s:%d requested" % (self.server, self.port))

        if self.domain not in usages:
            usages[self.domain] = 0

        if self.domain in limits:
            limit = limits[self.domain]
            usage = usages[self.domain]
            if usage >= limit:
                self.client_socket.send(b"HTTP/1.1 413 Usage over limit\r\n\r\n")
                self.close_connection()
                return
            usage += len(self.data) / 1024
            usages[self.domain] = usage

        if self.data[:7] == b"CONNECT":
            self.client_socket.send(b"HTTP/1.1 200 Connection established\r\n\r\n")
            self.exchange()
        else:
            (method, tail) = self.parse_request()
            self.server_socket.send(b"%s %s %s" % (method, bytes(self.path, encoding='latin-1'), tail))
            self.exchange()
            self.close_connection()

    def close_connection(self):
        self.client_socket.close()
        self.server_socket.close()
        logging.debug("Connection to %s:%d closed" % (self.server, self.port))

    def parse_request(self):
        split_str = self.data.decode('latin-1').split(' ', maxsplit=2)
        return (bytes(split_str[0], encoding='latin-1'), bytes(split_str[2], encoding='latin-1'))

    def exchange(self):
        sockets = [self.client_socket, self.server_socket]
        exit_flag = False
        while not exit_flag:
            (recv, _, error) = select.select(sockets, [], sockets, 15)
            if len(recv) == 0 or error:
                break
            for sock in recv:
                data = sock.recv(buffer_size)
                if len(data) == 0:
                    exit_flag = True
                if sock is self.client_socket:
                    self.server_socket.send(data)
                    usages[self.domain] += len(data) / 1024
                else:
                    self.client_socket.send(data)
                    usages[self.domain] += len(data) / 1024

def reset_usage():
    usages = {}
    timer = threading.Timer(secs_left_in_day(), reset_usage)
    timer.start()

def secs_left_in_day():
    now = datetime.datetime.now()
    tomorrow = now + datetime.timedelta(days=1)
    delta =  datetime.datetime.combine(tomorrow, datetime.time.min) - now
    return delta.seconds

def parse_domain(url):
    if url is None:
        return None
    tld_index = url.rfind('.')
    tld = url[tld_index:]
    head = url[:tld_index]
    sld_index = head.rfind('.')
    sld = head[sld_index + 1:]
    domain = sld + tld
    return domain

def sort_usages(usages):
    return sorted(usages.items(), key=lambda x:x[1], reverse=True)

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="[%(asctime)s] %(message)s", datefmt='%m/%d/%Y %H:%M:%S')
    proxy_thread = None
    try:
        while True:
            print('Enter "add" to start tracking a domain\'s usage, or "start"/"stop" to start or stop the proxy server.')
            input_str = input().strip().lower()

            if input_str == "start":
                if proxy_thread is None:
                    timer = threading.Timer(secs_left_in_day(), reset_usage)
                    timer.start()
                    proxy_thread = ListenThread()
                    proxy_thread.start()
                else:
                    print("Error: proxy is already running.")

            elif input_str == "stop":
                if proxy_thread is not None:
                    proxy_thread.stop_proxy()
                    proxy_thread = None

            elif input_str == "usage":
                print(sort_usages(usages))

            elif input_str == "add":
                print("Please enter the domain you'd like to track. Example: facebook.com")
                domain = input().strip().lower()
                print("Please enter the maximum amount of traffic to allow the domain (in MB).")
                limit = input().strip()
                while not limit.isdecimal():
                    print("Please enter a valid integer.")
                    limit = input().strip()
                limit = int(limit)
                limits[domain] = limit * 1024
                print("%s has been added to the list of tracked domains, with a limit of %d MB." % (domain, limit))

            else:
                print("Error: invalid command.")
    except KeyboardInterrupt:
        logging.info("Execution ended by user, shutting down all active threads...")
        timers = [t for t in threading.enumerate() if type(t) == threading.Timer]
        for timer in timers:
            timer.cancel()
        if proxy_thread is not None:
            proxy_thread.stop_proxy()
