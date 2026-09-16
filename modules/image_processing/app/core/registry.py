class Registry:
    def __init__(self):
        self._registry = {}

    def register(self, key, item):
        self._registry[key] = item

    def get(self, key):
        return self._registry.get(key)
