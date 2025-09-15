# server.py
import socket
import struct
import os
import threading
import binascii

BASE_DIR = r"C:/Users/Lucas/redes_utfpr/trab_1"
SERVER_PORT = 12000
PAYLOAD_SIZE = 1024  # bytes per UDP payload
HDR_FMT = "!IIHI"    # seq (4), total (4), payload_len (2), crc32 (4)
HDR_SIZE = struct.calcsize(HDR_FMT)

sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
sock.bind(("0.0.0.0", SERVER_PORT))
print(f"[+] UDP server listening on port {SERVER_PORT}")

# Keep file segments in memory while serving RETR (could be large; ok for lab)
file_cache = {}  # key: (client_addr, filename) -> list of segment bytes (index 1..total)

def pack_segment(seq, total, payload_bytes):
    payload_len = len(payload_bytes)
    crc = binascii.crc32(payload_bytes) & 0xffffffff
    header = struct.pack(HDR_FMT, seq, total, payload_len, crc)
    return header + payload_bytes

def handle_request(data, client_addr):
    text = data.decode(errors="ignore").strip()
    parts = text.split()
    if not parts:
        return
    cmd = parts[0].upper()
    if cmd == "GET":
        if len(parts) < 2:
            sock.sendto(b"ERR GET sem nome de arquivo", client_addr)
            return
        filename = parts[1]
        filepath = os.path.join(BASE_DIR, filename)
        if not os.path.isfile(filepath):
            sock.sendto(b"ERR Arquivo nao encontrado", client_addr)
            print(f"[-] {client_addr} requested missing file {filename}")
            return

        # Read file and segment
        with open(filepath, "rb") as f:
            data_bytes = f.read()
        total = (len(data_bytes) + PAYLOAD_SIZE - 1) // PAYLOAD_SIZE
        segments = [None] * (total + 1)  # index by 1..total
        for i in range(total):
            start = i * PAYLOAD_SIZE
            chunk = data_bytes[start:start+PAYLOAD_SIZE]
            seg = pack_segment(i+1, total, chunk)
            segments[i+1] = seg

        # cache segments for possible retransmission
        file_cache[(client_addr, filename)] = segments

        # send all segments
        print(f"[+] Sending {filename} to {client_addr} in {total} segments")
        for i in range(1, total+1):
            sock.sendto(segments[i], client_addr)

        # send FIN
        fin_msg = f"FIN {total}".encode()
        sock.sendto(fin_msg, client_addr)
        print(f"[+] Sent FIN to {client_addr}")

    elif cmd == "RETR":
        # format RETR filename? or RETR seqlist? We'll accept "RETR filename 3,7,12" or "RETR 3,7,12"
        # For simplicity, if first argument doesn't contain comma, treat as filename; else use last GET'd filename stored.
        # We'll parse flexible forms:
        args = parts[1:]
        if not args:
            sock.sendto(b"ERR RETR sem argumentos", client_addr)
            return
        # Try to find cached (client_addr, filename) entry
        # Choose filename if provided
        if len(args) == 1 and "," in args[0]:
            seq_list_str = args[0]
            # try to find any cached file for this client
            candidate = None
            for (addr, fname) in file_cache.keys():
                if addr == client_addr:
                    candidate = fname
                    break
            if candidate is None:
                sock.sendto(b"ERR RETR sem contexto de arquivo", client_addr)
                return
            filename = candidate
        else:
            # maybe args[0] is filename and args[1] is seqlist
            if len(args) >= 2:
                filename = args[0]
                seq_list_str = args[1]
            else:
                # maybe only filename provided -> nothing to retransmit
                sock.sendto(b"ERR RETR formato invalido", client_addr)
                return

        key = (client_addr, filename)
        if key not in file_cache:
            sock.sendto(b"ERR RETR sem arquivo em cache", client_addr)
            return
        segments = file_cache[key]
        seqs = []
        for token in seq_list_str.split(","):
            token = token.strip()
            if not token:
                continue
            try:
                s = int(token)
                seqs.append(s)
            except:
                continue
        print(f"[+] RETR from {client_addr} for {filename}: {seqs}")
        for s in seqs:
            if 1 <= s < len(segments) and segments[s] is not None:
                sock.sendto(segments[s], client_addr)
        # optional: after retransmit, send ACK or FIN fragment; we'll send a small marker
        sock.sendto(b"RETR_DONE", client_addr)
    else:
        sock.sendto(b"ERR Comando desconhecido", client_addr)

def main_loop():
    while True:
        try:
            data, client_addr = sock.recvfrom(4096)
            # handle in new thread so server can receive other requests
            threading.Thread(target=handle_request, args=(data, client_addr), daemon=True).start()
        except KeyboardInterrupt:
            print("Shutting down server.")
            break

if __name__ == "__main__":
    main_loop()
