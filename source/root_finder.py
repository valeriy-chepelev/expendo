import logging
class TreeCache:

    def __init__(self):
        self.scanned = dict()

    def root(self, key):
        return self.scanned[key] if key in self.scanned else None

    @property
    def roots(self):
        return self.scanned

    def add(self, item):
        stack = [item.key]  # Stack of items chain from 'item'
        s = None
        while ((p := item.parent) is not None and
               (s := self.root(item.key)) is None):  # iterate wile we found original parent or already scanned item
            stack.append(item.key)  # add item data to stack
            item = p  # move to a parent
        # add stack to scanned list with root data from already scanned item or from original parent
        if s is None:
            s = (item.key, item.summary) if item.type.key == 'epic' else ('0', 'NoEpic')
        self.scanned.update({key: s for key in stack})
