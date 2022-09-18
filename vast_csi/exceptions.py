class Abort(Exception):

    @property
    def code(self):
        return self.args[0]

    @property
    def message(self):
        return self.args[1]
