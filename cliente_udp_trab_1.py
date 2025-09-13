from socket import *

serverPort = 12000
serverName = '127.0.0.1'

clientSocket = socket(AF_INET, SOCK_DGRAM)

while True:
    message = input("Message: ")
    clientSocket.sendto(message.encode(), (serverName, serverPort))

    arquivo, serverAddress = clientSocket.recvfrom(2048)

    print(arquivo.decode())


    clientSocket.close()