import socket
import os
import threading
import struct
import binascii
import time

class UDPFileServer:
    def __init__(self):
        self.host = "0.0.0.0"
        self.port = 12000
        self.directory = r"C:/Users/Lucas/redes_utfpr/trab_1"
        self.payload_size = 65000
        self.hdr_fmt = "!IIHIB"
        self.hdr_size = struct.calcsize(self.hdr_fmt)
        self.sleep_between_sends = 0.001
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.bind((self.host, self.port))
        print(f"[Server] Listening on {self.host}:{self.port}, serving dir: {self.directory}")
        self.start()

    def start(self):
        try:
            while True:
                data, client = self.sock.recvfrom(65536)
                text = data.decode(errors="ignore").strip()
                print(f"[Server] Received from {client}: {text}")
                t = threading.Thread(target=self.handle_request, args=(text, client))
                t.daemon = True
                t.start()
        except KeyboardInterrupt:
            print("\n[Server] Shutting down.")
        finally:
            self.sock.close()

    def handle_request(self, text, client_addr):
        parts = text.split()

        if len(parts) < 2:
            self.send_error(client_addr, "Invalid request format")
            return

        cmd = parts[0].upper()

        if cmd == "GET":
            filename = parts[1]
            self.send_file(client_addr, filename)

        elif cmd == "RETR":
            if len(parts) < 3:
                self.send_error(client_addr, "RETR requires filename and sequence list")
                return
            filename = parts[1]
            seq_list_str = parts[2]
            try:
                seqs = [int(s) for s in seq_list_str.split(",") if s.strip()]
                self.retransmit_segments(client_addr, filename, seqs)
            except ValueError:
                self.send_error(client_addr, "Invalid sequence list for RETR")
        
        else:
            self.send_error(client_addr, f"Unknown command: {cmd}")

    def send_error(self, client_addr, msg):
        payload = msg.encode()
        crc = binascii.crc32(payload) & 0xffffffff
        header = struct.pack(self.hdr_fmt, 0, 0, len(payload), crc, 2)
        packet = header + payload
        self.sock.sendto(packet, client_addr)
        print(f"[Server] Sent ERROR to {client_addr}: {msg}")

    def send_file(self, client_addr, filename):
        path = os.path.join(self.directory, filename)
        if not os.path.isfile(path):
            self.send_error(client_addr, "File not found")
            return

        file_size = os.path.getsize(path)
        total_segments = (file_size + self.payload_size - 1) // self.payload_size
        print(f"[Server] Sending '{filename}' ({file_size} bytes) in {total_segments} segments to {client_addr}")

        with open(path, "rb") as f:
            seq = 1
            while True:
                chunk = f.read(self.payload_size)
                if not chunk:
                    break
                crc = binascii.crc32(chunk) & 0xffffffff
                header = struct.pack(self.hdr_fmt, seq, total_segments, len(chunk), crc, 0)
                packet = header + chunk
                print(f"[Server] Packet no. {seq} | Sizes of hdr: {len(header)}, chunk: {len(chunk)}, packet: {len(packet)}")
                self.sock.sendto(packet, client_addr)
                seq += 1
                time.sleep(self.sleep_between_sends)

        header = struct.pack(self.hdr_fmt, 0, total_segments, 0, 0, 1)
        self.sock.sendto(header, client_addr)
        print(f"[Server] Finished sending '{filename}' to {client_addr} (EOF)")

    def retransmit_segments(self, client_addr, filename, seqs):
        path = os.path.join(self.directory, filename)
        if not os.path.isfile(path):
            self.send_error(client_addr, "File not found")
            return

        file_size = os.path.getsize(path)
        total_segments = (file_size + self.payload_size - 1) // self.payload_size
        print(f"[Server] RETR request for '{filename}' seqs={seqs} to {client_addr}")

        with open(path, "rb") as f:
            for seq in seqs:
                if seq < 1 or seq > total_segments:
                    print(f"[Server] Ignoring invalid seq {seq}")
                    continue
                offset = (seq - 1) * self.payload_size
                f.seek(offset)
                chunk = f.read(self.payload_size)
                crc = binascii.crc32(chunk) & 0xffffffff
                header = struct.pack(self.hdr_fmt, seq, total_segments, len(chunk), crc, 0)
                packet = header + chunk
                self.sock.sendto(packet, client_addr)
                time.sleep(self.sleep_between_sends)

        header = struct.pack(self.hdr_fmt, 0, total_segments, 0, 0, 1)
        self.sock.sendto(header, client_addr)
        print(f"[Server] Finished RETR batch for '{filename}' to {client_addr}")

if __name__ == "__main__":
    server = UDPFileServer()