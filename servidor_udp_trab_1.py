"""
Protocolo: GET filename [droplist] / RETR filename seq1,seq2,...
Cabeçalho por segmento: struct.pack('!IIHIB', seq, total, payload_len, crc32, flags)
flags: 0=data, 1=EOF, 2=ERROR (payload contains error message)
"""

import socket
import struct
import os
import time
import binascii

PAYLOAD_SIZE = 1024  # bytes of file data per UDP packet
HDR_FMT = "!IIHIB"   # seq(4), total(4), payload_len(2), crc32(4), flags(1)
HDR_SIZE = struct.calcsize(HDR_FMT)
SLEEP_BETWEEN_SENDS = 0.001

class UDPFileServer:
    def __init__(self):
        self.host = "0.0.0.0"
        self.port = 12000
        self.directory = r"C:/Users/Lucas/redes_utfpr/trab_1"
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.bind((self.host, self.port))
        print(f"[Server] Listening on {self.host}:{self.port}, serving dir: {self.directory}")
        self.start()

    def start(self):
        try:
            while True:
                data, client = self.sock.recvfrom(4096)
                text = data.decode(errors="ignore").strip()
                print(f"[Server] Received from {client}: {text}")
                # Handle request in a thread so server can continue listening
                # t = threading.Thread(target=self.handle_request, args=(text, client))
                # t.daemon = True
                # t.start()
                self.handle_request(text, client)
        except KeyboardInterrupt:
            print("\n[Server] Shutting down.")
        finally:
            self.sock.close()

    def handle_request(self, text, client_addr):
        # Request formats supported:
        # GET filename [droplist]   (droplist is ignored by server; for client-only simulation)
        # RETR filename seq1,seq2,...
        parts = text.split()
        if len(parts) < 2:
            self.send_error(client_addr, "Invalid request format")
            return

        cmd = parts[0].upper()
        if cmd == "GET":
            filename = parts[1]
            self.send_file(client_addr, filename)
        elif cmd == "RETR":
            # Expect: RETR filename seq1,seq2,...
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
        header = struct.pack(HDR_FMT, 0, 0, len(payload), crc, 2)
        packet = header + payload
        self.sock.sendto(packet, client_addr)
        print(f"[Server] Sent ERROR to {client_addr}: {msg}")

    def send_file(self, client_addr, filename):
        path = os.path.join(self.directory, filename)
        if not os.path.isfile(path):
            self.send_error(client_addr, "File not found")
            return

        file_size = os.path.getsize(path)
        total_segments = (file_size + PAYLOAD_SIZE - 1) // PAYLOAD_SIZE
        print(f"[Server] Sending '{filename}' ({file_size} bytes) in {total_segments} segments to {client_addr}")

        with open(path, "rb") as f:
            seq = 1
            while True:
                chunk = f.read(PAYLOAD_SIZE)
                if not chunk:
                    break
                crc = binascii.crc32(chunk) & 0xffffffff
                header = struct.pack(HDR_FMT, seq, total_segments, len(chunk), crc, 0)
                packet = header + chunk
                self.sock.sendto(packet, client_addr)
                seq += 1
                time.sleep(SLEEP_BETWEEN_SENDS)

        # send EOF packet (no payload, flags=1)
        header = struct.pack(HDR_FMT, 0, total_segments, 0, 0, 1)
        self.sock.sendto(header, client_addr)
        print(f"[Server] Finished sending '{filename}' to {client_addr} (EOF)")

    def retransmit_segments(self, client_addr, filename, seqs):
        path = os.path.join(self.directory, filename)
        if not os.path.isfile(path):
            self.send_error(client_addr, "File not found")
            return

        file_size = os.path.getsize(path)
        total_segments = (file_size + PAYLOAD_SIZE - 1) // PAYLOAD_SIZE
        print(f"[Server] RETR request for '{filename}' seqs={seqs} to {client_addr}")

        with open(path, "rb") as f:
            for seq in seqs:
                if seq < 1 or seq > total_segments:
                    # skip invalid seq numbers (could also send an error)
                    print(f"[Server] Ignoring invalid seq {seq}")
                    continue
                offset = (seq - 1) * PAYLOAD_SIZE
                f.seek(offset)
                chunk = f.read(PAYLOAD_SIZE)
                crc = binascii.crc32(chunk) & 0xffffffff
                header = struct.pack(HDR_FMT, seq, total_segments, len(chunk), crc, 0)
                packet = header + chunk
                self.sock.sendto(packet, client_addr)
                time.sleep(SLEEP_BETWEEN_SENDS)
        # After retransmits, send EOF to mark end of this batch
        header = struct.pack(HDR_FMT, 0, total_segments, 0, 0, 1)
        self.sock.sendto(header, client_addr)
        print(f"[Server] Finished RETR batch for '{filename}' to {client_addr}")

if __name__ == "__main__":
    server = UDPFileServer()
    #server.start()
