from socket import *

serverPort = 12000
serverName = '127.0.0.1'

clientSocket = socket(AF_INET, SOCK_DGRAM)

message = input("Message: ")
clientSocket.sendto(message.encode(), (serverName, serverPort))

modifiedMessage, serverAddress = clientSocket.recvfrom(2048)

print(modifiedMessage.decode())
print(serverAddress)
clientSocket.close()