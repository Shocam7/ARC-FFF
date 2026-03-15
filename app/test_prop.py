from PyQt6.QtCore import QObject

class Test(QObject):
    @property
    def connection_state(self):
        return 'foo'

t = Test()
print(t.connection_state)
