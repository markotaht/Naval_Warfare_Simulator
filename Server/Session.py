import pika, threading, time, traceback, sys

from commons import createRPCListener
from types import MethodType
from Player import Player

#TODO: Make shared with Board.py
TILE_EMPTY = 0
TILE_SHIP = 1
TILE_MISS = 2
TILE_SHIP_HIT = 3

class Session(threading.Thread):
    def __init__(self, server, sessionName, hostName, boardWidth):
        threading.Thread.__init__(self)
        self.server = server
        self.name = sessionName
        self.hostName = hostName
        self.prefix = server.name +"." + sessionName
        self.lock = threading.Lock()
        self.updateChannel = None
        #TODO: Not really used?
        self.connections = []

        self.players = {}
        self.order = []
        self.boardWidth = boardWidth
        self.shipCount = self.getShipCount(boardWidth)
        self.dead = []
        self.state = "INIT"
        self.playerturn = 0
        self.shots = 0

        self.shouldDie = False;

        self.initChannels()


    def kill(self):
        for i in self.connections:
            try:
                i.close()
            except:
                print "Failed to close a connection"


    def tryAddPlayer(self, name):
        with self.lock:
            if name in self.players and self.players[name].connected == True:
                return False
            else:
                self.updateChannel.basic_publish(exchange=self.prefix + 'updates', routing_key='',
                                                     body="NEWPLAYER:%s" % name)

                board = [[0 for i in range(self.boardWidth)] for j in range(self.boardWidth)]
                isHost = name == self.hostName
                keepAliveTime = time.time()


                player = Player()
                player.init(name, isHost, False, keepAliveTime, board, self.shipCount)
                self.players[name] = player
                self.order.append(name)

                #Create bombing boards
                for otherPlayer in self.players.keys():
                    if otherPlayer != name:
                        #Create a bombing board for other players to attack the joined player
                        self.players[otherPlayer].otherBoards[name] = [[0 for i in range(self.boardWidth)] for j in range(self.boardWidth)]
                        #Create a bombing board for the joined player to attack other players
                        self.players[name].otherBoards[otherPlayer] = [[0 for i in range(self.boardWidth)] for j in range(self.boardWidth)]

                return True


    def run(self):
        while 1:
            if self.shouldDie:
                self.server.killSession(self.name)
                return
            #Check keepalive values for players and mark players as not ready if it is 20 seconds old
            for playerName in self.players:
                player = self.players[playerName]
                if player != 0:
                    if float(player.keepAliveTime) + 6 < float(time.time()):
                        if player.connected:
                            print "Old keepalive for player", player.keepAliveTime
                            print "Marking player as disconnected"
                            #TODO: Pick a new host
                            player.connected = False

                            #TODO: send the player "TIMEDOUT" so if the player receives it, he can be put to main menu and stop listening

                            self.updateChannel.basic_publish(exchange=self.prefix + 'updates',
                                                             routing_key='',
                                                             body="DISCONNECTED:%s" % playerName)

                            if self.order[self.playerturn] == playerName:
                                print "Skipping disconnected player"
                                # Was this players turn, skip him
                                self.notifyNextPlayer()

                            if self.hostName == playerName:
                                if len(self.players) > 0:
                                    # Set a new host
                                    self.hostName = self.players.keys()[0]
                                    self.updateChannel.basic_publish(exchange=self.prefix + 'updates', routing_key='',
                                                                     body="NEWHOST:" + self.hostName)
                                else:
                                    # Tag session to be closed
                                    self.shouldDie = True

            time.sleep(1) #check only every second

    def initChannels(self):
        with self.lock:
            self.updateConnection = pika.BlockingConnection(pika.ConnectionParameters(host='localhost'))
            self.updateChannel = self.updateConnection.channel()
            self.updateChannel.exchange_declare(exchange=self.prefix + 'updates',type='fanout')
            self.connections.append(self.updateConnection)

            self.kickPlayerListener = MethodType(createRPCListener(self, 'rpc_kick_player', self.kickPlayerCallback), self, Session)
            self.kickPlayer = threading.Thread(target=self.kickPlayerListener)
            self.kickPlayer.start()

            self.bombShipListener = MethodType(createRPCListener(self,'rpc_bomb',self.bombShipCallback), self, Session)
            self.bombship = threading.Thread(target=self.bombShipListener)
            self.bombship.start()

            self.gameStartListener = MethodType(createRPCListener(self,'rpc_start',self.gameStartCallback), self, Session)
            self.gamestart = threading.Thread(target=self.gameStartListener)
            self.gamestart.start()

            self.gameRestartListener = MethodType(createRPCListener(self, 'rpc_restart', self.gameRestartCallback), self, Session)
            self.gameRestart = threading.Thread(target=self.gameRestartListener)
            self.gameRestart.start()

            self.finishedPlacingListener = MethodType(createRPCListener(self,'rpc_finished_placing',self.finishedPlacingCallback, True), self, Session)
            self.finishedPlacing = threading.Thread(target=self.finishedPlacingListener)
            self.finishedPlacing.start()

            self.keepAliveListener = MethodType(createRPCListener(self, 'rpc_update_keep_alive', self.updateKeepAlive), self, Session)
            self.keepAliveListener = threading.Thread(target = self.keepAliveListener)
            self.keepAliveListener.start()

            self.leaveListener = MethodType(createRPCListener(self,'rpc_leave',self.leaveCallback,True),self,Session)
            self.leave = threading.Thread(target=self.leaveListener)
            self.leave.start()

            self.disconnectListener = MethodType(createRPCListener(self,'rpc_disconnect',self.disconnectCallback,True),self,Session)
            self.disconnect = threading.Thread(target=self.disconnectListener)
            self.disconnect.start()

            self.runThread = threading.Thread(target = self.run)
            self.runThread.start()

    def disconnectCallback(self, request):
        self.players[request].connected = False

        self.updateChannel.basic_publish(exchange=self.prefix + 'updates',
                                         routing_key='',
                                         body="DISCONNECTED:%s" % request)

        if self.order[self.playerturn] == request:
            print "Skipping disconnected player"
            #Was this players turn, skip him
            self.notifyNextPlayer()


        if self.hostName == request:
            if len(self.players) > 0:
                # Set a new host
                self.hostName = self.players.keys()[0]
                self.updateChannel.basic_publish(exchange=self.prefix + 'updates', routing_key='',
                                                 body="NEWHOST:" + self.hostName)
            else:
                # Tag session to be closed
                self.shouldDie = True

        return "OK", ""

    def gameRestartCallback(self, request):
        print "Restarting the session"

        oldPlayers = self.players

        self.state = "INIT"
        self.players = { }
        self.order = []
        self.dead = []
        self.playerturn = 0
        self.shots = 0

        for oldPlayer in oldPlayers:
            self.tryAddPlayer(oldPlayer)

        #The global argument doesnt seem to be working, so...
        self.updateChannel.basic_publish(exchange=self.prefix + 'updates',
                                         routing_key='',
                                         body="RESTARTING")
        return "OK", ""

    def leaveCallback(self,request):
        print("[.] player %s left" % request)
        #The global argument doesnt seem to be working, so...
        self.updateChannel.basic_publish(exchange=self.prefix + 'updates',
                                         routing_key='',
                                         body="LEFT:"+request)

        if self.order[self.playerturn] == request:
            print "Skipping left player"
            #Was this players turn, skip him
            self.notifyNextPlayer()


        if self.hostName == request:
            if len(self.players) > 0:
                #Set a new host
                self.hostName = self.players.keys()[0]
                self.updateChannel.basic_publish(exchange=self.prefix + 'updates', routing_key='',
                                             body="NEWHOST:" + self.hostName)
            else:
                #Tag session to be closed
                self.shouldDie = True

        # remove player from player list and turn list
        # update shots also
        if self.order.index(request) <= self.playerturn:
            self.playerturn -= 1
        if request in self.order:
            self.order.remove(request)
        if request in self.players:
            self.players.pop(request, None)

        self.shots -= 1

        return "OK",""

        return
    def kickPlayerCallback(self, request):
        print(" [.] kickPlayer(%s)" % request)

        #The global argument doesnt seem to be working, so...
        self.updateChannel.basic_publish(exchange=self.prefix + 'updates',
                                         routing_key='',
                                         body="LEFT:"+request)

        if self.order[self.playerturn] == request:
            print "Skipping left player"
            #Was this players turn, skip him
            self.notifyNextPlayer()


        if self.hostName == request:
            if len(self.players) > 0:
                #Set a new host
                self.hostName = self.players.keys()[0]
                self.updateChannel.basic_publish(exchange=self.prefix + 'updates', routing_key='',
                                             body="NEWHOST:" + self.hostName)
            else:
                # Tag session to be closed
                self.shouldDie = True

        # remove player from player list and turn list
        # update shots also
        if self.order.index(request) <= self.playerturn:
            self.playerturn -= 1
        if request in self.order:
            self.order.remove(request)
        if request in self.players:
            self.players.pop(request, None)

        self.shots -= 1

        return "OK", ""

    def finishedPlacingCallback(self,request):
        print( "[S] finishedPlacingCallback(%s)" % request)
        name, ships = request.split(':')

        success = self.placeShips(name, ships.split("|"))
        if success:
            self.players[name].isReady = True
            print "Session - %s is ready"%name
            return "OK", "READY:" + name
        else:
            return "FAIL", ""

    def placeShips(self, name, ships):
        print(ships)
        try:
            board = self.players[name].board

            for ship in ships:
                ship = ship.split(";")
                tileX = int(ship[0])
                tileY = int(ship[1])
                vertical = False if ship[2] == "False" else True
                shipSize = int(ship[3])

                if vertical == False:
                    if tileX > self.boardWidth - shipSize:
                        return False

                    # Check if the area around the ship is free
                    for x in range(tileX - 1, tileX + shipSize + 1):
                        for y in range(tileY - 1, tileY + 2):
                            if x < 0 or y < 0 or x >= self.boardWidth or y >= self.boardWidth:
                                # Out of range, can skip these tiles
                                continue
                            if board[x][y] != TILE_EMPTY:
                                return False

                    # If this is reached, can place the ship
                    for i in range(tileX, tileX + shipSize):
                        board[i][tileY] = TILE_SHIP
                else:
                    if tileY > self.boardWidth - shipSize:
                        # The ship would be out of bounds
                        return False

                    # Check if the area around the ship is free
                    for x in range(tileX - 1, tileX + 2):
                        for y in range(tileY - 1, tileY + + shipSize + 1):
                            if x < 0 or y < 0 or x >= self.boardWidth or y >= self.boardWidth:
                                # Out of range, can skip these tiles
                                continue
                            if board[x][y] != TILE_EMPTY:
                                return False

                    # If this is reached, can place the ship
                    for i in range(tileY, tileY + shipSize):
                        board[tileX][i] = TILE_SHIP


        except ValueError:
            traceback.print_exc(file=sys.stdout)
            return False
        except KeyError:
            traceback.print_exc(file=sys.stdout)
            return False

        return True


    def checkHit(self, x, y, victim, attacker):
        if self.players[victim].board[x][y] == TILE_SHIP:
            self.players[victim].board[x][y] = TILE_SHIP_HIT
            self.players[attacker].otherBoards[victim][x][y] = TILE_SHIP_HIT
            return "HIT"
        else:
            self.players[victim].board[x][y] = TILE_MISS
            self.players[attacker].otherBoards[victim][x][y] = TILE_MISS
            return "MISS"

    def checkSunk(self, x, y, victim):
        victimBoard = self.players[victim].board

        #check if ship on x+
        for i in range(x+1, self.boardWidth):
            if victimBoard[i][y] == TILE_SHIP:
                return False #Return false if we find ship
            elif victimBoard[i][y] == TILE_EMPTY:
                break #dont continue if nothing there

        for i in range(x-1, -1, -1):
            if victimBoard[i][y] == TILE_SHIP:
                return False
            elif victimBoard[i][y] == TILE_EMPTY:
                break


        for i in range(y+1, self.boardWidth):
            if victimBoard[x][i] == TILE_SHIP:
                return False
            elif victimBoard[x][i] == TILE_EMPTY:
                break

        for i in range(y-1, -1, -1):
            if victimBoard[x][i] == TILE_SHIP:
                return False
            elif victimBoard[x][i] == TILE_EMPTY:
                break

        return True

    def updateOtherBoards(self,shiphit, shipmiss, victim):
        for player in self.players:
            if player != victim:
                tmpBoard = self.players[player].otherBoards[victim]
                for i in shiphit:
                    tmpBoard[i[0]][i[1]] = TILE_SHIP_HIT
                for i in shipmiss:
                    tmpBoard[i[0]][i[1]] = TILE_MISS

    def getSunkDetails(self,x,y,player):
        tmpBoard = self.players[player].board
        shiphit = []#tuples of coords (x,y),board = 3
        shipmiss = []#tuples of coors(x,y), board = 2

        #can add x,y as they sunk the ship
        shiphit.append((x,y))

        #check all directions for hits and create shiphit
        for i in range(x + 1, self.boardWidth):
            if tmpBoard[i][y] == TILE_SHIP_HIT:
                shiphit.append((i,y))
            else:
                break

        for i in range(x - 1, -1, -1):
            if tmpBoard[i][y] == TILE_SHIP_HIT:
                shiphit.append((i,y))
            else:
                break

        for i in range(y + 1, self.boardWidth):
            if tmpBoard[x][i] == 3:
                shiphit.append((x,i))
            else:
                break

        for i in range(y - 1, -1, -1):
            if tmpBoard[x][i] == 3:
                shiphit.append((x,i))
            else:
                break

        #Iterate around each shiphit element and mark misses around them
        for j in shiphit:
            x = int(j[0])
            y = int(j[1])
            #print x,y
            #print self.boardWidth

            #Check the 8 directions to see if they should be marked with dots
            if x > 0 and tmpBoard[x - 1][y] == TILE_EMPTY:
                tmpBoard[x - 1][y] = TILE_MISS
                shipmiss.append((x-1, y))

            if x + 1 < self.boardWidth and tmpBoard[x + 1][y] == TILE_EMPTY:
                tmpBoard[x + 1][y] = TILE_MISS
                shipmiss.append((x+1, y))

            if y > 0 and tmpBoard[x][y - 1] == TILE_EMPTY:
                tmpBoard[x][y - 1] = TILE_MISS
                shipmiss.append((x, y - 1))

            if y + 1 < self.boardWidth and tmpBoard[x][y + 1] == TILE_EMPTY:
                tmpBoard[x][y + 1] = TILE_MISS
                shipmiss.append((x, y + 1))

            #The diagonals
            if x > 0 and y + 1 < self.boardWidth and tmpBoard[x - 1][y + 1] == TILE_EMPTY:
                tmpBoard[x - 1][y + 1] = TILE_MISS
                shipmiss.append((x - 1, y + 1))

            if x > 0 and y > 0 and tmpBoard[x - 1][y - 1] == TILE_EMPTY:
                tmpBoard[x - 1][y - 1] = TILE_MISS
                shipmiss.append((x - 1, y - 1))

            if x + 1 < self.boardWidth and y + 1 < self.boardWidth and tmpBoard[x + 1][y + 1] == TILE_EMPTY:
                tmpBoard[x + 1][y + 1] = TILE_MISS
                shipmiss.append((x + 1, y + 1))

            if x + 1 < self.boardWidth and y > 0 and tmpBoard[x + 1][y - 1] == TILE_EMPTY:
                tmpBoard[x + 1][y - 1] = TILE_MISS
                shipmiss.append((x + 1, y - 1))

        return list(set(shiphit)), list(set(shipmiss))

    def bombShipCallback(self,request):
        x, y, victim, attacker = request.split(":")

        print(" [.] bomb(%s,%s, %s, %s)" %(x,y,victim, attacker))
        response = self.checkHit(int(x),int(y),victim, attacker)

        if response == "MISS":
            self.shots -= 1

        if response == "HIT" and self.checkSunk(int(x),int(y),victim):
            hitcoords, misscoords = self.getSunkDetails(int(x),int(y),victim)
            self.updateOtherBoards(hitcoords, misscoords, victim)
            #pack for sending into x1;y1, x2;y2...
            hitcoords = ",".join([str(a[0])+";"+str(a[1]) for a in hitcoords])
            misscoords = ",".join([str(a[0])+";"+str(a[1]) for a in misscoords])
            #update all boards for dc stuff
            message = ":".join(["SUNK",victim, attacker,x,y, str(hitcoords), str(misscoords)])

            #update player's ship count
            #but allow to continue if they enemy has ships left
            if self.players[victim].shipsRemaining != 1:
                self.players[victim].shipsRemaining -= 1
            else:
                self.players[victim].shipsRemaining = 0
                self.killPlayer(victim, attacker)
                self.shots -= 1
                print "shots remaining", self.shots
                print "%s is dead"%victim
                #TODO update also player that he is dead
            response = "SUNK"
        else:
            message = ":".join(["BOMB",victim,attacker,x,y,response])

        #TODO this should be sent by the super global message thing
        self.updateChannel.basic_publish(exchange=self.prefix + 'updates',
                                         routing_key='',
                                         body=message)

        #also notify dead players
        #send SPECTATOR:victim:boarddata
        boardData = ""
        for x in range(0, self.boardWidth):
            for y in range(0, self.boardWidth):
                boardData += str(self.players[victim].board[x][y])

        self.updateChannel.basic_publish(exchange=self.prefix + 'updates',
                                         routing_key='',
                                         body="SPECTATOR:"+str(victim)+":"+boardData)

        print "SERVER - message:", message
        print "Shots remaining:", self.shots
        if self.shots <= 0:
            self.notifyNextPlayer()

        return response, message

    def notifyNextPlayer(self):
        if len(self.order) == 0:
            return
        elif len(self.order) == 1 and self.playerturn == 1:
            self.playerturn = 0

        self.playerturn = (self.playerturn+1)%len(self.order)

        message = ":".join(["NEXT",self.order[self.playerturn]])
        self.updateChannel.basic_publish(exchange=self.prefix + 'updates',
                                         routing_key='',
                                         body=message)
        self.shots = len(self.order)-1
        print "%s's turn"%self.order[self.playerturn]

    def gameStartCallback(self,request):
        #TODO: Possibly validate if the request sender is the host
        print("Starting the game")
        if self.state == "INIT":
            self.state = "PLAY"
            #set number of shots
            self.shots = len(self.order)-1

            self.updateChannel.basic_publish(exchange=self.prefix + 'updates',
                                             routing_key='',
                                             body="START")
            #Also notify that host is first
            message = ":".join(["NEXT", self.order[0]])
            print ""
            self.updateChannel.basic_publish(exchange=self.prefix + 'updates',
                                             routing_key='',
                                             body=message)
            print "%s's turn" % self.order[self.playerturn]

            return "OK",""
        else:
            return "FAIL",""

    def updateKeepAlive(self,request):
        name, keepalive = request.split(":")
        keepalive = float(keepalive)
        if name in self.players:
            self.players[name].keepAliveTime = keepalive
        #print "New keepalive:", name
        #TODO check why it fails with OK
        #fails with ok as it does not contain :, dno why
        return "O:K", ""

    def getShipCount(self, boardWidth):
        if boardWidth == 4 or boardWidth == 6:
            return 4
        elif boardWidth == 8:
            return 7
        elif boardWidth == 10:
            return 11
        elif boardWidth == 12:
            return 16
        else:
            print "Warning! Unsupported board size."

    def checkWin(self):
        if len(self.order) == 1:
            print "%s WON!"%self.order[0]
            self.updateChannel.basic_publish(exchange=self.prefix + 'updates',
                                             routing_key='',
                                             body="OVER:"+self.order[0])
            self.state = "OVER"

    def killPlayer(self, player, killer):
        self.players[player].shipsRemaining = 0
        self.players[player].isAlive = False
        self.order.remove(player)
        self.dead.append(player)
        print "%s is dead"%player
        self.updateChannel.basic_publish(exchange=self.prefix + 'updates',
                                         routing_key='',
                                         body="DEAD:" + player + ":" + killer)


        #After the player has died, immediately also publish all the spectator data so the dead player can get full states
        #send SPECTATOR:victim:boarddata
        for otherPlayer in self.players:
            if otherPlayer == player:
                continue
            boardData = ""
            for x in range(0, self.boardWidth):
                for y in range(0, self.boardWidth):
                    boardData += str(self.players[otherPlayer].board[x][y])

            self.updateChannel.basic_publish(exchange=self.prefix + 'updates',
                                             routing_key='',
                                             body="SPECTATOR:"+str(otherPlayer)+":"+boardData)

        self.checkWin()