import logging
import select
import socket
import sys
import threading


local_host = "127.0.0.1"
local_port = 8080
max_conn = 10
buffer_size = 4096
proxy_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
domains = {}

def start_proxy():
    proxy_socket.bind((local_host, local_port))
    proxy_socket.listen(max_conn)
    logging.info("Proxy started, listening at %s:%d" % (local_host, local_port))

    while True:
        (conn, addr) = proxy_socket.accept()
        data = conn.recv(buffer_size)
        ConnectionThread(conn, data, addr).start()

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

    def run(self):
        if self.server is None:
            return

        self.server_socket.connect((self.server, self.port))

        logging.info("Connection to %s:%d requested" % (self.server, self.port))

        tld_index = self.server.rfind('.')
        tld = self.server[tld_index:]
        head = self.server[:tld_index]
        sld_index = head.rfind('.')
        sld = head[sld_index + 1:]
        domain = sld + tld

        if domain in domains:
            (usage, limit) = domains[domain]
            if usage >= limit:
                self.client_socket.send(b"HTTP/1.1 413 Usage over limit\r\n\r\n")
                self.close_connection()
                return
            usage += len(self.data) / 1024
            print(usage, limit)
            domains[domain] = (usage, limit)

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
        logging.info("Connection to %s:%d closed" % (self.server, self.port))

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
                else:
                    self.client_socket.send(data)

if __name__ == "__main__":
    logging.basicConfig(level=logging.DEBUG, format="[%(asctime)s] %(message)s", datefmt='%m/%d/%Y %H:%M:%S')
    try:
        while True:
            print('Enter "add" to start tracking a domain\'s usage, or "start" to start the proxy.')
            input_str = input().strip().lower()

            if input_str == "start":
                start_proxy()
                break

            if input_str == "add":
                print("Please enter the domain you'd like to track. Example: facebook.com")
                domain = input().strip().lower()
                print("Please enter the maximum amount of traffic to allow the domain (in MB).")
                limit = input().strip()
                while not limit.isdecimal():
                    print("Please enter a valid integer.")
                    limit = input().strip()
                limit = int(limit)
                domains[domain] = (0, limit * 1024)
                print("%s has been added to the list of tracked deomains, with a limit of %d MB." % (domain, limit))

            else:
                print("Error: invalid command.")
    except KeyboardInterrupt:
        logging.info("Execution ended by user, shutting down all active threads...")
