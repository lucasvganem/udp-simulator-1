import socket
import argparse
import os
import struct
import zlib
import hashlib
import threading
import time

HDR_FMT = "!IIH I"  # seq (4), total (4), payload_len (2), crc32 (4)
HDR_SIZE = struct.calcsize(HDR_FMT)

def compute_md5(path):
    m = hashlib.md5()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            m.update(chunk)
    return m.hexdigest()

def make_segments(path, payload_size):
    filesize = os.path.getsize(path)
    total = (filesize + payload_size - 1) // payload_size
    with open(path, "rb") as f:
        for seq in range(total):
            chunk = f.read(payload_size)
            crc = zlib.crc32(chunk) & 0xffffffff
            hdr = struct.pack(HDR_FMT, seq, total, len(chunk), crc)
            yield seq, hdr + chunk

class UDPFileServer:
    def __init__(self, host="0.0.0.0", port=9000, folder=".", payload=1400, send_delay=0.000):
        self.addr = (host, port)
        self.folder = folder
        self.payload = payload
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.bind(self.addr)
        self.send_delay = send_delay
        print(f"[SERVER] listening on {host}:{port}, folder={folder}, payload={payload}")

        # store last requested transfer state so retransmissions can be served.
        # mapping: client_addr -> {'segments': {seq: bytes}, 'total': int}
        self.state = {}
        self.state_lock = threading.Lock()

    def handle_request(self, data, client_addr):
        text = data.decode(errors="ignore").strip()
        print(f"[REQ] from {client_addr}: {text}")
        if not text.startswith("GET "):
            self.sock.sendto(b"ERR 400 Invalid request", client_addr)
            return

        filename = text[4:].strip()
        path = os.path.join(self.folder, filename)
        if not os.path.isfile(path):
            msg = f"ERR 404 File not found"
            self.sock.sendto(msg.encode(), client_addr)
            print(f"[SERVER] {client_addr} -> {msg}")
            return

        filesize = os.path.getsize(path)
        md5hex = compute_md5(path)
        total = (filesize + self.payload - 1) // self.payload
        meta = f"META {filesize} {self.payload} {total} {md5hex}"
        self.sock.sendto(meta.encode(), client_addr)
        print(f"[SERVER] sent META to {client_addr}: {meta}")

        # prepare segments in memory (could stream; here we cache for retransmits)
        segments = {}
        with open(path, "rb") as f:
            for seq in range(total):
                chunk = f.read(self.payload)
                crc = zlib.crc32(chunk) & 0xffffffff
                hdr = struct.pack(HDR_FMT, seq, total, len(chunk), crc)
                pkt = hdr + chunk
                segments[seq] = pkt

        with self.state_lock:
            self.state[client_addr] = {'segments': segments, 'total': total}

        # send all segments sequentially
        print(f"[SERVER] start sending {total} segments to {client_addr}")
        for seq in range(total):
            pkt = segments[seq]
            self.sock.sendto(pkt, client_addr)
            # optional tiny delay to avoid flooding
            if self.send_delay:
                time.sleep(self.send_delay)
        print(f"[SERVER] finished initial send to {client_addr}")

    def handle_retrans(self, text, client_addr):
        # text example: RETR 3,7,12
        parts = text.split()
        if len(parts) < 2:
            self.sock.sendto(b"ERR 400 Bad RETR", client_addr)
            return
        seqs_str = parts[1]
        try:
            seqs = [int(s) for s in seqs_str.split(",") if s.strip() != ""]
        except ValueError:
            self.sock.sendto(b"ERR 400 Bad seq list", client_addr)
            return

        with self.state_lock:
            entry = self.state.get(client_addr)
        if not entry:
            self.sock.sendto(b"ERR 410 No active transfer", client_addr)
            return

        segments = entry['segments']
        sent = 0
        for seq in seqs:
            pkt = segments.get(seq)
            if pkt:
                self.sock.sendto(pkt, client_addr)
                sent += 1
                if self.send_delay:
                    time.sleep(self.send_delay)
        ack = f"RETR-OK {sent}"
        self.sock.sendto(ack.encode(), client_addr)
        print(f"[SERVER] retransmitted {sent} segments to {client_addr}")

    def serve_forever(self):
        print("[SERVER] ready")
        while True:
            data, client_addr = self.sock.recvfrom(65535)
            if not data:
                continue
            text = data.decode(errors="ignore").strip()
            if text.startswith("GET "):
                # spawn a thread to serve this request (so retrans can be processed concurrently)
                t = threading.Thread(target=self.handle_request, args=(data, client_addr), daemon=True)
                t.start()
            elif text.startswith("RETR "):
                # retrans request
                self.handle_retrans(text, client_addr)
            else:
                # could be a control / keep-alive / etc.
                self.sock.sendto(b"ERR 400 Unknown command", client_addr)

if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--host", default="0.0.0.0")
    ap.add_argument("--port", type=int, default=9000)
    ap.add_argument("--folder", default=".")
    ap.add_argument("--payload", type=int, default=1400, help="bytes payload per datagram")
    ap.add_argument("--send-delay", type=float, default=0.0, help="delay between datagrams (s)")
    args = ap.parse_args()

    server = UDPFileServer(host=args.host, port=args.port, folder=args.folder,
                           payload=args.payload, send_delay=args.send_delay)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n[SERVER] exiting")