import socket
import argparse
import struct
import zlib
import hashlib
import time

HDR_FMT = "!IIH I"
HDR_SIZE = struct.calcsize(HDR_FMT)

def parse_meta(text):
    # META <tamanho_bytes> <tam_payload> <total_segs> <md5hex>
    parts = text.split()
    if parts[0] != "META": raise ValueError("Not META")
    filesize = int(parts[1])
    payload = int(parts[2])
    total = int(parts[3])
    md5hex = parts[4]
    return filesize, payload, total, md5hex

def compute_md5_bytes(chunks):
    m = hashlib.md5()
    for b in chunks:
        m.update(b)
    return m.hexdigest()

class UDPFileClient:
    def __init__(self, server_host, server_port, timeout=3.0, simulate_drop=set()):
        self.server = (server_host, server_port)
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.settimeout(timeout)
        self.simulate_drop = simulate_drop

    def request_file(self, filename, outpath):
        req = f"GET {filename}"
        self.sock.sendto(req.encode(), self.server)

        # wait for META
        try:
            data, _ = self.sock.recvfrom(65535)
        except socket.timeout:
            print("[CLIENT] timeout waiting for META")
            return False
        text = data.decode(errors="ignore")
        if text.startswith("ERR "):
            print("[CLIENT] server error:", text)
            return False
        if text.startswith("META "):
            filesize, payload, total, md5hex = parse_meta(text)
            print(f"[CLIENT] META received filesize={filesize} payload={payload} total={total} md5={md5hex}")
        else:
            print("[CLIENT] unexpected reply:", text)
            return False

        # prepare buffer
        received = {}  # seq -> bytes payload
        received_crc_ok = set()
        expected_total = total

        # receive segments until we have all (or until a certain max attempts)
        start_time = time.time()
        # first phase: receive initial batch; we'll collect until we hear nothing for some time
        while True:
            try:
                pkt, _ = self.sock.recvfrom(65535)
            except socket.timeout:
                print("[CLIENT] recv timeout (end of initial phase)")
                break
            # if this is an ASCII control message, handle it (server may send RETR-OK, etc.)
            if pkt.startswith(b"ERR") or pkt.startswith(b"RETR-OK"):
                try:
                    print("[CLIENT] ctrl:", pkt.decode())
                except:
                    pass
                continue
            if len(pkt) < HDR_SIZE:
                print("[CLIENT] malformed pkt (too small)")
                continue
            hdr = pkt[:HDR_SIZE]
            try:
                seq, total_in_hdr, payload_len, crc = struct.unpack(HDR_FMT, hdr)
            except struct.error:
                print("[CLIENT] bad header unpack")
                continue
            payload = pkt[HDR_SIZE:HDR_SIZE+payload_len]

            # Simulate drop?
            if seq in self.simulate_drop:
                print(f"[CLIENT] simulating drop of seq {seq}")
                continue

            # check crc
            calc = zlib.crc32(payload) & 0xffffffff
            if calc != crc:
                print(f"[CLIENT] CRC mismatch seq {seq} (got {hex(calc)} expected {hex(crc)})")
                # don't store corrupted segment
                continue
            # store
            received[seq] = payload
            received_crc_ok.add(seq)
            # progress print
            if len(received) % 50 == 0 or len(received) == total:
                print(f"[CLIENT] got {len(received)}/{total} segments")

            # early stop when all segments received
            if len(received) >= total:
                print("[CLIENT] all segments received")
                break

        # find missing sequences
        missing = [str(i) for i in range(total) if i not in received]
        if missing:
            print(f"[CLIENT] missing {len(missing)} segments, requesting retransmission")
            # request in batches (avoid very long message)
            batch_size = 200
            i = 0
            while i < len(missing):
                chunk = missing[i:i+batch_size]
                msg = "RETR " + ",".join(chunk)
                self.sock.sendto(msg.encode(), self.server)
                # wait for some retransmitted packets
                t0 = time.time()
                while time.time() - t0 < 2.0:  # listen short while for retransmits
                    try:
                        pkt, _ = self.sock.recvfrom(65535)
                    except socket.timeout:
                        break
                    if len(pkt) < HDR_SIZE:
                        continue
                    seq, total_in_hdr, payload_len, crc = struct.unpack(HDR_FMT, pkt[:HDR_SIZE])
                    payload = pkt[HDR_SIZE:HDR_SIZE+payload_len]
                    if seq in self.simulate_drop:
                        print(f"[CLIENT] simulating drop of seq {seq} (during retrans)")
                        continue
                    calc = zlib.crc32(payload) & 0xffffffff
                    if calc != crc:
                        print(f"[CLIENT] CRC mismatch on retrans seq {seq}")
                        continue
                    received[seq] = payload
                i += batch_size
                # recalc missing
                missing = [str(i) for i in range(total) if i not in received]
                if not missing:
                    break

        # final check
        missing_final = [i for i in range(total) if i not in received]
        if missing_final:
            print(f"[CLIENT] still missing {len(missing_final)} segments: {missing_final[:10]} ...")
            print("[CLIENT] transfer failed")
            return False

        # assemble file
        chunks = [received[i] for i in range(total)]
        md5_calc = compute_md5_bytes(chunks)
        if md5_calc != md5hex:
            print(f"[CLIENT] MD5 mismatch: got {md5_calc} expected {md5hex}")
            print("[CLIENT] transfer failed (corrupt)")
            return False

        # write output
        with open(outpath, "wb") as f:
            for c in chunks:
                f.write(c)
        print(f"[CLIENT] saved to {outpath}, {filesize} bytes, md5={md5_calc}")
        self.sock.sendto(b"DONE OK", self.server)
        return True

if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--server", required=True, help="server_ip:port")
    ap.add_argument("--file", required=True, help="nome do arquivo no servidor")
    ap.add_argument("--out", default="received.bin", help="arquivo de saida local")
    ap.add_argument("--timeout", type=float, default=2.0)
    ap.add_argument("--drop", default="", help="simula drop de segmentos: ex '3,7,12'")
    args = ap.parse_args()
    host, port = args.server.split(":")
    port = int(port)
    simulate_drop = set()
    if args.drop.strip():
        for s in args.drop.split(","):
            try:
                simulate_drop.add(int(s))
            except:
                pass

    client = UDPFileClient(host, port, timeout=args.timeout, simulate_drop=simulate_drop)
    ok = client.request_file(args.file, args.out)
    if ok:
        print("[CLIENT] transfer concluido com sucesso")
    else:
        print("[CLIENT] transfer falhou")
