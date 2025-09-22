import socket
import struct
import argparse
import binascii
import os

class UDPFileClient:
    def __init__(self, server_ip, server_port):
        self.server = (server_ip, server_port)
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.hdr_fmt = "!IIHIB"
        self.hdr_size = struct.calcsize(self.hdr_fmt)
        self.timeout = 2.0
        self.payload_size = 65000
        self.recv_buffer = 65536
        self.sock.settimeout(self.timeout)
        self.save_dir = r"C:/Users/Lucas/redes_utfpr/trab_1"
        self.filename = None
        self.total_segments = None
        self.segments = {}
        self.crc_ok = {}
        print(f"[Client] Server set to {self.server}")

    def send_request(self, text):
        self.sock.sendto(text.encode(), self.server)
        print(f"[Client] Sent request: {text}")

    def receive_file_cycle(self, drop_set=None):
        while True:
            try:
                data, _ = self.sock.recvfrom(self.recv_buffer)
            except socket.timeout:
                break
            if len(data) < self.hdr_size:
                continue

            seq, total, payload_len, crc_recv, flags = struct.unpack(self.hdr_fmt, data[:self.hdr_size])
            payload = data[self.hdr_size:self.hdr_size+payload_len] if payload_len > 0 else b""

            if flags == 2:
                msg = payload.decode(errors="ignore")
                print(f"[Client] Server ERROR: {msg}")
                return

            if flags == 1:
                self.total_segments = total if self.total_segments is None else self.total_segments
                print("[Client] EOF packet received")
                continue

            if drop_set and seq in drop_set:
                print(f"[Client] (SIMULATED DROP) Dropping seq {seq}")
                continue

            computed_crc = binascii.crc32(payload) & 0xffffffff
            good = (computed_crc == crc_recv)
            self.segments[seq] = payload
            self.crc_ok[seq] = good
            self.total_segments = total if self.total_segments is None else self.total_segments

            if not good:
                print(f"[Client] Segment {seq} CRC MISMATCH")
            else:
                print(f"[Client] Segment {seq} received OK")

    def get_missing_or_corrupted(self):  
        if not self.total_segments:
            return []
        missing = []
        for s in range(1, self.total_segments+1):
            if s not in self.segments or not self.crc_ok.get(s, False):
                missing.append(s)
        return missing

    def assemble_and_save(self):
        if not self.total_segments or not self.filename:
            print("[Client] Not able to build file: missing data.")
            return False

        missing = self.get_missing_or_corrupted()
        if missing:
            print(f"[Client] Stil missing packets: {missing}")
            return False

        out_path = os.path.join(self.save_dir, "Copy_" + self.filename)
        with open(out_path, "wb") as f:
            for s in range(1, self.total_segments+1):
                f.write(self.segments[s])
        print(f"[Client] File built and saved in {out_path}")
        return True
    
    def get_cmd(self, parts):
        if len(parts) < 2:
            print("[Client] Invalid entry")
            return False
        self.filename = parts[1]
        self.total_segments = None
        self.segments.clear()
        self.crc_ok.clear()
        drop_set = set()
        if len(parts) >= 3:
            try:
                drop_set = set(int(x) for x in parts[2].split(",") if x.strip())
                print(f"[Client] Simulating drops in: {sorted(drop_set)}")
            except ValueError:
                print("[Client] Invalid list, ignoring drops")

        self.send_request(f"GET {self.filename}")
        self.receive_file_cycle(drop_set)
        print(f"[Client] GET done. Missing packets: {self.get_missing_or_corrupted()}")
        self.assemble_and_save()
        return True

    def retr_cmd(self, parts):
        if len(parts) < 3:
            print("[Client] Invalid entry")
            return False
        fname = parts[1]
        if self.filename != fname:
            print(f"[Client] You asked to retrie from {fname}, but the current file is {self.filename}")
            return False

        if parts[2].lower() == "all":
            seqs = self.get_missing_or_corrupted()
        else:
            try:
                seqs = [int(x) for x in parts[2].split(",") if x.strip()]
            except ValueError:
                print("[Client] Invalid list")
                return False

        if not seqs:
            print("[Client] No packet to retrieve")
            return False

        retr_msg = f"RETR {fname} " + ",".join(str(s) for s in seqs)
        self.send_request(retr_msg)
        self.receive_file_cycle()
        print(f"[Client] RETR done. Stil missing: {self.get_missing_or_corrupted()}")
        self.assemble_and_save()
        return True

    def interactive(self):
        while True:
            line = input("Type: GET filename [drops] or RETR filename [drops] | 'all' or 'quit' to exit\n>> ").strip()
            if not line:
                continue
            if line.lower() == "quit":
                break

            parts = line.split()
            cmd = parts[0].upper()

            if cmd == "GET":
                if not self.get_cmd(parts):
                    continue

            elif cmd == "RETR":
                if not self.retr_cmd(parts):
                    continue
                
            else:
                print("[Client] Unknown command")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="UDP File Client")
    parser.add_argument("--server-ip", required=True, help="UDP server ID")
    parser.add_argument("--server-port", type=int, help="UDP server door")
    args = parser.parse_args()

    client = UDPFileClient(args.server_ip, args.server_port)
    try:
        client.interactive()
    except KeyboardInterrupt:
        print("\n[Client] Exiting")
    finally:
        client.sock.close()

