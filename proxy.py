import logging
import select
import socket
import sys
import threading


local_host = "127.0.0.1"
local_port = 8080
max_conn = 10
buffer_size = 4096
client_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)

def start_proxy():
    client_socket.bind((local_host, local_port))
    client_socket.listen(max_conn)
    logging.info("Proxy started, listening at %s:%d" % (local_host, local_port))

    while True:
        (conn, addr) = client_socket.accept()
        data = conn.recv(buffer_size)
        ConnectionThread(conn, data, addr).start()

def server_info(data):
    if len(data) == 0:
        return None

    url = data.decode('latin-1').split(' ')[1]

    http_pos = url.find("://")
    if http_pos != -1:
        url = url[http_pos + 3:]

    port_pos = url.find(":")

    webserver_pos = url.find("/")
    if webserver_pos == -1:
        webserver_pos = len(url)
    server = ""
    port = 80
    server = url[:webserver_pos]
    if port_pos != -1:
        try:
            port = int((url[port_pos + 1:])[:webserver_pos - port_pos - 1])
            server = url[:port_pos]
        except ValueError:
            with open('error.log', 'a') as f:
                f.write("VALUE ERROR\n")
                f.write(url.decode('latin-1') + '\n')
    return (server, port)



class ConnectionThread(threading.Thread):
    def __init__(self, conn, data, addr):
        super().__init__()
        self.client_socket = conn
        self.data = data
        self.addr = addr
        self.server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)

    def run(self):
        info = server_info(self.data)
        if info is None:
            return

        (server, port) = info
        self.server_socket.connect((server, port))

        logging.info("Connection to %s:%d requested" % (server, port))

        if self.data[:7] == b"CONNECT":
            self.client_socket.send(b"HTTP/1.0 200 Connection established\r\n\r\n")
            self.exchange()
        else:
            self.server_socket.send(self.data)
            self.exchange()
        logging.info("Connection to %s:%d closed" % (server, port))

    def exchange(self):
        sockets = [self.client_socket, self.server_socket]
        exit_flag = False
        while not exit_flag:
            (recv, _, error) = select.select(sockets, [], sockets, 5)
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
        start_proxy()
    except KeyboardInterrupt:
        logging.info("Execution ended by user, shutting down all active threads...")
