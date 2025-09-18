"""
UDP File Client (orientado a objetos)
Uso: python client.py --server-ip <ip> --server-port <port>
O cliente solicita: GET filename [droplist]
Exemplo de GET com simulação de perda (o cliente vai "dropar" os segmentos 3,7,12 quando recebê-los):
GET abc.ext 3,7,12

Para pedir retransmissão de segmentos:
RETR filename 3,7,12
RETR filename all
"""

import socket
import struct
import argparse
import binascii
import os

HDR_FMT = "!IIHIB"
HDR_SIZE = struct.calcsize(HDR_FMT)
TIMEOUT = 2.0
PAYLOAD_SIZE = 1024
RECV_BUFFER = 65536

class UDPFileClient:
    def __init__(self, server_ip, server_port, save_dir="."):
        self.server = (server_ip, server_port)
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.settimeout(TIMEOUT)
        self.save_dir = save_dir
        # armazenamento entre comandos
        self.filename = None
        self.total_segments = None
        self.segments = {}      # seq -> bytes
        self.crc_ok = {}        # seq -> bool
        print(f"[Client] Server set to {self.server}")

    def send_request(self, text):
        self.sock.sendto(text.encode(), self.server)
        print(f"[Client] Sent request: {text}")

    def receive_file_cycle(self, drop_set=None):
        """
        Recebe segmentos até timeout ou EOF.
        Atualiza self.segments e self.crc_ok.
        """
        while True:
            try:
                data, _ = self.sock.recvfrom(RECV_BUFFER)
            except socket.timeout:
                break
            if len(data) < HDR_SIZE:
                continue

            seq, total, payload_len, crc_recv, flags = struct.unpack(HDR_FMT, data[:HDR_SIZE])
            payload = data[HDR_SIZE:HDR_SIZE+payload_len] if payload_len > 0 else b""

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

    def interactive(self):
        print("Type: GET filename [drops] or RETR filename [drops] | 'all' or 'quit' to exit")
        drop_set = set()

        while True:
            line = input(">> ").strip()
            if not line:
                continue
            if line.lower() == "quit":
                break

            parts = line.split()
            cmd = parts[0].upper()

            if cmd == "GET":
                if len(parts) < 2:
                    print("Type: GET filename [drops]")
                    continue
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
                print(f"[Client] GET terminou. Pacotes faltando: {self.get_missing_or_corrupted()}")

            elif cmd == "RETR":
                if len(parts) < 3:
                    print("Type: RETR filename [drops] | all")
                    continue
                fname = parts[1]
                if self.filename != fname:
                    print(f"[Client] You asked to retrie from {fname}, but the current file is {self.filename}")
                    continue

                if parts[2].lower() == "all":
                    seqs = self.get_missing_or_corrupted()
                else:
                    try:
                        seqs = [int(x) for x in parts[2].split(",") if x.strip()]
                    except ValueError:
                        print("[Client] Invalid list")
                        continue

                if not seqs:
                    print("[Client] No packet to retrieve")
                    continue

                retr_msg = f"RETR {fname} " + ",".join(str(s) for s in seqs)
                self.send_request(retr_msg)
                self.receive_file_cycle()
                print(f"[Client] RETR done. Stil missing: {self.get_missing_or_corrupted()}")

                # tentar montar se completo
                self.assemble_and_save()

            else:
                print("Unknown command.")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="UDP File Client")
    parser.add_argument("--server-ip", required=True, help="IP do servidor UDP")
    parser.add_argument("--server-port", type=int, help="Porta do servidor UDP")
    args = parser.parse_args()

    client = UDPFileClient(args.server_ip, args.server_port, save_dir=args.save_dir)
    try:
        client.interactive()
    except KeyboardInterrupt:
        print("\n[Client] Exiting")
    finally:
        client.sock.close()

