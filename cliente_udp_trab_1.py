# client.py
import socket
import argparse
import struct
import binascii
import os
import time

HDR_FMT = "!IIHI"
HDR_SIZE = struct.calcsize(HDR_FMT)
PAYLOAD_SIZE = 1024
RECV_BUF = 65536
TIMEOUT = 3.0  # seconds to wait for packets after FIN


def parse_header_and_payload(packet):
    if len(packet) < HDR_SIZE:
        return None
    header = packet[:HDR_SIZE]
    seq, total, payload_len, crc = struct.unpack(HDR_FMT, header)
    payload = packet[HDR_SIZE:HDR_SIZE+payload_len]
    return seq, total, payload_len, crc, payload


def main():
    parser = argparse.ArgumentParser(description="UDP file client")
    parser.add_argument("--server-ip", required=True, help="UDP server IP")
    parser.add_argument("--server-port", required=False, type=int, default=12000, help="UDP server port")
    args = parser.parse_args()

    server_addr = (args.server_ip, args.server_port)
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.settimeout(5.0)

    print(f"[+] Cliente pronto. Conectando a {server_addr}")
    # Interactive loop for GET/RETR
    last_filename = None
    while True:
        cmd = input("Digite comando (ex: GET nome.ext 3,7,12 | quit): ").strip()
        if not cmd:
            continue
        if cmd.lower() == "quit":
            print("Saindo.")
            break
        if not cmd.upper().startswith("GET "):
            print("Por favor inicie com GET ...")
            continue

        # Send GET
        sock.sendto(cmd.encode(), server_addr)
        parts = cmd.split()
        # parse drop list if provided in GET line (simulate loss) -> only for initial GET
        drop_list = set()
        if len(parts) >= 3:
            drops = parts[2]
            for tok in drops.split(","):
                tok = tok.strip()
                if tok:
                    try:
                        drop_list.add(int(tok))
                    except:
                        pass

        # Determine filename
        filename = parts[1]
        last_filename = filename
        print(f"[+] Requisitando {filename} (simulate drop: {sorted(drop_list)})")

        # Prepare receive structures
        segments = {}   # seq -> payload bytes
        crc_ok = {}     # seq -> True/False
        expected_total = None
        got_fin = False

        # We'll only simulate drops during this GET receive phase
        in_get_phase = True

        # Receive loop: collect until FIN and timeout
        while True:
            try:
                data, addr = sock.recvfrom(RECV_BUF)
            except socket.timeout:
                if got_fin:
                    break
                else:
                    print("[!] Timeout sem FIN, tentando esperar mais 2s...")
                    sock.settimeout(2.0)
                    try:
                        data, addr = sock.recvfrom(RECV_BUF)
                    except socket.timeout:
                        break
            # Process data
            try:
                text = data.decode(errors="ignore")
            except:
                text = ""
            if text.startswith("ERR"):
                print("[SERVER ERROR] " + text)
                break
            if text.startswith("FIN"):
                parts_fin = text.split()
                if len(parts_fin) >= 2:
                    try:
                        expected_total = int(parts_fin[1])
                        got_fin = True
                        print(f"[+] Recebeu FIN. total={expected_total}")
                    except:
                        pass
                else:
                    got_fin = True
                continue
            if text.strip() == "RETR_DONE":
                continue

            parsed = parse_header_and_payload(data)
            if parsed is None:
                continue
            seq, total, payload_len, crc, payload = parsed

            # apply simulated drops ONLY during the initial GET receive phase
            if in_get_phase and seq in drop_list:
                print(f"[SIM DROP] descartando segmento {seq} (simulado).")
                continue

            calc_crc = binascii.crc32(payload) & 0xffffffff
            ok = (calc_crc == crc)
            if not ok:
                print(f"[!] CRC mismatch seq {seq} (calc {calc_crc} != hdr {crc})")

            segments[seq] = payload
            crc_ok[seq] = ok
            expected_total = total

            if got_fin and expected_total is not None and len(segments) >= expected_total:
                break

        # After receive round: evaluate missing / corrupt
        # stop simulating drops from now on (so RETR receives aren't dropped)
        in_get_phase = False

        if expected_total is None:
            print("[!] Nao recebeu FIN; abortando tentativa.")
            continue

        missing = [i for i in range(1, expected_total+1) if i not in segments]
        corrupt = [i for i, ok in crc_ok.items() if not ok]
        for c in corrupt:
            if c not in missing:
                missing.append(c)
        missing.sort()
        print(f"[+] Round result: received {len(segments)} / {expected_total} segments. missing/corrupt: {missing}")

        # If no missing or corrupt -> assemble file
        if not missing:
            outpath = os.path.join(".", f"Copy_{filename}")
            with open(outpath, "wb") as out:
                for i in range(1, expected_total+1):
                    out.write(segments[i])
            print(f"[OK] Arquivo reconstruido: {outpath}")
            continue

        # else: ask user whether to request retransmission
        while True:
            user = input(f"Digite 'RETR x,y,z', 'RETR all', 'status' ou 'quit': ").strip()
            if not user:
                continue
            if user.lower() == "status":
                print(f"missing: {missing}")
                continue
            if user.lower() == "quit":
                print("Cancelando operacao.")
                break
            if user.upper().startswith("RETR"):
                partsr = user.split()
                if len(partsr) < 2:
                    print("Uso: RETR 3,7,12 | RETR all | RETR filename 3,7,12")
                    continue

                # special "all" option: request all missing/corrupt
                if partsr[1].lower() == "all":
                    if not missing:
                        print("[+] Nenhum segmento faltando — nada a retransmitir.")
                        continue
                    seqs = ",".join(str(x) for x in missing)
                    msg = f"RETR {filename} {seqs}"
                elif len(partsr) == 2 and "," in partsr[1]:
                    seqs = partsr[1]
                    msg = f"RETR {filename} {seqs}"
                elif len(partsr) >= 3:
                    msg = f"RETR {partsr[1]} {partsr[2]}"
                else:
                    seqs = " ".join(partsr[1:])
                    msg = f"RETR {filename} {seqs}"

                # Ensure we are NOT applying simulated drops during retransmission
                in_get_phase = False

                sock.sendto(msg.encode(), server_addr)
                print(f"[+] Enviado: {msg}. Aguardando retransmissao...")
                sock.settimeout(TIMEOUT)

                while True:
                    try:
                        data, addr = sock.recvfrom(RECV_BUF)
                    except socket.timeout:
                        print("[!] Timeout aguardando retransmissao.")
                        break
                    try:
                        text = data.decode(errors="ignore")
                    except:
                        text = ""
                    if text == "RETR_DONE":
                        print("[+] Servidor finalizou retransmissao desta rodada.")
                        break
                    if text.startswith("ERR"):
                        print("[SERVER ERROR] " + text)
                        break
                    parsed = parse_header_and_payload(data)
                    if parsed is None:
                        continue
                    seq, total, payload_len, crc, payload = parsed

                    # IMPORTANT: do NOT simulate drops here — accept retransmissions normally
                    calc_crc = binascii.crc32(payload) & 0xffffffff
                    ok = (calc_crc == crc)
                    if not ok:
                        print(f"[!] CRC mismatch on retransmit seq {seq}")
                    segments[seq] = payload
                    crc_ok[seq] = ok

                missing = [i for i in range(1, expected_total+1) if i not in segments]
                corrupt = [i for i, ok in crc_ok.items() if not ok]
                for c in corrupt:
                    if c not in missing:
                        missing.append(c)
                missing.sort()
                print(f"[+] Depois do RETR: faltando {len(missing)} segmentos: {missing}")
                if not missing:
                    outpath = os.path.join(".", f"Copy_{filename}")
                    with open(outpath, "wb") as out:
                        for i in range(1, expected_total+1):
                            out.write(segments[i])
                    print(f"[OK] Arquivo reconstruido: {outpath}")
                    break
                else:
                    continue
            else:
                print("Comando nao reconhecido. Use RETR, status ou quit.")
        # loop back to allow new GET


if __name__ == "__main__":
    main()
