from Assets import *
from Util import *
from external import eztext


class NewSessionScreen:

    def init(self, ui, windowSurface):
        self.ui = ui
        self.windowSurface = windowSurface
        #TODO: Move fonts to Assets
        self.tinyFont = pygame.font.SysFont(None, 18)
        self.smallFont = pygame.font.SysFont(None, 24)
        self.mediumFont = pygame.font.SysFont(None, 36)
        self.largeFont = pygame.font.SysFont(None, 48)

        self._availableSizes = [8, 10, 12]


    def update(self, events):

        if escapePressed(events):
            self.ui.loadSessionSelectScreen()

        #NEW SESSION
        newSessionText = self.largeFont.render("Creating a new session", True, COLOR_BLACK)
        newSessionTextRect = newSessionText.get_rect()
        newSessionTextRect.left = 40
        newSessionTextRect.top = 40
        newSessionRect = self.windowSurface.blit(newSessionText, newSessionTextRect)

        #EXISTING SESSIONS
        sizeText = self.mediumFont.render("Choose board size:", True, COLOR_BLACK)
        sizeTextRect = sizeText.get_rect()
        sizeTextRect.left = 40
        sizeTextRect.top = 150
        self.windowSurface.blit(sizeText, sizeTextRect)

        x = 100
        for size in self._availableSizes:
            sizeText = self.mediumFont.render(str(size) + "x" + str(size), True, COLOR_WHITE, COLOR_BLACK)
            sizeTextRect = sizeText.get_rect()
            sizeTextRect.centerx = x
            sizeTextRect.centery = 200
            x += 100

            sizeRect = self.windowSurface.blit(sizeText, sizeTextRect)

            if clickedOnRect(sizeRect, events):
                print "Clicked on " + str(size) + " size"
                # TODO: Create new session with the given size
                self.ui.loadSetupShipsScreen(size)
